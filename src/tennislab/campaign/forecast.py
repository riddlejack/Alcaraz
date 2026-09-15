"""Forecast-only S0--S3 combination with past-fold reads and score commitments."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.campaign.artifacts import CampaignInputs, load_inputs
from tennislab.campaign.contracts import CampaignConfig, config_receipt
from tennislab.campaign.members import MEMBER_IDS, RF_MEMBER_IDS
from tennislab.campaign.stack import (
    StackError,
    apply_logit_stack,
    fit_logit_stack,
    fixed_probability_blend,
    pooled_result_elo,
)
from tennislab.campaign.stages import (
    FORECAST_ANCHOR_SCHEMA,
    FORECAST_COMPLETION_SCHEMA,
    forecast_inventory_contract,
    inventory_sha256,
    typed_artifact,
)
from tennislab.chain.common import atomic_csv, atomic_json, canonical_hash_nonempty, sha256
from tennislab.chain.labels import LabelHistory
from tennislab.models import numerical as num
from tennislab.models import pipeline

FORECAST_COLUMNS = ("season", "match_id", "tourney_id", "S0", "S1", "S2", "S3")


class CampaignForecastError(StackError):
    """A forecast input, past-only decision, or emitted artifact failed closed."""


def _probabilities(
    inputs: CampaignInputs, year: int, member_id: str, keys: Sequence[tuple[str, str]]
) -> list[float]:
    artifact = inputs.raw_members[(year, member_id)]
    requested = tuple(keys)
    selected = set(requested)
    if tuple(key for key in artifact.keys if key in selected) != requested:
        raise CampaignForecastError(f"raw membership drift for {year}/{member_id}")
    return [artifact.probabilities[key] for key in requested]


def raw_member_matrix(
    inputs: CampaignInputs, year: int, keys: Sequence[tuple[str, str]]
) -> np.ndarray:
    return np.column_stack(
        [_probabilities(inputs, year, member_id, keys) for member_id in MEMBER_IDS]
    ).astype(np.float64, copy=False)


def _check_result_elo_member(
    inputs: CampaignInputs, year: int, keys: Sequence[tuple[str, str]]
) -> None:
    overall = [float(inputs.metadata[key]["elo_overall_logit"]) for key in keys]
    surface = [float(inputs.metadata[key]["elo_surface_logit"]) for key in keys]
    derived = pooled_result_elo(overall, surface)
    recorded = np.asarray(_probabilities(inputs, year, "result_elo", keys), dtype=np.float64)
    if not np.array_equal(derived, recorded):
        max_error = float(np.max(np.abs(derived - recorded)))
        raise CampaignForecastError(
            f"raw result Elo member differs from probability pooling in {year}: {max_error}"
        )


def _labels_for_years(
    config: CampaignConfig,
    inputs: CampaignInputs,
    outer_year: int,
    years: Sequence[int],
) -> tuple[dict[int, list[int]], list[dict[str, Any]]]:
    selected_by_year = inputs.selection_keys[outer_year]
    keys = tuple(key for year in years for key in selected_by_year[year])
    history = LabelHistory(
        inputs.labels_binding.path,
        inputs.labels_binding.sha256,
        purpose="past_selection_calibration",
        year_ceiling=outer_year - 1,
        fold_outer_year=outer_year,
    )
    selected = history.selected(keys, inputs.metadata)
    return (
        {year: [selected.values[key] for key in selected_by_year[year]] for year in years},
        history.reads,
    )


def _s2_fit(
    inputs: CampaignInputs,
    outer_year: int,
    years: Sequence[int],
    labels_by_year: Mapping[int, Sequence[int]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    trials: dict[str, dict[str, Any]] = {}
    for member_id in RF_MEMBER_IDS:
        probabilities = {
            year: [
                inputs.raw_members[(year, member_id)].probabilities[key]
                for key in inputs.selection_keys[outer_year][year]
            ]
            for year in years
        }
        trial = pipeline.fit_nonnegative_slope(probabilities, labels_by_year, years)
        trial["candidate_id"] = member_id
        trial["prediction_sources"] = {
            str(year): {
                "prediction_sha256": inputs.raw_members[(year, member_id)].binding.sha256,
                "selection_rows": len(inputs.selection_keys[outer_year][year]),
                "selection_membership_sha256": num.key_hash(
                    inputs.selection_keys[outer_year][year]
                ),
            }
            for year in years
        }
        trials[member_id] = trial
    selected = pipeline.select_calibrated_candidate(trials, RF_MEMBER_IDS)
    if selected.get("status") != "complete":
        failure = {
            "status": selected.get("status"),
            "candidate_trials": {
                candidate: pipeline.public_fit(trial) for candidate, trial in trials.items()
            },
            "selection": pipeline.public_selection(selected),
        }
        raise CampaignForecastError(f"S2 selection failed: {json.dumps(failure, sort_keys=True)}")
    return selected, trials


def compute_fold(
    config: CampaignConfig, inputs: CampaignInputs, outer_year: int
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Return forecasts, the public decision receipt, and committed private criteria."""
    years = tuple(range(outer_year - 3, outer_year))
    if any(year not in inputs.cohort_keys for year in years):
        raise CampaignForecastError(f"S2/S3 history is incomplete for {outer_year}")
    for year in (*years, outer_year):
        _check_result_elo_member(inputs, year, inputs.cohort_keys[year])
    labels_by_year, access_receipts = _labels_for_years(config, inputs, outer_year, years)

    selected, trials = _s2_fit(inputs, outer_year, years, labels_by_year)
    stack_probabilities = {
        year: raw_member_matrix(inputs, year, inputs.selection_keys[outer_year][year])
        for year in years
    }
    stack = fit_logit_stack(stack_probabilities, labels_by_year, years)
    if stack.status != "complete" or stack.coefficients is None:
        raise CampaignForecastError(
            f"S3 fit failed: {json.dumps(stack.public_receipt(), sort_keys=True)}"
        )

    target_keys = inputs.cohort_keys[outer_year]
    incumbent = inputs.incumbent[outer_year]
    if incumbent.keys != target_keys:
        raise CampaignForecastError(f"S0 membership drift in {outer_year}")
    s0 = np.asarray([incumbent.probabilities[key] for key in target_keys], dtype=np.float64)
    overall = [float(inputs.metadata[key]["elo_overall_logit"]) for key in target_keys]
    surface = [float(inputs.metadata[key]["elo_surface_logit"]) for key in target_keys]
    s1 = fixed_probability_blend(s0, overall, surface)
    selected_rf = str(selected["selected_candidate_id"])
    raw_rf = _probabilities(inputs, outer_year, selected_rf, target_keys)
    s2 = pipeline.apply_slope(raw_rf, float(selected["selected_slope"]))
    s3 = apply_logit_stack(raw_member_matrix(inputs, outer_year, target_keys), stack.coefficients)

    rows = [
        {
            "season": key[0],
            "match_id": key[1],
            "tourney_id": inputs.metadata[key]["tourney_id"],
            "S0": float(s0[index]),
            "S1": float(s1[index]),
            "S2": float(s2[index]),
            "S3": float(s3[index]),
        }
        for index, key in enumerate(target_keys)
    ]
    selection_keys = tuple(key for year in years for key in inputs.selection_keys[outer_year][year])
    s2_criterion = pipeline.criterion_document(trials, selected)
    private = {"s2": s2_criterion, "s3": stack.criterion_document()}
    decision = {
        "outer_year": outer_year,
        "selection_years": list(years),
        "selection_rows": len(selection_keys),
        "selection_membership_sha256": num.key_hash(selection_keys),
        "selection_cutoff_inclusive": f"{outer_year - 1:04d}-12-30",
        "outcome_access_receipts": access_receipts,
        "S2": {
            "candidate_trials": {
                candidate: pipeline.public_fit(trial) for candidate, trial in trials.items()
            },
            "selection": pipeline.public_selection(selected),
            "criterion_commitment_sha256": canonical_hash_nonempty(
                s2_criterion, label="S2 criterion"
            ),
            "selected_prediction_is_not_an_S3_member": True,
        },
        "S3": stack.public_receipt(),
        "target_rows": len(target_keys),
        "target_membership_sha256": num.key_hash(target_keys),
        "incumbent_prediction_sha256": incumbent.binding.sha256,
        "raw_member_prediction_sha256": {
            member_id: inputs.raw_members[(outer_year, member_id)].binding.sha256
            for member_id in MEMBER_IDS
        },
        "target_outcomes_read_or_scored": False,
        "scores_and_objectives_deferred_to_report": True,
    }
    return rows, decision, private


def run_forecast(config: CampaignConfig, output_root: Path) -> dict[str, Any]:
    inputs = load_inputs(config)
    stage = output_root / "forecast"
    if stage.exists():
        raise CampaignForecastError(f"forecast stage already exists: {stage}")
    stage.mkdir(parents=True)
    artifacts: list[dict[str, Any]] = []
    private_commitments: dict[str, Any] = {}
    exposure_receipts: list[dict[str, Any]] = []
    for year in config.target_years:
        try:
            rows, decision, private = compute_fold(config, inputs, year)
        except Exception as error:
            atomic_json(
                stage / "failures" / f"{year}.json",
                {
                    "status": "failed",
                    "outer_year": year,
                    "error": {"type": type(error).__name__, "message": str(error)},
                    "preserved_for_review": True,
                    "scientific_candidate_substitution_permitted": False,
                },
            )
            raise
        prediction_path = stage / "forecasts" / f"{year}.csv"
        prediction_hash = atomic_csv(prediction_path, FORECAST_COLUMNS, rows)
        decision_path = stage / "decisions" / f"{year}.json"
        decision_hash = atomic_json(decision_path, decision)
        del prediction_hash, decision_hash
        artifacts.extend(
            [
                typed_artifact(
                    prediction_path,
                    schema="campaign_forecast_rows/v1",
                    logical_key={"role": "forecast_rows", "outer_year": year},
                    root=output_root,
                ),
                typed_artifact(
                    decision_path,
                    schema="campaign_fold_decision/v1",
                    logical_key={"role": "fold_decision", "outer_year": year},
                    root=output_root,
                ),
            ]
        )
        private_commitments[str(year)] = {
            "S2": canonical_hash_nonempty(private["s2"], label="S2 criterion"),
            "S3": canonical_hash_nonempty(private["s3"], label="S3 criterion"),
        }
        exposure_receipts.extend(decision["outcome_access_receipts"])
    exposure = {
        "stage": "forecast",
        "physical_label_file_access": True,
        "returned_outcomes": "three_past_years_per_outer_fold_only",
        "receipts": exposure_receipts,
        "target_outcomes_returned_or_scored": False,
        "criterion_values_emitted": False,
    }
    exposure_path = stage / "exposure.json"
    exposure_hash = atomic_json(exposure_path, exposure)
    artifacts.append(
        typed_artifact(
            exposure_path,
            schema="campaign_forecast_exposure/v1",
            logical_key={"role": "exposure"},
            root=output_root,
        )
    )
    expected_inventory = forecast_inventory_contract(config.target_years)
    observed_inventory = [
        {
            "path": item["path"],
            "schema": item["schema"],
            "logical_key": item["logical_key"],
            "media_type": item["media_type"],
        }
        for item in artifacts
    ]
    if observed_inventory != expected_inventory:
        raise CampaignForecastError("forecast inventory differs from fixed target-year contract")
    manifest = {
        "schema": FORECAST_COMPLETION_SCHEMA,
        "status": "complete",
        "stage": "forecast",
        **config_receipt(config),
        "tour": config.tour,
        "target_years": list(config.target_years),
        "artifacts": artifacts,
        "inventory_sha256": inventory_sha256(artifacts),
        "attempt_id": config.document["attempt_id"],
        "private_criterion_commitments": private_commitments,
        "raw_member_order": list(MEMBER_IDS),
        "target_outcomes_read_or_scored": False,
        "pre_barrier_performance_values_emitted": False,
        "exposure_receipt_sha256": exposure_hash,
    }
    manifest_path = stage / "forecast_manifest.json"
    atomic_json(manifest_path, manifest)
    manifest_digest = sha256(manifest_path)
    anchor_path = output_root / "attempts" / f"forecast_{config.document['attempt_id']}.json"
    if anchor_path.exists():
        raise CampaignForecastError(f"forecast attempt anchor already exists: {anchor_path}")
    anchor = {
        "schema": FORECAST_ANCHOR_SCHEMA,
        "stage": "forecast_attempt_anchor",
        "status": "complete",
        "attempt_id": config.document["attempt_id"],
        "config_sha256": config.sha256,
        "producer_plan_sha256": config.producer_plan_sha256,
        "producer_completion_sha256": config.producer_completion_sha256,
        "forecast_completion": {
            "path": manifest_path.relative_to(output_root).as_posix(),
            "sha256": manifest_digest,
        },
        "custody_limit": "local immutable-attempt convention; independent custody is external",
    }
    atomic_json(anchor_path, anchor)
    manifest["forecast_manifest_sha256"] = manifest_digest
    manifest["forecast_attempt_anchor_sha256"] = sha256(anchor_path)
    return manifest


def read_forecasts(path: Path, year: int) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FORECAST_COLUMNS:
            raise CampaignForecastError(f"forecast header drift: {path}")
        rows = [dict(row) for row in reader]
    if not rows or any(row["season"] != str(year) for row in rows):
        raise CampaignForecastError(f"forecast season drift: {path}")
    return rows


def read_decision(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise CampaignForecastError(f"decision is not an object: {path}")
    return dict(value)
