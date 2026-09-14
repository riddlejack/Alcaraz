"""Shared fixtures: one complete synthetic chain run per test session.

``sample_run`` builds a workspace from the committed sample (outcomes known), drives the
chain from ``rule_mapping`` through ``report`` and ``sr03_component`` exactly as
``tennislab reproduce-small`` does, and hands its paths to every integrity test. Tests
that mutate the run copy the workspace first (``copy_run``). If the sample is absent the
fixture raises, so CI fails rather than skips (archive brief item 5).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tennislab.chain import runner
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache

SAMPLE_CHAIN_CONFIG = Path("configs", "chains", "sample_atp.json")
SAMPLE_RUN_ROOT = Path("work", "sample_atp", "run")


def drive(workspace: Path, argv: list[str]) -> int:
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


def build_sample_workspace(root: Path, workspace: Path, *extra: str) -> str:
    sample = root / "data" / "sample"
    if not (sample / "manifest.json").is_file() or not (root / SAMPLE_CHAIN_CONFIG).is_file():
        raise RuntimeError(
            "the committed synthetic sample is required for the integrity tests and is absent"
        )
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(root / "tools" / "make_sample.py"),
            "--workspace",
            str(workspace),
            "--template",
            str(root / SAMPLE_CHAIN_CONFIG),
            *extra,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return str(workspace / SAMPLE_CHAIN_CONFIG)


@pytest.fixture(scope="session")
def sample_run(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[dict[str, Any]]:
    root = Path(request.config.rootpath)
    workspace = tmp_path_factory.mktemp("sample_run")
    config = build_sample_workspace(root, workspace)
    assert drive(workspace, ["write-configs", "--config", config]) == 0
    assert drive(workspace, ["dry-run", "--config", config]) == 0
    assert drive(workspace, ["run", "--include-report", "--config", config]) == 0
    run_root = workspace / SAMPLE_RUN_ROOT
    ledger = [
        json.loads(line)
        for line in (run_root / runner.LEDGER).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    yield {
        "root": root,
        "workspace": workspace,
        "config": config,
        "run_root": run_root,
        "stages": [entry["stage"] for entry in ledger],
    }


def copy_run(sample: dict[str, Any], destination: Path) -> dict[str, Any]:
    """A private copy of the whole workspace, for tests that rerun or mutate stages."""
    shutil.copytree(sample["workspace"], destination, symlinks=True)
    return {
        **sample,
        "workspace": destination,
        "config": str(destination / SAMPLE_CHAIN_CONFIG),
        "run_root": destination / SAMPLE_RUN_ROOT,
    }


def rewind(run: dict[str, Any], first_stage: str) -> None:
    """Remove ``first_stage`` and everything after it so the chain can rerun from there."""
    run_root: Path = run["run_root"]
    stages: list[str] = run["stages"]
    index = stages.index(first_stage)
    for name in stages[index:]:
        shutil.rmtree(run_root / name, ignore_errors=True)
    # The two side configs are written outside the run root and refuse replacement.
    section = json.loads(Path(run["config"]).read_text(encoding="utf-8"))["chain"]
    for stage_name, key in (
        ("predictor_config", "predictor_config"),
        ("reporting_config", "reporting_config"),
    ):
        if stage_name in stages[index:]:
            (run["workspace"] / section[key]).unlink(missing_ok=True)
    ledger = run_root / runner.LEDGER
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    ledger.write_text("".join(line + "\n" for line in lines[:index]), encoding="utf-8")
