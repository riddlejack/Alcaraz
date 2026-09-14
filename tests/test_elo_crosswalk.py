"""Unit tests for ``tennislab.panel.elo_crosswalk``.

Ported from ``references/CONFIRM2026_elo/test_confirm2026_elo.py`` class
``CrosswalkTests``. Those tests round-tripped the real 2024 ATP and WTA player sets
out of the preserved ~50 MB Sackmann tarball, which is not part of this repository;
they are replaced here by the same assertions over a synthetic tarball with the
mirror's member layout, sized so every match method and the ambiguity quarantine
are exercised (two Zverevs, two Wongs sharing a first initial).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tennislab.panel import elo_crosswalk, mirror
from tests.test_mirror import build_fixture_archive, match

PLAYERS = [
    {"player_id": "100", "name_first": "Alexander", "name_last": "Zverev", "ioc": "GER"},
    {"player_id": "101", "name_first": "Mischa", "name_last": "Zverev", "ioc": "GER"},
    {"player_id": "102", "name_first": "Felix", "name_last": "Auger-Aliassime", "ioc": "CAN"},
    {"player_id": "104", "name_first": "Novak", "name_last": "Djokovic", "ioc": "SRB"},
    {"player_id": "200", "name_first": "Coco", "name_last": "Wong", "ioc": "USA"},
    {"player_id": "201", "name_first": "Chris", "name_last": "Wong", "ioc": "HKG"},
    # Present in the players file but never active: must not enter the index.
    {"player_id": "900", "name_first": "Retired", "name_last": "Zverev", "ioc": "GER"},
]


def pairing(year: int, number: int, winner: str, loser: str) -> dict[str, str]:
    return match(
        tourney_id=f"{year}-001",
        tourney_date=f"{year}0102",
        match_num=str(number),
        winner_id=winner,
        loser_id=loser,
    )


@pytest.fixture
def fixture_archive(tmp_path: Path) -> Path:
    return build_fixture_archive(
        tmp_path / "mirror.tar.gz",
        matches={
            ("atp", 2023): [
                pairing(2023, 1, "100", "101"),
                pairing(2023, 2, "200", "201"),
                pairing(2023, 3, "102", "104"),
            ],
            ("atp", 2024): [
                pairing(2024, 1, "100", "102"),
                pairing(2024, 2, "104", "201"),
            ],
        },
        players={"atp": PLAYERS},
    )


@pytest.fixture
def crosswalk(fixture_archive: Path) -> elo_crosswalk.Crosswalk:
    return elo_crosswalk.build(fixture_archive, "ATP")


def test_active_population_excludes_inactive_players(crosswalk) -> None:
    assert sorted(crosswalk.by_id) == ["100", "101", "102", "104", "200", "201"]
    assert "900" not in crosswalk.by_id
    assert len(crosswalk.active) == 6


def test_methods_and_quarantine(crosswalk) -> None:
    assert crosswalk.lookup("Alexander Zverev")["match_method"] == "exact_full"
    assert crosswalk.lookup("Alexander Zverev")["confidence"] == "high"
    assert crosswalk.lookup("Zverev A.")["match_method"] == "surname_initial"
    assert crosswalk.lookup("Zverev A.")["player_id"] == "100"
    assert crosswalk.lookup("Djokovic N.")["match_method"] == "surname_initial"
    assert (
        crosswalk.lookup("Felix Auger-Aliassime")["player_id"]
        == crosswalk.lookup("Auger-Aliassime F.")["player_id"]
    )
    ambiguous = crosswalk.lookup("Wong C.")
    assert ambiguous["matched"] is False
    assert ambiguous["reason"] == "ambiguous_surname_initial"
    assert len(str(ambiguous["candidate_ids"]).split(";")) > 1
    assert crosswalk.lookup("Notarealplayer Q.")["reason"] == "no_candidate"


def test_ambiguity_does_not_fall_through_to_a_weaker_method(crosswalk) -> None:
    """A method that resolves to more than one id stops the search; it never degrades."""
    record = crosswalk.lookup("Zverev")
    assert record["matched"] is False
    assert record["reason"] == "ambiguous_surname_unique"
    assert set(str(record["candidate_ids"]).split(";")) == {"100", "101"}


def test_surname_unique_resolves_a_bare_surname(crosswalk) -> None:
    record = crosswalk.lookup("Djokovic")
    assert record["matched"] is True
    assert record["match_method"] == "surname_unique"
    assert record["confidence"] == "low"


def test_round_trips_the_full_2024_player_set(fixture_archive: Path) -> None:
    report = elo_crosswalk.round_trip(fixture_archive, "ATP", season=2024)
    assert report["season_player_ids"] == 4
    assert report["season_player_ids_present_in_players_file"] == 4
    for style in ("draw_full_name", "odds_api_full_name"):
        stats = report["styles"][style]
        assert stats["wrong_id"] == 0
        assert stats["coverage"] == 1.0
    tennis_data = report["styles"]["tennis_data_surname_initial"]
    assert tennis_data["wrong_id"] == 0
    # "Wong C." collides with the other active Wong and is quarantined, never guessed.
    assert tennis_data["coverage"] == 0.75
    assert tennis_data["unresolved"] == tennis_data["failures"] == 1


def test_outputs_are_written(crosswalk, tmp_path: Path) -> None:
    matched, unmatched = elo_crosswalk.resolve_many(
        crosswalk, ["Alexander Zverev", "Wong C."], "ATP"
    )
    out_dir = tmp_path / "out"
    elo_crosswalk.write_outputs(matched, unmatched, out_dir)
    crosswalk_csv = (out_dir / "crosswalk.csv").read_text(encoding="utf-8")
    unmatched_csv = (out_dir / "unmatched.csv").read_text(encoding="utf-8")
    assert crosswalk_csv.splitlines()[0] == ",".join(elo_crosswalk.CROSSWALK_COLUMNS)
    assert unmatched_csv.splitlines()[0] == ",".join(elo_crosswalk.UNMATCHED_COLUMNS)
    assert "exact_full" in crosswalk_csv
    assert "100" in crosswalk_csv
    assert "ambiguous_surname_initial" in unmatched_csv


def test_load_players_reads_the_mirror_member(fixture_archive: Path) -> None:
    players = elo_crosswalk.load_players(fixture_archive, "ATP")
    assert len(players) == len(PLAYERS)
    assert players[0].display == "Alexander Zverev"


def test_names_and_constants_are_re_exported() -> None:
    """crosswalk_v2 reads these off this module, as it did off the archive copy."""
    assert elo_crosswalk.ARCHIVE_DEFAULT == mirror.ARCHIVE_DEFAULT
    assert elo_crosswalk.ARCHIVE_ROOT == mirror.ARCHIVE_ROOT
    assert elo_crosswalk.RESERVED_YEARS == mirror.RESERVED_YEARS
    assert elo_crosswalk.ACTIVITY_YEARS == (2023, 2024)
    assert elo_crosswalk.TENNIS_DATA_STYLE.match("Zverev A.").group("last") == "Zverev"
    assert elo_crosswalk.Player("1", "A", "B", "GER").display == "A B"
