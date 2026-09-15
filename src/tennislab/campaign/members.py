"""The eight fixed raw members and their exact fit/forecast receipt contract."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.campaign.stages import RAW_MEMBER_SCHEMA
from tennislab.chain.common import (
    atomic_json,
    canonical_hash_nonempty,
    relative_to_root,
    require_nonempty_digest,
    resolve_under_root,
    sha256,
)
from tennislab.models import numerical as num
from tennislab.models import pipeline

MEMBER_IDS = (
    "result_elo",
    "hgb_leaf07_depth3",
    "hgb_leaf15_depth4",
    "ridge_c001",
    "ridge_c01",
    "ridge_c1",
    "rf_leaf50",
    "rf_leaf100",
)
NUMERICAL_MEMBER_IDS = MEMBER_IDS[1:]
RF_MEMBER_IDS = MEMBER_IDS[-2:]


class CampaignMemberError(pipeline.PipelineError):
    """A fixed member, feature allowlist, fit receipt, or raw forecast drifted."""


@dataclass(frozen=True)
class MemberSpec:
    member_id: str
    kind: str
    learner: str | None
    candidate_id: str | None
    feature_bundle: str


def incumbent_bundle(tour: str) -> str:
    normalized = str(tour).upper()
    if normalized == "ATP":
        return "full_tier"
    if normalized == "WTA":
        return "full"
    raise CampaignMemberError(f"unsupported campaign tour: {tour!r}")


def member_specs(tour: str) -> tuple[MemberSpec, ...]:
    tree_bundle = incumbent_bundle(tour)
    return (
        MemberSpec("result_elo", "deterministic_state", None, None, "result_elo"),
        MemberSpec("hgb_leaf07_depth3", "numerical", "hgb", "hgb_leaf07_depth3", tree_bundle),
        MemberSpec("hgb_leaf15_depth4", "numerical", "hgb", "hgb_leaf15_depth4", tree_bundle),
        MemberSpec("ridge_c001", "numerical", "ridge", "ridge_c001", "full"),
        MemberSpec("ridge_c01", "numerical", "ridge", "ridge_c01", "full"),
        MemberSpec("ridge_c1", "numerical", "ridge", "ridge_c1", "full"),
        MemberSpec("rf_leaf50", "numerical", "random_forest", "rf_leaf50", tree_bundle),
        MemberSpec("rf_leaf100", "numerical", "random_forest", "rf_leaf100", tree_bundle),
    )


def _campaign_columns(
    contract: pipeline.FeatureContract, learner: str, block: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    numeric, context = contract.campaign_model_columns(learner, block)
    forbidden = sorted(pipeline.FORBIDDEN_MODEL_COLUMNS.intersection((*numeric, *context)))
    if forbidden:
        raise CampaignMemberError(f"forbidden campaign model columns: {forbidden}")
    if any(
        token in column.lower()
        for column in (*numeric, *context)
        for token in ("pinnacle", "market", "ps_probability", "ps_logit", "ps_missing")
    ):
        raise CampaignMemberError("market-derived column entered the campaign sports allowlist")
    return numeric, context


def numerical_member_config(contract: pipeline.FeatureContract, spec: MemberSpec) -> dict[str, Any]:
    """Return a complete pinned adapter configuration for one numerical member."""
    if spec.kind != "numerical" or spec.learner is None or spec.candidate_id is None:
        raise CampaignMemberError(f"member is not numerical: {spec.member_id}")
    numeric, context = _campaign_columns(contract, spec.learner, spec.feature_bundle)
    if spec.learner == "random_forest":
        return pipeline.random_forest_numerical_config(
            contract, spec.feature_bundle, spec.candidate_id
        )
    if spec.learner == "ridge":
        candidates = dict(pipeline.RIDGE_CANDIDATES)
        if spec.candidate_id not in candidates:
            raise CampaignMemberError(f"unknown ridge candidate: {spec.candidate_id}")
        params = dict(pipeline.RIDGE_PARAMS)
        params["C"] = candidates[spec.candidate_id]
        return {
            "config_id": f"ridge__{spec.feature_bundle}__{spec.candidate_id}",
            "family": "joint_logistic",
            "numeric_columns": list(numeric),
            "estimator_params": params,
        }
    if spec.learner == "hgb":
        candidates = {item[0]: item[1:] for item in pipeline.HGB_CANDIDATES}
        if spec.candidate_id not in candidates:
            raise CampaignMemberError(f"unknown HGB candidate: {spec.candidate_id}")
        leaves, depth = candidates[spec.candidate_id]
        params = dict(pipeline.HGB_PARAMS)
        params.update({"max_leaf_nodes": leaves, "max_depth": depth})
        return {
            "config_id": f"hgb__{spec.feature_bundle}__{spec.candidate_id}",
            "family": "hist_gradient_boosting",
            "signed_numeric_columns": list(numeric),
            "context_columns": list(context),
            "estimator_params": params,
        }
    raise CampaignMemberError(f"unsupported campaign learner: {spec.learner}")


def resolved_estimator_params(model_config: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the full pinned sklearn ``get_params`` view without fitting."""
    family = model_config.get("family")
    params = dict(model_config.get("estimator_params", {}))
    if family == "joint_logistic":
        estimator = num.LogisticRegression(**params)
    elif family == "hist_gradient_boosting":
        estimator = num.HistGradientBoostingClassifier(**params)
    elif family == "random_forest":
        estimator = num.RandomForestClassifier(**params)
    else:
        raise CampaignMemberError(f"unsupported estimator family: {family!r}")
    return dict(estimator.get_params(deep=True))


def _validated_receipts(
    receipts: Sequence[Mapping[str, Any]], *, label: str, fit_cutoff: str
) -> list[dict[str, Any]]:
    if not receipts:
        raise CampaignMemberError(f"{label} must be a nonempty receipt list")
    normalized: list[dict[str, Any]] = []
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, Mapping):
            raise CampaignMemberError(f"{label}[{index}] must be an object")
        artifact = receipt.get("artifact")
        if artifact is None and "path" in receipt and "sha256" in receipt:
            artifact = {"path": receipt["path"], "sha256": receipt["sha256"]}
        if not isinstance(artifact, Mapping):
            raise CampaignMemberError(f"{label}[{index}].artifact must be an object")
        path = artifact.get("path")
        horizon = receipt.get("horizon_end")
        if not isinstance(path, str) or not path:
            raise CampaignMemberError(f"{label}[{index}].path must be nonempty")
        digest = require_nonempty_digest(
            artifact.get("sha256"), label=f"{label}[{index}].artifact.sha256"
        )
        resolved = resolve_under_root(path, label=f"{label}[{index}]")
        if sha256(resolved) != digest:
            raise CampaignMemberError(f"{label}[{index}] artifact hash mismatch")
        if not isinstance(horizon, str) or horizon > fit_cutoff:
            raise CampaignMemberError(
                f"{label}[{index}].horizon_end must not exceed fit cutoff {fit_cutoff}"
            )
        normalized.append(
            {
                **{
                    key: value
                    for key, value in dict(receipt).items()
                    if key not in {"path", "sha256", "artifact"}
                },
                "horizon_end": horizon,
                "artifact": {
                    "path": relative_to_root(resolved, label=f"{label}[{index}]"),
                    "sha256": digest,
                },
            }
        )
    return normalized


def _fit_matrix_digest(matrix: np.ndarray) -> str:
    values = np.asarray(matrix, dtype="<f8", order="C")
    if not np.all(np.isfinite(values)):
        raise CampaignMemberError("campaign fit matrix contains nonfinite values")
    return hashlib.sha256(str(values.shape).encode() + values.tobytes()).hexdigest()


def _array_receipt(value: Any) -> dict[str, Any]:
    array = np.ascontiguousarray(np.asarray(value))
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "sha256": hashlib.sha256(
            str(array.shape).encode() + str(array.dtype).encode() + array.tobytes()
        ).hexdigest(),
    }


def _validate_training_membership_receipt(
    receipt: Mapping[str, Any],
    *,
    keys: Sequence[tuple[str, str]],
    dates: Mapping[tuple[str, str], str],
) -> dict[str, Any]:
    path = resolve_under_root(str(receipt.get("path", "")), label="training membership")
    digest = require_nonempty_digest(receipt.get("sha256"), label="training membership.sha256")
    if sha256(path) != digest:
        raise CampaignMemberError("training membership artifact hash mismatch")
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != ("season", "match_id", "match_date"):
                raise CampaignMemberError("training membership header drift")
            rows = list(reader)
    except OSError as error:
        raise CampaignMemberError(f"cannot read training membership: {error}") from error
    observed = tuple((row["season"], row["match_id"]) for row in rows)
    if observed != tuple(keys) or any(
        row["match_date"] != dates[key] for row, key in zip(rows, keys, strict=True)
    ):
        raise CampaignMemberError("training membership rows differ from actual fit inputs")
    expected = {
        "path": relative_to_root(path, label="training membership"),
        "sha256": digest,
        "rows": len(keys),
        "membership_sha256": num.key_hash(keys),
    }
    if dict(receipt) != expected:
        raise CampaignMemberError("training membership receipt fields drift")
    return expected


def _validated_prediction_features(
    receipt: Mapping[str, Any],
    *,
    supplied: num.FeatureTable,
    model_columns: Sequence[str],
) -> tuple[num.FeatureTable, dict[str, Any]]:
    path = resolve_under_root(str(receipt.get("path", "")), label="prediction features")
    digest = require_nonempty_digest(receipt.get("sha256"), label="prediction features.sha256")
    persisted = num.FeatureTable.read_csv(
        path,
        expected_sha256=digest,
        expected_header=(*num.KEY_COLUMNS, *model_columns),
    )
    expected = {
        "path": relative_to_root(path, label="prediction features"),
        "sha256": digest,
        "rows": len(persisted.keys),
        "membership_sha256": num.key_hash(persisted.keys),
    }
    if dict(receipt) != expected:
        raise CampaignMemberError("prediction feature receipt fields drift")
    if (
        supplied.header != persisted.header
        or supplied.keys != persisted.keys
        or supplied.rows != persisted.rows
    ):
        raise CampaignMemberError("supplied prediction features differ from prebound artifact")
    return persisted, expected


def fit_raw_numerical_member(
    *,
    spec: MemberSpec,
    contract: pipeline.FeatureContract,
    training_features: num.FeatureTable,
    training_labels: num.LabelTable,
    prediction_features: num.FeatureTable,
    tour: str,
    custody_scope: str,
    fit_cutoff: str,
    producer_plan_sha256: str,
    training_dates: Mapping[tuple[str, str], str],
    training_membership_receipt: Mapping[str, Any],
    prediction_feature_receipt: Mapping[str, Any],
    state_receipts: Sequence[Mapping[str, Any]],
    offset_receipts: Sequence[Mapping[str, Any]],
    fit_frame_receipt: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Fit one fixed raw member with exact-identity caching and complete receipts.

    This callable is used by synthetic/integrity rehearsals.  The production campaign
    runner consumes its manifest-bound outputs; it never silently launches the 40 real
    RF fits.  Cache reuse is possible only when every config, feature, label, key,
    horizon, state, offset and campaign binding in this identity is byte-identical.
    """
    normalized_tour = str(tour).upper()
    expected_spec = {item.member_id: item for item in member_specs(normalized_tour)}.get(
        spec.member_id
    )
    if expected_spec != spec:
        raise CampaignMemberError("raw member spec differs from the tour-specific plan")
    if custody_scope not in {"synthetic_rehearsal", "frozen_real_inputs"}:
        raise CampaignMemberError("raw member custody_scope is invalid")
    require_nonempty_digest(producer_plan_sha256, label="producer_plan_sha256")
    states = _validated_receipts(state_receipts, label="state_receipts", fit_cutoff=fit_cutoff)
    offset_applicability = (
        "required_tier" if spec.feature_bundle == "full_tier" else "not_applicable_non_tier"
    )
    if offset_applicability == "required_tier":
        offsets = _validated_receipts(
            offset_receipts, label="offset_receipts", fit_cutoff=fit_cutoff
        )
    else:
        if offset_receipts:
            raise CampaignMemberError("non-tier raw member must not invent offset receipts")
        offsets = []
    model_config = numerical_member_config(contract, spec)
    prediction_years = {int(key[0]) for key in prediction_features.keys}
    if len(prediction_years) != 1:
        raise CampaignMemberError("raw member predictions must cover exactly one year")
    prediction_year = next(iter(prediction_years))
    if fit_cutoff != f"{prediction_year - 1:04d}-12-30":
        raise CampaignMemberError(
            "raw member fit cutoff must be December 30 before prediction year"
        )
    tree = model_config["family"] in num.TREE_FAMILIES
    model_columns = tuple(
        model_config["signed_numeric_columns" if tree else "numeric_columns"]
    ) + tuple(model_config.get("context_columns", ()))
    prediction_features, prediction_feature_binding = _validated_prediction_features(
        prediction_feature_receipt,
        supplied=prediction_features,
        model_columns=model_columns,
    )
    expected_fit_frame = {
        "rows": len(training_features.keys),
        "columns": list(model_columns),
        "labels_sha256": training_labels.source_sha256,
        "training_keys_sha256": num.key_hash(training_features.keys),
        "fit_through": fit_cutoff,
        "prediction_year": prediction_year,
    }
    if any(fit_frame_receipt.get(key) != value for key, value in expected_fit_frame.items()):
        raise CampaignMemberError("campaign-integrity fit-frame receipt differs from actual fit")
    observed_matrix_sha256 = _fit_matrix_digest(training_features.matrix(model_columns))
    if fit_frame_receipt.get("matrix_sha256") != observed_matrix_sha256:
        raise CampaignMemberError("campaign-integrity fit-frame matrix digest is stale")
    observed_classes = sorted(set(training_labels.align_exact(training_features.keys).tolist()))
    if fit_frame_receipt.get("classes") != observed_classes or observed_classes != [0, 1]:
        raise CampaignMemberError("campaign-integrity fit-frame receipt lacks both classes")
    training_seasons = {int(key[0]) for key in training_features.keys}
    if not training_seasons or max(training_seasons) >= prediction_year:
        raise CampaignMemberError("raw member training membership reaches prediction year")
    if set(training_dates) != set(training_features.keys):
        raise CampaignMemberError("raw member training-date keys differ from fit membership")
    expected_fit_start = dt.date(max(2011, prediction_year - 5), 1, 1)
    expected_fit_end = dt.date(prediction_year - 1, 12, 30)
    if fit_frame_receipt.get("fit_start") != expected_fit_start.isoformat():
        raise CampaignMemberError("raw member fit_start differs from the immutable base window")
    observed_dates: list[dt.date] = []
    for key in training_features.keys:
        try:
            observed = dt.date.fromisoformat(str(training_dates[key]))
        except ValueError as error:
            raise CampaignMemberError(f"invalid raw member training date at {key}") from error
        if observed.year != int(key[0]):
            raise CampaignMemberError(f"raw member training date/season drift at {key}")
        if not expected_fit_start <= observed <= expected_fit_end:
            raise CampaignMemberError(f"raw member training date lies outside base window at {key}")
        observed_dates.append(observed)
    training_dates_sha256 = canonical_hash_nonempty(
        [[key[0], key[1], training_dates[key]] for key in training_features.keys],
        label="training dates",
    )
    training_membership = _validate_training_membership_receipt(
        training_membership_receipt,
        keys=training_features.keys,
        dates=training_dates,
    )
    identity = num.fit_identity(
        model_config,
        fit_cutoff,
        training_features,
        training_labels,
        producer_plan_sha256,
    )
    identity.update(
        {
            "producer_plan_sha256": producer_plan_sha256,
            "member_id": spec.member_id,
            "feature_bundle": spec.feature_bundle,
            "prediction_feature_sha256": prediction_features.source_sha256,
            "prediction_keys_sha256": num.key_hash(prediction_features.keys),
            "state_receipts_sha256": canonical_hash_nonempty(states, label="state receipts"),
            "offset_receipts_sha256": canonical_hash_nonempty(
                {"applicability": offset_applicability, "receipts": offsets},
                label="offset receipt policy",
            ),
            "fit_frame_receipt_sha256": canonical_hash_nonempty(
                dict(fit_frame_receipt), label="fit frame receipt"
            ),
            "training_dates_sha256": training_dates_sha256,
        }
    )
    observed_fit_inputs: dict[str, Any] = {}

    def observe_fit_inputs(
        matrix: Any,
        labels: np.ndarray,
        sample_weight: np.ndarray | None,
        feature_names: tuple[str, ...],
    ) -> None:
        observed_fit_inputs.update(
            {
                "matrix": _array_receipt(matrix),
                "labels": _array_receipt(labels),
                "sample_weight": (None if sample_weight is None else _array_receipt(sample_weight)),
                "feature_names": list(feature_names),
            }
        )

    cache = num.FileFitCache(output_dir / "fit_cache")
    attempt, fit_manifest = cache.fit_or_load(
        identity,
        training_features.keys,
        lambda: num.fit_procedure(
            model_config,
            training_features,
            training_labels,
            fit_input_observer=observe_fit_inputs,
        ),
    )
    fit_identity_sha256 = num.sha256_json(identity)
    fit_manifest_path = output_dir / "fit_cache" / fit_identity_sha256 / "fit_manifest.json"
    numeric_key = "signed_numeric_columns" if tree else "numeric_columns"
    record: dict[str, Any] = {
        "schema": RAW_MEMBER_SCHEMA,
        "stage": "raw_member",
        "custody_scope": custody_scope,
        "producer_plan_sha256": producer_plan_sha256,
        "tour": normalized_tour,
        "member_id": spec.member_id,
        "kind": spec.kind,
        "learner": spec.learner,
        "candidate_id": spec.candidate_id,
        "feature_bundle": spec.feature_bundle,
        "origin": "new_plan_fit",
        "model_fit_executed": True,
        "status": attempt.status,
        "fit_cache_reused": attempt.cache_reused,
        "fit_identity": identity,
        "fit_identity_sha256": fit_identity_sha256,
        "fit_manifest": {
            "path": relative_to_root(fit_manifest_path, label="raw fit manifest"),
            "sha256": fit_manifest["fit_manifest_file_sha256"],
        },
        "fit_manifest_sha256": fit_manifest["fit_manifest_file_sha256"],
        "estimator_config_sha256": num.sha256_json(model_config),
        "resolved_estimator_params": fit_manifest.get("estimator_get_params"),
        "ordered_feature_columns": {
            "numeric_or_signed": list(model_config[numeric_key]),
            "symmetric_context": list(model_config.get("context_columns", ())),
        },
        "estimator_feature_names": fit_manifest.get("estimator_feature_names"),
        "state_receipts": states,
        "offset_receipts": offsets,
        "offset_applicability": offset_applicability,
        "fit_frame_receipt": dict(fit_frame_receipt),
        "fit_window": {
            "start": expected_fit_start.isoformat(),
            "through": fit_cutoff,
        },
        "training_membership": training_membership,
        "prediction_features": prediction_feature_binding,
        # Directly consumable by integrity.campaign.assert_raw_member once that lane is
        # integrated.  These fields name the raw procedure, not a later S2 selection.
        "prediction_year": prediction_year,
        "fit_semantics": "raw_predeclared_numerical_candidate",
        "fit_cutoff": fit_cutoff,
        "training_season_max": max(training_seasons),
        "training_date_min": min(observed_dates).isoformat(),
        "training_date_max": max(observed_dates).isoformat(),
        "training_dates_sha256": training_dates_sha256,
        "training_rows": len(training_features.keys),
        "raw_unselected_uncalibrated": True,
        "same_year_selection_or_slope_used": False,
        "same_cutoff_batched_history": True,
        "same_cutoff_batched_history_sha256": canonical_hash_nonempty(
            {
                "fit_cutoff": fit_cutoff,
                "state_receipts": states,
                "offset_applicability": offset_applicability,
                "offset_receipts": offsets,
            },
            label="same-cutoff batched history",
        ),
        "procedure": "predeclared_raw_candidate",
        "selection_years": [],
        "calibration_years": [],
        "prediction_keys_sha256": num.key_hash(prediction_features.keys),
        "horizons": {
            "base_fit": fit_cutoff,
            "preprocessing": fit_cutoff,
            "state_policy": max(str(receipt["horizon_end"]) for receipt in states),
            "offset": (
                max(str(receipt["horizon_end"]) for receipt in offsets) if offsets else None
            ),
        },
        "features_sha256": training_features.source_sha256,
        "training_keys_sha256": num.key_hash(training_features.keys),
        "training_membership_sha256": num.key_hash(training_features.keys),
        "preprocessing_sha256": canonical_hash_nonempty(
            {
                "model_config_sha256": num.sha256_json(model_config),
                "fit_frame_matrix_sha256": fit_frame_receipt["matrix_sha256"],
            },
            label="preprocessing contract",
        ),
        "warnings": attempt.warnings,
        "error": attempt.error,
    }
    if attempt.status == "complete" and attempt.fitted is not None:
        try:
            prediction = attempt.fitted.predict(prediction_features)
            prediction_path = output_dir / "predictions.csv"
            prediction_sha256 = prediction.write_csv(prediction_path)
            record["prediction"] = {
                "path": relative_to_root(prediction_path, label="raw member prediction"),
                "sha256": prediction_sha256,
                "rows": len(prediction.keys),
                "membership_sha256": prediction.membership_sha256,
                "source_feature_sha256": prediction.source_feature_sha256,
                "diagnostics": prediction.diagnostics,
            }
            model_path = fit_manifest_path.parent / str(fit_manifest["model_path"])
            transformed_path = output_dir / "producer_evidence" / "transformed_fit_evidence.json"
            if attempt.cache_reused:
                if not transformed_path.is_file():
                    raise CampaignMemberError(
                        "cached fit lacks captured estimator-input evidence; refusing reuse"
                    )
                transformed = json.loads(transformed_path.read_text(encoding="utf-8"))
            else:
                if not observed_fit_inputs:
                    raise CampaignMemberError("actual estimator-fit input observation is missing")
                transformed = {
                    "schema": "campaign_transformed_fit_evidence/v1",
                    "status": "complete",
                    "producer_plan_sha256": producer_plan_sha256,
                    "fit_identity_sha256": fit_identity_sha256,
                    "fit_frame_receipt": dict(fit_frame_receipt),
                    "estimator_feature_names": fit_manifest.get("estimator_feature_names"),
                    "rms_scales": fit_manifest.get("rms_scales"),
                    "model": {
                        "path": relative_to_root(model_path, label="fitted model"),
                        "sha256": sha256(model_path),
                    },
                    "estimator_fit_inputs": observed_fit_inputs,
                    "basis": "captured_at_actual_estimator_fit_call",
                }
                atomic_json(transformed_path, transformed)
            if (
                transformed.get("producer_plan_sha256") != producer_plan_sha256
                or transformed.get("fit_identity_sha256") != fit_identity_sha256
                or transformed.get("model", {}).get("sha256") != sha256(model_path)
                or transformed.get("basis") != "captured_at_actual_estimator_fit_call"
            ):
                raise CampaignMemberError("captured estimator-fit evidence differs on cache reuse")
            closure_path = output_dir / "producer_evidence" / "prediction_closure.json"
            atomic_json(
                closure_path,
                {
                    "schema": "campaign_prediction_replay/v1",
                    "status": "complete",
                    "producer_plan_sha256": producer_plan_sha256,
                    "fit_identity_sha256": fit_identity_sha256,
                    "model_sha256": sha256(model_path),
                    "prediction_feature_sha256": prediction_features.source_sha256,
                    "prediction_features": prediction_feature_binding,
                    "preprocessing_sha256": record["preprocessing_sha256"],
                    "prediction_keys_sha256": num.key_hash(prediction_features.keys),
                    "recomputed_prediction_sha256": prediction_sha256,
                    "method": "predict_bound_model",
                },
            )
            record["transformed_fit_evidence"] = {
                "path": relative_to_root(transformed_path, label="transformed fit evidence"),
                "sha256": sha256(transformed_path),
            }
            record["prediction_closure"] = {
                "method": "predict_bound_model",
                "recomputed_prediction_sha256": prediction_sha256,
                "evidence": {
                    "path": relative_to_root(closure_path, label="prediction closure"),
                    "sha256": sha256(closure_path),
                },
            }
        except Exception as error:
            record["status"] = "failed_prediction"
            record["error"] = {"type": type(error).__name__, "message": str(error)}
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "raw_member_manifest.json"
    manifest_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    record["manifest_sha256"] = sha256(manifest_path)
    return record
