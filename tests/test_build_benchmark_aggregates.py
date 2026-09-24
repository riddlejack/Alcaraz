"""``tools/build_benchmark_aggregates.py``: hash-verified sources, template directives,
statuses and equality checks.

Synthetic archive only: a small scorer-shaped result written here; no real row.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path("tools", "build_benchmark_aggregates.py").resolve()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contrast(left: str, right: str, delta: float) -> dict:
    scores = {"n": 4, "match_weighted": {"log_loss": 0.6, "brier": 0.2, "accuracy": 0.7}}
    block = {
        "draws_attempted": 50,
        "empty_draws_skipped": 0,
        "log_loss": {
            "percentile_95": [delta - 0.01, delta + 0.005],
            "bootstrap_sd": 0.004,
            "draw_sha256": "a" * 64,
        },
        "brier": {"percentile_95": [-0.002, 0.001], "bootstrap_sd": 0.001, "draw_sha256": "b" * 64},
        "accuracy": {"percentile_95": [0.0, 0.02], "bootstrap_sd": 0.005, "draw_sha256": "c" * 64},
        "joint_draw_sha256": "d" * 64,
    }
    return {
        "left": left,
        "right": right,
        "years": [2017, 2018],
        "n": 4,
        "left_scores": scores,
        "right_scores": scores,
        "difference": {
            "match_weighted": {"log_loss": delta},
            "annual_log_loss": {"2017": delta, "2018": delta},
            "years_negative": 2,
        },
        "primary_interval_log_loss": {
            "mean_block_weeks": 8,
            "lower": delta - 0.01,
            "upper": delta + 0.005,
        },
        "uncertainty": {
            "method": "stationary",
            "grid_first_monday": "2017-01-02",
            "grid_last_monday": "2018-12-31",
            "grid_weeks": 105,
            "nonempty_weeks": 60,
            "results": {"8": block, "4": block, "13": block},
        },
        "equal_year_interval_log_loss": {
            "method": "per-year",
            "draws_attempted": 50,
            "empty_draws_skipped": 0,
            "mean_block_weeks": 8,
            "percentile_95": [-0.02, 0.0],
            "bootstrap_sd": 0.003,
            "draw_sha256": "e" * 64,
        },
        "variance_diagnostics": {"effective_sd": 0.2},
        "orientation_control_max_error": 0.0,
    }


def make_archive(root: Path, delta: float = -0.007) -> None:
    forecast = root / "runs/y2017.csv"
    forecast.parent.mkdir(parents=True, exist_ok=True)
    forecast.write_text("match_id,p\n1,0.6\n")
    binding = {"path": str(forecast), "sha256": sha(forecast)}
    result = {
        "experiment_id": "EXT-TEST",
        "bindings": {"membership": binding},
        "cohort": {"years": [2017, 2018], "n": 4, "n_by_year": {"2017": 2, "2018": 2}},
        "arms": {
            "alcaraz_frozen": {"bindings": {"2017": binding}, "rows_outside_membership_ignored": 3},
            "buildoak": {"bindings": {"2017": binding}, "rows_outside_membership_ignored": 0},
        },
        "contrasts": {
            "contrast2_best_alcaraz_minus_external": contrast("alcaraz_frozen", "buildoak", delta)
        },
    }
    (root / "results").mkdir(exist_ok=True)
    (root / "results/result.json").write_text(json.dumps(result))
    (root / "results/accepted.json").write_text(json.dumps(result | {"experiment_id": "ACCEPTED"}))
    (root / "results/report.json").write_text('{"copied": "byte for byte"}\n')


TEMPLATE = {
    "experiment_id": "@value res:experiment_id",
    "note": "@@literal at sign",
    "cohort": {
        "n": "@value res:cohort/n",
        "rows_outside": "@per_arm res rows_outside_membership_ignored",
    },
    "contrasts": {
        "contrast2_arm1_minus_buildoak": {
            "@c": "@contrast res:contrasts/contrast2_best_alcaraz_minus_external"
        }
    },
    "detailed": "@contrast_detailed res:contrasts/contrast2_best_alcaraz_minus_external",
    "provenance": {
        "result_json": "@file res",
        "membership": "@binding res:bindings/membership",
        "forecast_files": "@forecast_files res",
    },
    "sentence": "On {{out:cohort/n|int}} matches: {{out:contrasts/contrast2_arm1_minus_buildoak/difference/match_weighted/log_loss|s4}} {{out:contrasts/contrast2_arm1_minus_buildoak/intervals_95/log_loss/8|ci4}}.",
}


def make_repo(
    repo: Path, archive: Path, status: str = "extension", checks: list | None = None
) -> None:
    (repo / "docs/templates").mkdir(parents=True)
    (repo / "docs/benchmarks").mkdir()
    (repo / "docs/templates/t.json").write_text(json.dumps(TEMPLATE))
    targets = [
        {
            "output": "docs/benchmarks/out.json",
            "status": status,
            "template": "docs/templates/t.json",
            "arm_names": {"alcaraz_frozen": "arm1"},
            "checks": checks or [],
            "sources": {
                "res": {
                    "path": "results/result.json",
                    "sha256": sha(archive / "results/result.json"),
                },
                "accepted": {
                    "path": "results/accepted.json",
                    "sha256": sha(archive / "results/accepted.json"),
                },
            },
        },
        {
            "output": "docs/benchmarks/copy.json",
            "status": "extension",
            "copy": "report",
            "sources": {
                "report": {
                    "path": "results/report.json",
                    "sha256": sha(archive / "results/report.json"),
                }
            },
        },
        {
            "output": "docs/benchmarks/later.json",
            "status": "pending",
            "copy": "report",
            "sources": {"report": {"path": "results/later.json", "sha256": None}},
        },
    ]
    (repo / "docs/benchmarks/sources.json").write_text(json.dumps({"targets": targets}))


def run(repo: Path, archive: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "--repo", str(repo), "--archive-root", str(archive), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path]:
    archive, repo = tmp_path / "archive", tmp_path / "repo"
    archive.mkdir()
    repo.mkdir()
    make_archive(archive)
    make_repo(repo, archive)
    return repo, archive


def test_build_writes_outputs_and_check_passes(setup: tuple[Path, Path]) -> None:
    repo, archive = setup
    done = run(repo, archive)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PENDING docs/benchmarks/later.json" in done.stdout
    out = json.loads((repo / "docs/benchmarks/out.json").read_text())
    c2 = out["contrasts"]["contrast2_arm1_minus_buildoak"]
    assert c2["left"] == "arm1" and c2["right"] == "buildoak"
    assert list(c2["intervals_95"]["log_loss"]) == ["4", "8", "13"]
    assert "log_loss_draw_sha256" not in c2["draws"]["8"]
    assert out["detailed"]["draws"]["8"]["log_loss_draw_sha256"] == "a" * 64
    assert out["detailed"]["equal_year_interval_log_loss"]["bootstrap_sd"] == 0.003
    assert out["cohort"]["rows_outside"] == {"arm1": 3, "buildoak": 0}
    assert out["note"] == "@literal at sign"
    assert out["provenance"]["membership"]["archive_relative_path"] == "runs/y2017.csv"
    assert set(out["provenance"]["forecast_files"]) == {"arm1", "buildoak"}
    assert out["provenance"]["result_json"]["archive_relative_path"] == "results/result.json"
    assert out["sentence"] == "On 4 matches: −0.0070 [−0.0170, −0.0020]."
    assert (repo / "docs/benchmarks/copy.json").read_bytes() == (
        archive / "results/report.json"
    ).read_bytes()
    assert run(repo, archive, "--check").returncode == 0


def test_changed_source_stops_the_build(setup: tuple[Path, Path]) -> None:
    repo, archive = setup
    (archive / "results/result.json").write_text("{}")
    done = run(repo, archive)
    assert done.returncode == 1
    assert "sources.json binds" in done.stdout
    assert not (repo / "docs/benchmarks/out.json").exists()


def test_accepted_output_is_never_written(setup: tuple[Path, Path]) -> None:
    repo, archive = setup
    make_repo_accepted = json.loads((repo / "docs/benchmarks/sources.json").read_text())
    make_repo_accepted["targets"][0]["status"] = "accepted"
    (repo / "docs/benchmarks/sources.json").write_text(json.dumps(make_repo_accepted))
    committed = repo / "docs/benchmarks/out.json"
    committed.write_text('{"experiment_id": "EXT-TEST"}\n')
    done = run(repo, archive)
    assert done.returncode == 1
    assert "DIFFERS docs/benchmarks/out.json" in done.stdout
    assert "/cohort: only in the build" in done.stdout
    assert committed.read_text() == '{"experiment_id": "EXT-TEST"}\n'


def test_failed_check_writes_nothing(tmp_path: Path) -> None:
    archive, repo = tmp_path / "archive", tmp_path / "repo"
    archive.mkdir()
    repo.mkdir()
    make_archive(archive)
    checks = [{"equal": ["res:experiment_id", "accepted:experiment_id"]}]
    make_repo(repo, archive, checks=checks)
    done = run(repo, archive, "--only", "docs/benchmarks/out.json")
    assert done.returncode == 1
    assert "1 check(s) failed" in done.stdout
    assert not (repo / "docs/benchmarks/out.json").exists()


def test_source_override_needs_out_dir(setup: tuple[Path, Path], tmp_path: Path) -> None:
    repo, archive = setup
    alt = tmp_path / "fixture.json"
    alt.write_text('{"fixture": true}\n')
    only = ("--only", "docs/benchmarks/later.json", "--source", f"report={alt}")
    assert run(repo, archive, *only).returncode == 2
    done = run(repo, archive, *only, "--out-dir", str(tmp_path / "dry"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "dry/later.json").read_text() == '{"fixture": true}\n'
    assert not (repo / "docs/benchmarks/later.json").exists()


def test_host_path_in_a_copy_becomes_a_placeholder(setup: tuple[Path, Path]) -> None:
    repo, archive = setup
    report = archive / "results/report.json"
    report.write_text(json.dumps({"config": f"{archive.resolve()}/configs/run.json"}) + "\n")
    registry = json.loads((repo / "docs/benchmarks/sources.json").read_text())
    registry["targets"][1]["sources"]["report"]["sha256"] = sha(report)
    (repo / "docs/benchmarks/sources.json").write_text(json.dumps(registry))
    done = run(repo, archive, "--only", "docs/benchmarks/copy.json")
    assert done.returncode == 0, done.stdout + done.stderr
    tracked = json.loads((repo / "docs/benchmarks/copy.json").read_text())
    assert tracked == {"config": "<ARCHIVE_ROOT>/configs/run.json"}
    original = repo / "local/evidence/docs/benchmarks/copy.json"
    assert original.read_bytes() == report.read_bytes()
    assert run(repo, archive, "--only", "docs/benchmarks/copy.json", "--check").returncode == 0
