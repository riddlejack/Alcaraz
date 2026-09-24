"""``tools/render_winner_accuracy.py``: the accepted run roots by default, ``--run`` to name
another archive-relative root (a composed root with an added target year).

Synthetic archive only: random-free forecasts and labels written here; no real row.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path("tools", "render_winner_accuracy.py")
DEFAULT_ATP = "work/PHASE1_ATP_20260922/ladder_root/run"
BUNDLES = ("base", "full", "full_tier", "full_tier_entry")
PER_YEAR = 6


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def make_root(run: Path, years: range) -> None:
    """Every match in every file; player A wins the even-numbered matches and every
    forecast favours A, so each model picks PER_YEAR // 2 of PER_YEAR correctly."""
    features, labels = [], []
    for year in years:
        ids = [f"{year}-{i}" for i in range(PER_YEAR)]
        for index, match_id in enumerate(ids):
            features.append([match_id, year, 0.4, 0.2])
            labels.append([match_id, "1", "1" if index % 2 == 0 else "0"])
        rows = [[year, match_id, "0.7"] for match_id in ids]
        for bundle in BUNDLES:
            write_csv(
                run / "pipeline" / "selected" / str(year) / "hgb" / f"{bundle}.csv",
                ["season", "match_id", "p_a_wins"],
                rows,
            )
        for name in ("raw_ps.csv", "calibrated_ps.csv"):
            write_csv(
                run / "pipeline" / "market" / str(year) / name,
                ["season", "match_id", "p_a_wins"],
                rows,
            )
    write_csv(
        run / "features" / "features.csv",
        ["match_id", "calendar_year", "elo_overall_logit", "elo_surface_logit"],
        features,
    )
    write_csv(run / "features" / "labels.csv", ["match_id", "primary_target", "a_won"], labels)


def ladder_json(path: Path, years: range) -> Path:
    per_year = [{"tour": "ATP", "year": year, "n": PER_YEAR} for year in years]
    path.write_text(json.dumps({"tours": {"ATP": {"per_year": per_year}}}), encoding="utf-8")
    return path


def render(root: Path, archive: Path, ladder: Path, out: Path, *extra: str):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(root / TOOL),
            "--config",
            str(root / "configs" / "ladder.json"),
            "--configs-dir",
            str(root / "configs"),
            "--ladder",
            str(ladder),
            "--output-json",
            str(out / "winner_accuracy.json"),
            "--output-csv",
            str(out / "winner_accuracy.csv"),
            "--archive-root",
            str(archive),
            *extra,
        ],
        cwd=out,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def archive(tmp_path: Path) -> Path:
    archive = tmp_path / "archive"
    make_root(archive / DEFAULT_ATP, range(2017, 2025))
    make_root(archive / "roots" / "ATP_2017_2025" / "run", range(2017, 2026))
    return archive


def test_default_reads_the_accepted_root(
    request: pytest.FixtureRequest, archive: Path, tmp_path: Path
) -> None:
    root = Path(request.config.rootpath)
    done = render(root, archive, ladder_json(tmp_path / "l8.json", range(2017, 2025)), tmp_path)
    assert done.returncode == 0, done.stderr
    result = json.loads((tmp_path / "winner_accuracy.json").read_text(encoding="utf-8"))
    assert result["source"]["accepted_runs"]["ATP"] == DEFAULT_ATP
    block = result["tours"]["ATP"]
    assert [row["year"] for row in block["per_year"]] == list(range(2017, 2025))
    assert block["overall"]["atp_full_tier_entry"]["n"] == 8 * PER_YEAR
    assert block["overall"]["atp_full_tier_entry"]["accuracy"] == 0.5


def test_run_option_reads_the_named_root_with_a_ninth_year(
    request: pytest.FixtureRequest, archive: Path, tmp_path: Path
) -> None:
    root = Path(request.config.rootpath)
    ladder = ladder_json(tmp_path / "l9.json", range(2017, 2026))
    done = render(root, archive, ladder, tmp_path, "--run", "ATP=roots/ATP_2017_2025/run")
    assert done.returncode == 0, done.stderr
    result = json.loads((tmp_path / "winner_accuracy.json").read_text(encoding="utf-8"))
    assert result["source"]["accepted_runs"]["ATP"] == "roots/ATP_2017_2025/run"
    assert result["source"]["accepted_runs"]["WTA"] == "experiments/runs/WTA02/attempt_002/run"
    block = result["tours"]["ATP"]
    assert [row["year"] for row in block["per_year"]] == list(range(2017, 2026))
    assert block["overall"]["atp_full_tier_entry"]["n"] == 9 * PER_YEAR
    with (tmp_path / "winner_accuracy.csv").open(newline="", encoding="utf-8") as handle:
        years = {row["year"] for row in csv.DictReader(handle) if row["period"] == "year"}
    assert "2025" in years
    # Without --run the nine-year ladder cannot be matched against the eight-year root.
    done = render(root, archive, ladder, tmp_path)
    assert done.returncode != 0


@pytest.mark.parametrize("value", ["XYZ=roots/ATP_2017_2025/run", "ATP=", "ABSOLUTE"])
def test_run_option_refuses_unknown_tour_empty_or_absolute_root(
    request: pytest.FixtureRequest, archive: Path, tmp_path: Path, value: str
) -> None:
    root = Path(request.config.rootpath)
    if value == "ABSOLUTE":
        value = f"ATP={archive / 'roots' / 'ATP_2017_2025' / 'run'}"
    ladder = ladder_json(tmp_path / "l9.json", range(2017, 2026))
    done = render(root, archive, ladder, tmp_path, "--run", value)
    assert done.returncode != 0
    assert "--run needs TOUR=ARCHIVE_RELATIVE_ROOT" in done.stderr
    assert not (tmp_path / "winner_accuracy.json").exists()
