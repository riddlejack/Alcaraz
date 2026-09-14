"""Independent B2 review findings, exercised at public driver/accessor boundaries."""

import json
from pathlib import Path
from typing import Any

import pytest

from tennislab.chain import barrier_scan, runner
from tennislab.chain.common import ChainError, canonical_hash, sha256
from tennislab.chain.labels import PROJECTION_FIELDS, projected_rows
from tennislab.config import reset_workspace_cache
from tests.conftest import copy_run, drive, rewind
from tests.test_barrier_gate import _install_shim, manifest


@pytest.mark.parametrize("mode", ["r", "r+", "rb+", "os_rdwr"])
def test_read_capable_opens_are_observed(
    mode: str, sample_run: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = copy_run(sample_run, tmp_path / "ws")
    rewind(run, "edition_index")
    source = """
import os
from tennislab.chronology import edition_index

def main():
    path = os.environ["CHECK_PANEL"]
    mode = os.environ["CHECK_MODE"]
    if mode == "os_rdwr":
        fd = os.open(path, os.O_RDWR)
        assert b"a_won" in os.read(fd, 10000)
        os.close(fd)
    else:
        with open(path, mode) as handle:
            assert handle.read()
    return edition_index.main()

if __name__ == "__main__":
    raise SystemExit(main())
"""
    _install_shim(tmp_path / "shims", "read_capable_stage", source, monkeypatch)
    monkeypatch.setenv("CHECK_MODE", mode)
    monkeypatch.setenv("CHECK_PANEL", str(run["workspace"] / "data/sample/panel.csv"))
    monkeypatch.setitem(runner.MODULES, "edition_index", "read_capable_stage")
    with pytest.raises(ChainError, match="declares no outcome access but parsed"):
        drive(
            run["workspace"],
            ["run", "--from", "edition_index", "--to", "edition_index", "--config", run["config"]],
        )


@pytest.mark.parametrize(
    "target",
    [
        "run",
        "stage",
        "stdout.txt",
        "stderr.txt",
        "access_log.jsonl",
        "stage_manifest.json",
        "ledger",
        "nested/predictions.csv",
    ],
)
def test_runner_refuses_symlinks_before_any_write(
    target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    external = tmp_path / "immutable"
    external.mkdir()
    sentinel = external / "sentinel"
    sentinel.write_bytes(b"unchanged")
    run = ws / "run"
    if target == "run":
        run.symlink_to(external, target_is_directory=True)
    else:
        run.mkdir()
        stage = run / "dummy"
        if target == "stage":
            stage.symlink_to(external, target_is_directory=True)
        else:
            stage.mkdir()
            link = run / runner.LEDGER if target == "ledger" else stage / target
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(sentinel)
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(ws))
    reset_workspace_cache()
    try:
        with pytest.raises(ChainError, match="symbolic link"):
            runner.run_stage(runner.Stage("dummy", None, []), {}, run, earlier=[])
        assert sentinel.read_bytes() == b"unchanged"
        assert sorted(p.name for p in external.iterdir()) == ["sentinel"]
    finally:
        reset_workspace_cache()


def test_missing_audit_log_fails_the_stage(
    sample_run: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = copy_run(sample_run, tmp_path / "ws")
    rewind(run, "edition_index")
    source = """
import os
from tennislab.chronology import edition_index

def main():
    status = edition_index.main()
    os._exit(status)  # Deliberately skips the audit completion flush.

if __name__ == "__main__":
    raise SystemExit(main())
"""
    _install_shim(tmp_path / "shims", "no_audit_completion", source, monkeypatch)
    monkeypatch.setitem(runner.MODULES, "edition_index", "no_audit_completion")
    with pytest.raises(ChainError, match="invalid audit evidence"):
        drive(
            run["workspace"],
            ["run", "--from", "edition_index", "--to", "edition_index", "--config", run["config"]],
        )


def _bind_manifest(run: dict[str, Any], name: str) -> None:
    """Rebind the local ledger deliberately, so cached-verdict tests reach re-derivation."""
    path = run["run_root"] / runner.LEDGER
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    previous = "genesis"
    for entry in entries:
        if entry["stage"] == name:
            entry["manifest_sha256"] = sha256(run["run_root"] / name / runner.STAGE_MANIFEST)
            entry["outputs_sha256"] = manifest(run, name)["outputs_sha256"]
        entry["previous_entry_sha256"] = previous
        previous = canonical_hash(entry)
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))


@pytest.mark.parametrize("change", ["receipt", "declaration", "barrier", "exit_status"])
def test_verify_reconstructs_instead_of_trusting_cached_verdicts(
    change: str, sample_run: dict[str, Any], tmp_path: Path
) -> None:
    run = copy_run(sample_run, tmp_path / "ws")
    name = "barrier" if change == "barrier" else "pipeline"
    record = manifest(run, name)
    if change == "receipt":
        record["outcome_access"]["receipts"][0]["year_ceiling"] = 2099
    elif change == "declaration":
        record["outcome_access"]["declared"] = "target"
    elif change == "barrier":
        record["run_tree_sha256"] = "0" * 64
    else:
        record["exit_status"] = 1
    assert record["integrity_violations"] == []
    path = run["run_root"] / name / runner.STAGE_MANIFEST
    path.write_text(json.dumps(record))
    _bind_manifest(run, name)
    with pytest.raises(
        ChainError, match="outcome access differs|barrier run tree differs|exit status"
    ):
        drive(run["workspace"], ["verify", "--config", run["config"]])


def test_metadata_projection_is_closed_to_new_outcome_columns(sample_run: dict[str, Any]) -> None:
    panel = sample_run["workspace"] / "data/sample/panel.csv"
    for purpose in PROJECTION_FIELDS:
        flag = ("a_won", "outcome_known") if purpose == "calibration_metadata" else None
        rows = projected_rows(panel, sha256(panel), purpose=purpose, resolution_flag=flag)
        expected = set(PROJECTION_FIELDS[purpose]) | ({"outcome_known"} if flag else set())
        assert set(rows[0]) == expected
        assert {"a_won", "status", "a_svpt", "a_ace", "score"}.isdisjoint(rows[0])


def test_nested_bookkeeping_names_do_not_hide_metrics(tmp_path: Path) -> None:
    nested = tmp_path / "stage" / "nested"
    nested.mkdir(parents=True)
    for name in ("stage_manifest.json", "access_log.jsonl"):
        (nested / name).write_text('{"log_loss": 0.6}\n')
    result = barrier_scan.scan_tree(tmp_path, ["stage"])
    assert len(result["findings"]) == 2


@pytest.mark.parametrize("change", ["ceiling", "date"])
def test_verify_rejects_a_consistently_rebound_bad_access_log(
    change: str, sample_run: dict[str, Any], tmp_path: Path
) -> None:
    run = copy_run(sample_run, tmp_path / "ws")
    rewind(run, "barrier")
    name = "pipeline" if change == "ceiling" else "sr03_calibration"
    path = run["run_root"] / name / runner.ACCESS_LOG
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    receipt = next(
        item
        for item in entries
        if item["kind"] == "receipt" and item.get("fold_outer_year") is not None
    )
    if change == "ceiling":
        receipt["year_ceiling"] = receipt["fold_outer_year"]
    else:
        receipt["max_match_date_returned"] = "2099-01-01"
    path.write_text("".join(json.dumps(item) + "\n" for item in entries))
    record = manifest(run, name)
    record["outcome_access"]["receipts"] = [
        {key: value for key, value in item.items() if key != "kind"}
        for item in entries
        if item["kind"] == "receipt"
    ]
    record["outputs"] = runner.hash_tree(run["run_root"] / name)
    record["outputs_sha256"] = canonical_hash(record["outputs"])
    (run["run_root"] / name / runner.STAGE_MANIFEST).write_text(json.dumps(record))
    _bind_manifest(run, name)
    with pytest.raises(ChainError, match="ceiling|beyond cutoff"):
        drive(run["workspace"], ["verify", "--config", run["config"]])


def test_config_emission_refuses_linked_destination(
    sample_run: dict[str, Any], tmp_path: Path
) -> None:
    run = copy_run(sample_run, tmp_path / "ws")
    external = tmp_path / "immutable"
    external.mkdir()
    (run["workspace"] / "linked_configs").symlink_to(external, target_is_directory=True)
    config = Path(run["config"])
    document = json.loads(config.read_text())
    document["chain"]["configs_dir"] = "linked_configs"
    config.write_text(json.dumps(document))
    with pytest.raises(ChainError, match="symbolic link"):
        drive(run["workspace"], ["write-configs", "--config", str(config)])
    assert list(external.iterdir()) == []
