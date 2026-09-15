"""Deterministic, zero-fit builder for the repaired public campaign rehearsal."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.campaign.artifacts import (
    DATED_KEY_COLUMNS,
    KEY_COLUMNS,
    METADATA_COLUMNS,
    PREDICTION_COLUMNS,
    RAW_QUOTE_COLUMNS,
)
from tennislab.campaign.contracts import (
    TARGET_YEARS,
    campaign_settings,
    code_bindings,
    raw_years_for,
)
from tennislab.campaign.members import MEMBER_IDS, member_specs, resolved_estimator_params
from tennislab.campaign.stack import pooled_result_elo
from tennislab.campaign.stages import (
    BARRIER_COMPLETION_SCHEMA,
    CONSUMER_CONFIG_SCHEMA,
    FORECAST_COMPLETION_SCHEMA,
    INPUT_MANIFEST_SCHEMA,
    PRODUCER_COMPLETION_SCHEMA,
    PRODUCER_PLAN_SCHEMA,
    QUALIFICATION_SCHEMA,
    RAW_MEMBER_SCHEMA,
    REPORT_COMPLETION_SCHEMA,
    forecast_inventory_contract,
    inventory_sha256,
    report_inventory_contract,
    typed_artifact,
)
from tennislab.chain.common import (
    atomic_csv,
    atomic_json,
    relative_to_root,
    resolve_output_under_root,
    sha256,
)
from tennislab.chain.labels import LABEL_COLUMNS
from tennislab.dynamics.calibrate import CAMPAIGN_FIT_DISCLOSURE_POLICY
from tennislab.models import numerical as num
from tennislab.models import pipeline


class SyntheticCampaignError(ValueError):
    """The deterministic rehearsal workspace already exists or could not be bound."""


def _binding(path: Path, keys: tuple[tuple[str, str], ...] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": relative_to_root(path), "sha256": sha256(path)}
    if keys is not None:
        result.update({"rows": len(keys), "membership_sha256": num.key_hash(keys)})
    return result


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _params(member_id: str) -> dict[str, Any] | None:
    if member_id == "result_elo":
        return None
    if member_id.startswith("rf_"):
        result = dict(pipeline.RF_PARAMS)
        result["min_samples_leaf"] = dict(pipeline.RF_CANDIDATES)[member_id]
        return result
    if member_id.startswith("hgb_"):
        result = dict(pipeline.HGB_PARAMS)
        leaves, depth = {item[0]: item[1:] for item in pipeline.HGB_CANDIDATES}[member_id]
        result.update({"max_leaf_nodes": leaves, "max_depth": depth})
        return result
    result = dict(pipeline.RIDGE_PARAMS)
    result["C"] = dict(pipeline.RIDGE_CANDIDATES)[member_id]
    return result


def _model_config(
    *,
    member_id: str,
    learner: str,
    feature_bundle: str,
    numeric_or_signed: list[str],
    symmetric_context: list[str],
) -> dict[str, Any]:
    prefix = "random_forest" if learner == "random_forest" else learner
    common = {
        "config_id": f"{prefix}__{feature_bundle}__{member_id}",
        "estimator_params": _params(member_id),
    }
    if learner == "ridge":
        return {
            **common,
            "family": "joint_logistic",
            "numeric_columns": numeric_or_signed,
        }
    return {
        **common,
        "family": "hist_gradient_boosting" if learner == "hgb" else "random_forest",
        "signed_numeric_columns": numeric_or_signed,
        "context_columns": symmetric_context,
    }


def _expected_artifact(
    path: Path, *, schema: str, logical_key: dict[str, Any], media_type: str
) -> dict[str, Any]:
    return {
        "path": relative_to_root(path),
        "schema": schema,
        "logical_key": logical_key,
        "media_type": media_type,
    }


def prepare_rehearsal(
    root: Path,
    design_path: Path,
    *,
    tour: str = "ATP",
    dec31_year: int | None = None,
    malformed_quote: bool = False,
) -> Path:
    """Write a typed producer-to-report synthetic graph and return its config path."""
    root = resolve_output_under_root(root, label="campaign rehearsal root")
    if root.exists():
        raise SyntheticCampaignError(f"rehearsal root already exists: {root}")
    root.mkdir(parents=True)
    normalized_tour = str(tour).upper()
    if normalized_tour not in TARGET_YEARS:
        raise SyntheticCampaignError(f"unsupported rehearsal tour: {tour!r}")
    target_years = TARGET_YEARS[normalized_tour]
    raw_years = raw_years_for(target_years)
    settings = campaign_settings(normalized_tour, target_years)
    inputs_dir = root / "inputs"
    producer_root = inputs_dir / "producer"
    design_path = resolve_output_under_root(design_path, label="campaign design")

    rows_by_year: dict[int, list[dict[str, Any]]] = {}
    labels: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    for year in raw_years:
        year_rows: list[dict[str, Any]] = []
        for index in range(8):
            match_id = f"{year}-m{index:02d}"
            date = f"{year}-0{1 + index // 4}-{3 + index % 4:02d}"
            if year == dec31_year and index == 7:
                date = f"{year}-12-31"
            row = {
                "season": str(year),
                "match_id": match_id,
                "calendar_year": str(year),
                "source_season": str(year),
                "match_date": date,
                "eligible_through_date": f"{year}-0{1 + index // 4}-{1 + index % 4:02d}",
                "tourney_id": f"{year}-E{index // 4 + 1}",
                "identity_tier": "primary",
                "primary_target": "1",
                "source_field_agreement": "synthetic",
                "elo_overall_logit": format((index - 3.5) * 0.19, ".17g"),
                "elo_surface_logit": format((3.5 - index) * 0.07, ".17g"),
            }
            year_rows.append(row)
            metadata_rows.append(row)
            labels.append(
                {
                    "match_id": match_id,
                    "calendar_year": str(year),
                    "source_season": str(year),
                    "match_date": date,
                    "tourney_id": row["tourney_id"],
                    "identity_tier": "primary",
                    "primary_target": "1",
                    "a_won": str((index + year) % 2),
                    "status": "Completed",
                    "source_field_agreement": "synthetic",
                }
            )
        rows_by_year[year] = year_rows

    metadata_path = inputs_dir / "metadata.csv"
    labels_path = inputs_dir / "labels.csv"
    atomic_csv(metadata_path, METADATA_COLUMNS, metadata_rows)
    atomic_csv(labels_path, LABEL_COLUMNS, labels)
    provenance_path = inputs_dir / "synthetic_provenance.json"
    atomic_json(
        provenance_path,
        {
            "status": "complete",
            "scope": "synthetic arithmetic and public-interface rehearsal only",
            "real_tennis_rows": 0,
            "candidate_models_fitted": 0,
            "scientific_scores": False,
        },
    )
    provenance_binding = _binding(provenance_path)

    cohorts: list[dict[str, Any]] = []
    selection_cohorts: list[dict[str, Any]] = []
    priced_cohorts: list[dict[str, Any]] = []
    incumbent: list[dict[str, Any]] = []
    for year in raw_years:
        keys = tuple((row["season"], row["match_id"]) for row in rows_by_year[year])
        cohort_path = inputs_dir / "cohorts" / f"{year}.csv"
        atomic_csv(
            cohort_path, KEY_COLUMNS, [dict(zip(KEY_COLUMNS, key, strict=True)) for key in keys]
        )
        cohorts.append({"year": year, **_binding(cohort_path, keys)})
        if year in target_years:
            overall = [float(row["elo_overall_logit"]) for row in rows_by_year[year]]
            incumbent_path = inputs_dir / "incumbent" / f"{year}.csv"
            atomic_csv(
                incumbent_path,
                PREDICTION_COLUMNS,
                [
                    {
                        "season": key[0],
                        "match_id": key[1],
                        "p_a_wins": float(_sigmoid(0.87 * value)),
                    }
                    for key, value in zip(keys, overall, strict=True)
                ],
            )
            incumbent.append(
                {
                    "year": year,
                    "procedure": "unchanged_incumbent_selected_calibrated_hgb",
                    "prediction": _binding(incumbent_path, keys),
                }
            )
            priced = keys[1:]
            priced_path = inputs_dir / "priced_cohorts" / f"{year}.csv"
            atomic_csv(
                priced_path,
                KEY_COLUMNS,
                [dict(zip(KEY_COLUMNS, key, strict=True)) for key in priced],
            )
            priced_cohorts.append({"year": year, **_binding(priced_path, priced)})
    for outer_year in target_years:
        for source_year in range(outer_year - 3, outer_year):
            selected = tuple(
                (row["season"], row["match_id"])
                for row in rows_by_year[source_year]
                if row["match_date"] <= f"{source_year}-12-30"
            )
            path = inputs_dir / "selection_cohorts" / str(outer_year) / f"{source_year}.csv"
            atomic_csv(
                path, KEY_COLUMNS, [dict(zip(KEY_COLUMNS, key, strict=True)) for key in selected]
            )
            selection_cohorts.append(
                {"outer_year": outer_year, "source_year": source_year, **_binding(path, selected)}
            )

    quote_rows: list[dict[str, Any]] = []
    for year in target_years:
        for index, row in enumerate(rows_by_year[year]):
            probability = _sigmoid((index - 3.5) * 0.16)
            valid = index > 0
            quote_rows.append(
                {
                    "season": row["season"],
                    "match_id": row["match_id"],
                    "decimal_a": (
                        "NOT_A_QUOTE"
                        if malformed_quote and year == target_years[0] and index == 1
                        else format(1.0 / probability, ".17g")
                        if valid
                        else ""
                    ),
                    "decimal_b": format(1.0 / (1.0 - probability), ".17g") if valid else "",
                    "valid": "true" if valid else "false",
                    "market_source_path": relative_to_root(provenance_path) if valid else "",
                    "market_source_row": index + 1 if valid else "",
                    "market_source_sha256": provenance_binding["sha256"] if valid else "",
                }
            )
    raw_quotes_path = inputs_dir / "raw_quotes.csv"
    atomic_csv(raw_quotes_path, RAW_QUOTE_COLUMNS, quote_rows)

    qualification = {
        "schema": QUALIFICATION_SCHEMA,
        "stage": "population_qualification",
        "status": "complete",
        "custody_scope": "synthetic_rehearsal",
        "tour": normalized_tour,
        "independent_review_anchor": {
            "status": "not_applicable_synthetic",
            "sha256": sha256(design_path),
        },
        "metadata": _binding(metadata_path),
        "raw_quotes": _binding(raw_quotes_path),
        "cohorts": cohorts,
        "selection_cohorts": selection_cohorts,
        "priced_cohorts": priced_cohorts,
        "incumbent": incumbent,
        "limit": "local synthetic qualification proves consistency, not independent custody",
    }
    qualification_path = inputs_dir / "qualification.json"
    atomic_json(qualification_path, qualification)

    producer_specs: list[dict[str, Any]] = []
    year_contracts: list[dict[str, Any]] = []
    specs = {spec.member_id: spec for spec in member_specs(normalized_tour)}
    expected_artifacts: list[dict[str, Any]] = []
    for member_id in MEMBER_IDS:
        spec = specs[member_id]
        numeric_or_signed = [] if member_id == "result_elo" else ["elo_overall_logit"]
        symmetric_context = ["context_indoor"] if spec.learner in {"hgb", "random_forest"} else []
        model_config = (
            None
            if member_id == "result_elo"
            else _model_config(
                member_id=member_id,
                learner=str(spec.learner),
                feature_bundle=spec.feature_bundle,
                numeric_or_signed=numeric_or_signed,
                symmetric_context=symmetric_context,
            )
        )
        producer_specs.append(
            {
                "member_id": member_id,
                "kind": spec.kind,
                "learner": spec.learner,
                "candidate_id": spec.candidate_id,
                "feature_bundle": spec.feature_bundle,
                "ordered_feature_columns": {
                    "numeric_or_signed": numeric_or_signed,
                    "symmetric_context": symmetric_context,
                },
                "estimator_config": model_config,
                "resolved_estimator_params": (
                    None if model_config is None else resolved_estimator_params(model_config)
                ),
            }
        )
    for year in raw_years:
        fit_start_year = max(2011, year - 5)
        fit_start = f"{fit_start_year}-01-01"
        fit_through = f"{year - 1}-12-30"
        training_rows = [
            {
                "season": str(source_year),
                "match_id": f"train-{source_year}-{index}",
                "match_date": f"{source_year}-{'01-10' if index == 0 else '06-10'}",
            }
            for source_year in range(fit_start_year, year)
            for index in range(2)
        ]
        training_keys = tuple((row["season"], row["match_id"]) for row in training_rows)
        prediction_keys = tuple((row["season"], row["match_id"]) for row in rows_by_year[year])
        training_path = producer_root / "training" / f"{year}.csv"
        atomic_csv(training_path, DATED_KEY_COLUMNS, training_rows)
        state_path = producer_root / "state" / f"{year}.json"
        atomic_json(
            state_path,
            {"schema": "campaign_state/v1", "status": "complete", "horizon_end": fit_through},
        )
        state_receipts = [
            {
                "kind": "synthetic_state",
                "horizon_end": fit_through,
                "artifact": _binding(state_path),
            }
        ]
        offset_receipts: list[dict[str, Any]] = []
        expected_artifacts.extend(
            [
                _expected_artifact(
                    training_path,
                    schema="campaign_training_membership/v1",
                    logical_key={"role": "training_membership", "prediction_year": year},
                    media_type="text/csv",
                ),
                _expected_artifact(
                    state_path,
                    schema="campaign_state/v1",
                    logical_key={"role": "state", "prediction_year": year},
                    media_type="application/json",
                ),
            ]
        )
        if normalized_tour == "ATP":
            offset_path = producer_root / "offset" / f"{year}.json"
            atomic_json(
                offset_path,
                {"schema": "campaign_offset/v1", "status": "complete", "horizon_end": fit_through},
            )
            offset_receipts = [
                {
                    "kind": "synthetic_tier_offset",
                    "horizon_end": fit_through,
                    "artifact": _binding(offset_path),
                }
            ]
            expected_artifacts.append(
                _expected_artifact(
                    offset_path,
                    schema="campaign_offset/v1",
                    logical_key={"role": "offset", "prediction_year": year},
                    media_type="application/json",
                )
            )
        prediction_feature_bindings: dict[str, dict[str, Any]] = {}
        for member in producer_specs[1:]:
            member_id = str(member["member_id"])
            ordered = member["ordered_feature_columns"]
            columns = [*ordered["numeric_or_signed"], *ordered["symmetric_context"]]
            feature_path = producer_root / "prediction_features" / str(year) / f"{member_id}.csv"
            feature_rows = [
                {
                    "season": row["season"],
                    "match_id": row["match_id"],
                    **{column: (row[column] if column in row else "0") for column in columns},
                }
                for row in rows_by_year[year]
            ]
            atomic_csv(feature_path, (*KEY_COLUMNS, *columns), feature_rows)
            prediction_feature_bindings[member_id] = _binding(feature_path, prediction_keys)
            expected_artifacts.append(
                _expected_artifact(
                    feature_path,
                    schema="campaign_prediction_features/v1",
                    logical_key={
                        "role": "prediction_features",
                        "prediction_year": year,
                        "member_id": member_id,
                    },
                    media_type="text/csv",
                )
            )
        year_contracts.append(
            {
                "prediction_year": year,
                "fit_start": fit_start,
                "fit_through": fit_through,
                "training_membership": _binding(training_path, training_keys),
                "raw_prediction_membership": next(item for item in cohorts if item["year"] == year),
                "prediction_features": prediction_feature_bindings,
                "state_receipts": state_receipts,
                "offset_receipts": offset_receipts,
            }
        )
        for member_id in MEMBER_IDS:
            expected_artifacts.extend(
                [
                    _expected_artifact(
                        producer_root / "raw" / str(year) / f"{member_id}.csv",
                        schema="campaign_raw_prediction/v1",
                        logical_key={
                            "role": "raw_prediction",
                            "prediction_year": year,
                            "member_id": member_id,
                        },
                        media_type="text/csv",
                    ),
                    _expected_artifact(
                        producer_root / "records" / str(year) / f"{member_id}.json",
                        schema=RAW_MEMBER_SCHEMA,
                        logical_key={
                            "role": "raw_member_completion",
                            "prediction_year": year,
                            "member_id": member_id,
                        },
                        media_type="application/json",
                    ),
                ]
            )

    native_config_path = producer_root / "native_sr03" / "config.json"
    atomic_json(
        native_config_path,
        {
            "experiment_id": f"E-V1-{normalized_tour}-SYNTHETIC-NO-FIT-SR03",
            "calibration": {"fit_disclosure_policy": CAMPAIGN_FIT_DISCLOSURE_POLICY},
            "expected_records": 0,
            "synthetic_no_fit": True,
        },
    )
    native_paths = {
        "config": native_config_path,
        "fits": producer_root / "native_sr03" / "fits.json",
        "events": producer_root / "native_sr03" / "fit_events.jsonl",
        "run_manifest": producer_root / "native_sr03" / "run_manifest.json",
    }
    expected_artifacts.extend(
        [
            _expected_artifact(
                native_config_path,
                schema="campaign_native_sr03_config/v1",
                logical_key={"role": "native_sr03_config"},
                media_type="application/json",
            ),
            _expected_artifact(
                native_paths["fits"],
                schema="campaign_native_sr03_fits/v1",
                logical_key={"role": "native_sr03_fits"},
                media_type="application/json",
            ),
            _expected_artifact(
                native_paths["events"],
                schema="campaign_native_sr03_events/v1",
                logical_key={"role": "native_sr03_events"},
                media_type="application/x-ndjson",
            ),
            _expected_artifact(
                native_paths["run_manifest"],
                schema="campaign_native_sr03_completion/v1",
                logical_key={"role": "native_sr03_completion"},
                media_type="application/json",
            ),
        ]
    )
    plan = {
        "schema": PRODUCER_PLAN_SCHEMA,
        "stage": "producer_plan",
        "status": "complete",
        "custody_scope": "synthetic_rehearsal",
        "independent_review_status": "not_applicable_synthetic",
        "tour": normalized_tour,
        "raw_years": list(raw_years),
        "target_years": list(target_years),
        "producer_root": relative_to_root(producer_root),
        "review_anchor": {
            "fixed_commit": "34fbf584760b65837c288d36e027dd0491b0ada6",
            "repair_contract_sha256": sha256(design_path),
        },
        "settings": settings,
        "code": code_bindings(),
        "qualification": _binding(qualification_path),
        "member_contracts": producer_specs,
        "year_contracts": year_contracts,
        "native_sr03": {
            "policy": CAMPAIGN_FIT_DISCLOSURE_POLICY,
            "config": _binding(native_config_path),
            "fits_path": relative_to_root(native_paths["fits"]),
            "events_path": relative_to_root(native_paths["events"]),
            "run_manifest_path": relative_to_root(native_paths["run_manifest"]),
            "expected_records": 0,
        },
        "expected_artifacts": expected_artifacts,
        "real_fit_authorized": False,
    }
    plan_path = inputs_dir / "producer_plan.json"
    atomic_json(plan_path, plan)
    plan_sha256 = sha256(plan_path)

    raw_records: list[dict[str, Any]] = []
    plan_members = {item["member_id"]: item for item in producer_specs}
    plan_years = {item["prediction_year"]: item for item in year_contracts}
    for year in raw_years:
        keys = tuple((row["season"], row["match_id"]) for row in rows_by_year[year])
        overall = [float(row["elo_overall_logit"]) for row in rows_by_year[year]]
        surface = [float(row["elo_surface_logit"]) for row in rows_by_year[year]]
        member_values = {
            "result_elo": pooled_result_elo(overall, surface),
            "hgb_leaf07_depth3": np.asarray([_sigmoid(0.82 * value) for value in overall]),
            "hgb_leaf15_depth4": np.asarray([_sigmoid(0.91 * value) for value in overall]),
            "ridge_c001": np.asarray([_sigmoid(0.55 * value) for value in overall]),
            "ridge_c01": np.asarray([_sigmoid(0.70 * value) for value in overall]),
            "ridge_c1": np.asarray([_sigmoid(0.98 * value) for value in overall]),
            "rf_leaf50": np.asarray([_sigmoid(0.76 * value + 0.02) for value in overall]),
            "rf_leaf100": np.asarray([_sigmoid(0.64 * value - 0.01) for value in overall]),
        }
        for member_id in MEMBER_IDS:
            prediction_path = producer_root / "raw" / str(year) / f"{member_id}.csv"
            atomic_csv(
                prediction_path,
                PREDICTION_COLUMNS,
                [
                    {"season": key[0], "match_id": key[1], "p_a_wins": float(probability)}
                    for key, probability in zip(keys, member_values[member_id], strict=True)
                ],
            )
            prediction = _binding(prediction_path, keys)
            member = plan_members[member_id]
            year_contract = plan_years[year]
            origin = (
                "deterministic_state" if member_id == "result_elo" else "synthetic_fixture_no_fit"
            )
            producer_record = {
                "schema": RAW_MEMBER_SCHEMA,
                "stage": "raw_member",
                "status": "complete",
                "custody_scope": "synthetic_rehearsal",
                "producer_plan_sha256": plan_sha256,
                "tour": normalized_tour,
                "prediction_year": year,
                "member_id": member_id,
                "kind": member["kind"],
                "learner": member["learner"],
                "candidate_id": member["candidate_id"],
                "feature_bundle": member["feature_bundle"],
                "origin": origin,
                "model_fit_executed": False,
                "fit_window": {
                    "start": year_contract["fit_start"],
                    "through": year_contract["fit_through"],
                },
                "training_membership": (
                    None if member_id == "result_elo" else year_contract["training_membership"]
                ),
                "prediction_features": (
                    None
                    if member_id == "result_elo"
                    else year_contract["prediction_features"][member_id]
                ),
                "ordered_feature_columns": member["ordered_feature_columns"],
                "resolved_estimator_params": member["resolved_estimator_params"],
                "estimator_config_sha256": (
                    None
                    if member["estimator_config"] is None
                    else num.sha256_json(member["estimator_config"])
                ),
                "state_receipts": year_contract["state_receipts"],
                "offset_receipts": (
                    year_contract["offset_receipts"]
                    if member["feature_bundle"] == "full_tier"
                    else []
                ),
                "raw_unselected_uncalibrated": True,
                "same_year_selection_or_slope_used": False,
                "same_cutoff_batched_history": True,
                "selection_years": [],
                "calibration_years": [],
                "prediction": prediction,
                "prediction_closure": {
                    "method": (
                        "deterministic_state_recompute"
                        if member_id == "result_elo"
                        else "deterministic_fixture_generation"
                    ),
                    "recomputed_prediction_sha256": prediction["sha256"],
                },
                "limit": "synthetic raw probabilities; no estimator fit and no scientific evidence",
            }
            producer_record_path = producer_root / "records" / str(year) / f"{member_id}.json"
            atomic_json(producer_record_path, producer_record)
            raw_records.append(
                {
                    "year": year,
                    "member_id": member_id,
                    "producer_record": _binding(producer_record_path),
                    "prediction": prediction,
                }
            )

    atomic_json(native_paths["fits"], [])
    native_paths["events"].write_text("\n", encoding="utf-8")
    atomic_json(
        native_paths["run_manifest"],
        {
            "status": "complete",
            "experiment_id": f"E-V1-{normalized_tour}-SYNTHETIC-NO-FIT-SR03",
            "config_sha256": sha256(native_config_path),
            "artifacts": {
                "fits.json": sha256(native_paths["fits"]),
                "fit_events.jsonl": sha256(native_paths["events"]),
            },
            "fits": 0,
            "fit_disclosure": {
                "policy": CAMPAIGN_FIT_DISCLOSURE_POLICY,
                "objective_values_written_prebarrier": False,
                "committed_fit_records": 0,
            },
            "synthetic_no_fit": True,
        },
    )
    expected_by_path = {item["path"]: item for item in expected_artifacts}
    completed_artifacts: list[dict[str, Any]] = []
    for path in sorted(item for item in producer_root.rglob("*") if item.is_file()):
        spec = expected_by_path[relative_to_root(path)]
        completed_artifacts.append(
            typed_artifact(path, schema=spec["schema"], logical_key=spec["logical_key"])
        )
    completion = {
        "schema": PRODUCER_COMPLETION_SCHEMA,
        "stage": "producer_completion",
        "status": "complete",
        "custody_scope": "synthetic_rehearsal",
        "tour": normalized_tour,
        "raw_years": list(raw_years),
        "target_years": list(target_years),
        "producer_root": relative_to_root(producer_root),
        "producer_plan_sha256": plan_sha256,
        "artifacts": completed_artifacts,
        "inventory_sha256": inventory_sha256(completed_artifacts),
        "models_fitted": 0,
        "scores_computed": 0,
    }
    completion_path = inputs_dir / "producer_completion.json"
    atomic_json(completion_path, completion)

    input_manifest = {
        "schema": INPUT_MANIFEST_SCHEMA,
        "stage": "input_manifest",
        "status": "complete",
        "custody_scope": "synthetic_rehearsal",
        "tour": normalized_tour,
        "raw_years": list(raw_years),
        "target_years": list(target_years),
        "producer_plan_sha256": plan_sha256,
        "producer_completion_sha256": sha256(completion_path),
        "qualification": _binding(qualification_path),
        "metadata": _binding(metadata_path),
        "labels": _binding(labels_path),
        "cohorts": cohorts,
        "selection_cohorts": selection_cohorts,
        "priced_cohorts": priced_cohorts,
        "incumbent": incumbent,
        "raw_members": raw_records,
    }
    input_manifest_path = inputs_dir / "input_manifest.json"
    atomic_json(input_manifest_path, input_manifest)

    forecast_inventory = forecast_inventory_contract(target_years)
    report_inventory = report_inventory_contract()
    config = {
        "schema": CONSUMER_CONFIG_SCHEMA,
        "stage": "consumer_config",
        "schema_version": 1,
        "status": "complete",
        "campaign_id": f"E-V1-{normalized_tour}-SYNTHETIC-REHEARSAL",
        "attempt_id": "001",
        "execution_scope": "synthetic_rehearsal",
        "empirical_freeze_status": "not_applicable_synthetic",
        "design": {"path": relative_to_root(design_path), "sha256": sha256(design_path)},
        "code": code_bindings(),
        "settings": settings,
        "producer_plan": _binding(plan_path),
        "producer_completion": _binding(completion_path),
        "input_manifest": _binding(input_manifest_path),
        "raw_quotes": _binding(raw_quotes_path),
        "expected_forecast_inventory": forecast_inventory,
        "expected_report_inventory": report_inventory,
        "expected_barrier_schema": BARRIER_COMPLETION_SCHEMA,
        "expected_forecast_schema": FORECAST_COMPLETION_SCHEMA,
        "expected_report_schema": REPORT_COMPLETION_SCHEMA,
        "output_prefix": relative_to_root(root),
        "scientific_population": f"synthetic_only_not_{normalized_tour}_evidence",
    }
    config_path = root / "config.json"
    atomic_json(config_path, config)
    return config_path
