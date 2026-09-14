"""Decision RB9: the tier stages on the committed synthetic tier sample.

``data/sample_tier`` is the second synthetic scenario: the base world with a lower tier
beneath it, driven through ``tier_stream``, ``tier_elo``, ``sr02_tier_replay``, the
same-event-qualifying ablation ``sr02_tier_noqual_replay`` and ``tier_block``, then the
model tail with the five bundles and the report's ``full_tier_minus_full`` contrast. The
chain is regenerated into a temporary workspace and driven from ``rule_mapping`` to
``report`` exactly as ``tennislab reproduce-small --scenario tier`` drives it.

These tests fail, rather than skip, when the committed tier sample is absent.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tennislab import cli, reproduce
from tennislab.chain import runner
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache
from tennislab.features import tier_block
from tennislab.ratings import tier_elo

SAMPLE = Path("data", "sample_tier")
CHAIN_CONFIG = Path("configs", "chains", "sample_atp_tier.json")
RUN_ROOT = Path("work", "sample_atp_tier", "run")
CONFIGS_DIR = Path("work", "sample_atp_tier", "configs")
SIZE_BUDGET_BYTES = 5 * 1024 * 1024
TIER_STAGES = (
    "tier_stream",
    "tier_elo",
    "sr02_tier_replay",
    "sr02_tier_noqual_replay",
    "tier_block",
)
TIER_STAGE_OUTPUTS = {
    "tier_stream": ("tier_results.csv.gz", "tier_source_rows.csv.gz", "tier_circuit_dating.csv"),
    "tier_elo": ("tier_elo_features.csv", "tier_offsets_by_year.csv"),
    "sr02_tier_replay": ("selected_matches.csv", "same_event_qualifying_membership.csv"),
    "sr02_tier_noqual_replay": ("selected_matches.csv", "same_event_qualifying_membership.csv"),
    "tier_block": ("trait_latent_sidecar.csv", "tier_dictionary.json"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def committed_sample(root: Path) -> Path:
    sample = root / SAMPLE
    assert sample.is_dir(), f"the committed tier sample is absent: {sample}"
    assert (root / CHAIN_CONFIG).is_file(), f"the tier chain config is absent: {CHAIN_CONFIG}"
    return sample


def generate(root: Path, workspace: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(root / "tools" / "make_sample.py"),
            "--scenario",
            "tier",
            "--workspace",
            str(workspace),
            "--template",
            str(root / CHAIN_CONFIG),
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def inside(workspace: Path, argv: list[str]) -> int:
    """Run one chain-driver command with the workspace installed for this process."""
    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    try:
        return runner.main(argv)
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()


# --------------------------------------------------------------- (a) the committed sample


def test_the_committed_tier_sample_is_its_generators_output(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    root = Path(request.config.rootpath)
    sample = committed_sample(root)
    generate(root, tmp_path)
    receipt = read_json(sample / "manifest.json")
    assert receipt["synthetic"] is True and receipt["scenario"] == "tier"
    assert receipt["unknown_outcomes_final_year"] is False
    regenerated = read_json(tmp_path / SAMPLE / "manifest.json")
    assert regenerated == receipt
    for name, digest in receipt["files"].items():
        assert sha256(sample / name) == digest, name
        assert sha256(tmp_path / SAMPLE / name) == digest, name
    assert (tmp_path / CHAIN_CONFIG).read_bytes() == (root / CHAIN_CONFIG).read_bytes()
    # The chain config declares the offsets the generator measured, per training window.
    chain = read_json(root / CHAIN_CONFIG)["chain"]
    assert chain["tier_offset_mode"] == "per_training_window"
    assert (
        chain["tier_initial_rating_offset_by_year"] == receipt["tier_initial_rating_offset_by_year"]
    )
    assert any(value != 0.0 for value in chain["tier_initial_rating_offset_by_year"].values())


def test_the_tier_sample_is_declared_synthetic_and_stays_small(
    request: pytest.FixtureRequest,
) -> None:
    root = Path(request.config.rootpath)
    sample = committed_sample(root)
    readme = (sample / "README.md").read_text(encoding="utf-8")
    assert "synthetic" in readme.lower()
    total = sum(path.stat().st_size for path in sample.iterdir() if path.is_file())
    assert total < SIZE_BUDGET_BYTES
    expected = read_json(sample / "expected.json")
    assert expected["primary_contrast"] == "full_tier_minus_full"
    assert expected["pinned_on"]["environment"] == "uv.lock"
    assert set(expected["pooled_log_loss_match_weighted"]) == {
        "cohort",
        *reproduce.SCENARIOS["tier"].pooled_models,
    }
    # The custody chain tier_stream verifies: the manifest pins the tarball and the
    # inventory at the hashes the chain config declares.
    chain = read_json(root / CHAIN_CONFIG)["chain"]
    pinned = {
        entry["path"]: entry["sha256"]
        for entry in read_json(sample / "archive_manifest.json")["files"]
    }
    for key in ("archive", "archive_inventory"):
        entry = chain["inputs"][key]
        assert pinned[entry["path"]] == entry["sha256"] == sha256(root / entry["path"])
    assert (
        sha256(root / chain["inputs"]["archive_manifest"]["path"])
        == chain["inputs"]["archive_manifest"]["sha256"]
    )


def test_the_cli_forwards_the_tier_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(reproduce, "main", lambda argv: calls.append(argv) or 7)
    assert cli.main(["reproduce-small", "--scenario", "tier"]) == 7
    assert cli.main(["reproduce-small", "--scenario", "tier", "--pin"]) == 7
    assert cli.main(["reproduce-small", "--scenario", "base"]) == 7
    assert calls == [["--scenario", "tier"], ["--scenario", "tier", "--pin"], []]


# --------------------------------------------------------------- (b) the chain, end to end


@pytest.fixture(scope="module")
def chain(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[dict[str, Any]]:
    root = Path(request.config.rootpath)
    committed_sample(root)
    workspace = tmp_path_factory.mktemp("tier_scenario")
    generate(root, workspace)
    config = str(workspace / CHAIN_CONFIG)
    assert inside(workspace, ["write-configs", "--config", config]) == 0
    assert inside(workspace, ["dry-run", "--config", config]) == 0
    assert inside(workspace, ["run", "--include-report", "--config", config]) == 0
    yield {"workspace": workspace, "config": config, "root": root}


def test_every_tier_stage_writes_its_outputs(chain: dict[str, Any]) -> None:
    run_root = chain["workspace"] / RUN_ROOT
    names = [stage.name for stage in runner.stages(read_json(Path(chain["config"]))["chain"])]
    assert [name for name in names if name in TIER_STAGES] == list(TIER_STAGES)
    assert names.index("sidecar") < names.index("tier_stream")
    assert names.index("tier_block") < names.index("predictor_config")
    for name in TIER_STAGES:
        manifest = read_json(run_root / name / "stage_manifest.json")
        assert manifest["exit_status"] == 0, name
        for output in TIER_STAGE_OUTPUTS[name]:
            assert output in manifest["outputs"], (name, output)
            assert (run_root / name / output).is_file(), (name, output)
    assert inside(chain["workspace"], ["verify", "--config", chain["config"]]) == 0


def test_the_report_reproduces_the_pinned_tier_headline(chain: dict[str, Any]) -> None:
    expected = read_json(chain["root"] / SAMPLE / "expected.json")
    observed = reproduce.headline(chain["workspace"], reproduce.SCENARIOS["tier"])
    assert observed["primary_contrast"] == "full_tier_minus_full"
    assert reproduce.compare(observed, expected) == []
    primary = read_json(chain["workspace"] / RUN_ROOT / "report" / "primary.json")
    assert "base_tier_minus_base" in primary["secondary_contrasts"]


def test_the_stream_exercises_every_declared_rule(chain: dict[str, Any]) -> None:
    run_root = chain["workspace"] / RUN_ROOT
    stream = read_json(run_root / "tier_stream" / "summary.json")
    assert stream["parameters"]["satellite_circuit_dating"] is True
    assert stream["satellite_circuit_dating"]["circuits"] > 0
    assert stream["satellite_circuit_dating"]["rows_redated"] > 0
    assert all(
        stream["retained_by_tier"][tier] > 0 for tier in ("challenger", "qualifying", "futures")
    )
    assert stream["totals"]["sr02_feed_rows"] > 0
    assert stream["excluded"].get("status_walkover", 0) > 0
    elo = read_json(run_root / "tier_elo" / "summary.json")
    assert elo["offset_by_training_window"]["mode"] == "per_training_window"
    assert elo["offset_by_training_window"]["replays"] > 1
    assert elo["stream"]["players_with_a_lower_tier_debut"] > 0
    assert elo["regression_against_multi01_elo"]["exact"] is False


# --------------------------------------------------------------- (c) the drift refusal


def test_tier_elo_refuses_a_drifted_declared_offset(chain: dict[str, Any], tmp_path: Path) -> None:
    workspace = chain["workspace"]
    config = read_json(workspace / CONFIGS_DIR / "tier_elo.filled.json")
    declared = config["tier_elo"]["parameters"]["lower_tier_initial_offset_by_year"]
    year = max(declared)
    declared[year] = float(declared[year]) + 0.5
    scratch = workspace / "drift"
    scratch.mkdir()
    config["tier_elo"]["output_dir"] = str(scratch)
    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    try:
        with pytest.raises(
            tier_elo.TierEloError, match=f"offset for {year}.*differs from the measurement"
        ):
            tier_elo.run(config)
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()
    assert not any(scratch.iterdir())


# --------------------------------------------------------------- (d) the ablation


def test_the_ablation_admits_strictly_fewer_feed_rows(chain: dict[str, Any]) -> None:
    run_root = chain["workspace"] / RUN_ROOT
    full = read_json(run_root / "sr02_tier_replay" / "run_manifest.json")["tier_feed"]
    ablated = read_json(run_root / "sr02_tier_noqual_replay" / "run_manifest.json")["tier_feed"]
    assert full["enabled"] and ablated["enabled"]
    assert full["same_event_qualifying"]["excluded"] is False
    assert ablated["same_event_qualifying"]["excluded"] is True

    def admitted(feed: dict[str, Any]) -> int:
        return feed["counters"]["history_eligible"] + feed["counters"]["history_ineligible"]

    assert admitted(full) == full["feed_rows"]
    assert ablated["same_event_qualifying"]["rows_excluded"] > 0
    assert (
        admitted(ablated)
        == ablated["feed_rows"] - ablated["same_event_qualifying"]["rows_excluded"]
    )
    assert admitted(ablated) < full["feed_rows"]
    # Both replays declare the same membership, read off the unfiltered feed.
    membership = read_rows(run_root / "sr02_tier_replay" / "same_event_qualifying_membership.csv")
    assert membership
    assert membership == read_rows(
        run_root / "sr02_tier_noqual_replay" / "same_event_qualifying_membership.csv"
    )


# --------------------------------------------------------------- (e) the sidecar block


def test_the_tier_block_sidecar_carries_the_block_and_keeps_membership(
    chain: dict[str, Any],
) -> None:
    run_root = chain["workspace"] / RUN_ROOT
    base_header, base_rows = _read_csv(run_root / "sidecar" / "trait_latent_sidecar.csv")
    header, rows = _read_csv(run_root / "tier_block" / "trait_latent_sidecar.csv")
    columns = (*tier_block.SIDECAR_COLUMNS, *tier_block.NOQUAL_SIDECAR_COLUMNS)
    assert header == [*base_header, *columns]
    assert len(rows) == len(base_rows) > 0
    for row, base in zip(rows, base_rows, strict=True):
        assert row["match_id"] == base["match_id"]
        blank = base["dynamic_match_probability_a"] == ""
        assert (row[tier_block.TIER_DYNAMIC_PROBABILITY] == "") == blank, row["match_id"]
        assert (row[tier_block.TIER_NOQUAL_DYNAMIC_PROBABILITY] == "") == blank, row["match_id"]
    assert any(row["tier_prior_matches_raw_a"] != "0" for row in rows)
    assert any(row["tier_initial_offset_applied_a"] == "1" for row in rows)
    assert any(
        row[tier_block.TIER_DYNAMIC_PROBABILITY] != row[tier_block.TIER_NOQUAL_DYNAMIC_PROBABILITY]
        for row in rows
        if row[tier_block.TIER_DYNAMIC_PROBABILITY] != ""
    )
    dictionary = read_json(run_root / "tier_block" / "tier_dictionary.json")
    assert "full_tier_noqual" in dictionary["bundles"]


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)
