"""Typed completion, semantic disclosure scan, and hash freeze for Lane E."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tennislab.campaign.artifacts import load_inputs
from tennislab.campaign.contracts import CampaignConfig, config_receipt
from tennislab.campaign.stages import (
    BARRIER_COMPLETION_SCHEMA,
    FORECAST_ANCHOR_SCHEMA,
    FORECAST_COMPLETION_SCHEMA,
    forecast_inventory_contract,
    inventory_contract_map,
    inventory_sha256,
    read_object,
    require_completion,
    validate_typed_inventory,
)
from tennislab.chain import barrier_scan
from tennislab.chain.common import atomic_json, canonical_hash_nonempty, resolve_under_root, sha256


class CampaignBarrierError(ValueError):
    """A producer/forecast tree cannot be frozen or no longer matches its barrier."""


def hash_tree(directory: Path, root: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise CampaignBarrierError(f"missing campaign stage: {directory}")
    records: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise CampaignBarrierError(f"campaign tree contains a symlink: {path}")
        if path.is_file():
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
    if not records:
        raise CampaignBarrierError(f"campaign stage is empty: {directory}")
    return records


def read_forecast_completion(config: CampaignConfig, output_root: Path) -> dict[str, Any]:
    path = output_root / "forecast" / "forecast_manifest.json"
    document = read_object(path, label="forecast completion")
    try:
        require_completion(document, schema=FORECAST_COMPLETION_SCHEMA, stage="forecast")
    except ValueError as error:
        raise CampaignBarrierError(str(error)) from error
    if document.get("config_sha256") != config.sha256:
        raise CampaignBarrierError("forecast completion/config binding drift")
    if document.get("producer_plan", {}).get("sha256") != config.producer_plan_sha256:
        raise CampaignBarrierError("forecast completion/producer-plan binding drift")
    if document.get("producer_completion", {}).get("sha256") != config.producer_completion_sha256:
        raise CampaignBarrierError("forecast completion/producer binding drift")
    if document.get("target_years") != list(config.target_years):
        raise CampaignBarrierError("forecast completion target-year drift")
    if document.get("attempt_id") != config.document["attempt_id"]:
        raise CampaignBarrierError("forecast completion attempt drift")
    expected = inventory_contract_map(
        forecast_inventory_contract(config.target_years), label="forecast inventory"
    )
    try:
        records = validate_typed_inventory(
            document.get("artifacts"),
            root=output_root,
            inventory_root=output_root / "forecast",
            expected=expected,
            label="forecast completion",
            ignored_paths=("forecast/forecast_manifest.json",),
        )
    except ValueError as error:
        raise CampaignBarrierError(str(error)) from error
    if document.get("inventory_sha256") != inventory_sha256(records):
        raise CampaignBarrierError("forecast completion inventory commitment drift")
    return document


def _forecast_anchor(config: CampaignConfig, output_root: Path) -> tuple[Path, dict[str, Any]]:
    path = output_root / "attempts" / f"forecast_{config.document['attempt_id']}.json"
    document = read_object(path, label="forecast attempt anchor")
    try:
        require_completion(
            document,
            schema=FORECAST_ANCHOR_SCHEMA,
            stage="forecast_attempt_anchor",
        )
    except ValueError as error:
        raise CampaignBarrierError(str(error)) from error
    if document.get("attempt_id") != config.document["attempt_id"]:
        raise CampaignBarrierError("forecast attempt anchor id drift")
    if document.get("config_sha256") != config.sha256:
        raise CampaignBarrierError("forecast attempt anchor config drift")
    if document.get("producer_plan_sha256") != config.producer_plan_sha256:
        raise CampaignBarrierError("forecast attempt anchor plan drift")
    if document.get("producer_completion_sha256") != config.producer_completion_sha256:
        raise CampaignBarrierError("forecast attempt anchor producer drift")
    completion = document.get("forecast_completion")
    forecast_path = output_root / "forecast" / "forecast_manifest.json"
    if completion != {
        "path": "forecast/forecast_manifest.json",
        "sha256": sha256(forecast_path),
    }:
        raise CampaignBarrierError("forecast completion differs from original attempt anchor")
    return path, document


def _scan_prebarrier(config: CampaignConfig, output_root: Path) -> dict[str, Any]:
    forecast_scan = barrier_scan.scan_tree(output_root, ["forecast"], include_objective=True)
    workspace = resolve_under_root(".", label="workspace")
    producer_root = resolve_under_root(
        str(config.producer_plan["producer_root"]), label="producer root"
    )
    producer_scan = barrier_scan.scan_tree(
        workspace,
        [producer_root.relative_to(workspace).as_posix()],
        include_objective=True,
    )
    allowed_binary = {
        str(record["path"])
        for record in config.producer_completion["artifacts"]
        if record.get("media_type") == "application/x-joblib"
        and record.get("schema") == "campaign_fitted_model/v1"
    }
    producer_scan["uninspected"] = [
        path for path in producer_scan["uninspected"] if path not in allowed_binary
    ]
    return {
        "findings": [*forecast_scan["findings"], *producer_scan["findings"]],
        "scanned": [*forecast_scan["scanned"], *producer_scan["scanned"]],
        "uninspected": [*forecast_scan["uninspected"], *producer_scan["uninspected"]],
        "allowed_typed_binary_models": sorted(allowed_binary),
    }


def run_barrier(config: CampaignConfig, output_root: Path) -> dict[str, Any]:
    load_inputs(config)
    read_forecast_completion(config, output_root)
    anchor_path, _ = _forecast_anchor(config, output_root)
    stage = output_root / "barrier"
    if stage.exists():
        raise CampaignBarrierError(f"barrier stage already exists: {stage}")
    scan = _scan_prebarrier(config, output_root)
    if scan["findings"]:
        raise CampaignBarrierError(
            f"performance-shaped content exists before barrier: {scan['findings']}"
        )
    if scan["uninspected"]:
        raise CampaignBarrierError(f"uninspected pre-barrier artifacts: {scan['uninspected']}")
    tree = hash_tree(output_root / "forecast", output_root)
    producer_inventory = config.producer_completion["artifacts"]
    manifest = {
        "schema": BARRIER_COMPLETION_SCHEMA,
        "status": "complete",
        "stage": "barrier",
        **config_receipt(config),
        "attempt_id": config.document["attempt_id"],
        "forecast_completion": {
            "path": "forecast/forecast_manifest.json",
            "sha256": sha256(output_root / "forecast" / "forecast_manifest.json"),
        },
        "forecast_attempt_anchor": {
            "path": anchor_path.relative_to(output_root).as_posix(),
            "sha256": sha256(anchor_path),
        },
        "forecast_tree": tree,
        "forecast_tree_sha256": canonical_hash_nonempty(tree, label="forecast tree"),
        "producer_inventory_sha256": inventory_sha256(producer_inventory),
        "content_scan": scan,
        "target_outcomes_read_or_scored": False,
    }
    stage.mkdir(parents=True)
    path = stage / "barrier_manifest.json"
    atomic_json(path, manifest)
    manifest["barrier_manifest_sha256"] = sha256(path)
    return manifest


def verify_barrier(config: CampaignConfig, output_root: Path) -> dict[str, Any]:
    load_inputs(config)
    read_forecast_completion(config, output_root)
    anchor_path, _ = _forecast_anchor(config, output_root)
    path = output_root / "barrier" / "barrier_manifest.json"
    document = read_object(path, label="barrier completion")
    try:
        require_completion(document, schema=BARRIER_COMPLETION_SCHEMA, stage="barrier")
    except ValueError as error:
        raise CampaignBarrierError(str(error)) from error
    if document.get("config_sha256") != config.sha256:
        raise CampaignBarrierError("barrier completion/config binding drift")
    if document.get("forecast_completion") != {
        "path": "forecast/forecast_manifest.json",
        "sha256": sha256(output_root / "forecast" / "forecast_manifest.json"),
    }:
        raise CampaignBarrierError("barrier/forecast completion binding drift")
    if document.get("forecast_attempt_anchor") != {
        "path": anchor_path.relative_to(output_root).as_posix(),
        "sha256": sha256(anchor_path),
    }:
        raise CampaignBarrierError("barrier/attempt anchor binding drift")
    if document.get("producer_inventory_sha256") != inventory_sha256(
        config.producer_completion["artifacts"]
    ):
        raise CampaignBarrierError("barrier/producer inventory binding drift")
    tree = hash_tree(output_root / "forecast", output_root)
    if tree != document.get("forecast_tree"):
        raise CampaignBarrierError("forecast tree differs from the frozen barrier")
    if canonical_hash_nonempty(tree, label="forecast tree") != document.get("forecast_tree_sha256"):
        raise CampaignBarrierError("forecast tree commitment drift")
    scan = _scan_prebarrier(config, output_root)
    if scan["findings"] or scan["uninspected"] or scan != document.get("content_scan"):
        raise CampaignBarrierError("pre-barrier trees no longer pass the frozen content scan")
    actual_barrier = [item for item in (output_root / "barrier").rglob("*") if item.is_file()]
    if actual_barrier != [path] or any(
        item.is_symlink() for item in (output_root / "barrier").rglob("*")
    ):
        raise CampaignBarrierError("barrier stage inventory drift")
    return document
