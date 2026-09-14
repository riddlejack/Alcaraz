"""Barrier-separated Lane G repair workflow.

Forecast writes sports probabilities and provenance only. Outcomes, odds, scores and
metric values are admitted only after the completed forecast tree is committed.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import math
import platform
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.benchmark.core import (
    DECAY_EXPONENT,
    DECAY_NUMERATOR,
    DECAY_OFFSET,
    INITIAL,
    MAJOR_MULTIPLIER,
    OVERALL_WEIGHT,
    SCALE,
    SUPPORTED_SURFACES,
    SURFACE_WEIGHT,
    BenchmarkError,
    HistoryMatch,
    TargetMatch,
    rank_base_probability,
    rating_forecasts,
    winner_game_share,
)
from tennislab.benchmark.formats import (
    SUPPORTED_SUFFIXES,
    csv_header,
    data_row_count,
    format_name,
    gated_selected_csv_rows,
    json_values,
    selected_csv_rows,
)
from tennislab.benchmark.statistics import ScoredRow, log_loss, simultaneous_intervals
from tennislab.chain.barrier_scan import METRIC
from tennislab.chain.common import (
    atomic_csv,
    atomic_json,
    canonical_hash,
    code_receipt,
    read_config,
    relative_to_root,
    require_hash,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
)
from tennislab.dynamics import market
from tennislab.models import pipeline as legacy_pipeline
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
REPAIR_CONTRACT_SHA256 = "696d6e831a0a8a5a2d7e766cb1752a2e72f8377c3d3e53c20d583ebd7927bc2a"
REVIEW_SHA256 = "9a4d26aeadbb3e469cab20157e16e15d334279c6ecf03431f9d4b62bc23640bc"
BASE_CONFIG_SHA256 = "8acb934230137256b9cb58493239381be7c8ba09cd7bd5d1b33053d0209f0829"
EXPECTED_CONSTANTS: dict[str, float | int] = {
    "elo_initial": 1500.0,
    "elo_scale": 400.0,
    "k32": 32.0,
    "decaying_k_numerator": 250.0,
    "decaying_k_offset": 5.0,
    "decaying_k_exponent": 0.4,
    "kovalchik_major_multiplier": 1.1,
    "fivethirtyeight_overall_weight": 0.71,
    "fivethirtyeight_surface_weight": 0.29,
    "calibration_years": 3,
    "parameter_history_years": 5,
    "logit_clip": 1e-6,
    "scoring_clip": 1e-15,
}
SENSITIVE = re.compile(
    r"(?:^|_)(?:a_won|outcome|winner|match_status|score|price|odds?|decimal|implied|pinnacle|b365)(?:$|_)",
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
FALLBACK_FIELDS = ("tour", "calendar_year", "service", "scope", "reason", "count")
FORECAST_ARTIFACTS = frozenset(
    {
        "predictions.csv",
        "fit_receipts.json",
        "fallback_counts.csv",
        "access_receipt.json",
        "source_manifest.json",
        "stage_manifest.json",
    }
)
CODE_MODULES = (
    "tennislab.benchmark.workflow",
    "tennislab.benchmark.core",
    "tennislab.benchmark.formats",
    "tennislab.benchmark.statistics",
    "tennislab.chain.common",
    "tennislab.chain.barrier_scan",
    "tennislab.models.pipeline",
    "tennislab.models.numerical",
)
FALLBACK_REASONS = {
    "k32_pooled": ("fresh_player_initialization", "unknown_surface_overall_only"),
    "rank_logistic": ("missing_or_invalid_rank",),
    "kovalchik_overall_major": ("fresh_player_initialization",),
    "fivethirtyeight_surface": ("fresh_player_initialization", "unknown_surface_overall_only"),
    "welo": ("fresh_player_initialization", "unparsed_games_standard_update"),
}


def _rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    header = csv_header(path)
    return selected_csv_rows(path, header)


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    observed = set(value)
    if observed != expected:
        raise BenchmarkError(
            f"{label} schema mismatch: missing={sorted(expected - observed)} unknown={sorted(observed - expected)}"
        )


def _bound_path(entry: Mapping[str, Any], label: str, *, hash_required: bool) -> Path:
    if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
        raise BenchmarkError(f"invalid {label} binding")
    path = resolve_under_root(entry["path"], label=label)
    if not path.is_file():
        raise BenchmarkError(f"missing {label}: {path}")
    expected = entry.get("sha256")
    if hash_required and not isinstance(expected, str):
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
        year, week = (int(piece) for piece in value.split("-W"))
        dt.date.fromisocalendar(year, week, 1)
        return f"{year:04d}-W{week:02d}"
    parsed = (
        dt.datetime.strptime(value, "%Y%m%d").date() if len(value) == 8 else _date(value, "anchor")
    )
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


def _execution_binding() -> dict[str, Any]:
    return {
        "code": [code_receipt(name) for name in CODE_MODULES],
        "dependencies": legacy_pipeline.dependency_versions(),
        "runtime": {"python_implementation": platform.python_implementation()},
    }


def _validate_wta01_binding(invocation: Mapping[str, Any]) -> None:
    binding = invocation.get("wta01_independent_binding")
    if not isinstance(binding, Mapping):
        raise BenchmarkError("WTA01 independent binding absent")
    if (
        binding.get("status") != "historical_reconstruction_pass_only"
        or binding.get("product_commit") != "87448ab2dce4e65a479adaff01c9650d53eb7820"
        or binding.get("claim_limit") != "not_prospective_and_not_lane_g_acceptance"
    ):
        raise BenchmarkError("WTA01 independent binding identity drift")
    for name in ("primary_chain", "run_manifest", "current_amended_design"):
        _bound_path(binding[name], f"WTA01 {name}", hash_required=True)
    original = binding.get("original_design_blob")
    if not isinstance(original, Mapping) or original != {
        "archive_commit": "1f18978828293c745b93879ea7fae41c821b2900",
        "path": "experiments/WTA01.design.md",
        "sha256": "0428751403cbd8b1d52ef65f83a1a630d0b61d94f446a3ea5e286354071950f0",
    }:
        raise BenchmarkError("WTA01 original design-blob binding drift")


def _validate_reviewed_runtime(document: Mapping[str, Any]) -> None:
    reviewed = document.get("reviewed_runtime")
    if not isinstance(reviewed, Mapping) or reviewed.get("status") != "FROZEN_INDEPENDENT_REVIEW":
        raise BenchmarkError("real execution refused: reviewed runtime is pending")
    current = _execution_binding()
    module_hashes = {item["module"]: item["sha256"] for item in current["code"]}
    if reviewed.get("module_sha256") != module_hashes:
        raise BenchmarkError("real execution refused: reviewed module hashes mismatch")
    if reviewed.get("dependencies") != current["dependencies"]:
        raise BenchmarkError("real execution refused: reviewed dependencies mismatch")
    commit = reviewed.get("commit")
    if not isinstance(commit, str) or len(commit) != 40:
        raise BenchmarkError("real execution refused: reviewed commit binding absent")
    repository = Path(__file__).resolve().parents[3]
    observed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    if observed != commit:
        raise BenchmarkError("real execution refused: reviewed commit is not current HEAD")


def _load_config(config_path: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    config = resolve_under_root(config_path, label="benchmark config")
    invocation = read_config(config)
    if invocation.get("schema_version") != 2:
        raise BenchmarkError("Lane G repair requires schema_version 2")
    bindings: dict[str, Any] = {"invocation_config_sha256": sha256(config)}
    if "base_config" in invocation:
        base_path = _bound_path(invocation["base_config"], "base config", hash_required=True)
        if sha256(base_path) != BASE_CONFIG_SHA256:
            raise BenchmarkError("base config is not the preserved Lane G config")
        contract_path = _bound_path(
            invocation["repair_contract"], "repair contract", hash_required=True
        )
        review_path = _bound_path(
            invocation["independent_review"], "independent review", hash_required=True
        )
        if sha256(contract_path) != REPAIR_CONTRACT_SHA256 or sha256(review_path) != REVIEW_SHA256:
            raise BenchmarkError("repair authority binding mismatch")
        _validate_wta01_binding(invocation)
        document = copy.deepcopy(read_config(base_path))
        for key in (
            "schema_version",
            "proposal_status",
            "execution_scope",
            "output_root",
            "anchor_basis",
            "fixed_contract",
            "calibration",
            "market_references",
            "inference",
            "synthetic_policy",
            "reviewed_runtime",
            "wta01_independent_binding",
        ):
            document[key] = copy.deepcopy(invocation[key])
        document["procedures"] = list(invocation["fixed_contract"]["procedures"])
        document["constants"] = copy.deepcopy(invocation["fixed_contract"]["constants"])
        bindings.update(
            {
                "base_config_sha256": sha256(base_path),
                "repair_contract_sha256": sha256(contract_path),
                "independent_review_sha256": sha256(review_path),
            }
        )
    else:
        document = copy.deepcopy(invocation)
        bindings.update(
            {
                "base_config_sha256": BASE_CONFIG_SHA256,
                "repair_contract_sha256": REPAIR_CONTRACT_SHA256,
                "independent_review_sha256": REVIEW_SHA256,
                "synthetic_embedded_contract": True,
            }
        )
    bindings["effective_config_sha256"] = canonical_hash(document)
    _validate_document(document)
    return config, document, bindings


def _validate_document(document: Mapping[str, Any]) -> None:
    if document.get("benchmark_id") != "G-L":
        raise BenchmarkError("unsupported benchmark_id")
    if tuple(document.get("procedures", ())) != PROCEDURES:
        raise BenchmarkError("procedure contract drift")
    fixed = document.get("fixed_contract")
    if not isinstance(fixed, Mapping) or tuple(fixed.get("procedures", ())) != PROCEDURES:
        raise BenchmarkError("fixed procedure contract absent or drifted")
    constants = fixed.get("constants")
    if not isinstance(constants, Mapping) or set(constants) != set(EXPECTED_CONSTANTS):
        raise BenchmarkError("fixed constant contract absent or has unknown keys")
    for name, expected in EXPECTED_CONSTANTS.items():
        if constants[name] != expected or document.get("constants", {}).get(name) != expected:
            raise BenchmarkError(f"fixed constant drift: {name}")
    if not (
        INITIAL == constants["elo_initial"]
        and SCALE == constants["elo_scale"]
        and DECAY_NUMERATOR == constants["decaying_k_numerator"]
        and DECAY_OFFSET == constants["decaying_k_offset"]
        and DECAY_EXPONENT == constants["decaying_k_exponent"]
        and MAJOR_MULTIPLIER == constants["kovalchik_major_multiplier"]
        and OVERALL_WEIGHT == constants["fivethirtyeight_overall_weight"]
        and SURFACE_WEIGHT == constants["fivethirtyeight_surface_weight"]
    ):
        raise BenchmarkError("executable rating constants do not match repair contract")
    if document.get("anchor_basis") != "tourney_anchor_date_event_anchor_proxy":
        raise BenchmarkError("named anchor basis drift")
    if document.get("calibration") != {
        "implementation": "tennislab.models.pipeline.fit_nonnegative_slope",
        "application": "tennislab.models.pipeline.apply_slope",
        "year_weighting": "equal_total_weight_per_calendar_year",
        "intercept": False,
        "slope_lower_bound": 0.0,
    }:
        raise BenchmarkError("calibration procedure contract drift")
    market_contract = document.get("market_references")
    required_market = {
        "book": "PS",
        "valid_column": "PS_valid",
        "decimal_a_column": "PS_decimal_a",
        "decimal_b_column": "PS_decimal_b",
        "normalized_id": "normalized_pinnacle_raw",
        "past_calibrated_id": "normalized_pinnacle_calibrated_past",
        "quote_timing": "unknown_later_information_reference",
    }
    if market_contract != required_market:
        raise BenchmarkError("market-reference procedure contract drift")
    inference = document.get("inference")
    if not isinstance(inference, Mapping):
        raise BenchmarkError("inference contract absent")
    replicates = inference.get("replicates")
    maximum = inference.get("maximum_draws")
    level = inference.get("simultaneous_level")
    tolerance = inference.get("degenerate_se_tolerance")
    lengths = [
        inference.get("primary_mean_block_weeks"),
        *inference.get("sensitivity_mean_block_weeks", []),
    ]
    if not isinstance(replicates, int) or isinstance(replicates, bool) or replicates < 2:
        raise BenchmarkError("inference replicates must be >= 2")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < replicates:
        raise BenchmarkError("maximum draws must be >= replicates")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in lengths
    ):
        raise BenchmarkError("bootstrap mean block lengths must be positive integers")
    if not isinstance(level, (int, float)) or not math.isfinite(level) or not 0 < level < 1:
        raise BenchmarkError("simultaneous level must lie in (0,1)")
    if not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        raise BenchmarkError("degenerate tolerance must be finite and nonnegative")
    if inference.get("brier_inference") is not False:
        raise BenchmarkError("Brier inference must remain disabled")
    if inference.get("seed_base") != 20260914 or inference.get("tour_offsets") != {
        "ATP": 1000,
        "WTA": 2000,
    }:
        raise BenchmarkError("bootstrap seed contract drift")
    if set(document.get("tours", {})) - {"ATP", "WTA"} or not document.get("tours"):
        raise BenchmarkError("only nonempty ATP/WTA tour maps are accepted")
    for tour, spec in document["tours"].items():
        years = spec.get("target_years")
        if (
            not isinstance(years, list)
            or not years
            or any(not isinstance(year, int) for year in years)
        ):
            raise BenchmarkError(f"{tour}: invalid target years")
        if years != sorted(set(years)):
            raise BenchmarkError(f"{tour}: target years must be unique and sorted")
        if not spec.get("major_level_codes"):
            raise BenchmarkError(f"{tour}: major-level codes are absent")


def _input_paths(document: Mapping[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for tour, spec in document["tours"].items():
        inputs = spec["inputs"]
        for name, entry in inputs.items():
            if isinstance(entry, Mapping) and isinstance(entry.get("path"), str):
                result[f"{tour}:{name}"] = resolve_under_root(entry["path"], label=f"{tour} {name}")
        for year in spec["target_years"]:
            result[f"{tour}:incumbent:{year}"] = resolve_under_root(
                inputs["incumbent_pattern"].format(year=year), label=f"{tour}/{year} incumbent"
            )
    return result


def _validate_synthetic(document: Mapping[str, Any]) -> dict[str, Any]:
    policy = document.get("synthetic_policy")
    if document.get("proposal_status") != "synthetic_rehearsal" or not isinstance(policy, Mapping):
        raise BenchmarkError("synthetic policy absent")
    required_root = resolve_under_root(policy["required_root"], label="synthetic fixture root")
    manifest_entry = document.get("fixture_manifest")
    if not isinstance(manifest_entry, Mapping):
        raise BenchmarkError("synthetic fixture manifest binding absent")
    manifest_path = _bound_path(manifest_entry, "synthetic fixture manifest", hash_required=True)
    if (
        manifest_path.is_symlink()
        or required_root.is_symlink()
        or required_root not in manifest_path.parents
    ):
        raise BenchmarkError("synthetic fixture manifest is outside the non-symlink fixture root")
    fixture_root = manifest_path.parent.resolve()
    if fixture_root.parent.resolve() != required_root.resolve():
        raise BenchmarkError(
            "synthetic inputs must use one fixtures/synthetic/<fixture_id> subtree"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _exact_keys(manifest, {"schema_version", "fixture_id", "files"}, "fixture manifest")
    if manifest["schema_version"] != 1 or manifest["fixture_id"] != fixture_root.name:
        raise BenchmarkError("synthetic fixture identity mismatch")
    if not isinstance(manifest["files"], Mapping):
        raise BenchmarkError("synthetic fixture file map is invalid")
    inputs = _input_paths(document)
    observed_paths: set[str] = set()
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink() or fixture_root not in path.resolve().parents:
            raise BenchmarkError(f"arbitrary synthetic relabeling rejected: {label}")
        relative = path.relative_to(fixture_root).as_posix()
        observed_paths.add(relative)
        entry = manifest["files"].get(relative)
        if not isinstance(entry, Mapping) or set(entry) != {"sha256", "rows"}:
            raise BenchmarkError(f"synthetic manifest lacks exact binding: {relative}")
        if sha256(path) != entry["sha256"] or data_row_count(path) != entry["rows"]:
            raise BenchmarkError(f"synthetic input bytes/rows drifted: {relative}")
        if int(entry["rows"]) > int(policy["maximum_rows_per_input"]):
            raise BenchmarkError(f"synthetic input exceeds row limit: {relative}")
        if format_name(path) in {".csv", ".csv.gz"} and "match_id" in csv_header(path):
            _, rows = selected_csv_rows(path, ("match_id",))
            prefix = str(policy["required_match_id_prefix"])
            if any(not row["match_id"].startswith(prefix) for row in rows):
                raise BenchmarkError(f"non-synthetic match ID in {relative}")
    if set(manifest["files"]) != observed_paths:
        raise BenchmarkError("fixture manifest contains missing or unused inputs")
    return {
        "path": relative_to_root(manifest_path),
        "sha256": sha256(manifest_path),
        "files": manifest["files"],
    }


def _panel_metadata(path: Path) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    columns = (
        "match_id",
        "match_date",
        "player_a",
        "player_b",
        "a_rank",
        "b_rank",
        "surface",
        "tourney_level",
        "tourney_anchor_date",
    )
    header, rows = selected_csv_rows(path, columns)
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        match_id = raw["match_id"]
        if match_id in result:
            raise BenchmarkError(f"duplicate panel match_id: {match_id}")
        a, b, swapped = _canonical_ids(raw["player_a"], raw["player_b"])
        result[match_id] = {
            **raw,
            "match_date_value": _date(raw["match_date"], "panel match_date"),
            "canonical_a": a,
            "canonical_b": b,
            "swapped": swapped,
        }
    return result, header


def _feature_targets(
    path: Path,
    tour: str,
    years: set[int],
    panel_metadata: Mapping[str, Mapping[str, Any]],
) -> tuple[list[TargetMatch], list[dict[str, str]], Counter[tuple[int, str]]]:
    columns = (
        "match_id",
        "calendar_year",
        "source_season",
        "match_date",
        "eligible_through_date",
        "player_a",
        "player_b",
        "surface",
        "tourney_level",
        "primary_target",
        "identity_tier",
    )
    _, rows = selected_csv_rows(path, columns)
    selected: list[TargetMatch] = []
    selected_raw: list[dict[str, str]] = []
    fallbacks: Counter[tuple[int, str]] = Counter()
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
        panel = panel_metadata.get(match_id)
        if panel is None:
            raise BenchmarkError(f"feature row absent from panel: {match_id}")
        a, b, _ = _canonical_ids(raw["player_a"], raw["player_b"])
        if (a, b) != (panel["canonical_a"], panel["canonical_b"]):
            raise BenchmarkError(f"{match_id}: feature/panel canonical pair mismatch")
        match_date = _date(raw["match_date"], "feature match_date")
        if match_date != panel["match_date_value"]:
            raise BenchmarkError(f"{match_id}: feature/panel match date mismatch")
        if raw["surface"] != panel["surface"] or raw["tourney_level"] != panel["tourney_level"]:
            raise BenchmarkError(f"{match_id}: feature/panel surface or level mismatch")
        rank_a, rank_b = _finite_optional(panel["a_rank"]), _finite_optional(panel["b_rank"])
        if panel["swapped"]:
            rank_a, rank_b = rank_b, rank_a
        if any(value is None or value <= 0 for value in (rank_a, rank_b)):
            fallbacks[(year, "missing_or_invalid_rank")] += 1
        anchor = str(panel["tourney_anchor_date"]).strip()
        if not anchor:
            raise BenchmarkError(f"{match_id}: missing tournament anchor")
        target = TargetMatch(
            match_id=match_id,
            tour=tour,
            match_date=match_date,
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


def _history_rows(
    path: Path, tour: str, maximum_cutoff: dt.date
) -> tuple[list[HistoryMatch], dict[str, Any]]:
    gate_columns = ("match_id", "match_date", "played", "walkover")
    admitted = (
        "player_a",
        "player_b",
        "surface",
        "tourney_level",
        "a_won",
        "score",
        "retired",
    )
    header, rows = gated_selected_csv_rows(
        path,
        gate_columns,
        admitted,
        lambda raw: (
            _date(raw["match_date"], "history gate date") <= maximum_cutoff
            and _bool(raw["played"], "played")
            and not _bool(raw["walkover"], "walkover")
        ),
    )
    result: list[HistoryMatch] = []
    parsed_ids: list[str] = []
    for raw in rows:
        parsed_ids.append(raw["match_id"])
        a, b, swapped = _canonical_ids(raw["player_a"], raw["player_b"])
        won = _bool(raw["a_won"], "a_won")
        retired = _bool(raw["retired"], "retired")
        result.append(
            HistoryMatch(
                match_id=raw["match_id"],
                tour=tour,
                match_date=_date(raw["match_date"], "match_date"),
                player_a=a,
                player_b=b,
                surface=raw["surface"],
                level=raw["tourney_level"],
                a_won=(not won) if swapped else won,
                score=raw["score"],
                played=True,
                retired=retired,
            )
        )
    return result, {
        "selected_columns": [*gate_columns, *admitted],
        "source_columns": list(header),
        "max_parsed_outcome_date": max(
            (row.match_date for row in result), default=dt.date.min
        ).isoformat(),
        "parsed_outcome_count": len(parsed_ids),
        "parsed_outcome_membership_sha256": key_hash(sorted((tour, item) for item in parsed_ids)),
        "parsed_outcome_match_ids": sorted(parsed_ids),
    }


def _target_membership(rows: Sequence[TargetMatch]) -> tuple[int, str]:
    keys = sorted((str(row.match_date.year), row.match_id) for row in rows)
    return len(keys), key_hash(keys)


def structural_projection(document: Mapping[str, Any]) -> dict[str, Any]:
    """Verify bound real inputs and exact target membership without target values."""
    _validate_document(document)
    result: dict[str, Any] = {
        "benchmark_id": "G-L",
        "status": "verified_structural_projection",
        "target_value_interpretation": "none",
        "tours": {},
    }
    for tour, spec in document["tours"].items():
        inputs = spec["inputs"]
        paths = {
            name: _bound_path(entry, f"{tour} {name}", hash_required=True)
            for name, entry in inputs.items()
            if isinstance(entry, Mapping) and "path" in entry
        }
        features, panel = paths["features"], paths["history_panel"]
        predictor = read_config(paths["predictor_config"])
        dispatch = spec["incumbent_native_dispatch"]
        settings = predictor.get("settings", {})
        observed_tour = settings["tour"] if "tour" in settings else "omitted"
        if (
            predictor.get("experiment_id") != dispatch["experiment_id"]
            or observed_tour != dispatch["tour_setting"]
        ):
            raise BenchmarkError(f"{tour}: incumbent native dispatch mismatch")
        feature_columns = (
            "match_id",
            "calendar_year",
            "source_season",
            "primary_target",
            "identity_tier",
        )
        feature_header, feature_rows = selected_csv_rows(features, feature_columns)
        panel_header = csv_header(panel)
        if not {"match_id", "match_date", "player_a", "player_b", "tourney_anchor_date"} <= set(
            panel_header
        ):
            raise BenchmarkError(f"{tour}: structural panel header contract failed")
        if len(feature_rows) != int(inputs["features"]["rows"]) or data_row_count(panel) != int(
            inputs["history_panel"]["rows"]
        ):
            raise BenchmarkError(f"{tour}: structural row-count mismatch")
        annual: dict[str, Any] = {}
        target_keys: set[tuple[str, str]] = set()
        for year in spec["target_years"]:
            chosen = [
                row
                for row in feature_rows
                if row["identity_tier"] == "primary"
                and _bool(row["primary_target"], "primary_target")
                and int(row["calendar_year"]) == year
                and int(row["source_season"]) == year
            ]
            membership = key_hash(sorted((row["source_season"], row["match_id"]) for row in chosen))
            expected = spec["annual_primary"][str(year)]
            if len(chosen) != int(expected["rows"]) or membership != expected["membership_sha256"]:
                raise BenchmarkError(f"{tour}/{year}: primary membership mismatch")
            annual[str(year)] = {"rows": len(chosen), "membership_sha256": membership}
            target_keys.update((str(year), row["match_id"]) for row in chosen)
            incumbent = resolve_under_root(
                inputs["incumbent_pattern"].format(year=year), label="incumbent"
            )
            bound = spec["incumbent_files"][str(year)]
            require_hash(incumbent, bound["sha256"], label=f"{tour}/{year} incumbent")
            _, incumbent_rows = selected_csv_rows(incumbent, ("season", "match_id", "p_a_wins"))
            if len(incumbent_rows) != int(bound["rows"]):
                raise BenchmarkError(f"{tour}/{year}: incumbent row-count mismatch")
            required = {(str(year), row["match_id"]) for row in chosen}
            if not required <= {(row["season"], row["match_id"]) for row in incumbent_rows}:
                raise BenchmarkError(f"{tour}/{year}: incumbent lacks target keys")
        if len(target_keys) != int(spec["expected_primary_rows"]):
            raise BenchmarkError(f"{tour}: target total mismatch")
        result["tours"][tour] = {
            "bound_input_sha256": {name: sha256(path) for name, path in sorted(paths.items())},
            "feature_columns": len(feature_header),
            "feature_rows": len(feature_rows),
            "panel_columns": len(panel_header),
            "panel_rows": data_row_count(panel),
            "target_rows": len(target_keys),
            "annual": annual,
            "incumbent_coverage": "complete_for_target_membership",
            "native_dispatch": dispatch,
        }
    return result


def project(config_path: str | Path) -> dict[str, Any]:
    config, document, bindings = _load_config(config_path)
    result = structural_projection(document)
    result.update(bindings)
    result["config_path"] = relative_to_root(config)
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
        represented = tuple(range(year - history_years, year))
        training = [row for prior in represented for row in by_year.get(prior, ())]
        if {row.match_date.year for row in training} != set(represented):
            raise BenchmarkError(f"rank logistic {year}: incomplete five-year history")
        if any(row.match_id not in outcomes for row in training):
            raise BenchmarkError(f"rank logistic {year}: missing past outcomes")
        base = np.asarray(
            [rank_base_probability(row.rank_a, row.rank_b) for row in training], dtype=float
        )
        labels = np.asarray([outcomes[row.match_id] for row in training], dtype=float)
        fitted = market.fit(base, labels)
        current = by_year.get(year, [])
        predicted = fitted.predict(
            np.asarray([rank_base_probability(row.rank_a, row.rank_b) for row in current])
        )
        probabilities.update(
            {row.match_id: float(value) for row, value in zip(current, predicted, strict=True)}
        )
        annual = {
            str(prior): {
                "rows": len(by_year[prior]),
                "membership_sha256": key_hash(
                    sorted((str(prior), row.match_id) for row in by_year[prior])
                ),
            }
            for prior in represented
        }
        receipts.append(
            {
                "fit_type": "rank_parameter_fit",
                "procedure": "rank_logistic",
                "outer_year": year,
                "selection_years": list(represented),
                "annual_membership": annual,
                "selection_rows": len(training),
                "selection_membership_sha256": key_hash(
                    sorted((str(row.match_date.year), row.match_id) for row in training)
                ),
                "slope": fitted.market_slope,
                "boundary": fitted.market_slope <= 1e-12,
                "status": "complete",
            }
        )
    return probabilities, receipts


def _incumbent(
    spec: Mapping[str, Any], targets: Sequence[TargetMatch], *, hash_required: bool
) -> dict[str, tuple[float, str]]:
    by_year: defaultdict[int, set[str]] = defaultdict(set)
    for row in targets:
        by_year[row.match_date.year].add(row.match_id)
    result: dict[str, tuple[float, str]] = {}
    for year, required in sorted(by_year.items()):
        path = resolve_under_root(
            spec["inputs"]["incumbent_pattern"].format(year=year), label=f"incumbent {year}"
        )
        bound = spec.get("incumbent_files", {}).get(str(year), {})
        require_hash(
            path, bound.get("sha256") if hash_required else None, label=f"incumbent {year}"
        )
        _, rows = selected_csv_rows(path, ("season", "match_id", "p_a_wins"))
        values: dict[str, tuple[float, str]] = {}
        for raw in rows:
            if raw["season"] != str(year):
                continue
            match_id = raw["match_id"]
            if match_id in values:
                raise BenchmarkError(f"duplicate incumbent key: {year}/{match_id}")
            token = raw["p_a_wins"]
            value = float(token)
            if not math.isfinite(value) or not 0 < value < 1:
                raise BenchmarkError(f"invalid incumbent probability: {year}/{match_id}")
            values[match_id] = (value, token)
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
) -> tuple[dict[tuple[int, str], dict[str, Any]], list[dict[str, Any]]]:
    by_year: defaultdict[int, list[TargetMatch]] = defaultdict(list)
    for target in targets:
        by_year[target.match_date.year].append(target)
    products: dict[tuple[int, str], dict[str, Any]] = {}
    receipts: list[dict[str, Any]] = []
    for outer_year in target_years:
        required = tuple(range(outer_year - years_back, outer_year))
        if any(not by_year[year] for year in required):
            raise BenchmarkError(f"calibration {outer_year}: incomplete calendar-year history")
        for procedure in COMPARATORS:
            if any(
                row.match_id not in outcomes or row.match_id not in raw[procedure]
                for year in required
                for row in by_year[year]
            ):
                raise BenchmarkError(
                    f"calibration {outer_year}/{procedure}: missing past selection values"
                )
            yearly_p = {
                year: [raw[procedure][row.match_id] for row in by_year[year]] for year in required
            }
            yearly_y = {
                year: [outcomes[row.match_id] for row in by_year[year]] for year in required
            }
            fitted = legacy_pipeline.fit_nonnegative_slope(yearly_p, yearly_y, required)
            if (
                fitted.get("status") != "complete"
                or not isinstance(fitted.get("slope"), (int, float))
                or not math.isfinite(fitted["slope"])
            ):
                raise BenchmarkError(
                    f"calibration failed: {outer_year}/{procedure}: {fitted.get('error')}"
                )
            products[(outer_year, procedure)] = fitted
            annual = {
                str(year): {
                    "rows": len(by_year[year]),
                    "membership_sha256": key_hash(
                        sorted((str(year), row.match_id) for row in by_year[year])
                    ),
                }
                for year in required
            }
            union = [row for year in required for row in by_year[year]]
            receipts.append(
                {
                    "fit_type": "common_equal_year_calibration",
                    "procedure": procedure,
                    "outer_year": outer_year,
                    "selection_years": list(required),
                    "annual_membership": annual,
                    "selection_rows": len(union),
                    "selection_membership_sha256": key_hash(
                        sorted((str(row.match_date.year), row.match_id) for row in union)
                    ),
                    "slope": fitted["slope"],
                    "logit_clip_count": fitted["probability_clip_count"],
                    "derivative_at_zero": fitted["derivative_at_zero"],
                    "root_bracket": fitted["root_bracket"],
                    "boundary": fitted["slope"] == 0.0,
                    "status": "complete",
                }
            )
    return products, receipts


def _fallback_rows(
    tour: str,
    years: Sequence[int],
    targets: Sequence[TargetMatch],
    history: Sequence[HistoryMatch],
    rank_missing: Counter[tuple[int, str]],
) -> list[dict[str, Any]]:
    counts: Counter[tuple[int, str, str]] = Counter()
    for row in targets:
        year = row.match_date.year
        if row.surface not in SUPPORTED_SURFACES:
            counts[(year, "k32_pooled", "unknown_surface_overall_only")] += 1
            counts[(year, "fivethirtyeight_surface", "unknown_surface_overall_only")] += 1
        prior_players = {
            player
            for item in history
            if item.match_date <= row.eligible_through_date
            for player in (item.player_a, item.player_b)
        }
        fresh = int(row.player_a not in prior_players) + int(row.player_b not in prior_players)
        for service in ("k32_pooled", "kovalchik_overall_major", "fivethirtyeight_surface", "welo"):
            counts[(year, service, "fresh_player_initialization")] += fresh
    for (year, reason), count in rank_missing.items():
        counts[(year, "rank_logistic", reason)] += count
    for item in history:
        if winner_game_share(item.score) is None:
            counts[(item.match_date.year, "welo", "unparsed_games_standard_update")] += 1
    rows: list[dict[str, Any]] = []
    for year in sorted(years):
        for service, reasons in FALLBACK_REASONS.items():
            for reason in reasons:
                rows.append(
                    {
                        "tour": tour,
                        "calendar_year": year,
                        "service": service,
                        "scope": "target"
                        if reason != "unparsed_games_standard_update"
                        else "history_update",
                        "reason": reason,
                        "count": counts[(year, service, reason)],
                    }
                )
    return rows


def _manifest_files(directory: Path, *, exclude: set[str] | None = None) -> dict[str, str]:
    omitted = exclude or set()
    return {
        path.relative_to(directory).as_posix(): sha256(path)
        for path in sorted(item for item in directory.rglob("*") if item.is_file())
        if path.relative_to(directory).as_posix() not in omitted
    }


def _source_manifest(document: Mapping[str, Any], *, synthetic: bool) -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for label, path in sorted(_input_paths(document).items()):
        if not path.is_file():
            raise BenchmarkError(f"source absent: {label}: {path}")
        sources[label] = {"path": relative_to_root(path), "sha256": sha256(path)}
    return {
        "schema_version": 1,
        "source_bindings": sources,
        "report_only_sources_hashed_not_value_parsed": sorted(
            label for label in sources if label.endswith(":labels") or label.endswith(":prices")
        ),
        "synthetic": synthetic,
    }


def _scan_json(value: Any, prefix: str = "$", *, sensitive: bool = True) -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            here = f"{prefix}.{key}"
            if (
                METRIC.search(str(key))
                and isinstance(child, (int, float))
                and not isinstance(child, bool)
            ):
                findings.append(here)
            if sensitive and SENSITIVE.search(str(key)):
                findings.append(here)
            findings.extend(_scan_json(child, here, sensitive=sensitive))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_scan_json(child, f"{prefix}[{index}]", sensitive=sensitive))
    return findings


def _content_scan(forecast_root: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    scanned: list[str] = []
    for path in sorted(item for item in forecast_root.rglob("*") if item.is_file()):
        relative = path.relative_to(forecast_root).as_posix()
        kind = format_name(path)
        scanned.append(relative)
        hits: list[str] = []
        if kind in {".csv", ".csv.gz"}:
            hits = [
                f"header:{name}"
                for name in csv_header(path)
                if METRIC.search(name) or SENSITIVE.search(name)
            ]
        else:
            sensitive = relative not in {
                "access_receipt.json",
                "fit_receipts.json",
                "source_manifest.json",
            }
            for prefix, value in json_values(path):
                hits.extend(f"{prefix}:{item}" for item in _scan_json(value, sensitive=sensitive))
        if hits:
            findings.append({"artifact": relative, "locations": hits})
    return {"supported_formats": list(SUPPORTED_SUFFIXES), "scanned": scanned, "findings": findings}


def _validate_forecast_payloads(forecast_root: Path, manifest: Mapping[str, Any]) -> None:
    header, predictions = selected_csv_rows(forecast_root / "predictions.csv", PREDICTION_FIELDS)
    if tuple(header) != PREDICTION_FIELDS or len(predictions) != manifest["rows"]:
        raise BenchmarkError("prediction schema or row count mismatch")
    prediction_keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in predictions:
        key = (row["tour"], row["year"], row["match_id"])
        if key in seen:
            raise BenchmarkError(f"duplicate saved prediction key: {key}")
        seen.add(key)
        prediction_keys.append((f"{row['tour']}:{row['year']}", row["match_id"]))
        for procedure in PROCEDURES:
            raw = float(row[f"raw_{procedure}"])
            calibrated = float(row[f"calibrated_{procedure}"])
            if not all(math.isfinite(value) and 0 <= value <= 1 for value in (raw, calibrated)):
                raise BenchmarkError("invalid saved sports probability")
            if procedure == "incumbent" and row["raw_incumbent"] != row["calibrated_incumbent"]:
                raise BenchmarkError("incumbent aliases differ")
    if key_hash(sorted(prediction_keys)) != manifest["membership_sha256"]:
        raise BenchmarkError("prediction membership mismatch")

    fits = json.loads((forecast_root / "fit_receipts.json").read_text(encoding="utf-8"))
    if not isinstance(fits, list) or not fits:
        raise BenchmarkError("fit receipts are absent")
    rank_keys = {
        "tour",
        "fit_type",
        "procedure",
        "outer_year",
        "selection_years",
        "annual_membership",
        "selection_rows",
        "selection_membership_sha256",
        "slope",
        "boundary",
        "status",
    }
    calibration_keys = rank_keys | {"logit_clip_count", "derivative_at_zero", "root_bracket"}
    for receipt in fits:
        if not isinstance(receipt, Mapping):
            raise BenchmarkError("fit receipt is not an object")
        if receipt.get("fit_type") not in {
            "rank_parameter_fit",
            "common_equal_year_calibration",
        }:
            raise BenchmarkError("unknown fit receipt type")
        expected = (
            calibration_keys
            if receipt.get("fit_type") == "common_equal_year_calibration"
            else rank_keys
        )
        _exact_keys(receipt, expected, "fit receipt")
        if receipt["status"] != "complete" or not isinstance(receipt["selection_rows"], int):
            raise BenchmarkError("fit receipt is incomplete")

    fallback_header, fallback_rows = selected_csv_rows(
        forecast_root / "fallback_counts.csv", FALLBACK_FIELDS
    )
    if tuple(fallback_header) != FALLBACK_FIELDS or not fallback_rows:
        raise BenchmarkError("fallback receipt schema mismatch")
    fallback_keys: set[tuple[str, ...]] = set()
    for row in fallback_rows:
        key = tuple(row[name] for name in FALLBACK_FIELDS[:-1])
        if key in fallback_keys or int(row["count"]) < 0:
            raise BenchmarkError("fallback receipt key/count invalid")
        fallback_keys.add(key)

    access = json.loads((forecast_root / "access_receipt.json").read_text(encoding="utf-8"))
    if not isinstance(access, Mapping):
        raise BenchmarkError("access receipt is not an object")
    _exact_keys(
        access,
        {"schema_version", "forecast_value_access", "excluded_column_categories", "tours"},
        "access receipt",
    )
    if access["schema_version"] != 1 or access["forecast_value_access"] != "sports_columns_only":
        raise BenchmarkError("access receipt semantics mismatch")
    tour_keys = {
        "selected_columns",
        "source_columns",
        "max_parsed_outcome_date",
        "parsed_outcome_count",
        "parsed_outcome_membership_sha256",
        "parsed_outcome_match_ids",
        "opened_paths",
        "metadata_selected_columns",
        "feature_selected_columns",
        "incumbent_selected_columns",
        "panel_path_contains_price_columns",
        "price_columns_numerically_accessed",
        "purpose_memberships",
    }
    for tour, receipt in access["tours"].items():
        if tour not in {"ATP", "WTA"} or not isinstance(receipt, Mapping):
            raise BenchmarkError("access receipt tour invalid")
        _exact_keys(receipt, tour_keys, "tour access receipt")
        if receipt["price_columns_numerically_accessed"] is not False:
            raise BenchmarkError("forecast accessed price values")
        purposes = receipt["purpose_memberships"]
        if set(purposes) != {"rating_targets", "forecast_targets", "rank_and_calibration_past"}:
            raise BenchmarkError("access purpose membership schema mismatch")
        for membership in purposes.values():
            if not isinstance(membership, Mapping) or set(membership) != {
                "rows",
                "membership_sha256",
            }:
                raise BenchmarkError("access purpose membership malformed")


def _validate_stage_manifest(
    forecast_root: Path,
    config: Path,
    document: Mapping[str, Any],
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_path = forecast_root / "stage_manifest.json"
    if not manifest_path.is_file():
        raise BenchmarkError("completed forecast stage manifest is absent")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise BenchmarkError("forecast stage manifest must be an object")
    expected_keys = {
        "schema_version",
        "completion",
        "benchmark_id",
        "attempt",
        "proposal_status",
        "invocation_config_sha256",
        "effective_config_sha256",
        "authority_bindings",
        "effective_contract",
        "execution_binding",
        "source_manifest_sha256",
        "artifacts",
        "rows",
        "membership_sha256",
    }
    _exact_keys(manifest, expected_keys, "forecast stage manifest")
    if manifest["schema_version"] != 2 or manifest["completion"] != "complete":
        raise BenchmarkError("forecast stage is not complete")
    if manifest["benchmark_id"] != "G-L" or not isinstance(manifest["attempt"], str):
        raise BenchmarkError("forecast stage identity mismatch")
    if manifest["proposal_status"] != document["proposal_status"]:
        raise BenchmarkError("forecast proposal status mismatch")
    if manifest["invocation_config_sha256"] != sha256(config):
        raise BenchmarkError("invocation config changed after forecast")
    if manifest["effective_config_sha256"] != canonical_hash(document):
        raise BenchmarkError("effective config changed after forecast")
    if manifest["authority_bindings"] != bindings:
        raise BenchmarkError("forecast authority bindings mismatch")
    if manifest["effective_contract"] != {
        "procedures": list(PROCEDURES),
        "constants": dict(EXPECTED_CONSTANTS),
        "anchor_basis": "tourney_anchor_date_event_anchor_proxy",
    }:
        raise BenchmarkError("forecast executable contract mismatch")
    if manifest["execution_binding"] != _execution_binding():
        raise BenchmarkError("effective code or dependencies changed after forecast")
    source_path = forecast_root / "source_manifest.json"
    if manifest["source_manifest_sha256"] != sha256(source_path):
        raise BenchmarkError("forecast source manifest hash mismatch")
    expected_artifacts = _manifest_files(forecast_root, exclude={"stage_manifest.json"})
    if manifest["artifacts"] != expected_artifacts or set(
        expected_artifacts
    ) != FORECAST_ARTIFACTS - {"stage_manifest.json"}:
        raise BenchmarkError("forecast artifact allowlist/hash mismatch")
    if not isinstance(manifest["rows"], int) or manifest["rows"] <= 0:
        raise BenchmarkError("forecast stage has no rows")
    if (
        not isinstance(manifest["membership_sha256"], str)
        or len(manifest["membership_sha256"]) != 64
    ):
        raise BenchmarkError("forecast membership digest invalid")
    _validate_forecast_payloads(forecast_root, manifest)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    expected_source = _source_manifest(
        document, synthetic=document["proposal_status"] == "synthetic_rehearsal"
    )
    if source != expected_source:
        raise BenchmarkError("source bytes changed or source manifest malformed")
    return dict(manifest)


def forecast(config_path: str | Path, attempt: str) -> Path:
    config, document, bindings = _load_config(config_path)
    synthetic = document.get("proposal_status") == "synthetic_rehearsal"
    if synthetic:
        bindings = {**bindings, "fixture_manifest": _validate_synthetic(document)}
    else:
        if document.get("proposal_status") != "frozen_for_real_execution":
            raise BenchmarkError("real forecast refused: proposal is not frozen_for_real_execution")
        _validate_reviewed_runtime(document)
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
        fit_receipts: list[dict[str, Any]] = []
        fallbacks: list[dict[str, Any]] = []
        access: dict[str, Any] = {
            "schema_version": 1,
            "forecast_value_access": "sports_columns_only",
            "excluded_column_categories": [
                "report_labels",
                "outcomes_after_cutoff",
                "prices",
                "odds",
                "scores_as_metrics",
            ],
            "tours": {},
        }
        years_back = int(document["constants"]["calibration_years"])
        parameter_history = int(document["constants"]["parameter_history_years"])
        for tour, spec in document["tours"].items():
            target_years = [int(year) for year in spec["target_years"]]
            raw_years = set(range(min(target_years) - years_back, max(target_years) + 1))
            feature_years = set(range(min(raw_years) - parameter_history, max(raw_years) + 1))
            inputs = spec["inputs"]
            features_path = _bound_path(
                inputs["features"], f"{tour} features", hash_required=not synthetic
            )
            panel_path = _bound_path(
                inputs["history_panel"], f"{tour} history panel", hash_required=not synthetic
            )
            metadata, panel_header = _panel_metadata(panel_path)
            all_targets, _, rank_missing = _feature_targets(
                features_path, tour, feature_years, metadata
            )
            targets = [row for row in all_targets if row.match_date.year in raw_years]
            target_rows = [row for row in targets if row.match_date.year in set(target_years)]
            if {row.match_date.year for row in target_rows} != set(target_years):
                raise BenchmarkError(f"{tour}: one or more target years are empty")
            maximum_cutoff = max(row.eligible_through_date for row in targets)
            history, history_access = _history_rows(panel_path, tour, maximum_cutoff)
            outcomes = {row.match_id: int(row.a_won) for row in history}
            rating_raw, _ = rating_forecasts(history, targets, spec.get("major_level_codes", ["G"]))
            raw: dict[str, dict[str, float]] = {
                procedure: {match_id: values[procedure] for match_id, values in rating_raw.items()}
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
            incumbent = _incumbent(spec, target_rows, hash_required=not synthetic)
            raw["incumbent"] = {match_id: value for match_id, (value, _) in incumbent.items()}
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
                    raw_value = raw[procedure][row.match_id]
                    if not math.isfinite(raw_value) or not 0 <= raw_value <= 1:
                        raise BenchmarkError(
                            f"invalid raw probability: {tour}/{row.match_id}/{procedure}"
                        )
                    if procedure == "incumbent":
                        token = incumbent[row.match_id][1]
                        output["raw_incumbent"] = token
                        output["calibrated_incumbent"] = token
                    else:
                        output[f"raw_{procedure}"] = raw_value
                        output[f"calibrated_{procedure}"] = float(
                            legacy_pipeline.apply_slope(
                                [raw_value], float(calibration[(year, procedure)]["slope"])
                            )[0]
                        )
                all_predictions.append(output)
            fit_receipts.extend({"tour": tour, **row} for row in rank_receipts)
            fit_receipts.extend({"tour": tour, **row} for row in calibration_receipts)
            fallbacks.extend(
                _fallback_rows(tour, sorted(raw_years), targets, history, rank_missing)
            )
            history_access.update(
                {
                    "opened_paths": sorted(
                        {
                            relative_to_root(path)
                            for label, path in _input_paths(document).items()
                            if label.startswith(f"{tour}:")
                        }
                    ),
                    "metadata_selected_columns": [
                        "match_id",
                        "match_date",
                        "player_a",
                        "player_b",
                        "a_rank",
                        "b_rank",
                        "surface",
                        "tourney_level",
                        "tourney_anchor_date",
                    ],
                    "feature_selected_columns": [
                        "match_id",
                        "calendar_year",
                        "source_season",
                        "match_date",
                        "eligible_through_date",
                        "player_a",
                        "player_b",
                        "surface",
                        "tourney_level",
                        "primary_target",
                        "identity_tier",
                    ],
                    "incumbent_selected_columns": ["season", "match_id", "p_a_wins"],
                    "panel_path_contains_price_columns": any(
                        re.search(r"price|odds|decimal|pinnacle|^PS_", name, re.I)
                        for name in panel_header
                    ),
                    "price_columns_numerically_accessed": False,
                    "purpose_memberships": {
                        "rating_targets": {
                            "rows": len(targets),
                            "membership_sha256": _target_membership(targets)[1],
                        },
                        "forecast_targets": {
                            "rows": len(target_rows),
                            "membership_sha256": _target_membership(target_rows)[1],
                        },
                        "rank_and_calibration_past": {
                            "rows": sum(
                                1 for item in targets if item.match_date.year < max(target_years)
                            ),
                            "membership_sha256": _target_membership(
                                [
                                    item
                                    for item in targets
                                    if item.match_date.year < max(target_years)
                                ]
                            )[1],
                        },
                    },
                }
            )
            access["tours"][tour] = history_access
        atomic_csv(forecast_root / "predictions.csv", PREDICTION_FIELDS, all_predictions)
        atomic_json(forecast_root / "fit_receipts.json", fit_receipts)
        atomic_csv(forecast_root / "fallback_counts.csv", FALLBACK_FIELDS, fallbacks)
        atomic_json(forecast_root / "access_receipt.json", access)
        source = _source_manifest(document, synthetic=synthetic)
        atomic_json(forecast_root / "source_manifest.json", source)
        membership = key_hash(
            sorted((f"{row['tour']}:{row['year']}", row["match_id"]) for row in all_predictions)
        )
        stage_manifest = {
            "schema_version": 2,
            "completion": "complete",
            "benchmark_id": "G-L",
            "attempt": attempt,
            "proposal_status": document["proposal_status"],
            "invocation_config_sha256": sha256(config),
            "effective_config_sha256": canonical_hash(document),
            "authority_bindings": bindings,
            "effective_contract": {
                "procedures": list(PROCEDURES),
                "constants": dict(EXPECTED_CONSTANTS),
                "anchor_basis": "tourney_anchor_date_event_anchor_proxy",
            },
            "execution_binding": _execution_binding(),
            "source_manifest_sha256": sha256(forecast_root / "source_manifest.json"),
            "artifacts": _manifest_files(forecast_root),
            "rows": len(all_predictions),
            "membership_sha256": membership,
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
    config, document, bindings = _load_config(config_path)
    if document["proposal_status"] == "synthetic_rehearsal":
        bindings = {**bindings, "fixture_manifest": _validate_synthetic(document)}
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
        if (attempt_root / "failure.json").exists() or any(forecast_root.glob("*failure*")):
            raise BenchmarkError("failed forecast cannot cross barrier")
        scan = _content_scan(forecast_root)
        if scan["findings"]:
            raise BenchmarkError(
                f"forecast barrier rejected metric or sensitive content: {scan['findings']}"
            )
        observed_names = {path.name for path in forecast_root.iterdir() if path.is_file()}
        if observed_names != FORECAST_ARTIFACTS or any(
            path.is_dir() for path in forecast_root.iterdir()
        ):
            raise BenchmarkError("forecast barrier rejected artifact allowlist mismatch")
        manifest = _validate_stage_manifest(forecast_root, config, document, bindings)
        barrier_root = attempt_root / "barrier"
        barrier_root.mkdir()
        atomic_json(
            barrier_root / "commitment.json",
            {
                "schema_version": 2,
                "completion": "committed",
                "benchmark_id": "G-L",
                "attempt": attempt,
                "invocation_config_sha256": sha256(config),
                "effective_config_sha256": canonical_hash(document),
                "forecast_manifest_sha256": sha256(forecast_root / "stage_manifest.json"),
                "forecast_artifacts": _manifest_files(forecast_root),
                "authority_bindings": bindings,
                "execution_binding": _execution_binding(),
                "source_manifest_sha256": manifest["source_manifest_sha256"],
                "content_scan": scan,
            },
        )
    except Exception as exc:
        atomic_json(
            attempt_root / "barrier_failure.json",
            {"stage": "barrier", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    return barrier_root


def _verify_barrier(
    attempt_root: Path,
    config: Path,
    document: Mapping[str, Any],
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    commitment_path = attempt_root / "barrier" / "commitment.json"
    if not commitment_path.is_file():
        raise BenchmarkError("barrier commitment is absent")
    commitment = json.loads(commitment_path.read_text(encoding="utf-8"))
    expected = {
        "schema_version",
        "completion",
        "benchmark_id",
        "attempt",
        "invocation_config_sha256",
        "effective_config_sha256",
        "forecast_manifest_sha256",
        "forecast_artifacts",
        "authority_bindings",
        "execution_binding",
        "source_manifest_sha256",
        "content_scan",
    }
    _exact_keys(commitment, expected, "barrier commitment")
    if commitment["schema_version"] != 2 or commitment["completion"] != "committed":
        raise BenchmarkError("barrier is not a completed commitment")
    if commitment["invocation_config_sha256"] != sha256(config) or commitment[
        "effective_config_sha256"
    ] != canonical_hash(document):
        raise BenchmarkError("config changed after barrier")
    if commitment["authority_bindings"] != bindings:
        raise BenchmarkError("authority bindings changed after barrier")
    if commitment["execution_binding"] != _execution_binding():
        raise BenchmarkError("effective code or dependencies changed after barrier")
    forecast_root = attempt_root / "forecast"
    if commitment["forecast_artifacts"] != _manifest_files(forecast_root):
        raise BenchmarkError("forecast bytes changed after barrier")
    manifest = _validate_stage_manifest(forecast_root, config, document, bindings)
    if commitment["forecast_manifest_sha256"] != sha256(forecast_root / "stage_manifest.json"):
        raise BenchmarkError("forecast manifest changed after barrier")
    scan = _content_scan(forecast_root)
    if scan != commitment["content_scan"] or scan["findings"]:
        raise BenchmarkError("forecast content no longer passes barrier")
    if commitment["source_manifest_sha256"] != manifest["source_manifest_sha256"]:
        raise BenchmarkError("source manifest changed after barrier")
    return commitment


def _labels(path: Path) -> dict[str, int]:
    _, rows = selected_csv_rows(path, ("match_id", "a_won"))
    result: dict[str, int] = {}
    for row in rows:
        if row["match_id"] in result:
            raise BenchmarkError(f"duplicate target label: {row['match_id']}")
        result[row["match_id"]] = int(_bool(row["a_won"], "a_won"))
    return result


def _prices(path: Path, market_contract: Mapping[str, Any]) -> dict[str, float]:
    valid = str(market_contract["valid_column"])
    column_a = str(market_contract["decimal_a_column"])
    column_b = str(market_contract["decimal_b_column"])
    _, rows = selected_csv_rows(
        path, ("match_id", "player_a", "player_b", valid, column_a, column_b)
    )
    result: dict[str, float] = {}
    for row in rows:
        if not _bool(row[valid], valid):
            continue
        if row["match_id"] in result:
            raise BenchmarkError(f"duplicate priced key: {row['match_id']}")
        a, b = float(row[column_a]), float(row[column_b])
        if not math.isfinite(a) or not math.isfinite(b) or a <= 1 or b <= 1:
            raise BenchmarkError(f"invalid decimal odds: {row['match_id']}")
        q_a, q_b = 1.0 / a, 1.0 / b
        _, _, swapped = _canonical_ids(row["player_a"], row["player_b"])
        if swapped:
            q_a, q_b = q_b, q_a
        result[row["match_id"]] = q_a / (q_a + q_b)
    return result


def _market_predictions(
    targets: Sequence[TargetMatch],
    labels: Mapping[str, int],
    prices: Mapping[str, float],
    target_years: Sequence[int],
    years_back: int,
) -> tuple[dict[str, float], dict[str, float], list[dict[str, Any]]]:
    by_year: defaultdict[int, list[TargetMatch]] = defaultdict(list)
    for row in targets:
        if row.match_id in prices:
            by_year[row.match_date.year].append(row)
    raw = {row.match_id: prices[row.match_id] for year in target_years for row in by_year[year]}
    calibrated: dict[str, float] = {}
    receipts: list[dict[str, Any]] = []
    for outer_year in target_years:
        required = tuple(range(outer_year - years_back, outer_year))
        if any(not by_year[year] for year in required):
            raise BenchmarkError(f"market calibration {outer_year}: incomplete priced history")
        if any(row.match_id not in labels for year in required for row in by_year[year]):
            raise BenchmarkError(f"market calibration {outer_year}: missing past labels")
        fit = legacy_pipeline.fit_nonnegative_slope(
            {year: [prices[row.match_id] for row in by_year[year]] for year in required},
            {year: [labels[row.match_id] for row in by_year[year]] for year in required},
            required,
        )
        if fit.get("status") != "complete":
            raise BenchmarkError(f"market calibration failed: {outer_year}: {fit.get('error')}")
        current = by_year[outer_year]
        values = legacy_pipeline.apply_slope(
            [prices[row.match_id] for row in current], float(fit["slope"])
        )
        calibrated.update(
            {row.match_id: float(value) for row, value in zip(current, values, strict=True)}
        )
        union = [row for year in required for row in by_year[year]]
        receipts.append(
            {
                "outer_year": outer_year,
                "selection_years": list(required),
                "annual_membership": {
                    str(year): {
                        "rows": len(by_year[year]),
                        "membership_sha256": key_hash(
                            sorted((str(year), row.match_id) for row in by_year[year])
                        ),
                    }
                    for year in required
                },
                "selection_rows": len(union),
                "selection_membership_sha256": key_hash(
                    sorted((str(row.match_date.year), row.match_id) for row in union)
                ),
                "slope": fit["slope"],
                "logit_clip_count": fit["probability_clip_count"],
                "root_bracket": fit["root_bracket"],
                "boundary": fit["slope"] == 0.0,
                "status": "complete",
            }
        )
    return raw, calibrated, receipts


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise BenchmarkError("cannot summarize an empty score cell")
    return float(np.mean(np.asarray(values, dtype=float)))


def _score_table(
    entries: Sequence[dict[str, Any]], procedures: Sequence[str], clip: float
) -> dict[str, Any]:
    if not entries:
        raise BenchmarkError("cannot score an empty paired cohort")
    annual: dict[str, Any] = {}
    for year in sorted({int(row["year"]) for row in entries}):
        year_rows = [row for row in entries if int(row["year"]) == year]
        procedure_scores: dict[str, Any] = {}
        for procedure in procedures:
            probabilities = [float(row["probabilities"][procedure]) for row in year_rows]
            outcomes = [int(row["outcome"]) for row in year_rows]
            procedure_scores[procedure] = {
                "log_loss": _mean(
                    [log_loss(p, y, clip) for p, y in zip(probabilities, outcomes, strict=True)]
                ),
                "brier": _mean(
                    [(p - y) ** 2 for p, y in zip(probabilities, outcomes, strict=True)]
                ),
                "log_loss_clip_count": sum(p < clip or p > 1 - clip for p in probabilities),
            }
        annual[str(year)] = {"n": len(year_rows), "procedures": procedure_scores}
    equal_year: dict[str, Any] = {}
    match_weighted: dict[str, Any] = {}
    for procedure in procedures:
        equal_year[procedure] = {
            metric: _mean([annual[year]["procedures"][procedure][metric] for year in annual])
            for metric in ("log_loss", "brier")
        }
        probabilities = [float(row["probabilities"][procedure]) for row in entries]
        outcomes = [int(row["outcome"]) for row in entries]
        match_weighted[procedure] = {
            "log_loss": _mean(
                [log_loss(p, y, clip) for p, y in zip(probabilities, outcomes, strict=True)]
            ),
            "brier": _mean([(p - y) ** 2 for p, y in zip(probabilities, outcomes, strict=True)]),
        }
    contrasts: dict[str, Any] = {}
    for comparator in procedures:
        if comparator == "incumbent":
            continue
        contrasts[f"incumbent_minus_{comparator}"] = {
            "annual": {
                year: {
                    metric: annual[year]["procedures"]["incumbent"][metric]
                    - annual[year]["procedures"][comparator][metric]
                    for metric in ("log_loss", "brier")
                }
                for year in annual
            },
            "equal_year": {
                metric: equal_year["incumbent"][metric] - equal_year[comparator][metric]
                for metric in ("log_loss", "brier")
            },
            "match_weighted": {
                metric: match_weighted["incumbent"][metric] - match_weighted[comparator][metric]
                for metric in ("log_loss", "brier")
            },
        }
    return {
        "annual": annual,
        "equal_year": equal_year,
        "match_weighted": match_weighted,
        "contrasts": contrasts,
        "coverage": {
            procedure: {"rows": len(entries), "fraction": 1.0} for procedure in procedures
        },
        "clipping_counts": {
            procedure: {
                "natural_log_loss": sum(
                    annual[year]["procedures"][procedure]["log_loss_clip_count"] for year in annual
                ),
                "brier": 0,
            }
            for procedure in procedures
        },
    }


def _fixed_sensitivities(entries: Sequence[dict[str, Any]], clip: float) -> dict[str, Any]:
    years = sorted({int(row["year"]) for row in entries})
    contrasts = {name: ("incumbent", name) for name in COMPARATORS}

    def estimates(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
        scored = [
            ScoredRow(
                year=int(row["year"]),
                week=row["week"],
                values={
                    name: log_loss(float(row["probabilities"][name]), int(row["outcome"]), clip)
                    for name in PROCEDURES
                },
            )
            for row in rows
        ]
        by_year: defaultdict[int, list[ScoredRow]] = defaultdict(list)
        for row in scored:
            by_year[row.year].append(row)
        means = {
            name: _mean(
                [_mean([item.values[name] for item in year_rows]) for year_rows in by_year.values()]
            )
            for name in PROCEDURES
        }
        return {name: means[left] - means[right] for name, (left, right) in contrasts.items()}

    loo = {
        str(year): estimates([row for row in entries if int(row["year"]) != year])
        for year in years
        if len(years) > 1
    }
    return {
        "semantics": "fixed_predictions_no_refit_not_independent_fold",
        "leave_one_year_out": loo,
        "leave_2020_out": loo.get("2020") if 2020 in years else None,
    }


def _validate_report_completion(
    report_root: Path, config: Path, document: Mapping[str, Any], attempt: str
) -> None:
    path = report_root / "stage_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version",
        "completion",
        "benchmark_id",
        "attempt",
        "invocation_config_sha256",
        "effective_config_sha256",
        "barrier_sha256",
        "forecast_manifest_sha256",
        "execution_binding",
        "artifacts",
        "report_only_values_read_after_barrier",
    }
    _exact_keys(manifest, expected, "report stage manifest")
    if (
        manifest["schema_version"] != 2
        or manifest["completion"] != "complete"
        or manifest["benchmark_id"] != "G-L"
        or manifest["attempt"] != attempt
        or manifest["invocation_config_sha256"] != sha256(config)
        or manifest["effective_config_sha256"] != canonical_hash(document)
        or manifest["execution_binding"] != _execution_binding()
        or manifest["artifacts"] != _manifest_files(report_root, exclude={"stage_manifest.json"})
        or set(manifest["artifacts"]) != {"benchmark_report.json"}
        or manifest["report_only_values_read_after_barrier"] is not True
    ):
        raise BenchmarkError("report completion manifest validation failed")


def report(config_path: str | Path, attempt: str) -> Path:
    config, document, bindings = _load_config(config_path)
    synthetic = document.get("proposal_status") == "synthetic_rehearsal"
    if synthetic:
        bindings = {**bindings, "fixture_manifest": _validate_synthetic(document)}
    elif document.get("proposal_status") != "frozen_for_real_execution":
        raise BenchmarkError("real report refused: proposal is not frozen_for_real_execution")
    else:
        _validate_reviewed_runtime(document)
    attempt_root = resolve_output_under_root(
        Path(document["output_root"]) / attempt, label="benchmark attempt"
    )
    if (attempt_root / "report_failure.json").exists() or (attempt_root / "report").exists():
        raise BenchmarkError("report attempt already closed and is immutable")
    try:
        commitment = _verify_barrier(attempt_root, config, document, bindings)
    except Exception as exc:
        atomic_json(
            attempt_root / "report_failure.json",
            {"stage": "report_preflight", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    report_root = attempt_root / "report"
    report_root.mkdir()
    try:
        _, predictions = selected_csv_rows(
            attempt_root / "forecast/predictions.csv", PREDICTION_FIELDS
        )
        _, saved_fallbacks = selected_csv_rows(
            attempt_root / "forecast/fallback_counts.csv", FALLBACK_FIELDS
        )
        summary: dict[str, Any] = {
            "schema_version": 2,
            "benchmark_id": "G-L",
            "attempt": attempt,
            "proposal_status": document["proposal_status"],
            "claim_scope": "aligned_rank_elo_diagnostic_not_state_of_the_art",
            "inference_scope": {
                "family": "five_calibrated_sports_log_loss_contrasts_per_tour",
                "brier_inference": False,
                "conditional_limits": "fixed forecasts and declared week dependence only; no fit, selection, or source-choice uncertainty",
                "deferred": ["unordered_player_dyad", "player_cluster", "fitting_uncertainty"],
            },
            "admission_failures": {
                "ingram": "Bayesian point-based aggregate serve/return replay contract absent",
                "ultimate_tennis_statistics": "dated redistributable feed or faithful public reconstruction absent; distinct from UTR",
                "public_feature_ml": "separate feature and nested-selection freeze absent",
            },
            "tours": {},
        }
        inference = document["inference"]
        clip = float(document["constants"]["scoring_clip"])
        years_back = int(document["constants"]["calibration_years"])
        for tour, spec in document["tours"].items():
            inputs = spec["inputs"]
            labels_path = _bound_path(
                inputs["labels"], f"{tour} labels", hash_required=not synthetic
            )
            prices_path = _bound_path(
                inputs["prices"], f"{tour} prices", hash_required=not synthetic
            )
            features_path = _bound_path(
                inputs["features"], f"{tour} features", hash_required=not synthetic
            )
            panel_path = _bound_path(
                inputs["history_panel"], f"{tour} panel", hash_required=not synthetic
            )
            labels = _labels(labels_path)
            prices = _prices(prices_path, document["market_references"])
            target_years = [int(year) for year in spec["target_years"]]
            metadata, _ = _panel_metadata(panel_path)
            market_years = set(range(min(target_years) - years_back, max(target_years) + 1))
            market_targets, _, _ = _feature_targets(features_path, tour, market_years, metadata)
            market_raw, market_cal, market_receipts = _market_predictions(
                market_targets, labels, prices, target_years, years_back
            )
            tour_rows = [row for row in predictions if row["tour"] == tour]
            if len({row["match_id"] for row in tour_rows}) != len(tour_rows):
                raise BenchmarkError(f"{tour}: duplicate prediction membership")
            required_ids = {row["match_id"] for row in tour_rows}
            if not required_ids <= set(labels):
                raise BenchmarkError(f"{tour}: labels missing prediction keys")
            entries_by_variant: dict[str, list[dict[str, Any]]] = {"raw": [], "calibrated": []}
            priced_by_variant: dict[str, list[dict[str, Any]]] = {"raw": [], "calibrated": []}
            for row in tour_rows:
                match_id = row["match_id"]
                for variant in ("raw", "calibrated"):
                    probabilities = {name: float(row[f"{variant}_{name}"]) for name in PROCEDURES}
                    if any(
                        not math.isfinite(value) or not 0 <= value <= 1
                        for value in probabilities.values()
                    ):
                        raise BenchmarkError(f"{tour}/{match_id}: invalid saved prediction")
                    entry = {
                        "year": int(row["year"]),
                        "week": row["tournament_week"],
                        "match_id": match_id,
                        "outcome": labels[match_id],
                        "probabilities": probabilities,
                    }
                    entries_by_variant[variant].append(entry)
                    if match_id in market_raw:
                        priced = copy.deepcopy(entry)
                        priced["probabilities"]["normalized_pinnacle_raw"] = market_raw[match_id]
                        priced["probabilities"]["normalized_pinnacle_calibrated_past"] = market_cal[
                            match_id
                        ]
                        priced_by_variant[variant].append(priced)
            if not synthetic:
                if len(tour_rows) != int(spec["expected_primary_rows"]):
                    raise BenchmarkError(f"{tour}: report primary count mismatch")
                if len(priced_by_variant["raw"]) != int(spec["expected_priced_rows"]):
                    raise BenchmarkError(f"{tour}: report priced count mismatch")
            cohorts: dict[str, Any] = {}
            for name, collections in (
                ("primary", entries_by_variant),
                ("priced", priced_by_variant),
            ):
                scores: dict[str, Any] = {}
                for variant, entries in collections.items():
                    procedures = list(PROCEDURES)
                    if name == "priced":
                        procedures.extend(
                            ["normalized_pinnacle_raw", "normalized_pinnacle_calibrated_past"]
                        )
                    scores[variant] = _score_table(entries, procedures, clip)
                cohorts[name] = {"rows": len(collections["raw"]), "scores": scores}
            inference_output: dict[str, Any] = {}
            contrasts = {f"incumbent_minus_{name}": ("incumbent", name) for name in COMPARATORS}
            for cohort_name, entries in (
                ("primary", entries_by_variant["calibrated"]),
                ("priced", priced_by_variant["calibrated"]),
            ):
                scored_rows = [
                    ScoredRow(
                        int(row["year"]),
                        row["week"],
                        {
                            name: log_loss(
                                float(row["probabilities"][name]), int(row["outcome"]), clip
                            )
                            for name in PROCEDURES
                        },
                    )
                    for row in entries
                ]
                blocks: dict[str, Any] = {}
                lengths = [
                    int(inference["primary_mean_block_weeks"]),
                    *(int(value) for value in inference["sensitivity_mean_block_weeks"]),
                ]
                for length in lengths:
                    seed = (
                        int(inference["seed_base"]) + int(inference["tour_offsets"][tour]) + length
                    )
                    block = simultaneous_intervals(
                        scored_rows,
                        contrasts,
                        replicates=int(inference["replicates"]),
                        maximum_draws=int(inference["maximum_draws"]),
                        seed=seed,
                        mean_block=length,
                        level=float(inference["simultaneous_level"]),
                        degenerate_tolerance=float(inference["degenerate_se_tolerance"]),
                    )
                    block["stream_unit"] = f"{tour}:{cohort_name}:{length}"
                    block["generator_reset_for_stream"] = True
                    block["metrics"] = ["natural_log_loss"]
                    blocks[str(length)] = block
                inference_output[cohort_name] = blocks
            summary["tours"][tour] = {
                "primary_rows": len(entries_by_variant["raw"]),
                "priced_rows": len(priced_by_variant["raw"]),
                "cohorts": cohorts,
                "market_calibration_receipts": market_receipts,
                "market_qualification": "normalized Pinnacle quote timing unknown and may contain later information",
                "fallback_receipt_path": "../forecast/fallback_counts.csv",
                "fallback_counts": [row for row in saved_fallbacks if row["tour"] == tour],
                "fixed_prediction_sensitivities": _fixed_sensitivities(
                    entries_by_variant["calibrated"], clip
                ),
                "inference": inference_output,
            }
        atomic_json(report_root / "benchmark_report.json", summary)
        manifest = {
            "schema_version": 2,
            "completion": "complete",
            "benchmark_id": "G-L",
            "attempt": attempt,
            "invocation_config_sha256": sha256(config),
            "effective_config_sha256": canonical_hash(document),
            "barrier_sha256": sha256(attempt_root / "barrier/commitment.json"),
            "forecast_manifest_sha256": commitment["forecast_manifest_sha256"],
            "execution_binding": _execution_binding(),
            "artifacts": _manifest_files(report_root),
            "report_only_values_read_after_barrier": True,
        }
        atomic_json(report_root / "stage_manifest.json", manifest)
        _validate_report_completion(report_root, config, document, attempt)
    except Exception as exc:
        atomic_json(
            report_root / "failure.json",
            {"stage": "report", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    return report_root
