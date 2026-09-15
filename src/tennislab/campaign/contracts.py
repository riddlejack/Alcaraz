"""Frozen settings, code bindings, and workspace-confined campaign configuration."""

from __future__ import annotations

import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import scipy
import sklearn

from tennislab.campaign.members import MEMBER_IDS
from tennislab.campaign.stack import (
    STACK_FTOL,
    STACK_GTOL,
    STACK_INITIAL,
    STACK_L2,
    STACK_LOGIT_CLIP,
    STACK_MAXITER,
    STACK_PROJECTED_GRADIENT_TOL,
)
from tennislab.campaign.stages import (
    CONSUMER_CONFIG_SCHEMA,
    INDEPENDENT_REVIEW_SCHEMA,
    PRODUCER_COMPLETION_SCHEMA,
    PRODUCER_PLAN_SCHEMA,
    forecast_inventory_contract,
    read_object,
    report_inventory_contract,
    require_completion,
)
from tennislab.campaign.stages import (
    binding as stage_binding,
)
from tennislab.chain.common import (
    ChainError,
    canonical_hash_nonempty,
    code_receipt,
    read_config,
    relative_to_root,
    require_nonempty_digest,
    resolve_under_root,
    sha256,
)
from tennislab.dynamics.calibrate import CAMPAIGN_FIT_DISCLOSURE_POLICY
from tennislab.models import pipeline

CAMPAIGN_MODULES = (
    "tennislab.campaign.members",
    "tennislab.campaign.stack",
    "tennislab.campaign.artifacts",
    "tennislab.campaign.contracts",
    "tennislab.campaign.forecast",
    "tennislab.campaign.barrier",
    "tennislab.campaign.report",
    "tennislab.campaign.runner",
    "tennislab.campaign.stages",
    "tennislab.chain.barrier_scan",
    "tennislab.chain.common",
    "tennislab.chain.labels",
    "tennislab.dynamics.calibrate",
    "tennislab.evaluation.scores",
    "tennislab.models.numerical",
    "tennislab.models.pipeline",
)
TARGET_YEARS = {"ATP": tuple(range(2017, 2025)), "WTA": tuple(range(2019, 2025))}
EXPECTED_POPULATION = {
    "ATP": {"target_rows": 18_972, "priced_rows": 18_882},
    "WTA": {"target_rows": 12_900, "priced_rows": 12_785},
}
CONSUMER_CODE_AUTHORIZATION_SCHEMA = "campaign_consumer_code_authorization/v1"
EC01_AUTHORIZATION_ID = "D91"
EC01_TRANSITION_ID = "EC-01"
EC01_COMPLETION_REVIEW_SHA256 = "518c5b405d61eec84495e1080839ba9c2013a6a0852df56ff22b1cff36c06170"
EC01_CHANGED_MODULES = (
    "tennislab.campaign.artifacts",
    "tennislab.campaign.contracts",
)
EC01_AUTHORIZED_SEMANTICS = {
    "full_metadata_source_season_alignment": "not_required",
    "qualified_membership_source_season_alignment": "required",
    "calendar_key_date_eligibility_integrity": "required",
    "producer_graph_and_fit_identities": "immutable",
    "refit_or_consumer_execution": "not_authorized",
}


class CampaignConfigError(ChainError):
    """A campaign config, binding, execution scope, or frozen setting drifted."""


@dataclass(frozen=True)
class CampaignConfig:
    document: dict[str, Any]
    path: Path
    sha256: str
    tour: str
    raw_years: tuple[int, ...]
    target_years: tuple[int, ...]
    producer_plan_path: Path
    producer_plan_sha256: str
    producer_plan: dict[str, Any]
    producer_completion_path: Path
    producer_completion_sha256: str
    producer_completion: dict[str, Any]
    input_manifest_path: Path
    input_manifest_sha256: str
    raw_quotes_path: Path
    raw_quotes_sha256: str
    output_prefix: Path


def raw_years_for(target_years: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(range(target_years[0] - 3, target_years[-1] + 1))


def campaign_settings(tour: str, target_years: tuple[int, ...] | None = None) -> dict[str, Any]:
    normalized = str(tour).upper()
    if normalized not in TARGET_YEARS:
        raise CampaignConfigError(f"unsupported tour: {tour!r}")
    targets = TARGET_YEARS[normalized] if target_years is None else tuple(target_years)
    if not targets or targets != tuple(sorted(set(targets))):
        raise CampaignConfigError("target years must be nonempty, sorted, and unique")
    raw_years = raw_years_for(targets)
    tree_bundle = "full_tier" if normalized == "ATP" else "full"
    return {
        "schema_version": 1,
        "tour": normalized,
        "runtime": {
            "python_implementation": platform.python_implementation(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "year_plan": {
            "target_years": list(targets),
            "raw_years": list(raw_years),
            "selection_years_back": 3,
            "training_window_years": 5,
            "history_floor_year": 2011,
            "training_start_rule": "max(2011-01-01, raw_year_minus_5-01-01)",
            "training_end_month_day": "12-30",
            "cutoff": "D-2_reported_date_inclusive",
        },
        "configurations": {
            "S0": "unchanged_incumbent_selected_calibrated_hgb",
            "S1": "fixed_probability_blend_S0_and_result_pooled_Elo_equal_weights",
            "S2": "two_setting_random_forest_inherited_past_only_slope_and_selection",
            "S3": "eight_fixed_raw_member_positive_L2_nonnegative_logit_stack",
        },
        "raw_member_order": list(MEMBER_IDS),
        "raw_member_contracts": [
            {"member_id": "result_elo", "kind": "deterministic_state", "bundle": "result_elo"},
            {"member_id": "hgb_leaf07_depth3", "learner": "hgb", "bundle": tree_bundle},
            {"member_id": "hgb_leaf15_depth4", "learner": "hgb", "bundle": tree_bundle},
            {"member_id": "ridge_c001", "learner": "ridge", "bundle": "full"},
            {"member_id": "ridge_c01", "learner": "ridge", "bundle": "full"},
            {"member_id": "ridge_c1", "learner": "ridge", "bundle": "full"},
            {"member_id": "rf_leaf50", "learner": "random_forest", "bundle": tree_bundle},
            {"member_id": "rf_leaf100", "learner": "random_forest", "bundle": tree_bundle},
        ],
        "random_forest": {
            "candidate_ids": [item[0] for item in pipeline.RF_CANDIDATES],
            "estimator_params": pipeline.RF_PARAMS,
            "selection": "inherited_nonnegative_slope_then_candidate_rank_on_same_three_past_years",
            "tree_feature_contract": "named_signed_and_symmetric_context_allowlist_only",
        },
        "stack": {
            "probability_clip": STACK_LOGIT_CLIP,
            "l2_penalty": STACK_L2,
            "intercept": False,
            "sum_to_one": False,
            "bounds": [0.0, None],
            "initial_coefficient": STACK_INITIAL,
            "optimizer": "scipy_L-BFGS-B",
            "maxiter": STACK_MAXITER,
            "ftol": STACK_FTOL,
            "gtol": STACK_GTOL,
            "projected_gradient_inf_norm_max": STACK_PROJECTED_GRADIENT_TOL,
            "second_calibration_slope": False,
        },
        "sr03_fit_disclosure": {
            "config_field": "calibration.fit_disclosure_policy",
            "policy": CAMPAIGN_FIT_DISCLOSURE_POLICY,
            "prebarrier_sinks": ["fit_events.jsonl", "fits.json"],
            "prebarrier_objective_values": False,
            "postbarrier_disclosure_artifact": "fit_objectives.json",
            "prebarrier_raw_quotes_parsed": False,
            "prebarrier_prediction_price_values": False,
            "standalone_campaign_evaluate_requires_barrier": True,
            "postbarrier_both_sink_commitments_reconciled": True,
        },
        "report": {
            "primary_contrast": "S3_minus_S0",
            "secondary_contrasts": ["S1_minus_S0", "S2_minus_S0", "S3_minus_S2"],
            "score_probability_clip": 1e-15,
            "primary_estimand": "equal_year_mean_of_paired_match_log_loss_deltas",
            "bootstrap": {
                "unit": "tournament_edition_within_year",
                "replicates": 2000,
                "interval": "95_percentile_linear_quantiles",
                "generator": "numpy_PCG64",
                "seed": 20260914,
                "years": "ascending",
            },
            "calibration_edges": [index / 10 for index in range(11)],
            "score_only_sensitivities": ["leave_one_year_out", "leave_2020_out"],
            "annual_equal_year_degrees_of_freedom": "number_of_target_years_minus_one",
            "nomination": {
                "candidate": "S3_only",
                "maximum_equal_year_delta": -0.002,
                "minimum_negative_years": 6 if normalized == "ATP" else 5,
                "required_years": 8 if normalized == "ATP" else 6,
                "interval_upper_below_zero": True,
                "automatic_promotion": False,
            },
        },
        "forbidden_predictor_classes": [
            "current_market_prices",
            "lagged_market_inputs",
            "market_missingness_or_coverage",
            "player_id_ordinal_encodings",
            "undeclared_numeric_columns",
        ],
    }


def code_bindings() -> dict[str, dict[str, str]]:
    return {module: code_receipt(module) for module in CAMPAIGN_MODULES}


def code_inventory_sha256(value: Any, *, label: str = "campaign code inventory") -> str:
    """Validate and canonically bind a complete campaign code inventory."""
    if not isinstance(value, Mapping) or set(value) != set(CAMPAIGN_MODULES):
        raise CampaignConfigError(f"{label} is incomplete")
    inventory: dict[str, dict[str, str]] = {}
    for module in CAMPAIGN_MODULES:
        item = value[module]
        if not isinstance(item, Mapping) or set(item) != {
            "module",
            "package_version",
            "sha256",
        }:
            raise CampaignConfigError(f"{label} has an invalid binding for {module}")
        if item.get("module") != module or not str(item.get("package_version", "")).strip():
            raise CampaignConfigError(f"{label} has invalid module metadata for {module}")
        require_nonempty_digest(item.get("sha256"), label=f"{label}.{module}.sha256")
        inventory[module] = dict(item)
    return canonical_hash_nonempty(inventory, label=label)


def _validate_consumer_code_transition(
    *,
    document: Mapping[str, Any],
    review: Mapping[str, Any],
    tour: str,
    producer_plan_sha256: str,
    producer_completion_sha256: str,
    producer_code: Mapping[str, Any],
    consumer_code: Mapping[str, Any],
) -> None:
    """Bind the exact EC-01 transition; external issuance/review confers authority."""
    try:
        authorization_path, authorization_sha256 = stage_binding(
            document.get("consumer_code_authorization"),
            label="consumer code root authorization",
        )
        authorization = read_object(
            authorization_path,
            label="consumer code root authorization",
        )
    except ValueError as error:
        raise CampaignConfigError(str(error)) from error
    required_fields = {
        "schema",
        "stage",
        "status",
        "authorization_id",
        "transition_id",
        "tour",
        "producer_plan_sha256",
        "producer_completion_sha256",
        "producer_code_inventory_sha256",
        "successor_code_inventory_sha256",
        "successor_commit",
        "changed_modules",
        "completion_review_sha256",
        "authorized_semantics",
    }
    if set(authorization) != required_fields:
        raise CampaignConfigError("consumer code root authorization fields drift")
    producer_inventory_sha256 = code_inventory_sha256(
        producer_code,
        label="producer code inventory",
    )
    successor_inventory_sha256 = code_inventory_sha256(
        consumer_code,
        label="successor consumer code inventory",
    )
    changed_modules = tuple(
        module for module in CAMPAIGN_MODULES if producer_code[module] != consumer_code[module]
    )
    successor_commit = authorization.get("successor_commit")
    if (
        authorization.get("schema") != CONSUMER_CODE_AUTHORIZATION_SCHEMA
        or authorization.get("stage") != "consumer_code_authorization"
        or authorization.get("status") != "accepted"
        or authorization.get("authorization_id") != EC01_AUTHORIZATION_ID
        or authorization.get("transition_id") != EC01_TRANSITION_ID
        or authorization.get("tour") != tour
        or authorization.get("producer_plan_sha256") != producer_plan_sha256
        or authorization.get("producer_completion_sha256") != producer_completion_sha256
        or authorization.get("producer_code_inventory_sha256") != producer_inventory_sha256
        or authorization.get("successor_code_inventory_sha256") != successor_inventory_sha256
        or authorization.get("changed_modules") != list(EC01_CHANGED_MODULES)
        or changed_modules != EC01_CHANGED_MODULES
        or authorization.get("completion_review_sha256") != EC01_COMPLETION_REVIEW_SHA256
        or authorization.get("authorized_semantics") != EC01_AUTHORIZED_SEMANTICS
        or not isinstance(successor_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", successor_commit) is None
        or document.get("consumer_source_commit") != successor_commit
    ):
        raise CampaignConfigError("consumer code root authorization does not bind exact EC-01")
    try:
        _, repair_review_sha256 = stage_binding(
            review.get("repair_review"),
            label="independent EC-01 repair review",
        )
    except ValueError as error:
        raise CampaignConfigError(str(error)) from error
    if (
        review.get("consumer_code_transition") != EC01_TRANSITION_ID
        or review.get("consumer_code_authorization_sha256") != authorization_sha256
        or review.get("successor_code_inventory_sha256") != successor_inventory_sha256
        or review.get("successor_commit") != successor_commit
        or repair_review_sha256 == authorization_sha256
    ):
        raise CampaignConfigError(
            "independent review does not bind the consumer code root authorization"
        )


def load_campaign_config(path: Path | str) -> CampaignConfig:
    resolved = resolve_under_root(path, label="campaign config")
    document = read_config(resolved)
    if document.get("schema") != CONSUMER_CONFIG_SCHEMA or document.get("schema_version") != 1:
        raise CampaignConfigError(f"campaign config schema must be {CONSUMER_CONFIG_SCHEMA}")
    if document.get("stage") != "consumer_config":
        raise CampaignConfigError("campaign consumer config stage drift")
    if document.get("status") != "complete":
        raise CampaignConfigError("campaign consumer config is not complete")
    if document.get("campaign_id") is None or not str(document["campaign_id"]).strip():
        raise CampaignConfigError("campaign_id must be nonempty")
    scope = document.get("execution_scope")
    if scope not in {"synthetic_rehearsal", "frozen_real_inputs"}:
        raise CampaignConfigError(
            "execution_scope must be synthetic_rehearsal or frozen_real_inputs"
        )
    settings = document.get("settings")
    if not isinstance(settings, dict):
        raise CampaignConfigError("campaign settings must be an object")
    tour = str(settings.get("tour", "")).upper()
    plan = settings.get("year_plan")
    if not isinstance(plan, dict):
        raise CampaignConfigError("campaign settings need a year_plan")
    targets = tuple(int(year) for year in plan.get("target_years", ()))
    expected = campaign_settings(tour, targets)
    if settings != expected:
        raise CampaignConfigError("campaign settings differ from the reviewed executable contract")
    if scope == "frozen_real_inputs" and targets != TARGET_YEARS[tour]:
        raise CampaignConfigError("real campaign target years differ from the reviewed population")
    if (
        scope == "frozen_real_inputs"
        and document.get("expected_population") != EXPECTED_POPULATION[tour]
    ):
        raise CampaignConfigError("real campaign population counts differ from reviewed constants")

    try:
        producer_plan_path, producer_plan_digest = stage_binding(
            document.get("producer_plan"), label="campaign producer plan"
        )
        producer_plan = read_object(producer_plan_path, label="campaign producer plan")
        require_completion(producer_plan, schema=PRODUCER_PLAN_SCHEMA, stage="producer_plan")
        producer_completion_path, producer_completion_digest = stage_binding(
            document.get("producer_completion"), label="campaign producer completion"
        )
        producer_completion = read_object(
            producer_completion_path, label="campaign producer completion"
        )
        require_completion(
            producer_completion,
            schema=PRODUCER_COMPLETION_SCHEMA,
            stage="producer_completion",
        )
    except ValueError as error:
        raise CampaignConfigError(str(error)) from error
    for label, producer in (("plan", producer_plan), ("completion", producer_completion)):
        if producer.get("tour") != tour:
            raise CampaignConfigError(f"producer {label} tour drift")
        if producer.get("raw_years") != list(raw_years_for(targets)):
            raise CampaignConfigError(f"producer {label} raw-year drift")
        if producer.get("target_years") != list(targets):
            raise CampaignConfigError(f"producer {label} target-year drift")
        if producer.get("custody_scope") != scope:
            raise CampaignConfigError(f"producer {label} custody scope drift")
    if producer_plan.get("settings") != settings:
        raise CampaignConfigError("producer plan settings differ from consumer settings")
    if producer_completion.get("producer_plan_sha256") != producer_plan_digest:
        raise CampaignConfigError("producer completion/plan binding drift")
    if (
        document.get("execution_scope") == "frozen_real_inputs"
        and producer_plan.get("independent_review_status") != "accepted"
    ):
        raise CampaignConfigError("real producer plan lacks accepted independent review")
    review: dict[str, Any] | None = None
    if document.get("execution_scope") == "frozen_real_inputs":
        try:
            review_path, _ = stage_binding(
                document.get("independent_review"), label="campaign independent review"
            )
            review = read_object(review_path, label="campaign independent review")
            require_completion(
                review,
                schema=INDEPENDENT_REVIEW_SCHEMA,
                stage="independent_review",
            )
        except ValueError as error:
            raise CampaignConfigError(str(error)) from error
        if (
            review.get("tour") != tour
            or review.get("producer_plan_sha256") != producer_plan_digest
            or review.get("producer_completion_sha256") != producer_completion_digest
            or review.get("qualification_sha256")
            != producer_plan.get("qualification", {}).get("sha256")
        ):
            raise CampaignConfigError("independent review does not bind the real campaign graph")

    design = document.get("design")
    if not isinstance(design, dict):
        raise CampaignConfigError("campaign config needs a design binding")
    design_path = resolve_under_root(design.get("path", ""), label="campaign design")
    if sha256(design_path) != design.get("sha256"):
        raise CampaignConfigError("campaign design hash mismatch")

    declared_code = document.get("code")
    code_inventory_sha256(declared_code, label="campaign code binding inventory")
    assert isinstance(declared_code, Mapping)
    observed_code = code_bindings()
    for module in CAMPAIGN_MODULES:
        binding = declared_code[module]
        if not isinstance(binding, dict):
            raise CampaignConfigError(f"invalid code binding for {module}")
        require_nonempty_digest(binding.get("sha256"), label=f"code.{module}.sha256")
        if binding != observed_code[module]:
            raise CampaignConfigError(f"campaign code binding drift: {module}")
    producer_code = producer_plan.get("code")
    code_inventory_sha256(producer_code, label="producer code binding inventory")
    assert isinstance(producer_code, Mapping)
    if producer_code == declared_code:
        if "consumer_code_authorization" in document or "consumer_source_commit" in document:
            raise CampaignConfigError("unexpected consumer code transition binding")
    else:
        if scope != "frozen_real_inputs" or review is None:
            raise CampaignConfigError("producer plan/consumer code binding drift")
        _validate_consumer_code_transition(
            document=document,
            review=review,
            tour=tour,
            producer_plan_sha256=producer_plan_digest,
            producer_completion_sha256=producer_completion_digest,
            producer_code=producer_code,
            consumer_code=declared_code,
        )
    if document.get("attempt_id") != "001":
        raise CampaignConfigError("campaign attempt_id must be the frozen first repair attempt")
    if document.get("expected_forecast_schema") != "campaign_forecast_completion/v1":
        raise CampaignConfigError("campaign forecast completion schema drift")
    if document.get("expected_barrier_schema") != "campaign_barrier_completion/v1":
        raise CampaignConfigError("campaign barrier completion schema drift")
    if document.get("expected_report_schema") != "campaign_report_completion/v1":
        raise CampaignConfigError("campaign report completion schema drift")
    if document.get("expected_forecast_inventory") != forecast_inventory_contract(targets):
        raise CampaignConfigError("campaign forecast inventory differs from fixed target years")
    if document.get("expected_report_inventory") != report_inventory_contract():
        raise CampaignConfigError("campaign report inventory differs from fixed stage roles")

    try:
        input_path, input_digest = stage_binding(
            document.get("input_manifest"), label="input manifest"
        )
        raw_quotes_path, raw_quotes_digest = stage_binding(
            document.get("raw_quotes"), label="raw quote artifact"
        )
    except ValueError as error:
        raise CampaignConfigError(str(error)) from error

    output_prefix_text = document.get("output_prefix")
    if not isinstance(output_prefix_text, str) or not output_prefix_text:
        raise CampaignConfigError("output_prefix must be a nonempty workspace-relative path")
    output_prefix = resolve_under_root(output_prefix_text, label="campaign output prefix")
    return CampaignConfig(
        document=document,
        path=resolved,
        sha256=sha256(resolved),
        tour=tour,
        raw_years=tuple(int(year) for year in plan["raw_years"]),
        target_years=targets,
        producer_plan_path=producer_plan_path,
        producer_plan_sha256=producer_plan_digest,
        producer_plan=producer_plan,
        producer_completion_path=producer_completion_path,
        producer_completion_sha256=producer_completion_digest,
        producer_completion=producer_completion,
        input_manifest_path=input_path,
        input_manifest_sha256=input_digest,
        raw_quotes_path=raw_quotes_path,
        raw_quotes_sha256=raw_quotes_digest,
        output_prefix=output_prefix,
    )


def config_receipt(config: CampaignConfig) -> dict[str, Any]:
    receipt = {
        "campaign_id": config.document["campaign_id"],
        "config_path": relative_to_root(config.path),
        "config_sha256": config.sha256,
        "design": config.document["design"],
        "code": config.document["code"],
        "producer_plan": {
            "path": relative_to_root(config.producer_plan_path),
            "sha256": config.producer_plan_sha256,
        },
        "producer_completion": {
            "path": relative_to_root(config.producer_completion_path),
            "sha256": config.producer_completion_sha256,
        },
        "input_manifest": {
            "path": relative_to_root(config.input_manifest_path),
            "sha256": config.input_manifest_sha256,
        },
        "raw_quotes": {
            "path": relative_to_root(config.raw_quotes_path),
            "sha256": config.raw_quotes_sha256,
        },
    }
    if "independent_review" in config.document:
        receipt["independent_review"] = config.document["independent_review"]
    if "consumer_code_authorization" in config.document:
        receipt["consumer_code_authorization"] = config.document["consumer_code_authorization"]
        receipt["consumer_source_commit"] = config.document["consumer_source_commit"]
    return receipt
