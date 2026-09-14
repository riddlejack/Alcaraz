"""Bind a completed SR02 point run, fit market procedures and score outputs.

Ported from the archive's ``references/SR02_models/runner.py`` (SR02-C1 revision). What
changed: the repository root computed from the source file is gone and every configured
path resolves through the declared workspace; the ``market_execution.files`` inventory
is split into *data* bindings, verified by hash, and *code* bindings (``*.py``), which
are recorded as ``declared_binding`` while the package modules run (porting guide rule
2); errors are :class:`~tennislab.dynamics.dynamic.DynamicsError`.

This program scores outcomes: ``load`` reads ``a_won`` for every selected match and
``evaluate``/``comparison``/``reliability`` compute proper scores on them, including
the outer target years. Every such read is marked ``# outcome-history read`` so the
integration pass can move scoring behind the report barrier.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

from tennislab.chain.common import code_receipt, relative_to_root, resolve_under_root, sha256
from tennislab.dynamics import market, protocol
from tennislab.dynamics.dynamic import DynamicsError

sha = sha256


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def write_csv(path, rows):
    if not rows:
        raise DynamicsError("Refusing empty artifact: " + str(path))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def boolean(value):
    if value not in ("true", "false"):
        raise DynamicsError("Invalid literal boolean")
    return value == "true"


def load(panel_path, point_path):
    source = read_csv(panel_path)
    panel = {r["match_id"]: r for r in source}
    points = read_csv(point_path)
    ids = {r["match_id"] for r in points}
    expected = {r["match_id"] for r in source if 2011 <= int(r["match_date"][:4]) <= 2024}
    if len(panel) != len(source) or len(ids) != len(points) or ids != expected:
        raise DynamicsError("Selected point-run identity coverage differs")
    result = []
    for prediction in points:
        row = panel[prediction["match_id"]]
        for field in (
            "match_id",
            "source_key",
            "source_season",
            "match_date",
            "tourney_id",
            "surface",
            "best_of",
            "player_a",
            "player_b",
        ):
            if prediction[field] != row[field]:
                raise DynamicsError("Point/source identity or metadata differs: " + field)
        if prediction["rule_status"] != "provided":
            raise DynamicsError("Selected match lacks an explicit rule")
        item = {**row, **prediction}
        for field in ("PS_valid", "completed", "source_field_agreement"):
            item[field] = boolean(row[field])
        item["a_won"] = int(boolean(row["a_won"]))  # outcome-history read: every selected match
        item["q"] = None
        if item["PS_valid"]:
            a, b = float(row["PS_decimal_a"]), float(row["PS_decimal_b"])
            if not np.isfinite([a, b]).all() or a <= 1 or b <= 1:
                raise DynamicsError("Invalid marked Pinnacle pair")
            item["q"] = (1 / a) / (1 / a + 1 / b)
        for family in ("dynamic", "unadjusted", "simple_unadjusted"):
            field = family + "_match_probability_a"
            item[field] = float(prediction[field])
            market.probabilities([item[field]])
        roles = ("a_serve", "a_return", "b_serve", "b_return")
        if any("dynamic_" + role + "_unseen" not in prediction for role in roles):
            item["history_support"] = "unavailable"
        elif any(int(prediction["dynamic_" + role + "_unseen"]) for role in roles):
            item["history_support"] = "unseen_role"
        elif (
            min(int(prediction["dynamic_" + role + "_point_observations"]) for role in roles) < 500
        ):
            item["history_support"] = "under_500_observed_points_in_a_role"
        else:
            item["history_support"] = "at_least_500_points_in_each_role"
        result.append(item)
    return result


def cohort(row, name):
    primary = row["identity_tier"] == "primary"
    return {
        "primary": primary,
        "completed_only": primary and row["completed"],
        "source_agreement": primary and row["source_field_agreement"],
        "provisional_extension": True,
    }[name]


def reliability(rows, field, scope):
    groups = defaultdict(list)
    for row in rows:
        groups[min(int(float(row[field]) * 10), 9)].append(row)
    return [
        {
            "scope": scope,
            "model": field,
            "bin": b,
            "n": len(items),
            "mean_prediction": float(np.mean([r[field] for r in items])),
            "outcome_rate": float(np.mean([r["a_won"] for r in items])),  # outcome-history read
        }
        for b, items in sorted(groups.items())
    ]


def comparison(rows, treatment, control, seed=20260911, repetitions=2000):
    years = sorted({int(r["match_date"][:4]) for r in rows})
    annual, groups = [], []
    pooled_sum = 0.0
    for year in years:
        yearly = [r for r in rows if int(r["match_date"][:4]) == year]
        clusters = defaultdict(lambda: [0.0, 0])
        for row in yearly:
            y = row["a_won"]  # outcome-history read: paired log-loss difference
            a = market.probabilities([row[treatment]])[0]
            b = market.probabilities([row[control]])[0]
            delta = -y * np.log(a / b) - (1 - y) * np.log((1 - a) / (1 - b))
            clusters[row["tourney_id"]][0] += float(delta)
            clusters[row["tourney_id"]][1] += 1
        total = sum(v[0] for v in clusters.values())
        pooled_sum += total
        annual.append(
            {
                "year": year,
                "n": len(yearly),
                "event_editions": len(clusters),
                "delta": total / len(yearly),
            }
        )
        groups.append(np.array(list(clusters.values()), dtype=float))
    deltas = np.array([r["delta"] for r in annual])
    center = float(np.mean(deltas))
    error = (
        float(stats.t.ppf(0.975, len(years) - 1) * np.std(deltas, ddof=1) / np.sqrt(len(years)))
        if len(years) > 1
        else None
    )
    rng = np.random.default_rng(seed)
    boot = np.zeros((repetitions, len(years)))
    for j, grouped in enumerate(groups):
        indices = rng.integers(len(grouped), size=(repetitions, len(grouped)))
        totals = grouped[indices].sum(axis=1)
        boot[:, j] = totals[:, 0] / totals[:, 1]
    return {
        "treatment": treatment,
        "control": control,
        "n": len(rows),
        "annual": annual,
        "equal_year_delta": center,
        "match_weighted_delta": pooled_sum / len(rows),
        "approximate_across_year_t95": [center - error, center + error]
        if error is not None
        else None,
        "fixed_fit_stratified_event_bootstrap95": np.quantile(
            boot.mean(axis=1), [0.025, 0.975]
        ).tolist(),
        "bootstrap_repetitions": repetitions,
        "bootstrap_seed": seed,
        "years_improving": int(sum(deltas < 0)),
        "years_tied_exactly": int(sum(deltas == 0)),
        "leave_2020_out_equal_year_delta": float(
            np.mean([r["delta"] for r in annual if r["year"] != 2020])
        ),
    }


def evaluate(rows, predictions):
    source = {r["match_id"]: r for r in rows}
    market_rows = [{**source[p["match_id"]], **p} for p in predictions]
    sports_rows = [
        r
        for r in rows
        if 2012 <= int(r["match_date"][:4]) <= 2024
        and int(r["source_season"]) == int(r["match_date"][:4])
    ]
    metrics, bins, comparisons = [], [], {}
    market_models = (
        "market_calibrated",
        "legacy_pinnacle_calibration",
        "dynamic_augmented",
        "unadjusted_augmented",
        "pinnacle_raw_normalized",
        "dynamic_match_probability_a",
        "unadjusted_match_probability_a",
    )
    sports_models = (
        "dynamic_match_probability_a",
        "unadjusted_match_probability_a",
        "simple_unadjusted_match_probability_a",
    )
    for scope, inputs, models in [
        ("market_2017_2024", market_rows, market_models),
        ("sports_2012_2024", sports_rows, sports_models),
    ]:
        for name in ("primary", "completed_only", "source_agreement", "provisional_extension"):
            population = [r for r in inputs if cohort(r, name)]
            for year in [None, *sorted({int(r["match_date"][:4]) for r in population})]:
                selected = [
                    r for r in population if year is None or int(r["match_date"][:4]) == year
                ]
                for model in models:
                    metrics.append(
                        {
                            "scope": scope,
                            "cohort": name,
                            "year": year if year is not None else "pooled",
                            "model": model,
                            **market.scores(
                                [r[model] for r in selected],
                                [r["a_won"] for r in selected],  # outcome-history read
                            ),
                        }
                    )
            if scope.startswith("market"):
                pairs = [
                    ("dynamic_augmented", "market_calibrated"),
                    ("unadjusted_augmented", "market_calibrated"),
                    ("dynamic_augmented", "legacy_pinnacle_calibration"),
                    ("market_calibrated", "legacy_pinnacle_calibration"),
                ]
            else:
                pairs = [("dynamic_match_probability_a", "unadjusted_match_probability_a")]
            for treatment, control in pairs:
                comparisons[f"{scope}/{name}/{treatment}_minus_{control}"] = comparison(
                    population, treatment, control
                )
        primary = [r for r in inputs if cohort(r, "primary")]
        for model in models:
            bins.extend(reliability(primary, model, scope))
        for dimension in ("surface", "best_of", "status", "history_support"):
            for value in sorted({str(r[dimension]) for r in primary}):
                selected = [r for r in primary if str(r[dimension]) == value]
                for model in models:
                    metrics.append(
                        {
                            "scope": scope,
                            "cohort": f"{dimension}={value}",
                            "year": "pooled",
                            "model": model,
                            **market.scores(
                                [r[model] for r in selected],
                                [r["a_won"] for r in selected],  # outcome-history read
                            ),
                        }
                    )
    return metrics, bins, comparisons


def split_bindings(records):
    """Code bindings (``*.py``) are declared provenance; everything else is data."""
    code = [dict(record) for record in records if str(record["path"]).endswith(".py")]
    data = [dict(record) for record in records if not str(record["path"]).endswith(".py")]
    return code, data


def run(config_path, point_dir, output):
    config_path = resolve_under_root(config_path, label="config")
    point_dir = resolve_under_root(point_dir, label="point_directory")
    output = resolve_under_root(output, label="output")
    config = json.loads(config_path.read_text())
    if config.get("proposal_status") != "frozen_for_real_execution":
        raise DynamicsError("Real execution requires frozen configuration")
    if config["market_execution"]["penalties"] != [None, 1.0, 0.1, 0.01, 0.001]:
        raise DynamicsError("Penalty grid differs from frozen procedure")
    declared_code, data_bindings = split_bindings(config["market_execution"]["files"])
    if not declared_code:
        raise DynamicsError("Incomplete market code bindings")
    for record in data_bindings:
        bound = resolve_under_root(record["path"], label="market binding")
        if sha(bound) != record["sha256"]:
            raise DynamicsError("Bound market source differs: " + record["path"])
    point_manifest = json.loads((point_dir / "run_manifest.json").read_text())
    point_path = point_dir / "selected_matches.csv"
    if (
        point_manifest["status"] != "complete"
        or point_manifest["config_sha256"] != sha(config_path)
        or point_manifest["panel_sha256"] != config["input"]["panel_sha256"]
        or point_manifest["selected_matches_sha256"] != sha(point_path)
    ):
        raise DynamicsError("Completed point stage does not match this frozen configuration")
    panel_path = resolve_under_root(config["input"]["panel_path"], label="panel")
    if sha(panel_path) != config["input"]["panel_sha256"]:
        raise DynamicsError("Panel changed")
    rows = load(panel_path, point_path)
    if len(rows) != point_manifest["selected_matches_rows"]:
        raise DynamicsError("Point manifest row count differs")
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "start.json",
        {
            "config_path": relative_to_root(config_path, label="config"),
            "config_sha256": sha(config_path),
            "point_manifest_sha256": sha(point_dir / "run_manifest.json"),
            "selected_matches_sha256": sha(point_path),
            "panel_sha256": sha(panel_path),
        },
    )

    def persist_fit_event(event):
        with (output / "fit_events.jsonl").open("a") as handle:
            handle.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")

    try:
        result = protocol.run(rows, record_sink=persist_fit_event)
    except Exception as exc:
        write_json(
            output / "failure.json",
            {
                "status": "failed",
                "config_sha256": sha(config_path),
                "point_manifest_sha256": sha(point_dir / "run_manifest.json"),
                "error": str(exc),
            },
        )
        raise
    legacy_binding = config["market_execution"]["legacy_market_predictions"]
    legacy_path = resolve_under_root(legacy_binding["path"], label="legacy_market_predictions")
    if sha(legacy_path) != legacy_binding["sha256"]:
        raise DynamicsError("Legacy pure-market forecasts changed")
    legacy_rows = read_csv(legacy_path)
    legacy = {(int(r["season"]), r["match_id"]): r for r in legacy_rows}
    if len(legacy) != len(legacy_rows):
        raise DynamicsError("Legacy predictions contain duplicate keys")
    for prediction in result["predictions"]:
        old = legacy[(prediction["year"], prediction["match_id"])]
        if (
            old["reported_match_date"] != prediction["match_date"]
            or abs(float(old["pinnacle_raw_normalized"]) - prediction["pinnacle_raw_normalized"])
            > 1e-12
        ):
            raise DynamicsError("Legacy market row basis differs")
        prediction["legacy_pinnacle_calibration"] = float(old["pinnacle_calibration_logistic"])
    write_csv(output / "predictions.csv", result["predictions"])
    write_json(output / "fits.json", result["fits"])
    write_json(output / "selections.json", result["selections"])
    write_json(
        output / "predictions_boundary.json",
        {
            "status": "forecasts_persisted_before_evaluation",
            "predictions_sha256": sha(output / "predictions.csv"),
            "limit": "Input bytes include exposed outcomes; past-only fit/selection controls information use, not holdout custody.",
        },
    )
    metrics, bins, comparisons = evaluate(rows, result["predictions"])
    write_csv(output / "metrics.csv", metrics)
    write_csv(output / "reliability.csv", bins)
    write_json(output / "comparisons.json", comparisons)
    clip_counts = {
        field: sum(
            0 < r[field] < market.CLIP or 1 - market.CLIP < r[field] < 1
            for r in rows
            if r[field] is not None
        )
        for field in ("q", "dynamic_match_probability_a", "unadjusted_match_probability_a")
    }
    write_json(
        output / "run_manifest.json",
        {
            "status": "complete",
            "config_sha256": sha(config_path),
            "fits": len(result["fits"]),
            "selections": len(result["selections"]),
            "predictions": len(result["predictions"]),
            "interior_probability_clip": market.CLIP,
            "interior_input_clip_counts": clip_counts,
            "code": {
                "runner": code_receipt(__name__),
                "market": code_receipt(market.__name__),
                "protocol": code_receipt(protocol.__name__),
                "declared_binding": declared_code,
            },
            "artifacts": {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "output": relative_to_root(output, label="output"),
                "predictions": len(result["predictions"]),
            }
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("point_directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    run(args.config, args.point_directory, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
