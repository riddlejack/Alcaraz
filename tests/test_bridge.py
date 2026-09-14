"""Unit tests for ``tennislab.sources.bridge``.

The archive carried no unit-test file for ``bridge_res2026.py``: its checks were the
``--self-test-year 2024`` round trip, ``--event-self-check`` and
``--generate-preview-season`` against the preserved Sackmann tarball, which is not in
this repository, plus one ``synthesize_market_rows`` test in
``CONFIRM2026_models/test_audit_asof_contract.py`` written against a later as-of
revision of the bridge whose fields this revision does not carry. The pure functions
are pinned here directly; the archive-reading paths (event index, generation, dedupe,
tar composition, the full ``build``) run over a synthetic tarball with the mirror's
member layout and the bridge's exact annual schema.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from tennislab.chain.common import ChainError, sha256
from tennislab.chronology.dating import DateBasis
from tennislab.config import reset_workspace_cache
from tennislab.panel import crosswalk_v2, mirror
from tennislab.sources import bridge

PLAYERS = [
    {"player_id": "100", "name_first": "Jannik", "name_last": "Sinner", "ioc": "ITA"},
    {"player_id": "101", "name_first": "Carlos", "name_last": "Alcaraz", "ioc": "ESP"},
    {"player_id": "102", "name_first": "Alex", "name_last": "Michelsen", "ioc": "USA"},
    {"player_id": "103", "name_first": "Novak", "name_last": "Djokovic", "ioc": "SRB"},
]
PLAYER_COLUMNS = ("player_id", "name_first", "name_last", "hand", "dob", "ioc")
NAMES = {p["player_id"]: f"{p['name_first']} {p['name_last']}" for p in PLAYERS}


def sackmann_row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(bridge.SACKMANN_FIELDS, "")
    row.update(
        {
            "tourney_id": "2024-0421",
            "tourney_name": "Canada Masters",
            "surface": "Hard",
            "draw_size": "16",
            "tourney_level": "M",
            "tourney_date": "20240805",
            "match_num": "1",
            "winner_id": "100",
            "loser_id": "101",
            "score": "6-3 6-4",
            "best_of": "3",
            "round": "R16",
        }
    )
    row.update(overrides)
    row["winner_name"] = row["winner_name"] or NAMES.get(row["winner_id"], "")
    row["loser_name"] = row["loser_name"] or NAMES.get(row["loser_id"], "")
    return row


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def build_bridge_archive(
    path: Path, matches: dict[int, list[dict[str, str]]], tour: str = "atp"
) -> Path:
    """A tarball with the mirror's member layout and the bridge's exact annual schema."""
    with tarfile.open(path, "w:gz") as tar:
        for year, rows in matches.items():
            payload = _csv_bytes(bridge.SACKMANN_FIELDS, rows)
            info = tarfile.TarInfo(f"{mirror.ARCHIVE_ROOT}/{tour}/{tour}_matches_{year}.csv")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        payload = _csv_bytes(PLAYER_COLUMNS, PLAYERS)
        info = tarfile.TarInfo(f"{mirror.ARCHIVE_ROOT}/{tour}/{tour}_players.csv")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return path


MIRROR_2023 = [
    sackmann_row(tourney_id="2023-0421", tourney_date="20230807", winner_id="100", loser_id="102"),
    sackmann_row(
        tourney_id="2023-0421",
        tourney_date="20230807",
        match_num="2",
        winner_id="103",
        loser_id="101",
        round="QF",
    ),
]
MIRROR_2024 = [sackmann_row()]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    return tmp_path


@pytest.fixture
def archive(workspace: Path) -> Path:
    return build_bridge_archive(workspace / "mirror.tar.gz", {2023: MIRROR_2023, 2024: MIRROR_2024})


def wiki_row(**overrides: str) -> dict[str, str]:
    row = {
        "source": "wikipedia",
        "tour": "ATP",
        "tournament": "National_Bank_Open",
        "round": "R1",
        "winner": "Jannik Sinner (tennis)",
        "loser": "Carlos Alcaraz",
        "winner_display": "Jannik Sinner",
        "loser_display": "Carlos Alcaraz",
        "score": "6–3 6–4",
        "sets_played": "",
        "status": "completed",
        "week_label": "5 Aug",
        "source_url": "synthetic://2024-0421",
    }
    row.update(overrides)
    return row


WIKI_ROWS = [
    wiki_row(),
    wiki_row(
        winner="Alex Michelsen",
        loser="Novak Djokovic",
        winner_display="Alex Michelsen",
        loser_display="Novak Djokovic",
        score="7–6(5) 0–0 retired",
        status="retired",
    ),
    wiki_row(winner="Nobody Known", loser="Novak Djokovic", winner_display="Nobody Known"),
]


# ------------------------------------------------------------- pure functions


def test_normalized_and_ascii_fold() -> None:
    assert bridge.normalized("US_Open") == "us open"
    assert bridge.normalized("  Winston-Salem   Open ") == "winston salem open"
    assert bridge.normalized("Generali Open Kitzbühel") == "generali open kitzbühel"
    assert bridge._ascii_fold("Generali Open Kitzbühel") == "generali open kitzbuhel"
    assert bridge._ascii_fold("Queen's Club Championships") == "queen s club championships"
    assert bridge._ascii_fold("Libéma Open") == "libema open"


def test_find_edition_direct_alias_and_folded_alias() -> None:
    editions = {
        name: {"tourney_name": name} for name in ("Us Open", "Kitzbuhel", "s Hertogenbosch")
    }
    index = {f"name:{bridge.normalized(name)}": ed for name, ed in editions.items()}
    assert bridge.find_edition(index, "US_Open") == (editions["Us Open"], "normalized_name")
    assert bridge.find_edition(index, "Libema Open") == (
        editions["s Hertogenbosch"],
        "alias:s Hertogenbosch",
    )
    assert bridge.find_edition(index, "Generali Open Kitzbühel") == (
        editions["Kitzbuhel"],
        "ascii_folded_alias:Kitzbuhel",
    )
    # The sanitized spelling RES2026 writes for the same event is registered too.
    assert bridge.find_edition(index, "Generali_Open_Kitzb_hel")[1] == "alias:Kitzbuhel"
    assert bridge.find_edition(index, "Nowhere Open") == (None, "")


def test_event_resolution_table_policies() -> None:
    edition = {
        "tourney_name": "Us Open",
        "tourney_id": "2024-560",
        "season": 2024,
        "draw_size": "128",
        "tourney_level": "G",
        "best_of": "5",
    }
    index = {"name:us open": edition}
    with pytest.raises(ChainError, match="resolve to no mirror edition"):
        bridge.event_resolution_table(index, "ATP")
    report = bridge.event_resolution_table(index, "ATP", "quarantine")
    assert report["status"] == "PASS_WITH_UNRESOLVED_QUARANTINED"
    assert report["events_resolved_in_scope"] == 1
    assert "US Open" not in report["unresolved_in_scope"]
    assert "Wimbledon Championships" in report["unresolved_in_scope"]
    assert report["events_in_scope"] == sum(1 for tour, _ in bridge.RES2026_EVENTS if tour == "ATP")
    with pytest.raises(ChainError, match="unknown unresolved_event_policy"):
        bridge.event_resolution_table(index, "ATP", "ignore")


def test_round_label_vocabulary() -> None:
    assert bridge.numeric_round("R1") == 1
    assert bridge.numeric_round("Round 2") == 2
    assert bridge.numeric_round("QF") is None
    assert bridge.canonical_round("Quarterfinals") == ("QF", None)
    assert bridge.canonical_round("The Final") == ("F", None)
    assert bridge.canonical_round("R3") == ("", 3)
    with pytest.raises(ChainError, match="unknown round label"):
        bridge.canonical_round("Playoff")


def test_week_starts_reads_all_four_cell_shapes() -> None:
    assert bridge.week_starts("8 Jun") == ([(6, 8)], None)
    assert bridge.week_starts("Jun 8") == ([(6, 8)], None)
    assert bridge.week_starts("31 Aug7 Sep") == ([(8, 31), (9, 7)], None)
    assert bridge.week_starts("Aug 31Sep 7") == ([(8, 31), (9, 7)], None)
    assert bridge.week_starts("31 August 2026") == ([(8, 31)], 2026)
    with pytest.raises(ChainError, match="cannot parse week label"):
        bridge.week_starts("sometime in June")
    with pytest.raises(ChainError, match="cannot parse week label"):
        bridge.week_starts("")


def test_parse_week_label_takes_the_first_week_start() -> None:
    assert bridge.parse_week_label("31 Aug7 Sep", 2026) == dt.date(2026, 8, 31)
    assert bridge.parse_week_label("Aug 31Sep 7", 2026) == dt.date(2026, 8, 31)
    assert bridge.parse_week_label("2026-08-31", 2026) == dt.date(2026, 8, 31)
    assert bridge.parse_week_label("5 Aug", 2024) == dt.date(2024, 8, 5)
    with pytest.raises(ChainError, match="not in season"):
        bridge.parse_week_label("31 Aug 2025", 2026)
    with pytest.raises(ChainError, match="not in season"):
        bridge.parse_week_label("2025-08-31", 2026)
    with pytest.raises(ChainError, match="no date in season"):
        bridge.parse_week_label("31 Feb", 2026)


def test_fallback_event_end_is_last_week_start_plus_seven() -> None:
    assert bridge.fallback_event_end("31 Aug7 Sep", 2026) == dt.date(2026, 9, 14)
    # The 2024 Canada final was played on the Monday after its week (5 Aug + 7).
    assert bridge.fallback_event_end("5 Aug", 2024) == dt.date(2024, 8, 12)
    assert bridge.fallback_event_end("Aug 12", 2024) == dt.date(2024, 8, 19)
    with pytest.raises(ChainError, match="not in season"):
        bridge.fallback_event_end("5 Aug 2023", 2024)


def test_infobox_completion_date(tmp_path: Path) -> None:
    page = tmp_path / "atp_US_Open.html"
    page.write_bytes(
        b'<html><body><table class="infobox"><tr><th>Date</th>'
        b"<td>29 August \xe2\x80\x93 12 September 2026</td></tr></table></body></html>"
    )
    parsed, text, digest = bridge.infobox_completion_date(page, 2026)
    assert parsed == dt.date(2026, 9, 12)
    assert "12 September 2026" in text
    assert digest == sha256(page)
    page.write_bytes(
        b'<div class="infobox"><tr><th scope="row">Date</th><td>September 12, 2026</td></tr></div>'
    )
    assert bridge.infobox_completion_date(page, 2026)[0] == dt.date(2026, 9, 12)
    # Outside the season: no date, the cell text still reported.
    assert bridge.infobox_completion_date(page, 2025)[0] is None
    assert bridge.infobox_completion_date(page, 2025)[1] == "September 12, 2026"
    page.write_bytes(b"<html><body>no box here</body></html>")
    assert bridge.infobox_completion_date(page, 2026) == (None, "", sha256(page))


def test_event_end_dating_route(tmp_path: Path) -> None:
    first = {"week_label": "31 Aug7 Sep", "_source_path": "/x/atp_US_Open_mens_singles.csv"}
    anchor = dt.date(2026, 8, 31)
    page = tmp_path / "atp_US_Open_mens_singles.html"
    page.write_bytes(
        b'<table class="infobox"><tr><th>Date</th><td>12 September 2026</td></tr></table>'
    )
    end, basis, text, digest = bridge.event_end(first, 2026, anchor, tmp_path)
    assert (end, basis) == (dt.date(2026, 9, 12), bridge.INFOBOX_END_BASIS)
    assert text == "12 September 2026" and digest == sha256(page)
    # An infobox date before the anchor is unusable; the calendar-cell rule stands.
    page.write_bytes(b'<table class="infobox"><tr><th>Date</th><td>1 August 2026</td></tr></table>')
    end, basis, _text, _digest = bridge.event_end(first, 2026, anchor, tmp_path)
    assert (end, basis) == (dt.date(2026, 9, 14), bridge.FALLBACK_END_BASIS + ":infobox_unusable")
    # No retained page: the calendar-cell rule, and nothing read.
    end, basis, text, digest = bridge.event_end(first, 2026, anchor, None)
    assert (end, basis, text, digest) == (dt.date(2026, 9, 14), bridge.FALLBACK_END_BASIS, "", "")


def test_normalize_score() -> None:
    assert bridge.normalize_score("6–4 3–6 0–0 retired", "retired") == "6-4 3-6 RET"
    assert bridge.normalize_score("7-6(5) 6-6 defaulted", "default") == "7-6(5) 6-6 DEF"
    assert bridge.normalize_score("w/o", "walkover") == "W/O"
    assert bridge.normalize_score("6-1, 6-2", "completed") == "6-1 6-2"
    with pytest.raises(ChainError, match="still carries letters"):
        bridge.normalize_score("6-1 abandoned early", "completed")


def test_draw_order_and_bracket_top() -> None:
    rounds = {"F": 1, "QF": 4, "R32": 16, "RR": 12, "SF": 2, "R16": 8}
    assert bridge._draw_order(rounds) == ["R32", "R16", "QF", "SF", "F", "RR"]
    assert bridge.bracket_top("96") == 128
    assert bridge.bracket_top("56") == 64
    assert bridge.bracket_top("32") == 32
    assert bridge.bracket_top("") is None
    assert bridge.bracket_top("1") is None


def edition(rounds: dict[str, int], draw_size: str = "32") -> dict[str, Any]:
    return {"rounds": rounds, "ordered_rounds": bridge._draw_order(rounds), "draw_size": draw_size}


def test_derive_draw_structure_labels_from_the_ladder() -> None:
    carried = edition({"R32": 16, "R16": 8, "QF": 4, "SF": 2, "F": 1})
    structure, refusal = bridge.derive_draw_structure(
        {"R1": 16, "R2": 8, "QF": 4, "SF": 2, "F": 1}, carried
    )
    assert refusal == ""
    assert structure["mapping"] == {"R1": "R32", "R2": "R16", "QF": "QF", "SF": "SF", "F": "F"}
    assert structure["page_round_order"] == ["R1", "R2", "QF", "SF", "F"]
    assert structure["draw_size"] == "32" and structure["draw_size_basis"] == "carried_edition"
    assert structure["warnings"] == [] and structure["rounds_pending"] == []
    # A 96-draw against a 64 carried edition: the bracket changed, so the acquired
    # draw's own bracket is the draw size and the change is a warning, not a refusal.
    grown, refusal = bridge.derive_draw_structure(
        {"R1": 32, "R2": 32, "R3": 16, "R4": 8, "QF": 4, "SF": 2, "F": 1},
        edition({"R64": 32, "R32": 16, "R16": 8, "QF": 4, "SF": 2, "F": 1}, "64"),
    )
    assert refusal == ""
    assert grown["mapping"]["R1"] == "R128" and grown["mapping"]["R4"] == "R16"
    assert grown["draw_size"] == "128" and grown["draw_size_basis"] == "acquired_draw"
    assert grown["warnings"][0] == "draw_size_from_acquired_draw:128_carried_edition:64"
    # An incomplete draw reports the rounds it lacks as pending, not invented.
    partial, refusal = bridge.derive_draw_structure({"R1": 16, "R2": 8}, carried)
    assert refusal == ""
    assert partial["rounds_pending"] == ["QF", "SF", "F"]
    assert "rounds_pending:QF,SF,F" in partial["warnings"]
    # Counts that fit no ladder are refused.
    assert bridge.derive_draw_structure({"R1": 16, "R2": 7, "QF": 4}, carried)[1].startswith(
        "round_match_count_differs:R16=7"
    )
    assert bridge.derive_draw_structure({"R1": 17}, carried)[1].startswith("first_round_matches_17")
    assert bridge.derive_draw_structure({"R1": 8, "SF": 2}, carried)[1] == (
        "rounds_not_contiguous:SF,R16"
    )
    assert bridge.derive_draw_structure({}, carried)[1] == "draw_has_no_rounds"
    assert bridge.derive_draw_structure({"Round Robin": 12, "F": 1}, carried)[1] == (
        "non_ladder_round_label:RR"
    )


def test_draw_structure_falls_back_to_edition_alignment_for_round_robin() -> None:
    carried = edition({"RR": 12, "SF": 2, "F": 1}, "8")
    structure, refusal = bridge.draw_structure({"Round Robin": 12, "SF": 2, "F": 1}, carried)
    assert refusal == ""
    assert structure["basis"] == "carried_edition_alignment"
    assert structure["mapping"] == {"Round Robin": "RR", "SF": "SF", "F": "F"}
    assert structure["page_round_order"] == ["SF", "F", "Round Robin"]
    structure, refusal = bridge.draw_structure({"Round Robin": 10, "SF": 2, "F": 1}, carried)
    assert structure is None
    assert refusal == "non_ladder_round_label:RR;round_match_count_differs:Round Robin=10_vs_RR=12"


def test_align_rounds_refusals() -> None:
    carried = edition({"R32": 16, "R16": 8, "QF": 4, "SF": 2, "F": 1})
    assert bridge.align_rounds({"R1": 16, "R2": 8, "QF": 4}, carried)[0] == {
        "R1": "R32",
        "R2": "R16",
        "QF": "QF",
    }
    assert bridge.align_rounds({"R1": 16}, carried)[1] == "numbered_round_count_differs:1_vs_2"
    assert bridge.align_rounds({"R1": 16, "R2": 8, "BR": 1}, carried)[1] == "edition_lacks_round:BR"


def test_dedupe_key_is_unordered_on_the_pair() -> None:
    assert bridge.dedupe_key("2024-0421", "F", "200", "100") == ("0421", "F", "100", "200")
    assert bridge.dedupe_key("0421", "F", "100", "200") == ("0421", "F", "100", "200")


def test_round_order_is_provenance_only() -> None:
    assert bridge.round_order("F", 96) == 6
    assert bridge.round_order("R64", 96) == 1
    assert bridge.round_order("R128", 128) == 0
    assert bridge.round_order("R16", "16") == 0
    assert bridge.round_order("F", "") is None
    assert bridge.round_order("R256", 128) is None
    assert bridge.round_order("RR", 8) is None
    # The archive's first design dated the Canada 2026 final at start + 6 = 9 Aug, four
    # days before it was played; that route is gone and the string is never written.
    source = Path(bridge.__file__).read_text(encoding="utf-8")
    assert DateBasis.START_PLUS_ROUND_ORDER.value not in source
    assert "START_PLUS_ROUND_ORDER" not in source
    assert bridge.SYNTHESIZED_DATE_BASIS == DateBasis.INFERRED_EVENT_END == "inferred_event_end"
    assert bridge.TENNIS_DATA_DATE_BASIS == DateBasis.REPORTED_MATCH_DATE
    assert DateBasis(bridge.SYNTHESIZED_DATE_BASIS).proves_availability


def test_wta_market_round() -> None:
    assert bridge.wta_market_round("R32", "32") == "1st Round"
    assert bridge.wta_market_round("R16", "32") == "2nd Round"
    assert bridge.wta_market_round("R64", "96") == "2nd Round"
    assert bridge.wta_market_round("R16", "128") == "4th Round"
    assert bridge.wta_market_round("F", "32") == "The Final"
    assert bridge.wta_market_round("RR", "8") == "Round Robin"
    assert bridge.wta_market_round("R32", "") is None
    assert bridge.wta_market_round("R8", "128") is None


def test_market_style() -> None:
    assert bridge.market_style("Jannik Sinner") == "Sinner J."
    assert bridge.market_style("Felix Auger Aliassime") == "Auger Aliassime F."
    assert bridge.market_style("Nadal") == "Nadal"


class Join:
    """The two `join` hooks the bridge calls, with the join's own semantics."""

    @staticmethod
    def normalized(value: str) -> str:
        return "".join(ch for ch in value.casefold() if ch.isalnum())

    @staticmethod
    def round_agrees(archive: dict[str, str], market_round: str) -> bool:
        return bridge.wta_market_round(archive["round"], archive["draw_size"]) == market_round


def test_market_event_identity_bases() -> None:
    match = {"tourney_id": "2026-0421", "tourney_name": "Canada Masters"}
    carried = {
        "0421": {
            "market_tournament": "National Bank Open",
            "market_location": "Toronto",
            "market_event_number": "54",
        }
    }
    event, basis, warning = bridge.market_event_identity(match, {}, carried, Join())
    assert event == {"ATP": "54", "Location": "Toronto", "Tournament": "Canada Masters"}
    assert basis == "archive_event_name_exact_by_construction" and warning == ""
    agreeing = {
        "560": {
            "market_tournament": "US Open",
            "market_location": "New York",
            "market_event_number": "60",
        }
    }
    event, basis, _ = bridge.market_event_identity(
        {"tourney_id": "2026-560", "tourney_name": "Us Open"}, {}, agreeing, Join()
    )
    assert event["Tournament"] == "US Open"
    assert basis == "carried_tennis_data_name_matches_archive_name"
    qualified = {
        "560": {
            "market_tournament": "US Open",
            "market_location": "New York",
            "market_event_numbers": "60",
        }
    }
    _, basis, _ = bridge.market_event_identity(
        {"tourney_id": "2026-560", "tourney_name": "Us Open"}, qualified, {}, Join()
    )
    assert basis == "qualified_crosswalk_name_matches_archive_name"
    _, basis, warning = bridge.market_event_identity(
        {"tourney_id": "2026-999", "tourney_name": "Nowhere"}, {}, {}, Join()
    )
    assert basis == "archive_event_name_exact_by_construction"
    assert warning == "no_carried_tennis_data_location_or_number"
    event, basis, warning = bridge.market_event_identity(
        {"tourney_id": "2026-0421", "tourney_name": ""}, {}, carried, Join()
    )
    assert event["Tournament"] == "National Bank Open"
    assert basis == "carried_tennis_data_name_without_archive_name"
    assert warning == "archive_event_carries_no_tourney_name"


def test_wta_market_event_identity() -> None:
    carried = {
        "0421": {
            "market_tournament": "National Bank Open",
            "market_location": "Montreal",
            "market_event_number": "38",
        }
    }
    match = {"tourney_id": "2026-0421", "tourney_name": "Montreal"}
    event, basis, warning = bridge.wta_market_event_identity(match, carried)
    assert event == {"WTA": "38", "Location": "Montreal", "Tournament": "National Bank Open"}
    assert basis == "carried_tennis_data_identity_from_frozen_wta_crosswalk" and warning == ""
    event, basis, warning = bridge.wta_market_event_identity(match, {})
    assert event == {"WTA": "", "Location": "Montreal", "Tournament": "Montreal"}
    assert basis == "archive_event_name_no_frozen_crosswalk_identity"
    assert warning == "no_frozen_wta_crosswalk_edition_for_this_event_code"


def test_tennis_data_cover_index() -> None:
    rows = [
        {
            "Tournament": "US Open",
            "Location": "New York",
            "Round": "1st Round",
            "market_date": dt.date(2026, 8, 31),
        },
        {
            "Tournament": "US Open",
            "Location": "New York",
            "Round": "2nd Round",
            "market_date": None,
        },
    ]
    index = bridge.tennis_data_cover_index(rows, Join())
    assert index == {"usopen": [(dt.date(2026, 8, 31), "1st Round"), (None, "2nd Round")]}
    by_location = bridge.tennis_data_cover_index(rows, Join(), by_location=True)
    assert by_location["location:newyork"] == index["usopen"]


def generated_match(**overrides: str) -> dict[str, str]:
    row = {
        "tourney_id": "2026-0421",
        "tourney_name": "Canada Masters",
        "round": "F",
        "draw_size": "96",
        "surface": "Hard",
        "best_of": "3",
        "winner_id": "1",
        "loser_id": "2",
        "score": "6-3 7-6(4)",
        "tourney_date": "20260803",
    }
    row.update(overrides)
    return row


ATP_COLUMNS = [
    "ATP",
    "Location",
    "Tournament",
    "Date",
    "Series",
    "Court",
    "Surface",
    "Round",
    "Best of",
    "Winner",
    "Loser",
    "Comment",
    "PSW",
    "PSL",
]
STYLES = {"1": {"market_style": "Sinner J."}, "2": {"market_style": "Alcaraz C."}}
CARRIED = {
    "0421": {
        "market_tournament": "National Bank Open",
        "market_location": "Toronto",
        "market_event_number": "54",
    }
}


def test_synthesize_market_rows_dates_every_row_at_the_event_end() -> None:
    final = generated_match()
    r64 = generated_match(round="R64", winner_id="2", loser_id="1", score="6-4 4-6 6-4 RET")
    rows, provenance, refused, report = bridge.synthesize_market_rows(
        [final, r64], 2026, ATP_COLUMNS, STYLES, {}, Join(), 2,
        event_names=CARRIED, covered={}, event_end_dates={"2026-0421": dt.date(2026, 8, 12)},
    )  # fmt: skip
    assert refused == []
    assert [row["Date"] for row in rows] == ["2026-08-12", "2026-08-12"]
    assert [row["market_date"] for row in rows] == [dt.date(2026, 8, 12)] * 2
    assert [row["Round"] for row in rows] == ["The Final", "2nd Round"]
    assert rows[0]["Comment"] == "Completed" and rows[1]["Comment"] == "Retired"
    assert rows[0]["Winner"] == "Sinner J." and rows[1]["Winner"] == "Alcaraz C."
    assert rows[0]["ATP"] == "54" and rows[0]["Series"] == "" and rows[0]["PSW"] == ""
    assert [row["market_source_row"] for row in rows] == [2, 3]
    assert {row["market_date_basis"] for row in provenance} == {"inferred_event_end"}
    assert {row["route"] for row in provenance} == {bridge.SYNTHESIZED_ROUTE}
    assert [row["market_date"] for row in provenance] == ["2026-08-12", "2026-08-12"]
    # The start-plus-round-order approximation survives only as provenance.
    assert [row["round_order"] for row in provenance] == [6, 1]
    assert report["synthesized_per_event"] == {"2026-0421|Canada Masters": 2}
    assert report["event_identity_basis"] == {
        "2026-0421|Canada Masters": "archive_event_name_exact_by_construction"
    }


def test_synthesize_market_rows_refusals_and_cover_skip() -> None:
    final = generated_match()
    rows, provenance, refused, report = bridge.synthesize_market_rows(
        [final], 2026, ATP_COLUMNS, STYLES, {}, Join(), 2, event_names=CARRIED, covered={}
    )
    assert rows == [] and provenance == []
    assert [row["reason"] for row in refused] == ["no_event_end_date"]
    assert refused[0]["detail"] == "tourney_id 2026-0421"
    assert report["refused_per_event"] == {"2026-0421|Canada Masters": 1}
    ends = {"2026-0421": dt.date(2026, 8, 12)}
    _, _, refused, _ = bridge.synthesize_market_rows(
        [generated_match(round="R8", draw_size="96")], 2026, ATP_COLUMNS, STYLES, {}, Join(), 2,
        event_names=CARRIED, covered={}, event_end_dates=ends,
    )  # fmt: skip
    assert [row["reason"] for row in refused] == ["no_market_round_string"]
    _, _, refused, _ = bridge.synthesize_market_rows(
        [generated_match(winner_id="9")], 2026, ATP_COLUMNS, STYLES, {}, Join(), 2,
        event_names=CARRIED, covered={}, event_end_dates=ends,
    )  # fmt: skip
    assert [row["reason"] for row in refused] == ["no_market_name_style_for_player"]
    # A round the retained workbook already carries, under the carried tennis-data
    # name and inside the -2..+21 day window of the event start, gets no row.
    covered = {"nationalbankopen": [(dt.date(2026, 8, 10), "The Final")]}
    rows, _, refused, report = bridge.synthesize_market_rows(
        [final], 2026, ATP_COLUMNS, STYLES, {}, Join(), 2,
        event_names=CARRIED, covered=covered, event_end_dates=ends,
    )  # fmt: skip
    assert rows == [] and refused == []
    assert report["skipped_tennis_data_covered_per_event"] == {"2026-0421|Canada Masters": 1}
    # Outside the window it is a different edition and the row is synthesized.
    covered = {"nationalbankopen": [(dt.date(2026, 9, 10), "The Final")]}
    rows, _, _, _ = bridge.synthesize_market_rows(
        [final], 2026, ATP_COLUMNS, STYLES, {}, Join(), 2,
        event_names=CARRIED, covered=covered, event_end_dates=ends,
    )  # fmt: skip
    assert len(rows) == 1


def test_synthesize_market_rows_wta_branch() -> None:
    columns = [
        "WTA",
        "Location",
        "Tournament",
        "Date",
        "Tier",
        "Court",
        "Surface",
        "Round",
        "Best of",
        "Winner",
        "Loser",
        "Comment",
    ]
    carried = {
        "0421": {
            "market_tournament": "National Bank Open",
            "market_location": "Montreal",
            "market_event_number": "38",
        }
    }
    match = generated_match(tourney_name="Montreal", draw_size="64", round="R32")
    rows, provenance, refused, _ = bridge.synthesize_market_rows(
        [match], 2026, columns, STYLES, {}, bridge._WtaJoinShim(), 5,
        event_names=carried, covered={}, tour="WTA", event_end_dates={"2026-0421": dt.date(2026, 8, 10)},
    )  # fmt: skip
    assert refused == []
    assert rows[0]["WTA"] == "38" and rows[0]["Tier"] == "" and "ATP" not in rows[0]
    assert rows[0]["Location"] == "Montreal" and rows[0]["Tournament"] == "National Bank Open"
    assert rows[0]["Round"] == "2nd Round" and rows[0]["Date"] == "2026-08-10"
    assert provenance[0]["market_date_basis"] == "inferred_event_end"
    # A sponsor rename: the workbook carries the round under another name but the
    # same location, and the location key suppresses the duplicate.
    covered = {"location:montreal": [(dt.date(2026, 8, 3), "2nd Round")]}
    rows, _, _, report = bridge.synthesize_market_rows(
        [match], 2026, columns, STYLES, {}, bridge._WtaJoinShim(), 5,
        event_names=carried, covered=covered, tour="WTA", event_end_dates={"2026-0421": dt.date(2026, 8, 10)},
    )  # fmt: skip
    assert rows == [] and sum(report["skipped_tennis_data_covered_per_event"].values()) == 1


def test_merge_annual_keeps_mirror_rows_and_drops_duplicates() -> None:
    mirror_rows = [sackmann_row()]
    duplicate = sackmann_row(match_num="7", score="6-3 6-4")
    changed = sackmann_row(match_num="8", winner_id="101", loser_id="100", score="7-5 7-5")
    fresh = sackmann_row(match_num="9", winner_id="102", loser_id="103")
    fresh_again = sackmann_row(match_num="10", winner_id="103", loser_id="102")
    kept, dropped = bridge.merge_annual(mirror_rows, [duplicate, changed, fresh, fresh_again], 2024)
    assert [row["match_num"] for row in kept] == ["1", "9"]
    assert [row["dedupe_key"] for row in dropped] == [
        "0421|R16|100|101",
        "0421|R16|100|101",
        "0421|R16|102|103",
    ]
    assert [row["keys_identical"] for row in dropped] == [True, False, False]
    assert dropped[1]["generated_winner_id"] == "101" and dropped[1]["mirror_winner_id"] == "100"
    assert set(dropped[0]) == set(bridge.DUPLICATE_FIELDS)


def test_write_annual_csv_uses_the_mirror_line_terminator(tmp_path: Path) -> None:
    path = tmp_path / "atp_matches_2024.csv"
    bridge.write_annual_csv(path, [sackmann_row(), {"tourney_id": "x", "minutes": None}])
    payload = path.read_bytes()
    assert b"\r\n" not in payload
    lines = payload.decode("utf-8").split("\n")
    assert lines[0] == ",".join(bridge.SACKMANN_FIELDS)
    assert lines[2].startswith("x,,,")
    assert len(lines) == 4 and lines[3] == ""


# ------------------------------------------------------- archive-reading paths


def test_read_mirror_annual_and_event_index(archive: Path) -> None:
    payload, header, rows = bridge.read_mirror_annual(
        archive, mirror.ARCHIVE_ROOT, "ATP", 2024, allow_reserved=False
    )
    assert header == bridge.SACKMANN_FIELDS and len(rows) == 1
    assert payload.startswith(b"tourney_id,")
    index = bridge.event_index(
        archive, mirror.ARCHIVE_ROOT, "ATP", [2023, 2024], allow_reserved=False
    )
    ed = index["0421"]
    assert ed is index["name:canada masters"]
    assert ed["season"] == 2024 and ed["tourney_id"] == "2024-0421"
    assert ed["rounds"] == {"R16": 1} and ed["ordered_rounds"] == ["R16"]
    assert ed["best_of"] == "3" and ed["max_match_num"] == 1 and ed["draw_size"] == "16"
    with pytest.raises(ChainError, match="reserved"):
        bridge.event_index(archive, mirror.ARCHIVE_ROOT, "ATP", [2025], allow_reserved=False)


def test_resolver_applies_the_confidence_policy() -> None:
    class Walk:
        calls = 0

        def lookup(self, name: str) -> dict[str, Any]:
            Walk.calls += 1
            if name == "Low Guy":
                return {
                    "matched": True,
                    "confidence": "low",
                    "match_method": "surname_unique",
                    "player_id": "7",
                }
            return {
                "matched": True,
                "confidence": "high",
                "match_method": "exact_full",
                "player_id": "1",
            }

    resolver = bridge.Resolver({"ATP": Walk()})
    low = resolver.resolve("atp", " Low Guy ")
    assert low["matched"] is False
    assert low["reason"] == "below_accepted_confidence_surname_unique"
    assert low["candidate_ids"] == "7"
    assert resolver.resolve("ATP", "Low Guy") is low and Walk.calls == 1
    assert resolver.resolve("ATP", "Top Guy")["matched"] is True
    with pytest.raises(ChainError, match="no crosswalk built"):
        resolver.resolve("WTA", "Anyone")


def test_generate_from_wikipedia_over_the_fixture(archive: Path) -> None:
    index = bridge.event_index(
        archive, mirror.ARCHIVE_ROOT, "ATP", [2023, 2024], allow_reserved=False
    )
    resolver = bridge.Resolver({"ATP": crosswalk_v2.build(archive, "ATP")})
    generated, rejected, unmapped, resolutions = bridge.generate_from_wikipedia(
        WIKI_ROWS, 2024, index, resolver
    )
    assert unmapped == []
    assert [row["source_name"] for row in rejected] == ["Nobody Known"]
    assert rejected[0]["reason"] == "no_candidate_full_file" and rejected[0]["side"] == "winner"
    assert [(r["winner_id"], r["loser_id"], r["match_num"], r["score"]) for r in generated] == [
        ("102", "103", "2", "7-6(5) RET"),
        ("100", "101", "3", "6-3 6-4"),
    ]
    row = generated[0]
    assert row["tourney_id"] == "2024-0421" and row["tourney_name"] == "Canada Masters"
    assert row["round"] == "R16" and row["tourney_date"] == "20240805"
    assert row["surface"] == "Hard" and row["best_of"] == "3" and row["draw_size"] == "16"
    assert row["winner_name"] == "Alex Michelsen"
    assert all(row[field] == "" for field in bridge.BLANK_ON_GENERATED)
    record = resolutions["ATP|National_Bank_Open"]
    assert record["resolved_via"] == "alias:Canada Masters"
    assert record["generated_tourney_id"] == "2024-0421"
    assert record["tournament_start_date"] == "2024-08-05"
    assert record["tournament_end_date"] == "2024-08-12"
    assert record["event_end_basis"] == bridge.FALLBACK_END_BASIS
    assert record["rounds_generated"] == ["R16"] and record["rounds_pending"] == ["QF", "SF", "F"]
    assert record["week_starts_in_cell"] == 1 and record["matches"] == 3
    # The overlap rule: the mirror row wins and the regenerated copy is dropped.
    merged, dropped = bridge.merge_annual(MIRROR_2024, generated, 2024)
    assert [row["match_num"] for row in merged] == ["1", "2"]
    assert [row["keys_identical"] for row in dropped] == [True]


def test_generate_from_wikipedia_quarantines_per_draw(archive: Path) -> None:
    index = bridge.event_index(
        archive, mirror.ARCHIVE_ROOT, "ATP", [2023, 2024], allow_reserved=False
    )
    resolver = bridge.Resolver({"ATP": crosswalk_v2.build(archive, "ATP")})
    rows = [
        wiki_row(tournament="Nowhere_Open"),
        wiki_row(week_label="sometime"),
        wiki_row(tournament="Canada_Masters", round="Playoff"),
        wiki_row(tournament="Canada Masters", round="R1"),
        wiki_row(tournament="Canada Masters", round="QF"),
    ]
    generated, _rejected, unmapped, resolutions = bridge.generate_from_wikipedia(
        rows, 2024, index, resolver
    )
    assert generated == [] and resolutions == {}
    assert {(row["tournament"], row["reason"]) for row in unmapped} == {
        ("Nowhere_Open", "no_mirror_edition_for_event"),
        ("National_Bank_Open", "week_label_unparseable"),
        ("Canada_Masters", "unknown_round_label"),
        ("Canada Masters", "round_structure_mismatch"),
    }
    assert set(unmapped[0]) == set(bridge.UNMAPPED_EVENT_FIELDS)


def test_compose_tar_routes_members_and_is_reproducible(workspace: Path, archive: Path) -> None:
    replacement = b"tourney_id\n2024-0421\n"
    first = bridge.compose_tar(
        archive, mirror.ARCHIVE_ROOT, "ATP", [2023, 2024], {2024: replacement},
        workspace / "out" / "atp_panel_source.tar.gz", allow_reserved=False,
    )  # fmt: skip
    assert first["path"] == "out/atp_panel_source.tar.gz"
    assert [(m["member"].rsplit("/", 1)[1], m["route"]) for m in first["members"]] == [
        ("atp_players.csv", "mirror_bytes_unchanged"),
        ("atp_matches_2023.csv", "mirror_bytes_unchanged"),
        ("atp_matches_2024.csv", "bridge_extended"),
    ]
    assert first["members"][2]["sha256"] == bridge.sha256_bytes(replacement)
    with tarfile.open(archive, "r:gz") as source:
        original = source.extractfile(first["members"][1]["member"]).read()
    assert first["members"][1]["sha256"] == bridge.sha256_bytes(original)
    composed = (workspace / "out" / "atp_panel_source.tar.gz").read_bytes()
    assert composed[4:8] == b"\x00\x00\x00\x00"  # gzip header mtime
    assert composed[10:31] == b"atp_panel_source.tar\x00"
    with tarfile.open(workspace / "out" / "atp_panel_source.tar.gz", "r:gz") as tar:
        infos = tar.getmembers()
        assert [i.name.rsplit("/", 1)[1] for i in infos] == [
            "atp_players.csv", "atp_matches_2023.csv", "atp_matches_2024.csv",
        ]  # fmt: skip
        assert all(
            (i.mtime, i.uid, i.gid, i.uname, i.gname, i.mode) == (0, 0, 0, "", "", 0o644)
            for i in infos
        )
        assert tar.extractfile(infos[2]).read() == replacement
    second = bridge.compose_tar(
        archive, mirror.ARCHIVE_ROOT, "ATP", [2023, 2024], {2024: replacement},
        workspace / "again" / "atp_panel_source.tar.gz", allow_reserved=False,
    )  # fmt: skip
    assert (
        second["sha256"] == first["sha256"] == sha256(workspace / "out" / "atp_panel_source.tar.gz")
    )
    assert gzip.decompress(composed) == gzip.decompress(
        (workspace / "again" / "atp_panel_source.tar.gz").read_bytes()
    )
    with pytest.raises(ChainError, match="reserved"):
        bridge.compose_tar(
            archive, mirror.ARCHIVE_ROOT, "ATP", [2024, 2025], {},
            workspace / "no" / "atp_panel_source.tar.gz", allow_reserved=False,
        )  # fmt: skip


def test_read_wikipedia_requires_the_draw_columns(workspace: Path) -> None:
    path = workspace / "draw.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(WIKI_ROWS[0]))
        writer.writeheader()
        writer.writerows(WIKI_ROWS)
    rows = bridge.read_wikipedia([path])
    assert len(rows) == 3 and rows[0]["_source_path"] == str(path)
    (workspace / "bad.csv").write_text("tour,tournament\nATP,x\n", encoding="utf-8")
    with pytest.raises(ChainError, match="lacks Wikipedia draw columns"):
        bridge.read_wikipedia([workspace / "bad.csv"])


def test_read_tennis_data_csv_route_drops_provenance_columns(workspace: Path) -> None:
    path = workspace / "window.csv"
    path.write_text(
        "ATP,Location,Tournament,Date,Round,Winner,Loser,source,source_url,retrieved_at_utc,archive_capture\n"
        "54,Toronto,National Bank Open,2026-08-03,1st Round,Sinner J.,Alcaraz C.,tennis-data,http://x,2026-09-01T00:00:00Z,\n"
        "54,Toronto,National Bank Open,,2nd Round,Sinner J.,Alcaraz C.,tennis-data,http://x,2026-09-01T00:00:00Z,\n",
        encoding="utf-8",
    )
    columns, rows = bridge.read_tennis_data(path, 2026)
    assert columns == ["ATP", "Location", "Tournament", "Date", "Round", "Winner", "Loser"]
    assert rows[0]["market_date"] == dt.date(2026, 8, 3) and rows[1]["market_date"] is None
    assert rows[0]["market_source_row"] == 2 and rows[0]["market_source_path"] == "window.csv"
    assert rows[0]["_source_url"] == "http://x" and "source_url" not in rows[0]
    assert bridge._parse_market_date("03/08/2026") == dt.date(2026, 8, 3)
    assert bridge._parse_market_date("2026-08-03 00:00:00") == dt.date(2026, 8, 3)
    with pytest.raises(ChainError, match="cannot parse market date"):
        bridge._parse_market_date("August")


def test_read_wta_workbook_and_reproducible_writer(workspace: Path) -> None:
    columns = ["WTA", "Location", "Tournament", "Date", "Tier", "Round", "Winner", "Loser"]
    source = openpyxl.Workbook()
    sheet = source.active
    sheet.append(columns)
    sheet.append(
        [
            1,
            "Auckland",
            "ASB Classic",
            dt.datetime(2026, 1, 5),
            "WTA250",
            "1st Round",
            "A B.",
            "C D.",
        ]
    )
    sheet.append([None, "", None, None, None, None, None, None])
    sheet.append(
        [1, "Auckland", "ASB Classic", "06/01/2026", "WTA250", "2nd Round", "A B.", "E F."]
    )
    source.save(workspace / "wta.xlsx")
    header, rows = bridge.read_wta_workbook(workspace / "wta.xlsx", 2026)
    assert header == columns
    assert [row["market_source_row"] for row in rows] == [2, 4]
    assert rows[0]["market_date"] == dt.date(2026, 1, 5) and rows[1]["market_date"] == dt.date(
        2026, 1, 6
    )
    assert rows[0]["market_source_path"] == "wta.xlsx" and rows[0]["WTA"] == 1
    assert bridge.wta_norm_name("Libéma Open & Co.") == "libema open and co"
    synthesized = {
        **dict.fromkeys(columns, ""),
        "Tournament": "ASB Classic",
        "Date": "2026-01-12",
        "market_date": dt.date(2026, 1, 12),
    }
    first = bridge.write_market_workbook(workspace / "one.xlsx", columns, [*rows, synthesized])
    second = bridge.write_market_workbook(workspace / "two.xlsx", columns, [*rows, synthesized])
    assert first == second
    header, again = bridge.read_wta_workbook(workspace / "one.xlsx", 2026)
    assert header == columns and len(again) == 3
    assert again[2]["market_date"] == dt.date(2026, 1, 12)
    assert isinstance(again[2]["Date"], dt.datetime)


YEAR_PLAN = {
    "calibration_years_back": 3,
    "feature_end_year": 2024,
    "history_floor_year": 2011,
    "panel_end_year": 2024,
    "target_years": [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
    "training_window_years": 5,
}


def bridge_config(workspace: Path, archive: Path, **bridge_overrides: Any) -> Path:
    (workspace / "wiki").mkdir()
    with (workspace / "wiki" / "atp_National_Bank_Open.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(WIKI_ROWS[0]))
        writer.writeheader()
        writer.writerows(WIKI_ROWS)
    acquisition = workspace / "work" / "MULTI01_market_acquisition"
    acquisition.mkdir(parents=True)
    (acquisition / "headers_by_year.json").write_text(
        json.dumps({"2024": ATP_COLUMNS}), encoding="utf-8"
    )
    (acquisition / "acquisition_manifest.json").write_text(
        json.dumps({"records": [{"year": 2023, "retained_path": "raw/annual/2023.xlsx"}]}),
        encoding="utf-8",
    )
    crosswalk = workspace / "work" / "MULTI01_event_crosswalk"
    crosswalk.mkdir(parents=True)
    (crosswalk / "qualified_event_crosswalk.csv").write_text(
        "season,archive_tourney_id,market_tournament,market_location,market_event_numbers\n"
        "2024,2024-0421,National Bank Open,Montreal,54\n",
        encoding="utf-8",
    )
    document = {
        "bridge": {
            "archive": {
                "path": "mirror.tar.gz",
                "sha256": sha256(archive),
                "tar_root": mirror.ARCHIVE_ROOT,
            },
            "carry_forward_years": [2023, 2024],
            "output_dir": "work/run/inputs",
            "panel_start_year": 2023,
            "reserved_release_acknowledged": False,
            "seasons": [2024],
            "sources": {"2024": {"wikipedia": ["wiki/atp_National_Bank_Open.csv"]}},
            "tour": "ATP",
            "unresolved_event_policy": "quarantine",
            **bridge_overrides,
        },
        "year_plan": YEAR_PLAN,
    }
    path = workspace / "bridge.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def test_build_end_to_end_on_the_fixture(
    workspace: Path, archive: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = bridge_config(workspace, archive)
    assert bridge.main(["--config", str(config), "--allow-reserved-years"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["seasons"] == [2024]
    assert printed["composed_archive"] == "work/run/inputs/archive/atp_panel_source.tar.gz"
    assert printed["quarantine_counts"] == {
        "distinct_unmatched_player_names": 1,
        "dropped_duplicates": 1,
        "dropped_duplicates_with_identical_keys": 1,
        "unmapped_event_or_row_entries": 0,
        "unmapped_reasons": {},
        "unmatched_player_name_rows": 1,
    }
    out = workspace / "work" / "run" / "inputs"
    summary = json.loads((out / "bridge_summary.json").read_text(encoding="utf-8"))
    assert summary["id"] == "CONFIRM2026-res2026-bridge" and summary["tour"] == "ATP"
    assert summary["code"]["bridge"]["module"] == "tennislab.sources.bridge"
    assert summary["code"]["crosswalk_v2"]["module"] == "tennislab.panel.crosswalk_v2"
    assert summary["code"]["join_candidates"]["module"] == "tennislab.panel.join"
    assert summary["code"]["wta_sources"] is None
    assert summary["market_event_names"]["path"] == "tennislab/sources/market_event_names.json"
    assert summary["res2026_event_resolution"]["status"] == "PASS_WITH_UNRESOLVED_QUARANTINED"
    season = summary["seasons_detail"]["2024"]
    assert season["mirror_rows"] == 1 and season["generated_sackmann_rows"] == 2
    assert season["rows_added_after_dedupe"] == 1 and season["duplicates_dropped"] == 1
    assert season["market_rows_passthrough"] == 0 and season["market_rows_synthesized"] == 1
    assert season["market_workbook"]["path"] == "work/run/inputs/market/2024.xlsx"
    assert (
        season["market_workbook"]["route"]
        == "res2026_bridge_merge_tennis_data_plus_synthesized_wikipedia_rows"
    )
    assert season["annual_output"] == {
        "path": "work/run/inputs/sackmann/atp_matches_2024.csv",
        "sha256": sha256(out / "sackmann" / "atp_matches_2024.csv"),
        "rows": 2,
    }
    assert season["draws_with_rounds_pending"] == {"ATP|National_Bank_Open": ["QF", "SF", "F"]}
    assert summary["draw_structure"]["draws_generated"] == 1
    assert summary["composed_archive"]["sha256"] == sha256(
        out / "archive" / "atp_panel_source.tar.gz"
    )
    routes = [m["route"] for m in summary["composed_archive"]["members"]]
    assert routes == ["mirror_bytes_unchanged", "mirror_bytes_unchanged", "bridge_extended"]
    for name, digest in summary["outputs"].items():
        assert sha256(out / name) == digest
    provenance = list(
        csv.DictReader(
            (out / "market" / "market_row_provenance.csv").open(newline="", encoding="utf-8")
        )
    )
    assert list(provenance[0]) == list(bridge.MARKET_PROVENANCE_FIELDS)
    assert [
        (r["route"], r["market_date_basis"], r["market_date"], r["round_order"]) for r in provenance
    ] == [(bridge.SYNTHESIZED_ROUTE, "inferred_event_end", "2024-08-12", "0")]
    assert provenance[0]["winner_id"] == "102" and provenance[0]["market_source_row"] == "2"
    manifest = json.loads(
        (out / "market" / "acquisition_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["bridge_records"] == [2024]
    assert manifest["scope"].startswith("ATP annual Tennis-Data files 2023-2024")
    record = manifest["records"][-1]
    assert record["retained_path"] == "../run/inputs/market/2024.xlsx"
    assert record["retained_sha256"] == sha256(out / "market" / "2024.xlsx")
    unmatched = list(
        csv.DictReader(
            (out / "quarantine" / "unmatched_players.csv").open(newline="", encoding="utf-8")
        )
    )
    assert [(r["source_name"], r["reason"]) for r in unmatched] == [
        ("Nobody Known", "no_candidate_full_file")
    ]
    annual = (out / "sackmann" / "atp_matches_2024.csv").read_bytes()
    assert annual.count(b"\n") == 3 and b"\r\n" not in annual
    # A second build reproduces every output byte, the workbook and tarball included.
    digests = {name: sha256(out / name) for name in summary["outputs"]}
    workbook, composed = sha256(out / "market" / "2024.xlsx"), summary["composed_archive"]["sha256"]
    bridge.build(config, allow_reserved=True)
    assert {name: sha256(out / name) for name in summary["outputs"]} == digests
    assert sha256(out / "market" / "2024.xlsx") == workbook
    assert sha256(out / "archive" / "atp_panel_source.tar.gz") == composed


def test_build_refuses_reserved_seasons_without_acknowledgement(
    workspace: Path, archive: Path
) -> None:
    config = bridge_config(workspace, archive, seasons=[2025])
    with pytest.raises(ChainError, match="reserved window"):
        bridge.build(config, allow_reserved=True)
    with pytest.raises(ChainError, match="reserved window"):
        bridge.build(config, allow_reserved=False)
    (workspace / "empty.json").write_text(json.dumps({"year_plan": YEAR_PLAN}), encoding="utf-8")
    with pytest.raises(ChainError, match="configuration has no bridge object"):
        bridge.build(workspace / "empty.json", allow_reserved=False)


def test_main_dry_run_and_event_self_check(
    workspace: Path, archive: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = bridge_config(workspace, archive)
    assert bridge.main(["--config", str(config), "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "dry_run_ok" and printed["seasons"] == [2024]
    assert (
        bridge.main(
            ["--config", str(config), "--event-self-check", "--report", str(workspace / "r.json")]
        )
        == 0
    )
    report = json.loads((workspace / "r.json").read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out) == report
    assert report["status"] == "PASS_WITH_UNRESOLVED_QUARANTINED"
    resolved = [row for row in report["resolutions"] if row["resolved"]]
    assert [(row["res2026_event_name"], row["resolved_via"]) for row in resolved] == [
        ("National Bank Open", "alias:Canada Masters"),
        ("National Bank Open", "alias:Canada Masters"),
    ]
    assert (
        bridge.main(
            [
                "--config",
                str(config),
                "--generate-preview-season",
                "2024",
                "--wikipedia",
                "wiki/atp_National_Bank_Open.csv",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    assert preview["generated_rows_before_dedupe"] == 2 and preview["unmatched_player_rows"] == 1
    assert preview["generated_per_draw"]["2024-0421"]["rows"] == 2
    assert preview["generated_per_draw"]["2024-0421"]["match_num_span"] == [2, 3]
    assert (
        preview["event_resolutions"]["ATP|National_Bank_Open"]["tournament_end_date"]
        == "2024-08-12"
    )
