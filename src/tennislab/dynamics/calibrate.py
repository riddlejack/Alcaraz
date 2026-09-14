"""Stage ``sr03_calibration``: year-parameterised SR03 slope calibration of a point run,
and the post-barrier stage ``sr03_component`` that scores what it predicted.

Ported from the archive's ``references/TIER01_models/sr03_calibrate.py`` (base) with the
``references/WTA02_models/sr03_calibrate.py`` additions merged: the ``tour`` switch in
the panel-binding authority. The calibration core lives in
:mod:`tennislab.dynamics.calibration`; this module reads the config, derives the
:class:`~tennislab.dynamics.calibration.CalibrationWindow` from ``year_plan``, validates
the bindings, runs the fits and writes the stage directory.

Decision RB14 (Lane B2): the calibration stage is **forecast-only**. It writes fits,
slope receipts, training membership and ``predictions.csv`` for every outer year and
scores nothing; ``scoring_boundary.json`` says so and records the historical
``calibration.score_years_max`` value where a frozen config still carries one. The
component metrics the archive wrote here before the barrier (``metrics.csv``,
``reliability.csv``, ``comparisons.json``, ``cohort_counts.json``) are computed by
``calibrate evaluate`` in stage ``sr03_component`` after the report, from the persisted
predictions, with identical arithmetic.

Outcome reads. The fits read training outcomes through
:func:`calibration.panel_outcomes_for_fold` (one ``PanelOutcomeHistory`` per outer year,
ceiling = outer year − 1, cutoff = 30 December); ``evaluate`` reads the scored outcomes
through the same accessor with purpose ``component_scoring`` and no ceiling.

    python -m tennislab.dynamics.calibrate run <sr03 config> <stage dir>
    python -m tennislab.dynamics.calibrate evaluate <sr03 config> <calibration stage dir> <stage dir>
    python -m tennislab.dynamics.calibrate preflight <sr03 config>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    code_receipt,
    read_config,
    relative_to_root,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
)
from tennislab.dynamics import calibration, market, sr02_runner
from tennislab.dynamics.calibration import (
    FAMILIES,
    METRIC_FIELDS,
    PREDICTION_FIELDS,
    RELIABILITY_FIELDS,
    TRAINING_FIELDS,
    CalibrationWindow,
    read_csv,
    write_csv,
    write_json,
)

COMPONENT_FILES = ("metrics.csv", "reliability.csv", "comparisons.json", "cohort_counts.json")


def scoring_boundary(config: dict[str, Any], outer_years: list[int]) -> dict[str, Any]:
    """The receipt that nothing was scored here and every outer year is deferred."""
    section = config["calibration"]
    return {
        "outer_years_scored": [],
        "outer_years_deferred_to_sr03_component_stage": sorted(int(y) for y in outer_years),
        "historical_score_years_max": section.get("score_years_max"),
        "basis": "RB14: the calibration stage emits fits and predictions only; component "
        "metrics are computed after the report barrier by `calibrate evaluate`",
    }


def _load(config_path: Path) -> tuple[dict[str, Any], CalibrationWindow, dict[str, Any]]:
    config = read_config(config_path)
    window = CalibrationWindow.from_config(config)
    calibration.validate_config(config, require_frozen=True, window=window)
    manifest = calibration.validate_bindings(config, window=window)
    return config, window, manifest


def _refuse_nonempty(output: Path) -> None:
    # An empty pre-created directory is allowed (the chain driver creates the stage
    # directory first); a nonempty one is refused.
    if output.exists() and any(output.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)


def _source_hashes(config: dict[str, Any]) -> dict[str, str]:
    source = config["source"]
    return {
        "point_manifest_sha256": sha256(
            resolve_under_root(source["point_manifest_path"], label="point_manifest")
        ),
        "selected_matches_sha256": sha256(
            resolve_under_root(source["selected_matches_path"], label="selected_matches")
        ),
        "panel_sha256": sha256(resolve_under_root(source["panel_path"], label="panel")),
        "rule_mapping_sha256": sha256(
            resolve_under_root(source["rule_mapping_path"], label="rule_mapping")
        ),
    }


def run(config_path: Path, output: Path) -> dict[str, Any]:
    config_path = resolve_under_root(config_path, label="config")
    output = resolve_output_under_root(output, label="output")
    config, window, manifest = _load(config_path)
    _refuse_nonempty(output)
    start = {
        "experiment_id": config["experiment_id"],
        "config_path": relative_to_root(config_path, label="config"),
        "config_sha256": sha256(config_path),
        "point_manifest_sha256": config["source"]["point_manifest_sha256"],
        "selected_matches_sha256": config["source"]["selected_matches_sha256"],
        "panel_sha256": config["source"]["panel_sha256"],
        "design_sha256": config["source"]["design_sha256"],
    }
    write_json(output / "start.json", start)

    def event_sink(event: dict[str, object]) -> None:
        with (output / "fit_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")

    try:
        dataset = calibration.load_dataset(
            config, window=window, labels=True, exclude_without_rule=True
        )
        if dataset.refused_without_rule:
            print(
                json.dumps(
                    {
                        "rows_excluded_rule_status_not_provided": len(dataset.refused_without_rule),
                        "examples": sorted(dataset.refused_without_rule)[:10],
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
        outer_years = [int(year) for year in config["calibration"]["outer_years"]]
        predictions, fits, memberships = calibration.fit_and_predict(
            dataset.rows,
            calibration.panel_outcomes_for_fold(dataset),
            outer_years,
            window=window,
            event_sink=event_sink,
        )
        expected_fits = len(outer_years) * len(FAMILIES)
        if len(fits) != expected_fits:
            raise ChainError(f"scheduled fit count differs: {len(fits)} != {expected_fits}")
        write_csv(output / "training_membership.csv", memberships, TRAINING_FIELDS)
        write_json(output / "fits.json", fits)
        write_csv(output / "predictions.csv", predictions, PREDICTION_FIELDS)
        write_json(
            output / "predictions_boundary.json",
            {
                "status": "year_ahead_predictions_persisted_before_outer_scoring",
                "predictions_sha256": sha256(output / "predictions.csv"),
                "prediction_rows": len(predictions),
                "target_outcome_fields_in_prediction_artifact": [],
                "limit": "Input bytes contain exposed outcomes; chronology and separate label access enforce the developmental information boundary, not holdout custody.",
            },
        )
        write_json(output / "scoring_boundary.json", scoring_boundary(config, outer_years))
    except Exception as exc:
        write_json(output / "failure.json", {**start, "status": "failed", "error": str(exc)})
        raise

    files = sorted(path for path in output.iterdir() if path.is_file())
    document = {
        "status": "complete",
        "experiment_id": config["experiment_id"],
        "config_sha256": sha256(config_path),
        **_source_hashes(config),
        "source_point_rows": manifest["selected_matches_rows"],
        "fits": len(fits),
        "predictions": len(predictions),
        "scored": 0,
        "code": {
            "calibrate": code_receipt(__name__),
            "calibration": code_receipt(calibration.__name__),
            "market": code_receipt(market.__name__),
            "sr02_runner": code_receipt(sr02_runner.__name__),
            "declared_binding": manifest["declared_binding"],
        },
        "artifacts": {path.name: sha256(path) for path in files},
    }
    write_json(output / "run_manifest.json", document)
    print(
        json.dumps(
            {
                "status": "complete",
                "fits": len(fits),
                "predictions": len(predictions),
                "output": relative_to_root(output, label="output"),
            }
        )
    )
    return document


def evaluate(config_path: Path, calibration_dir: Path, output: Path) -> dict[str, Any]:
    """Stage ``sr03_component``: score the persisted predictions, after the barrier.

    The predictions are bound by the calibration stage's ``run_manifest.json``; the
    dataset is reloaded from the same panel and selected matches (hash-checked by the
    config bindings); the arithmetic is :func:`calibration.evaluate` unchanged.
    """
    config_path = resolve_under_root(config_path, label="config")
    calibration_dir = resolve_under_root(calibration_dir, label="calibration_dir")
    output = resolve_output_under_root(output, label="output")
    config, window, manifest = _load(config_path)
    run_manifest = read_config(calibration_dir / "run_manifest.json")
    if run_manifest.get("status") != "complete":
        raise ChainError("calibration stage did not complete")
    if run_manifest.get("config_sha256") != sha256(config_path):
        raise ChainError("calibration stage ran with a different config")
    predictions_path = calibration_dir / "predictions.csv"
    predictions_sha256 = sha256(predictions_path)
    if run_manifest["artifacts"].get("predictions.csv") != predictions_sha256:
        raise ChainError("persisted predictions differ from the calibration manifest")
    _refuse_nonempty(output)

    dataset = calibration.load_dataset(
        config, window=window, labels=True, exclude_without_rule=True
    )
    predictions = [
        {**row, "calibration_year": int(row["calibration_year"])}
        for row in read_csv(predictions_path)
    ]
    for row in predictions:
        for field in (
            *(f"raw_{f}" for f, _ in FAMILIES),
            *(f"calibrated_{f}" for f, _ in FAMILIES),
        ):
            row[field] = float(row[field])
        row["pinnacle_raw_normalized"] = (
            None if row["pinnacle_raw_normalized"] == "" else float(row["pinnacle_raw_normalized"])
        )
    known = {row["match_id"] for row in dataset.rows if row.get("outcome_known")}
    resolved_ids = [str(row["match_id"]) for row in predictions if str(row["match_id"]) in known]
    from tennislab.chain.labels import PanelOutcomeHistory

    history = PanelOutcomeHistory(
        dataset.panel_path, dataset.panel_sha256, purpose="component_scoring"
    )
    outcomes = history.selected(resolved_ids)  # outcome read after the barrier
    metrics, bins, comparisons, counts = calibration.evaluate(
        dataset.rows,
        outcomes,
        predictions,
        edges=config["calibration"]["reliability_bin_edges"],
        bootstrap_seed=config["comparisons"]["bootstrap_seed"],
        bootstrap_repetitions=config["comparisons"]["bootstrap_repetitions"],
    )
    write_csv(output / "metrics.csv", metrics, METRIC_FIELDS)
    write_csv(output / "reliability.csv", bins, RELIABILITY_FIELDS)
    write_json(output / "comparisons.json", comparisons)
    write_json(output / "cohort_counts.json", counts)
    document = {
        "status": "complete",
        "experiment_id": config["experiment_id"],
        "config_sha256": sha256(config_path),
        **_source_hashes(config),
        "calibration_run_manifest_sha256": sha256(calibration_dir / "run_manifest.json"),
        "predictions_sha256": predictions_sha256,
        "prediction_rows": len(predictions),
        "scored_rows": counts["resolved_outcome_rows"],
        "unresolved_rows": counts["unresolved_outcome_rows"],
        "outcome_read": history.reads[-1],
        "code": {
            "calibrate": code_receipt(__name__),
            "calibration": code_receipt(calibration.__name__),
            "market": code_receipt(market.__name__),
            "sr02_runner": code_receipt(sr02_runner.__name__),
            "declared_binding": manifest["declared_binding"],
        },
        "artifacts": {name: sha256(output / name) for name in COMPONENT_FILES},
    }
    write_json(output / "component_manifest.json", document)
    print(
        json.dumps(
            {
                "status": "complete",
                "scored_rows": counts["resolved_outcome_rows"],
                "unresolved_rows": counts["unresolved_outcome_rows"],
                "output": relative_to_root(output, label="output"),
            }
        )
    )
    return document


def preflight(config_path: Path) -> dict[str, object]:
    config_path = resolve_under_root(config_path, label="config")
    config = read_config(config_path)
    window = CalibrationWindow.from_config(config)
    manifest = calibration.validate_bindings(config, window=window)
    selected = read_csv(
        resolve_under_root(config["source"]["selected_matches_path"], label="selected_matches")
    )
    required = {
        "match_id",
        "match_date",
        "source_season",
        "source_key",
        "tourney_id",
        "surface",
        "best_of",
        "player_a",
        "player_b",
        "annual_target_eligible",
        "rule_status",
        *(field for _, field in FAMILIES),
    }
    if not selected or not required <= set(selected[0]):
        raise ChainError("selected match schema lacks required prediction inputs")
    return {
        "status": "PASS",
        "scope": "hash_schema_and_point_manifest_binding_only_no_fit_or_score",
        "config_sha256": sha256(config_path),
        "point_manifest_sha256": sha256(
            resolve_under_root(config["source"]["point_manifest_path"], label="point_manifest")
        ),
        "selected_matches_sha256": sha256(
            resolve_under_root(config["source"]["selected_matches_path"], label="selected_matches")
        ),
        "selected_matches_rows": len(selected),
        "manifest_selected_matches_rows": manifest["selected_matches_rows"],
        "scheduled_fits": len(config["calibration"]["outer_years"]) * len(FAMILIES),
        "outer_years": config["calibration"]["outer_years"],
        "calibration_window": window.as_document(),
        "outcomes_accessed": False,
        "model_fit_executed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("config", type=Path)
    run_parser.add_argument("output", type=Path)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("config", type=Path)
    evaluate_parser.add_argument("calibration_dir", type=Path)
    evaluate_parser.add_argument("output", type=Path)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("config", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.config, args.output)
    elif args.command == "evaluate":
        evaluate(args.config, args.calibration_dir, args.output)
    else:
        print(json.dumps(preflight(args.config), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
