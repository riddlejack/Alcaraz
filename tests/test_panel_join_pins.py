"""The CH01 pin files are config bindings with the frozen files as defaults.

A synthetic workspace carries a small frozen pin set at the fixed paths and an extended
set (the frozen records, unchanged and in order, followed by records for a later season)
elsewhere. ``load_inputs`` is replaced by synthetic archive and market rows -- it needs
the pinned 2018 workbook -- so everything the pins touch runs as in production:
``configure``, alias and event resolution, classification, the outputs and ``audit.json``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tennislab.chain import runner
from tennislab.chain.common import ChainError
from tennislab.config import reset_workspace_cache
from tennislab.panel import join

FROZEN_PLAYERS = [
    {"season": 2020, "td_name": "Alpha A.", "canonical_player_id": 100, "basis": "fixture"},
    {"season": 2020, "td_name": "Beta B.", "canonical_player_id": 200, "basis": "fixture"},
]
FROZEN_EVENTS = [
    {
        "season": 2020,
        "archive_tourney_id": "2020-0123",
        "td_event_number": "123",
        "td_tournament": "Example Open",
        "td_location": "Exampleton",
    }
]
# The later season's market names do not match the archive's source names, so without
# a pin the row cannot be matched; with the extension pins it is a q1 candidate.
EXTENSION_PLAYERS = [
    {"season": 2021, "td_name": "Gamma-Name C.", "canonical_player_id": 300, "basis": "fixture"},
    {"season": 2021, "td_name": "Delta-Name D.", "canonical_player_id": 400, "basis": "fixture"},
]
EXTENSION_EVENTS = [
    {
        "season": 2021,
        "archive_tourney_id": "2021-0456",
        "td_event_number": "456",
        "td_tournament": "Later Open",
        "td_location": "Laterville",
    }
]
STUBBED_INPUTS = (
    "archive_source_panel",
    "archive_quality_report",
    "market_manifest",
    "market_profile_adapter",
)
OUTPUTS = (
    "common_panel_candidates.csv",
    "market_row_candidates.csv",
    "ambiguous_candidates.csv",
    "unmatched_market_rows.csv",
    "unmatched_archive_rows.csv",
    "date_correction_candidates.csv",
    "conflict_locators.csv",
    "alias_candidates.csv",
    "coverage_by_year.csv",
    "ch01_validation.json",
)


class Row(dict):
    """A source row whose unset fields read as blank cells."""

    def __missing__(self, key: str) -> str:
        return ""


def archive_row(season: int, tourney: str, a: tuple[int, str], b: tuple[int, str]) -> Row:
    return Row(
        season=str(season),
        source_key=f"{tourney}/1",
        tourney_id=tourney,
        tourney_name="Archive Event",
        tourney_anchor_date=f"{season}-01-06",
        round="R32",
        draw_size="32",
        a_entity_id=str(a[0]),
        a_source_name=a[1],
        b_entity_id=str(b[0]),
        b_source_name=b[1],
        a_won="true",
        score="6-4 6-3",
        surface="Hard",
        best_of="3",
        status="completed",
    )


def market_row(season: int, number: str, event: str, place: str, names: tuple[str, str]) -> Row:
    return Row(
        {
            "market_season": season,
            "market_source_path": f"market_{season}.xlsx",
            "market_source_sha256": "0" * 64,
            "market_source_row": 2,
            "capture_timestamp": "",
            "market_date": dt.date(season, 1, 7),
            "ATP": number,
            "Tournament": event,
            "Location": place,
            "Round": "1st Round",
            "Winner": names[0],
            "Loser": names[1],
            "Surface": "Hard",
            "Best of": "3",
            "Comment": "Completed",
            "W1": "6",
            "L1": "4",
            "W2": "6",
            "L2": "3",
        }
    )


def synthetic_inputs(settings: join.JoinSettings) -> tuple[list, list, dict[str, Any]]:
    archive = [
        archive_row(2020, "2020-0123", (100, "Alpha Aname"), (200, "Beta Bname")),
        archive_row(2021, "2021-0456", (300, "Gamma Cname"), (400, "Delta Dname")),
        # No market row reaches this one; the join writes its unmatched archive rows.
        archive_row(2021, "2021-0789", (500, "Epsilon Ename"), (600, "Zeta Zname")),
    ]
    market = [
        market_row(2020, "123", "Example Open", "Exampleton", ("Alpha A.", "Beta B.")),
        market_row(2021, "456", "Later Open", "Laterville", ("Gamma-Name C.", "Delta-Name D.")),
    ]
    # The records load_inputs would write for the files it reads; validate re-hashes them.
    metadata: dict[str, Any] = {"market_files": {}, "market_headers": {}}
    for name in STUBBED_INPUTS:
        path = settings.archive_panel_dir.parent / f"{name}.txt"
        metadata[name] = {"path": f"work/fixture/{name}.txt", "sha256": sha(path)}
    return archive, market, metadata


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    write_json(tmp_path / join.CH01_PLAYERS, FROZEN_PLAYERS)
    write_json(tmp_path / join.CH01_EVENTS, FROZEN_EVENTS)
    write_json(
        tmp_path / "work/bindings/player_crosswalk_plus.json", FROZEN_PLAYERS + EXTENSION_PLAYERS
    )
    write_json(
        tmp_path / "work/bindings/event_crosswalk_plus.json", FROZEN_EVENTS + EXTENSION_EVENTS
    )
    for path in join.CH01_LINEAGE.values():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("match_id,td_source_row\n", encoding="utf-8")
    for path in (join.ORIGINAL_ADAPTER, join.TESTS_PATH):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("# fixture\n", encoding="utf-8")
    for name in STUBBED_INPUTS:
        (tmp_path / "work/fixture").mkdir(parents=True, exist_ok=True)
        (tmp_path / f"work/fixture/{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    monkeypatch.setattr(join, "load_inputs", synthetic_inputs)
    yield tmp_path
    reset_workspace_cache()


def build(root: Path, name: str, **keys: str) -> dict[str, Any]:
    document = {
        "join": {
            "archive_panel_dir": "work/fixture/panel",
            "panel_start_year": 2020,
            "panel_end_year": 2021,
            **keys,
        }
    }
    return join.build(root / "work/join" / name, join.configure(document))


def classifications(report: dict[str, Any], root: Path, name: str) -> dict[str, str]:
    import csv

    with (root / "work/join" / name / "market_row_candidates.csv").open(encoding="utf-8") as handle:
        return {row["market_season"]: row["classification"] for row in csv.DictReader(handle)}


def test_without_the_keys_the_frozen_files_are_read_and_recorded(workspace: Path) -> None:
    settings = join.configure({"join": {}})
    assert settings.ch01_player_aliases == workspace / join.CH01_PLAYERS
    assert settings.ch01_event_crosswalk == workspace / join.CH01_EVENTS
    # describe() is what the prepare stage records about the join; it does not move.
    assert set(settings.describe()) == {
        "archive_panel_dir",
        "market_dir",
        "market_manifest",
        "market_profile_adapter",
        "span",
    }
    report = build(workspace, "default")
    assert report["inputs"]["ch01_player_aliases"] == {
        "path": join.CH01_PLAYERS,
        "sha256": sha(workspace / join.CH01_PLAYERS),
    }
    assert report["inputs"]["ch01_event_crosswalk"] == {
        "path": join.CH01_EVENTS,
        "sha256": sha(workspace / join.CH01_EVENTS),
    }
    assert classifications(report, workspace, "default") == {
        "2020": "candidate_q1_pinned_ch01",
        "2021": "unmatched_player_alias",
    }


def test_naming_the_frozen_files_explicitly_changes_no_output_byte(workspace: Path) -> None:
    build(workspace, "omitted")
    build(
        workspace,
        "named",
        ch01_player_aliases=join.CH01_PLAYERS,
        ch01_event_crosswalk=join.CH01_EVENTS,
    )
    for name in (*OUTPUTS, "audit.json"):
        omitted = (workspace / "work/join/omitted" / name).read_bytes()
        named = (workspace / "work/join/named" / name).read_bytes()
        assert omitted == named, name


def test_named_pin_files_are_read_hashed_and_validated(workspace: Path) -> None:
    players = "work/bindings/player_crosswalk_plus.json"
    events = "work/bindings/event_crosswalk_plus.json"
    report = build(workspace, "extended", ch01_player_aliases=players, ch01_event_crosswalk=events)
    assert report["inputs"]["ch01_player_aliases"] == {
        "path": players,
        "sha256": sha(workspace / players),
    }
    assert report["inputs"]["ch01_event_crosswalk"] == {
        "path": events,
        "sha256": sha(workspace / events),
    }
    # The frozen season is classified as before; the extension pins bind the later one.
    assert classifications(report, workspace, "extended") == {
        "2020": "candidate_q1_pinned_ch01",
        "2021": "candidate_q1_pinned_ch01",
    }
    # The frozen files were not the ones hashed.
    assert report["inputs"]["ch01_player_aliases"]["sha256"] != sha(workspace / join.CH01_PLAYERS)
    # validate() re-checks the named files, not the frozen ones.
    join.validate(workspace / "work/join/extended", join.configure({}))
    (workspace / players).write_text(
        json.dumps(FROZEN_PLAYERS + EXTENSION_PLAYERS[:1]), encoding="utf-8"
    )
    with pytest.raises(ChainError, match="input drift: ch01_player_aliases"):
        join.validate(workspace / "work/join/extended", join.configure({}))


def test_a_duplicate_pin_in_a_named_file_is_still_refused(workspace: Path) -> None:
    write_json(workspace / "work/bindings/dup.json", FROZEN_PLAYERS + FROZEN_PLAYERS[:1])
    with pytest.raises(ChainError, match="duplicate CH01 player aliases"):
        build(workspace, "dup", ch01_player_aliases="work/bindings/dup.json")


def test_the_chain_carries_the_keys_through_stage_config_overrides(workspace: Path) -> None:
    """No chain field is added: `stage_config_overrides.join.join` already reaches the
    emitted join config, and the runner declares the two paths as stage inputs."""
    document = json.loads(
        (Path(__file__).parents[1] / "configs/chains/atp_tier01_2017_2024.json").read_text(
            encoding="utf-8"
        )
    )
    section = document["chain"]
    plan = runner.year_plan(document)
    pins = {
        "ch01_player_aliases": "work/bindings/player_crosswalk_plus.json",
        "ch01_event_crosswalk": "work/bindings/event_crosswalk_plus.json",
    }
    overridden = {**section, "stage_config_overrides": {"join": {"join": pins}}}
    base = runner.write_configs(document, section, plan)["emitted"]
    configs = workspace / section["configs_dir"]
    base_bytes = {name: (configs / f"{name}.json").read_bytes() for name in base}
    for path in configs.iterdir():
        path.unlink()
    emitted = runner.write_configs(document, overridden, plan)["emitted"]
    changed = [
        name for name in emitted if (configs / f"{name}.json").read_bytes() != base_bytes[name]
    ]
    assert changed == ["join"]
    join_config = json.loads((configs / "join.json").read_text(encoding="utf-8"))
    assert {key: join_config["join"][key] for key in pins} == pins
    declared = runner.declared_input_paths(join_config)
    assert set(pins.values()) <= set(declared)
    # The emitted config resolves to the named files.
    settings = join.configure(join_config)
    assert settings.ch01_player_aliases == workspace / pins["ch01_player_aliases"]
    assert settings.ch01_event_crosswalk == workspace / pins["ch01_event_crosswalk"]
