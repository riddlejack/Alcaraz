"""Ported from the archive's ``MULTI01_ranking_lookup/test_ranking_lookup.py``.

The fixture tests are unchanged in substance. ``RealFreezeFixtureTest`` called
``RankingLookup.from_gzip()`` with defaults computed from the module's own location; the
ported module has no such defaults, so the test names the archive's pinned stream
explicitly and is skipped when the archive is not mounted.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from tennislab.chronology.ranking_lookup import LookupRequest, RankingLookup

QUALIFIED_SOURCE_SHA256 = "f4ce52888a6ff8889add3ef51e5ad8d6cd9cb8fe635f43c428a759e6a75ce866"
ARCHIVE_SOURCE = "work/MULTI01_rankings/rankings_2000_2024.csv.gz"
ARCHIVE_INDEX = "work/MULTI01_ranking_lookup/edition_index.json"


def row(date: str, rank: str, player: str, points: str, line: int) -> dict[str, str]:
    return {
        "effective_date": date,
        "rank": rank,
        "player_id": player,
        "ranking_points": points,
        "source_member": "fixture/rankings.csv",
        "source_physical_line": str(line),
    }


def test_exact_d_minus_two_boundary() -> None:
    lookup = RankingLookup.from_rows(
        [
            row("2024-01-01", "12", "100", "900", 2),
            row("2024-01-03", "10", "100", "1000", 3),
        ]
    )
    results = lookup.lookup_many(
        [LookupRequest("2024-01-05", 100), LookupRequest("2024-01-04", 100)]
    )
    assert results[0].cutoff_date == dt.date(2024, 1, 3)
    assert results[0].snapshot_date == dt.date(2024, 1, 3)
    assert results[0].rank == 10
    assert results[1].snapshot_date == dt.date(2024, 1, 1)
    assert results[1].rank == 12


def test_absent_on_newest_global_list_does_not_fall_back() -> None:
    lookup = RankingLookup.from_rows(
        [
            row("2024-01-01", "12", "100", "900", 2),
            row("2024-01-08", "5", "200", "1500", 3),
        ]
    )
    result = lookup.lookup("2024-01-10", 100)
    assert result.snapshot_date == dt.date(2024, 1, 8)
    assert result.player_missing_on_snapshot
    assert not result.unknown_player_id
    assert result.missing_reason == "player_absent_on_selected_global_edition"
    assert result.rank is None
    assert result.source_locators == ()


def test_byte_equivalent_and_conflicting_duplicates() -> None:
    lookup = RankingLookup.from_rows(
        [
            row("2024-01-08", "7", "100", "1200", 10),
            row("2024-01-08", "7", "100", "1200", 11),
            row("2024-01-08", "8", "200", "1100", 12),
            row("2024-01-08", "9", "200", "1050", 13),
        ]
    )
    exact, conflict = lookup.lookup_many([("2024-01-10", 100), ("2024-01-10", 200)])
    assert exact.duplicate_status == "byte_equivalent_collapsed"
    assert exact.rank == 7
    assert exact.ranking_points == 1200
    assert [x.source_physical_line for x in exact.source_locators] == [10, 11]
    assert not exact.ambiguous_duplicate

    assert conflict.duplicate_status == "conflicting"
    assert conflict.ambiguous_duplicate
    assert conflict.rank_missing
    assert conflict.points_missing
    assert conflict.rank is None
    assert conflict.raw_rank is None
    assert [(x.raw_rank, x.raw_ranking_points) for x in conflict.candidate_rows] == [
        ("8", "1100"),
        ("9", "1050"),
    ]


def test_rank_remains_available_when_points_are_blank() -> None:
    lookup = RankingLookup.from_rows([row("2024-01-08", "3", "100", "", 2)])
    result = lookup.lookup("2024-01-10", 100)
    assert result.rank == 3
    assert result.raw_rank == "3"
    assert result.ranking_points is None
    assert result.raw_ranking_points == ""
    assert not result.rank_missing
    assert result.points_missing


def test_unknown_id_and_no_prior_global_edition_are_distinct() -> None:
    lookup = RankingLookup.from_rows([row("2024-01-08", "3", "100", "1000", 2)])
    unknown = lookup.lookup("2024-01-10", 999)
    assert not unknown.snapshot_missing
    assert unknown.player_missing_on_snapshot
    assert unknown.unknown_player_id
    before_source = lookup.lookup("2024-01-09", 100)
    assert before_source.snapshot_missing
    assert not before_source.player_missing_on_snapshot
    assert before_source.missing_reason == "no_global_edition_on_or_before_cutoff"


def test_future_append_invariance() -> None:
    base = [
        row("2024-01-01", "12", "100", "900", 2),
        row("2024-01-08", "10", "100", "1000", 3),
    ]
    future = [*base, row("2030-01-01", "1", "100", "9999", 4)]
    assert RankingLookup.from_rows(base).lookup("2024-01-10", 100) == (
        RankingLookup.from_rows(future).lookup("2024-01-10", 100)
    )


def _archive_stream() -> tuple[Path, Path] | None:
    root = os.environ.get("TENNISLAB_ARCHIVE")
    if not root:
        return None
    source, index = Path(root) / ARCHIVE_SOURCE, Path(root) / ARCHIVE_INDEX
    return (source, index) if source.is_file() and index.is_file() else None


@pytest.mark.skipif(_archive_stream() is None, reason="research archive not mounted")
def test_real_freeze_and_duplicate_examples() -> None:
    paths = _archive_stream()
    assert paths is not None
    source, index = paths
    lookup = RankingLookup.from_gzip(
        source,
        edition_index_path=index,
        expected_source_sha256=QUALIFIED_SOURCE_SHA256,
    )
    freeze, exact, conflict = lookup.lookup_many(
        [("2020-08-23", 104925), ("2021-07-21", 126193), ("2011-07-27", 106223)]
    )
    assert freeze.cutoff_date == dt.date(2020, 8, 21)
    assert freeze.snapshot_date == dt.date(2020, 3, 16)
    assert freeze.snapshot_age_days == 160
    assert freeze.stale_over_14_days
    assert freeze.rank == 1
    assert freeze.ranking_points == 10220
    assert freeze.source_locators[0].source_member == "atp/atp_rankings_20s.csv"
    assert freeze.source_locators[0].source_physical_line == 17403

    assert exact.snapshot_date == dt.date(2021, 7, 19)
    assert exact.duplicate_status == "byte_equivalent_collapsed"
    assert exact.rank == 701
    assert exact.ranking_points == 33
    assert [x.source_physical_line for x in exact.source_locators] == [104415, 104515]

    assert conflict.snapshot_date == dt.date(2011, 7, 25)
    assert conflict.ambiguous_duplicate
    assert conflict.rank is None
    assert [(x.raw_rank, x.raw_ranking_points) for x in conflict.candidate_rows] == [
        ("1489", "1"),
        ("1596", "1"),
    ]
