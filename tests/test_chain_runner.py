"""The chain driver: stage tables, ledger chaining, the empty-digest refusal."""

import json
from pathlib import Path

import pytest

from tennislab.chain import runner
from tennislab.chain.common import ChainError, canonical_hash
from tennislab.config import reset_workspace_cache
from tennislab.ratings import tier_stream

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


def test_the_ll_option_reaches_only_the_features_config_and_only_when_declared() -> None:
    """ARMS01 Arm 1-LLx: `entry_level_block_ll_as_no_flag` is carried to features.json
    exactly as `entry_level_block` is; no other emitted stage config changes."""
    document = json.loads(
        Path("configs/chains/atp_arms01_2017_2024.json").read_text(encoding="utf-8")
    )
    section = document["chain"]
    plan = runner.year_plan(document).as_document()
    arm1 = runner._stage_config_bodies(section, section["inputs"], plan)
    assert "entry_level_block_ll_as_no_flag" not in arm1["features"]
    assert arm1["features"]["entry_level_block"] is True
    llx_section = {**section, "entry_level_block_ll_as_no_flag": True}
    llx = runner._stage_config_bodies(llx_section, section["inputs"], plan)
    assert [name for name in arm1 if arm1[name] != llx[name]] == ["features"]
    assert {**arm1["features"], "entry_level_block_ll_as_no_flag": True} == llx["features"]
    # Only a literal true is carried.
    other = {**section, "entry_level_block_ll_as_no_flag": "true"}
    assert runner._stage_config_bodies(other, section["inputs"], plan) == arm1


def test_the_any_qualifier_option_reaches_only_the_features_config_when_false() -> None:
    """ARMS01 attempt 002: `entry_any_qualifier_counts_ll: false` is carried to features.json;
    absent or true emits every stage config byte-identical to today's; a non-boolean is refused."""
    document = json.loads(
        Path("configs/chains/atp_arms01_2017_2024.json").read_text(encoding="utf-8")
    )
    section = document["chain"]
    plan = runner.year_plan(document).as_document()
    arm1 = runner._stage_config_bodies(section, section["inputs"], plan)
    assert "entry_any_qualifier_counts_ll" not in arm1["features"]
    explicit = {**section, "entry_any_qualifier_counts_ll": True}
    assert runner._stage_config_bodies(explicit, section["inputs"], plan) == arm1
    registered = {**section, "entry_any_qualifier_counts_ll": False}
    attempt2 = runner._stage_config_bodies(registered, section["inputs"], plan)
    assert [name for name in arm1 if arm1[name] != attempt2[name]] == ["features"]
    assert {**arm1["features"], "entry_any_qualifier_counts_ll": False} == attempt2["features"]
    with pytest.raises(ChainError, match="entry_any_qualifier_counts_ll"):
        runner._stage_config_bodies(
            {**section, "entry_any_qualifier_counts_ll": "false"}, section["inputs"], plan
        )


def _tier_chain() -> tuple[dict, dict]:
    document = json.loads(
        Path("configs/chains/atp_tier01_2017_2024.json").read_text(encoding="utf-8")
    )
    return document, document["chain"]


def test_the_chain_acknowledgement_reaches_the_tier_stream_config_only_when_true() -> None:
    """One chain-level `reserved_release_acknowledged` covers the bridge and tier_stream;
    a chain that does not acknowledge emits every stage config as before."""
    document, section = _tier_chain()
    plan = runner.year_plan(document).as_document()
    assert section["reserved_release_acknowledged"] is False
    base = runner._stage_config_bodies(section, section["inputs"], plan)
    assert "reserved_release_acknowledged" not in base["tier_stream"]["tier_stream"]
    assert base["bridge"]["bridge"]["reserved_release_acknowledged"] is False
    acknowledged = runner._stage_config_bodies(
        {**section, "reserved_release_acknowledged": True}, section["inputs"], plan
    )
    assert [name for name in base if base[name] != acknowledged[name]] == [
        "bridge",
        "tier_stream",
    ]
    assert acknowledged["bridge"]["bridge"]["reserved_release_acknowledged"] is True
    assert acknowledged["tier_stream"]["tier_stream"] == {
        **base["tier_stream"]["tier_stream"],
        "reserved_release_acknowledged": True,
    }
    # Only a literal true reaches tier_stream.
    loose = runner._stage_config_bodies(
        {**section, "reserved_release_acknowledged": "true"}, section["inputs"], plan
    )
    assert loose["tier_stream"] == base["tier_stream"]


def test_the_emitted_tier_stream_config_opens_2025_only_under_the_chain_acknowledgement() -> None:
    document, section = _tier_chain()
    plan_document = {
        **document["year_plan"],
        "panel_end_year": 2025,
        "feature_end_year": 2025,
        "target_years": [*document["year_plan"]["target_years"], 2025],
    }
    plan = runner.year_plan({"year_plan": plan_document}).as_document()
    for acknowledged in (False, True):
        body = runner._stage_config_bodies(
            {**section, "reserved_release_acknowledged": acknowledged}, section["inputs"], plan
        )["tier_stream"]
        stage_plan = tier_stream.year_plan(body)
        if acknowledged:
            _, _, last_year = tier_stream.read_parameters(body["tier_stream"], stage_plan)
            assert last_year == 2025
        else:
            with pytest.raises(tier_stream.TierStreamError) as refused:
                tier_stream.read_parameters(body["tier_stream"], stage_plan)
            assert str(refused.value) == (
                "refusing to read a reserved year: last_year 2025 >= 2025"
            )


def test_the_tier_stream_note_changes_only_for_an_acknowledging_chain() -> None:
    _, section = _tier_chain()
    notes = {stage.name: stage.note for stage in runner.stages(section)}
    assert notes["tier_stream"] == (
        "Qualifying/Challenger/Futures history from the pinned mirror; "
        "reads no reserved year and no run artifact."
    )
    acknowledged = {
        stage.name: stage.note
        for stage in runner.stages({**section, "reserved_release_acknowledged": True})
    }
    assert [name for name in notes if notes[name] != acknowledged[name]] == ["tier_stream"]
    assert "reads no reserved year" not in acknowledged["tier_stream"]
    assert "summary.span" in acknowledged["tier_stream"]
    # The note follows what the emitted config carries, so a per-stage override that sets
    # (or clears) the flag moves the note with it.
    override = {"tier_stream": {"tier_stream": {"reserved_release_acknowledged": True}}}
    by_override = {
        stage.name: stage.note
        for stage in runner.stages({**section, "stage_config_overrides": override})
    }
    assert by_override == acknowledged
    cleared = {"tier_stream": {"tier_stream": {"reserved_release_acknowledged": False}}}
    by_clearing = {
        stage.name: stage.note
        for stage in runner.stages(
            {**section, "reserved_release_acknowledged": True, "stage_config_overrides": cleared}
        )
    }
    assert by_clearing == notes
