"""Barrier-separated Lane G projection, forecast, commitment, and reporting stages."""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import platform
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.benchmark.core import (
    BenchmarkError,
    HistoryMatch,
    TargetMatch,
    rank_base_probability,
    rating_forecasts,
)
from tennislab.benchmark.statistics import ScoredRow, log_loss, simultaneous_intervals
from tennislab.chain.barrier_scan import scan_tree
from tennislab.chain.common import (
    atomic_csv,
    atomic_json,
    canonical_hash,
    code_receipt,
    read_config,
    require_hash,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
)
from tennislab.dynamics import market
from tennislab.models.numerical import key_hash

PROCEDURES = (
    "incumbent",
    "k32_pooled",
    "rank_logistic",
    "kovalchik_overall_major",
    "fivethirtyeight_surface",
    "welo",
)
COMPARATORS = PROCEDURES[1:]
SENSITIVE = re.compile(
    r"(?:^|_)(?:a_won|outcome|winner|status|score|price|odds?|decimal|implied|pinnacle|b365)(?:$|_)",
    re.I,
)
PREDICTION_FIELDS = (
    "tour",
    "year",
    "match_id",
    "match_date",
    "tournament_week",
    *(f"raw_{name}" for name in PROCEDURES),
    *(f"calibrated_{name}" for name in PROCEDURES),
)


def _rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        if not header or len(header) != len(set(header)):
            raise BenchmarkError(f"invalid CSV header: {path}")
        return header, [dict(row) for row in reader]


def _bound_path(entry: Mapping[str, Any], label: str, *, hash_required: bool) -> Path:
    path = resolve_under_root(str(entry["path"]), label=label)
    if not path.is_file():
        raise BenchmarkError(f"missing {label}: {path}")
    expected = entry.get("sha256")
    if hash_required and not expected:
        raise BenchmarkError(f"{label} has no frozen hash")
    require_hash(path, str(expected) if expected else None, label=label)
    return path


def _bool(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false"}:
        return False
    raise BenchmarkError(f"invalid {label}: {value!r}")


def _date(value: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise BenchmarkError(f"invalid {label}: {value!r}") from exc


def _week(value: str) -> str:
    value = value.strip()
    if "-W" in value:
        dt.date.fromisocalendar(int(value[:4]), int(value[-2:]), 1)
        return value
    if len(value) == 8 and value.isdigit():
        parsed = dt.datetime.strptime(value, "%Y%m%d").date()
    else:
        parsed = _date(value, "tournament start date")
    iso = parsed.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _finite_optional(value: str) -> float | None:
    if not value.strip():
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _canonical_ids(a: str, b: str) -> tuple[str, str, bool]:
    try:
        a_int, b_int = int(a), int(b)
    except ValueError as exc:
        raise BenchmarkError("player IDs must be decimal integers") from exc
    if a_int == b_int:
        raise BenchmarkError("a match cannot contain the same player twice")
    return (str(a_int), str(b_int), False) if a_int < b_int else (str(b_int), str(a_int), True)


def _panel_rows(path: Path, tour: str) -> tuple[list[HistoryMatch], dict[str, dict[str, str]]]:
    header, rows = _rows(path)
    required = {
        "match_id",
        "match_date",
        "player_a",
        "player_b",
        "surface",
        "tourney_level",
        "a_won",
        "score",
        "played",
        "retired",
    }
    missing = sorted(required - set(header))
    if missing:
        raise BenchmarkError(f"history panel missing columns: {missing}")
    result: list[HistoryMatch] = []
    metadata: dict[str, dict[str, str]] = {}
    for raw in rows:
        match_id = raw["match_id"]
        if match_id in metadata:
            raise BenchmarkError(f"duplicate panel match_id: {match_id}")
        a, b, swapped = _canonical_ids(raw["player_a"], raw["player_b"])
        won = _bool(raw["a_won"], "a_won")
        played = _bool(raw["played"], "played")
        metadata[match_id] = raw
        if not played or _bool(raw.get("walkover", "false"), "walkover"):
            continue
        result.append(
            HistoryMatch(
                match_id=match_id,
                tour=tour,
                match_date=_date(raw["match_date"], "match_date"),
                player_a=a,
                player_b=b,
                surface=raw["surface"],
                level=raw["tourney_level"],
                a_won=(not won) if swapped else won,
                score=raw["score"],
                played=True,
                retired=_bool(raw["retired"], "retired"),
            )
        )
    return result, metadata


def _feature_targets(
    path: Path,
    tour: str,
    years: set[int],
    panel_metadata: Mapping[str, Mapping[str, str]],
) -> tuple[list[TargetMatch], list[dict[str, str]], Counter[str]]:
    header, rows = _rows(path)
    required = {
        "match_id",
        "calendar_year",
        "source_season",
        "match_date",
        "eligible_through_date",
        "player_a",
        "player_b",
        "surface",
        "tourney_level",
        "rank_a",
        "rank_b",
        "primary_target",
        "identity_tier",
    }
    missing = sorted(required - set(header))
    if missing:
        raise BenchmarkError(f"features missing columns: {missing}")
    selected: list[TargetMatch] = []
    selected_raw: list[dict[str, str]] = []
    fallbacks: Counter[str] = Counter()
    seen: set[str] = set()
    for raw in rows:
        if raw["identity_tier"] != "primary" or not _bool(raw["primary_target"], "primary_target"):
            continue
        year = int(raw["calendar_year"])
        if int(raw["source_season"]) != year or year not in years:
            continue
        match_id = raw["match_id"]
        if match_id in seen:
            raise BenchmarkError(f"duplicate feature match_id: {match_id}")
        seen.add(match_id)
        if match_id not in panel_metadata:
            raise BenchmarkError(f"feature row absent from panel: {match_id}")
        a, b, swapped = _canonical_ids(raw["player_a"], raw["player_b"])
        rank_a, rank_b = _finite_optional(raw["rank_a"]), _finite_optional(raw["rank_b"])
        if swapped:
            rank_a, rank_b = rank_b, rank_a
        if any(
            value is None or not math.isfinite(value) or value <= 0
            for value in (rank_a, rank_b)
        ):
            fallbacks["rank_missing_or_invalid"] += 1
        panel = panel_metadata[match_id]
        anchor = raw.get("tournament_week", "") or panel.get("tourney_anchor_date", "")
        if not anchor:
            anchor = raw["match_date"]
        target = TargetMatch(
            match_id=match_id,
            tour=tour,
            match_date=_date(raw["match_date"], "match_date"),
            eligible_through_date=_date(raw["eligible_through_date"], "eligible_through_date"),
            tournament_week=_week(anchor),
            player_a=a,
            player_b=b,
            surface=raw["surface"],
            level=raw["tourney_level"],
            rank_a=rank_a,
            rank_b=rank_b,
        )
        if target.eligible_through_date != target.match_date - dt.timedelta(days=2):
            raise BenchmarkError(f"{match_id}: expected exact D-2 eligibility cutoff")
        selected.append(target)
        selected_raw.append(raw)
    return selected, selected_raw, fallbacks


def _target_membership(raw_rows: Sequence[Mapping[str, str]]) -> tuple[int, str]:
    keys = sorted((row["source_season"], row["match_id"]) for row in raw_rows)
    return len(keys), key_hash(keys)


def structural_projection(document: Mapping[str, Any]) -> dict[str, Any]:
    """Verify real bindings and memberships without parsing target values."""
    if document.get("benchmark_id") != "G-L":
        raise BenchmarkError("unsupported benchmark_id")
    result: dict[str, Any] = {
        "benchmark_id": "G-L",
        "status": "verified_structural_projection",
        "target_value_interpretation": "none",
        "tours": {},
    }
    for tour, spec in document["tours"].items():
        inputs = spec["inputs"]
        bound_inputs = {
            name: _bound_path(entry, f"{tour} {name}", hash_required=True)
            for name, entry in inputs.items()
            if isinstance(entry, dict) and "path" in entry
        }
        features = _bound_path(inputs["features"], f"{tour} features", hash_required=True)
        panel = _bound_path(inputs["history_panel"], f"{tour} history panel", hash_required=True)
        predictor = read_config(bound_inputs["predictor_config"])
        dispatch = spec["incumbent_native_dispatch"]
        settings = predictor.get("settings", {})
        observed_tour = settings["tour"] if "tour" in settings else "omitted"
        if predictor.get("experiment_id") != dispatch["experiment_id"]:
            raise BenchmarkError(f"{tour}: incumbent experiment dispatch mismatch")
        if observed_tour != dispatch["tour_setting"]:
            raise BenchmarkError(f"{tour}: incumbent native tour dispatch mismatch")
        feature_header, feature_rows = _rows(features)
        panel_header, panel_rows = _rows(panel)
        required_features = {
            "match_id", "calendar_year", "source_season", "primary_target", "identity_tier"
        }
        required_panel = {"match_id", "match_date", "player_a", "player_b", "tourney_anchor_date"}
        if not required_features <= set(feature_header) or not required_panel <= set(panel_header):
            raise BenchmarkError(f"{tour}: structural header contract failed")
        if len(feature_rows) != int(inputs["features"]["rows"]):
            raise BenchmarkError(f"{tour}: feature row-count mismatch")
        if len(panel_rows) != int(inputs["history_panel"]["rows"]):
            raise BenchmarkError(f"{tour}: panel row-count mismatch")
        annual: dict[str, Any] = {}
        target_keys: set[tuple[str, str]] = set()
        for year in spec["target_years"]:
            chosen = [
                row
                for row in feature_rows
                if row["identity_tier"] == "primary"
                and row["primary_target"] in {"1", "true"}
                and int(row["calendar_year"]) == year
                and int(row["source_season"]) == year
            ]
            observed = key_hash(
                sorted((row["source_season"], row["match_id"]) for row in chosen)
            )
            expected = spec["annual_primary"][str(year)]
            if len(chosen) != int(expected["rows"]) or observed != expected["membership_sha256"]:
                raise BenchmarkError(f"{tour}/{year}: primary membership mismatch")
            annual[str(year)] = {"rows": len(chosen), "membership_sha256": observed}
            target_keys.update((str(year), row["match_id"]) for row in chosen)
            incumbent_path = resolve_under_root(
                inputs["incumbent_pattern"].format(year=year), label=f"{tour}/{year} incumbent"
            )
            bound = spec["incumbent_files"][str(year)]
            require_hash(incumbent_path, bound["sha256"], label=f"{tour}/{year} incumbent")
            header, incumbent_rows = _rows(incumbent_path)
            if not {"season", "match_id", "p_a_wins"} <= set(header):
                raise BenchmarkError(f"{tour}/{year}: incumbent header mismatch")
            if len(incumbent_rows) != int(bound["rows"]):
                raise BenchmarkError(f"{tour}/{year}: incumbent row-count mismatch")
            incumbent_keys = {(row["season"], row["match_id"]) for row in incumbent_rows}
            required_keys = {(str(year), row["match_id"]) for row in chosen}
            if not required_keys <= incumbent_keys:
                raise BenchmarkError(f"{tour}/{year}: incumbent lacks primary target keys")
        if len(target_keys) != int(spec["expected_primary_rows"]):
            raise BenchmarkError(f"{tour}: target total mismatch")
        result["tours"][tour] = {
            "bound_input_sha256": {
                name: sha256(path) for name, path in sorted(bound_inputs.items())
            },
            "feature_columns": len(feature_header),
            "feature_rows": len(feature_rows),
            "panel_columns": len(panel_header),
            "panel_rows": len(panel_rows),
            "target_rows": len(target_keys),
            "annual": annual,
            "incumbent_coverage": "complete_for_target_membership",
            "native_dispatch": dispatch,
        }
    return result


def project(config_path: str | Path) -> dict[str, Any]:
    path = resolve_under_root(config_path, label="benchmark config")
    document = read_config(path)
    design = _bound_path(document["design"], "benchmark design", hash_required=True)
    result = structural_projection(document)
    result["config_sha256"] = sha256(path)
    result["design_sha256"] = sha256(design)
    return result


def _rank_probabilities(
    targets: Sequence[TargetMatch],
    outcomes: Mapping[str, int],
    history_years: int,
    prediction_years: set[int],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    by_year: defaultdict[int, list[TargetMatch]] = defaultdict(list)
    for row in targets:
        by_year[row.match_date.year].append(row)
    probabilities: dict[str, float] = {}
    receipts: list[dict[str, Any]] = []
    for year in sorted(prediction_years):
        represented = set(range(year - history_years, year))
        training = [row for prior in represented for row in by_year.get(prior, ())]
        if {row.match_date.year for row in training} != represented:
            raise BenchmarkError(f"rank logistic {year}: incomplete five-year history")
        base = np.asarray(
            [rank_base_probability(row.rank_a, row.rank_b) for row in training], dtype=float
        )
        labels = np.asarray([outcomes[row.match_id] for row in training], dtype=float)
        fitted = market.fit(base, labels)
        theta = fitted.market_slope
        current_base = np.asarray(
            [rank_base_probability(row.rank_a, row.rank_b) for row in by_year[year]], dtype=float
        )
        predicted = fitted.predict(current_base)
        probabilities.update(
            {row.match_id: float(value) for row, value in zip(by_year[year], predicted, strict=True)}
        )
        receipts.append(
            {
                "procedure": "rank_logistic",
                "year": year,
                "theta": theta,
                "training_rows": len(training),
                "boundary": theta <= 1e-12,
            }
        )
    return probabilities, receipts


def _incumbent(
    spec: Mapping[str, Any], targets: Sequence[TargetMatch], *, hash_required: bool
) -> dict[str, float]:
    by_year: defaultdict[int, set[str]] = defaultdict(set)
    for row in targets:
        by_year[row.match_date.year].add(row.match_id)
    result: dict[str, float] = {}
    for year, required in sorted(by_year.items()):
        path = resolve_under_root(
            spec["inputs"]["incumbent_pattern"].format(year=year),
            label=f"incumbent {year}",
        )
        bound = spec.get("incumbent_files", {}).get(str(year), {})
        require_hash(path, bound.get("sha256") if hash_required else None, label=f"incumbent {year}")
        _, rows = _rows(path)
        values: dict[str, float] = {}
        for raw in rows:
            match_id = raw["match_id"]
            if match_id in values:
                raise BenchmarkError(f"duplicate incumbent key: {year}/{match_id}")
            value = float(raw["p_a_wins"])
            if not math.isfinite(value) or not 0 < value < 1:
                raise BenchmarkError(f"invalid incumbent probability: {year}/{match_id}")
            values[match_id] = value
        if not required <= set(values):
            raise BenchmarkError(f"incumbent missing target keys in {year}")
        result.update({match_id: values[match_id] for match_id in required})
    return result


def _fit_calibration(
    raw: Mapping[str, Mapping[str, float]],
    targets: Sequence[TargetMatch],
    outcomes: Mapping[str, int],
    target_years: Sequence[int],
    years_back: int,
) -> tuple[dict[tuple[int, str], Any], list[dict[str, Any]]]:
    by_year: defaultdict[int, list[TargetMatch]] = defaultdict(list)
    for target in targets:
        by_year[target.match_date.year].append(target)
    products: dict[tuple[int, str], Any] = {}
    receipts: list[dict[str, Any]] = []
    for outer_year in target_years:
        expected = set(range(outer_year - years_back, outer_year))
        training = [row for year in sorted(expected) for row in by_year.get(year, ())]
        if {row.match_date.year for row in training} != expected:
            raise BenchmarkError(f"calibration {outer_year}: incomplete calendar-year history")
        for procedure in COMPARATORS:
            fitted = market.fit(
                np.asarray([raw[procedure][row.match_id] for row in training], dtype=float),
                np.asarray([outcomes[row.match_id] for row in training], dtype=float),
            )
            products[(outer_year, procedure)] = fitted
            receipts.append(
                {
                    "procedure": procedure,
                    "outer_year": outer_year,
                    "alpha": fitted.market_slope,
                    "training_rows": len(training),
                    "boundary": fitted.market_slope <= 1e-12,
                }
            )
    return products, receipts


def _manifest_files(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256(path)
        for path in sorted(item for item in directory.rglob("*") if item.is_file())
    }


def _sensitive_json_paths(value: Any, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{prefix}.{key}"
            if SENSITIVE.search(str(key)):
                findings.append(here)
            findings.extend(_sensitive_json_paths(child, here))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_sensitive_json_paths(child, f"{prefix}[{index}]"))
    return findings


def _sensitive_findings(directory: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.name == "stage_manifest.json":
            continue
        relative = path.relative_to(directory).as_posix()
        hits: list[str] = []
        if path.suffix == ".csv":
            header, _ = _rows(path)
            hits = [f"header:{field}" for field in header if SENSITIVE.search(field)]
        elif path.suffix == ".json":
            hits = _sensitive_json_paths(json.loads(path.read_text(encoding="utf-8")))
        elif path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if line.strip():
                        hits.extend(
                            f"line:{number}:{hit}"
                            for hit in _sensitive_json_paths(json.loads(line))
                        )
        if hits:
            findings.append({"artifact": relative, "locations": hits})
    return findings


def forecast(config_path: str | Path, attempt: str) -> Path:
    config = resolve_under_root(config_path, label="benchmark config")
    document = read_config(config)
    synthetic = document.get("proposal_status") == "synthetic_rehearsal"
    if not synthetic and document.get("proposal_status") != "frozen_for_real_execution":
        raise BenchmarkError("real forecast refused: proposal is not frozen_for_real_execution")
    if not synthetic:
        _bound_path(document["design"], "benchmark design", hash_required=True)
        structural_projection(document)
    attempt_root = resolve_output_under_root(
        Path(document["output_root"]) / attempt, label="benchmark attempt"
    )
    if attempt_root.exists():
        raise BenchmarkError(f"attempt already exists and is immutable: {attempt_root}")
    attempt_root.mkdir(parents=True)
    forecast_root = attempt_root / "forecast"
    forecast_root.mkdir()
    try:
        all_predictions: list[dict[str, Any]] = []
        all_fit_receipts: list[dict[str, Any]] = []
        all_fallbacks: dict[str, Any] = {}
        source_manifest: dict[str, Any] = {}
        constants = document["constants"]
        probability_clip = float(constants.get("probability_clip", 1e-6))
        if not 0 < probability_clip < 0.5:
            raise BenchmarkError("probability_clip must lie in (0, 0.5)")
        years_back = int(constants["calibration_years"])
        parameter_history = int(constants["parameter_history_years"])
        for tour, spec in document["tours"].items():
            target_years = [int(value) for value in spec["target_years"]]
            raw_years = set(range(min(target_years) - years_back, max(target_years) + 1))
            feature_years = set(
                range(min(raw_years) - parameter_history, max(raw_years) + 1)
            )
            inputs = spec["inputs"]
            features_path = _bound_path(
                inputs["features"], f"{tour} features", hash_required=not synthetic
            )
            panel_path = _bound_path(
                inputs["history_panel"], f"{tour} history panel", hash_required=not synthetic
            )
            history, panel_metadata = _panel_rows(panel_path, tour)
            all_targets, raw_features, rank_fallbacks = _feature_targets(
                features_path, tour, feature_years, panel_metadata
            )
            targets = [row for row in all_targets if row.match_date.year in raw_years]
            outcomes = {row.match_id: int(row.a_won) for row in history}
            if not all(row.match_id in outcomes for row in all_targets):
                raise BenchmarkError(f"{tour}: calibration rows lack past outcomes")
            rating_raw, rating_fallbacks = rating_forecasts(
                history, targets, spec.get("major_level_codes", ["G"])
            )
            raw: dict[str, dict[str, float]] = {
                procedure: {
                    match_id: values[procedure] for match_id, values in rating_raw.items()
                }
                for procedure in (
                    "k32_pooled",
                    "kovalchik_overall_major",
                    "fivethirtyeight_surface",
                    "welo",
                )
            }
            rank_raw, rank_receipts = _rank_probabilities(
                all_targets, outcomes, parameter_history, raw_years
            )
            raw["rank_logistic"] = rank_raw
            target_rows = [row for row in targets if row.match_date.year in set(target_years)]
            if {row.match_date.year for row in target_rows} != set(target_years):
                raise BenchmarkError(f"{tour}: one or more target years are empty")
            raw["incumbent"] = _incumbent(spec, target_rows, hash_required=not synthetic)
            calibration, calibration_receipts = _fit_calibration(
                raw, targets, outcomes, target_years, years_back
            )
            for row in sorted(target_rows, key=lambda value: (value.match_date, value.match_id)):
                year = row.match_date.year
                output: dict[str, Any] = {
                    "tour": tour,
                    "year": year,
                    "match_id": row.match_id,
                    "match_date": row.match_date.isoformat(),
                    "tournament_week": row.tournament_week,
                }
                for procedure in PROCEDURES:
                    raw_value = min(
                        max(raw[procedure][row.match_id], probability_clip),
                        1.0 - probability_clip,
                    )
                    output[f"raw_{procedure}"] = raw_value
                    if procedure == "incumbent":
                        output[f"calibrated_{procedure}"] = raw_value
                    else:
                        calibrated_value = float(
                            calibration[(year, procedure)].predict(
                                np.asarray([raw[procedure][row.match_id]], dtype=float)
                            )[0]
                        )
                        output[f"calibrated_{procedure}"] = min(
                            max(calibrated_value, probability_clip), 1.0 - probability_clip
                        )
                all_predictions.append(output)
            all_fit_receipts.extend({"tour": tour, **row} for row in rank_receipts)
            all_fit_receipts.extend({"tour": tour, **row} for row in calibration_receipts)
            all_fallbacks[tour] = {**dict(rank_fallbacks), **dict(rating_fallbacks)}
            source_manifest[tour] = {
                "features": {"path": inputs["features"]["path"], "sha256": sha256(features_path)},
                "history_panel": {
                    "path": inputs["history_panel"]["path"],
                    "sha256": sha256(panel_path),
                },
                "raw_membership": {
                    "rows": len(raw_features),
                    "sha256": _target_membership(raw_features)[1],
                },
                "target_rows": len(target_rows),
                "incumbent_forecasts": {
                    str(year): {
                        "path": inputs["incumbent_pattern"].format(year=year),
                        "sha256": sha256(
                            resolve_under_root(
                                inputs["incumbent_pattern"].format(year=year),
                                label=f"{tour}/{year} incumbent",
                            )
                        ),
                    }
                    for year in target_years
                },
            }
        predictions_path = forecast_root / "predictions.csv"
        atomic_csv(predictions_path, PREDICTION_FIELDS, all_predictions)
        atomic_json(forecast_root / "fit_receipts.json", all_fit_receipts)
        atomic_json(forecast_root / "fallback_counts.json", all_fallbacks)
        atomic_json(forecast_root / "source_manifest.json", source_manifest)
        stage_manifest = {
            "benchmark_id": document["benchmark_id"],
            "proposal_status": document["proposal_status"],
            "attempt": attempt,
            "config_sha256": sha256(config),
            "config_canonical_sha256": canonical_hash(document),
            "code": [
                code_receipt(__name__),
                code_receipt("tennislab.benchmark.core"),
                code_receipt("tennislab.dynamics.market"),
            ],
            "runtime": {"python": sys.version, "platform": platform.platform()},
            "artifacts": _manifest_files(forecast_root),
            "rows": len(all_predictions),
            "report_only_label_file_read": False,
            "history_outcomes_read_under_cutoff_contract": True,
            "price_values_read": False,
        }
        atomic_json(forecast_root / "stage_manifest.json", stage_manifest)
    except Exception as exc:
        atomic_json(
            attempt_root / "failure.json",
            {"stage": "forecast", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    return attempt_root


def barrier(config_path: str | Path, attempt: str) -> Path:
    config = resolve_under_root(config_path, label="benchmark config")
    document = read_config(config)
    attempt_root = resolve_output_under_root(
        Path(document["output_root"]) / attempt, label="benchmark attempt"
    )
    forecast_root = attempt_root / "forecast"
    if (
        not forecast_root.is_dir()
        or (attempt_root / "barrier").exists()
        or (attempt_root / "barrier_failure.json").exists()
    ):
        raise BenchmarkError("forecast absent or barrier attempt already closed")
    try:
        scan = scan_tree(attempt_root, ["forecast"])
        sensitive = _sensitive_findings(forecast_root)
        if scan["findings"] or scan["uninspected"] or sensitive:
            raise BenchmarkError(
                f"forecast barrier rejected content: metric_scan={scan}; sensitive={sensitive}"
            )
        barrier_root = attempt_root / "barrier"
        barrier_root.mkdir()
        atomic_json(
            barrier_root / "commitment.json",
            {
                "benchmark_id": document["benchmark_id"],
                "attempt": attempt,
                "config_sha256": sha256(config),
                "forecast_artifacts": _manifest_files(forecast_root),
                "scan": scan,
                "sensitive_findings": sensitive,
                "code": [
                    code_receipt(__name__),
                    code_receipt("tennislab.chain.barrier_scan"),
                ],
            },
        )
    except Exception as exc:
        atomic_json(
            attempt_root / "barrier_failure.json",
            {"stage": "barrier", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    return barrier_root


def _verify_barrier(attempt_root: Path, config: Path) -> Mapping[str, Any]:
    commitment_path = attempt_root / "barrier" / "commitment.json"
    if not commitment_path.is_file():
        raise BenchmarkError("barrier commitment is absent")
    commitment = json.loads(commitment_path.read_text(encoding="utf-8"))
    if commitment["config_sha256"] != sha256(config):
        raise BenchmarkError("config changed after barrier")
    observed = _manifest_files(attempt_root / "forecast")
    if observed != commitment["forecast_artifacts"]:
        raise BenchmarkError("forecast bytes changed after barrier")
    scan = scan_tree(attempt_root, ["forecast"])
    if scan["findings"] or scan["uninspected"] or _sensitive_findings(attempt_root / "forecast"):
        raise BenchmarkError("forecast content no longer passes barrier")
    return commitment


def _labels(path: Path) -> dict[str, int]:
    _, rows = _rows(path)
    result: dict[str, int] = {}
    for row in rows:
        match_id = row["match_id"]
        if match_id in result:
            raise BenchmarkError(f"duplicate target label: {match_id}")
        result[match_id] = int(_bool(row["a_won"], "a_won"))
    return result


def _priced(path: Path) -> set[str]:
    header, rows = _rows(path)
    valid_column = "PS_valid" if "PS_valid" in header else "priced"
    if valid_column not in header:
        raise BenchmarkError("price input lacks PS_valid/priced membership flag")
    result: set[str] = set()
    for row in rows:
        if _bool(row[valid_column], valid_column):
            result.add(row["match_id"])
    return result


def report(config_path: str | Path, attempt: str) -> Path:
    config = resolve_under_root(config_path, label="benchmark config")
    document = read_config(config)
    synthetic = document.get("proposal_status") == "synthetic_rehearsal"
    if not synthetic and document.get("proposal_status") != "frozen_for_real_execution":
        raise BenchmarkError("real report refused: proposal is not frozen_for_real_execution")
    attempt_root = resolve_output_under_root(
        Path(document["output_root"]) / attempt, label="benchmark attempt"
    )
    if (attempt_root / "report_failure.json").exists():
        raise BenchmarkError("report attempt already failed and is immutable")
    try:
        _verify_barrier(attempt_root, config)
    except Exception as exc:
        atomic_json(
            attempt_root / "report_failure.json",
            {"stage": "report_preflight", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    report_root = attempt_root / "report"
    if report_root.exists():
        raise BenchmarkError("report already exists")
    report_root.mkdir()
    try:
        _, predictions = _rows(attempt_root / "forecast" / "predictions.csv")
        summary: dict[str, Any] = {
            "benchmark_id": document["benchmark_id"],
            "attempt": attempt,
            "proposal_status": document["proposal_status"],
            "admission_failures": {
                "ingram": "exact public features, preprocessing, weights/retraining contract absent",
                "uts_utr": "dated redistributable rating feed or faithful public reconstruction absent",
                "public_feature_ml": "separate feature and nested-selection freeze absent",
            },
            "tours": {},
        }
        inference = document["inference"]
        for tour, spec in document["tours"].items():
            inputs = spec["inputs"]
            labels_path = _bound_path(inputs["labels"], f"{tour} labels", hash_required=not synthetic)
            prices_path = _bound_path(inputs["prices"], f"{tour} prices", hash_required=not synthetic)
            labels = _labels(labels_path)
            priced = _priced(prices_path)
            tour_rows = [row for row in predictions if row["tour"] == tour]
            required_ids = {row["match_id"] for row in tour_rows}
            if not required_ids <= set(labels):
                raise BenchmarkError(f"{tour}: labels missing prediction keys")
            procedure_columns = tuple(f"calibrated_{name}" for name in PROCEDURES)
            full: list[ScoredRow] = []
            priced_rows: list[ScoredRow] = []
            for row in tour_rows:
                values = {
                    name: log_loss(float(row[name]), labels[row["match_id"]])
                    for name in procedure_columns
                }
                scored = ScoredRow(int(row["year"]), row["tournament_week"], values)
                full.append(scored)
                if row["match_id"] in priced:
                    priced_rows.append(scored)
            if not synthetic:
                if len(full) != int(spec["expected_primary_rows"]):
                    raise BenchmarkError(f"{tour}: report primary count mismatch")
                if len(priced_rows) != int(spec["expected_priced_rows"]):
                    raise BenchmarkError(f"{tour}: report priced count mismatch")
            contrasts = {
                name: ("calibrated_incumbent", f"calibrated_{name}") for name in COMPARATORS
            }
            tour_summary: dict[str, Any] = {"primary_rows": len(full), "priced_rows": len(priced_rows)}
            for cohort_name, cohort_rows in (("primary", full), ("priced_secondary", priced_rows)):
                blocks: dict[str, Any] = {}
                lengths = [
                    int(inference["primary_mean_block_weeks"]),
                    *(int(value) for value in inference["sensitivity_mean_block_weeks"]),
                ]
                for length in lengths:
                    offset = (1 if tour == "ATP" else 2) * 1000 + length
                    blocks[str(length)] = simultaneous_intervals(
                        cohort_rows,
                        contrasts,
                        replicates=int(inference["replicates"]),
                        maximum_draws=int(inference["maximum_draws"]),
                        seed=int(inference["seed"]) + offset,
                        mean_block=length,
                        level=float(inference["simultaneous_level"]),
                        degenerate_tolerance=float(inference["degenerate_se_tolerance"]),
                    )
                tour_summary[cohort_name] = blocks
            summary["tours"][tour] = tour_summary
        atomic_json(report_root / "benchmark_report.json", summary)
        atomic_json(
            report_root / "stage_manifest.json",
            {
                "benchmark_id": document["benchmark_id"],
                "attempt": attempt,
                "config_sha256": sha256(config),
                "barrier_sha256": sha256(attempt_root / "barrier" / "commitment.json"),
                "artifacts": _manifest_files(report_root),
                "code": [
                    code_receipt(__name__),
                    code_receipt("tennislab.benchmark.statistics"),
                ],
                "target_values_read": True,
                "price_values_read": True,
            },
        )
    except Exception as exc:
        atomic_json(
            report_root / "failure.json",
            {"stage": "report", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    return report_root
