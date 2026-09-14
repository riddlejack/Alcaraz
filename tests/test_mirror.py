"""Unit tests for ``tennislab.panel.mirror``.

Ported from ``references/CONFIRM2026_elo/test_confirm2026_elo.py`` class
``ReservedWindowGuardTests``. The archive's other mirror assertions ran against the
preserved ~50 MB Sackmann tarball, which is not part of this repository; they are
replaced here by a synthetic tarball with the same member layout that exercises
``event_rule``, ``classify_status``, the row filter, the exclusion counters and the
sort key.
"""

from __future__ import annotations

import csv
import io
import tarfile
from pathlib import Path

import pytest

from tennislab.chain.common import ChainError
from tennislab.panel import mirror

MATCH_COLUMNS = (
    "tourney_id",
    "tourney_name",
    "surface",
    "tourney_level",
    "tourney_date",
    "match_num",
    "winner_id",
    "winner_name",
    "loser_id",
    "loser_name",
    "score",
    "round",
    "best_of",
)

PLAYER_COLUMNS = ("player_id", "name_first", "name_last", "hand", "dob", "ioc")


def match(**overrides: str) -> dict[str, str]:
    base = {
        "tourney_id": "2023-001",
        "tourney_name": "Adelaide",
        "surface": "Hard",
        "tourney_level": "A",
        "tourney_date": "20230102",
        "match_num": "1",
        "winner_id": "100",
        "winner_name": "Alpha One",
        "loser_id": "200",
        "loser_name": "Beta Two",
        "score": "6-3 6-4",
        "round": "R32",
        "best_of": "3",
    }
    return {**base, **overrides}


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def build_fixture_archive(
    path: Path,
    *,
    matches: dict[tuple[str, int], list[dict[str, str]]],
    players: dict[str, list[dict[str, str]]],
) -> Path:
    """A tarball with the mirror's member layout, for tests that must open members."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for (tour, year), rows in matches.items():
            payload = _csv_bytes(MATCH_COLUMNS, rows)
            info = tarfile.TarInfo(f"{mirror.ARCHIVE_ROOT}/{tour}/{tour}_matches_{year}.csv")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        for tour, rows in players.items():
            payload = _csv_bytes(PLAYER_COLUMNS, rows)
            info = tarfile.TarInfo(f"{mirror.ARCHIVE_ROOT}/{tour}/{tour}_players.csv")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return path


@pytest.fixture
def fixture_archive(tmp_path: Path) -> Path:
    rows = [
        match(match_num="3", round="QF"),
        match(match_num="2", round="R16", surface="Clay", tourney_id="2023-002"),
        match(match_num="1", tourney_date="20230109", tourney_id="2023-003"),
        match(match_num="4", tourney_name="Laver Cup"),
        match(match_num="5", tourney_name="NextGen Finals"),
        match(match_num="6", tourney_name="Tour Finals", tourney_level="F"),
        match(match_num="7", tourney_name="Olympics", tourney_level="O"),
        match(match_num="8", score="W/O"),
        match(match_num="9", score="6-3 RET"),
        match(match_num="10", surface="Carpet"),
        match(match_num="11", surface="Unknown"),
        match(match_num="12", best_of="4"),
        match(match_num="13", winner_id=""),
        match(match_num="14", tourney_level="C"),
    ]
    return build_fixture_archive(
        tmp_path / "mirror.tar.gz",
        matches={("atp", 2023): rows},
        players={
            "atp": [{"player_id": "100", "name_first": "Alpha", "name_last": "One", "ioc": "USA"}]
        },
    )


def test_reserved_members_are_refused() -> None:
    for member in (
        "tennis-sackmann-archive-x/atp/atp_matches_2025.csv",
        "tennis-sackmann-archive-x/atp/atp_matches_2026.csv",
        "tennis-sackmann-archive-x/wta/wta_matches_2025.csv",
        "tennis-sackmann-archive-x/wta/wta_matches_2026.csv",
        "data/raw/RES2026/anything.csv",
    ):
        with pytest.raises(mirror.ReservedWindowError):
            mirror.guard_member(member)


def test_reserved_years_are_refused_by_extract(tmp_path: Path) -> None:
    """The guard fires before any member is opened, so the path need not exist."""
    with pytest.raises(mirror.ReservedWindowError):
        mirror.extract_results(tmp_path / "absent.tar.gz", "ATP", [2024, 2025])


def test_permitted_members_pass_the_guard() -> None:
    for year in (2005, 2017, 2024):
        mirror.guard_member(f"tennis-sackmann-archive-x/atp/atp_matches_{year}.csv")
    mirror.guard_member("tennis-sackmann-archive-x/atp/atp_players.csv")


def test_classify_status() -> None:
    assert mirror.classify_status("6-3 6-4") == ("completed", "true")
    assert mirror.classify_status("W/O") == ("walkover", "false")
    assert mirror.classify_status("WALKOVER") == ("walkover", "false")
    assert mirror.classify_status("6-3 RET") == ("retired", "true")
    assert mirror.classify_status("DEF") == ("default", "")
    assert mirror.classify_status("ABN") == ("abandoned", "")
    assert mirror.classify_status("") == ("unknown", "")


def test_event_rule_scope() -> None:
    assert mirror.event_rule(match(tourney_name="Laver Cup"))[:2] == (False, "excluded_team")
    assert mirror.event_rule(match(tourney_name="Davis Cup Finals"))[:2] == (False, "excluded_team")
    assert mirror.event_rule(match(tourney_name="NextGen Finals"))[:2] == (
        False,
        "excluded_nextgen",
    )
    assert mirror.event_rule(match(tourney_name="Tour Finals", tourney_level="F"))[:2] == (
        True,
        "main_tour_finals",
    )
    assert mirror.event_rule(match(tourney_name="Olympics", tourney_level="O"))[:2] == (
        True,
        "olympics_consistency_override",
    )
    assert mirror.event_rule(match(tourney_name="Olympics", tourney_level="A"))[:2] == (
        True,
        "level_A",
    )
    assert mirror.event_rule(match(tourney_level="C"))[:2] == (False, "excluded_other_level")
    # The WTA level vocabulary is the module's declared extension.
    assert mirror.event_rule(match(tourney_level="PM"), "WTA")[:2] == (True, "level_PM")
    assert mirror.event_rule(match(tourney_level="D"), "WTA")[:2] == (False, "excluded_other_level")


def test_anchor_date() -> None:
    assert mirror.anchor_date("20230102").isoformat() == "2023-01-02"
    with pytest.raises(ValueError):
        mirror.anchor_date("2023-01-02")


def test_extract_results_filters_counts_and_orders(fixture_archive: Path) -> None:
    rows, stats, hashes = mirror.extract_results(fixture_archive, "ATP", [2023])
    assert stats["source_rows"] == 14
    assert stats["included"] == 7
    assert stats["excluded_event"] == 3  # Laver Cup, NextGen, level C
    assert stats["excluded_status_walkover"] == 1
    assert stats["excluded_surface"] == 1
    assert stats["excluded_best_of"] == 1
    assert stats["excluded_missing_id"] == 1
    assert list(hashes) == [f"{mirror.ARCHIVE_ROOT}/atp/atp_matches_2023.csv"]
    # Chronological, then the mirror's own (tourney_id, match_num) order.
    assert [(r["date"], r["tourney_id"], r["match_num"]) for r in rows] == [
        ("2023-01-02", "2023-001", "3"),
        ("2023-01-02", "2023-001", "6"),
        ("2023-01-02", "2023-001", "7"),
        ("2023-01-02", "2023-001", "9"),
        ("2023-01-02", "2023-001", "10"),
        ("2023-01-02", "2023-002", "2"),
        ("2023-01-09", "2023-003", "1"),
    ]
    assert rows[0]["source"] == (f"{mirror.ARCHIVE_ROOT}/atp/atp_matches_2023.csv#2023-001/3")


def test_write_results_csv_column_order(fixture_archive: Path, tmp_path: Path) -> None:
    rows, _stats, _hashes = mirror.extract_results(fixture_archive, "ATP", [2023])
    out = tmp_path / "results.csv"
    mirror.write_results_csv(rows, out)
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(mirror.CANONICAL_COLUMNS)
    mirror.write_results_csv(rows, out, extra_columns=("tourney_id", "match_num"))
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join([*mirror.CANONICAL_COLUMNS, "tourney_id", "match_num"])


def test_active_player_ids_and_list_members(fixture_archive: Path) -> None:
    assert mirror.active_player_ids(fixture_archive, "ATP", [2023]) == {"100", "200"}
    names = [name for name, _size in mirror.list_members(fixture_archive)]
    assert f"{mirror.ARCHIVE_ROOT}/atp/atp_players.csv" in names


def test_unsupported_tour_is_refused(fixture_archive: Path) -> None:
    with pytest.raises(ValueError):
        mirror.extract_results(fixture_archive, "ITF", [2023])


def test_archive_default_is_a_workspace_relative_string(tmp_path, monkeypatch) -> None:
    assert not Path(mirror.ARCHIVE_DEFAULT).is_absolute()
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    from tennislab.config import reset_workspace_cache

    reset_workspace_cache()
    try:
        assert mirror.resolve_archive() == tmp_path / mirror.ARCHIVE_DEFAULT
        with pytest.raises(ChainError):
            mirror.resolve_archive("/etc/passwd")
    finally:
        reset_workspace_cache()
