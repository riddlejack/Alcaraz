"""Host-side checks of the WTA walk-forward preparation and orientation mapping.

Synthetic sources only; no container, fit or real row. The container path is exercised by
``tools/buildoak_extension/wta_walkforward/synthetic_rehearsal.py``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path("tools", "buildoak_extension", "wta_walkforward")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root: Path, script: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(root / TOOLS / script), *argv],
        cwd=root,
        capture_output=True,
        text=True,
    )


def prepare(root: Path, sources: dict, year: int, output: Path, selection: Path | None = None):
    selected = Path(sources["selected_root"]) / str(year)
    return run(
        root,
        "prepare_year.py",
        "--year",
        str(year),
        "--frozen-plan",
        sources["frozen_plan"],
        "--native-raw",
        sources["native_raw"],
        "--rankings",
        sources["rankings"],
        "--selected",
        str(selected / "full.csv"),
        "--selection-json",
        str(selection or selected / "full.json"),
        "--labels",
        sources["labels"],
        "--output",
        str(output),
    )


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest):
    root = Path(request.config.rootpath)
    output = tmp_path_factory.mktemp("wta_walkforward") / "sources"
    done = run(root, "synthetic_rehearsal.py", "--output-root", str(output), "--generate-only")
    assert done.returncode == 0, done.stderr
    return root, json.loads((output / "SOURCES.json").read_text())


def test_frozen_year_reproduces_the_frozen_plan_byte_for_byte(synthetic, tmp_path: Path) -> None:
    root, sources = synthetic
    done = prepare(root, sources, 2019, tmp_path / "prep")
    assert done.returncode == 0, done.stderr
    assert sha256(tmp_path / "prep" / "date_hierarchy_plan.json") == sha256(
        Path(sources["frozen_plan"])
    )


def test_walk_forward_year_moves_only_the_roles(synthetic, tmp_path: Path) -> None:
    root, sources = synthetic
    done = prepare(root, sources, 2018, tmp_path / "prep")
    assert done.returncode == 0, done.stderr
    prep = tmp_path / "prep"
    frozen = json.loads(Path(sources["frozen_plan"]).read_text())
    plan = json.loads((prep / "date_hierarchy_plan.json").read_text())
    roles = {"fit_target", "evaluation_target"}
    assert [{k: v for k, v in r.items() if k not in roles} for r in plan] == [
        {k: v for k, v in r.items() if k not in roles} for r in frozen
    ]
    with open(sources["labels"], newline="") as handle:
        primary = {
            r["match_id"]
            for r in csv.DictReader(handle)
            if r["primary_target"] == "1" and r["calendar_year"] == "2018"
        }
    targets = {r["match_id"] for r in plan if r["evaluation_target"]}
    assert targets == primary
    fit = [r for r in plan if r["fit_target"]]
    assert all(
        r["target_date_proxy"] <= "2017-12-30" and r["available_date_proxy"] <= "2017-12-30"
        for r in fit
    )
    assert any("@" in r["match_id"] for r in fit)
    receipt = json.loads((prep / "preparation.json").read_text())
    assert receipt["state_only_rows"] > 0 and receipt["elo_reference_date"] == "2017-12-30"
    assert receipt["cohort_checks"]["excluded_non_primary_selected_rows"] > 0
    assert receipt["fit_menu_projection"]["recent_global"]["projected_active"] is False
    vocabulary = json.loads((prep / "ioc_vocabulary.json").read_text())
    assert len(vocabulary["vocabulary"]) == 10
    assert sum(vocabulary["counts"].values()) == 2 * len(fit)
    assert (prep / "fit_membership.txt").read_text().split() == sorted(r["match_id"] for r in fit)


def test_cohort_that_differs_from_the_selection_is_refused(synthetic, tmp_path: Path) -> None:
    root, sources = synthetic
    selection = Path(sources["selected_root"]) / "2018" / "full.json"
    drifted = json.loads(selection.read_text())
    drifted["outer_primary_rows"] += 1
    (tmp_path / "full.json").write_text(json.dumps(drifted))
    done = prepare(root, sources, 2018, tmp_path / "prep", selection=tmp_path / "full.json")
    assert done.returncode != 0
    assert "primary rows" in done.stderr


def committed_run(tmp_path: Path, rows: list[list[str]]) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "forecast").mkdir(parents=True)
    forecasts = run_dir / "forecast" / "native_forecasts.csv"
    with forecasts.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["match_id", "canonical_a_source_id", "p_a_native", "native_status"])
        writer.writerows(rows)
    commitment = run_dir / "FORECAST_COMMITMENT.json"
    commitment.write_text(
        json.dumps({"forecast_sha256": {"native_forecasts.csv": sha256(forecasts)}})
    )
    (tmp_path / "verification.json").write_text(
        json.dumps({"status": "PASS", "commitment_sha256": sha256(commitment)})
    )
    (tmp_path / "target_membership.txt").write_text("".join(r[0] + "\n" for r in sorted(rows)))
    with (tmp_path / "panel.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["match_id", "a_won", "a_source_id", "b_source_id"])
        writer.writerow(["E/1", "unread", "11", "22"])
        writer.writerow(["E/2", "unread", "44", "33"])
    return run_dir


def mapping_args(tmp_path: Path, run_dir: Path) -> list[str]:
    return [
        "--run",
        str(run_dir),
        "--verification",
        str(tmp_path / "verification.json"),
        "--membership",
        str(tmp_path / "target_membership.txt"),
        "--panel",
        str(tmp_path / "panel.csv"),
        "--output",
        str(tmp_path / "report" / "panel_orientation_forecasts.csv"),
    ]


def test_mapping_complements_when_panel_a_is_not_canonical(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    root = Path(request.config.rootpath)
    run_dir = committed_run(
        tmp_path, [["E/1", "11", "0.625", "native"], ["E/2", "33", "0.25", "native"]]
    )
    done = run(root, "map_orientation.py", *mapping_args(tmp_path, run_dir))
    assert done.returncode == 0, done.stderr
    mapped = (tmp_path / "report" / "panel_orientation_forecasts.csv").read_text()
    assert mapped == "match_id,p_a_wins\nE/1,0.625\nE/2,0.75\n"
    receipt = json.loads(
        (tmp_path / "report" / "panel_orientation_forecasts_receipt.json").read_text()
    )
    assert receipt["flipped_rows"] == 1 and receipt["rows"] == 2


def test_mapping_refuses_a_canonical_identity_mismatch(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    root = Path(request.config.rootpath)
    run_dir = committed_run(
        tmp_path, [["E/1", "22", "0.625", "native"], ["E/2", "33", "0.25", "native"]]
    )
    done = run(root, "map_orientation.py", *mapping_args(tmp_path, run_dir))
    assert done.returncode != 0
    assert "canonical orientation" in done.stderr
    assert not (tmp_path / "report" / "panel_orientation_forecasts.csv").exists()
