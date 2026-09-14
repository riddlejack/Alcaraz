"""The committed sample and ``tennislab reproduce-small``'s comparison.

The whole reproduction runs once in ``tests/test_cli.py`` (``cli.main(["reproduce-small"])``)
and once more in ``make reproduce-small``; these tests cover what those runs do not: that
the committed sample is exactly what its generator emits at the pinned seed, that the
headline comparison refuses a drift, and that the CLI hands the command to the module.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tennislab import cli, reproduce

SAMPLE = Path("data", "sample")
CHAIN_CONFIG = Path("configs", "chains", "sample_atp.json")
SIZE_BUDGET_BYTES = 5 * 1024 * 1024


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_committed_sample_is_its_generators_output(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    root = Path(request.config.rootpath)
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(root / "tools" / "make_sample.py"),
            "--workspace",
            str(tmp_path),
            "--template",
            str(root / CHAIN_CONFIG),
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    receipt = json.loads((root / SAMPLE / "manifest.json").read_text(encoding="utf-8"))
    assert receipt["synthetic"] is True and receipt["unknown_outcomes_final_year"] is False
    regenerated = json.loads((tmp_path / SAMPLE / "manifest.json").read_text(encoding="utf-8"))
    assert regenerated == receipt
    for name, digest in receipt["files"].items():
        assert sha256(root / SAMPLE / name) == digest, name
        assert sha256(tmp_path / SAMPLE / name) == digest, name
    assert (tmp_path / CHAIN_CONFIG).read_bytes() == (root / CHAIN_CONFIG).read_bytes()


def test_the_sample_is_declared_synthetic_and_stays_small(request: pytest.FixtureRequest) -> None:
    root = Path(request.config.rootpath)
    readme = (root / SAMPLE / "README.md").read_text(encoding="utf-8")
    assert "synthetic" in readme.lower()
    total = sum(path.stat().st_size for path in (root / SAMPLE).iterdir() if path.is_file())
    assert total < SIZE_BUDGET_BYTES
    expected = json.loads((root / SAMPLE / "expected.json").read_text(encoding="utf-8"))
    assert expected["primary_contrast"] == "full_minus_base"
    assert expected["pinned_on"]["environment"] == "uv.lock"


def test_compare_names_every_value_that_drifts() -> None:
    pinned = {
        "primary_contrast": "full_minus_base",
        "n": 10,
        "equal_year_log_loss_delta": 0.001,
        "match_weighted_log_loss_delta": 0.002,
        "pooled_log_loss_match_weighted": {
            "cohort": "primary_priced",
            "selected/hgb/base": 0.6,
            "selected/hgb/full": 0.59,
            "market/calibrated_ps": 0.57,
        },
        "tolerance": 1e-9,
    }
    observed = json.loads(json.dumps(pinned))
    assert reproduce.compare(observed, pinned) == []
    observed["equal_year_log_loss_delta"] += 5e-10
    assert reproduce.compare(observed, pinned) == []
    observed["equal_year_log_loss_delta"] += 1e-8
    observed["n"] = 11
    observed["pooled_log_loss_match_weighted"]["market/calibrated_ps"] = 0.58
    problems = reproduce.compare(observed, pinned)
    assert [problem.split(":")[0] for problem in problems] == [
        "n",
        "equal_year_log_loss_delta",
        "pooled_log_loss_match_weighted.market/calibrated_ps",
    ]
    del observed["pooled_log_loss_match_weighted"]["selected/hgb/full"]
    assert any("selected/hgb/full" in problem for problem in reproduce.compare(observed, pinned))


def test_the_cli_hands_reproduce_small_to_the_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(reproduce, "main", lambda argv: calls.append(argv) or 7)
    assert cli.main(["reproduce-small"]) == 7
    assert cli.main(["reproduce-small", "--pin"]) == 7
    assert calls == [[], ["--pin"]]


def test_reproduce_small_refuses_to_run_outside_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert reproduce.main([]) == 1
