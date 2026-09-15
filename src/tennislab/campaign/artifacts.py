"""Validated producer, population, forecast-input, and post-barrier quote artifacts."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from tennislab.campaign.contracts import EXPECTED_POPULATION, CampaignConfig, CampaignConfigError
from tennislab.campaign.members import MEMBER_IDS, member_specs, resolved_estimator_params
from tennislab.campaign.stages import (
    INPUT_MANIFEST_SCHEMA,
    QUALIFICATION_SCHEMA,
    RAW_MEMBER_SCHEMA,
    binding,
    inventory_sha256,
    read_object,
    require_completion,
    validate_typed_inventory,
)
from tennislab.chain.common import (
    canonical_hash_nonempty,
    relative_to_root,
    require_nonempty_digest,
    resolve_under_root,
    sha256,
)
from tennislab.chain.labels import LABEL_COLUMNS, METADATA_FIELDS
from tennislab.dynamics.calibrate import CAMPAIGN_FIT_DISCLOSURE_POLICY
from tennislab.dynamics.calibration import FAMILIES
from tennislab.models import numerical as num
from tennislab.models import pipeline

METADATA_COLUMNS = (
    "season",
    "match_id",
    "calendar_year",
    "source_season",
    "match_date",
    "eligible_through_date",
    "tourney_id",
    "identity_tier",
    "primary_target",
    "source_field_agreement",
    "elo_overall_logit",
    "elo_surface_logit",
)
KEY_COLUMNS = ("season", "match_id")
DATED_KEY_COLUMNS = (*KEY_COLUMNS, "match_date")
PREDICTION_COLUMNS = (*KEY_COLUMNS, "p_a_wins")
RAW_QUOTE_COLUMNS = (
    *KEY_COLUMNS,
    "decimal_a",
    "decimal_b",
    "valid",
    "market_source_path",
    "market_source_row",
    "market_source_sha256",
)


class CampaignArtifactError(CampaignConfigError):
    """A bound artifact, membership, producer, or chronology receipt drifted."""


@dataclass(frozen=True)
class ArtifactBinding:
    path: Path
    sha256: str


@dataclass(frozen=True)
class PredictionArtifact:
    year: int
    keys: tuple[tuple[str, str], ...]
    probabilities: dict[tuple[str, str], float]
    binding: ArtifactBinding
    receipt: dict[str, Any]


@dataclass(frozen=True)
class CampaignInputs:
    document: dict[str, Any]
    qualification: dict[str, Any]
    metadata: dict[tuple[str, str], dict[str, str]]
    metadata_binding: ArtifactBinding
    labels_binding: ArtifactBinding
    cohort_keys: dict[int, tuple[tuple[str, str], ...]]
    selection_keys: dict[int, dict[int, tuple[tuple[str, str], ...]]]
    priced_keys: dict[int, tuple[tuple[str, str], ...]]
    incumbent: dict[int, PredictionArtifact]
    raw_members: dict[tuple[int, str], PredictionArtifact]


@dataclass(frozen=True)
class QuoteArtifact:
    probabilities: dict[tuple[str, str], float]
    priced_keys: dict[int, tuple[tuple[str, str], ...]]
    binding: ArtifactBinding


def _binding(value: Any, *, label: str) -> ArtifactBinding:
    try:
        path, digest = binding(value, label=label)
    except ValueError as error:
        raise CampaignArtifactError(str(error)) from error
    return ArtifactBinding(path, digest)


def _read_csv(path: Path, expected_header: Sequence[str]) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != tuple(expected_header):
                raise CampaignArtifactError(f"CSV header drift: {path}")
            return [dict(row) for row in reader]
    except OSError as error:
        raise CampaignArtifactError(f"cannot read CSV {path}: {error}") from error


def _keys(
    rows: Sequence[Mapping[str, str]], *, year: int | None = None
) -> tuple[tuple[str, str], ...]:
    values = tuple((str(row["season"]), str(row["match_id"])) for row in rows)
    if not values or len(set(values)) != len(values) or tuple(sorted(values)) != values:
        raise CampaignArtifactError("artifact keys must be nonempty, unique, and sorted")
    if year is not None and any(key[0] != str(year) for key in values):
        raise CampaignArtifactError(f"artifact contains a key outside year {year}")
    return values


def _validate_binding_counts(
    record: Mapping[str, Any], keys: Sequence[tuple[str, str]], *, label: str
) -> None:
    if record.get("rows") != len(keys):
        raise CampaignArtifactError(f"{label} row count mismatch")
    if record.get("membership_sha256") != num.key_hash(keys):
        raise CampaignArtifactError(f"{label} membership hash mismatch")


def _validate_full_metadata_chronology(
    metadata: Mapping[tuple[str, str], Mapping[str, str]],
) -> None:
    """Validate full-source chronology without imposing qualified-cohort eligibility."""
    for key, row in metadata.items():
        if row["calendar_year"] != key[0]:
            raise CampaignArtifactError(f"campaign metadata calendar-key drift at {key}")
        try:
            int(row["source_season"])
            match_date = dt.date.fromisoformat(row["match_date"])
            eligible = dt.date.fromisoformat(row["eligible_through_date"])
            if match_date.year != int(key[0]) or eligible > match_date:
                raise ValueError("invalid date chronology")
            for field in ("elo_overall_logit", "elo_surface_logit"):
                if not math.isfinite(float(row[field])):
                    raise ValueError("nonfinite result Elo input")
        except ValueError as error:
            raise CampaignArtifactError(f"invalid campaign metadata at {key}") from error


def _validate_qualified_source_seasons(
    metadata: Mapping[tuple[str, str], Mapping[str, str]],
    keys: Sequence[tuple[str, str]],
    *,
    label: str,
) -> None:
    """Require source-season alignment only for rows admitted into a qualified membership."""
    for key in keys:
        row = metadata.get(key)
        if row is None:
            raise CampaignArtifactError(f"{label} contains unknown metadata key: {key}")
        if row["source_season"] != key[0]:
            raise CampaignArtifactError(f"{label} contains source-season crossover at {key}")


def _load_prediction(value: Mapping[str, Any], *, year: int, label: str) -> PredictionArtifact:
    bound = _binding(value, label=label)
    rows = _read_csv(bound.path, PREDICTION_COLUMNS)
    keys = _keys(rows, year=year)
    _validate_binding_counts(value, keys, label=label)
    probabilities: dict[tuple[str, str], float] = {}
    for key, row in zip(keys, rows, strict=True):
        try:
            probability = float(row["p_a_wins"])
        except ValueError as error:
            raise CampaignArtifactError(f"invalid probability in {label} at {key}") from error
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise CampaignArtifactError(f"probability outside [0,1] in {label} at {key}")
        probabilities[key] = probability
    return PredictionArtifact(year, keys, probabilities, bound, dict(value))


def _prediction_sha256(prediction: num.Predictions) -> str:
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(PREDICTION_COLUMNS)
    for (season, match_id), probability in zip(
        prediction.keys, prediction.probabilities, strict=True
    ):
        writer.writerow((season, match_id, repr(float(probability))))
    return hashlib.sha256(handle.getvalue().encode()).hexdigest()


def _expected_constructor_params(member_id: str) -> dict[str, Any] | None:
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


def _plan_model_config(plan_member: Mapping[str, Any]) -> dict[str, Any]:
    learner = str(plan_member.get("learner"))
    ordered = plan_member.get("ordered_feature_columns")
    if not isinstance(ordered, Mapping):
        raise CampaignArtifactError("producer plan lacks ordered feature columns")
    named_columns = [
        *ordered.get("numeric_or_signed", []),
        *ordered.get("symmetric_context", []),
    ]
    forbidden = sorted(pipeline.FORBIDDEN_MODEL_COLUMNS.intersection(named_columns))
    if forbidden or any(
        token in str(column).lower()
        for column in named_columns
        for token in ("pinnacle", "market", "ps_probability", "ps_logit", "ps_missing")
    ):
        raise CampaignArtifactError(
            f"producer plan contains forbidden model columns: {forbidden or named_columns}"
        )
    config_prefix = "random_forest" if learner == "random_forest" else learner
    common = {
        "config_id": (
            f"{config_prefix}__{plan_member['feature_bundle']}__{plan_member['candidate_id']}"
        ),
        "estimator_params": _expected_constructor_params(str(plan_member["member_id"])),
    }
    if learner == "ridge":
        expected = {
            **common,
            "family": "joint_logistic",
            "numeric_columns": ordered.get("numeric_or_signed"),
        }
    elif learner in {"hgb", "random_forest"}:
        expected = {
            **common,
            "family": ("hist_gradient_boosting" if learner == "hgb" else "random_forest"),
            "signed_numeric_columns": ordered.get("numeric_or_signed"),
            "context_columns": ordered.get("symmetric_context"),
        }
    else:
        raise CampaignArtifactError(f"unsupported planned learner: {learner}")
    if plan_member.get("estimator_config") != expected:
        raise CampaignArtifactError(
            f"producer plan estimator config drift: {plan_member.get('member_id')}"
        )
    return expected


def _validate_state_receipts(
    receipts: Any,
    *,
    expected: Any,
    completed_paths: Mapping[str, Mapping[str, Any]],
    label: str,
    fit_through: str,
) -> None:
    if receipts != expected or not isinstance(receipts, list):
        raise CampaignArtifactError(f"{label} differs from the frozen producer plan")
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, Mapping):
            raise CampaignArtifactError(f"{label}[{index}] must be an object")
        horizon = receipt.get("horizon_end")
        try:
            horizon_date = dt.date.fromisoformat(str(horizon))
            if horizon_date > dt.date.fromisoformat(fit_through):
                raise CampaignArtifactError(f"{label}[{index}] exceeds the fit cutoff")
        except ValueError as error:
            raise CampaignArtifactError(f"{label}[{index}] horizon is invalid") from error
        artifact = _binding(receipt.get("artifact"), label=f"{label}[{index}].artifact")
        artifact_path = str(receipt["artifact"]["path"])
        if (
            artifact_path not in completed_paths
            or completed_paths[artifact_path].get("sha256") != artifact.sha256
        ):
            raise CampaignArtifactError(f"{label}[{index}] is absent from producer completion")
        state = read_object(artifact.path, label=f"{label}[{index}] state")
        if state.get("status") != "complete" or state.get("horizon_end") != horizon:
            raise CampaignArtifactError(f"{label}[{index}] content/horizon drift")


def _training_membership(
    value: Mapping[str, Any], *, year: int, fit_start: str, fit_through: str, label: str
) -> tuple[tuple[tuple[str, str], ...], str]:
    artifact = _binding(value, label=label)
    rows = _read_csv(artifact.path, DATED_KEY_COLUMNS)
    keys = _keys(rows)
    _validate_binding_counts(value, keys, label=label)
    lower = dt.date.fromisoformat(fit_start)
    upper = dt.date.fromisoformat(fit_through)
    for key, row in zip(keys, rows, strict=True):
        try:
            observed = dt.date.fromisoformat(row["match_date"])
        except ValueError as error:
            raise CampaignArtifactError(f"invalid training date in {label} at {key}") from error
        if observed.year != int(key[0]) or not lower <= observed <= upper:
            raise CampaignArtifactError(f"training date outside base window in {label} at {key}")
    if max(int(key[0]) for key in keys) >= year:
        raise CampaignArtifactError(f"{label} reaches prediction year")
    dates_sha256 = canonical_hash_nonempty(
        [[key[0], key[1], row["match_date"]] for key, row in zip(keys, rows, strict=True)],
        label=f"{label} dates",
    )
    return keys, dates_sha256


def _validate_estimator_fit_inputs(
    value: Any,
    *,
    training_rows: int,
    feature_names: Sequence[str],
    tree: bool,
    label: str,
) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "matrix",
        "labels",
        "sample_weight",
        "feature_names",
    }:
        raise CampaignArtifactError(f"{label} estimator-fit input receipt drift")
    fitted_rows = 2 * training_rows if tree else training_rows
    if value.get("feature_names") != list(feature_names):
        raise CampaignArtifactError(f"{label} fitted feature-name drift")
    matrix = value.get("matrix")
    labels = value.get("labels")
    if not isinstance(matrix, Mapping) or matrix.get("shape") != [fitted_rows, len(feature_names)]:
        raise CampaignArtifactError(f"{label} fitted matrix shape drift")
    if not isinstance(labels, Mapping) or labels.get("shape") != [fitted_rows]:
        raise CampaignArtifactError(f"{label} fitted label shape drift")
    for name, receipt in (("matrix", matrix), ("labels", labels)):
        if not isinstance(receipt.get("dtype"), str):
            raise CampaignArtifactError(f"{label} {name} dtype drift")
        require_nonempty_digest(receipt.get("sha256"), label=f"{label} {name}")
    weight = value.get("sample_weight")
    if tree:
        if not isinstance(weight, Mapping) or weight.get("shape") != [fitted_rows]:
            raise CampaignArtifactError(f"{label} fitted sample-weight shape drift")
        require_nonempty_digest(weight.get("sha256"), label=f"{label} sample weight")
    elif weight is not None:
        raise CampaignArtifactError(f"{label} unexpected fitted sample weights")


def _validate_producer_tree(config: CampaignConfig) -> None:
    plan = config.producer_plan
    completion = config.producer_completion
    expected_records = plan.get("expected_artifacts")
    if not isinstance(expected_records, list):
        raise CampaignArtifactError("producer plan lacks expected_artifacts")
    expected: dict[str, tuple[str, Mapping[str, Any], str]] = {}
    for record in expected_records:
        if not isinstance(record, Mapping):
            raise CampaignArtifactError("producer expected artifact must be an object")
        path = str(record.get("path", ""))
        if path in expected or not path:
            raise CampaignArtifactError(f"duplicate/blank producer expected artifact: {path}")
        expected[path] = (
            str(record.get("schema", "")),
            dict(record.get("logical_key", {})),
            str(record.get("media_type", "")),
        )
    producer_root = resolve_under_root(str(plan.get("producer_root", "")), label="producer root")
    if completion.get("producer_root") != plan.get("producer_root"):
        raise CampaignArtifactError("producer completion root drift")
    try:
        records = validate_typed_inventory(
            completion.get("artifacts"),
            root=resolve_under_root(".", label="workspace"),
            inventory_root=producer_root,
            expected=expected,
            label="producer completion",
        )
    except ValueError as error:
        raise CampaignArtifactError(str(error)) from error
    if completion.get("inventory_sha256") != inventory_sha256(records):
        raise CampaignArtifactError("producer completion inventory commitment drift")
    _validate_native_sr03(config)


def _contains_objective(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(key == "objective" or _contains_objective(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_objective(child) for child in value)
    return False


def _validate_native_sr03(config: CampaignConfig) -> None:
    native = config.producer_plan.get("native_sr03")
    if not isinstance(native, Mapping) or native.get("policy") != CAMPAIGN_FIT_DISCLOSURE_POLICY:
        raise CampaignArtifactError("producer plan lacks the reviewed native SR03 policy")
    native_config = read_object(
        _binding(native.get("config"), label="native SR03 config").path,
        label="native SR03 config",
    )
    if (
        native_config.get("calibration", {}).get("fit_disclosure_policy")
        != CAMPAIGN_FIT_DISCLOSURE_POLICY
    ):
        raise CampaignArtifactError("actual native SR03 config lacks the reviewed policy")
    fits_path = resolve_under_root(str(native.get("fits_path", "")), label="native SR03 fits")
    events_path = resolve_under_root(str(native.get("events_path", "")), label="native SR03 events")
    run_path = resolve_under_root(
        str(native.get("run_manifest_path", "")), label="native SR03 completion"
    )
    completed_paths = {str(item["path"]): item for item in config.producer_completion["artifacts"]}
    for path, label in (
        (_binding(native.get("config"), label="native SR03 config").path, "config"),
        (fits_path, "fits"),
        (events_path, "events"),
        (run_path, "completion"),
    ):
        path_text = relative_to_root(path, label=f"native SR03 {label}")
        if path_text not in completed_paths or completed_paths[path_text].get("sha256") != sha256(
            path
        ):
            raise CampaignArtifactError(f"native SR03 {label} is absent from producer completion")
    try:
        fits = json.loads(fits_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as error:
        raise CampaignArtifactError(
            f"cannot parse native SR03 disclosure sinks: {error}"
        ) from error
    if not isinstance(fits, list) or any(not isinstance(item, Mapping) for item in fits + events):
        raise CampaignArtifactError("native SR03 disclosure sinks have invalid records")
    expected_records = native.get("expected_records")
    if expected_records != len(fits) or expected_records != len(events):
        raise CampaignArtifactError("native SR03 disclosure sink inventory drift")
    for sink, name in ((fits, "fits.json"), (events, "fit_events.jsonl")):
        for record in sink:
            if _contains_objective(record):
                raise CampaignArtifactError(f"native SR03 {name} exposed an objective")
            if record.get("fit_objective_disclosure") != "deferred_to_post_barrier":
                raise CampaignArtifactError(f"native SR03 {name} lacks disclosure marker")
            require_nonempty_digest(
                record.get("full_fit_record_commitment_sha256"),
                label=f"native SR03 {name} full-record commitment",
            )

    def commitments(items: Sequence[Mapping[str, Any]]) -> dict[tuple[int, str], str]:
        output: dict[tuple[int, str], str] = {}
        for item in items:
            key = (int(item["outer_year"]), str(item["family"]))
            if key in output:
                raise CampaignArtifactError(f"duplicate native SR03 disclosure key: {key}")
            output[key] = str(item["full_fit_record_commitment_sha256"])
        return output

    fit_commitments = commitments(fits)
    event_commitments = commitments(events)
    if fit_commitments != event_commitments:
        raise CampaignArtifactError("native SR03 disclosure sink commitments differ")
    outer_years = native_config.get("calibration", {}).get("outer_years")
    if expected_records:
        if not isinstance(outer_years, list):
            raise CampaignArtifactError("native SR03 config lacks outer-year inventory")
        expected_keys = {(int(year), family) for year in outer_years for family, _ in FAMILIES}
        if set(fit_commitments) != expected_keys:
            raise CampaignArtifactError("native SR03 disclosure keys differ from its config")
    run = read_object(run_path, label="native SR03 completion")
    artifacts = run.get("artifacts", {})
    if (
        run.get("status") != "complete"
        or run.get("config_sha256") != _binding(native.get("config"), label="native config").sha256
        or run.get("fit_disclosure", {}).get("policy") != CAMPAIGN_FIT_DISCLOSURE_POLICY
        or artifacts.get("fits.json")
        != _binding(
            {"path": str(native["fits_path"]), "sha256": artifacts.get("fits.json")},
            label="native fits sink",
        ).sha256
        or artifacts.get("fit_events.jsonl")
        != _binding(
            {
                "path": str(native["events_path"]),
                "sha256": artifacts.get("fit_events.jsonl"),
            },
            label="native events sink",
        ).sha256
        or run.get("fits") != expected_records
    ):
        raise CampaignArtifactError("native SR03 completion does not bind both sinks")


def _validate_raw_producer(
    config: CampaignConfig,
    record: Mapping[str, Any],
    *,
    year: int,
    member_id: str,
    plan_member: Mapping[str, Any],
    plan_year: Mapping[str, Any],
) -> None:
    completed_paths = {str(item["path"]): item for item in config.producer_completion["artifacts"]}

    def completed_binding(value: Any, *, label: str) -> ArtifactBinding:
        observed = _binding(value, label=label)
        path_text = str(value["path"])
        if (
            path_text not in completed_paths
            or completed_paths[path_text]["sha256"] != observed.sha256
        ):
            raise CampaignArtifactError(f"{label} is absent from producer completion")
        return observed

    producer_binding = completed_binding(
        record.get("producer_record"), label=f"raw member {year}/{member_id} producer record"
    )
    producer = read_object(producer_binding.path, label=f"raw member {year}/{member_id}")
    try:
        require_completion(producer, schema=RAW_MEMBER_SCHEMA, stage="raw_member")
    except ValueError as error:
        raise CampaignArtifactError(str(error)) from error
    if producer.get("custody_scope") != config.document["execution_scope"]:
        raise CampaignArtifactError(f"raw member {year}/{member_id} custody scope drift")
    exact = {
        "producer_plan_sha256": config.producer_plan_sha256,
        "tour": config.tour,
        "prediction_year": year,
        "member_id": member_id,
        "kind": plan_member["kind"],
        "learner": plan_member.get("learner"),
        "candidate_id": plan_member.get("candidate_id"),
        "feature_bundle": plan_member["feature_bundle"],
        "fit_window": {
            "start": plan_year["fit_start"],
            "through": plan_year["fit_through"],
        },
        "ordered_feature_columns": plan_member["ordered_feature_columns"],
        "resolved_estimator_params": plan_member.get("resolved_estimator_params"),
        "state_receipts": plan_year["state_receipts"],
        "offset_receipts": (
            plan_year["offset_receipts"] if plan_member["feature_bundle"] == "full_tier" else []
        ),
    }
    for name, expected in exact.items():
        if producer.get(name) != expected:
            raise CampaignArtifactError(f"raw member {year}/{member_id} {name} drift")
    if producer.get("raw_unselected_uncalibrated") is not True:
        raise CampaignArtifactError(f"raw member {year}/{member_id} is not actual raw output")
    if producer.get("same_year_selection_or_slope_used") is not False:
        raise CampaignArtifactError(f"raw member {year}/{member_id} used a same-year decision")
    if producer.get("same_cutoff_batched_history") is not True:
        raise CampaignArtifactError(f"raw member {year}/{member_id} history batching drift")
    if producer.get("selection_years") != [] or producer.get("calibration_years") != []:
        raise CampaignArtifactError(f"raw member {year}/{member_id} has decision ancestry")
    training = producer.get("training_membership")
    training_keys: tuple[tuple[str, str], ...] = ()
    training_dates_sha256 = ""
    persisted_prediction_features: num.FeatureTable | None = None
    if member_id == "result_elo":
        if training is not None or producer.get("origin") != "deterministic_state":
            raise CampaignArtifactError("result Elo producer semantics drift")
    else:
        expected_model_config = _plan_model_config(plan_member)
        expected_resolved_params = resolved_estimator_params(expected_model_config)
        if not isinstance(training, Mapping) or dict(training) != plan_year["training_membership"]:
            raise CampaignArtifactError(f"raw member {year}/{member_id} training binding drift")
        completed_binding(
            training,
            label=f"raw member {year}/{member_id} training membership",
        )
        training_keys, training_dates_sha256 = _training_membership(
            training,
            year=year,
            fit_start=plan_year["fit_start"],
            fit_through=plan_year["fit_through"],
            label=f"raw member {year}/{member_id} training membership",
        )
        if (
            plan_member.get("resolved_estimator_params") != expected_resolved_params
            or producer.get("resolved_estimator_params") != expected_resolved_params
        ):
            raise CampaignArtifactError(f"raw member {year}/{member_id} estimator drift")
        origin = producer.get("origin")
        ordered = plan_member["ordered_feature_columns"]
        expected_columns = [
            *ordered["numeric_or_signed"],
            *ordered["symmetric_context"],
        ]
        if origin != "verified_legacy_native_import":
            planned_prediction_features = plan_year.get("prediction_features")
            if not isinstance(planned_prediction_features, Mapping):
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} lacks planned prediction features"
                )
            expected_prediction_features = planned_prediction_features.get(member_id)
            if (
                not isinstance(expected_prediction_features, Mapping)
                or producer.get("prediction_features") != expected_prediction_features
            ):
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} prediction feature binding drift"
                )
            prediction_feature_binding = completed_binding(
                expected_prediction_features,
                label=f"raw member {year}/{member_id} prediction features",
            )
            try:
                persisted_prediction_features = num.FeatureTable.read_csv(
                    prediction_feature_binding.path,
                    expected_sha256=prediction_feature_binding.sha256,
                    expected_header=(*KEY_COLUMNS, *expected_columns),
                )
            except ValueError as error:
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} prediction features drift: {error}"
                ) from error
            prediction_feature_keys = _keys(
                persisted_prediction_features.rows,
                year=year,
            )
            _validate_binding_counts(
                expected_prediction_features,
                prediction_feature_keys,
                label=f"raw member {year}/{member_id} prediction features",
            )
            raw_membership = plan_year.get("raw_prediction_membership")
            if (
                not isinstance(raw_membership, Mapping)
                or raw_membership.get("rows") != len(prediction_feature_keys)
                or raw_membership.get("membership_sha256") != num.key_hash(prediction_feature_keys)
            ):
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} planned prediction membership drift"
                )
        if config.document["execution_scope"] == "synthetic_rehearsal":
            if origin == "synthetic_fixture_no_fit" and producer.get("model_fit_executed") is False:
                pass
            elif origin == "new_plan_fit" and producer.get("model_fit_executed") is True:
                pass
            elif (
                origin == "verified_legacy_native_import"
                and producer.get("model_fit_executed") is True
            ):
                pass
            else:
                raise CampaignArtifactError(f"raw member {year}/{member_id} synthetic origin drift")
        elif origin not in {"new_plan_fit", "verified_legacy_native_import"}:
            raise CampaignArtifactError(f"raw member {year}/{member_id} producer origin drift")
        if origin in {"new_plan_fit", "verified_legacy_native_import"}:
            expected_model_config_sha256 = num.sha256_json(expected_model_config)
            if producer.get("estimator_config_sha256") != expected_model_config_sha256:
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} estimator config digest drift"
                )
            fit_frame = producer.get("fit_frame_receipt")
            if (
                not isinstance(fit_frame, Mapping)
                or fit_frame.get("rows") != len(training_keys)
                or fit_frame.get("columns") != expected_columns
                or fit_frame.get("training_keys_sha256") != num.key_hash(training_keys)
                or fit_frame.get("fit_start") != plan_year["fit_start"]
                or fit_frame.get("fit_through") != plan_year["fit_through"]
                or fit_frame.get("prediction_year") != year
                or fit_frame.get("classes") != [0, 1]
            ):
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} fit-frame receipt drift"
                )
            for field in ("matrix_sha256", "labels_sha256"):
                require_nonempty_digest(
                    fit_frame.get(field),
                    label=f"raw member {year}/{member_id} fit-frame {field}",
                )
            fit_binding = completed_binding(
                producer.get("fit_manifest"), label=f"raw member {year}/{member_id} fit"
            )
            if producer.get("fit_manifest_sha256") != fit_binding.sha256:
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} duplicate fit digest drift"
                )
            transformed_binding = completed_binding(
                producer.get("transformed_fit_evidence"),
                label=f"raw member {year}/{member_id} transformed fit evidence",
            )
            fit = read_object(fit_binding.path, label=f"raw member {year}/{member_id} fit")
            transformed = read_object(
                transformed_binding.path,
                label=f"raw member {year}/{member_id} transformed fit evidence",
            )
            if fit.get("status") != "complete":
                raise CampaignArtifactError(f"raw member {year}/{member_id} actual fit failed")
            if fit.get("estimator_get_params") != expected_resolved_params:
                raise CampaignArtifactError(f"raw member {year}/{member_id} fit settings drift")
            if (
                transformed.get("schema") != "campaign_transformed_fit_evidence/v1"
                or transformed.get("status") != "complete"
                or transformed.get("producer_plan_sha256") != config.producer_plan_sha256
                or transformed.get("fit_frame_receipt") != producer.get("fit_frame_receipt")
                or transformed.get("fit_identity_sha256") != producer.get("fit_identity_sha256")
            ):
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} transformed fit evidence drift"
                )
            if (
                fit.get("estimator_feature_names") != expected_columns
                or transformed.get("estimator_feature_names") != expected_columns
            ):
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} estimator feature-name drift"
                )
            _validate_estimator_fit_inputs(
                transformed.get("estimator_fit_inputs"),
                training_rows=len(training_keys),
                feature_names=expected_columns,
                tree=str(plan_member.get("learner")) in {"hgb", "random_forest"},
                label=f"raw member {year}/{member_id}",
            )
            model = completed_binding(
                transformed.get("model"), label=f"raw member {year}/{member_id} fitted model"
            )
            if fit.get("model_sha256") != model.sha256:
                raise CampaignArtifactError(f"raw member {year}/{member_id} model binding drift")
            expected_preprocessing_sha256 = canonical_hash_nonempty(
                {
                    "model_config_sha256": expected_model_config_sha256,
                    "fit_frame_matrix_sha256": fit_frame["matrix_sha256"],
                },
                label=f"raw member {year}/{member_id} preprocessing contract",
            )
            if producer.get("preprocessing_sha256") != expected_preprocessing_sha256:
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} preprocessing contract drift"
                )
            if origin == "new_plan_fit":
                identity = fit.get("fit_identity")
                expected_identity = {
                    "config_id": expected_model_config["config_id"],
                    "config_sha256": expected_model_config_sha256,
                    "fit_cutoff": plan_year["fit_through"],
                    "frozen_manifest_sha256": config.producer_plan_sha256,
                    "training_feature_sha256": require_nonempty_digest(
                        producer.get("features_sha256"),
                        label=f"raw member {year}/{member_id} training feature source",
                    ),
                    "training_label_sha256": fit_frame["labels_sha256"],
                    "training_keys_sha256": num.key_hash(training_keys),
                    "training_rows": len(training_keys),
                    "producer_plan_sha256": config.producer_plan_sha256,
                    "member_id": member_id,
                    "feature_bundle": plan_member["feature_bundle"],
                    "prediction_feature_sha256": prediction_feature_binding.sha256,
                    "prediction_keys_sha256": num.key_hash(persisted_prediction_features.keys),
                    "state_receipts_sha256": canonical_hash_nonempty(
                        list(plan_year["state_receipts"]),
                        label=f"raw member {year}/{member_id} state receipts",
                    ),
                    "offset_receipts_sha256": canonical_hash_nonempty(
                        {
                            "applicability": producer.get("offset_applicability"),
                            "receipts": producer["offset_receipts"],
                        },
                        label=f"raw member {year}/{member_id} offset receipt policy",
                    ),
                    "fit_frame_receipt_sha256": canonical_hash_nonempty(
                        dict(fit_frame),
                        label=f"raw member {year}/{member_id} fit frame receipt",
                    ),
                    "training_dates_sha256": training_dates_sha256,
                }
                identity_sha256 = num.sha256_json(expected_identity)
                if (
                    identity != expected_identity
                    or producer.get("fit_identity") != expected_identity
                    or producer.get("training_dates_sha256") != training_dates_sha256
                    or fit.get("fit_identity_sha256") != identity_sha256
                    or producer.get("fit_identity_sha256") != identity_sha256
                    or transformed.get("fit_identity_sha256") != identity_sha256
                    or transformed.get("basis") != "captured_at_actual_estimator_fit_call"
                ):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} actual fit identity drift"
                    )
            else:
                legacy = producer.get("legacy_import")
                anchor = plan_member.get("legacy_review_anchor")
                if (
                    not isinstance(legacy, Mapping)
                    or not isinstance(anchor, Mapping)
                    or legacy.get("review_anchor") != anchor
                    or anchor.get("status") != "accepted"
                ):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} lacks reviewed legacy anchor"
                    )
                require_nonempty_digest(anchor.get("sha256"), label="legacy review anchor")
                original_completion_binding = completed_binding(
                    legacy.get("original_completion"),
                    label=f"raw member {year}/{member_id} original completion",
                )
                original_config_binding = completed_binding(
                    legacy.get("original_config"),
                    label=f"raw member {year}/{member_id} original config",
                )
                original_prediction_binding = completed_binding(
                    legacy.get("original_prediction"),
                    label=f"raw member {year}/{member_id} original prediction",
                )
                original_training_binding = completed_binding(
                    legacy.get("original_training_keys"),
                    label=f"raw member {year}/{member_id} original training keys",
                )
                if legacy.get("original_fit_manifest") != producer.get("fit_manifest"):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original fit binding drift"
                    )
                original_completion = read_object(
                    original_completion_binding.path,
                    label=f"raw member {year}/{member_id} original completion",
                )
                original_config = read_object(
                    original_config_binding.path,
                    label=f"raw member {year}/{member_id} original config",
                )
                if (
                    original_completion.get("status") != "complete"
                    or original_completion.get("config_sha256") != original_config_binding.sha256
                ):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original completion/config drift"
                    )
                config_code = original_config.get("code")
                completion_code = original_completion.get("code")
                if not isinstance(config_code, Mapping) or not isinstance(completion_code, Mapping):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original code receipt missing"
                    )
                for role in ("runner", "numerical"):
                    observed_code = completion_code.get(role)
                    if observed_code != {
                        "module": config_code.get(f"{role}_path"),
                        "package_version": config_code.get("package_version"),
                        "sha256": config_code.get(f"{role}_sha256"),
                    }:
                        raise CampaignArtifactError(
                            f"raw member {year}/{member_id} original {role} code drift"
                        )
                original_attempts = original_completion.get("raw_attempts")
                if not isinstance(original_attempts, list):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original attempt inventory missing"
                    )
                expected_config_id = expected_model_config["config_id"]
                matches = [
                    item
                    for item in original_attempts
                    if isinstance(item, Mapping)
                    and item.get("year") == year
                    and item.get("learner") == plan_member.get("learner")
                    and item.get("block") == plan_member.get("feature_bundle")
                    and item.get("candidate_id") == plan_member.get("candidate_id")
                    and item.get("config_id") == expected_config_id
                ]
                if len(matches) != 1:
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original attempt is not unique"
                    )
                original_attempt = matches[0]
                identity = fit.get("fit_identity")
                if not isinstance(identity, Mapping):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original fit identity missing"
                    )
                identity_sha256 = num.sha256_json(dict(identity))
                if (
                    original_attempt.get("status") != "complete"
                    or original_attempt.get("error") is not None
                    or original_attempt.get("outcome_labels_used_for_fit") is not True
                    or original_attempt.get("outcome_labels_used_for_prediction") is not False
                    or original_attempt.get("fit_manifest_sha256") != fit_binding.sha256
                    or original_attempt.get("fit_identity_sha256") != identity_sha256
                    or fit.get("fit_identity_sha256") != identity_sha256
                    or producer.get("fit_identity_sha256") != identity_sha256
                    or fit.get("config_id") != expected_config_id
                    or identity.get("config_id") != expected_config_id
                    or identity.get("config_sha256") != expected_model_config_sha256
                    or identity.get("frozen_manifest_sha256") != original_config_binding.sha256
                    or identity.get("fit_cutoff") != plan_year["fit_through"]
                    or identity.get("training_rows") != len(training_keys)
                    or identity.get("training_keys_sha256") != num.key_hash(training_keys)
                    or identity.get("training_label_sha256") != fit_frame.get("labels_sha256")
                    or identity.get("training_feature_sha256") != producer.get("features_sha256")
                    or original_attempt.get("training_rows") != len(training_keys)
                    or original_attempt.get("training_membership_sha256")
                    != num.key_hash(training_keys)
                ):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original fit chain drift"
                    )
                original_training_rows = _read_csv(original_training_binding.path, KEY_COLUMNS)
                original_training_keys = _keys(original_training_rows)
                if (
                    original_training_keys != training_keys
                    or fit.get("training_keys_file_sha256") != original_training_binding.sha256
                ):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original training-key drift"
                    )
                original_prediction = _load_prediction(
                    {
                        **dict(legacy["original_prediction"]),
                        "rows": original_attempt.get("prediction_rows"),
                        "membership_sha256": original_attempt.get("prediction_membership_sha256"),
                    },
                    year=year,
                    label=f"raw member {year}/{member_id} original prediction",
                )
                campaign_prediction = _load_prediction(
                    producer["prediction"],
                    year=year,
                    label=f"raw member {year}/{member_id} projected prediction",
                )
                if any(
                    original_prediction.probabilities.get(key) != probability
                    for key, probability in campaign_prediction.probabilities.items()
                ):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original prediction projection drift"
                    )
                projection = legacy.get("prediction_projection")
                if projection != {
                    "method": "exact_key_projection_no_refit",
                    "source_prediction_sha256": original_prediction_binding.sha256,
                    "source_rows": len(original_prediction.keys),
                    "source_membership_sha256": num.key_hash(original_prediction.keys),
                    "target_prediction_sha256": campaign_prediction.binding.sha256,
                    "target_rows": len(campaign_prediction.keys),
                    "target_membership_sha256": num.key_hash(campaign_prediction.keys),
                }:
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} prediction projection receipt drift"
                    )
                if (
                    original_attempt.get("prediction_sha256") != original_prediction_binding.sha256
                    or original_attempt.get("primary_target_rows") != len(campaign_prediction.keys)
                    or original_attempt.get("primary_target_membership_sha256")
                    != num.key_hash(campaign_prediction.keys)
                ):
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} original prediction receipt drift"
                    )
                reconstruction = transformed.get("reconstruction")
                if transformed.get(
                    "basis"
                ) != "reconstructed_from_bound_legacy_inputs_and_model" or reconstruction != {
                    "original_config_sha256": original_config_binding.sha256,
                    "original_fit_manifest_sha256": fit_binding.sha256,
                    "original_training_keys_sha256": original_training_binding.sha256,
                    "original_model_sha256": model.sha256,
                    "prefit_frame_receipt_sha256": canonical_hash_nonempty(
                        dict(fit_frame), label="legacy prefit frame receipt"
                    ),
                }:
                    raise CampaignArtifactError(
                        f"raw member {year}/{member_id} legacy reconstruction basis drift"
                    )
    _validate_state_receipts(
        producer["state_receipts"],
        expected=plan_year["state_receipts"],
        completed_paths=completed_paths,
        label=f"raw member {year}/{member_id} state receipts",
        fit_through=plan_year["fit_through"],
    )
    if producer["offset_receipts"]:
        _validate_state_receipts(
            producer["offset_receipts"],
            expected=plan_year["offset_receipts"],
            completed_paths=completed_paths,
            label=f"raw member {year}/{member_id} offset receipts",
            fit_through=plan_year["fit_through"],
        )
    prediction = producer.get("prediction")
    if prediction != record.get("prediction"):
        raise CampaignArtifactError(f"raw member {year}/{member_id} output binding drift")
    completed_binding(prediction, label=f"raw member {year}/{member_id} prediction")
    prediction_artifact = _load_prediction(
        prediction,
        year=year,
        label=f"raw member {year}/{member_id} prediction",
    )
    closure = producer.get("prediction_closure")
    allowed_closure = {
        "synthetic_fixture_no_fit": "deterministic_fixture_generation",
        "new_plan_fit": "predict_bound_model",
        "verified_legacy_native_import": "predict_only_replay",
        "deterministic_state": "deterministic_state_recompute",
    }
    if not isinstance(closure, Mapping) or closure.get("method") != allowed_closure.get(
        str(producer.get("origin"))
    ):
        raise CampaignArtifactError(f"raw member {year}/{member_id} prediction closure drift")
    if closure.get("recomputed_prediction_sha256") != prediction.get("sha256"):
        raise CampaignArtifactError(f"raw member {year}/{member_id} prediction replay drift")
    if producer.get("origin") in {"new_plan_fit", "verified_legacy_native_import"}:
        prediction_feature_sha256 = require_nonempty_digest(
            prediction.get("source_feature_sha256"),
            label=f"raw member {year}/{member_id} prediction feature source",
        )
        evidence_binding = completed_binding(
            closure.get("evidence"), label=f"raw member {year}/{member_id} prediction replay"
        )
        evidence = read_object(
            evidence_binding.path, label=f"raw member {year}/{member_id} prediction replay"
        )
        if (
            evidence.get("schema") != "campaign_prediction_replay/v1"
            or evidence.get("status") != "complete"
            or evidence.get("producer_plan_sha256") != config.producer_plan_sha256
            or evidence.get("fit_identity_sha256") != producer.get("fit_identity_sha256")
            or evidence.get("model_sha256") != fit.get("model_sha256")
            or evidence.get("prediction_feature_sha256") != prediction_feature_sha256
            or evidence.get("method") != closure.get("method")
            or evidence.get("recomputed_prediction_sha256") != prediction.get("sha256")
            or evidence.get("prediction_keys_sha256") != prediction.get("membership_sha256")
            or (
                producer.get("origin") == "new_plan_fit"
                and (
                    evidence.get("prediction_features") != producer.get("prediction_features")
                    or evidence.get("preprocessing_sha256") != producer.get("preprocessing_sha256")
                )
            )
        ):
            raise CampaignArtifactError(f"raw member {year}/{member_id} replay evidence drift")
        if producer.get("origin") == "new_plan_fit":
            try:
                fitted = joblib.load(model.path)
            except Exception as error:
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} bound model cannot be loaded: {error}"
                ) from error
            if (
                not isinstance(fitted, num.FittedProcedure)
                or fitted.config != expected_model_config
                or list(fitted.estimator_feature_names) != expected_columns
            ):
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} bound model/preprocessing drift"
                )
            try:
                replayed = fitted.predict(persisted_prediction_features)
            except Exception as error:
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} bound model replay failed: {error}"
                ) from error
            replayed_sha256 = _prediction_sha256(replayed)
            if (
                replayed.keys != prediction_artifact.keys
                or replayed.membership_sha256 != prediction.get("membership_sha256")
                or replayed.source_feature_sha256 != prediction_feature_sha256
                or any(
                    float(probability) != prediction_artifact.probabilities[key]
                    for key, probability in zip(replayed.keys, replayed.probabilities, strict=True)
                )
                or replayed_sha256 != prediction.get("sha256")
                or replayed_sha256 != closure.get("recomputed_prediction_sha256")
                or replayed_sha256 != evidence.get("recomputed_prediction_sha256")
            ):
                raise CampaignArtifactError(
                    f"raw member {year}/{member_id} bound model prediction replay drift"
                )
        if producer.get("origin") == "verified_legacy_native_import" and (
            evidence.get("original_prediction_sha256") != legacy["original_prediction"]["sha256"]
            or evidence.get("prediction_projection_sha256")
            != canonical_hash_nonempty(
                dict(legacy["prediction_projection"]),
                label="legacy prediction projection",
            )
        ):
            raise CampaignArtifactError(f"raw member {year}/{member_id} legacy replay chain drift")


def _qualified_records(document: Mapping[str, Any], name: str) -> dict[Any, Mapping[str, Any]]:
    records = document.get(name)
    if not isinstance(records, list):
        raise CampaignArtifactError(f"qualification {name} must be a list")
    output: dict[Any, Mapping[str, Any]] = {}
    for record in records:
        key = (
            (int(record["outer_year"]), int(record["source_year"]))
            if name == "selection_cohorts"
            else int(record["year"])
        )
        if key in output:
            raise CampaignArtifactError(f"duplicate qualification {name} key: {key}")
        output[key] = record
    return output


def load_inputs(config: CampaignConfig) -> CampaignInputs:
    """Validate every pre-barrier sports input without opening or parsing raw quotes."""
    _validate_producer_tree(config)
    document = read_object(config.input_manifest_path, label="campaign input manifest")
    require_completion(document, schema=INPUT_MANIFEST_SCHEMA, stage="input_manifest")
    for name, expected in (
        ("tour", config.tour),
        ("custody_scope", config.document["execution_scope"]),
        ("raw_years", list(config.raw_years)),
        ("target_years", list(config.target_years)),
        ("producer_plan_sha256", config.producer_plan_sha256),
        ("producer_completion_sha256", config.producer_completion_sha256),
    ):
        if document.get(name) != expected:
            raise CampaignArtifactError(f"input manifest {name} drift")

    qualification_binding = _binding(document.get("qualification"), label="qualification")
    if config.producer_plan.get("qualification") != document.get("qualification"):
        raise CampaignArtifactError("producer plan/input qualification binding drift")
    qualification = read_object(qualification_binding.path, label="qualification")
    require_completion(
        qualification,
        schema=QUALIFICATION_SCHEMA,
        stage="population_qualification",
    )
    if qualification.get("custody_scope") != config.document["execution_scope"]:
        raise CampaignArtifactError("qualification custody scope drift")
    if qualification.get("tour") != config.tour:
        raise CampaignArtifactError("qualification tour drift")
    expected_quotes = {
        "path": relative_to_root(config.raw_quotes_path, label="raw quote artifact"),
        "sha256": config.raw_quotes_sha256,
    }
    if qualification.get("raw_quotes") != expected_quotes:
        raise CampaignArtifactError("qualification/raw quote binding drift")
    if config.document["execution_scope"] == "frozen_real_inputs":
        anchor = qualification.get("independent_review_anchor")
        if not isinstance(anchor, Mapping) or anchor.get("status") != "accepted":
            raise CampaignArtifactError("real population lacks accepted independent qualification")
        require_nonempty_digest(anchor.get("sha256"), label="independent review anchor")

    metadata_binding = _binding(document.get("metadata"), label="campaign metadata")
    if qualification.get("metadata") != document.get("metadata"):
        raise CampaignArtifactError("qualified metadata binding drift")
    metadata_rows = _read_csv(metadata_binding.path, METADATA_COLUMNS)
    metadata_keys = _keys(metadata_rows)
    metadata = {key: row for key, row in zip(metadata_keys, metadata_rows, strict=True)}
    _validate_full_metadata_chronology(metadata)
    labels_binding = _binding(document.get("labels"), label="campaign labels")

    qualified_cohorts = _qualified_records(qualification, "cohorts")
    cohort_keys: dict[int, tuple[tuple[str, str], ...]] = {}
    records = document.get("cohorts")
    if not isinstance(records, list):
        raise CampaignArtifactError("input manifest cohorts must be a list")
    for record in records:
        year = int(record["year"])
        if record != qualified_cohorts.get(year):
            raise CampaignArtifactError(f"cohort {year} differs from qualification")
        artifact = _binding(record, label=f"cohort {year}")
        keys = _keys(_read_csv(artifact.path, KEY_COLUMNS), year=year)
        _validate_binding_counts(record, keys, label=f"cohort {year}")
        _validate_qualified_source_seasons(metadata, keys, label=f"cohort {year}")
        cohort_keys[year] = keys
    if set(cohort_keys) != set(config.raw_years):
        raise CampaignArtifactError("cohort inventory must cover exactly raw years")

    qualified_selection = _qualified_records(qualification, "selection_cohorts")
    selection_keys: dict[int, dict[int, tuple[tuple[str, str], ...]]] = {}
    selection_records = document.get("selection_cohorts")
    if not isinstance(selection_records, list):
        raise CampaignArtifactError("input manifest selection_cohorts must be a list")
    expected_selection = {
        (outer, source) for outer in config.target_years for source in range(outer - 3, outer)
    }
    for record in selection_records:
        outer = int(record["outer_year"])
        source = int(record["source_year"])
        key = (outer, source)
        if record != qualified_selection.get(key):
            raise CampaignArtifactError(f"selection cohort {key} differs from qualification")
        artifact = _binding(record, label=f"selection cohort {key}")
        keys = _keys(_read_csv(artifact.path, KEY_COLUMNS), year=source)
        _validate_binding_counts(record, keys, label=f"selection cohort {key}")
        cutoff = dt.date(source, 12, 30)
        derived = tuple(
            item
            for item in cohort_keys[source]
            if dt.date.fromisoformat(metadata[item]["match_date"]) <= cutoff
        )
        if keys != derived:
            raise CampaignArtifactError(f"selection cohort {key} differs from Dec-30 derivation")
        selection_keys.setdefault(outer, {})[source] = keys
    if (
        set(qualified_selection) != expected_selection
        or {(outer, source) for outer, years in selection_keys.items() for source in years}
        != expected_selection
    ):
        raise CampaignArtifactError("selection inventory is incomplete")

    qualified_priced = _qualified_records(qualification, "priced_cohorts")
    priced_keys: dict[int, tuple[tuple[str, str], ...]] = {}
    priced_records = document.get("priced_cohorts")
    if not isinstance(priced_records, list):
        raise CampaignArtifactError("input manifest priced_cohorts must be a list")
    for record in priced_records:
        year = int(record["year"])
        if record != qualified_priced.get(year):
            raise CampaignArtifactError(f"priced cohort {year} differs from qualification")
        artifact = _binding(record, label=f"priced cohort {year}")
        keys = _keys(_read_csv(artifact.path, KEY_COLUMNS), year=year)
        _validate_binding_counts(record, keys, label=f"priced cohort {year}")
        if not set(keys) <= set(cohort_keys[year]):
            raise CampaignArtifactError(f"priced cohort {year} is not a target subset")
        priced_keys[year] = keys
    if set(priced_keys) != set(config.target_years):
        raise CampaignArtifactError("priced cohort inventory must cover target years")

    qualified_incumbent = _qualified_records(qualification, "incumbent")
    incumbent: dict[int, PredictionArtifact] = {}
    incumbent_records = document.get("incumbent")
    if not isinstance(incumbent_records, list):
        raise CampaignArtifactError("input manifest incumbent must be a list")
    for record in incumbent_records:
        year = int(record["year"])
        if record != qualified_incumbent.get(year):
            raise CampaignArtifactError(f"incumbent {year} differs from qualification")
        artifact = _load_prediction(record["prediction"], year=year, label=f"incumbent {year}")
        if artifact.keys != cohort_keys[year]:
            raise CampaignArtifactError(f"incumbent {year} membership differs from cohort")
        if record.get("procedure") != "unchanged_incumbent_selected_calibrated_hgb":
            raise CampaignArtifactError(f"incumbent {year} procedure drift")
        incumbent[year] = artifact
    if set(incumbent) != set(config.target_years):
        raise CampaignArtifactError("incumbent inventory must cover target years")

    member_contracts = config.producer_plan.get("member_contracts")
    year_contracts = config.producer_plan.get("year_contracts")
    if not isinstance(member_contracts, list) or not isinstance(year_contracts, list):
        raise CampaignArtifactError("producer plan member/year contracts must be lists")
    plan_members = {item["member_id"]: item for item in member_contracts}
    plan_years = {int(item["prediction_year"]): item for item in year_contracts}
    if (
        len(member_contracts) != len(plan_members)
        or len(year_contracts) != len(plan_years)
        or set(plan_members) != set(MEMBER_IDS)
        or set(plan_years) != set(config.raw_years)
    ):
        raise CampaignArtifactError("producer plan member/year inventory drift")
    expected_specs = {item.member_id: item for item in member_specs(config.tour)}
    for member_id, planned in plan_members.items():
        spec = expected_specs[member_id]
        if any(
            planned.get(field) != expected
            for field, expected in (
                ("kind", spec.kind),
                ("learner", spec.learner),
                ("candidate_id", spec.candidate_id),
                ("feature_bundle", spec.feature_bundle),
            )
        ):
            raise CampaignArtifactError(f"producer plan fixed member drift: {member_id}")
        if spec.kind == "deterministic" and (
            planned.get("estimator_config") is not None
            or planned.get("resolved_estimator_params") is not None
        ):
            raise CampaignArtifactError(f"deterministic member has estimator settings: {member_id}")
    for year, planned in plan_years.items():
        expected_start = f"{max(2011, year - 5):04d}-01-01"
        expected_through = f"{year - 1:04d}-12-30"
        if (
            planned.get("fit_start") != expected_start
            or planned.get("fit_through") != expected_through
            or planned.get("raw_prediction_membership") != qualified_cohorts.get(year)
            or not isinstance(planned.get("training_membership"), Mapping)
            or not isinstance(planned.get("state_receipts"), list)
            or not planned["state_receipts"]
            or not isinstance(planned.get("offset_receipts"), list)
            or (config.tour == "ATP" and not planned["offset_receipts"])
            or (config.tour == "WTA" and bool(planned["offset_receipts"]))
        ):
            raise CampaignArtifactError(f"producer plan year contract drift: {year}")
        if config.document["execution_scope"] == "frozen_real_inputs":
            training_keys, _ = _training_membership(
                planned["training_membership"],
                year=year,
                fit_start=planned["fit_start"],
                fit_through=planned["fit_through"],
                label=f"producer plan {year} numerical training membership",
            )
            _validate_qualified_source_seasons(
                metadata,
                training_keys,
                label=f"producer plan {year} numerical training membership",
            )
    raw_members: dict[tuple[int, str], PredictionArtifact] = {}
    raw_records = document.get("raw_members")
    if not isinstance(raw_records, list):
        raise CampaignArtifactError("input manifest raw_members must be a list")
    for record in raw_records:
        year = int(record["year"])
        member_id = str(record["member_id"])
        key = (year, member_id)
        if member_id not in plan_members or year not in plan_years or key in raw_members:
            raise CampaignArtifactError(f"unexpected/duplicate raw member: {key}")
        _validate_raw_producer(
            config,
            record,
            year=year,
            member_id=member_id,
            plan_member=plan_members[member_id],
            plan_year=plan_years[year],
        )
        artifact = _load_prediction(
            record["prediction"], year=year, label=f"raw member {year}/{member_id}"
        )
        if artifact.keys != cohort_keys[year]:
            raise CampaignArtifactError(f"raw member {year}/{member_id} membership differs")
        raw_members[key] = PredictionArtifact(
            artifact.year,
            artifact.keys,
            artifact.probabilities,
            artifact.binding,
            dict(record),
        )
    expected_raw = {(year, member_id) for year in config.raw_years for member_id in MEMBER_IDS}
    if set(raw_members) != expected_raw:
        raise CampaignArtifactError("raw member inventory is not the exact eight-member menu")

    if config.document["execution_scope"] == "frozen_real_inputs":
        expected = config.document.get("expected_population")
        if expected != EXPECTED_POPULATION[config.tour]:
            raise CampaignArtifactError("real population contract differs from reviewed constants")
        observed_rows = sum(len(cohort_keys[year]) for year in config.target_years)
        observed_priced = sum(len(priced_keys[year]) for year in config.target_years)
        if not isinstance(expected, Mapping) or expected.get("target_rows") != observed_rows:
            raise CampaignArtifactError("real target population differs from qualified count")
        if expected.get("priced_rows") != observed_priced:
            raise CampaignArtifactError("real priced population differs from qualified count")
    return CampaignInputs(
        document=document,
        qualification=qualification,
        metadata=metadata,
        metadata_binding=metadata_binding,
        labels_binding=labels_binding,
        cohort_keys=cohort_keys,
        selection_keys=selection_keys,
        priced_keys=priced_keys,
        incumbent=incumbent,
        raw_members=raw_members,
    )


def load_quotes(config: CampaignConfig, inputs: CampaignInputs) -> QuoteArtifact:
    """Post-barrier-only raw decimal quote validation and normalization."""
    rows = _read_csv(config.raw_quotes_path, RAW_QUOTE_COLUMNS)
    keys = _keys(rows)
    expected_all = tuple(key for year in config.target_years for key in inputs.cohort_keys[year])
    if keys != expected_all:
        raise CampaignArtifactError("raw quote artifact differs from target membership")
    priced = {key for year in config.target_years for key in inputs.priced_keys[year]}
    probabilities: dict[tuple[str, str], float] = {}
    for row, key in zip(rows, keys, strict=True):
        expected_valid = key in priced
        if row["valid"] not in {"true", "false"} or (row["valid"] == "true") != expected_valid:
            raise CampaignArtifactError(
                f"raw quote validity differs from qualified subset at {key}"
            )
        if not expected_valid:
            if row["decimal_a"] or row["decimal_b"]:
                raise CampaignArtifactError(f"unpriced row carries quotes at {key}")
            continue
        try:
            decimal_a = float(row["decimal_a"])
            decimal_b = float(row["decimal_b"])
            source_row = int(row["market_source_row"])
        except ValueError as error:
            raise CampaignArtifactError(f"invalid raw quote at {key}") from error
        source_path_text = row["market_source_path"]
        source_sha256 = require_nonempty_digest(
            row["market_source_sha256"], label=f"quote source {key}"
        )
        source_path = resolve_under_root(source_path_text, label=f"quote source {key}")
        if (
            not math.isfinite(decimal_a)
            or not math.isfinite(decimal_b)
            or decimal_a <= 1.0
            or decimal_b <= 1.0
            or source_row <= 0
            or not source_path_text
            or not source_path.is_file()
            or sha256(source_path) != source_sha256
        ):
            raise CampaignArtifactError(f"invalid raw quote/provenance at {key}")
        probability = (1.0 / decimal_a) / ((1.0 / decimal_a) + (1.0 / decimal_b))
        if not 0.0 < probability < 1.0:
            raise CampaignArtifactError(f"invalid normalized quote at {key}")
        probabilities[key] = probability
    if set(probabilities) != priced:
        raise CampaignArtifactError("normalized quote keys differ from qualified priced subset")
    return QuoteArtifact(
        probabilities,
        inputs.priced_keys,
        ArtifactBinding(config.raw_quotes_path, config.raw_quotes_sha256),
    )


def read_target_labels(inputs: CampaignInputs) -> dict[tuple[str, str], int]:
    rows = _read_csv(inputs.labels_binding.path, LABEL_COLUMNS)
    output: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["source_season"], row["match_id"])
        if key in output:
            raise CampaignArtifactError(f"duplicate target label key: {key}")
        if row["a_won"] not in {"0", "1"}:
            raise CampaignArtifactError(f"invalid target label at {key}")
        if key in inputs.metadata:
            for field in METADATA_FIELDS:
                if row[field] != inputs.metadata[key][field]:
                    raise CampaignArtifactError(f"metadata/label {field} drift at {key}")
        output[key] = int(row["a_won"])
    return output
