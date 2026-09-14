"""The chain driver: stage tables, ledger chaining, the empty-digest refusal."""

import json
from pathlib import Path

import pytest

from tennislab.chain import runner
from tennislab.chain.common import ChainError, canonical_hash
from tennislab.config import reset_workspace_cache

ATP_SECTION = {
    "tour": "ATP",
    "configs": {"tier_stream": "x"},
    "tier_same_event_qualifying_ablation": True,
    "reporting_primary_contrast": "full_tier_minus_full",
}


def test_atp_table_has_the_23_stages_in_the_archive_order() -> None:
    names = [stage.name for stage in runner.stages(ATP_SECTION)]
    assert names == [
        "bridge",
        "archive_panel",
        "join",
        "event_carry_forward",
        "prepare_panel",
        "format_corrections",
        "rule_mapping",
        "sr02_replay",
        "sr03_calibration",
        "rankings",
        "edition_index",
        "features",
        "sidecar",
        "tier_stream",
        "tier_elo",
        "sr02_tier_replay",
        "sr02_tier_noqual_replay",
        "tier_block",
        "predictor_config",
        "preflight",
        "pipeline",
        "barrier",
        "reporting_config",
    ]
    assert runner.report_stage(ATP_SECTION).name == "report"


def test_wta_table_swaps_the_tour_specific_modules_and_orders_carry_before_join() -> None:
    table = runner.stages({"tour": "WTA", "bridge_seasons": [2025]})
    names = [stage.name for stage in table]
    assert names[:4] == ["bridge", "archive_panel", "event_carry_forward", "join"]
    modules = {stage.name: stage.module for stage in table}
    assert modules["join"] == "tennislab.panel.wta_join"
    assert modules["rule_mapping"] == "tennislab.panel.wta_rules"
    edition = next(stage for stage in table if stage.name == "edition_index")
    assert "--unordered-source" in edition.argv


def test_skip_stages_refuses_unknown_names() -> None:
    with pytest.raises(ChainError):
        runner.stages({"tour": "ATP", "skip_stages": ["nonesuch"]})


def test_ledger_chains_and_detects_a_rewrite(tmp_path: Path) -> None:
    runner.append_ledger(tmp_path, {"stage": "a", "exit_status": 0})
    runner.append_ledger(tmp_path, {"stage": "b", "exit_status": 0})
    entries = runner.verify_ledger(tmp_path)
    assert [entry["stage"] for entry in entries] == ["a", "b"]
    assert entries[0]["previous_entry_sha256"] == "genesis"
    assert entries[1]["previous_entry_sha256"] == canonical_hash(entries[0])
    # Rewrite the first entry in place: the second no longer chains to it.
    lines = (tmp_path / runner.LEDGER).read_text().splitlines()
    first = json.loads(lines[0])
    first["exit_status"] = 1
    lines[0] = json.dumps(first, sort_keys=True)
    (tmp_path / runner.LEDGER).write_text("\n".join(lines) + "\n")
    with pytest.raises(ChainError):
        runner.verify_ledger(tmp_path)


def test_barrier_refuses_an_empty_run_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # SCAR_TISSUE B5: a manifest recorded sha256({}) as the run-tree digest.
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    run_root = tmp_path / "run"
    run_root.mkdir()
    barrier = runner.Stage("barrier", None, [], dry_run=False)
    with pytest.raises(ChainError, match="empty"):
        runner.run_stage(barrier, {"configs": {}}, run_root, earlier=[])
    reset_workspace_cache()


def test_command_uses_the_running_interpreter_and_module(tmp_path: Path) -> None:
    stage = runner.stages(ATP_SECTION)[1]
    command = runner.command_for(stage, {"configs": {"archive_panel": "c.json"}}, tmp_path / "run")
    assert command[1:4] == ["-B", "-m", "tennislab.panel.archive_panel"]
    assert command[4:] == [
        "--config",
        "c.json",
        "--output-dir",
        str(tmp_path / "run" / "archive_panel"),
    ]
