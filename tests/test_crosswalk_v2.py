"""Unit tests for ``tennislab.panel.crosswalk_v2``.

The archive carried no unit-test file for ``crosswalk_v2.py``; its checks were the three
report modes (``round_trip``, ``self_id_check``, ``held_out_activity``) run against the
preserved Sackmann tarball, which is not in this repository. They are reproduced here
over a synthetic tarball with the mirror's member layout, sized so both repairs (the
disambiguator strip and the full-file fallback), the ambiguity rule and the confidence
tiers are each exercised, plus ``self_id_check`` end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tennislab.chain.common import ChainError
from tennislab.config import reset_workspace_cache
from tennislab.panel import crosswalk_v2, elo_crosswalk
from tests.test_mirror import build_fixture_archive, match

PLAYERS = [
    {"player_id": "100", "name_first": "Alexander", "name_last": "Zverev", "ioc": "GER"},
    {"player_id": "105", "name_first": "Andrey", "name_last": "Zverev", "ioc": "RUS"},
    {"player_id": "102", "name_first": "Felix", "name_last": "Auger-Aliassime", "ioc": "CAN"},
    {"player_id": "104", "name_first": "Novak", "name_last": "Djokovic", "ioc": "SRB"},
    # Never active in 2023-2024: reachable only through the full-file fallback.
    {"player_id": "300", "name_first": "Joao", "name_last": "Fonseca", "ioc": "BRA"},
    {"player_id": "303", "name_first": "Tomas", "name_last": "Machac", "ioc": "CZE"},
    {"player_id": "304", "name_first": "Tadeas", "name_last": "Machac", "ioc": "CZE"},
]


def pairing(year: int, number: int, winner: str, loser: str) -> dict[str, str]:
    return match(
        tourney_id=f"{year}-001",
        tourney_date=f"{year}0102",
        match_num=str(number),
        winner_id=winner,
        loser_id=loser,
        winner_name=next(p for p in PLAYERS if p["player_id"] == winner)["name_first"]
        + " "
        + next(p for p in PLAYERS if p["player_id"] == winner)["name_last"],
        loser_name=next(p for p in PLAYERS if p["player_id"] == loser)["name_first"]
        + " "
        + next(p for p in PLAYERS if p["player_id"] == loser)["name_last"],
    )


@pytest.fixture
def fixture_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    return build_fixture_archive(
        tmp_path / "mirror.tar.gz",
        matches={
            ("atp", 2023): [
                pairing(2023, 1, "100", "105"),
                pairing(2023, 2, "102", "104"),
            ],
            ("atp", 2024): [
                pairing(2024, 1, "100", "102"),
                pairing(2024, 2, "104", "105"),
            ],
        },
        players={"atp": PLAYERS},
    )


def test_strip_disambiguator() -> None:
    assert crosswalk_v2.strip_disambiguator("Hugo Dellien (tennis)") == ("Hugo Dellien", True)
    assert crosswalk_v2.strip_disambiguator("Hugo Dellien (tennis player)") == (
        "Hugo Dellien",
        True,
    )
    assert crosswalk_v2.strip_disambiguator("Marco Trungelliti (born 1990)") == (
        "Marco Trungelliti",
        True,
    )
    # A parenthetical without the keywords is part of the name, not a disambiguator.
    assert crosswalk_v2.strip_disambiguator("Queen's Club (London)") == (
        "Queen's Club (London)",
        False,
    )
    # A name that is nothing but a disambiguator is returned untouched.
    assert crosswalk_v2.strip_disambiguator("(tennis)") == ("(tennis)", False)


def test_confidence_and_population_tables_cover_every_method() -> None:
    assert set(crosswalk_v2.CONFIDENCE) == set(crosswalk_v2.POPULATION)
    assert crosswalk_v2.ACCEPTED_CONFIDENCE == frozenset({"high", "medium"})
    assert crosswalk_v2.CONFIDENCE["surname_unique"] == "low"
    assert crosswalk_v2.CONFIDENCE["full_file_surname_initial"] == "low"


def test_active_hit_carries_confidence_and_population(fixture_archive: Path) -> None:
    walk = crosswalk_v2.build(fixture_archive, "ATP")
    record = walk.lookup("Felix Auger-Aliassime")
    assert record["matched"] is True
    assert record["player_id"] == "102"
    assert record["match_method"] == "exact_full"
    assert record["confidence"] == "high"
    assert record["reference_population"] == "active_2023_2024"
    assert record["disambiguator_stripped"] is False
    assert record["tour"] == "ATP"


def test_disambiguator_is_stripped_before_matching(fixture_archive: Path) -> None:
    walk = crosswalk_v2.build(fixture_archive, "ATP")
    record = walk.lookup("Novak Djokovic (tennis)")
    assert record["matched"] is True
    assert record["player_id"] == "104"
    assert record["query_name"] == "Novak Djokovic (tennis)"
    assert record["query_after_strip"] == "Novak Djokovic"
    assert record["disambiguator_stripped"] is True


def test_ambiguous_active_hit_is_not_widened(fixture_archive: Path) -> None:
    walk = crosswalk_v2.build(fixture_archive, "ATP")
    record = walk.lookup("Zverev A.")
    assert record["matched"] is False
    assert record["reason"] == "ambiguous_surname_initial"
    assert set(record["candidate_ids"].split(";")) == {"100", "105"}
    # The full-file index would not help either, and must not be consulted.
    assert "reference_population" not in record


def test_full_file_fallback_exact_full_is_medium(fixture_archive: Path) -> None:
    walk = crosswalk_v2.build(fixture_archive, "ATP")
    record = walk.lookup("Joao Fonseca")
    assert record["matched"] is True
    assert record["player_id"] == "300"
    assert record["sackmann_name"] == "Joao Fonseca"
    assert record["match_method"] == "full_file_exact_full"
    assert record["confidence"] == "medium"
    assert record["reference_population"] == "full_players_file"
    assert record["candidates_considered"] == 1
    # The reversed "Last First" spelling is indexed too.
    assert walk.lookup("Fonseca Joao")["player_id"] == "300"


def test_full_file_fallback_surname_initial_is_low(fixture_archive: Path) -> None:
    walk = crosswalk_v2.build(fixture_archive, "ATP")
    record = walk.lookup("Fonseca J.")
    assert record["matched"] is True
    assert record["player_id"] == "300"
    assert record["match_method"] == "full_file_surname_initial"
    assert record["confidence"] == "low"
    assert record["confidence"] not in crosswalk_v2.ACCEPTED_CONFIDENCE


def test_full_file_ambiguity_is_reported_with_candidates(fixture_archive: Path) -> None:
    walk = crosswalk_v2.build(fixture_archive, "ATP")
    record = walk.lookup("Machac T.")
    assert record["matched"] is False
    assert record["player_id"] is None
    assert record["reason"] == "ambiguous_full_file_surname_initial"
    assert set(record["candidate_ids"].split(";")) == {"303", "304"}


def test_no_candidate_anywhere(fixture_archive: Path) -> None:
    walk = crosswalk_v2.build(fixture_archive, "ATP")
    record = walk.lookup("Nobody Atall")
    assert record["matched"] is False
    assert record["reason"] == "no_candidate_full_file"
    assert record["candidate_ids"] == ""


def test_full_file_index_shape() -> None:
    index = crosswalk_v2.FullFileIndex(
        [
            elo_crosswalk.Player(p["player_id"], p["name_first"], p["name_last"], p["ioc"])
            for p in PLAYERS
        ]
    )
    assert index.rows == len(PLAYERS)
    assert index.full["alexander zverev"] == ["100"]
    assert index.full["zverev alexander"] == ["100"]
    assert index.surname_initial[("machac", "t")] == ["303", "304"]
    assert index.lookup("Tomas Machac", "full_name") == (
        "303",
        "full_file_exact_full",
        ["303"],
    )
    assert index.lookup("", "full_name") == (None, "no_candidate_full_file", [])


def test_resolve_many_and_write_outputs(fixture_archive: Path, tmp_path: Path) -> None:
    walk = crosswalk_v2.build(fixture_archive, "ATP")
    matched, unmatched = crosswalk_v2.resolve_many(walk, ["Joao Fonseca", "Nobody Atall"])
    assert [row["player_id"] for row in matched] == ["300"]
    assert [row["reason"] for row in unmatched] == ["no_candidate_full_file"]
    outputs = crosswalk_v2.write_outputs(matched, unmatched, tmp_path / "out")
    assert set(outputs) == {"crosswalk.csv", "unmatched.csv"}
    header = (tmp_path / "out" / "crosswalk.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(crosswalk_v2.CROSSWALK_COLUMNS)
    header = (tmp_path / "out" / "unmatched.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(crosswalk_v2.UNMATCHED_COLUMNS)


def test_self_id_check_passes_on_the_fixture(fixture_archive: Path) -> None:
    report = crosswalk_v2.self_id_check(fixture_archive, "ATP", 2024)
    assert report["status"] == "PASS"
    assert report["distinct_name_id_pairs"] == 4
    assert report["crosswalk_v2"]["resolved_to_own_id"] == 4
    assert report["crosswalk_v2"]["wrong_id"] == 0
    assert report["unresolved_change"] == 0


def test_round_trip_reports_both_crosswalks(fixture_archive: Path) -> None:
    report = crosswalk_v2.round_trip(fixture_archive, "ATP", 2024)
    assert report["full_reference_players"] == len(PLAYERS)
    styles = report["styles"]
    assert styles["draw_full_name_with_disambiguator"]["crosswalk_v2"]["wrong_id"] == 0
    # The frozen crosswalk cannot strip the disambiguator; v2 can.
    assert styles["draw_full_name_with_disambiguator"]["unresolved_change"] < 0


def test_reserved_seasons_are_refused(fixture_archive: Path) -> None:
    with pytest.raises(ChainError):
        crosswalk_v2.round_trip(fixture_archive, "ATP", 2025)
    with pytest.raises(ChainError):
        crosswalk_v2.self_id_check(fixture_archive, "ATP", 2026)
    with pytest.raises(ChainError):
        crosswalk_v2.held_out_activity(fixture_archive, "ATP", 2024, activity=(2025,))


def test_re_exports_are_the_package_modules() -> None:
    from tennislab.panel import mirror
    from tennislab.ratings import elo

    assert crosswalk_v2.normalize_name is elo.normalize_name
    assert crosswalk_v2.Player is elo_crosswalk.Player
    assert crosswalk_v2.ARCHIVE_DEFAULT == mirror.ARCHIVE_DEFAULT
    assert crosswalk_v2.RESERVED_YEARS == mirror.RESERVED_YEARS
    assert crosswalk_v2.ACTIVITY_YEARS == elo_crosswalk.ACTIVITY_YEARS
