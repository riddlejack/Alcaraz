"""Bounded EC-01 metadata and producer/consumer code-transition regression."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from tennislab.campaign.artifacts import (
    CampaignArtifactError,
    _validate_full_metadata_chronology,
    _validate_qualified_source_seasons,
    load_inputs,
)
from tennislab.campaign.contracts import (
    CAMPAIGN_MODULES,
    CONSUMER_CODE_AUTHORIZATION_SCHEMA,
    EC01_AUTHORIZATION_ID,
    EC01_AUTHORIZED_SEMANTICS,
    EC01_CHANGED_MODULES,
    EC01_COMPLETION_REVIEW_SHA256,
    EC01_TRANSITION_ID,
    CampaignConfigError,
    _validate_consumer_code_transition,
    code_bindings,
    code_inventory_sha256,
    load_campaign_config,
)
from tennislab.campaign.synthetic import prepare_rehearsal
from tennislab.chain.common import sha256
from tennislab.config import reset_workspace_cache

PLAN_SHA256 = "1" * 64
COMPLETION_SHA256 = "2" * 64
SUCCESSOR_COMMIT = "a" * 40


def _write(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _binding(path: Path, workspace: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256(path),
    }


def _metadata_row(**updates: str) -> dict[str, str]:
    row = {
        "season": "2007",
        "match_id": "2008-339/10",
        "calendar_year": "2007",
        "source_season": "2008",
        "match_date": "2007-12-31",
        "eligible_through_date": "2007-12-29",
        "elo_overall_logit": "0.1",
        "elo_surface_logit": "-0.2",
    }
    row.update(updates)
    return row


def _transition_fixture(
    workspace: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
    Path,
]:
    consumer_code = code_bindings()
    producer_code = copy.deepcopy(consumer_code)
    for module, digit in zip(EC01_CHANGED_MODULES, ("c", "d"), strict=True):
        producer_code[module]["sha256"] = digit * 64
    authorization = {
        "schema": CONSUMER_CODE_AUTHORIZATION_SCHEMA,
        "stage": "consumer_code_authorization",
        "status": "accepted",
        "authorization_id": EC01_AUTHORIZATION_ID,
        "transition_id": EC01_TRANSITION_ID,
        "tour": "ATP",
        "producer_plan_sha256": PLAN_SHA256,
        "producer_completion_sha256": COMPLETION_SHA256,
        "producer_code_inventory_sha256": code_inventory_sha256(producer_code),
        "successor_code_inventory_sha256": code_inventory_sha256(consumer_code),
        "successor_commit": SUCCESSOR_COMMIT,
        "changed_modules": list(EC01_CHANGED_MODULES),
        "completion_review_sha256": EC01_COMPLETION_REVIEW_SHA256,
        "authorized_semantics": EC01_AUTHORIZED_SEMANTICS,
    }
    authorization_path = workspace / "authorization.json"
    _write(authorization_path, authorization)
    repair_review_path = workspace / "repair_review.md"
    repair_review_path.write_text("# Test-only EC-01 repair review\n", encoding="utf-8")
    document: dict[str, object] = {
        "consumer_source_commit": SUCCESSOR_COMMIT,
        "consumer_code_authorization": _binding(authorization_path, workspace),
    }
    review: dict[str, object] = {
        "consumer_code_transition": EC01_TRANSITION_ID,
        "consumer_code_authorization_sha256": sha256(authorization_path),
        "successor_code_inventory_sha256": code_inventory_sha256(consumer_code),
        "successor_commit": SUCCESSOR_COMMIT,
        "repair_review": _binding(repair_review_path, workspace),
    }
    return document, review, producer_code, consumer_code, authorization_path


def _validate_transition_fixture(
    document: dict[str, object],
    review: dict[str, object],
    producer_code: dict[str, dict[str, str]],
    consumer_code: dict[str, dict[str, str]],
) -> None:
    _validate_consumer_code_transition(
        document=document,
        review=review,
        tour="ATP",
        producer_plan_sha256=PLAN_SHA256,
        producer_completion_sha256=COMPLETION_SHA256,
        producer_code=producer_code,
        consumer_code=consumer_code,
    )


def test_excluded_source_season_crossover_retains_full_metadata_chronology() -> None:
    key = ("2007", "2008-339/10")
    _validate_full_metadata_chronology({key: _metadata_row()})


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"calendar_year": "2008"}, "calendar-key drift"),
        ({"match_date": "2008-01-01"}, "invalid campaign metadata"),
        ({"eligible_through_date": "2008-01-01"}, "invalid campaign metadata"),
        ({"source_season": "not-a-year"}, "invalid campaign metadata"),
    ),
)
def test_full_metadata_still_rejects_chronology_and_eligibility_drift(
    updates: dict[str, str], message: str
) -> None:
    key = ("2007", "2008-339/10")
    with pytest.raises(CampaignArtifactError, match=message):
        _validate_full_metadata_chronology({key: _metadata_row(**updates)})


def test_crossover_admitted_to_qualified_membership_is_rejected() -> None:
    key = ("2007", "2008-339/10")
    with pytest.raises(CampaignArtifactError, match="source-season crossover"):
        _validate_qualified_source_seasons(
            {key: _metadata_row()},
            (key,),
            label="qualified raw cohort 2007",
        )


def test_exact_ec01_code_transition_binding_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    document, review, producer_code, consumer_code, _ = _transition_fixture(tmp_path)
    _validate_transition_fixture(document, review, producer_code, consumer_code)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema", "campaign_consumer_code_authorization/v2"),
        ("status", "pending"),
        ("authorization_id", "D90"),
        ("transition_id", "EC-02"),
        ("tour", "WTA"),
        ("producer_plan_sha256", "3" * 64),
        ("producer_completion_sha256", "4" * 64),
        ("completion_review_sha256", "5" * 64),
        (
            "changed_modules",
            [*EC01_CHANGED_MODULES, "tennislab.campaign.runner"],
        ),
    ),
)
def test_incorrect_root_authorization_fields_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    document, review, producer_code, consumer_code, authorization_path = _transition_fixture(
        tmp_path
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization[field] = value
    _write(authorization_path, authorization)
    document["consumer_code_authorization"] = _binding(authorization_path, tmp_path)
    review["consumer_code_authorization_sha256"] = sha256(authorization_path)
    with pytest.raises(CampaignConfigError, match="does not bind exact EC-01"):
        _validate_transition_fixture(document, review, producer_code, consumer_code)


def test_missing_root_authorization_field_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    document, review, producer_code, consumer_code, authorization_path = _transition_fixture(
        tmp_path
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization.pop("status")
    _write(authorization_path, authorization)
    document["consumer_code_authorization"] = _binding(authorization_path, tmp_path)
    review["consumer_code_authorization_sha256"] = sha256(authorization_path)
    with pytest.raises(CampaignConfigError, match="authorization fields drift"):
        _validate_transition_fixture(document, review, producer_code, consumer_code)


def test_missing_and_hash_mismatched_root_bindings_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    document, review, producer_code, consumer_code, _ = _transition_fixture(tmp_path)
    missing = copy.deepcopy(document)
    missing.pop("consumer_code_authorization")
    with pytest.raises(CampaignConfigError, match="binding must be an object"):
        _validate_transition_fixture(missing, review, producer_code, consumer_code)
    mismatched = copy.deepcopy(document)
    mismatched["consumer_code_authorization"]["sha256"] = "0" * 64
    with pytest.raises(CampaignConfigError, match="hash mismatch"):
        _validate_transition_fixture(mismatched, review, producer_code, consumer_code)


def test_extra_changed_module_is_derived_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    document, review, producer_code, consumer_code, _ = _transition_fixture(tmp_path)
    extra = next(module for module in CAMPAIGN_MODULES if module not in EC01_CHANGED_MODULES)
    producer_code[extra]["sha256"] = "e" * 64
    with pytest.raises(CampaignConfigError, match="does not bind exact EC-01"):
        _validate_transition_fixture(document, review, producer_code, consumer_code)


def test_forged_replacement_authorization_fails_reviewed_digest_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    document, review, producer_code, consumer_code, authorization_path = _transition_fixture(
        tmp_path
    )
    trusted_reviewed_digest = review["consumer_code_authorization_sha256"]
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["successor_commit"] = "f" * 40
    _write(authorization_path, authorization)
    document["consumer_source_commit"] = "f" * 40
    document["consumer_code_authorization"] = _binding(authorization_path, tmp_path)
    assert review["consumer_code_authorization_sha256"] == trusted_reviewed_digest
    with pytest.raises(CampaignConfigError, match="independent review does not bind"):
        _validate_transition_fixture(document, review, producer_code, consumer_code)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("consumer_code_authorization_sha256", "0" * 64),
        ("consumer_code_transition", "EC-02"),
        ("successor_code_inventory_sha256", "0" * 64),
        ("successor_commit", "0" * 40),
        ("repair_review", None),
    ),
)
def test_missing_or_forged_independent_review_binding_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    document, review, producer_code, consumer_code, _ = _transition_fixture(tmp_path)
    review[field] = value
    with pytest.raises((CampaignConfigError, ValueError)):
        _validate_transition_fixture(document, review, producer_code, consumer_code)


def test_pending_consumer_config_remains_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    (tmp_path / "design.md").write_text("# Synthetic campaign contract\n", encoding="utf-8")
    config_path = prepare_rehearsal(Path("work/rehearsal"), Path("design.md"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["status"] = "pending_independent_review"
    _write(config_path, config)
    with pytest.raises(CampaignConfigError, match="not complete"):
        load_campaign_config(config_path)


@pytest.mark.parametrize(
    ("tour", "attempt", "expected_metadata", "expected_crossovers", "expected_raw"),
    (
        ("ATP", "attempt_007", 51_222, 91, 88),
        ("WTA", "attempt_004", 42_485, 160, 72),
    ),
)
def test_exact_completed_graph_accepts_ec01_successor_config(
    monkeypatch: pytest.MonkeyPatch,
    tour: str,
    attempt: str,
    expected_metadata: int,
    expected_crossovers: int,
    expected_raw: int,
) -> None:
    workspace_text = os.environ.get("TENNISLAB_EC01_GRAPH_WORKSPACE")
    if workspace_text is None:
        pytest.skip("set TENNISLAB_EC01_GRAPH_WORKSPACE to the test-only copied graph")
    workspace = Path(workspace_text).resolve()
    pending_path = (
        workspace
        / "work/campaign_e_v1/real"
        / tour.lower()
        / attempt
        / "consumer_config.pending_review.json"
    )
    assert pending_path.is_file()
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(workspace))
    reset_workspace_cache()
    scratch_parent = workspace / "work/ec01_successor_regression"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f"{tour.lower()}_", dir=scratch_parent))
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        plan_path = workspace / pending["producer_plan"]["path"]
        completion_path = workspace / pending["producer_completion"]["path"]
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        consumer_code = code_bindings()
        assert (
            tuple(
                module
                for module in CAMPAIGN_MODULES
                if plan["code"][module] != consumer_code[module]
            )
            == EC01_CHANGED_MODULES
        )
        authorization = {
            "schema": CONSUMER_CODE_AUTHORIZATION_SCHEMA,
            "stage": "consumer_code_authorization",
            "status": "accepted",
            "authorization_id": EC01_AUTHORIZATION_ID,
            "transition_id": EC01_TRANSITION_ID,
            "tour": tour,
            "producer_plan_sha256": sha256(plan_path),
            "producer_completion_sha256": sha256(completion_path),
            "producer_code_inventory_sha256": code_inventory_sha256(plan["code"]),
            "successor_code_inventory_sha256": code_inventory_sha256(consumer_code),
            "successor_commit": SUCCESSOR_COMMIT,
            "changed_modules": list(EC01_CHANGED_MODULES),
            "completion_review_sha256": EC01_COMPLETION_REVIEW_SHA256,
            "authorized_semantics": EC01_AUTHORIZED_SEMANTICS,
        }
        authorization_path = scratch / "TEST_ONLY.root_authorization.json"
        _write(authorization_path, authorization)
        repair_review_path = scratch / "TEST_ONLY.repair_review.md"
        repair_review_path.write_text("# Test-only EC-01 repair review\n", encoding="utf-8")
        review = {
            "schema": "campaign_independent_review/v1",
            "stage": "independent_review",
            "status": "complete",
            "tour": tour,
            "producer_plan_sha256": sha256(plan_path),
            "producer_completion_sha256": sha256(completion_path),
            "qualification_sha256": plan["qualification"]["sha256"],
            "consumer_code_transition": EC01_TRANSITION_ID,
            "consumer_code_authorization_sha256": sha256(authorization_path),
            "successor_code_inventory_sha256": code_inventory_sha256(consumer_code),
            "successor_commit": SUCCESSOR_COMMIT,
            "repair_review": _binding(repair_review_path, workspace),
            "test_only": True,
        }
        review_path = scratch / "TEST_ONLY.independent_review.json"
        _write(review_path, review)
        config = copy.deepcopy(pending)
        config.update(
            status="complete",
            empirical_freeze_status="independently_reviewed_complete",
            code=consumer_code,
            consumer_source_commit=SUCCESSOR_COMMIT,
            consumer_code_authorization=_binding(authorization_path, workspace),
            independent_review=_binding(review_path, workspace),
            output_prefix=(scratch / "run").relative_to(workspace).as_posix(),
        )
        config_path = scratch / "TEST_ONLY.config.json"
        _write(config_path, config)

        with pytest.raises(CampaignConfigError, match="not complete"):
            load_campaign_config(pending_path)
        loaded = load_campaign_config(config_path)
        inputs = load_inputs(loaded)
        assert len(inputs.metadata) == expected_metadata
        assert (
            sum(row["source_season"] != row["calendar_year"] for row in inputs.metadata.values())
            == expected_crossovers
        )
        assert len(inputs.raw_members) == expected_raw
        assert not (scratch / "run").exists()

        plan_drift = copy.deepcopy(config)
        plan_drift["producer_plan"]["sha256"] = "0" * 64
        plan_drift_path = scratch / "TEST_ONLY.plan_drift.json"
        _write(plan_drift_path, plan_drift)
        with pytest.raises(CampaignConfigError, match="hash mismatch"):
            load_campaign_config(plan_drift_path)

        completion_drift = copy.deepcopy(config)
        completion_drift["producer_completion"]["sha256"] = "0" * 64
        completion_drift_path = scratch / "TEST_ONLY.completion_drift.json"
        _write(completion_drift_path, completion_drift)
        with pytest.raises(CampaignConfigError, match="hash mismatch"):
            load_campaign_config(completion_drift_path)
    finally:
        shutil.rmtree(scratch)
        reset_workspace_cache()
