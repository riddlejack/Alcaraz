"""Fail-closed reporting for frozen forecast artifacts: stage ``report``.

Base revision: the archive's ``references/TIER01_models/report.py`` (tier contrasts,
configured primary and secondary contrasts, configured bootstrap seed). Merged from
``references/WTA02_models/report.py`` under the tour switch: the configured experiment
identity and tour, the cohort label, the published bootstrap resampling unit with both
units always computed, and the dynamic-feature dispersion carried from the predictor
config. Scoring, cohorts, the contrast definitions and the bootstrap procedure are
CONFIRM2026's, unchanged.

The two settings contracts are the runner's: a reporting config that declares a tour
is read under the WTA02 contract (``bootstrap_unit``, ``contrasts``, ``cohort``,
``tour`` in its settings; ``unit``-shaped bootstrap rows), one that does not under
TIER01's (``secondary_contrasts``; ``contrast_id``-shaped bootstrap rows).

This is the only module in the package that opens ``labels.csv`` to score a target
year, and it does so in exactly one place (``_read_source_tables``). The proper-score
arithmetic lives in ``tennislab.evaluation.scores`` as pure functions; this module
pairs them with outcomes. The published primary contrast, secondary contrasts,
bootstrap seed and interval unit come from the reporting configuration, never from a
literal here. It never fits or recalibrates a model: it scores already-emitted
probabilities only after validating every binding, forecast hash, CSV schema, ordering
and common membership.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.chain import common
from tennislab.chain.common import (
    ChainError,
    code_receipt,
    read_config,
    relative_to_root,
    require_nonempty_digest,
    resolve_under_root,
    sha256,
)
from tennislab.evaluation.scores import (
    block_bootstrap,
    contrast_delta,
    quantile_interval,
    reliability_bins,
    t_half_width,
)
from tennislab.evaluation.scores import individual_scores as _individual_scores

REPORTER_MODULE = "tennislab.evaluation.report"
DEFAULT_EXPERIMENT_ID = "TIER01"
TOURS = ("ATP", "WTA")
EXPERIMENT_ID = DEFAULT_EXPERIMENT_ID
TOUR: str | None = None
# The JOINT04 window is the default; validate_config installs the configured plan
# before any score is computed.
DEFAULT_YEAR_PLAN = {
    "panel_end_year": 2024,
    "feature_end_year": 2024,
    "target_years": list(range(2017, 2025)),
    "calibration_years_back": 3,
    "history_floor_year": 2011,
    "training_window_years": 5,
}
# `LEARNERS`, `BLOCKS` and `CONTRASTS` are installed by `configure_bundles()` from the
# frozen configuration, the way `RAW_YEARS` is installed by `configure_years()`.  The
# defaults are JOINT04's, so a config that declares no bundle list reports as before.
DEFAULT_LEARNERS = ("ridge", "hgb")
DEFAULT_BLOCKS = ("base", "traits", "dynamic", "full")
BASE_BLOCKS = DEFAULT_BLOCKS
TIER_SUFFIX = "_tier"
# The same-event-qualifying ablation bundle.  It yields two further contrasts --
# against its JOINT04 stem, and against the unablated tier bundle, which is the channel
# estimate itself.
TIER_NOQUAL_SUFFIX = "_tier_noqual"
# ARMS01 Arm 1: the `*_tier_entry` bundle (the tier bundle plus the entry/level block).
# It yields `<stem>_tier_entry_minus_<stem>_tier`, the Arm 1 minus Arm 0 contrast, and
# `<stem>_tier_entry_minus_<stem>` when the JOINT04 stem was fitted too.
TIER_ENTRY_SUFFIX = "_tier_entry"
VARIANT_SUFFIXES = (TIER_ENTRY_SUFFIX, TIER_NOQUAL_SUFFIX, TIER_SUFFIX)
LEARNERS = DEFAULT_LEARNERS
BLOCKS = DEFAULT_BLOCKS
CANDIDATES = {
    "ridge": ("ridge_c001", "ridge_c01", "ridge_c1"),
    "hgb": ("hgb_leaf07_depth3", "hgb_leaf15_depth4"),
}
FIXED_RAW = {"ridge": "ridge_c1", "hgb": "hgb_leaf07_depth3"}
LABEL_HEADER = (
    "match_id",
    "calendar_year",
    "source_season",
    "match_date",
    "tourney_id",
    "identity_tier",
    "primary_target",
    "a_won",
    "status",
    "source_field_agreement",
)
PREDICTION_HEADER = ("season", "match_id", "p_a_wins")
RELIABILITY_EDGES = tuple(index / 10.0 for index in range(11))
SCORE_CLIP = 1e-15
BOOTSTRAP_REPLICATES = 2000
# The bootstrap seed and the contrast the bootstrap is computed for are configuration,
# not literals.  `configure_primary()` installs both from the reporting config; the
# defaults are what the bundle list implies.
DEFAULT_BOOTSTRAP_SEED = 20260911
TIER_BOOTSTRAP_SEED = 20260912  # experiments/TIER01.design.md
BOOTSTRAP_SEED = DEFAULT_BOOTSTRAP_SEED
PRIMARY_CONTRAST: str | None = None
SECONDARY_CONTRASTS: tuple[str, ...] = ()
# Under the tour contract both units are always computed and `BOOTSTRAP_UNIT` names the
# published one.  `match` is the unit the WTA designs register, `tournament_edition` the
# one CONFIRM2026 published; the TIER01 contract publishes tournament editions only.
BOOTSTRAP_UNITS = ("match", "tournament_edition")
DEFAULT_BOOTSTRAP_UNIT = "match"
BOOTSTRAP_UNIT: str | None = None
# (annual row scope, equal-year summary scope) per unit.
BOOTSTRAP_SCOPES = {
    "match": (
        "conditional_on_fixed_predictions_within_year_matches",
        "conditional_on_fixed_predictions_stratified_within_year_match_bootstrap",
    ),
    "tournament_edition": (
        "conditional_on_fixed_predictions_within_year_tournament_edition_blocks",
        "conditional_on_fixed_predictions_stratified_within_year_tournament_edition_block_bootstrap",
    ),
}
# The cohort label the predictor froze.  The reporter does not re-derive membership --
# it scores the emitted forecasts' own membership -- so this names the population.
DEFAULT_COHORT = "aligned_primary"
COHORT = DEFAULT_COHORT
# Student-t critical value for the across-year interval, supplied by the config for
# len(EVALUATION_YEARS) - 1 degrees of freedom, and null (interval suppressed) when a
# single target year leaves no across-year spread.
DEFAULT_T_CRITICAL_95 = 2.3646242510102993
T_CRITICAL_95: float | None = DEFAULT_T_CRITICAL_95
PRIORITY_REFERENCE = 0.001
COHORTS = ("primary", "primary_priced", "completed_primary", "primary_plus_provisional")
JOINT04_CONTRASTS = (
    ("full_minus_base", {"full": 1.0, "base": -1.0}),
    ("traits_minus_base", {"traits": 1.0, "base": -1.0}),
    ("dynamic_minus_base", {"dynamic": 1.0, "base": -1.0}),
    ("full_minus_traits", {"full": 1.0, "traits": -1.0}),
    ("full_minus_dynamic", {"full": 1.0, "dynamic": -1.0}),
    (
        "full_minus_traits_minus_dynamic_plus_base",
        {"full": 1.0, "traits": -1.0, "dynamic": -1.0, "base": 1.0},
    ),
)


class ReportError(ChainError):
    """A binding, structure, membership, or reporting contract failed."""


def tour_contract() -> bool:
    """True under the WTA02 settings contract (a declared tour), false under TIER01's."""
    return TOUR is not None


def contrasts_for(blocks: Sequence[str]) -> tuple[tuple[str, dict[str, float]], ...]:
    """Every declared contrast whose blocks were all fitted in this run.

    One contrast per stem that was fitted both with and without the tier block;
    `full_tier_minus_full` is then the primary comparison.  A contrast naming a block
    this run did not fit is dropped rather than made up.
    """
    present = set(blocks)
    derived = [
        (name, dict(coefficients))
        for name, coefficients in JOINT04_CONTRASTS
        if set(coefficients).issubset(present)
    ]
    for stem in BASE_BLOCKS:
        for suffix in (TIER_SUFFIX, TIER_NOQUAL_SUFFIX, TIER_ENTRY_SUFFIX):
            tier = f"{stem}{suffix}"
            if tier in present and stem in present:
                derived.append((f"{tier}_minus_{stem}", {tier: 1.0, stem: -1.0}))
        tier = f"{stem}{TIER_SUFFIX}"
        ablated = f"{stem}{TIER_NOQUAL_SUFFIX}"
        if tier in present and ablated in present:
            derived.append((f"{tier}_minus_{ablated}", {tier: 1.0, ablated: -1.0}))
        entry = f"{stem}{TIER_ENTRY_SUFFIX}"
        if tier in present and entry in present:
            # ARMS01 contrast 1: Arm 1 (entry/level block) minus Arm 0 (the tier bundle).
            derived.append((f"{entry}_minus_{tier}", {entry: 1.0, tier: -1.0}))
    return tuple(derived)


def default_primary_contrast(names: Sequence[str]) -> str:
    """The primary contrast a bundle list implies when the config names none."""
    available = set(names)
    if f"full{TIER_ENTRY_SUFFIX}_minus_full{TIER_SUFFIX}" in available:
        return f"full{TIER_ENTRY_SUFFIX}_minus_full{TIER_SUFFIX}"
    if f"full{TIER_SUFFIX}_minus_full" in available:
        return f"full{TIER_SUFFIX}_minus_full"
    if "full_minus_base" in available:
        return "full_minus_base"
    raise ReportError("no primary contrast is available for the configured bundles")


def default_secondary_contrasts(names: Sequence[str], primary: str) -> tuple[str, ...]:
    """A tier primary publishes `base_tier - base` and the ablation contrasts beside it."""
    available = set(names)
    if not primary.endswith(f"{TIER_SUFFIX}_minus_full"):
        return ()
    chosen = [
        name
        for name in (
            f"base{TIER_SUFFIX}_minus_base",
            f"full{TIER_NOQUAL_SUFFIX}_minus_full",
            f"full{TIER_SUFFIX}_minus_full{TIER_NOQUAL_SUFFIX}",
        )
        if name in available
    ]
    return tuple(chosen)


def default_bootstrap_seed(primary: str) -> int:
    return (
        TIER_BOOTSTRAP_SEED
        if primary.endswith(f"{TIER_SUFFIX}_minus_full")
        else DEFAULT_BOOTSTRAP_SEED
    )


def primary_contrast_id() -> str:
    names = [name for name, _ in CONTRASTS]
    if PRIMARY_CONTRAST is not None:
        if PRIMARY_CONTRAST not in names:
            raise ReportError(
                f"the configured primary contrast {PRIMARY_CONTRAST!r} was not formed by "
                f"the configured bundles: {names}"
            )
        return PRIMARY_CONTRAST
    return default_primary_contrast(names)


def secondary_contrast_ids() -> tuple[str, ...]:
    names = [name for name, _ in CONTRASTS]
    primary = primary_contrast_id()
    for name in SECONDARY_CONTRASTS:
        if name not in names:
            raise ReportError(f"unknown secondary contrast: {name}")
        if name == primary:
            raise ReportError("the primary contrast cannot also be a secondary contrast")
    return tuple(SECONDARY_CONTRASTS)


def configure_identity(
    experiment_id: str | None = None, tour: str | None = None
) -> tuple[str, str | None]:
    """Install the experiment id and the tour this report is for.

    The id is the config's own and is cross-checked against the predictor config it
    scores; the tour decides which settings contract the config is read under.
    """
    global EXPERIMENT_ID, TOUR
    chosen_id = str(experiment_id or DEFAULT_EXPERIMENT_ID)
    if not chosen_id.strip() or any(character in chosen_id for character in "/\\ "):
        raise ReportError(f"invalid experiment_id {chosen_id!r}")
    chosen_tour = None if tour is None else str(tour).upper()
    if chosen_tour is not None and chosen_tour not in TOURS:
        raise ReportError(f"unknown tour {chosen_tour!r}; expected one of {list(TOURS)}")
    EXPERIMENT_ID, TOUR = chosen_id, chosen_tour
    return EXPERIMENT_ID, TOUR


def configure_primary(
    primary_contrast: str | None = None,
    secondary_contrasts: Sequence[str] | None = None,
    bootstrap_seed: int | None = None,
    bootstrap_unit: str | None = None,
) -> None:
    """Install the published primary/secondary contrasts, the bootstrap seed and unit.

    Called by `validate_config` from the reporting config, and by `configure_bundles`
    with no arguments to reinstall the defaults the configured bundles imply.  A config
    that names a different pair changes which difference `primary.json`, `report.md` and
    `bootstrap.csv` publish -- which is the point: the bundles alone do not say which
    difference the design declared primary.
    """
    global PRIMARY_CONTRAST, SECONDARY_CONTRASTS, BOOTSTRAP_SEED, BOOTSTRAP_UNIT
    names = [name for name, _ in CONTRASTS]
    if primary_contrast is not None and primary_contrast not in names:
        raise ReportError(
            f"the configured primary contrast {primary_contrast!r} was not formed by the "
            f"configured bundles: {names}"
        )
    PRIMARY_CONTRAST = primary_contrast
    resolved = primary_contrast_id()
    if secondary_contrasts is None:
        SECONDARY_CONTRASTS = default_secondary_contrasts(names, resolved)
    else:
        SECONDARY_CONTRASTS = tuple(secondary_contrasts)
    secondary_contrast_ids()
    if bootstrap_seed is None:
        BOOTSTRAP_SEED = default_bootstrap_seed(resolved)
    else:
        seed = int(bootstrap_seed)
        if seed < 0:
            raise ReportError("the bootstrap seed must be a nonnegative integer")
        BOOTSTRAP_SEED = seed
    if tour_contract():
        if SECONDARY_CONTRASTS:
            raise ReportError(
                "the tour settings contract publishes one contrast; it cannot record "
                f"secondary contrasts {list(SECONDARY_CONTRASTS)}"
            )
        chosen_unit = str(bootstrap_unit or DEFAULT_BOOTSTRAP_UNIT)
        if chosen_unit not in BOOTSTRAP_UNITS:
            raise ReportError(
                f"unknown bootstrap_unit {chosen_unit!r}; expected one of {list(BOOTSTRAP_UNITS)}"
            )
        BOOTSTRAP_UNIT = chosen_unit
    else:
        if bootstrap_unit is not None:
            raise ReportError(
                "a bootstrap_unit is declared only under the tour settings contract; "
                "the tier contract publishes tournament-edition blocks"
            )
        BOOTSTRAP_UNIT = None


CONTRASTS = contrasts_for(BLOCKS)


def raw_years_for(plan: Mapping[str, Any]) -> tuple[int, ...]:
    """Targets plus their calibration years, matching the runner's derivation."""
    back = int(plan["calibration_years_back"])
    needed: set[int] = set()
    for year in plan["target_years"]:
        needed.add(int(year))
        needed.update(int(year) - offset for offset in range(1, back + 1))
    return tuple(sorted(needed))


def configure_years(plan: Mapping[str, Any], t_critical_95: float | None) -> None:
    """Install the configured evaluation window; the only place years are set."""
    global RAW_YEARS, EVALUATION_YEARS, YEAR_PLAN, T_CRITICAL_95
    if not isinstance(plan, Mapping) or set(plan) != set(DEFAULT_YEAR_PLAN):
        raise ReportError(f"report year_plan keys must be exactly {sorted(DEFAULT_YEAR_PLAN)}")
    targets = plan["target_years"]
    if not isinstance(targets, list | tuple) or not targets:
        raise ReportError("report year_plan target_years must be a nonempty list")
    if list(targets) != sorted({int(year) for year in targets}):
        raise ReportError("report year_plan target_years must be sorted and unique")
    YEAR_PLAN = {
        key: (list(value) if isinstance(value, list | tuple) else value)
        for key, value in plan.items()
    }
    EVALUATION_YEARS = tuple(int(year) for year in targets)
    RAW_YEARS = raw_years_for(plan)
    if len(EVALUATION_YEARS) < 2:
        if t_critical_95 is not None:
            raise ReportError("a single target year cannot carry an across-year t interval")
    elif (
        not isinstance(t_critical_95, int | float)
        or not math.isfinite(float(t_critical_95))
        or t_critical_95 <= 0
    ):
        raise ReportError("t_critical_95 must be a positive finite number")
    T_CRITICAL_95 = None if t_critical_95 is None else float(t_critical_95)


def configure_bundles(
    blocks: Sequence[str] | None = None, learners: Sequence[str] | None = None
) -> None:
    """Install the bundle and learner lists the run actually produced."""
    global BLOCKS, LEARNERS, CONTRASTS
    chosen_blocks = tuple(DEFAULT_BLOCKS if blocks is None else blocks)
    chosen_learners = tuple(DEFAULT_LEARNERS if learners is None else learners)
    if not chosen_blocks or len(set(chosen_blocks)) != len(chosen_blocks):
        raise ReportError("report blocks must be a nonempty list of distinct names")
    if not chosen_learners or len(set(chosen_learners)) != len(chosen_learners):
        raise ReportError("report learners must be a nonempty list of distinct names")
    for block in chosen_blocks:
        stem = block
        for suffix in VARIANT_SUFFIXES:
            if block.endswith(suffix):
                stem = block[: -len(suffix)]
                break
        if stem not in BASE_BLOCKS:
            raise ReportError(f"unknown report block: {block}")
        if stem != block and tour_contract():
            raise ReportError(
                "a configuration that declares a tour is read under the WTA02 settings "
                f"contract, which cannot record the tier bundle {block}"
            )
    for learner in chosen_learners:
        if learner not in DEFAULT_LEARNERS:
            raise ReportError(f"unknown report learner: {learner}")
    BLOCKS = chosen_blocks
    LEARNERS = chosen_learners
    CONTRASTS = contrasts_for(BLOCKS)
    if not CONTRASTS:
        raise ReportError("the configured bundles form no declared contrast")
    # The bundle list changes which contrasts exist, so the published primary,
    # secondary, seed and unit are reinstalled from it; `configure_primary` is then
    # called again by `validate_config` with whatever the reporting config declares.
    configure_primary()


def configure_cohort(mode: str | None = None) -> str:
    """Record the cohort the predictor froze; it names the population, nothing else."""
    global COHORT
    chosen = str(mode or DEFAULT_COHORT)
    if chosen not in ("aligned_primary", "aligned_primary_no_dynamic"):
        raise ReportError(f"unknown cohort mode {chosen!r}")
    COHORT = chosen
    return COHORT


def settings_document() -> dict[str, Any]:
    """The settings contract a reporting config must equal, in the shape its revision froze."""
    document: dict[str, Any] = {
        "year_plan": dict(YEAR_PLAN),
        "raw_years": list(RAW_YEARS),
        "evaluation_years": list(EVALUATION_YEARS),
        "learners": list(LEARNERS),
        "blocks": list(BLOCKS),
        "candidate_ids": {key: list(value) for key, value in CANDIDATES.items()},
        "fixed_raw_candidates": FIXED_RAW,
        "score_log_loss_clip": SCORE_CLIP,
        "reliability_edges": list(RELIABILITY_EDGES),
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "primary_contrast": primary_contrast_id(),
        "t_critical_95": T_CRITICAL_95,
        "priority_effect_reference_log_loss": PRIORITY_REFERENCE,
    }
    if tour_contract():
        document["bootstrap_unit"] = BOOTSTRAP_UNIT
        document["bootstrap_units_emitted"] = list(BOOTSTRAP_UNITS)
        document["tour"] = TOUR
        document["contrasts"] = [name for name, _ in CONTRASTS]
        document["cohort"] = COHORT
    else:
        document["secondary_contrasts"] = list(secondary_contrast_ids())
    return document


YEAR_PLAN: dict[str, Any] = dict(DEFAULT_YEAR_PLAN)
EVALUATION_YEARS = tuple(int(year) for year in DEFAULT_YEAR_PLAN["target_years"])
RAW_YEARS = raw_years_for(DEFAULT_YEAR_PLAN)
DEFAULT_SETTINGS = settings_document()


def key_hash(keys: Sequence[tuple[str, str]]) -> str:
    payload = "".join(f"{season},{match_id}\n" for season, match_id in keys)
    return hashlib.sha256(payload.encode()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    json.dumps(value, allow_nan=False)  # refuses NaN and infinity before anything is written
    common.atomic_json(path, value)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> str:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    return sha256(path)


def _inside_root(path: Path) -> Path:
    """Lexical containment in the workspace; the archive resolved symbolic links."""
    return resolve_under_root(path, label="report path")


def _workspace_root() -> Path:
    return resolve_under_root(".", label="workspace")


def resolve_existing(value: Any, *bases: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ReportError(f"invalid path: {value!r}")
    supplied = Path(value)
    if supplied.is_absolute():
        path = _inside_root(supplied)
        if not path.is_file():
            raise ReportError(f"missing file: {path}")
        return path
    found = []
    for base in bases:
        candidate = _inside_root(base / supplied)
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    if len(found) != 1:
        raise ReportError(f"relative path resolves to {len(found)} files: {value}")
    return found[0]


def _digest(value: Any, label: str) -> str:
    try:
        return require_nonempty_digest(value, label=label)
    except ChainError as error:
        raise ReportError(str(error)) from error


def bound_path(binding: Any, *bases: Path, label: str) -> Path:
    if not isinstance(binding, dict):
        raise ReportError(f"missing binding: {label}")
    expected = binding.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ReportError(f"invalid hash binding: {label}")
    _digest(expected, label)
    path = resolve_existing(binding.get("path"), *bases)
    observed = sha256(path)
    if observed != expected:
        raise ReportError(f"{label} hash mismatch: {observed}")
    return path


def finite_probability(value: str, path: Path, key: tuple[str, str]) -> float:
    try:
        probability = float(value)
    except ValueError as error:
        raise ReportError(f"invalid probability at {path}:{key}: {value!r}") from error
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ReportError(f"probability outside [0,1] at {path}:{key}")
    return probability


def read_predictions(path: Path, expected_year: int) -> dict[tuple[str, str], float]:
    output: dict[tuple[str, str], float] = {}
    observed_order = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PREDICTION_HEADER:
            raise ReportError(f"prediction header drift: {path}")
        for row in reader:
            key = (row["season"], row["match_id"])
            if row["season"] != str(expected_year):
                raise ReportError(f"prediction season/path mismatch: {path}:{key}")
            if key in output:
                raise ReportError(f"duplicate prediction key: {path}:{key}")
            output[key] = finite_probability(row["p_a_wins"], path, key)
            observed_order.append(key)
    if not output or observed_order != sorted(observed_order):
        raise ReportError(f"prediction keys empty or not exactly sorted: {path}")
    return output


def record_field(record: Mapping[str, Any], names: Sequence[str], label: str) -> Any:
    present = [record[name] for name in names if name in record]
    if not present:
        raise ReportError(f"record missing {label}: tried {names}")
    if any(value != present[0] for value in present[1:]):
        raise ReportError(f"conflicting aliases for {label}")
    return present[0]


@dataclass(frozen=True)
class Forecast:
    kind: str
    year: int
    learner: str
    block: str
    candidate_id: str
    path: Path
    sha256: str
    predictions: dict[tuple[str, str], float]
    receipt: Mapping[str, Any]

    @property
    def model_id(self) -> str:
        bits = [self.kind]
        if self.kind == "raw":
            bits.extend((self.learner, self.block, self.candidate_id))
        elif self.learner:
            bits.extend((self.learner, self.block))
        else:
            bits.append(self.candidate_id)
        return "/".join(bits)


@dataclass
class Inputs:
    report_config: dict[str, Any]
    config_path: Path
    selection: dict[str, Any]
    selection_path: Path
    predictor_config: dict[str, Any]
    predictor_config_path: Path
    labels_path: Path
    features_path: Path
    labels: dict[tuple[str, str], dict[str, str]]
    features: dict[tuple[str, str], dict[str, str]]
    forecasts: list[Forecast]
    selection_records: list[dict[str, Any]]
    shared_records: list[dict[str, Any]]
    market_records: list[dict[str, Any]]
    binding_hashes: dict[str, str]
    declared_code: dict[str, Any]


def _forecast_from_record(
    kind: str,
    year: int,
    learner: str,
    block: str,
    candidate_id: str,
    record: Mapping[str, Any],
    run_root: Path,
    path_names: Sequence[str],
    hash_names: Sequence[str],
    expected_suffix: str,
) -> Forecast:
    path = resolve_existing(
        record_field(record, path_names, f"{kind} path"), run_root, _workspace_root()
    )
    try:
        relative = path.relative_to(run_root).as_posix()
    except ValueError as error:
        raise ReportError(f"forecast outside run root: {path}") from error
    if relative != expected_suffix:
        raise ReportError(f"forecast path drift: {relative} != {expected_suffix}")
    expected_hash = _digest(record_field(record, hash_names, f"{kind} hash"), f"{kind} hash")
    observed_hash = sha256(path)
    if expected_hash != observed_hash:
        raise ReportError(f"forecast hash mismatch: {path}")
    return Forecast(kind, year, learner, block, candidate_id, path, observed_hash, {}, record)


def declared_code_binding(code: Any) -> dict[str, Any]:
    """Record the config's reporter binding; verify it only when it names this module."""
    if not isinstance(code, dict):
        raise ReportError("report config code bindings must be an object")
    declared_hash = _digest(code.get("reporter_sha256"), "code.reporter_sha256")
    if code.get("reporter_path") == REPORTER_MODULE:
        if declared_hash != code_receipt(__name__)["sha256"]:
            raise ReportError("reporter code hash binding differs from executing code")
    return dict(code)


def validate_config(config_path: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    config_path = _inside_root(config_path)
    config = read_config(config_path)
    scope = config.get("execution_scope")
    if scope not in {"synthetic_fixture", "frozen_real_outputs"}:
        raise ReportError("invalid report execution_scope")
    settings = config.get("settings")
    if not isinstance(settings, dict):
        raise ReportError("report settings must be an object")
    # The experiment id is the config's own, not a literal; `preflight` cross-checks it
    # against the predictor config.  The tour decides the settings contract.
    configure_identity(config.get("experiment_id"), settings.get("tour"))
    configure_years(settings.get("year_plan", {}), settings.get("t_critical_95"))
    configure_bundles(settings.get("blocks"), settings.get("learners"))
    configure_cohort(settings.get("cohort"))
    configure_primary(
        settings.get("primary_contrast"),
        settings.get("secondary_contrasts"),
        settings.get("bootstrap_seed"),
        settings.get("bootstrap_unit"),
    )
    if settings != settings_document():
        raise ReportError("report settings differ from the contract under the configured year plan")
    declared_code: dict[str, Any] = {}
    if scope == "frozen_real_outputs":
        if config.get("status") != "frozen":
            raise ReportError("real report config must be frozen")
        declared_code = declared_code_binding(config.get("code"))
        # The declared counts are checked against the counts recomputed from the
        # configured target years in validate_memberships below.
        expected = config.get("expected_membership")
        if not isinstance(expected, dict) or set(expected) != {
            "selected_primary_rows",
            "selected_primary_priced_rows",
        }:
            raise ReportError(
                "real report expected_membership must declare exactly selected_primary_rows and selected_primary_priced_rows"
            )
        if any(not isinstance(value, int) or value <= 0 for value in expected.values()):
            raise ReportError("real report expected membership counts must be positive integers")
    selection_path = bound_path(
        config.get("inputs", {}).get("selection_complete"),
        _workspace_root(),
        label="selection_complete",
    )
    return config, selection_path, declared_code


def _validate_and_describe_forecasts(
    selection: dict[str, Any], selection_path: Path, raw_complete: dict[str, Any]
) -> list[Forecast]:
    run_root = selection_path.parent
    forecasts: list[Forecast] = []
    raw_records = raw_complete.get("raw_attempts")
    if not isinstance(raw_records, list):
        raise ReportError("raw_complete lacks raw_attempts")
    for record in raw_records:
        if record.get("status") != "complete":
            raise ReportError("reporting requires a complete raw candidate menu")
        year = int(record["year"])
        learner, block, candidate = record["learner"], record["block"], record["candidate_id"]
        forecasts.append(
            _forecast_from_record(
                "raw",
                year,
                learner,
                block,
                candidate,
                record,
                run_root,
                ("prediction_path",),
                ("prediction_sha256",),
                f"raw/{year}/{learner}/{block}/{candidate}.csv",
            )
        )
    expected_raw = {
        (year, learner, block, candidate)
        for year in RAW_YEARS
        for learner in LEARNERS
        for block in BLOCKS
        for candidate in CANDIDATES[learner]
    }
    observed_raw = {(x.year, x.learner, x.block, x.candidate_id) for x in forecasts}
    if observed_raw != expected_raw or len(forecasts) != len(expected_raw):
        raise ReportError("raw forecast menu/path coverage drift")

    selection_records = selection.get("selection_records")
    shared_records = selection.get("shared_base_records")
    market_records = selection.get("market_records")
    if not all(
        isinstance(value, list) for value in (selection_records, shared_records, market_records)
    ):
        raise ReportError("selection_complete record arrays missing")
    for kind, records, prefix in (
        ("selected", selection_records, "selected"),
        ("shared_base", shared_records, "shared_base"),
    ):
        for record in records:
            if record.get("status") != "complete":
                raise ReportError(f"incomplete {kind} record")
            if record.get("outer_labels_used") is not False:
                raise ReportError(f"{kind} record used outer labels")
            year = int(record_field(record, ("outer_year", "year"), f"{kind} year"))
            learner, block = record["learner"], record["block"]
            candidate = record_field(
                record,
                ("selected_candidate_id", "candidate_id"),
                f"{kind} candidate",
            )
            forecasts.append(
                _forecast_from_record(
                    kind,
                    year,
                    learner,
                    block,
                    str(candidate),
                    record,
                    run_root,
                    ("selected_prediction_path", "selected_path", "prediction_path")
                    if kind == "selected"
                    else ("shared_prediction_path", "shared_base_path", "prediction_path"),
                    ("selected_prediction_sha256", "selected_sha256", "prediction_sha256")
                    if kind == "selected"
                    else ("shared_prediction_sha256", "shared_base_sha256", "prediction_sha256"),
                    f"{prefix}/{year}/{learner}/{block}.csv",
                )
            )
        observed = {(x.year, x.learner, x.block) for x in forecasts if x.kind == kind}
        expected = {
            (year, learner, block)
            for year in EVALUATION_YEARS
            for learner in LEARNERS
            for block in BLOCKS
        }
        if observed != expected or len(observed) != len(records):
            raise ReportError(f"{kind} forecast coverage drift")

    for record in market_records:
        if record.get("status") != "complete":
            raise ReportError("incomplete market record")
        if record.get("outer_labels_used") is not False:
            raise ReportError("market record used outer labels")
        year = int(record_field(record, ("outer_year", "year"), "market year"))
        for model, path_names, hash_names in (
            (
                "raw_ps",
                ("raw_prediction_path", "raw_ps_path", "raw_path"),
                ("raw_prediction_sha256", "raw_ps_sha256", "raw_sha256"),
            ),
            (
                "calibrated_ps",
                ("calibrated_prediction_path", "calibrated_ps_path", "calibrated_path"),
                ("calibrated_prediction_sha256", "calibrated_ps_sha256", "calibrated_sha256"),
            ),
        ):
            forecasts.append(
                _forecast_from_record(
                    "market",
                    year,
                    "",
                    "",
                    model,
                    record,
                    run_root,
                    path_names,
                    hash_names,
                    f"market/{year}/{model}.csv",
                )
            )
    observed_market = {(x.year, x.candidate_id) for x in forecasts if x.kind == "market"}
    expected_market = {
        (year, model) for year in EVALUATION_YEARS for model in ("raw_ps", "calibrated_ps")
    }
    if observed_market != expected_market or len(market_records) != len(EVALUATION_YEARS):
        raise ReportError("market forecast coverage drift")
    return forecasts


def _read_source_tables(labels_path: Path, features_path: Path) -> tuple[dict, dict]:
    """Read the label and feature tables the forecasts are scored against.

    This is the package's only read of ``labels.csv`` for a target year: the outcomes
    enter the chain here and nowhere earlier.
    """
    labels: dict[tuple[str, str], dict[str, str]] = {}
    with labels_path.open(newline="", encoding="utf-8") as handle:  # target-year outcome read
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LABEL_HEADER:
            raise ReportError("labels header drift")
        for row in reader:
            key = (row["calendar_year"], row["match_id"])
            if key in labels:
                raise ReportError(f"duplicate label key: {key}")
            if row["a_won"] == "":
                # RB3: an unresolved outcome is refused, never scored or skipped silently.
                raise ReportError(
                    f"unresolved outcome (blank a_won) at {key}: the report scores no "
                    "target year whose outcomes are not yet known"
                )
            if row["a_won"] not in {"0", "1"}:
                raise ReportError(f"invalid a_won at {key}")
            if row["status"] not in {"completed", "retired", "default"}:
                raise ReportError(f"unknown match status at {key}: {row['status']}")
            if row["identity_tier"] not in {"primary", "provisional"}:
                raise ReportError(f"unknown identity tier at {key}")
            labels[key] = row
    features: dict[tuple[str, str], dict[str, str]] = {}
    required = {
        "match_id",
        "calendar_year",
        "source_season",
        "match_date",
        "tourney_id",
        "identity_tier",
        "primary_target",
        "source_field_agreement",
        "ps_probability_a",
        "ps_missing",
    }
    with features_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not required.issubset(reader.fieldnames or ()):
            raise ReportError("feature table lacks report metadata/price fields")
        for row in reader:
            key = (row["calendar_year"], row["match_id"])
            if key in features:
                raise ReportError(f"duplicate feature key: {key}")
            if row["ps_missing"] not in {"0", "1"}:
                raise ReportError(f"invalid ps_missing at {key}")
            if (row["ps_missing"] == "1") != (row["ps_probability_a"] == ""):
                raise ReportError(f"ps probability/missing conflict at {key}")
            if row["ps_missing"] == "0":
                finite_probability(row["ps_probability_a"], features_path, key)
            features[key] = row
    if set(labels) != set(features):
        raise ReportError("label/feature memberships differ")
    for key in labels:
        for field in (
            "calendar_year",
            "source_season",
            "match_date",
            "tourney_id",
            "identity_tier",
            "primary_target",
            "source_field_agreement",
        ):
            if labels[key][field] != features[key][field]:
                raise ReportError(f"label/feature {field} mismatch at {key}")
    return labels, features


def _receipt_value(record: Mapping[str, Any], names: Sequence[str], label: str) -> Any:
    return record_field(record, names, label)


def _check_rows_and_membership(
    record: Mapping[str, Any],
    keys: Sequence[tuple[str, str]],
    row_names: Sequence[str],
    membership_names: Sequence[str],
    label: str,
) -> None:
    rows = _receipt_value(record, row_names, f"{label} rows")
    membership = _receipt_value(record, membership_names, f"{label} membership")
    if int(rows) != len(keys):
        raise ReportError(f"{label} row receipt mismatch")
    if membership != key_hash(keys):
        raise ReportError(f"{label} membership receipt mismatch")


def validate_forecast_receipts(
    forecasts: Sequence[Forecast], labels: Mapping[tuple[str, str], Mapping[str, str]]
) -> None:
    """Bind every parsed forecast body back to its row and key receipts."""
    for item in forecasts:
        keys = tuple(item.predictions)
        receipt = item.receipt
        if item.kind == "raw":
            if receipt.get("outcome_labels_used_for_prediction") is not False:
                raise ReportError(f"raw prediction used target labels: {item.path}")
            _check_rows_and_membership(
                receipt,
                keys,
                ("prediction_rows",),
                ("prediction_membership_sha256",),
                f"raw/{item.year}/{item.learner}/{item.block}/{item.candidate_id}",
            )
            primary = tuple(key for key in keys if labels[key]["identity_tier"] == "primary")
            provisional = tuple(
                key for key in keys if labels[key]["identity_tier"] == "provisional"
            )
            _check_rows_and_membership(
                receipt,
                primary,
                ("primary_target_rows",),
                ("primary_target_membership_sha256",),
                f"raw primary/{item.year}/{item.learner}/{item.block}/{item.candidate_id}",
            )
            _check_rows_and_membership(
                receipt,
                provisional,
                ("provisional_target_rows",),
                ("provisional_target_membership_sha256",),
                f"raw provisional/{item.year}/{item.learner}/{item.block}/{item.candidate_id}",
            )
        elif item.kind == "selected":
            _check_rows_and_membership(
                receipt,
                keys,
                ("outer_target_rows",),
                ("selected_prediction_membership_sha256",),
                f"selected/{item.year}/{item.learner}/{item.block}",
            )
            primary = tuple(key for key in keys if labels[key]["identity_tier"] == "primary")
            provisional = tuple(
                key for key in keys if labels[key]["identity_tier"] == "provisional"
            )
            _check_rows_and_membership(
                receipt,
                primary,
                ("outer_primary_rows",),
                ("outer_primary_membership_sha256",),
                f"selected primary/{item.year}/{item.learner}/{item.block}",
            )
            _check_rows_and_membership(
                receipt,
                provisional,
                ("outer_provisional_rows",),
                ("outer_provisional_membership_sha256",),
                f"selected provisional/{item.year}/{item.learner}/{item.block}",
            )
        elif item.kind == "shared_base":
            _check_rows_and_membership(
                receipt,
                keys,
                ("prediction_rows",),
                ("prediction_membership_sha256",),
                f"shared_base/{item.year}/{item.learner}/{item.block}",
            )
        elif item.kind == "market":
            _check_rows_and_membership(
                receipt,
                keys,
                ("target_rows",),
                ("target_membership_sha256",),
                f"market/{item.year}/{item.candidate_id}",
            )


def validate_selection_links(forecasts: Sequence[Forecast], selection: Mapping[str, Any]) -> None:
    """Cross-link saved selected/shared procedures to raw files and saved trials."""
    raw = {
        (item.year, item.learner, item.block, item.candidate_id): item
        for item in forecasts
        if item.kind == "raw"
    }
    selected_records = {
        (int(record["outer_year"]), record["learner"], record["block"]): record
        for record in selection["selection_records"]
    }
    for (year, learner, block), record in selected_records.items():
        nested = record.get("selection")
        if not isinstance(nested, dict) or nested.get("status") != "complete":
            raise ReportError(f"selected procedure receipt incomplete: {year}/{learner}/{block}")
        candidate = record["selected_candidate_id"]
        slope = record["selected_slope"]
        if (
            nested.get("selected_candidate_id") != candidate
            or nested.get("selected_slope") != slope
        ):
            raise ReportError(
                f"selected top-level/nested receipt mismatch: {year}/{learner}/{block}"
            )
        trials = record.get("candidate_trials")
        if not isinstance(trials, dict) or candidate not in trials:
            raise ReportError(
                f"selected candidate trial missing: {year}/{learner}/{block}/{candidate}"
            )
        trial = trials[candidate]
        if (
            trial.get("status") != "complete"
            or trial.get("candidate_id") != candidate
            or trial.get("slope") != slope
        ):
            raise ReportError(
                f"selected candidate trial mismatch: {year}/{learner}/{block}/{candidate}"
            )
        source = raw[(year, learner, block, candidate)]
        if record.get("source_raw_prediction_sha256") != source.sha256:
            raise ReportError(
                f"selected source raw hash mismatch: {year}/{learner}/{block}/{candidate}"
            )

    base_candidates = {
        (year, learner): record["selected_candidate_id"]
        for (year, learner, block), record in selected_records.items()
        if block == "base"
    }
    for record in selection["shared_base_records"]:
        year, learner, block = int(record["outer_year"]), record["learner"], record["block"]
        candidate = record["candidate_id"]
        if candidate != base_candidates[(year, learner)]:
            raise ReportError(
                f"shared candidate differs from base-selected candidate: {year}/{learner}/{block}"
            )
        own_trial = selected_records[(year, learner, block)]["candidate_trials"].get(candidate)
        if (
            not isinstance(own_trial, dict)
            or own_trial.get("status") != "complete"
            or own_trial.get("slope") != record.get("slope")
        ):
            raise ReportError(
                f"shared slope differs from own-block candidate trial: {year}/{learner}/{block}"
            )
        source = raw[(year, learner, block, candidate)]
        if record.get("source_raw_prediction_sha256") != source.sha256:
            raise ReportError(
                f"shared source raw hash mismatch: {year}/{learner}/{block}/{candidate}"
            )

    for record in selection["market_records"]:
        fit = record.get("slope_fit")
        if (
            not isinstance(fit, dict)
            or fit.get("status") != "complete"
            or fit.get("slope") != record.get("slope")
        ):
            raise ReportError(f"market slope receipt mismatch: {record.get('outer_year')}")
        if record.get("quote_timing") != "unknown":
            raise ReportError(f"market quote timing contract drift: {record.get('outer_year')}")


def preflight(config_path: Path) -> Inputs:
    """Validate all hashes and forecast structures before any score is computed."""
    config, selection_path, declared_code = validate_config(config_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection.get("status") != "complete":
        raise ReportError("selection_complete status differs")
    if selection.get("all_outer_forecasts_saved_before_reporting") is not True:
        raise ReportError("outer forecasts were not sealed before reporting")
    if selection.get("outer_target_outcomes_scored") is not False:
        raise ReportError("selection manifest says outer outcomes were already scored")
    # The archive resolved the ledger's recorded (absolute) predictor path; here the
    # predictor config is bound through the reporting config's own hash binding and the
    # ledger's recorded hash must agree with it.
    recorded_path = selection.get("config_path")
    if not isinstance(recorded_path, str) or not recorded_path:
        raise ReportError("selection_complete records no predictor config path")
    predictor_path = bound_path(
        config.get("inputs", {}).get("predictor_config"),
        _workspace_root(),
        label="predictor_config",
    )
    if sha256(predictor_path) != _digest(selection.get("config_sha256"), "selection config_sha256"):
        raise ReportError("predictor config hash mismatch")
    predictor = json.loads(predictor_path.read_text(encoding="utf-8"))
    if predictor.get("experiment_id") != EXPERIMENT_ID:
        raise ReportError("predictor config experiment drift")
    predictor_tour = predictor.get("settings", {}).get("tour")
    if (None if predictor_tour is None else str(predictor_tour).upper()) != TOUR:
        raise ReportError("predictor config tour differs from the report config tour")
    predictor_plan = predictor.get("settings", {}).get("year_plan")
    if predictor_plan != YEAR_PLAN:
        raise ReportError("predictor year plan differs from the report year plan")
    labels_path = bound_path(
        predictor.get("inputs", {}).get("labels"), _workspace_root(), label="predictor labels"
    )
    features_path = bound_path(
        predictor.get("inputs", {}).get("features"),
        _workspace_root(),
        label="predictor features",
    )
    raw_path = resolve_existing(
        selection.get("raw_complete_path", "raw_complete.json"),
        selection_path.parent,
        _workspace_root(),
    )
    if sha256(raw_path) != _digest(selection.get("raw_complete_sha256"), "raw_complete_sha256"):
        raise ReportError("raw_complete hash mismatch")
    raw_complete = json.loads(raw_path.read_text(encoding="utf-8"))
    if raw_complete.get("status") != "complete":
        raise ReportError("raw_complete status differs")
    if raw_complete.get("all_candidate_predictions_saved_before_scoring") is not True:
        raise ReportError("raw candidate forecasts were not sealed before scoring")
    if raw_complete.get("target_outcomes_scored") is not False:
        raise ReportError("raw manifest outcome-scoring flag differs")
    if raw_complete.get("config_sha256") != selection.get("config_sha256"):
        raise ReportError("raw and selection predictor config hashes differ")
    if raw_complete.get("config_path") != recorded_path:
        raise ReportError("raw and selection predictor config paths differ")
    descriptors = _validate_and_describe_forecasts(selection, selection_path, raw_complete)
    # Hashes and complete descriptor coverage are now validated.  Parse forecast
    # bodies and source tables only after that gate.
    forecasts = [
        Forecast(
            item.kind,
            item.year,
            item.learner,
            item.block,
            item.candidate_id,
            item.path,
            item.sha256,
            read_predictions(item.path, item.year),
            item.receipt,
        )
        for item in descriptors
    ]
    labels, features = _read_source_tables(labels_path, features_path)
    validate_forecast_receipts(forecasts, labels)
    validate_selection_links(forecasts, selection)
    validate_memberships(forecasts, labels, features, selection, config)
    return Inputs(
        config,
        config_path,
        selection,
        selection_path,
        predictor,
        predictor_path,
        labels_path,
        features_path,
        labels,
        features,
        forecasts,
        selection["selection_records"],
        selection["shared_base_records"],
        selection["market_records"],
        {
            "reporter": code_receipt(__name__)["sha256"],
            "report_config": sha256(config_path),
            "selection_complete": sha256(selection_path),
            "predictor_config": sha256(predictor_path),
            "raw_complete": sha256(raw_path),
            "labels": sha256(labels_path),
            "features": sha256(features_path),
        },
        declared_code,
    )


def _label_accepts(row: Mapping[str, str]) -> bool:
    year = row["calendar_year"]
    return (
        row["source_season"] == year
        and row["match_date"][:4] == year
        and (
            (row["identity_tier"] == "primary" and row["primary_target"] == "1")
            or (row["identity_tier"] == "provisional" and row["primary_target"] == "0")
        )
    )


def cohort_keys(
    keys: Sequence[tuple[str, str]], name: str, labels: Mapping, features: Mapping
) -> tuple[tuple[str, str], ...]:
    selected = []
    for key in keys:
        row = labels[key]
        primary = row["identity_tier"] == "primary" and row["primary_target"] == "1"
        provisional = row["identity_tier"] == "provisional" and row["primary_target"] == "0"
        accepted = {
            "primary": primary,
            "primary_priced": primary and features[key]["ps_missing"] == "0",
            "completed_primary": primary and row["status"] == "completed",
            "primary_plus_provisional": primary or provisional,
        }[name]
        if accepted:
            selected.append(key)
    return tuple(selected)


def validate_memberships(
    forecasts: Sequence[Forecast],
    labels: Mapping,
    features: Mapping,
    selection: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    by_kind_year: dict[tuple[str, int], list[Forecast]] = {}
    for item in forecasts:
        keys = tuple(item.predictions)
        if any(key not in labels for key in keys):
            raise ReportError(f"forecast has unknown label key: {item.path}")
        if any(not _label_accepts(labels[key]) for key in keys):
            raise ReportError(f"forecast has unaligned/non-target key: {item.path}")
        by_kind_year.setdefault((item.kind, item.year), []).append(item)
    raw_keys: dict[int, tuple[tuple[str, str], ...]] = {}
    selected_keys: dict[int, tuple[tuple[str, str], ...]] = {}
    for (kind, year), items in by_kind_year.items():
        memberships = [tuple(item.predictions) for item in items]
        if any(keys != memberships[0] for keys in memberships[1:]):
            raise ReportError(f"{kind}/{year} forecast memberships differ")
        if kind == "raw":
            raw_keys[year] = memberships[0]
        elif kind == "selected":
            selected_keys[year] = memberships[0]
    for year in EVALUATION_YEARS:
        if selected_keys[year] != raw_keys[year]:
            raise ReportError(f"selected/raw membership differs in {year}")
        for kind in ("shared_base",):
            keys = tuple(by_kind_year[(kind, year)][0].predictions)
            if keys != selected_keys[year]:
                raise ReportError(f"{kind}/selected membership differs in {year}")
        market = tuple(by_kind_year[("market", year)][0].predictions)
        expected_market = cohort_keys(selected_keys[year], "primary_priced", labels, features)
        if market != expected_market:
            raise ReportError(f"market membership differs from exact primary-priced keys in {year}")
    primary_n = sum(
        len(cohort_keys(selected_keys[y], "primary", labels, features)) for y in EVALUATION_YEARS
    )
    priced_n = sum(
        len(cohort_keys(selected_keys[y], "primary_priced", labels, features))
        for y in EVALUATION_YEARS
    )
    if config["execution_scope"] == "frozen_real_outputs":
        expected = config["expected_membership"]
        if (
            primary_n != expected["selected_primary_rows"]
            or priced_n != expected["selected_primary_priced_rows"]
        ):
            raise ReportError(
                f"selected report membership drift: primary={primary_n}, priced={priced_n}"
            )
    manifest_membership = selection.get("membership", {})
    for aliases, value in (
        (("selected_primary_rows", "selected_primary_rows_2017_2024"), primary_n),
        (("selected_primary_priced_rows", "selected_primary_priced_rows_2017_2024"), priced_n),
    ):
        observed = [manifest_membership[name] for name in aliases if name in manifest_membership]
        if observed and any(int(item) != value for item in observed):
            raise ReportError(f"selection manifest membership mismatch for {aliases[0]}")


def individual_scores(
    probabilities: Sequence[float], outcomes: Sequence[int]
) -> tuple[np.ndarray, np.ndarray, int]:
    return _individual_scores(probabilities, outcomes, SCORE_CLIP)


def metric_row(
    item: Forecast, cohort: str, keys: Sequence[tuple[str, str]], inputs: Inputs
) -> dict[str, Any]:
    probabilities = [item.predictions[key] for key in keys]
    outcomes = [int(inputs.labels[key]["a_won"]) for key in keys]
    loss, brier, clipping = individual_scores(probabilities, outcomes)
    primary_n = sum(inputs.labels[key]["identity_tier"] == "primary" for key in keys)
    provisional_n = sum(inputs.labels[key]["identity_tier"] == "provisional" for key in keys)
    return {
        "forecast_kind": item.kind,
        "season": item.year,
        "learner": item.learner,
        "block": item.block,
        "candidate_id": item.candidate_id,
        "model_id": item.model_id,
        "cohort": cohort,
        "n": len(keys),
        "primary_n": primary_n,
        "provisional_n": provisional_n,
        "membership_sha256": key_hash(keys),
        "log_loss": float(np.mean(loss)),
        "brier": float(np.mean(brier)),
        "score_clip_count": clipping,
        "probability_min": min(probabilities),
        "probability_max": max(probabilities),
        "probability_zero_count": sum(value == 0.0 for value in probabilities),
        "probability_one_count": sum(value == 1.0 for value in probabilities),
    }


def annual_metrics(inputs: Inputs) -> list[dict[str, Any]]:
    rows = []
    for item in inputs.forecasts:
        base_keys = tuple(item.predictions)
        cohorts = ("primary_priced",) if item.kind == "market" else COHORTS
        for cohort in cohorts:
            keys = cohort_keys(base_keys, cohort, inputs.labels, inputs.features)
            if not keys:
                raise ReportError(f"empty {cohort} metric for {item.model_id}/{item.year}")
            rows.append(metric_row(item, cohort, keys, inputs))
    return rows


def pooled_metrics(annual: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Summarize absolute model scores by both match and equal-year weighting."""
    grouped: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in annual:
        key = (
            str(row["forecast_kind"]),
            str(row["learner"]),
            str(row["block"]),
            str(row["model_id"]),
            str(row["cohort"]),
        )
        grouped.setdefault(key, []).append(row)
    output = []
    for (kind, learner, block, model_id, cohort), rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda row: int(row["season"]))
        total = sum(int(row["n"]) for row in rows)
        candidate_ids = sorted({str(row["candidate_id"]) for row in rows})
        output.append(
            {
                "forecast_kind": kind,
                "learner": learner,
                "block": block,
                "candidate_id": candidate_ids[0] if len(candidate_ids) == 1 else "varies_by_year",
                "model_id": model_id,
                "cohort": cohort,
                "years": len(rows),
                "n": total,
                "primary_n": sum(int(row["primary_n"]) for row in rows),
                "provisional_n": sum(int(row["provisional_n"]) for row in rows),
                "log_loss_match_weighted": sum(
                    int(row["n"]) * float(row["log_loss"]) for row in rows
                )
                / total,
                "log_loss_equal_year": float(np.mean([float(row["log_loss"]) for row in rows])),
                "brier_match_weighted": sum(int(row["n"]) * float(row["brier"]) for row in rows)
                / total,
                "brier_equal_year": float(np.mean([float(row["brier"]) for row in rows])),
                "score_clip_count": sum(int(row["score_clip_count"]) for row in rows),
                "probability_min": min(float(row["probability_min"]) for row in rows),
                "probability_max": max(float(row["probability_max"]) for row in rows),
                "probability_zero_count": sum(int(row["probability_zero_count"]) for row in rows),
                "probability_one_count": sum(int(row["probability_one_count"]) for row in rows),
            }
        )
    return output


def coverage_rows(inputs: Inputs) -> list[dict[str, Any]]:
    representative: dict[tuple[str, int], Forecast] = {}
    for item in inputs.forecasts:
        if item.kind == "market":
            continue
        representative.setdefault((item.kind, item.year), item)
    rows = []
    for (kind, year), item in sorted(representative.items()):
        keys = tuple(item.predictions)
        primary = cohort_keys(keys, "primary", inputs.labels, inputs.features)
        provisional = tuple(
            key for key in keys if inputs.labels[key]["identity_tier"] == "provisional"
        )
        rows.append(
            {
                "forecast_kind": kind,
                "season": year,
                "n": len(keys),
                "membership_sha256": key_hash(keys),
                "primary_n": len(primary),
                "provisional_n": len(provisional),
                "completed_primary_n": sum(
                    inputs.labels[key]["status"] == "completed" for key in primary
                ),
                "retired_primary_n": sum(
                    inputs.labels[key]["status"] == "retired" for key in primary
                ),
                "default_primary_n": sum(
                    inputs.labels[key]["status"] == "default" for key in primary
                ),
                "source_agreement_primary_n": sum(
                    inputs.labels[key]["source_field_agreement"] == "1" for key in primary
                ),
                "source_agreement_provisional_n": sum(
                    inputs.labels[key]["source_field_agreement"] == "1" for key in provisional
                ),
                "primary_priced_n": len(
                    cohort_keys(keys, "primary_priced", inputs.labels, inputs.features)
                ),
                "primary_price_missing_n": sum(
                    inputs.features[key]["ps_missing"] == "1" for key in primary
                ),
            }
        )
    return rows


def _forecast_index(inputs: Inputs) -> dict[tuple[str, int, str, str], Forecast]:
    output = {}
    for item in inputs.forecasts:
        if item.kind == "market":
            continue
        key = (item.kind, item.year, item.learner, item.block)
        if item.kind == "raw" and item.candidate_id != FIXED_RAW[item.learner]:
            continue
        if key in output:
            raise ReportError(f"duplicate contrast forecast: {key}")
        output[key] = item
    return output


def contrast_outputs(
    inputs: Inputs,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    index = _forecast_index(inputs)
    annual = []
    details: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    kinds = (("raw", RAW_YEARS), ("selected", EVALUATION_YEARS), ("shared_base", EVALUATION_YEARS))
    for kind, years in kinds:
        for learner in LEARNERS:
            for cohort in COHORTS:
                for contrast_id, coefficients in CONTRASTS:
                    for year in years:
                        forecasts = {
                            block: index[(kind, year, learner, block)] for block in coefficients
                        }
                        memberships = [tuple(item.predictions) for item in forecasts.values()]
                        if any(value != memberships[0] for value in memberships[1:]):
                            raise ReportError("contrast forecast membership differs")
                        keys = cohort_keys(memberships[0], cohort, inputs.labels, inputs.features)
                        component_losses = {}
                        component_briers = {}
                        for block, item in forecasts.items():
                            p = [item.predictions[key] for key in keys]
                            y = [int(inputs.labels[key]["a_won"]) for key in keys]
                            component_losses[block], component_briers[block], _ = individual_scores(
                                p, y
                            )
                        loss_delta = contrast_delta(component_losses, coefficients)
                        brier_delta = contrast_delta(component_briers, coefficients)
                        row = {
                            "forecast_kind": kind,
                            "learner": learner,
                            "cohort": cohort,
                            "contrast_id": contrast_id,
                            "season": year,
                            "n": len(keys),
                            "membership_sha256": key_hash(keys),
                            "log_loss_delta": float(np.mean(loss_delta)),
                            "brier_delta": float(np.mean(brier_delta)),
                            "effect_direction": contrast_id,
                        }
                        annual.append(row)
                        details[(kind, learner, cohort, contrast_id, year)] = {
                            "keys": keys,
                            "loss_delta": loss_delta,
                            "brier_delta": brier_delta,
                        }
    summary = []
    primary_id = primary_contrast_id()
    for kind, years in kinds:
        for learner in LEARNERS:
            for cohort in COHORTS:
                for contrast_id, _ in CONTRASTS:
                    pieces = [details[(kind, learner, cohort, contrast_id, year)] for year in years]
                    annual_ll = [float(np.mean(piece["loss_delta"])) for piece in pieces]
                    annual_brier = [float(np.mean(piece["brier_delta"])) for piece in pieces]
                    all_ll = np.concatenate([piece["loss_delta"] for piece in pieces])
                    all_brier = np.concatenate([piece["brier_delta"] for piece in pieces])
                    is_primary = (
                        kind == "selected"
                        and learner == "hgb"
                        and cohort == "primary"
                        and contrast_id == primary_id
                    )
                    ll_mean = float(np.mean(annual_ll))
                    if is_primary and T_CRITICAL_95 is not None and len(years) > 1:
                        half = t_half_width(annual_ll, T_CRITICAL_95)
                    else:
                        half = None
                    summary.append(
                        {
                            "forecast_kind": kind,
                            "learner": learner,
                            "cohort": cohort,
                            "contrast_id": contrast_id,
                            "years": len(years),
                            "n": len(all_ll),
                            "equal_year_log_loss_delta": ll_mean,
                            "match_weighted_log_loss_delta": float(np.mean(all_ll)),
                            "equal_year_brier_delta": float(np.mean(annual_brier)),
                            "match_weighted_brier_delta": float(np.mean(all_brier)),
                            "years_negative_log_loss": sum(value < 0 for value in annual_ll),
                            "years_positive_log_loss": sum(value > 0 for value in annual_ll),
                            "years_zero_log_loss": sum(value == 0 for value in annual_ll),
                            "approximate_t_lower_95": "" if half is None else ll_mean - half,
                            "approximate_t_upper_95": "" if half is None else ll_mean + half,
                            "primary_comparison": is_primary,
                        }
                    )
    primary_row = next(row for row in summary if row["primary_comparison"])
    priced_row = next(
        row
        for row in summary
        if row["forecast_kind"] == "selected"
        and row["learner"] == "hgb"
        and row["cohort"] == "primary_priced"
        and row["contrast_id"] == primary_id
    )
    primary_annual = [
        row
        for row in annual
        if row["forecast_kind"] == "selected"
        and row["learner"] == "hgb"
        and row["cohort"] == "primary"
        and row["contrast_id"] == primary_id
    ]
    primary: dict[str, Any] = {"comparison": f"selected_calibrated_hgb_{primary_id}"}
    if tour_contract():
        primary["contrast_id"] = primary_id
    primary.update(
        {
            # The primary contrast is `<bundle> - <bundle without the tier block>`,
            # `<bundle with the entry/level block> - <bundle without it>` or
            # `full - base`, so a negative value favours the richer bundle either way.
            "effect_direction": (
                "negative_favors_entry_level_block"
                if f"{TIER_ENTRY_SUFFIX}_minus_" in primary_id
                else "negative_favors_tier_history"
                if primary_id.endswith(f"{TIER_SUFFIX}_minus_full")
                else "negative_favors_full"
            ),
            "population": f"{COHORT}_{min(EVALUATION_YEARS)}_{max(EVALUATION_YEARS)}",
            "n": primary_row["n"],
            "annual_deltas": {str(row["season"]): row["log_loss_delta"] for row in primary_annual},
            "equal_year_log_loss_delta": primary_row["equal_year_log_loss_delta"],
            "match_weighted_log_loss_delta": primary_row["match_weighted_log_loss_delta"],
            "years_negative": primary_row["years_negative_log_loss"],
            "years_positive": primary_row["years_positive_log_loss"],
            "years_zero": primary_row["years_zero_log_loss"],
            "approximate_t_95": [
                primary_row["approximate_t_lower_95"],
                primary_row["approximate_t_upper_95"],
            ],
            "t_critical_95": T_CRITICAL_95,
            "t_degrees_of_freedom": len(EVALUATION_YEARS) - 1,
            "priced_descriptive": {
                "n": priced_row["n"],
                "equal_year_log_loss_delta": priced_row["equal_year_log_loss_delta"],
                "match_weighted_log_loss_delta": priced_row["match_weighted_log_loss_delta"],
            },
            "priority_effect_reference_log_loss": PRIORITY_REFERENCE,
            "priority_reference_interpretation": "planning reference only; an effect smaller than 0.001 does not imply the representation is useless",
        }
    )
    bootstrap_rows, bootstrap_summary, bootstrap_secondary = bootstrap_primary(
        details, inputs.labels
    )
    primary["fixed_prediction_bootstrap"] = bootstrap_summary
    if tour_contract():
        primary["fixed_prediction_bootstrap_secondary"] = bootstrap_secondary
        # Show which raw years' dynamic feature was constant.  The predictor config this
        # report is bound to carries the measurement; a config written without it
        # carries none and the block is simply absent.
        dispersion = inputs.predictor_config.get("dynamic_feature_dispersion_by_raw_year")
        if dispersion:
            primary["dynamic_feature_dispersion_by_raw_year"] = dispersion
            primary["raw_years_with_a_constant_dynamic_feature"] = [
                year
                for year, record in sorted(dispersion.items())
                if not record.get("informative", True)
            ]
    else:
        # Every secondary contrast the config declares gets its own interval from the
        # same seed and the same tournament-edition blocks, so the differences are
        # paired rather than independently resampled.
        secondary: dict[str, Any] = {}
        for contrast_id in secondary_contrast_ids():
            rows, summary_block = bootstrap_contrast(details, inputs.labels, contrast_id)
            bootstrap_rows.extend(rows)
            secondary_row = next(
                row
                for row in summary
                if row["forecast_kind"] == "selected"
                and row["learner"] == "hgb"
                and row["cohort"] == "primary"
                and row["contrast_id"] == contrast_id
            )
            secondary[contrast_id] = {
                "comparison": f"selected_calibrated_hgb_{contrast_id}",
                "n": secondary_row["n"],
                "equal_year_log_loss_delta": secondary_row["equal_year_log_loss_delta"],
                "match_weighted_log_loss_delta": secondary_row["match_weighted_log_loss_delta"],
                "years_negative": secondary_row["years_negative_log_loss"],
                "fixed_prediction_bootstrap": summary_block,
            }
        primary["secondary_contrasts"] = secondary
    return annual, summary, primary, bootstrap_rows


def bootstrap_unit_blocks(
    detail: Mapping[str, Any],
    labels: Mapping[tuple[str, str], Mapping[str, str]],
    unit: str,
) -> list[list[int]]:
    """The resampling blocks of one year: one match each, or one edition each."""
    if unit == "match":
        return [[index] for index in range(len(detail["keys"]))]
    grouped: dict[str, list[int]] = {}
    for index, key in enumerate(detail["keys"]):
        grouped.setdefault(labels[key]["tourney_id"], []).append(index)
    return [grouped[name] for name in sorted(grouped)]


def _bootstrap_years(
    details: Mapping[tuple, Mapping[str, Any]],
    labels: Mapping[tuple[str, str], Mapping[str, str]],
    contrast_id: str,
    unit: str,
) -> tuple[list[dict[str, Any]], float, float]:
    """One generator seeded with `BOOTSTRAP_SEED`, consumed in evaluation-year order."""
    if unit not in BOOTSTRAP_UNITS:
        raise ReportError(f"unknown bootstrap unit {unit!r}")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    matrix = np.zeros((BOOTSTRAP_REPLICATES, len(EVALUATION_YEARS)), dtype=np.float64)
    years = []
    for column, year in enumerate(EVALUATION_YEARS):
        detail = details[("selected", "hgb", "primary", contrast_id, year)]
        blocks = bootstrap_unit_blocks(detail, labels, unit)
        values = block_bootstrap(detail["loss_delta"], blocks, BOOTSTRAP_REPLICATES, rng)
        matrix[:, column] = values
        lower, upper = quantile_interval(values)
        years.append(
            {
                "season": year,
                "n": len(detail["keys"]),
                "blocks": len(blocks),
                "point_log_loss_delta": float(np.mean(detail["loss_delta"])),
                "bootstrap_lower_95": lower,
                "bootstrap_upper_95": upper,
            }
        )
    lower, upper = quantile_interval(matrix.mean(axis=1))
    return years, lower, upper


def bootstrap_contrast(
    details: Mapping[tuple, Mapping[str, Any]],
    labels: Mapping[tuple[str, str], Mapping[str, str]],
    contrast_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The tier-contract shape: tournament-edition blocks, rows keyed by contrast."""
    years, lower, upper = _bootstrap_years(details, labels, contrast_id, "tournament_edition")
    annual_scope, summary_scope = BOOTSTRAP_SCOPES["tournament_edition"]
    rows = [
        {
            "contrast_id": contrast_id,
            "season": year["season"],
            "n": year["n"],
            "tournament_edition_blocks": year["blocks"],
            "point_log_loss_delta": year["point_log_loss_delta"],
            "bootstrap_lower_95": year["bootstrap_lower_95"],
            "bootstrap_upper_95": year["bootstrap_upper_95"],
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "scope": annual_scope,
        }
        for year in years
    ]
    return rows, {
        "contrast_id": contrast_id,
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "lower_95": lower,
        "upper_95": upper,
        "scope": summary_scope,
        "models_refit": False,
        "selection_refit": False,
    }


def bootstrap_for_unit(
    details: Mapping[tuple, Mapping[str, Any]],
    labels: Mapping[tuple[str, str], Mapping[str, str]],
    unit: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The tour-contract shape: one resampling unit's rows and equal-year interval."""
    years, lower, upper = _bootstrap_years(details, labels, primary_contrast_id(), unit)
    annual_scope, summary_scope = BOOTSTRAP_SCOPES[unit]
    rows = [
        {
            "unit": unit,
            "season": year["season"],
            "n": year["n"],
            "resampling_blocks": year["blocks"],
            "point_log_loss_delta": year["point_log_loss_delta"],
            "bootstrap_lower_95": year["bootstrap_lower_95"],
            "bootstrap_upper_95": year["bootstrap_upper_95"],
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "scope": annual_scope,
        }
        for year in years
    ]
    return rows, {
        "unit": unit,
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "lower_95": lower,
        "upper_95": upper,
        "scope": summary_scope,
        "models_refit": False,
        "selection_refit": False,
    }


def bootstrap_primary(
    details: Mapping[tuple, Mapping[str, Any]],
    labels: Mapping[tuple[str, str], Mapping[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    """The declared primary contrast's fixed-prediction bootstrap.

    Under the tour contract every registered unit is computed; the configured one is
    the published primary and the other is returned as a labelled secondary.  Under
    the tier contract only tournament-edition blocks are resampled and the secondary
    mapping is empty.
    """
    if not tour_contract():
        rows, summary = bootstrap_contrast(details, labels, primary_contrast_id())
        return rows, summary, {}
    if BOOTSTRAP_UNIT is None:
        raise ReportError("no bootstrap unit is configured")
    emitted = {unit: bootstrap_for_unit(details, labels, unit) for unit in BOOTSTRAP_UNITS}
    rows = [row for unit in BOOTSTRAP_UNITS for row in emitted[unit][0]]
    return (
        rows,
        emitted[BOOTSTRAP_UNIT][1],
        {unit: emitted[unit][1] for unit in BOOTSTRAP_UNITS if unit != BOOTSTRAP_UNIT},
    )


def fixed_reliability(pairs: Sequence[tuple[float, int]]) -> list[dict[str, Any]]:
    return reliability_bins(pairs, RELIABILITY_EDGES)


def reliability_rows(inputs: Inputs) -> list[dict[str, Any]]:
    output = []
    selected_models = {
        (item.learner, item.block): [] for item in inputs.forecasts if item.kind == "selected"
    }
    market_models = {model: [] for model in ("raw_ps", "calibrated_ps")}
    for item in inputs.forecasts:
        if item.kind == "selected":
            selected_models[(item.learner, item.block)].append(item)
        elif item.kind == "market":
            market_models[item.candidate_id].append(item)

    def emit(
        model_id: str, cohort: str, year: str | int, pairs: Sequence[tuple[float, int]]
    ) -> None:
        for row in fixed_reliability(pairs):
            output.append(
                {
                    "scope": "pooled" if year == "pooled" else "annual",
                    "season": year,
                    "cohort": cohort,
                    "model_id": model_id,
                    **row,
                }
            )

    for (learner, block), items in sorted(selected_models.items()):
        items.sort(key=lambda item: item.year)
        for cohort in ("primary", "primary_priced"):
            pooled = []
            for item in items:
                keys = cohort_keys(tuple(item.predictions), cohort, inputs.labels, inputs.features)
                pairs = [(item.predictions[key], int(inputs.labels[key]["a_won"])) for key in keys]
                emit(item.model_id, cohort, item.year, pairs)
                pooled.extend(pairs)
            emit(f"selected/{learner}/{block}", cohort, "pooled", pooled)
    for model, items in sorted(market_models.items()):
        items.sort(key=lambda item: item.year)
        pooled = []
        for item in items:
            pairs = [
                (item.predictions[key], int(inputs.labels[key]["a_won"]))
                for key in item.predictions
            ]
            emit(item.model_id, "primary_priced", item.year, pairs)
            pooled.extend(pairs)
        emit(f"market/{model}", "primary_priced", "pooled", pooled)
    return output


def recompute_selection_criteria(inputs: Inputs) -> dict[str, Any]:
    """Recompute every selection criterion after the barrier and check the commitments.

    Decision RB14: the pipeline wrote each fold's decision, membership and a hash of
    the criterion table (past-year log losses per candidate, the ranked scores, the
    runner-up gap) but not the scores themselves. This recomputes the table from the
    persisted raw forecasts, the persisted selection keys and the labels with the
    pipeline's own arithmetic, requires the hash and the decision to match, and returns
    the full table for publication. A pipeline whose decision is not the argmin of its
    recomputed criterion fails here.
    """
    from tennislab.models import numerical as NUM
    from tennislab.models import pipeline

    pipeline_dir = inputs.selection_path.parent
    raw = {
        (item.year, item.learner, item.block, item.candidate_id): item
        for item in inputs.forecasts
        if item.kind == "raw"
    }
    selection_out: list[dict[str, Any]] = []
    gaps: dict[tuple[str, int, str, str], Any] = {}
    for record in inputs.selection_records:
        year = int(record["outer_year"])
        learner, block = record["learner"], record["block"]
        years = tuple(int(item) for item in record["selection_years"])
        keys_path = pipeline_dir / str(record.get("selection_keys_path", ""))
        if not keys_path.is_file():
            raise ReportError(f"selection keys missing: {year}/{learner}/{block}")
        keys = pipeline.read_selection_keys(keys_path)
        if NUM.key_hash(keys) != record.get("selection_membership_sha256"):
            raise ReportError(f"selection keys differ from their membership hash: {year}")
        keys_by_year = {y: tuple(key for key in keys if int(key[0]) == y) for y in years}
        if any(not keys_by_year[y] for y in years):
            raise ReportError(f"selection keys cover no row of a selection year: {year}")
        labels_by_year = {
            y: [int(inputs.labels[key]["a_won"]) for key in keys_by_year[y]] for y in years
        }
        public_trials = record.get("candidate_trials")
        if not isinstance(public_trials, dict):
            raise ReportError(f"selection record without candidate trials: {year}")
        trials: dict[str, dict[str, Any]] = {}
        for candidate, public in public_trials.items():
            if public.get("status") != "complete":
                trials[candidate] = {
                    "status": public.get("status"),
                    "slope": None,
                    "equal_year_mean_log_loss": None,
                    "error": public.get("error"),
                }
                continue
            probabilities = {
                y: [raw[(y, learner, block, candidate)].predictions[key] for key in keys_by_year[y]]
                for y in years
            }
            trials[candidate] = pipeline.fit_nonnegative_slope(probabilities, labels_by_year, years)
        selected = pipeline.select_calibrated_candidate(trials, list(public_trials))
        criterion = pipeline.criterion_document(trials, selected)
        if common.canonical_hash(criterion) != record.get("criterion_sha256"):
            raise ReportError(
                f"recomputed selection criterion differs from the pipeline's commitment: "
                f"{year}/{learner}/{block}"
            )
        if selected.get("selected_candidate_id") != record.get(
            "selected_candidate_id"
        ) or selected.get("selected_slope") != record.get("selected_slope"):
            raise ReportError(
                f"pipeline decision is not the argmin of its criterion: {year}/{learner}/{block}"
            )
        gaps[("selected", year, learner, block)] = selected.get("runner_up_gap")
        selection_out.append(
            {
                "outer_year": year,
                "learner": learner,
                "block": block,
                "selection_years": list(years),
                "selection_keys_sha256": sha256(keys_path),
                "criterion_sha256": record["criterion_sha256"],
                "candidate_trials": trials,
                "selection": selected,
            }
        )
    market_out: list[dict[str, Any]] = []
    for record in inputs.market_records:
        year = int(record["outer_year"])
        years = tuple(int(item) for item in record["selection_years"])
        keys_path = pipeline_dir / str(record.get("selection_keys_path", ""))
        if not keys_path.is_file():
            raise ReportError(f"market selection keys missing: {year}")
        keys = pipeline.read_selection_keys(keys_path)
        if NUM.key_hash(keys) != record.get("selection_membership_sha256"):
            raise ReportError(f"market selection keys differ from their membership hash: {year}")
        keys_by_year = {y: tuple(key for key in keys if int(key[0]) == y) for y in years}
        fit = pipeline.fit_nonnegative_slope(
            {
                y: [float(inputs.features[key]["ps_probability_a"]) for key in keys_by_year[y]]
                for y in years
            },
            {y: [int(inputs.labels[key]["a_won"]) for key in keys_by_year[y]] for y in years},
            years,
        )
        if common.canonical_hash(pipeline.fit_criterion_document(fit)) != record.get(
            "criterion_sha256"
        ):
            raise ReportError(
                f"recomputed market slope fit differs from the pipeline's commitment: {year}"
            )
        if fit.get("slope") != record.get("slope"):
            raise ReportError(f"market slope differs from its recomputed fit: {year}")
        market_out.append(
            {
                "outer_year": year,
                "selection_years": list(years),
                "selection_keys_sha256": sha256(keys_path),
                "criterion_sha256": record["criterion_sha256"],
                "slope_fit": fit,
            }
        )
    return {
        "status": "recomputed_after_barrier",
        "basis": "RB14: pipeline commitments verified; scores published here, never before the barrier",
        "selection_records": selection_out,
        "market_records": market_out,
        "runner_up_gaps": gaps,
    }


def selection_diagnostics(
    inputs: Inputs, gaps: Mapping[tuple[str, int, str, str], Any] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    gaps = gaps or {}
    for kind, records in (
        ("selected", inputs.selection_records),
        ("shared_base", inputs.shared_records),
        ("market", inputs.market_records),
    ):
        for record in records:
            year = int(record_field(record, ("outer_year", "year"), f"{kind} year"))
            learner = record.get("learner", "")
            block = record.get("block", "")
            selection = (
                record.get("selection", {}) if isinstance(record.get("selection", {}), dict) else {}
            )
            slope_fit = (
                record.get("slope_fit", {}) if isinstance(record.get("slope_fit", {}), dict) else {}
            )
            candidate = record.get(
                "selected_candidate_id",
                record.get("candidate_id", selection.get("selected_candidate_id", "")),
            )
            slope = record.get(
                "selected_slope",
                record.get("slope", selection.get("selected_slope", slope_fit.get("slope", ""))),
            )
            gap = record.get("runner_up_gap", selection.get("runner_up_gap", ""))
            if (kind, year, learner, block) in gaps:
                gap = gaps[(kind, year, learner, block)]
            if slope == "" or not math.isfinite(float(slope)) or float(slope) < 0.0:
                raise ReportError(f"missing/invalid saved slope in {kind}/{year}/{learner}/{block}")
            rows.append(
                {
                    "kind": kind,
                    "season": year,
                    "learner": learner,
                    "block": block,
                    "candidate_id": candidate,
                    "slope": slope,
                    "runner_up_gap": gap,
                    "selection_years": json.dumps(
                        record.get("selection_years", record.get("past_selection_years", "")),
                        separators=(",", ":"),
                    ),
                    "selection_rows": record.get(
                        "selection_rows", record.get("past_selection_rows", "")
                    ),
                    "selection_membership_sha256": record.get(
                        "selection_membership_sha256",
                        record.get("past_selection_membership_sha256", ""),
                    ),
                    "selection_cutoff": record.get(
                        "selection_cutoff_inclusive",
                        record.get("selection_cutoff", record.get("past_selection_cutoff", "")),
                    ),
                }
            )
    linked = {
        "selection_complete_path": relative_to_root(inputs.selection_path),
        "selection_complete_sha256": inputs.binding_hashes["selection_complete"],
        "selection_records": inputs.selection_records,
        "shared_base_records": inputs.shared_records,
        "market_records": inputs.market_records,
        "note": "Saved slopes, candidate trials, selected settings, rankings, runner-up gaps, and source forecast hashes are copied without refitting.",
    }
    return rows, linked


SCOPE_TEXT = """## Scope

All metrics use frozen predictions. The report did not refit models, selection, calibration, or features. Log loss alone clips to [1e-15, 1-1e-15]; Brier uses emitted probabilities. Completed-primary and primary-plus-provisional rows are unchanged-prediction sensitivities. The provisional-inclusive cohort includes both primary and provisional rows, reported with separate counts. Target-year outcomes enter the chain here and nowhere earlier; whether this window is exposed development or reserved evidence is a property of the configured target years, not of this program.
"""
PRICED_TEXT = (
    "The primary-priced diagnostic has n={n}; it is a common-membership probability-quality "
    "reference with unknown quote timing. The fixed 0.001 effect is a planning reference, not "
    "a significance, profitability, usefulness, or feature-admission threshold."
)


def markdown_report(primary: Mapping[str, Any], bootstrap: Mapping[str, Any]) -> str:
    interval = primary["approximate_t_95"]
    if interval[0] == "" or interval[1] == "":
        t_line = (
            f"- approximate across-year t interval: suppressed "
            f"({len(EVALUATION_YEARS)} target year(s) leave {len(EVALUATION_YEARS) - 1} degrees of freedom)"
        )
    else:
        t_line = (
            f"- approximate t{primary['t_degrees_of_freedom']} 95% interval: "
            f"[{interval[0]:.12g}, {interval[1]:.12g}]"
        )
    window = (
        f"{min(EVALUATION_YEARS)}–{max(EVALUATION_YEARS)}"
        if len(EVALUATION_YEARS) > 1
        else str(EVALUATION_YEARS[0])
    )
    priced = PRICED_TEXT.format(n=primary["priced_descriptive"]["n"])
    common_lines = (
        f"- n: {primary['n']}\n"
        f"- equal-year mean log-loss delta: {primary['equal_year_log_loss_delta']:.12g}\n"
        f"- match-weighted log-loss delta: {primary['match_weighted_log_loss_delta']:.12g}\n"
        f"- negative / positive / exact-zero years: {primary['years_negative']} / {primary['years_positive']} / {primary['years_zero']}\n"
        f"{t_line}\n"
    )
    if tour_contract():
        secondary_lines = "".join(
            f"\n- secondary fixed-prediction bootstrap 95% interval, {unit} resampling unit: "
            f"[{record['lower_95']:.12g}, {record['upper_95']:.12g}]"
            for unit, record in sorted(
                primary.get("fixed_prediction_bootstrap_secondary", {}).items()
            )
        )
        contrast_id = primary["contrast_id"]
        left, right = (
            contrast_id.split("_minus_", 1) if "_minus_" in contrast_id else (contrast_id, "")
        )
        comparison = (
            f"Selected/calibrated {left} HGB minus selected/calibrated {right} HGB"
            if right
            else f"Selected/calibrated HGB contrast {contrast_id}"
        )
        return (
            f"# {EXPERIMENT_ID} reporting output\n\n## Primary comparison\n\n"
            f"{comparison} on {COHORT} {window} matches:\n\n"
            f"{common_lines}"
            f"- published fixed-prediction bootstrap 95% interval, {bootstrap['unit']} resampling "
            f"unit: [{bootstrap['lower_95']:.12g}, {bootstrap['upper_95']:.12g}] "
            f"(seed {bootstrap['seed']}, {bootstrap['replicates']} replicates){secondary_lines}\n\n"
            f"{priced}\n\n{SCOPE_TEXT}"
        )
    secondary_lines = ""
    for contrast_id, block in (primary.get("secondary_contrasts") or {}).items():
        interval_block = block["fixed_prediction_bootstrap"]
        secondary_lines += (
            f"\n## Secondary comparison: {contrast_id}\n\n"
            f"- n: {block['n']}\n"
            f"- equal-year mean log-loss delta: {block['equal_year_log_loss_delta']:.12g}\n"
            f"- match-weighted log-loss delta: {block['match_weighted_log_loss_delta']:.12g}\n"
            f"- negative years: {block['years_negative']}\n"
            "- fixed-prediction tournament-edition bootstrap 95% interval: "
            f"[{interval_block['lower_95']:.12g}, {interval_block['upper_95']:.12g}]\n"
        )
    return (
        f"# {EXPERIMENT_ID} reporting output\n\n## Primary comparison\n\n"
        f"{primary['comparison']} on aligned primary {window} matches:\n\n"
        f"{common_lines}"
        "- fixed-prediction tournament-edition bootstrap 95% interval: "
        f"[{bootstrap['lower_95']:.12g}, {bootstrap['upper_95']:.12g}]\n\n"
        f"{secondary_lines}\n{priced}\n\n{SCOPE_TEXT}"
    )


def run(config_path: Path, output: Path) -> dict[str, Any]:
    inputs = preflight(config_path)
    output = _inside_root(output)
    # An *empty* pre-created directory is allowed: the chain driver creates the stage
    # directory before launching this program.  A nonempty directory is still refused,
    # so a second scoring pass cannot overwrite the first.
    if output.exists() and any(output.iterdir()):
        raise ReportError(f"output already exists and is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    start: dict[str, Any] = {"experiment_id": EXPERIMENT_ID}
    if tour_contract():
        start["tour"] = TOUR
    start.update(
        {
            "status": "bindings_validated_before_scoring",
            "started_utc": dt.datetime.now(dt.UTC).isoformat(),
            "binding_hashes": inputs.binding_hashes,
            "declared_binding": inputs.declared_code,
            "code": code_receipt(__name__),
            "score_semantics": {
                "log_loss_clip": SCORE_CLIP,
                "brier": "emitted_probability_unclipped",
            },
        }
    )
    atomic_json(output / "start.json", start)
    metrics = annual_metrics(inputs)
    pooled = pooled_metrics(metrics)
    coverage = coverage_rows(inputs)
    annual, summaries, primary, bootstrap_rows = contrast_outputs(inputs)
    reliability = reliability_rows(inputs)
    criteria = recompute_selection_criteria(inputs)
    diagnostic_rows, diagnostic_link = selection_diagnostics(inputs, criteria["runner_up_gaps"])
    diagnostic_link["criteria_recomputed_after_barrier"] = "selection_trials.json"
    hashes = {
        "annual_metrics.csv": write_csv(output / "annual_metrics.csv", metrics, tuple(metrics[0])),
        "pooled_metrics.csv": write_csv(output / "pooled_metrics.csv", pooled, tuple(pooled[0])),
        "coverage.csv": write_csv(output / "coverage.csv", coverage, tuple(coverage[0])),
        "annual_contrasts.csv": write_csv(
            output / "annual_contrasts.csv", annual, tuple(annual[0])
        ),
        "contrast_summary.csv": write_csv(
            output / "contrast_summary.csv", summaries, tuple(summaries[0])
        ),
        "bootstrap.csv": write_csv(
            output / "bootstrap.csv", bootstrap_rows, tuple(bootstrap_rows[0])
        ),
        "reliability.csv": write_csv(
            output / "reliability.csv", reliability, tuple(reliability[0])
        ),
        "selection_diagnostics.csv": write_csv(
            output / "selection_diagnostics.csv", diagnostic_rows, tuple(diagnostic_rows[0])
        ),
    }
    atomic_json(output / "selection_receipts.json", diagnostic_link)
    atomic_json(
        output / "selection_trials.json",
        {key: value for key, value in criteria.items() if key != "runner_up_gaps"},
    )
    atomic_json(output / "primary.json", primary)
    (output / "report.md").write_text(
        markdown_report(primary, primary["fixed_prediction_bootstrap"]), encoding="utf-8"
    )
    hashes.update(
        {
            "selection_receipts.json": sha256(output / "selection_receipts.json"),
            "selection_trials.json": sha256(output / "selection_trials.json"),
            "primary.json": sha256(output / "primary.json"),
            "report.md": sha256(output / "report.md"),
        }
    )
    result = {
        "status": "complete",
        "completed_utc": dt.datetime.now(dt.UTC).isoformat(),
        "primary": primary,
        "files": hashes,
        "counts": {
            "annual_metric_rows": len(metrics),
            "pooled_metric_rows": len(pooled),
            "annual_contrast_rows": len(annual),
            "contrast_summary_rows": len(summaries),
            "reliability_rows": len(reliability),
            "selection_diagnostic_rows": len(diagnostic_rows),
        },
        "forbidden_analyses": {
            "model_refits": 0,
            "calibration_refits": 0,
            "p_values": 0,
            "feature_importance": 0,
            "feature_screening": 0,
        },
    }
    atomic_json(output / "result.json", result)
    artifacts = []
    for path in sorted(
        item
        for item in output.iterdir()
        if item.is_file() and item.name != "artifact_manifest.json"
    ):
        artifacts.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    atomic_json(output / "artifact_manifest.json", {"status": "complete", "files": artifacts})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--run", action="store_true", help="execute reporting after fail-closed preflight"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.run:
        print("--run is required; no report was created", file=sys.stderr)
        return 1
    try:
        result = run(args.config, args.output)
    except ChainError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"status": result["status"], "primary": result["primary"], "files": result["files"]},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
