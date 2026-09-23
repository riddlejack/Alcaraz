"""Bounded annual fit, past-only selection and calibration: stages ``preflight`` and ``pipeline``.

Base revision: the archive's ``references/TIER01_models/runner.py`` (the tier bundles,
the ``full_tier_noqual`` ablation, a measured wall clock per fit attempt). Merged from
``references/WTA02_models/runner.py`` under the tour switch: the configured experiment
identity and tour, the membership predicate (``cohort``), and the dynamic-feature
dispersion receipts. Nothing about the JOINT04 menu, training window, selection or
calibration moved.

Two settings contracts exist in the archive and both are honoured here. The TIER01
contract declares no tour and freezes ``tier_columns`` in its settings; the WTA02
contract declares ``tour`` and ``cohort`` and writes the dispersion receipts. A
configuration that declares a tour is read under the WTA02 contract, one that does not
under TIER01's; ``tour_contract()`` is that switch. Tier bundles are TIER01's and are
refused under the tour contract, whose settings could not record them.

Draw-time context (ARMS01 Arm 1): the ``*_tier_entry`` bundle is the ``*_tier`` bundle
plus the entry/level block the features stage emits under ``entry_level_block``:
``ENTRY_LEVEL_SIGNED`` (signed A-B entry-status differences for Q, LL, WC, PR) in the HGB
signed list and ``ENTRY_LEVEL_CONTEXT`` (the symmetric any-qualifier flag and the G/M/A/F
level indicators) in the HGB context list, appended after every existing column. The
rule is explicit: tournament level enters only as swap-invariant context, entry status
only as draw-time status, and the round never. The raw ``tourney_level``, ``round``,
``a_entry``/``b_entry``, seeds and draw size stay in ``FORBIDDEN_MODEL_COLUMNS``; a
dictionary that lists any of them as a model column is refused. Without an entry bundle
the settings document, the column order and every existing bundle are unchanged.
The WTA secondary has no tier block: its ``*_entry`` bundle (``full_entry``) is the
JOINT04 bundle of the same stem plus the same block, and it is the one variant the tour
(WTA02) settings contract admits; the contract then records ``entry_level_columns``.

Code bindings: the archive loaded ``numerical.py`` by path at a pinned hash and checked
its own file hash against the config. Here the adapter is ``tennislab.models.numerical``
imported by name; a config's ``code`` block is recorded as the declared binding and
verified only when it names a package module.

Outcomes: every read of ``labels.csv`` before the reporter goes through
``tennislab.chain.labels.LabelHistory`` and is marked ``# outcome-history read``. The
year plan object is ``tennislab.models.year_plan.YearPlan``; ``DEFAULT_YEAR_PLAN`` and
``configure_years`` live here because they install this module's year state.

Public interface kept for: ``tennislab.chain.configs`` (``configure_years``,
``configure_identity``, ``configure_bundles``, ``configure_cohort``,
``runtime_description``, ``FeatureContract``, ``assemble_feature_bundle``,
``target_keys``, ``provisional_target_keys``, ``all_prediction_keys``, ``training_keys``,
``selection_keys``, ``is_aligned_primary``, ``candidate_ids``, ``ordered_model_columns``,
``LABEL_COLUMNS``, ``RAW_YEARS``, ``OUTER_YEARS``, ``BLOCKS``, ``LEARNERS``, ``NUM``,
``dynamic_dispersion_by_raw_year``, ``training_window_dispersion``,
``tour_contract``); ``tennislab.features.tier_block`` (``FeatureContract``,
``FORBIDDEN_MODEL_COLUMNS``, ``TIER_SIGNED``, ``TIER_DYNAMIC_SIGNED``,
``TIER_DYNAMIC_PROBABILITY``, ``TIER_NOQUAL_DYNAMIC_SIGNED``,
``TIER_NOQUAL_DYNAMIC_PROBABILITY``, ``TIER_SIDECAR_INPUTS``, ``TIER_COLUMNS``,
``TIER_NOQUAL_COLUMNS``, ``TIER_PROVENANCE_ONLY_COLUMNS``,
``TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS``, ``training_window``, ``split_block``,
``tier_enabled``, ``noqual_enabled``); ``tennislab.ratings.tier_elo``
(``training_window``, ``DEFAULT_YEAR_PLAN``); the tests (``Joint04Error``,
``transformed_additions``, ``numerical_config``, ``fit_nonnegative_slope``,
``select_calibrated_candidate``, ``weighted_calibration_arrays``, ``apply_slope``,
``is_valid_market``, ``validation_years``, ``settings_document``, ``TRAIT_SIGNED``,
``TRAIT_HGB_CONTEXT``, ``DYNAMIC_SIGNED``, ``LOGIT_CLIP``, ``SCORE_CLIP``,
``RIDGE_PARAMS``, ``HGB_PARAMS``, ``RIDGE_CANDIDATES``, ``HGB_CANDIDATES``).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import multiprocessing
import os
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy import optimize

from tennislab.chain import access, common
from tennislab.chain.common import (
    ChainError,
    code_receipt,
    read_config,
    relative_to_root,
    require_nonempty_digest,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
)
from tennislab.chain.labels import LABEL_COLUMNS, LabelHistory
from tennislab.models import numerical as NUM
from tennislab.models.year_plan import YearPlan, YearPlanError

NUMERICAL_MODULE = "tennislab.models.numerical"
RUNNER_MODULE = "tennislab.models.pipeline"

# The TIER01 revision's literal is the default identity; the WTA02 revision declares its
# own `experiment_id` and `tour` beside the year plan (its defect D2).
DEFAULT_EXPERIMENT_ID = "TIER01"
TOURS = ("ATP", "WTA")
EXPERIMENT_ID = DEFAULT_EXPERIMENT_ID
TOUR: str | None = None

# `BLOCKS` and `LEARNERS` are installed by `configure_bundles()` from the frozen config,
# exactly as RAW_YEARS/OUTER_YEARS are installed by `configure_years()`.  The defaults
# are JOINT04's, so every JOINT04/CONFIRM2026 year-plan file written before TIER01
# still produces the same predictor configuration.
BASE_BLOCKS = ("base", "traits", "dynamic", "full")
TIER_SUFFIX = "_tier"
# The same-event-qualifying ablation bundle.  `full_tier_noqual` is `full_tier` with its
# tier dynamic logit replaced by the one fed without qualifying rows carried under a main
# draw's own tourney id; the Elo and experience columns are the same objects.  Checked
# before TIER_SUFFIX, because it ends with it.
TIER_NOQUAL_SUFFIX = "_tier_noqual"
# ARMS01 Arm 1: `full_tier_entry` is `full_tier` plus the entry/level block.  Checked
# first in `split_block`; the three variant suffixes are pairwise non-nested.
TIER_ENTRY_SUFFIX = "_tier_entry"
# ARMS01 WTA secondary: `full_entry` is the JOINT04 `full` bundle plus the same block (the
# WTA chain has no tier block).  Tested after every tier suffix, since `_tier_entry` ends
# with it.  The variants that carry the tier block are TIER_VARIANTS; the entry block is
# carried by ENTRY_VARIANTS.
ENTRY_SUFFIX = "_entry"
TIER_VARIANTS = frozenset({"tier", "tier_noqual", "tier_entry"})
ENTRY_VARIANTS = frozenset({"tier_entry", "entry"})
DEFAULT_BLOCKS = BASE_BLOCKS
DEFAULT_LEARNERS = ("ridge", "hgb")
BLOCKS = DEFAULT_BLOCKS
LEARNERS = DEFAULT_LEARNERS
# Blocks whose model columns include the SR02 dynamic predictor.  A cohort that does
# not require a dynamic probability cannot fit one of these: a training row with a
# blank `dynamic_match_logit` has no value to fit.
DYNAMIC_BLOCKS = frozenset({"dynamic", "full"})
# The membership predicate.  `aligned_primary` is JOINT04's, unchanged and the default.
# `aligned_primary_no_dynamic` drops the two SR02 requirements and nothing else, for the
# WTA secondary base-and-traits comparison, whose population reaches back before the
# WTA dynamic block exists.  Every field either predicate reads is knowable at the
# cutoff; no cohort is defined on an outcome.
COHORT_MODES = ("aligned_primary", "aligned_primary_no_dynamic")
COHORT = "aligned_primary"
TIE_TOLERANCE = 1e-12
LOGIT_CLIP = 1e-6
SCORE_CLIP = 1e-15

TRAIT_SIGNED = (
    "trait_z_age_diff",
    "trait_z_age_sq_diff",
    "trait_height_10cm_diff",
    "trait_left_hand_diff",
    "trait_age_missing_diff",
    "trait_height_missing_diff",
    "trait_hand_missing_diff",
)
TRAIT_HGB_CONTEXT = (
    "trait_mean_z_age",
    "trait_mean_centered_height",
    "trait_age_missing_sum",
    "trait_height_missing_sum",
    "trait_hand_missing_sum",
)
DYNAMIC_SIGNED = ("dynamic_match_logit",)

# TIER01's prespecified block: the two tier-inclusive pooled-Elo logits (each already a
# signed A-B difference, exactly like JOINT04's own `elo_overall_logit`), the two signed
# lower-tier experience differences, and -- for a bundle that already carries the dynamic
# block -- the tier-inclusive dynamic logit, which *replaces nothing*: both dynamic logits
# are kept.  These tuples must equal `tier_block.TIER_SIGNED` /
# `tier_block.TIER_DYNAMIC_SIGNED`, so the model column list cannot drift between the
# program that computes the block and the program that fits it.  The columns arrive on
# the sidecar, never on the base feature table, and enter only the `*_tier` bundles.
TIER_SIGNED = (
    "tier_elo_overall_logit",
    "tier_elo_surface_logit",
    "tier_prior_matches_diff",
    "tier_prior_titles_diff",
)
TIER_DYNAMIC_SIGNED = ("tier_dynamic_match_logit",)
# The sidecar input the tier dynamic logit is derived from, by the same clip-and-logit
# transformation `dynamic_match_probability_a` already goes through below.
TIER_DYNAMIC_PROBABILITY = "tier_dynamic_match_probability_a"
TIER_NOQUAL_DYNAMIC_SIGNED = ("tier_noqual_dynamic_match_logit",)
TIER_NOQUAL_DYNAMIC_PROBABILITY = "tier_noqual_dynamic_match_probability_a"
TIER_SIDECAR_INPUTS = TIER_SIGNED + (TIER_DYNAMIC_PROBABILITY,)
TIER_COLUMNS = TIER_SIGNED + TIER_DYNAMIC_SIGNED
TIER_NOQUAL_COLUMNS = TIER_NOQUAL_DYNAMIC_SIGNED
# TIER01 provenance: how a rating was initialised, how stale a tier-inclusive state was,
# how much lower-tier history existed, and the prespecified thin-side subgroup indicator.
# Every one of them describes data availability or cohort membership rather than tennis,
# and every one is refused as a model column.
TIER_PROVENANCE_ONLY_COLUMNS = (
    "tier_first_tier_a",
    "tier_first_tier_b",
    "tier_initial_offset_applied_a",
    "tier_initial_offset_applied_b",
    "tier_last_lower_match_days_a",
    "tier_last_lower_match_days_b",
    "tier_history_absent_overall_a",
    "tier_history_absent_overall_b",
    "tier_history_absent_surface_a",
    "tier_history_absent_surface_b",
    "tier_prior_matches_raw_a",
    "tier_prior_matches_raw_b",
    "tier_prior_titles_raw_a",
    "tier_prior_titles_raw_b",
    "tier_prior_tour_matches_a",
    "tier_prior_tour_matches_b",
    "tier_thin_side",
    "tier_dynamic_state_stale_days_a",
    "tier_dynamic_state_stale_days_b",
    "tier_dynamic_state_stale_days",
)
TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS = (
    "tier_noqual_dynamic_state_stale_days_a",
    "tier_noqual_dynamic_state_stale_days_b",
    "tier_noqual_dynamic_state_stale_days",
)

# ARMS01 Arm 1: the entry/level block.  Computed by the features stage from the panel's
# draw-time entry codes and the event's level, and appended to the feature file after
# every existing column.  These tuples must equal `tennislab.features.base`'s
# `ENTRY_LEVEL_SIGNED` / `ENTRY_LEVEL_CONTEXT`; the tests assert it.  The signed columns
# are A-B differences of per-side indicators (Q, LL, WC, PR) and negate under a player
# swap; the context columns (either side a qualifier or lucky loser; level G/M/A/F) are
# functions of the unordered pair and the event and do not.  The raw codes and the raw
# level are audit columns and are refused below.
ENTRY_LEVEL_SIGNED = ("entry_q_diff", "entry_ll_diff", "entry_wc_diff", "entry_pr_diff")
ENTRY_LEVEL_CONTEXT = (
    "entry_any_qualifier",
    "level_context_g",
    "level_context_m",
    "level_context_a",
    "level_context_f",
)
ENTRY_LEVEL_COLUMNS = ENTRY_LEVEL_SIGNED + ENTRY_LEVEL_CONTEXT
ENTRY_RAW_COLUMNS = ("a_entry", "b_entry")

RIDGE_CANDIDATES = (
    ("ridge_c001", 0.01),
    ("ridge_c01", 0.1),
    ("ridge_c1", 1.0),
)
HGB_CANDIDATES = (
    ("hgb_leaf07_depth3", 7, 3),
    ("hgb_leaf15_depth4", 15, 4),
)
RF_CANDIDATES = (
    ("rf_leaf50", 50),
    ("rf_leaf100", 100),
)

RIDGE_PARAMS = {
    "C": 1.0,
    "class_weight": None,
    "fit_intercept": False,
    "l1_ratio": 0.0,
    "max_iter": 5000,
    "random_state": 71101,
    "solver": "lbfgs",
    "tol": 1e-7,
    "verbose": 0,
    "warm_start": False,
}
HGB_PARAMS = {
    "early_stopping": False,
    "l2_regularization": 10.0,
    "learning_rate": 0.05,
    "loss": "log_loss",
    "max_bins": 255,
    "max_depth": 3,
    "max_iter": 200,
    "max_leaf_nodes": 7,
    "min_samples_leaf": 80,
    "random_state": 71101,
}
RF_PARAMS = {
    "bootstrap": True,
    "ccp_alpha": 0.0,
    "class_weight": None,
    "criterion": "log_loss",
    "max_depth": None,
    "max_features": 1.0,
    "max_leaf_nodes": None,
    "max_samples": None,
    "min_impurity_decrease": 0.0,
    "min_samples_leaf": 50,
    "min_samples_split": 2,
    "min_weight_fraction_leaf": 0.0,
    "monotonic_cst": None,
    "n_estimators": 500,
    "n_jobs": 1,
    "oob_score": False,
    "random_state": 71101,
    "verbose": 0,
    "warm_start": False,
}

FORBIDDEN_MODEL_COLUMNS = frozenset(
    {
        # Outcomes and outcome-adjacent fields.
        "a_won",
        "status",
        "score",
        "winner",
        "winner_id",
        "loser",
        "loser_id",
        # Identity, chronology, and split fields are keys or audit metadata.
        "match_id",
        "calendar_year",
        "source_season",
        "match_date",
        "eligible_through_date",
        "tourney_id",
        "tourney_name",
        "tourney_level",
        "competition_type",
        "round",
        "surface",
        "best_of",
        "player_a",
        "player_b",
        "primary_target",
        "identity_tier",
        "date_basis",
        "archive_date_basis",
        "source_field_agreement",
        # Contemporaneous and lagged market predictors are excluded here.
        "ps_probability_a",
        "ps_logit_a",
        "ps_missing",
        "lagged_market_elo_overall_logit",
        "lagged_market_elo_surface_logit",
        # SR02 dynamic-state staleness is data-availability provenance, not tennis:
        # emitted by the replay so a stale row can be reported, never fitted.
        "dynamic_state_stale_days",
        "dynamic_state_stale_days_a",
        "dynamic_state_stale_days_b",
        # Event-identity acquisition provenance, written on rows that qualified only
        # through the design's declared event-crosswalk carry-forward.  It reports how a
        # row was admitted, not anything about the tennis.
        "carried_forward",
        # Raw draw-time fields.  Entry status enters only through the derived
        # ENTRY_LEVEL_SIGNED / ENTRY_LEVEL_CONTEXT columns; the raw codes, seeds and the
        # draw size never do (tourney_level and round are refused above).
        *ENTRY_RAW_COLUMNS,
        "a_seed",
        "b_seed",
        "draw_size",
        # TIER01 provenance: rating initialisation, tier-inclusive state staleness,
        # uncapped history counts and the prespecified thin-side subgroup indicator.
        *TIER_PROVENANCE_ONLY_COLUMNS,
        *TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS,
    }
)


class PipelineError(ChainError):
    """Fail-closed input, chronology, fitting, or selection error."""


Joint04Error = PipelineError


# The JOINT04 window is the default so that `describe` and the exposed 2017-2024
# regression need no extra argument.  Nothing else in this file mentions a calendar year.
DEFAULT_YEAR_PLAN = {
    "panel_end_year": 2024,
    "feature_end_year": 2024,
    "target_years": list(range(2017, 2025)),
    "calibration_years_back": 3,
    "history_floor_year": 2011,
    "training_window_years": 5,
}


def _year_plan(mapping: Mapping[str, Any]) -> YearPlan:
    try:
        return YearPlan.from_mapping(mapping)
    except YearPlanError as error:
        raise PipelineError(str(error)) from error


PLAN = _year_plan(DEFAULT_YEAR_PLAN)
RAW_YEARS = PLAN.raw_years
OUTER_YEARS = PLAN.target_years


def configure_years(mapping: Mapping[str, Any]) -> YearPlan:
    """Install the configured year plan; the only place RAW/OUTER years are set."""
    global PLAN, RAW_YEARS, OUTER_YEARS
    PLAN = _year_plan(mapping)
    RAW_YEARS = PLAN.raw_years
    OUTER_YEARS = PLAN.target_years
    return PLAN


def tour_contract() -> bool:
    """True under the WTA02 settings contract (a declared tour), false under TIER01's."""
    return TOUR is not None


def split_block(block: str) -> tuple[str, str]:
    """`("full", "tier")` for `full_tier`, `("full", "tier_noqual")` for the ablation,
    `("full", "")` for `full`, `("full", "tier_entry")` for the entry/level variant,
    `("full", "entry")` for the tier-free entry/level variant.  The variant suffixes are
    tested longest first."""
    if block.endswith(TIER_ENTRY_SUFFIX):
        return block[: -len(TIER_ENTRY_SUFFIX)], "tier_entry"
    if block.endswith(TIER_NOQUAL_SUFFIX):
        return block[: -len(TIER_NOQUAL_SUFFIX)], "tier_noqual"
    if block.endswith(TIER_SUFFIX):
        return block[: -len(TIER_SUFFIX)], "tier"
    if block.endswith(ENTRY_SUFFIX):
        return block[: -len(ENTRY_SUFFIX)], "entry"
    return block, ""


def tier_enabled() -> bool:
    return any(split_block(block)[1] in TIER_VARIANTS for block in BLOCKS)


def noqual_enabled() -> bool:
    return any(split_block(block)[1] == "tier_noqual" for block in BLOCKS)


def entry_enabled() -> bool:
    """True when a `*_tier_entry` or `*_entry` bundle is configured: the entry/level block
    is then part of the assembled column set and of the settings document, and nowhere
    otherwise."""
    return any(split_block(block)[1] in ENTRY_VARIANTS for block in BLOCKS)


def _check_contract_supports_blocks(blocks: Sequence[str], tour: str | None) -> None:
    if tour is not None and any(split_block(block)[1] in TIER_VARIANTS for block in blocks):
        raise PipelineError(
            "a configuration that declares a tour is read under the WTA02 settings "
            "contract, which cannot record a tier bundle"
        )


def _check_cohort_supports_blocks(blocks: Sequence[str], cohort: str) -> None:
    if cohort == "aligned_primary_no_dynamic":
        offending = sorted(set(blocks) & DYNAMIC_BLOCKS)
        if offending:
            raise PipelineError(
                "cohort aligned_primary_no_dynamic cannot fit a block that needs the SR02 "
                f"dynamic predictor: {offending}"
            )


def configure_identity(
    experiment_id: str | None = None, tour: str | None = None
) -> tuple[str, str | None]:
    """Install the experiment id and the tour from the frozen configuration.

    Absent, the identity is TIER01's and no tour is declared.  Install the identity
    before the bundles: the tour decides which settings contract the bundles must fit.
    """
    global EXPERIMENT_ID, TOUR
    chosen_id = str(experiment_id or DEFAULT_EXPERIMENT_ID)
    if not chosen_id.strip() or any(character in chosen_id for character in "/\\ "):
        raise PipelineError(f"invalid experiment_id {chosen_id!r}")
    chosen_tour = None if tour is None else str(tour).upper()
    if chosen_tour is not None and chosen_tour not in TOURS:
        raise PipelineError(f"unknown tour {chosen_tour!r}; expected one of {list(TOURS)}")
    _check_contract_supports_blocks(BLOCKS, chosen_tour)
    EXPERIMENT_ID, TOUR = chosen_id, chosen_tour
    return EXPERIMENT_ID, TOUR


def configure_bundles(
    blocks: Sequence[str] | None = None, learners: Sequence[str] | None = None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Install the configured bundle and learner lists; the only place they are set.

    TIER01 adds the `*_tier` bundles: the JOINT04 bundle of the same stem plus the
    frozen tier block.  Ridge is refused for a tier bundle because the TIER01 design
    runs JOINT04's HGB menu and nothing else.  Install the bundles before the cohort:
    the cohort check reads both, and a no-dynamic cohort against the default four
    blocks is refused, which is the right answer for a run but the wrong order for a
    caller about to narrow the blocks.
    """
    global BLOCKS, LEARNERS
    chosen_blocks = tuple(DEFAULT_BLOCKS if blocks is None else blocks)
    chosen_learners = tuple(DEFAULT_LEARNERS if learners is None else learners)
    if not chosen_blocks or len(set(chosen_blocks)) != len(chosen_blocks):
        raise PipelineError("blocks must be a nonempty list of distinct names")
    if not chosen_learners or len(set(chosen_learners)) != len(chosen_learners):
        raise PipelineError("learners must be a nonempty list of distinct names")
    for block in chosen_blocks:
        stem, _ = split_block(block)
        if stem not in BASE_BLOCKS:
            raise PipelineError(f"unknown block: {block}")
    for learner in chosen_learners:
        if learner not in DEFAULT_LEARNERS:
            raise PipelineError(f"unknown learner: {learner}")
    if "ridge" in chosen_learners and any(split_block(b)[1] for b in chosen_blocks):
        raise PipelineError(
            "ridge cannot fit a tier or entry bundle: TIER01 and ARMS01 declare JOINT04's "
            "HGB menu only"
        )
    _check_contract_supports_blocks(chosen_blocks, TOUR)
    # Commit only after the checks pass, so a refused call leaves the module as it was.
    _check_cohort_supports_blocks(chosen_blocks, COHORT)
    global HGB_MENUS
    BLOCKS = chosen_blocks
    LEARNERS = chosen_learners
    # A bundle menu belongs to one bundle list; `configure_hgb_menus` reinstalls it.
    HGB_MENUS = {}
    return BLOCKS, LEARNERS


def configure_cohort(mode: str | None = None) -> str:
    """Install the membership predicate; absent, JOINT04's aligned-primary cohort."""
    global COHORT
    chosen = str(mode or "aligned_primary")
    if chosen not in COHORT_MODES:
        raise PipelineError(f"unknown cohort mode {chosen!r}; expected one of {list(COHORT_MODES)}")
    _check_cohort_supports_blocks(BLOCKS, chosen)
    COHORT = chosen
    return COHORT


# ------------------------------------------------------------------ TUNE01: per-bundle HGB menus
#
# A configuration may bind, per bundle, an enlarged HGB menu file by path and sha256
# (`hgb_menus: {"full_tier_entry": {"path": ..., "sha256": ...}}` beside the year plan).
# The menu's anchors are JOINT04's two candidates, fitted exactly as without a menu; its
# grid candidates are bagged and temporally early-stopped (`numerical.fit_bagged_early_stopped`).
# Without `hgb_menus` nothing here is installed and every setting, count and forecast of
# every existing configuration is unchanged.

HGB_MENU_KIND_ANCHOR = "anchor_incumbent"
HGB_MENU_KIND_GRID = "grid_bagged_early_stopped"
HGB_GRID_AXES = ("learning_rate", "max_leaf_nodes", "min_samples_leaf", "l2_regularization")
HGB_GRID_FIXED = {
    "early_stopping": False,
    "loss": "log_loss",
    "max_bins": 255,
    "max_depth": None,
    "max_features": 1.0,
    "random_state": 71101,
}
HGB_BAG_RNG = (
    "numpy.random.Generator(numpy.random.PCG64(numpy.random.SeedSequence("
    "[{seed}, R, role, member])))"
)
HGB_MENUS: dict[str, HgbMenu] = {}


@dataclass(frozen=True)
class HgbMenu:
    """One bundle's HGB candidate menu, loaded from a hash-bound menu file."""

    path: str
    sha256: str
    candidate_ids: tuple[str, ...]
    grid_params: dict[str, dict[str, Any]]
    tuning: dict[str, Any]

    def binding(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


def grid_candidate_id(params: Mapping[str, Any]) -> str:
    """`tune_lr{1000*lr:03d}_leaf{leaves:02d}_min{min leaf:03d}_reg{l2:02d}`."""
    return (
        f"tune_lr{round(1000 * params['learning_rate']):03d}"
        f"_leaf{params['max_leaf_nodes']:02d}"
        f"_min{params['min_samples_leaf']:03d}"
        f"_reg{round(params['l2_regularization']):02d}"
    )


def _anchor_params(leaves: int, depth: int) -> dict[str, Any]:
    params = dict(HGB_PARAMS)
    params.update({"max_leaf_nodes": leaves, "max_depth": depth})
    return params


def load_hgb_menu(path: Path, binding_path: str) -> HgbMenu:
    """Parse and check a menu file: anchors equal today's candidates, the grid is the
    full product of its declared axes, and the stopping and bagging rules are complete."""
    digest = sha256(path)
    document = read_config(path)

    def fail(message: str) -> PipelineError:
        return PipelineError(f"HGB menu {binding_path}: {message}")

    anchors = document.get("anchors")
    grid = document.get("grid")
    if not isinstance(anchors, list) or not isinstance(grid, list) or not grid:
        raise fail("needs anchor and grid candidate lists")
    expected_anchors = [
        {
            "candidate_id": candidate_id,
            "kind": HGB_MENU_KIND_ANCHOR,
            "bagging": None,
            "early_stopping": None,
            "estimator_params": _anchor_params(leaves, depth),
        }
        for candidate_id, leaves, depth in HGB_CANDIDATES
    ]
    if anchors != expected_anchors:
        raise fail("anchors must be JOINT04's two candidates with HGB_PARAMS, in menu order")
    axes = document.get("grid_axes")
    if not isinstance(axes, dict) or set(axes) != set(HGB_GRID_AXES):
        raise fail(f"grid_axes must name exactly {list(HGB_GRID_AXES)}")
    if document.get("fixed_grid_params") != HGB_GRID_FIXED:
        raise fail("fixed_grid_params differ from the declared grid contract")
    grid_params: dict[str, dict[str, Any]] = {}
    for entry in grid:
        if not isinstance(entry, dict) or entry.get("kind") != HGB_MENU_KIND_GRID:
            raise fail("every grid entry must be a grid_bagged_early_stopped candidate")
        params = entry.get("estimator_params")
        if not isinstance(params, dict) or set(params) != set(HGB_GRID_FIXED) | set(HGB_GRID_AXES):
            raise fail(f"grid parameters must be the fixed set plus {list(HGB_GRID_AXES)}")
        if any(params[key] != value for key, value in HGB_GRID_FIXED.items()):
            raise fail(f"{entry.get('candidate_id')} changes a fixed grid parameter")
        if any(params[axis] not in axes[axis] for axis in HGB_GRID_AXES):
            raise fail(f"{entry.get('candidate_id')} lies outside the grid axes")
        candidate_id = grid_candidate_id(params)
        if entry.get("candidate_id") != candidate_id or candidate_id in grid_params:
            raise fail(f"grid candidate id must be the unique {candidate_id}")
        grid_params[candidate_id] = dict(params)
    if len(grid_params) != math.prod(len(axes[axis]) for axis in HGB_GRID_AXES):
        raise fail("the grid must be the full product of its axes")
    stopping = document.get("early_stopping")
    bagging = document.get("bagging")
    if not isinstance(stopping, dict) or not isinstance(bagging, dict):
        raise fail("needs early_stopping and bagging objects")
    base_seed = HGB_GRID_FIXED["random_state"]
    if bagging.get("rng") != HGB_BAG_RNG.format(seed=base_seed):
        raise fail(f"bagging rng must be {HGB_BAG_RNG.format(seed=base_seed)}")
    tuning = {
        "kind": NUM.TUNING_KIND,
        "menu_sha256": digest,
        "max_iter_cap": stopping.get("max_iter_cap"),
        "patience": stopping.get("patience"),
        "tol": stopping.get("tol"),
        "members": bagging.get("members"),
        "row_subsample_fraction": bagging.get("row_subsample_fraction"),
        "base_seed": base_seed,
    }
    NUM._tuning_spec(
        {"family": "hist_gradient_boosting", "estimator_params": HGB_GRID_FIXED, "tuning": tuning}
    )
    counts = document.get("counts", {})
    ids = tuple(item[0] for item in HGB_CANDIDATES) + tuple(grid_params)
    if (
        counts.get("anchors"),
        counts.get("grid"),
        counts.get("total_candidates_seen_by_selector"),
    ) != (
        len(HGB_CANDIDATES),
        len(grid_params),
        len(ids),
    ):
        raise fail("declared counts differ from the enumerated menu")
    return HgbMenu(binding_path, digest, ids, grid_params, tuning)


def configure_hgb_menus(bindings: Mapping[str, Any] | None = None) -> dict[str, HgbMenu]:
    """Install the per-bundle HGB menus a configuration binds; absent, none.

    Install after the bundles: a menu may name only a configured bundle, and only when
    HGB is a configured learner.  Each file is resolved under the workspace and must
    hash to its binding.
    """
    global HGB_MENUS
    chosen: dict[str, HgbMenu] = {}
    for block, binding in (bindings or {}).items():
        if block not in BLOCKS or "hgb" not in LEARNERS:
            raise PipelineError(f"an HGB menu names a bundle that is not fitted by HGB: {block}")
        if not isinstance(binding, Mapping) or set(binding) != {"path", "sha256"}:
            raise PipelineError(f"hgb_menus.{block} must be exactly {{path, sha256}}")
        path = resolve_under_root(str(binding["path"]), label=f"hgb_menus.{block}.path")
        if sha256(path) != binding["sha256"]:
            raise PipelineError(f"hgb_menus.{block} hash mismatch")
        chosen[block] = load_hgb_menu(path, str(binding["path"]))
    HGB_MENUS = chosen
    return HGB_MENUS


def settings_document() -> dict[str, Any]:
    """The settings contract a config must equal, in the shape its revision froze."""
    document: dict[str, Any] = {
        "year_plan": PLAN.as_document(),
        "raw_years": list(RAW_YEARS),
        "outer_years": list(OUTER_YEARS),
        "blocks": list(BLOCKS),
        "learners": list(LEARNERS),
        "ridge_candidates": [item[0] for item in RIDGE_CANDIDATES],
        "hgb_candidates": [item[0] for item in HGB_CANDIDATES],
        "selection_years": PLAN.calibration_years_back,
        "tie_tolerance": TIE_TOLERANCE,
        "logit_clip": LOGIT_CLIP,
        "score_clip": SCORE_CLIP,
        "bootstrap_replicates": 2000,
        "bootstrap_seed": 20260911,
        "reliability_edges": [index / 10 for index in range(11)],
    }
    if HGB_MENUS:
        # TUNE01: present only when a menu is bound, so every earlier settings document
        # still equals the runner contract.
        document["hgb_menus"] = {block: menu.binding() for block, menu in HGB_MENUS.items()}
    if tour_contract():
        document["cohort"] = COHORT
        document["tour"] = TOUR
        if entry_enabled():
            # Only with an entry bundle, so every frozen WTA settings document still
            # equals the runner contract.
            document["entry_level_columns"] = list(ENTRY_LEVEL_COLUMNS)
    else:
        document["tier_columns"] = (
            list(TIER_COLUMNS) + (list(TIER_NOQUAL_COLUMNS) if noqual_enabled() else [])
            if tier_enabled()
            else []
        )
        if entry_enabled():
            # Present only when an entry bundle is configured, so every settings
            # document frozen before ARMS01 still equals the runner contract.
            document["entry_level_columns"] = list(ENTRY_LEVEL_COLUMNS)
    return document


def derived_membership_names() -> tuple[str, ...]:
    return (
        "raw_primary_rows",
        "selected_primary_rows",
        "aligned_primary_warmup_rows",
        "raw_fit_attempts",
        "raw_primary_by_year",
    )


canonical_json = NUM.canonical_json
sha256_json = NUM.sha256_json


def atomic_json(path: Path, value: Any) -> None:
    canonical_json(value)  # refuses NaN and infinity before anything is written
    common.atomic_json(path, value)


def code_receipts() -> dict[str, dict[str, str]]:
    """The provenance of the code that runs: this module and the numerical adapter."""
    return {"runner": code_receipt(__name__), "numerical": code_receipt(NUMERICAL_MODULE)}


DECLARED_CODE = (
    ("runner_path", "runner_sha256", RUNNER_MODULE),
    ("numerical_path", "numerical_sha256", NUMERICAL_MODULE),
)


def declared_code_binding(code: Any) -> dict[str, Any]:
    """Record a config's code bindings; verify the ones that name a package module.

    The archive verified its own file hash against the config.  A binding that names an
    archive file is recorded as declared and not compared with the package; one that
    names ``tennislab.models.pipeline`` or ``tennislab.models.numerical`` must match the
    executing file.
    """
    if not isinstance(code, dict):
        raise PipelineError("missing code bindings")
    receipts = code_receipts()
    for path_key, hash_key, module in DECLARED_CODE:
        declared_hash = code.get(hash_key)
        try:
            require_nonempty_digest(declared_hash, label=f"code.{hash_key}")
        except ChainError as error:
            raise PipelineError(str(error)) from error
        if code.get(path_key) == module:
            observed = receipts["runner" if module == RUNNER_MODULE else "numerical"]["sha256"]
            if declared_hash != observed:
                raise PipelineError(f"config {hash_key} differs from the executing {module}")
    return dict(code)


@dataclass(frozen=True)
class FeatureContract:
    base_linear: tuple[str, ...]
    base_signed: tuple[str, ...]
    binary_context: tuple[str, ...]
    hgb_base_context: tuple[str, ...]
    trait_interactions: tuple[str, ...]
    # The entry/level block the features stage declared, or () for a dictionary written
    # without it.  Read only when an entry bundle is configured.
    entry_level: tuple[str, ...] = ()

    @classmethod
    def from_dictionary(cls, dictionary: Mapping[str, Any]) -> FeatureContract:
        base_linear = tuple(dictionary.get("linear_sports_model_features", ()))
        base_signed = tuple(dictionary.get("signed_base_model_features", ()))
        binary_context = tuple(dictionary.get("binary_context_columns", ()))
        if len(base_linear) != 162 or len(base_signed) != 22 or len(binary_context) != 6:
            raise PipelineError("base feature dictionary does not match 162/22/6 contract")
        if any(
            len(columns) != len(set(columns))
            for columns in (base_linear, base_signed, binary_context)
        ):
            raise PipelineError("duplicate base feature column")
        forbidden = sorted(
            FORBIDDEN_MODEL_COLUMNS.intersection((*base_linear, *base_signed, *binary_context))
        )
        if forbidden:
            raise PipelineError(f"forbidden base model columns: {forbidden}")
        dictionary_forbidden = {
            *dictionary.get("identifier_and_split_columns", ()),
            *dictionary.get("label_file_columns", ()),
            *dictionary.get("contemporaneous_pinnacle_fields", ()),
            *dictionary.get("lagged_market_elo_features", ()),
        }
        leaked = sorted(
            dictionary_forbidden.intersection((*base_linear, *base_signed, *binary_context))
        )
        if leaked:
            raise PipelineError(f"dictionary-declared non-sports columns in model lists: {leaked}")
        if not set(base_signed).issubset(base_linear):
            raise PipelineError("signed HGB base fields must be contained in the ridge sports base")
        hgb_context = binary_context + ("ranking_global_age_days", "ranking_global_stale")
        interactions = tuple(
            f"{trait}_x_{context}" for trait in TRAIT_SIGNED for context in binary_context
        )
        entry_level = tuple(dictionary.get("entry_level_columns", ()))
        if entry_level:
            # The features stage and this runner must agree on the block to the column;
            # a raw code or level listed as a model column is refused with the rest.
            if entry_level != ENTRY_LEVEL_COLUMNS:
                raise PipelineError(
                    "dictionary entry_level_columns differ from the runner's ENTRY_LEVEL_COLUMNS"
                )
            declared_signed = tuple(dictionary.get("entry_level_signed_columns", ()))
            declared_context = tuple(dictionary.get("entry_level_context_columns", ()))
            if (declared_signed, declared_context) != (ENTRY_LEVEL_SIGNED, ENTRY_LEVEL_CONTEXT):
                raise PipelineError("dictionary entry/level signed/context split differs")
            leaked_raw = sorted(
                FORBIDDEN_MODEL_COLUMNS.intersection(
                    (*entry_level, *declared_signed, *declared_context)
                )
            )
            if leaked_raw:
                raise PipelineError(f"forbidden entry/level model columns: {leaked_raw}")
        return cls(base_linear, base_signed, binary_context, hgb_context, interactions, entry_level)

    @property
    def all_columns(self) -> tuple[str, ...]:
        ordered = (
            *self.base_linear,
            *self.base_signed,
            *self.hgb_base_context,
            *TRAIT_SIGNED,
            *self.trait_interactions,
            *TRAIT_HGB_CONTEXT,
            *DYNAMIC_SIGNED,
            # TIER01: appended last, so the assembled column order of every JOINT04
            # bundle is unchanged when no tier bundle is configured.
            *(TIER_COLUMNS if tier_enabled() else ()),
            *(TIER_NOQUAL_COLUMNS if noqual_enabled() else ()),
            # ARMS01: after the tier columns, so every earlier bundle's order is unchanged
            # when no entry bundle is configured.
            *(ENTRY_LEVEL_COLUMNS if entry_enabled() else ()),
        )
        return tuple(dict.fromkeys(ordered))

    def _explicit_model_columns(
        self, learner: str, block: str
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Resolve one named family/bundle without changing the historical run menu.

        Campaign code needs the reviewed RF tree contract and ATP ``full_tier`` beside
        non-tier ridge ``full``.  Installing that mixed menu in ``LEARNERS``/``BLOCKS``
        would change historical settings documents and fit counts, so the explicit path
        is deliberately separate from :meth:`model_columns`.
        """
        if learner not in (*DEFAULT_LEARNERS, "random_forest"):
            raise PipelineError(f"unknown learner: {learner}")
        stem, variant = split_block(block)
        if stem not in BASE_BLOCKS:
            raise PipelineError(f"unknown block: {block}")
        has_tier = variant in TIER_VARIANTS
        has_traits = stem in {"traits", "full"}
        has_dynamic = stem in {"dynamic", "full"}
        if learner == "ridge":
            if variant:
                raise PipelineError("ridge cannot fit a tier or entry bundle")
            numeric = list(self.base_linear)
            if has_traits:
                numeric.extend(TRAIT_SIGNED)
                numeric.extend(self.trait_interactions)
            if has_dynamic:
                numeric.extend(DYNAMIC_SIGNED)
            return tuple(numeric), ()
        signed = list(self.base_signed)
        context = list(self.hgb_base_context)
        if has_traits:
            signed.extend(TRAIT_SIGNED)
            context.extend(TRAIT_HGB_CONTEXT)
        if has_dynamic:
            signed.extend(DYNAMIC_SIGNED)
        if has_tier:
            # TIER01: appended, nothing removed.  The tier-inclusive dynamic logit joins
            # the block only where the base dynamic logit is already present, and the
            # base one stays -- the design keeps both.  The ablation bundle takes the
            # same block with the ablated dynamic logit in place of the full one, so it
            # differs from its `_tier` sibling in exactly one column.
            signed.extend(TIER_SIGNED)
            if has_dynamic:
                signed.extend(
                    TIER_NOQUAL_DYNAMIC_SIGNED if variant == "tier_noqual" else TIER_DYNAMIC_SIGNED
                )
        if variant in ENTRY_VARIANTS:
            # ARMS01: the `*_tier` bundle (ATP) or the JOINT04 bundle (WTA `*_entry`) plus
            # the entry/level block, appended after it: signed entry differences with the
            # signed columns, the symmetric any-qualifier flag and level indicators with
            # the context columns.
            if self.entry_level != ENTRY_LEVEL_COLUMNS:
                raise PipelineError(
                    f"bundle {block} needs the features stage's entry/level block "
                    "(entry_level_block: true); the dictionary declares none"
                )
            signed.extend(ENTRY_LEVEL_SIGNED)
            context.extend(ENTRY_LEVEL_CONTEXT)
        return tuple(signed), tuple(context)

    def model_columns(self, learner: str, block: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if learner not in LEARNERS or block not in BLOCKS:
            raise PipelineError(f"unknown learner/block: {learner}/{block}")
        return self._explicit_model_columns(learner, block)

    def campaign_model_columns(
        self, learner: str, block: str
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """The fixed Lane E family/bundle allowlist, independent of global run state."""
        return self._explicit_model_columns(learner, block)


@dataclass(frozen=True)
class AssembledBundle:
    features: Any
    metadata: dict[tuple[str, str], dict[str, str]]
    contract: FeatureContract
    source_hashes: dict[str, str]


@dataclass(frozen=True)
class FrozenRunConfig:
    document: dict[str, Any]
    path: Path
    sha256: str
    inputs: dict[str, Path]
    input_hashes: dict[str, str]
    declared_code: dict[str, Any]


def parse_finite(value: str, field: str, key: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise PipelineError(f"invalid {field} at {key}: {value!r}") from error
    if not math.isfinite(number):
        raise PipelineError(f"nonfinite {field} at {key}")
    return number


def parse_binary(value: str, field: str, key: str) -> int:
    if value not in {"0", "1"}:
        raise PipelineError(f"{field} must be 0/1 at {key}: {value!r}")
    return int(value)


def _clipped_logit(probability: float) -> str:
    clipped = min(max(probability, LOGIT_CLIP), 1.0 - LOGIT_CLIP)
    return repr(float(math.log(clipped / (1.0 - clipped))))


def transformed_additions(
    base: Mapping[str, str],
    sidecar: Mapping[str, str],
    contract: FeatureContract,
) -> dict[str, str]:
    """Create the fixed arithmetic traits and dynamic predictor for one match."""
    key = str(base["match_id"])
    if key != sidecar.get("match_id"):
        raise PipelineError("base/sidecar key mismatch")
    for field in (
        "calendar_year",
        "source_season",
        "match_date",
        "eligible_through_date",
        "tourney_id",
        "surface",
        "best_of",
        "player_a",
        "player_b",
        "primary_target",
        "identity_tier",
    ):
        if str(base[field]) != str(sidecar[field]):
            raise PipelineError(f"base/sidecar {field} mismatch at {key}")

    missing: dict[str, tuple[int, int]] = {}
    for field in ("age", "height", "hand"):
        missing[field] = tuple(  # type: ignore[assignment]
            parse_binary(sidecar[f"{field}_missing_{side}"], f"{field}_missing_{side}", key)
            for side in ("a", "b")
        )

    z_age: list[float] = []
    centered_height: list[float] = []
    left: list[int] = []
    for index, side in enumerate(("a", "b")):
        if missing["age"][index]:
            z_age.append(0.0)
        else:
            age = parse_finite(sidecar[f"age_years_at_target_{side}"], "age", key)
            z_age.append((age - 25.0) / 10.0)
        if missing["height"][index]:
            centered_height.append(0.0)
        else:
            height = parse_finite(sidecar[f"height_cm_{side}"], "height", key)
            centered_height.append((height - 180.0) / 10.0)
        hand = sidecar[f"hand_{side}"]
        if missing["hand"][index]:
            if hand in {"L", "R"}:
                raise PipelineError(f"missing hand flag conflicts with valid code at {key}")
            left.append(0)
        else:
            if hand not in {"L", "R"}:
                raise PipelineError(f"known hand must be L/R at {key}: {hand!r}")
            left.append(int(hand == "L"))

    height_diff = centered_height[0] - centered_height[1] if not any(missing["height"]) else 0.0
    signed_values = {
        "trait_z_age_diff": z_age[0] - z_age[1],
        "trait_z_age_sq_diff": z_age[0] ** 2 - z_age[1] ** 2,
        "trait_height_10cm_diff": height_diff,
        "trait_left_hand_diff": left[0] - left[1],
        "trait_age_missing_diff": missing["age"][0] - missing["age"][1],
        "trait_height_missing_diff": missing["height"][0] - missing["height"][1],
        "trait_hand_missing_diff": missing["hand"][0] - missing["hand"][1],
    }
    output = {field: repr(float(value)) for field, value in signed_values.items()}
    for trait in TRAIT_SIGNED:
        for context in contract.binary_context:
            context_value = parse_binary(str(base[context]), context, key)
            output[f"{trait}_x_{context}"] = repr(float(signed_values[trait] * context_value))
    output.update(
        {
            "trait_mean_z_age": repr(float(0.5 * sum(z_age))),
            "trait_mean_centered_height": repr(float(0.5 * sum(centered_height))),
            "trait_age_missing_sum": repr(float(sum(missing["age"]))),
            "trait_height_missing_sum": repr(float(sum(missing["height"]))),
            "trait_hand_missing_sum": repr(float(sum(missing["hand"]))),
        }
    )

    probability_text = sidecar.get("dynamic_match_probability_a", "")
    if probability_text == "":
        output["dynamic_match_logit"] = ""
    else:
        probability = parse_finite(probability_text, "dynamic_match_probability_a", key)
        if not 0.0 <= probability <= 1.0:
            raise PipelineError(f"dynamic probability outside [0,1] at {key}")
        output["dynamic_match_logit"] = _clipped_logit(probability)
    if tier_enabled():
        # The block is measured by the tier Elo and the tier SR02 replay and arrives on
        # the sidecar.  Nothing is derived here except the tier dynamic logit, which
        # goes through exactly the transformation above; a blank or nonfinite signed
        # cell fails closed rather than becoming a silent zero.
        for column in TIER_SIGNED:
            text = sidecar.get(column, "")
            if text == "":
                raise PipelineError(f"missing tier column {column} at {key}")
            output[column] = repr(parse_finite(text, column, key))
        tier_text = sidecar.get(TIER_DYNAMIC_PROBABILITY, "")
        if (tier_text == "") != (probability_text == ""):
            raise PipelineError(
                f"tier and base dynamic membership differ at {key}: the primary cohort "
                "must be the same set of matches with and without the tier block"
            )
        if tier_text == "":
            output["tier_dynamic_match_logit"] = ""
        else:
            tier_probability = parse_finite(tier_text, TIER_DYNAMIC_PROBABILITY, key)
            if not 0.0 <= tier_probability <= 1.0:
                raise PipelineError(f"tier dynamic probability outside [0,1] at {key}")
            output["tier_dynamic_match_logit"] = _clipped_logit(tier_probability)
        if noqual_enabled():
            # The same transformation on the ablated replay's probability, under the same
            # membership contract: the ablation must score the identical cohort.
            noqual_text = sidecar.get(TIER_NOQUAL_DYNAMIC_PROBABILITY, "")
            if (noqual_text == "") != (probability_text == ""):
                raise PipelineError(f"ablated tier and base dynamic membership differ at {key}")
            if noqual_text == "":
                output["tier_noqual_dynamic_match_logit"] = ""
            else:
                noqual_probability = parse_finite(noqual_text, TIER_NOQUAL_DYNAMIC_PROBABILITY, key)
                if not 0.0 <= noqual_probability <= 1.0:
                    raise PipelineError(f"ablated tier dynamic probability outside [0,1] at {key}")
                output["tier_noqual_dynamic_match_logit"] = _clipped_logit(noqual_probability)
    if entry_enabled():
        # The block arrives on the base feature file, already derived.  Nothing is
        # computed here; each cell is checked against its declared range and re-emitted,
        # so a blank, a raw code or an out-of-range value fails closed.
        for column in ENTRY_LEVEL_SIGNED:
            text = base.get(column, "")
            if text not in {"-1", "0", "1"}:
                raise PipelineError(f"{column} must be -1/0/1 at {key}: {text!r}")
            output[column] = repr(float(int(text)))
        for column in ENTRY_LEVEL_CONTEXT:
            output[column] = repr(float(parse_binary(base.get(column, ""), column, key)))
    return output


def _csv_rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        rows = list(reader)
    if not header:
        raise PipelineError(f"empty CSV header: {path}")
    return header, rows


def assemble_feature_bundle(
    base_path: Path,
    dictionary_path: Path,
    sidecar_path: Path,
    expected_hashes: Mapping[str, str] | None = None,
) -> AssembledBundle:
    paths = {"base": base_path, "dictionary": dictionary_path, "sidecar": sidecar_path}
    observed_hashes = {name: sha256(path) for name, path in paths.items()}
    if expected_hashes is not None:
        for name, observed in observed_hashes.items():
            if observed != expected_hashes.get(name):
                raise PipelineError(f"{name} hash mismatch: {observed}")
    dictionary = json.loads(dictionary_path.read_text(encoding="utf-8"))
    contract = FeatureContract.from_dictionary(dictionary)
    base_header, base_rows = _csv_rows(base_path)
    if base_header != tuple(dictionary.get("ordered_feature_file_columns", ())):
        raise PipelineError("base feature header differs from dictionary")
    sidecar_header, sidecar_rows = _csv_rows(sidecar_path)
    required_sidecar = {
        "match_id",
        "calendar_year",
        "source_season",
        "match_date",
        "eligible_through_date",
        "tourney_id",
        "surface",
        "best_of",
        "player_a",
        "player_b",
        "primary_target",
        "identity_tier",
        "sr02_selected_match_present",
        "dynamic_match_probability_a",
        *(
            f"{field}_{side}"
            for field in (
                "age_years_at_target",
                "age_missing",
                "height_cm",
                "height_missing",
                "hand",
                "hand_missing",
            )
            for side in ("a", "b")
        ),
    }
    if tier_enabled():
        required_sidecar |= set(TIER_SIDECAR_INPUTS)
    if noqual_enabled():
        required_sidecar.add(TIER_NOQUAL_DYNAMIC_PROBABILITY)
    if not required_sidecar.issubset(sidecar_header):
        raise PipelineError(
            f"sidecar missing columns: {sorted(required_sidecar - set(sidecar_header))}"
        )
    leaked = sorted(FORBIDDEN_MODEL_COLUMNS.intersection(contract.all_columns))
    if leaked:
        raise PipelineError(f"forbidden columns reached the model column set: {leaked}")
    sidecar_by_key = {row["match_id"]: row for row in sidecar_rows}
    if len(sidecar_by_key) != len(sidecar_rows):
        raise PipelineError("duplicate sidecar match_id")
    if set(sidecar_by_key) != {row["match_id"] for row in base_rows}:
        raise PipelineError("base/sidecar membership differs")

    model_rows: list[dict[str, str]] = []
    metadata: dict[tuple[str, str], dict[str, str]] = {}
    for base in base_rows:
        key = base["match_id"]
        sidecar = sidecar_by_key[key]
        match_date = parse_iso(base["match_date"])
        eligible_through = parse_iso(base["eligible_through_date"])
        if eligible_through > match_date - dt.timedelta(days=2):
            raise PipelineError(f"feature chronology exceeds D-2 at {key}")
        season = base["calendar_year"]
        model_key = (season, key)
        if model_key in metadata:
            raise PipelineError(f"duplicate model key: {model_key}")
        row = {"season": season, "match_id": key}
        for column in contract.all_columns:
            if column in base:
                row[column] = base[column]
        row.update(transformed_additions(base, sidecar, contract))
        missing_columns = [column for column in contract.all_columns if column not in row]
        if missing_columns:
            raise PipelineError(f"assembled row missing model columns at {key}: {missing_columns}")
        model_rows.append(row)
        metadata[model_key] = {
            "calendar_year": season,
            "source_season": base["source_season"],
            "match_date": base["match_date"],
            "eligible_through_date": base["eligible_through_date"],
            "tourney_id": base["tourney_id"],
            "primary_target": base["primary_target"],
            "identity_tier": base["identity_tier"],
            "sr02_selected_match_present": sidecar["sr02_selected_match_present"],
            "dynamic_match_probability_a": sidecar["dynamic_match_probability_a"],
            "ps_probability_a": base["ps_probability_a"],
            "ps_missing": base["ps_missing"],
            "source_field_agreement": base["source_field_agreement"],
        }
    header = ("season", "match_id", *contract.all_columns)
    table = NUM.FeatureTable.from_rows(
        model_rows,
        header,
        source_path=f"{base_path}+{sidecar_path}",
        source_sha256=sha256_json(observed_hashes),
    )
    return AssembledBundle(table, metadata, contract, observed_hashes)


def parse_iso(value: str) -> dt.date:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as error:
        raise PipelineError(f"invalid ISO date: {value!r}") from error
    if parsed.isoformat() != value:
        raise PipelineError(f"noncanonical ISO date: {value!r}")
    return parsed


def training_window(year: int) -> tuple[dt.date, dt.date]:
    if year not in RAW_YEARS:
        raise PipelineError(f"raw year outside configured raw years {RAW_YEARS}: {year}")
    start_year = max(PLAN.history_floor_year, year - PLAN.training_window_years)
    return dt.date(start_year, 1, 1), dt.date(year - 1, 12, 30)


def validation_years(outer_year: int) -> tuple[int, ...]:
    if outer_year not in OUTER_YEARS:
        raise PipelineError(
            f"outer year outside configured target years {OUTER_YEARS}: {outer_year}"
        )
    return tuple(outer_year - offset for offset in range(PLAN.calibration_years_back, 0, -1))


def _has_dynamic_block(metadata: Mapping[str, str]) -> bool:
    return (
        metadata["sr02_selected_match_present"] == "1"
        and metadata["dynamic_match_probability_a"] != ""
    )


def is_aligned_primary(metadata: Mapping[str, str]) -> bool:
    year = metadata["calendar_year"]
    match_date = parse_iso(metadata["match_date"])
    aligned = (
        metadata["primary_target"] == "1"
        and metadata["identity_tier"] == "primary"
        and metadata["source_season"] == year
        and str(match_date.year) == year
    )
    if COHORT == "aligned_primary_no_dynamic":
        return aligned
    return aligned and _has_dynamic_block(metadata)


def is_aligned_provisional(metadata: Mapping[str, str]) -> bool:
    year = metadata["calendar_year"]
    match_date = parse_iso(metadata["match_date"])
    aligned = (
        metadata["primary_target"] == "0"
        and metadata["identity_tier"] == "provisional"
        and metadata["source_season"] == year
        and str(match_date.year) == year
    )
    if COHORT == "aligned_primary_no_dynamic":
        return aligned
    return aligned and _has_dynamic_block(metadata)


def target_keys(
    metadata: Mapping[tuple[str, str], Mapping[str, str]], year: int
) -> tuple[tuple[str, str], ...]:
    if year not in RAW_YEARS:
        raise PipelineError(f"target year outside raw range: {year}")
    keys = tuple(
        sorted(
            key for key, row in metadata.items() if key[0] == str(year) and is_aligned_primary(row)
        )
    )
    if not keys:
        raise PipelineError(f"empty target membership in {year}")
    return keys


def provisional_target_keys(
    metadata: Mapping[tuple[str, str], Mapping[str, str]], year: int
) -> tuple[tuple[str, str], ...]:
    if year not in RAW_YEARS:
        raise PipelineError(f"target year outside raw range: {year}")
    return tuple(
        sorted(
            key
            for key, row in metadata.items()
            if key[0] == str(year) and is_aligned_provisional(row)
        )
    )


def all_prediction_keys(
    metadata: Mapping[tuple[str, str], Mapping[str, str]], year: int
) -> tuple[tuple[str, str], ...]:
    primary = target_keys(metadata, year)
    provisional = provisional_target_keys(metadata, year)
    return tuple(sorted((*primary, *provisional)))


def training_keys(
    metadata: Mapping[tuple[str, str], Mapping[str, str]], year: int
) -> tuple[tuple[str, str], ...]:
    start, end = training_window(year)
    keys = tuple(
        sorted(
            key
            for key, row in metadata.items()
            if is_aligned_primary(row) and start <= parse_iso(row["match_date"]) <= end
        )
    )
    if not keys:
        raise PipelineError(f"empty training membership in {year}")
    return keys


def selection_keys(
    metadata: Mapping[tuple[str, str], Mapping[str, str]],
    outer_year: int,
) -> dict[int, tuple[tuple[str, str], ...]]:
    cutoff = dt.date(outer_year - 1, 12, 30)
    result: dict[int, tuple[tuple[str, str], ...]] = {}
    for year in validation_years(outer_year):
        keys = tuple(
            sorted(
                key
                for key, row in metadata.items()
                if key[0] == str(year)
                and is_aligned_primary(row)
                and parse_iso(row["match_date"]) <= cutoff
            )
        )
        if not keys:
            raise PipelineError(f"empty selection year {year} for outer {outer_year}")
        result[year] = keys
    return result


def numerical_config(
    contract: FeatureContract, learner: str, block: str, q_id: str
) -> dict[str, Any]:
    numeric, context = contract.model_columns(learner, block)
    config_id = f"{learner}__{block}__{q_id}"
    if learner == "ridge":
        candidates = dict(RIDGE_CANDIDATES)
        if q_id not in candidates:
            raise PipelineError(f"unknown ridge candidate: {q_id}")
        params = dict(RIDGE_PARAMS)
        params["C"] = candidates[q_id]
        return {
            "config_id": config_id,
            "family": "joint_logistic",
            "numeric_columns": list(numeric),
            "estimator_params": params,
        }
    if learner == "hgb":
        menu = HGB_MENUS.get(block)
        if menu is not None and q_id in menu.grid_params:
            # TUNE01 grid candidate: the menu's parameters, the capped iteration count of
            # the stopping fits (the refit takes k*), and the bagging/stopping contract.
            return {
                "config_id": config_id,
                "family": "hist_gradient_boosting",
                "signed_numeric_columns": list(numeric),
                "context_columns": list(context),
                "estimator_params": {
                    **menu.grid_params[q_id],
                    "max_iter": menu.tuning["max_iter_cap"],
                },
                "tuning": dict(menu.tuning),
            }
        # Anchors of a bundle menu are today's candidates, built exactly as without one.
        candidates = {candidate[0]: candidate[1:] for candidate in HGB_CANDIDATES}
        if q_id not in candidates:
            raise PipelineError(f"unknown HGB candidate: {q_id}")
        leaves, depth = candidates[q_id]
        params = dict(HGB_PARAMS)
        params.update({"max_leaf_nodes": leaves, "max_depth": depth})
        return {
            "config_id": config_id,
            "family": "hist_gradient_boosting",
            "signed_numeric_columns": list(numeric),
            "context_columns": list(context),
            "estimator_params": params,
        }
    raise PipelineError(f"unknown learner: {learner}")


def random_forest_numerical_config(
    contract: FeatureContract, block: str, candidate_id: str
) -> dict[str, Any]:
    """Resolve the reviewed Lane E RF contract without extending historical menus.

    The caller must choose the tour-specific incumbent bundle (ATP ``full_tier`` or
    WTA ``full``).  Columns come only from the existing signed/context allowlist; the
    adapter never scans the numeric feature table for additional columns.
    """
    candidates = dict(RF_CANDIDATES)
    if candidate_id not in candidates:
        raise PipelineError(f"unknown random-forest candidate: {candidate_id}")
    signed, context = contract.campaign_model_columns("random_forest", block)
    forbidden = sorted(FORBIDDEN_MODEL_COLUMNS.intersection((*signed, *context)))
    if forbidden:
        raise PipelineError(f"forbidden random-forest model columns: {forbidden}")
    params = dict(RF_PARAMS)
    params["min_samples_leaf"] = candidates[candidate_id]
    return {
        "config_id": f"random_forest__{block}__{candidate_id}",
        "family": "random_forest",
        "signed_numeric_columns": list(signed),
        "context_columns": list(context),
        "estimator_params": params,
    }


def candidate_ids(learner: str, block: str | None = None) -> tuple[str, ...]:
    """The candidate menu of one learner, in menu order; a bundle with a bound HGB menu
    (TUNE01) has that menu's candidates, every other bundle the default menu."""
    if learner == "ridge":
        return tuple(item[0] for item in RIDGE_CANDIDATES)
    if learner == "hgb":
        menu = HGB_MENUS.get(block) if block is not None else None
        if menu is not None:
            return menu.candidate_ids
        return tuple(item[0] for item in HGB_CANDIDATES)
    raise PipelineError(f"unknown learner: {learner}")


def expected_fit_attempts() -> int:
    """Raw fits per run: the candidate menu of every learner/bundle times the raw years."""
    return sum(
        len(candidate_ids(learner, block)) * len(RAW_YEARS)
        for learner in LEARNERS
        for block in BLOCKS
    )


def weighted_calibration_arrays(
    yearly_probabilities: Mapping[int, Sequence[float]],
    yearly_labels: Mapping[int, Sequence[int]],
    required_years: Sequence[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    logits: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    weights: list[np.ndarray] = []
    clipped_count = 0
    for year in required_years:
        p = np.asarray(yearly_probabilities[year], dtype=np.float64)
        y = np.asarray(yearly_labels[year], dtype=np.float64)
        if p.ndim != 1 or y.ndim != 1 or len(p) != len(y) or len(p) == 0:
            raise PipelineError(f"invalid calibration arrays in {year}")
        if not np.all(np.isfinite(p)) or np.any(p < 0.0) or np.any(p > 1.0):
            raise PipelineError(f"invalid calibration probabilities in {year}")
        if not np.all(np.isin(y, (0.0, 1.0))):
            raise PipelineError(f"invalid calibration labels in {year}")
        clipped = np.clip(p, LOGIT_CLIP, 1.0 - LOGIT_CLIP)
        clipped_count += int(np.count_nonzero(clipped != p))
        logits.append(np.log(clipped / (1.0 - clipped)))
        labels.append(y)
        weights.append(np.full(len(p), 1.0 / (len(required_years) * len(p))))
    return np.concatenate(logits), np.concatenate(labels), np.concatenate(weights), clipped_count


def sigmoid(values: np.ndarray) -> np.ndarray:
    output = np.empty_like(values, dtype=np.float64)
    positive = values >= 0
    output[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp_values = np.exp(values[~positive])
    output[~positive] = exp_values / (1.0 + exp_values)
    return output


def fit_nonnegative_slope(
    yearly_probabilities: Mapping[int, Sequence[float]],
    yearly_labels: Mapping[int, Sequence[int]],
    required_years: Sequence[int],
) -> dict[str, Any]:
    """Fit one no-intercept slope with equal total weight per calendar year."""
    try:
        x, y, weights, clipped_count = weighted_calibration_arrays(
            yearly_probabilities, yearly_labels, required_years
        )

        def derivative(slope: float) -> float:
            return float(np.sum(weights * x * (sigmoid(slope * x) - y)))

        at_zero = derivative(0.0)
        if at_zero >= 0.0:
            slope = 0.0
            bracket = [0.0, 0.0]
        else:
            upper = 1.0
            while derivative(upper) <= 0.0 and upper < 1_048_576.0:
                upper *= 2.0
            if derivative(upper) <= 0.0:
                raise PipelineError("calibration optimum has no finite nonnegative bracket")
            slope = float(optimize.brentq(derivative, 0.0, upper, xtol=1e-12, rtol=1e-14))
            bracket = [0.0, upper]
        losses = np.logaddexp(0.0, slope * x) - y * slope * x
        annual: dict[str, dict[str, float | int]] = {}
        offset = 0
        for year in required_years:
            n = len(yearly_labels[year])
            annual[str(year)] = {
                "n": n,
                "mean_log_loss": float(np.mean(losses[offset : offset + n])),
            }
            offset += n
        return {
            "status": "complete",
            "slope": slope,
            "equal_year_mean_log_loss": float(np.sum(weights * losses)),
            "annual": annual,
            "rows": len(y),
            "probability_clip_count": clipped_count,
            "derivative_at_zero": at_zero,
            "root_bracket": bracket,
            "fit_semantics": "in_sample_nuisance_calibration_on_past_selection_sample",
        }
    except Exception as error:
        return {
            "status": "failed",
            "slope": None,
            "equal_year_mean_log_loss": None,
            "error": {"type": type(error).__name__, "message": str(error)},
            "fit_semantics": "in_sample_nuisance_calibration_on_past_selection_sample",
        }


def select_calibrated_candidate(
    trials: Mapping[str, Mapping[str, Any]],
    ordered_candidates: Sequence[str],
    tie_tolerance: float = TIE_TOLERANCE,
) -> dict[str, Any]:
    if len(set(ordered_candidates)) != len(ordered_candidates):
        raise PipelineError("candidate order contains duplicates")
    if set(trials) != set(ordered_candidates):
        raise PipelineError("calibration trials differ from candidate menu")
    eligible = []
    unavailable = []
    for order, candidate in enumerate(ordered_candidates):
        trial = trials[candidate]
        if trial.get("status") != "complete":
            unavailable.append({"candidate_id": candidate, "error": trial.get("error")})
            continue
        score = float(trial["equal_year_mean_log_loss"])
        if not math.isfinite(score):
            raise PipelineError(f"nonfinite candidate score: {candidate}")
        eligible.append(
            {
                "candidate_id": candidate,
                "score": score,
                "order": order,
                "slope": float(trial["slope"]),
            }
        )
    if unavailable:
        return {
            "status": "unavailable_incomplete_candidate_menu",
            "selected_candidate_id": None,
            "selected_slope": None,
            "ranked": sorted(eligible, key=lambda item: (item["score"], item["order"])),
            "unavailable": unavailable,
            "tie_tolerance": tie_tolerance,
            "score_semantics": "past_in_sample_nuisance_calibration_plus_complexity_selection",
        }
    if not eligible:
        return {
            "status": "unavailable",
            "selected_candidate_id": None,
            "ranked": [],
            "unavailable": unavailable,
        }
    minimum = min(item["score"] for item in eligible)
    tied = [item for item in eligible if item["score"] <= minimum + tie_tolerance]
    selected = min(tied, key=lambda item: item["order"])
    ranked = sorted(eligible, key=lambda item: (item["score"], item["order"]))
    runner_up_gap = None if len(ranked) < 2 else ranked[1]["score"] - ranked[0]["score"]
    return {
        "status": "complete",
        "selected_candidate_id": selected["candidate_id"],
        "selected_slope": selected["slope"],
        "minimum_equal_year_mean_log_loss": selected["score"],
        "runner_up_gap": runner_up_gap,
        "tie_tolerance": tie_tolerance,
        "ranked": ranked,
        "unavailable": unavailable,
        "score_semantics": "past_in_sample_nuisance_calibration_plus_complexity_selection",
    }


# ------------------------------------------------------------------ RB14: scores stay in memory
#
# The selection stage takes its decisions on past-year log losses. Those losses are
# scores of outer years (a later fold's selection window contains an earlier fold's
# target year), so the stage no longer writes them: it writes the decision, the
# membership, and a commitment hash of the criterion table; the reporter recomputes the
# table after the barrier, checks the hash and publishes the numbers.

SELECTION_KEYS_FILE = "selection_keys.csv"


def criterion_document(
    trials: Mapping[str, Mapping[str, Any]], selected: Mapping[str, Any]
) -> dict[str, Any]:
    """The scores a selection was taken on, in the form the reporter recomputes and hashes."""
    return {
        "candidate_trials": {
            candidate: {
                "status": trial.get("status"),
                "slope": trial.get("slope"),
                "equal_year_mean_log_loss": trial.get("equal_year_mean_log_loss"),
                "annual": {
                    year: value.get("mean_log_loss")
                    for year, value in (trial.get("annual") or {}).items()
                },
            }
            for candidate, trial in trials.items()
        },
        "selection": {
            "selected_candidate_id": selected.get("selected_candidate_id"),
            "minimum_equal_year_mean_log_loss": selected.get("minimum_equal_year_mean_log_loss"),
            "runner_up_gap": selected.get("runner_up_gap"),
            "ranked": [
                {"candidate_id": item["candidate_id"], "score": item["score"]}
                for item in selected.get("ranked", [])
            ],
        },
    }


def fit_criterion_document(fit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": fit.get("status"),
        "slope": fit.get("slope"),
        "equal_year_mean_log_loss": fit.get("equal_year_mean_log_loss"),
        "annual": {
            year: value.get("mean_log_loss") for year, value in (fit.get("annual") or {}).items()
        },
    }


def public_fit(fit: Mapping[str, Any]) -> dict[str, Any]:
    """A slope fit without its scores: the learned constant and its receipts only."""
    public = {key: value for key, value in fit.items() if key != "equal_year_mean_log_loss"}
    if isinstance(fit.get("annual"), Mapping):
        public["annual"] = {
            year: {key: value for key, value in record.items() if key != "mean_log_loss"}
            for year, record in fit["annual"].items()
        }
    public["scores_deferred_to_report"] = True
    return public


def public_selection(selected: Mapping[str, Any]) -> dict[str, Any]:
    """A selection decision without its scores: the ranked candidate order remains."""
    public = {
        key: value
        for key, value in selected.items()
        if key not in ("minimum_equal_year_mean_log_loss", "runner_up_gap")
    }
    public["ranked"] = [
        {key: value for key, value in item.items() if key != "score"}
        for item in selected.get("ranked", [])
    ]
    public["scores_deferred_to_report"] = True
    return public


def write_selection_keys(path: Path, keys: Sequence[tuple[str, str]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("season", "match_id"))
        writer.writerows(keys)
    return sha256(path)


def read_selection_keys(path: Path) -> tuple[tuple[str, str], ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        if next(reader, None) != ["season", "match_id"]:
            raise PipelineError(f"selection key header drift: {path}")
        return tuple((row[0], row[1]) for row in reader)


def apply_slope(probabilities: Sequence[float], slope: float) -> np.ndarray:
    if not math.isfinite(slope) or slope < 0.0:
        raise PipelineError("calibration slope must be finite and nonnegative")
    p = np.asarray(probabilities, dtype=np.float64)
    if not np.all(np.isfinite(p)) or np.any(p < 0.0) or np.any(p > 1.0):
        raise PipelineError("invalid raw probabilities")
    clipped = np.clip(p, LOGIT_CLIP, 1.0 - LOGIT_CLIP)
    logits = np.log(clipped / (1.0 - clipped))
    return sigmoid(slope * logits)


def _project_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise PipelineError(f"{field} must be a nonempty workspace-relative path")
    return resolve_under_root(value, label=field)


def dependency_versions() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": NUM.scipy.__version__,
        "scikit_learn": NUM.sklearn.__version__,
        "joblib": NUM.joblib.__version__,
    }


def load_frozen_run_config(path: Path) -> FrozenRunConfig:
    """Load the owner's frozen bindings and reject protocol drift before work."""
    path = resolve_under_root(path, label="config")
    document = read_config(path)
    settings_binding = document.get("settings")
    if not isinstance(settings_binding, dict):
        raise PipelineError("config settings must be an object")
    # Installed from the config rather than compared against a literal: the settings
    # document equality check below is what refuses a config the runner disagrees with,
    # and the identity decides which settings contract the config is read under.
    configure_identity(document.get("experiment_id"), settings_binding.get("tour"))
    configure_years(settings_binding.get("year_plan", {}))
    configure_bundles(settings_binding.get("blocks"), settings_binding.get("learners"))
    configure_cohort(settings_binding.get("cohort"))
    configure_hgb_menus(settings_binding.get("hgb_menus"))
    if document.get("execution_scope") not in {"synthetic_fixture", "frozen_real_inputs"}:
        raise PipelineError(
            "config execution_scope must be synthetic_fixture or frozen_real_inputs"
        )
    design = document.get("design")
    if not isinstance(design, dict):
        raise PipelineError("missing design binding")
    design_path = _project_path(design.get("path"), "design.path")
    if sha256(design_path) != design.get("sha256"):
        raise PipelineError("design hash mismatch")
    inputs_document = document.get("inputs")
    if not isinstance(inputs_document, dict):
        raise PipelineError("config inputs must be an object")
    names = ("features", "dictionary", "sidecar", "labels")
    inputs: dict[str, Path] = {}
    input_hashes: dict[str, str] = {}
    for name in names:
        binding = inputs_document.get(name)
        if not isinstance(binding, dict):
            raise PipelineError(f"missing input binding: {name}")
        bound_hash = binding.get("sha256")
        if not isinstance(bound_hash, str) or len(bound_hash) != 64:
            raise PipelineError(f"invalid input hash binding: {name}")
        bound_path = _project_path(binding.get("path"), f"inputs.{name}.path")
        if name == "labels":
            # RB3: the label file is not opened here, not even to hash it. Every read
            # goes through LabelHistory, which checks this bound hash before it reads.
            inputs[name] = bound_path
            input_hashes[name] = bound_hash
            continue
        observed = sha256(bound_path)
        if observed != bound_hash:
            raise PipelineError(f"{name} hash mismatch: {observed}")
        inputs[name] = bound_path
        input_hashes[name] = observed

    declared_code = declared_code_binding(document.get("code"))
    dependencies = document.get("dependencies")
    if dependencies != dependency_versions():
        raise PipelineError("config dependency versions differ from executing environment")

    if settings_binding != settings_document():
        raise PipelineError(
            "config settings differ from the runner contract under the configured year plan"
        )
    if tuple(document.get("label_file_columns", ())) != LABEL_COLUMNS:
        raise PipelineError("config label_file_columns differ from fixed header")
    expected = document.get("expected_membership")
    if not isinstance(expected, dict):
        raise PipelineError("missing expected_membership")
    # The completeness gate is derived from the configured target years: the declared
    # per-year counts must cover exactly the configured raw years, sum to the declared
    # totals, and the fit-attempt count must equal the candidate menu times blocks times
    # raw years.  validate_membership then checks every declared count against the
    # assembled feature table itself.
    if document.get("execution_scope") == "frozen_real_inputs":
        for name in derived_membership_names():
            if name not in expected:
                raise PipelineError(f"real config expected membership must declare {name}")
        by_year = expected["raw_primary_by_year"]
        if not isinstance(by_year, dict):
            raise PipelineError("expected_membership raw_primary_by_year must be an object")
        if set(by_year) != {str(year) for year in RAW_YEARS}:
            raise PipelineError(
                "expected_membership raw_primary_by_year must cover exactly the configured raw years"
            )
        if any(not isinstance(value, int) or value <= 0 for value in by_year.values()):
            raise PipelineError("expected_membership per-year counts must be positive integers")
        if sum(by_year.values()) != expected["raw_primary_rows"]:
            raise PipelineError(
                "expected_membership raw_primary_rows differs from its per-year counts"
            )
        if sum(by_year[str(year)] for year in OUTER_YEARS) != expected["selected_primary_rows"]:
            raise PipelineError(
                "expected_membership selected_primary_rows differs from the target-year per-year counts"
            )
        derived_attempts = expected_fit_attempts()
        if expected["raw_fit_attempts"] != derived_attempts:
            raise PipelineError(
                f"expected_membership raw_fit_attempts must equal the derived menu size {derived_attempts}"
            )
        warmup = expected["aligned_primary_warmup_rows"]
        if not isinstance(warmup, int) or warmup < 0:
            raise PipelineError(
                "expected_membership aligned_primary_warmup_rows must be a nonnegative integer"
            )
    return FrozenRunConfig(document, path, sha256(path), inputs, input_hashes, declared_code)


def ordered_model_columns(contract: FeatureContract) -> dict[str, dict[str, dict[str, list[str]]]]:
    output: dict[str, dict[str, dict[str, list[str]]]] = {}
    for learner in LEARNERS:
        output[learner] = {}
        for block in BLOCKS:
            numeric, context = contract.model_columns(learner, block)
            output[learner][block] = {
                "numeric_or_signed": list(numeric),
                "symmetric_context": list(context),
            }
    return output


def dynamic_dispersion_by_raw_year(
    metadata: Mapping[tuple[str, str], Mapping[str, str]],
) -> dict[str, Any]:
    """Per raw year: how much the dynamic feature varies over the aligned-primary cohort.

    A raw year whose training rows carry a constant dynamic probability produces a
    `full` fit that cannot use the block, and the report has to be able to say which
    years those were.  Counted on the cohort itself -- the rows the fits and the
    selection actually see -- and never fitted: this is availability provenance.
    """
    output: dict[str, Any] = {}
    for year in RAW_YEARS:
        rows = [
            row for key, row in metadata.items() if key[0] == str(year) and is_aligned_primary(row)
        ]
        values = [
            float(row["dynamic_match_probability_a"])
            for row in rows
            if row["dynamic_match_probability_a"] != ""
        ]
        distinct = len({format(value, ".17g") for value in values})
        mean = sum(values) / len(values) if values else None
        variance = (
            sum((value - mean) ** 2 for value in values) / len(values) if len(values) > 1 else 0.0
        )
        output[str(year)] = {
            "cohort_rows": len(rows),
            "rows_with_a_dynamic_probability": len(values),
            "distinct_dynamic_probabilities": distinct,
            "dynamic_probability_sd": math.sqrt(variance) if values else None,
            "informative": distinct > 1,
        }
    return output


def constant_dynamic_calendar_years(
    metadata: Mapping[tuple[str, str], Mapping[str, str]],
) -> set[str]:
    """Calendar years whose cohort dynamic probability takes exactly one value."""
    values: dict[str, set[str]] = {}
    for row in metadata.values():
        if not is_aligned_primary(row) or row["dynamic_match_probability_a"] == "":
            continue
        values.setdefault(row["calendar_year"], set()).add(
            format(float(row["dynamic_match_probability_a"]), ".17g")
        )
    return {year for year, seen in values.items() if len(seen) == 1}


def training_window_dispersion(
    metadata: Mapping[tuple[str, str], Mapping[str, str]],
) -> dict[str, Any]:
    """The same measure over each raw year's own training window.

    `constant_feature_training_rows` is the count this exists for: a training window
    that reaches back before the first season with serve counts is fitted partly or
    wholly on rows whose dynamic feature cannot distinguish them.
    """
    constant_years = constant_dynamic_calendar_years(metadata)
    output: dict[str, Any] = {}
    for year in RAW_YEARS:
        start, end = training_window(year)
        rows = [
            row
            for row in metadata.values()
            if is_aligned_primary(row)
            and start <= parse_iso(row["match_date"]) <= end
            and row["dynamic_match_probability_a"] != ""
        ]
        values = [float(row["dynamic_match_probability_a"]) for row in rows]
        distinct = len({format(value, ".17g") for value in values})
        constant_rows = sum(1 for row in rows if row["calendar_year"] in constant_years)
        output[str(year)] = {
            "training_window": [start.isoformat(), end.isoformat()],
            "training_rows_with_a_dynamic_probability": len(values),
            "distinct_dynamic_probabilities": distinct,
            "constant_feature_training_rows": constant_rows,
            "constant_feature_training_share": (
                round(constant_rows / len(values), 6) if values else None
            ),
            "informative": distinct > 1,
            "wholly_constant_training_window": bool(values) and constant_rows == len(values),
        }
    return output


def validate_membership(
    bundle: AssembledBundle,
    config: FrozenRunConfig,
) -> dict[str, Any]:
    if config.document.get("ordered_model_columns") != ordered_model_columns(bundle.contract):
        raise PipelineError("config ordered model columns differ from assembled feature contract")
    primary_by_year = {str(year): len(target_keys(bundle.metadata, year)) for year in RAW_YEARS}
    provisional_by_year = {
        str(year): len(provisional_target_keys(bundle.metadata, year)) for year in RAW_YEARS
    }
    warmup = sum(
        key[0] == str(PLAN.history_floor_year) and is_aligned_primary(row)
        for key, row in bundle.metadata.items()
    )
    result = {
        "raw_primary_by_year": primary_by_year,
        "raw_primary_rows": sum(primary_by_year.values()),
        "selected_primary_rows": sum(primary_by_year[str(year)] for year in OUTER_YEARS),
        "provisional_by_year": provisional_by_year,
        "aligned_primary_warmup_rows": warmup,
        "raw_fit_attempts": expected_fit_attempts(),
    }
    expected = config.document["expected_membership"]
    for field, expected_value in expected.items():
        if field in result and result[field] != expected_value:
            raise PipelineError(
                f"membership mismatch for {field}: {result[field]} != {expected_value}"
            )
    return result


def label_subset(
    path: Path,
    expected_sha256: str,
    keys: Sequence[tuple[str, str]],
    metadata: Mapping[tuple[str, str], Mapping[str, str]],
    *,
    purpose: str,
    year_ceiling: int,
    fold_outer_year: int | None = None,
) -> Any:
    """Read outcomes for only a previously fixed key set, as declared history."""
    history = LabelHistory(
        path,
        expected_sha256,
        purpose=purpose,
        year_ceiling=year_ceiling,
        fold_outer_year=fold_outer_year,
    )
    return history.selected(keys, metadata)  # outcome-history read


def prediction_map(path: Path) -> dict[tuple[str, str], float]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != ("season", "match_id", "p_a_wins"):
            raise PipelineError(f"prediction header drift: {path}")
        output: dict[tuple[str, str], float] = {}
        for row in reader:
            key = (row["season"], row["match_id"])
            if key in output:
                raise PipelineError(f"duplicate prediction key at {path}: {key}")
            probability = parse_finite(row["p_a_wins"], "p_a_wins", str(key))
            if not 0.0 <= probability <= 1.0:
                raise PipelineError(f"prediction outside [0,1] at {key}")
            output[key] = probability
    return output


def _write_calibrated_predictions(
    path: Path,
    keys: Sequence[tuple[str, str]],
    probabilities: Sequence[float],
) -> str:
    if len(keys) != len(probabilities):
        raise PipelineError("calibrated prediction key/value length mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("season", "match_id", "p_a_wins"))
        for key, probability in zip(keys, probabilities, strict=True):
            writer.writerow((*key, repr(float(probability))))
    return sha256(path)


def raw_prediction_path(
    output_dir: Path, year: int, learner: str, block: str, candidate_id: str
) -> Path:
    return output_dir / "raw" / str(year) / learner / block / f"{candidate_id}.csv"


def thread_environment() -> dict[str, str | None]:
    return {
        "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
        "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
        "MKL_NUM_THREADS": os.environ.get("MKL_NUM_THREADS"),
    }


def _assemble(config: FrozenRunConfig) -> AssembledBundle:
    return assemble_feature_bundle(
        config.inputs["features"],
        config.inputs["dictionary"],
        config.inputs["sidecar"],
        {
            "base": config.input_hashes["features"],
            "dictionary": config.input_hashes["dictionary"],
            "sidecar": config.input_hashes["sidecar"],
        },
    )


def _ledger_provenance(config: FrozenRunConfig) -> dict[str, Any]:
    return {
        "config_path": relative_to_root(config.path),
        "config_sha256": config.sha256,
        "declared_binding": config.declared_code,
        "code": code_receipts(),
    }


WORKERS_ENVIRONMENT_VARIABLE = "TENNISLAB_PIPELINE_WORKERS"


def pipeline_workers() -> int:
    """Worker processes for bagged candidates (TUNE01); 1, the default, fits in-process.

    Every other candidate is fitted in the stage's own process in the fixed loop order.
    Each bagged fit is a pure function of its identity, so forecasts do not depend on the
    worker count; every worker inherits the single-thread numerical environment.
    """
    text = os.environ.get(WORKERS_ENVIRONMENT_VARIABLE, "1")
    try:
        workers = int(text)
    except ValueError as error:
        raise PipelineError(
            f"{WORKERS_ENVIRONMENT_VARIABLE} must be an integer: {text!r}"
        ) from error
    if workers < 1:
        raise PipelineError(f"{WORKERS_ENVIRONMENT_VARIABLE} must be positive: {workers}")
    return workers


def stopping_partition(
    metadata: Mapping[tuple[str, str], Mapping[str, str]], year: int
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    """TUNE01: raw year R's training keys split for temporal early stopping.

    Stopping-validation keys are the window's last year, (R-1)-01-01 to (R-1)-12-30;
    stopping-train keys are dated up to (R-2)-12-30, the fit-boundary convention applied
    to R-1.  Keys dated (R-2)-12-31 belong to neither (they return in the refit).
    """
    validation_start, validation_end = dt.date(year - 1, 1, 1), dt.date(year - 1, 12, 30)
    train_end = dt.date(year - 2, 12, 30)
    train: list[tuple[str, str]] = []
    validation: list[tuple[str, str]] = []
    for key in training_keys(metadata, year):
        match_date = parse_iso(metadata[key]["match_date"])
        if validation_start <= match_date <= validation_end:
            validation.append(key)
        elif match_date <= train_end:
            train.append(key)
        elif match_date != dt.date(year - 2, 12, 31):
            raise PipelineError(f"training key outside every stopping set: {key}")
    if not train or not validation:
        raise PipelineError(f"raw year {year} has an empty stopping-train or validation set")
    return tuple(train), tuple(validation)


def run_raw_stage(
    config_path: Path,
    output_dir: Path,
    *,
    execute_frozen_real: bool = False,
) -> dict[str, Any]:
    """Fit the configured annual candidate menu and save all target forecasts unscored."""
    config = load_frozen_run_config(config_path)
    if config.document["execution_scope"] == "frozen_real_inputs" and not execute_frozen_real:
        raise PipelineError("real raw fitting requires explicit execute_frozen_real=True")
    bundle = _assemble(config)
    membership = validate_membership(bundle, config)
    workers = pipeline_workers()
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "raw_progress.json"
    write_progress(
        progress_path,
        "running",
        config_sha256=config.sha256,
        membership=membership,
        outcome_exposure="training_subsets_only",
    )
    cache = NUM.FileFitCache(output_dir / "fit_cache")
    attempts: list[dict[str, Any]] = []

    def settle(record: dict[str, Any], outcome: Any) -> None:
        result = outcome.result() if isinstance(outcome, Future) else outcome
        if "access" in result:
            access.absorb(result.pop("access"))
        record.update(result)
        if "prediction_sha256" not in record:
            record.pop("prediction_path")
        attempts.append(record)
        atomic_json(
            output_dir
            / "attempts"
            / str(record["year"])
            / record["learner"]
            / record["block"]
            / f"{record['candidate_id']}.json",
            record,
        )
        write_progress(
            progress_path,
            "running",
            config_sha256=config.sha256,
            completed_attempts=len(attempts),
            expected_attempts=membership["raw_fit_attempts"],
        )

    # One fixed loop: len(RAW_YEARS) x (candidates x blocks) fits per learner.
    for year in RAW_YEARS:
        train_keys = training_keys(bundle.metadata, year)
        prediction_keys = all_prediction_keys(bundle.metadata, year)
        primary_keys = target_keys(bundle.metadata, year)
        provisional_keys = provisional_target_keys(bundle.metadata, year)
        train_features = bundle.features.subset(train_keys)
        train_labels = label_subset(  # outcome-history read: training-window fits
            config.inputs["labels"],
            config.input_hashes["labels"],
            train_keys,
            bundle.metadata,
            purpose="training_fit",
            year_ceiling=training_window(year)[1].year,
            fold_outer_year=year,
        )
        prediction_features = bundle.features.subset(prediction_keys)
        if prediction_features.keys != prediction_keys:
            raise PipelineError("prediction feature membership drift")
        # TUNE01: each bundle with a bound menu shares one set of rows per raw year
        # (the stopping partition and the bag subsamples) across its grid candidates.
        bagged_inputs: dict[str, NUM.BaggedTreeInputs] = {}
        if "hgb" in LEARNERS and HGB_MENUS:
            stopping_train, stopping_validation = stopping_partition(bundle.metadata, year)
            for block, menu in HGB_MENUS.items():
                bagged_inputs[block] = NUM.prepare_bagged_tree_inputs(
                    numerical_config(bundle.contract, "hgb", block, next(iter(menu.grid_params))),
                    train_features,
                    train_labels,
                    stopping_train_keys=stopping_train,
                    stopping_validation_keys=stopping_validation,
                    raw_year=year,
                )
        shared = {
            "cache_root": str(output_dir / "fit_cache"),
            "training_keys": train_keys,
            "prediction_features": prediction_features,
            "inputs": bagged_inputs,
        }
        pool = (
            ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=NUM.init_bagged_worker,
                initargs=(shared,),
            )
            if bagged_inputs and workers > 1
            else None
        )
        pending: list[tuple[dict[str, Any], Any]] = []
        try:
            for learner in LEARNERS:
                for block in BLOCKS:
                    for candidate_id in candidate_ids(learner, block):
                        model_config = numerical_config(
                            bundle.contract, learner, block, candidate_id
                        )
                        identity = NUM.fit_identity(
                            model_config,
                            training_window(year)[1].isoformat(),
                            train_features,
                            train_labels,
                            config.sha256,
                        )
                        prediction_path = raw_prediction_path(
                            output_dir, year, learner, block, candidate_id
                        )
                        record: dict[str, Any] = {
                            # A measured cost per attempt (fit_wall_clock_seconds, from
                            # the fit) so a real run can be planned from a measurement.
                            "year": year,
                            "learner": learner,
                            "block": block,
                            "candidate_id": candidate_id,
                            "config_id": model_config["config_id"],
                            "training_rows": len(train_keys),
                            "training_membership_sha256": NUM.key_hash(train_keys),
                            "primary_target_rows": len(primary_keys),
                            "primary_target_membership_sha256": NUM.key_hash(primary_keys),
                            "provisional_target_rows": len(provisional_keys),
                            "provisional_target_membership_sha256": NUM.key_hash(provisional_keys),
                            "outcome_labels_used_for_fit": True,
                            "outcome_labels_used_for_prediction": False,
                            "prediction_path": str(prediction_path.relative_to(output_dir)),
                        }
                        if "tuning" in model_config:
                            # The partition and the subsamples enter the fit identity.
                            identity["bagging"] = bagged_inputs[block].receipt
                            record["fit_identity_sha256"] = NUM.sha256_json(identity)
                            task = {
                                "block": block,
                                "config": model_config,
                                "identity": identity,
                                "prediction_path": str(prediction_path),
                            }
                            if pool is not None:
                                pending.append((record, pool.submit(NUM.run_bagged_task, task)))
                                continue
                            outcome = NUM.execute_bagged_task(task, shared)
                        else:
                            record["fit_identity_sha256"] = NUM.sha256_json(identity)
                            outcome = NUM.fit_cached_and_predict(
                                cache,
                                identity,
                                train_keys,
                                lambda model_config=model_config, train_features=train_features, train_labels=train_labels: (
                                    NUM.fit_procedure(model_config, train_features, train_labels)
                                ),
                                prediction_features,
                                prediction_path,
                            )
                        if pending:
                            pending.append((record, outcome))
                        else:
                            settle(record, outcome)
            for record, outcome in pending:
                settle(record, outcome)
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
    if len(attempts) != membership["raw_fit_attempts"]:
        raise PipelineError("raw attempt count drift")
    ledger = {
        "status": (
            "complete_with_failures"
            if any(item["status"] != "complete" for item in attempts)
            else "complete"
        ),
        **_ledger_provenance(config),
        "membership": membership,
        "thread_environment": thread_environment(),
        "raw_attempts": attempts,
        "all_candidate_predictions_saved_before_scoring": True,
        "target_outcomes_scored": False,
    }
    if HGB_MENUS:
        # TUNE01 only, so every earlier ledger keeps its shape.
        ledger["hgb_menus"] = {block: menu.binding() for block, menu in HGB_MENUS.items()}
        ledger["process_workers"] = workers
    atomic_json(output_dir / "raw_complete.json", ledger)
    write_progress(progress_path, ledger["status"], config_sha256=config.sha256)
    return ledger


def _raw_attempt_index(
    ledger: Mapping[str, Any],
) -> dict[tuple[int, str, str, str], Mapping[str, Any]]:
    records = ledger.get("raw_attempts")
    if not isinstance(records, list):
        raise PipelineError("raw ledger lacks raw_attempts")
    output: dict[tuple[int, str, str, str], Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise PipelineError("invalid raw attempt record")
        key = (
            int(record["year"]),
            str(record["learner"]),
            str(record["block"]),
            str(record["candidate_id"]),
        )
        if key in output:
            raise PipelineError(f"duplicate raw attempt record: {key}")
        output[key] = record
    expected = {
        (year, learner, block, candidate_id)
        for year in RAW_YEARS
        for learner in LEARNERS
        for block in BLOCKS
        for candidate_id in candidate_ids(learner, block)
    }
    if set(output) != expected:
        raise PipelineError("raw attempt ledger does not contain the configured candidate menu")
    return output


def _read_bound_raw_prediction(
    output_dir: Path,
    attempt_index: Mapping[tuple[int, str, str, str], Mapping[str, Any]],
    year: int,
    learner: str,
    block: str,
    candidate_id: str,
    expected_keys: Sequence[tuple[str, str]],
) -> tuple[dict[tuple[str, str], float], Mapping[str, Any]]:
    record = attempt_index[(year, learner, block, candidate_id)]
    if record.get("status") != "complete":
        raise PipelineError(f"raw candidate unavailable: {year}/{learner}/{block}/{candidate_id}")
    path = output_dir / str(record["prediction_path"])
    observed_hash = sha256(path)
    if observed_hash != record.get("prediction_sha256"):
        raise PipelineError(f"raw prediction hash drift: {path}")
    values = prediction_map(path)
    if tuple(sorted(values)) != tuple(expected_keys):
        raise PipelineError(f"raw prediction membership drift: {path}")
    return values, record


def is_valid_market(metadata: Mapping[str, str]) -> bool:
    if not is_aligned_primary(metadata):
        return False
    missing = metadata["ps_missing"]
    probability_text = metadata["ps_probability_a"]
    if missing not in {"0", "1"}:
        raise PipelineError("ps_missing must be 0/1")
    if missing == "1":
        if probability_text != "":
            raise PipelineError("ps_missing=1 conflicts with populated ps_probability_a")
        return False
    if probability_text == "":
        raise PipelineError("ps_missing=0 conflicts with blank ps_probability_a")
    probability = parse_finite(
        probability_text, "ps_probability_a", metadata.get("calendar_year", "")
    )
    if not 0.0 <= probability <= 1.0:
        raise PipelineError("ps_probability_a outside [0,1]")
    return True


def market_keys(
    metadata: Mapping[tuple[str, str], Mapping[str, str]], year: int
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(key for key, row in metadata.items() if key[0] == str(year) and is_valid_market(row))
    )


def _tuning_summary(raw_record: Mapping[str, Any]) -> dict[str, Any]:
    """A bagged raw attempt's stopped iteration count, stop status and bag seeds (none of
    them a score); an empty mapping for every other candidate."""
    tuning = raw_record.get("tuning")
    if not isinstance(tuning, Mapping):
        return {}
    return {
        "tuning": {
            "k_star": tuning["k_star"],
            "k_stop": tuning["k_stop"],
            "stop_status": tuning["stop_status"],
            "curve_sha256": tuning["curve_sha256"],
            "bag_seeds": {
                role: [item["seed_sequence"] for item in records]
                for role, records in tuning["subsamples"].items()
            },
        }
    }


def run_selection_stage(
    config_path: Path,
    output_dir: Path,
    *,
    execute_frozen_real: bool = False,
) -> dict[str, Any]:
    """Fit past-only slopes, select complexity, and emit unscored outer forecasts."""
    config = load_frozen_run_config(config_path)
    if config.document["execution_scope"] == "frozen_real_inputs" and not execute_frozen_real:
        raise PipelineError("real selection requires explicit execute_frozen_real=True")
    raw_ledger_path = output_dir / "raw_complete.json"
    raw_ledger = json.loads(raw_ledger_path.read_text(encoding="utf-8"))
    if raw_ledger.get("config_sha256") != config.sha256:
        raise PipelineError("raw ledger/config binding mismatch")
    attempt_index = _raw_attempt_index(raw_ledger)
    bundle = _assemble(config)
    membership = validate_membership(bundle, config)
    progress_path = output_dir / "selection_progress.json"
    write_progress(progress_path, "running", config_sha256=config.sha256)
    selection_records: list[dict[str, Any]] = []
    shared_records: list[dict[str, Any]] = []
    market_records: list[dict[str, Any]] = []

    for outer_year in OUTER_YEARS:
        keys_by_year = selection_keys(bundle.metadata, outer_year)
        combined_selection_keys = tuple(
            sorted(key for year in validation_years(outer_year) for key in keys_by_year[year])
        )
        past_labels = label_subset(  # outcome-history read: past-year selection windows
            config.inputs["labels"],
            config.input_hashes["labels"],
            combined_selection_keys,
            bundle.metadata,
            purpose="past_selection_calibration",
            year_ceiling=outer_year - 1,
            fold_outer_year=outer_year,
        )
        labels_by_year = {
            year: [past_labels.values[key] for key in keys_by_year[year]]
            for year in validation_years(outer_year)
        }
        outer_prediction_keys = all_prediction_keys(bundle.metadata, outer_year)
        outer_primary_keys = target_keys(bundle.metadata, outer_year)
        outer_provisional_keys = provisional_target_keys(bundle.metadata, outer_year)
        selected_by_learner_block: dict[tuple[str, str], dict[str, Any]] = {}
        write_selection_keys(
            output_dir / "selection" / str(outer_year) / SELECTION_KEYS_FILE,
            combined_selection_keys,
        )

        for learner in LEARNERS:
            for block in BLOCKS:
                trials: dict[str, dict[str, Any]] = {}
                for candidate_id in candidate_ids(learner, block):
                    candidate_probabilities: dict[int, list[float]] = {}
                    prediction_sources: dict[str, dict[str, Any]] = {}
                    try:
                        for past_year in validation_years(outer_year):
                            raw_values, raw_record = _read_bound_raw_prediction(
                                output_dir,
                                attempt_index,
                                past_year,
                                learner,
                                block,
                                candidate_id,
                                all_prediction_keys(bundle.metadata, past_year),
                            )
                            candidate_probabilities[past_year] = [
                                raw_values[key] for key in keys_by_year[past_year]
                            ]
                            prediction_sources[str(past_year)] = {
                                "prediction_sha256": raw_record["prediction_sha256"],
                                "selection_rows": len(keys_by_year[past_year]),
                                "selection_membership_sha256": NUM.key_hash(
                                    keys_by_year[past_year]
                                ),
                                # TUNE01: the stopped iteration count and bag seeds of
                                # a bagged candidate's raw year (absent otherwise).
                                **_tuning_summary(raw_record),
                            }
                        trial = fit_nonnegative_slope(
                            candidate_probabilities,
                            labels_by_year,
                            validation_years(outer_year),
                        )
                    except Exception as error:
                        trial = {
                            "status": "failed",
                            "slope": None,
                            "equal_year_mean_log_loss": None,
                            "error": {
                                "type": type(error).__name__,
                                "message": str(error),
                            },
                            "fit_semantics": "in_sample_nuisance_calibration_on_past_selection_sample",
                        }
                    trial["candidate_id"] = candidate_id
                    trial["prediction_sources"] = prediction_sources
                    trials[candidate_id] = trial
                selected = select_calibrated_candidate(trials, candidate_ids(learner, block))
                record: dict[str, Any] = {
                    "outer_year": outer_year,
                    "learner": learner,
                    "block": block,
                    "status": selected["status"],
                    "selection_years": list(validation_years(outer_year)),
                    "selection_rows": len(combined_selection_keys),
                    "selection_membership_sha256": NUM.key_hash(combined_selection_keys),
                    "selection_keys_path": str(
                        Path("selection", str(outer_year), SELECTION_KEYS_FILE)
                    ),
                    "selection_cutoff_inclusive": dt.date(outer_year - 1, 12, 30).isoformat(),
                    "candidate_trials": {
                        candidate: public_fit(trial) for candidate, trial in trials.items()
                    },
                    "selection": public_selection(selected),
                    "criterion_sha256": common.canonical_hash(criterion_document(trials, selected)),
                    "outer_target_rows": len(outer_prediction_keys),
                    "outer_primary_rows": len(outer_primary_keys),
                    "outer_primary_membership_sha256": NUM.key_hash(outer_primary_keys),
                    "outer_provisional_rows": len(outer_provisional_keys),
                    "outer_provisional_membership_sha256": NUM.key_hash(outer_provisional_keys),
                    "outer_labels_used": False,
                }
                if learner == "hgb" and block in HGB_MENUS:
                    record["hgb_menu"] = HGB_MENUS[block].binding()
                if selected["status"] == "complete":
                    chosen_id = str(selected["selected_candidate_id"])
                    raw_values, raw_record = _read_bound_raw_prediction(
                        output_dir,
                        attempt_index,
                        outer_year,
                        learner,
                        block,
                        chosen_id,
                        outer_prediction_keys,
                    )
                    calibrated = apply_slope(
                        [raw_values[key] for key in outer_prediction_keys],
                        float(selected["selected_slope"]),
                    )
                    selected_path = (
                        output_dir / "selected" / str(outer_year) / learner / f"{block}.csv"
                    )
                    selected_hash = _write_calibrated_predictions(
                        selected_path, outer_prediction_keys, calibrated
                    )
                    record.update(
                        {
                            "selected_candidate_id": chosen_id,
                            "selected_slope": selected["selected_slope"],
                            "selected_prediction_path": str(selected_path.relative_to(output_dir)),
                            "selected_prediction_sha256": selected_hash,
                            "source_raw_prediction_sha256": raw_record["prediction_sha256"],
                            "selected_prediction_membership_sha256": NUM.key_hash(
                                outer_prediction_keys
                            ),
                            **_tuning_summary(raw_record),
                        }
                    )
                selection_records.append(record)
                selected_by_learner_block[(learner, block)] = record
                atomic_json(
                    output_dir / "selection" / str(outer_year) / learner / f"{block}.json",
                    record,
                )

            base_record = selected_by_learner_block[(learner, "base")]
            for block in BLOCKS:
                own_record = selected_by_learner_block[(learner, block)]
                shared_record: dict[str, Any] = {
                    "outer_year": outer_year,
                    "learner": learner,
                    "block": block,
                    "status": "unavailable",
                    "complexity_source": "base_selected_candidate",
                    "slope_source": "block_own_candidate_trial",
                    "outer_labels_used": False,
                }
                if base_record["status"] == "complete" and own_record["status"] == "complete":
                    shared_q = str(base_record["selected_candidate_id"])
                    own_trial = own_record["candidate_trials"][shared_q]
                    if own_trial["status"] == "complete":
                        raw_values, raw_record = _read_bound_raw_prediction(
                            output_dir,
                            attempt_index,
                            outer_year,
                            learner,
                            block,
                            shared_q,
                            outer_prediction_keys,
                        )
                        calibrated = apply_slope(
                            [raw_values[key] for key in outer_prediction_keys],
                            float(own_trial["slope"]),
                        )
                        shared_path = (
                            output_dir / "shared_base" / str(outer_year) / learner / f"{block}.csv"
                        )
                        shared_hash = _write_calibrated_predictions(
                            shared_path, outer_prediction_keys, calibrated
                        )
                        shared_record.update(
                            {
                                "status": "complete",
                                "candidate_id": shared_q,
                                "slope": own_trial["slope"],
                                "prediction_path": str(shared_path.relative_to(output_dir)),
                                "prediction_sha256": shared_hash,
                                "source_raw_prediction_sha256": raw_record["prediction_sha256"],
                                "prediction_rows": len(outer_prediction_keys),
                                "prediction_membership_sha256": NUM.key_hash(outer_prediction_keys),
                            }
                        )
                shared_records.append(shared_record)
                atomic_json(
                    output_dir / "shared_base" / str(outer_year) / learner / f"{block}.json",
                    shared_record,
                )

        market_selection_keys = {
            year: tuple(key for key in keys_by_year[year] if is_valid_market(bundle.metadata[key]))
            for year in validation_years(outer_year)
        }
        market_selection_union = tuple(
            sorted(
                key for year in validation_years(outer_year) for key in market_selection_keys[year]
            )
        )
        market_labels = label_subset(  # outcome-history read: past-year market calibration
            config.inputs["labels"],
            config.input_hashes["labels"],
            market_selection_union,
            bundle.metadata,
            purpose="past_market_calibration",
            year_ceiling=outer_year - 1,
            fold_outer_year=outer_year,
        )
        market_fit = fit_nonnegative_slope(
            {
                year: [
                    float(bundle.metadata[key]["ps_probability_a"])
                    for key in market_selection_keys[year]
                ]
                for year in validation_years(outer_year)
            },
            {
                year: [market_labels.values[key] for key in market_selection_keys[year]]
                for year in validation_years(outer_year)
            },
            validation_years(outer_year),
        )
        current_market_keys = market_keys(bundle.metadata, outer_year)
        write_selection_keys(
            output_dir / "market" / str(outer_year) / SELECTION_KEYS_FILE, market_selection_union
        )
        market_record: dict[str, Any] = {
            "outer_year": outer_year,
            "status": market_fit["status"],
            "selection_years": list(validation_years(outer_year)),
            "selection_rows": len(market_selection_union),
            "selection_membership_sha256": NUM.key_hash(market_selection_union),
            "selection_keys_path": str(Path("market", str(outer_year), SELECTION_KEYS_FILE)),
            "selection_cutoff_inclusive": dt.date(outer_year - 1, 12, 30).isoformat(),
            "target_rows": len(current_market_keys),
            "target_membership_sha256": NUM.key_hash(current_market_keys),
            "slope_fit": public_fit(market_fit),
            "criterion_sha256": common.canonical_hash(fit_criterion_document(market_fit)),
            "outer_labels_used": False,
            "quote_timing": "unknown",
        }
        if market_fit["status"] == "complete":
            raw_market = [
                float(bundle.metadata[key]["ps_probability_a"]) for key in current_market_keys
            ]
            calibrated_market = apply_slope(raw_market, float(market_fit["slope"]))
            raw_market_path = output_dir / "market" / str(outer_year) / "raw_ps.csv"
            calibrated_market_path = output_dir / "market" / str(outer_year) / "calibrated_ps.csv"
            market_record.update(
                {
                    "raw_prediction_path": str(raw_market_path.relative_to(output_dir)),
                    "raw_prediction_sha256": _write_calibrated_predictions(
                        raw_market_path, current_market_keys, raw_market
                    ),
                    "calibrated_prediction_path": str(
                        calibrated_market_path.relative_to(output_dir)
                    ),
                    "calibrated_prediction_sha256": _write_calibrated_predictions(
                        calibrated_market_path, current_market_keys, calibrated_market
                    ),
                    "slope": market_fit["slope"],
                }
            )
        market_records.append(market_record)
        atomic_json(output_dir / "market" / str(outer_year) / "calibration.json", market_record)
        write_progress(
            progress_path,
            "running",
            config_sha256=config.sha256,
            completed_outer_years=OUTER_YEARS.index(outer_year) + 1,
            expected_outer_years=len(OUTER_YEARS),
        )

    failed = [record for record in selection_records if record["status"] != "complete"]
    failed += [record for record in market_records if record["status"] != "complete"]
    ledger = {
        "status": "complete_with_failures" if failed else "complete",
        **_ledger_provenance(config),
        "raw_complete_sha256": sha256(raw_ledger_path),
        "membership": membership,
        "thread_environment": thread_environment(),
        "selection_records": selection_records,
        "shared_base_records": shared_records,
        "market_records": market_records,
        "all_outer_forecasts_saved_before_reporting": True,
        "outer_target_outcomes_scored": False,
    }
    atomic_json(output_dir / "selection_complete.json", ledger)
    write_progress(progress_path, ledger["status"], config_sha256=config.sha256)
    return ledger


def run_curve_publication(config_path: Path, output_dir: Path, publish_dir: Path) -> dict[str, Any]:
    """TUNE01, after the barrier (RB14): publish the early-stopping curves of the selected
    bagged candidates.

    The pipeline committed only each curve's sha256, because a curve is a set of scores
    of an earlier fold's target year.  For every outer year whose selected candidate in a
    menu bundle is a bagged one, the stopping members of that candidate and raw year (=
    the outer year) are refitted from the same training-window rows, the curve is checked
    against its committed hash and written with the patience decision.  Reads the same
    training-window outcomes as the raw fit (purpose ``training_fit``, ceiling R - 1);
    reads no target-year outcome.  A hash mismatch is recorded, never repaired.
    """
    config = load_frozen_run_config(config_path)
    barrier = output_dir.parent / "barrier" / "stage_manifest.json"
    if not barrier.is_file() or not read_config(barrier).get("run_tree_sha256"):
        raise PipelineError(f"curve publication needs a frozen barrier: {barrier}")
    if publish_dir.exists():
        raise PipelineError(f"refusing to replace published curves: {publish_dir}")
    selection = read_config(output_dir / "selection_complete.json")
    raw_ledger = read_config(output_dir / "raw_complete.json")
    if (
        selection.get("config_sha256") != config.sha256
        or raw_ledger.get("config_sha256") != config.sha256
    ):
        raise PipelineError("selection/raw ledgers were not produced from this config")
    attempt_index = _raw_attempt_index(raw_ledger)
    bundle = _assemble(config)
    published: list[dict[str, Any]] = []
    for record in selection["selection_records"]:
        block, year = str(record["block"]), int(record["outer_year"])
        if record["learner"] != "hgb" or block not in HGB_MENUS:
            continue
        candidate = str(record["selected_candidate_id"])
        model_config = numerical_config(bundle.contract, "hgb", block, candidate)
        entry: dict[str, Any] = {"outer_year": year, "block": block, "candidate_id": candidate}
        if "tuning" not in model_config:
            published.append({**entry, "status": "anchor_selected_no_curve"})
            continue
        committed = attempt_index[(year, "hgb", block, candidate)]["tuning"]
        train_keys = training_keys(bundle.metadata, year)
        stopping_train, stopping_validation = stopping_partition(bundle.metadata, year)
        inputs = NUM.prepare_bagged_tree_inputs(
            model_config,
            bundle.features.subset(train_keys),
            label_subset(  # outcome-history read: the raw fit's own training window
                config.inputs["labels"],
                config.input_hashes["labels"],
                train_keys,
                bundle.metadata,
                purpose="training_fit",
                year_ceiling=training_window(year)[1].year,
                fold_outer_year=year,
            ),
            stopping_train_keys=stopping_train,
            stopping_validation_keys=stopping_validation,
            raw_year=year,
        )
        curve, _ = NUM.bagged_stopping_curve(model_config, inputs)
        tuning = model_config["tuning"]
        decision = NUM.early_stopping_decision(curve, tuning["patience"], tuning["tol"])
        digest = NUM.sha256_json(curve)
        entry.update(
            {
                "status": "published",
                "raw_year": year,
                "stopping_validation_year": year - 1,
                "curve_semantics": "L(k), k = 1..cap: validation log loss of the bag-averaged "
                "symmetrised forecast on the stopping-validation year (an earlier fold's "
                "target year)",
                "curve": curve,
                "curve_sha256": digest,
                "committed_curve_sha256": committed["curve_sha256"],
                "hash_matches": digest == committed["curve_sha256"],
                "partition_matches": all(
                    inputs.receipt[key] == committed[key] for key in inputs.receipt
                ),
                "decision": decision,
                "committed_decision": {key: committed[key] for key in decision},
            }
        )
        published.append(entry)
        atomic_json(publish_dir / str(year) / "hgb" / f"{block}.json", entry)
    summary = {
        "status": (
            "complete"
            if all(item.get("hash_matches", True) for item in published)
            else "hash_mismatch_recorded"
        ),
        **_ledger_provenance(config),
        "barrier_run_tree_sha256": read_config(barrier)["run_tree_sha256"],
        "selection_complete_sha256": sha256(output_dir / "selection_complete.json"),
        "published": [
            {key: value for key, value in item.items() if key != "curve"} for item in published
        ],
    }
    atomic_json(publish_dir / "curves_complete.json", summary)
    return summary


def run_preflight(config_path: Path) -> dict[str, Any]:
    config = load_frozen_run_config(config_path)
    bundle = _assemble(config)
    result = {
        "status": "PASS_NO_FIT_NO_SCORE",
        "config_path": relative_to_root(config.path),
        "config_sha256": config.sha256,
        "input_hashes": config.input_hashes,
        "membership": validate_membership(bundle, config),
        "ordered_model_columns_sha256": sha256_json(ordered_model_columns(bundle.contract)),
        "declared_binding": config.declared_code,
        "code": code_receipts(),
    }
    if tour_contract():
        result["dynamic_feature_dispersion_by_raw_year"] = dynamic_dispersion_by_raw_year(
            bundle.metadata
        )
        result["dynamic_feature_dispersion_by_training_window"] = training_window_dispersion(
            bundle.metadata
        )
    return result


def runtime_description(year_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if year_plan is not None:
        configure_years(year_plan)
    receipts = code_receipts()
    return {
        "experiment_id": EXPERIMENT_ID,
        "tour": TOUR,
        "code": {
            "runner_path": receipts["runner"]["module"],
            "runner_sha256": receipts["runner"]["sha256"],
            "numerical_path": receipts["numerical"]["module"],
            "numerical_sha256": receipts["numerical"]["sha256"],
            "package_version": receipts["runner"]["package_version"],
        },
        "dependencies": dependency_versions(),
        "thread_environment": thread_environment(),
        "settings": settings_document(),
        "forecast_csv_columns": ["season", "match_id", "p_a_wins"],
    }


def write_progress(path: Path, status: str, **details: Any) -> None:
    atomic_json(path, {"status": status, **details})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    describe = subparsers.add_parser(
        "describe", help="print code, dependency, and configured-setting bindings"
    )
    describe.add_argument(
        "--year-plan",
        type=Path,
        help="JSON file holding the year_plan object; omitted means the default 2017-2024 plan",
    )
    for name in ("preflight", "raw", "select", "pipeline"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        if name != "preflight":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--execute-frozen-real", action="store_true")
    curves = subparsers.add_parser(
        "curves",
        help="TUNE01, after the barrier: publish the selected bagged candidates' "
        "early-stopping curves and check them against their committed hashes",
    )
    curves.add_argument("--config", type=Path, required=True)
    curves.add_argument("--output", type=Path, required=True, help="the pipeline stage directory")
    curves.add_argument("--publish", type=Path, required=True, help="a new post-barrier directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "describe":
            plan = None
            if args.year_plan is not None:
                plan = read_config(resolve_under_root(args.year_plan, label="year_plan"))
                plan = plan.get("year_plan", plan)
            result = runtime_description(plan)
        elif args.command == "preflight":
            result = run_preflight(args.config)
        elif args.command == "curves":
            result = run_curve_publication(
                args.config,
                resolve_under_root(args.output, label="output"),
                resolve_output_under_root(args.publish, label="publish"),
            )
        else:
            output = resolve_output_under_root(args.output, label="output")
            if args.command == "raw":
                result = run_raw_stage(
                    args.config, output, execute_frozen_real=args.execute_frozen_real
                )
            elif args.command == "select":
                result = run_selection_stage(
                    args.config, output, execute_frozen_real=args.execute_frozen_real
                )
            else:
                run_raw_stage(args.config, output, execute_frozen_real=args.execute_frozen_real)
                result = run_selection_stage(
                    args.config, output, execute_frozen_real=args.execute_frozen_real
                )
    except ChainError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
