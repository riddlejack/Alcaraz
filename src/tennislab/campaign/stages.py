"""Strict typed completion inventories for the Lane E producer/consumer DAG."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    canonical_hash_nonempty,
    relative_to_root,
    require_nonempty_digest,
    resolve_under_root,
    sha256,
)

PRODUCER_PLAN_SCHEMA = "campaign_producer_plan/v1"
PRODUCER_COMPLETION_SCHEMA = "campaign_producer_completion/v1"
CONSUMER_CONFIG_SCHEMA = "campaign_consumer_config/v1"
INPUT_MANIFEST_SCHEMA = "campaign_input_manifest/v1"
QUALIFICATION_SCHEMA = "campaign_population_qualification/v1"
INDEPENDENT_REVIEW_SCHEMA = "campaign_independent_review/v1"
RAW_MEMBER_SCHEMA = "campaign_raw_member_completion/v1"
FORECAST_COMPLETION_SCHEMA = "campaign_forecast_completion/v1"
BARRIER_COMPLETION_SCHEMA = "campaign_barrier_completion/v1"
REPORT_COMPLETION_SCHEMA = "campaign_report_completion/v1"
FORECAST_ANCHOR_SCHEMA = "campaign_forecast_attempt_anchor/v1"

MEDIA_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".joblib": "application/x-joblib",
    ".md": "text/markdown",
}
KEYED_SCHEMAS = frozenset(
    {
        "campaign_training_membership/v1",
        "campaign_prediction_features/v1",
        "campaign_raw_prediction/v1",
        "campaign_forecast_rows/v1",
    }
)


class CampaignStageError(ValueError):
    """A typed stage, completion status, inventory, or confined path drifted."""


def _inventory_spec(
    path: str, schema: str, role: str, media_type: str, **logical_key: Any
) -> dict[str, Any]:
    return {
        "path": path,
        "schema": schema,
        "logical_key": {"role": role, **logical_key},
        "media_type": media_type,
    }


def forecast_inventory_contract(target_years: Sequence[int]) -> list[dict[str, Any]]:
    """Derive the complete forecast-stage inventory from the fixed target years."""
    records = [
        record
        for year in target_years
        for record in (
            _inventory_spec(
                f"forecast/forecasts/{int(year)}.csv",
                "campaign_forecast_rows/v1",
                "forecast_rows",
                "text/csv",
                outer_year=int(year),
            ),
            _inventory_spec(
                f"forecast/decisions/{int(year)}.json",
                "campaign_fold_decision/v1",
                "fold_decision",
                "application/json",
                outer_year=int(year),
            ),
        )
    ]
    records.append(
        _inventory_spec(
            "forecast/exposure.json",
            "campaign_forecast_exposure/v1",
            "exposure",
            "application/json",
        )
    )
    return records


def report_inventory_contract() -> list[dict[str, Any]]:
    """Return the mandatory report-stage roles fixed by the executable contract."""
    return [
        _inventory_spec(
            "report/annual.csv", "campaign_annual_scores/v1", "annual_scores", "text/csv"
        ),
        _inventory_spec("report/bootstrap.csv", "campaign_bootstrap/v1", "bootstrap", "text/csv"),
        _inventory_spec(
            "report/calibration.csv", "campaign_calibration/v1", "calibration", "text/csv"
        ),
        _inventory_spec(
            "report/priced.csv", "campaign_priced_scores/v1", "priced_scores", "text/csv"
        ),
        _inventory_spec(
            "report/fit_criteria.json",
            "campaign_fit_criteria/v1",
            "fit_criteria",
            "application/json",
        ),
        _inventory_spec(
            "report/summary.json", "campaign_summary/v1", "summary", "application/json"
        ),
        _inventory_spec(
            "report/report.md", "campaign_short_report/v1", "short_report", "text/markdown"
        ),
        _inventory_spec(
            "report/exposure.json",
            "campaign_report_exposure/v1",
            "exposure",
            "application/json",
        ),
        _inventory_spec(
            "report/recomputation.json",
            "campaign_recomputation/v1",
            "recomputation",
            "application/json",
        ),
        _inventory_spec(
            "report/sensitivities.json",
            "campaign_sensitivities/v1",
            "sensitivities",
            "application/json",
        ),
        _inventory_spec(
            "report/clip_counts.json",
            "campaign_clip_counts/v1",
            "clip_counts",
            "application/json",
        ),
        _inventory_spec(
            "report/attempt_inventory.json",
            "campaign_attempt_inventory/v1",
            "attempts",
            "application/json",
        ),
    ]


def inventory_contract_map(
    records: Sequence[Mapping[str, Any]], *, label: str
) -> dict[str, tuple[str, Mapping[str, Any], str]]:
    """Normalize a trusted contract inventory for typed-tree validation."""
    output: dict[str, tuple[str, Mapping[str, Any], str]] = {}
    for record in records:
        path = str(record.get("path", ""))
        if not path or path in output:
            raise CampaignStageError(f"duplicate/blank {label} path")
        output[path] = (
            str(record.get("schema", "")),
            dict(record.get("logical_key", {})),
            str(record.get("media_type", "")),
        )
    return output


def read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CampaignStageError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise CampaignStageError(f"{label} must be an object")
    return value


def binding(value: Any, *, label: str) -> tuple[Path, str]:
    if not isinstance(value, Mapping):
        raise CampaignStageError(f"{label} binding must be an object")
    path = resolve_under_root(str(value.get("path", "")), label=label)
    digest = require_nonempty_digest(value.get("sha256"), label=f"{label}.sha256")
    if sha256(path) != digest:
        raise CampaignStageError(f"{label} hash mismatch")
    return path, digest


def require_completion(
    document: Mapping[str, Any], *, schema: str, stage: str | None = None
) -> None:
    if document.get("schema") != schema:
        raise CampaignStageError(f"completion schema must be {schema}")
    if document.get("status") != "complete":
        raise CampaignStageError(f"{schema} status must be complete")
    if stage is not None and document.get("stage") != stage:
        raise CampaignStageError(f"{schema} stage must be {stage}")


def typed_artifact(
    path: Path,
    *,
    schema: str,
    logical_key: Mapping[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    suffix = ".csv" if path.name.endswith(".csv") else path.suffix.lower()
    media_type = MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise CampaignStageError(f"no media type for typed artifact: {path}")
    relative = (
        path.relative_to(root).as_posix()
        if root is not None
        else relative_to_root(path, label="typed artifact")
    )
    record: dict[str, Any] = {
        "path": relative,
        "sha256": sha256(path),
        "media_type": media_type,
        "schema": schema,
        "logical_key": dict(logical_key),
        "status": "complete",
    }
    if schema in KEYED_SCHEMAS:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            if header[:2] != ("season", "match_id"):
                raise CampaignStageError(f"keyed artifact header drift: {path}")
            keys = [(str(row["season"]), str(row["match_id"])) for row in reader]
        if not keys or len(keys) != len(set(keys)):
            raise CampaignStageError(f"keyed artifact membership is empty/duplicated: {path}")
        record["rows"] = len(keys)
        record["membership_sha256"] = hashlib.sha256(
            "".join(f"{season},{match_id}\n" for season, match_id in keys).encode()
        ).hexdigest()
    return record


def validate_typed_inventory(
    records: Any,
    *,
    root: Path,
    inventory_root: Path,
    expected: Mapping[str, tuple[str, Mapping[str, Any], str]],
    label: str,
    ignored_paths: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Validate exact paths, types, logical keys, hashes, confinement and tree coverage.

    ``expected`` maps paths relative to ``root`` to
    ``(schema, logical_key, media_type)``. The manifest itself lives outside the
    inventoried directory and is therefore not listed.
    """
    if not isinstance(records, list):
        raise CampaignStageError(f"{label} artifacts must be a list")
    observed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(records):
        if not isinstance(item, Mapping):
            raise CampaignStageError(f"{label} artifact {index} must be an object")
        record = dict(item)
        path_text = record.get("path")
        if not isinstance(path_text, str) or not path_text:
            raise CampaignStageError(f"{label} artifact {index} path must be nonempty")
        if path_text in observed:
            raise CampaignStageError(f"duplicate {label} artifact: {path_text}")
        required_fields = {
            "path",
            "sha256",
            "media_type",
            "schema",
            "logical_key",
            "status",
        }
        if record.get("schema") in KEYED_SCHEMAS:
            required_fields |= {"rows", "membership_sha256"}
            if not isinstance(record.get("rows"), int) or record["rows"] <= 0:
                raise CampaignStageError(f"{label} keyed artifact row-count drift: {path_text}")
            require_nonempty_digest(
                record.get("membership_sha256"),
                label=f"{label}.{path_text}.membership_sha256",
            )
        if set(record) != required_fields:
            raise CampaignStageError(f"{label} artifact fields drift: {path_text}")
        if record["status"] != "complete":
            raise CampaignStageError(f"{label} artifact is not complete: {path_text}")
        if path_text not in expected:
            raise CampaignStageError(f"undeclared {label} artifact: {path_text}")
        expected_schema, expected_key, expected_media = expected[path_text]
        if record["schema"] != expected_schema:
            raise CampaignStageError(f"{label} artifact schema drift: {path_text}")
        if record["logical_key"] != dict(expected_key):
            raise CampaignStageError(f"{label} artifact logical key drift: {path_text}")
        if record["media_type"] != expected_media:
            raise CampaignStageError(f"{label} artifact media type drift: {path_text}")
        digest = require_nonempty_digest(record["sha256"], label=f"{label}.{path_text}")
        path = root / path_text
        try:
            path.relative_to(inventory_root)
        except ValueError as error:
            raise CampaignStageError(f"{label} artifact escapes its stage: {path_text}") from error
        current = inventory_root
        for part in path.relative_to(inventory_root).parts:
            current = current / part
            if current.is_symlink():
                raise CampaignStageError(f"{label} artifact passes through symlink: {path_text}")
        if not path.is_file() or sha256(path) != digest:
            raise CampaignStageError(f"{label} artifact hash drift: {path_text}")
        if record["schema"] in KEYED_SCHEMAS:
            independently_observed = typed_artifact(
                path,
                schema=str(record["schema"]),
                logical_key=dict(record["logical_key"]),
                root=root,
            )
            for field in ("rows", "membership_sha256"):
                if record[field] != independently_observed[field]:
                    raise CampaignStageError(f"{label} keyed artifact {field} drift: {path_text}")
        observed[path_text] = record
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        raise CampaignStageError(f"{label} inventory mismatch; missing={missing}, extra={extra}")
    actual: set[str] = set()
    if not inventory_root.is_dir():
        raise CampaignStageError(f"missing {label} directory: {inventory_root}")
    if inventory_root.is_symlink():
        raise CampaignStageError(f"{label} directory is a symlink: {inventory_root}")
    for path in inventory_root.rglob("*"):
        if path.is_symlink():
            raise CampaignStageError(f"{label} tree contains symlink: {path}")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    actual -= set(ignored_paths)
    if actual != set(expected):
        raise CampaignStageError(
            f"{label} tree differs from typed inventory; "
            f"missing={sorted(set(expected) - actual)}, undeclared={sorted(actual - set(expected))}"
        )
    return [observed[path] for path in sorted(observed)]


def inventory_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    normalized = sorted((dict(record) for record in records), key=lambda item: str(item["path"]))
    return canonical_hash_nonempty(normalized, label="typed inventory")
