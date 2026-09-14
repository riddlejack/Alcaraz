"""Exact-ID lookup against globally selected ranking editions.

Ported from the archive's ``work/MULTI01_ranking_lookup/ranking_lookup.py`` (which the
archive imported as the package ``MULTI01_ranking_lookup`` after putting ``work/`` on
``sys.path``; ``references/MULTI01_inputs/MULTI01_ranking_lookup/ranking_lookup.py`` is a
byte-identical tracked copy). Row validation, the D-2 cutoff, the global-edition
selection, the duplicate policy and the 14-day staleness flag are unchanged.

What changed in the port: the module no longer computes ``DEFAULT_SOURCE`` and
``DEFAULT_EDITION_INDEX`` from its own file location, so :meth:`RankingLookup.from_gzip`
takes both paths from its caller; failures are :class:`~tennislab.chain.common.ChainError`.
"""

from __future__ import annotations

import bisect
import csv
import datetime as dt
import gzip
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from tennislab.chain.common import ChainError, sha256

EXPECTED_HEADER = [
    "effective_date",
    "rank",
    "player_id",
    "ranking_points",
    "source_member",
    "source_physical_line",
]
CUTOFF_LAG_DAYS = 2
STALE_THRESHOLD_DAYS = 14


def _date(value: dt.date | str) -> dt.date:
    if isinstance(value, dt.datetime):
        raise ChainError("target_date must be a date without a time")
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(value)


def _positive_int(value: int | str, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ChainError(f"{field} must be a positive integer: {value!r}") from exc
    if parsed <= 0:
        raise ChainError(f"{field} must be a positive integer: {value!r}")
    return parsed


def _nonnegative_int_or_none(value: str, field: str) -> int | None:
    if value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ChainError(f"{field} must be blank or a nonnegative integer: {value!r}") from exc
    if parsed < 0:
        raise ChainError(f"{field} must be blank or a nonnegative integer: {value!r}")
    return parsed


@dataclass(frozen=True)
class LookupRequest:
    target_date: dt.date | str
    player_id: int | str


@dataclass(frozen=True)
class SourceLocator:
    source_member: str
    source_physical_line: int


@dataclass(frozen=True)
class CandidateRow:
    raw_rank: str
    raw_ranking_points: str
    source_locator: SourceLocator


@dataclass(frozen=True)
class RankingResult:
    target_date: dt.date
    cutoff_date: dt.date
    player_id: int
    snapshot_date: dt.date | None
    snapshot_age_days: int | None
    stale_over_14_days: bool
    snapshot_missing: bool
    player_missing_on_snapshot: bool
    unknown_player_id: bool
    ambiguous_duplicate: bool
    duplicate_status: str
    rank_missing: bool
    points_missing: bool
    rank: int | None
    ranking_points: int | None
    raw_rank: str | None
    raw_ranking_points: str | None
    missing_reason: str | None
    source_locators: tuple[SourceLocator, ...]
    candidate_rows: tuple[CandidateRow, ...]

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["target_date"] = self.target_date.isoformat()
        value["cutoff_date"] = self.cutoff_date.isoformat()
        value["snapshot_date"] = self.snapshot_date.isoformat() if self.snapshot_date else None
        return value


class RankingLookup:
    """Select a global edition, then find an exact player ID only within it.

    Use ``lookup_many`` for panel construction: the gzip source is streamed once
    for all requested edition/player keys. ``lookup`` is a convenience method and
    scans the source for its one request.
    """

    def __init__(
        self,
        *,
        edition_dates: Sequence[dt.date],
        known_player_ids: Iterable[int],
        source_path: Path | None = None,
        fixture_rows: Sequence[Mapping[str, str]] | None = None,
        source_sha256: str | None = None,
    ) -> None:
        dates = tuple(sorted(set(edition_dates)))
        if not dates:
            raise ChainError("ranking source contains no global editions")
        if (source_path is None) == (fixture_rows is None):
            raise ChainError("provide exactly one of source_path or fixture_rows")
        self.edition_dates = dates
        self.known_player_ids = frozenset(known_player_ids)
        self.source_path = source_path
        self._fixture_rows = (
            tuple(dict(row) for row in fixture_rows) if fixture_rows is not None else None
        )
        self.source_sha256 = source_sha256

    @classmethod
    def from_gzip(
        cls,
        source_path: str | Path,
        *,
        edition_index_path: str | Path,
        expected_source_sha256: str | None = None,
    ) -> RankingLookup:
        source = Path(source_path)
        actual_sha = sha256(source)
        if expected_source_sha256 is not None and actual_sha != expected_source_sha256:
            raise ChainError(f"ranking source SHA-256 mismatch: {actual_sha}")
        index = json.loads(Path(edition_index_path).read_text(encoding="utf-8"))
        if index["source_sha256"] != actual_sha:
            raise ChainError("edition index is not bound to the supplied ranking source")
        dates = [dt.date.fromisoformat(row["effective_date"]) for row in index["editions"]]
        return cls(
            edition_dates=dates,
            known_player_ids=[int(value) for value in index["known_player_ids"]],
            source_path=source,
            source_sha256=actual_sha,
        )

    @classmethod
    def from_rows(cls, rows: Sequence[Mapping[str, str]]) -> RankingLookup:
        copied = tuple(dict(row) for row in rows)
        for row in copied:
            validate_row(row)
        dates = [dt.date.fromisoformat(row["effective_date"]) for row in copied]
        player_ids = [int(row["player_id"]) for row in copied]
        return cls(edition_dates=dates, known_player_ids=player_ids, fixture_rows=copied)

    def selected_snapshot_date(self, target_date: dt.date | str) -> dt.date | None:
        target = _date(target_date)
        cutoff = target - dt.timedelta(days=CUTOFF_LAG_DAYS)
        position = bisect.bisect_right(self.edition_dates, cutoff)
        return self.edition_dates[position - 1] if position else None

    def _iter_rows(self) -> Iterator[Mapping[str, str]]:
        if self._fixture_rows is not None:
            yield from self._fixture_rows
            return
        assert self.source_path is not None
        with gzip.open(
            self.source_path, "rt", encoding="utf-8-sig", errors="strict", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != EXPECTED_HEADER:
                raise ChainError(f"unexpected ranking header: {reader.fieldnames}")
            yield from reader

    def lookup(self, target_date: dt.date | str, player_id: int | str) -> RankingResult:
        return self.lookup_many([LookupRequest(target_date, player_id)])[0]

    def lookup_many(
        self, requests: Iterable[LookupRequest | tuple[dt.date | str, int | str]]
    ) -> list[RankingResult]:
        normalized: list[tuple[dt.date, int, dt.date, dt.date | None]] = []
        requested_keys: set[tuple[dt.date, int]] = set()
        for request in requests:
            if isinstance(request, LookupRequest):
                target_raw, player_raw = request.target_date, request.player_id
            else:
                target_raw, player_raw = request
            target = _date(target_raw)
            player_id = _positive_int(player_raw, "player_id")
            cutoff = target - dt.timedelta(days=CUTOFF_LAG_DAYS)
            snapshot = self.selected_snapshot_date(target)
            normalized.append((target, player_id, cutoff, snapshot))
            if snapshot is not None:
                requested_keys.add((snapshot, player_id))

        found: dict[tuple[dt.date, int], list[CandidateRow]] = {key: [] for key in requested_keys}
        if requested_keys:
            requested_date_texts = {key[0].isoformat() for key in requested_keys}
            for row in self._iter_rows():
                row_date_text = row["effective_date"]
                if row_date_text not in requested_date_texts:
                    continue
                validate_row(row)
                row_date = dt.date.fromisoformat(row_date_text)
                player_id = int(row["player_id"])
                key = (row_date, player_id)
                if key in found:
                    found[key].append(
                        CandidateRow(
                            raw_rank=row["rank"],
                            raw_ranking_points=row["ranking_points"],
                            source_locator=SourceLocator(
                                source_member=row["source_member"],
                                source_physical_line=int(row["source_physical_line"]),
                            ),
                        )
                    )

        return [
            self._resolve(
                target, player, cutoff, snapshot, player not in self.known_player_ids, found
            )
            for target, player, cutoff, snapshot in normalized
        ]

    @staticmethod
    def _resolve(
        target: dt.date,
        player_id: int,
        cutoff: dt.date,
        snapshot: dt.date | None,
        unknown_player_id: bool,
        found: Mapping[tuple[dt.date, int], list[CandidateRow]],
    ) -> RankingResult:
        if snapshot is None:
            return RankingResult(
                target, cutoff, player_id, None, None, False, True, False, unknown_player_id, False,
                "not_applicable", True, True, None, None, None, None,
                "no_global_edition_on_or_before_cutoff", (), (),
            )  # fmt: skip
        age = (target - snapshot).days
        candidates = tuple(found[(snapshot, player_id)])
        locators = tuple(row.source_locator for row in candidates)
        if not candidates:
            return RankingResult(
                target, cutoff, player_id, snapshot, age, age > STALE_THRESHOLD_DAYS,
                False, True, unknown_player_id, False, "none", True, True, None, None, None, None,
                "player_absent_on_selected_global_edition", (), (),
            )  # fmt: skip
        raw_values = {(row.raw_rank, row.raw_ranking_points) for row in candidates}
        if len(raw_values) > 1:
            return RankingResult(
                target, cutoff, player_id, snapshot, age, age > STALE_THRESHOLD_DAYS,
                False, False, False, True, "conflicting", True, True, None, None, None, None,
                "conflicting_duplicate_on_selected_global_edition", locators, candidates,
            )  # fmt: skip
        raw_rank, raw_points = next(iter(raw_values))
        rank = _positive_int(raw_rank, "rank")
        points = _nonnegative_int_or_none(raw_points, "ranking_points")
        duplicate_status = "byte_equivalent_collapsed" if len(candidates) > 1 else "none"
        return RankingResult(
            target, cutoff, player_id, snapshot, age, age > STALE_THRESHOLD_DAYS,
            False, False, False, False, duplicate_status, False, points is None,
            rank, points, raw_rank, raw_points, None, locators, candidates,
        )  # fmt: skip


def validate_row(row: Mapping[str, str]) -> None:
    missing = [field for field in EXPECTED_HEADER if field not in row]
    if missing:
        raise ChainError(f"ranking row missing fields: {missing}")
    dt.date.fromisoformat(row["effective_date"])
    _positive_int(row["rank"], "rank")
    _positive_int(row["player_id"], "player_id")
    _nonnegative_int_or_none(row["ranking_points"], "ranking_points")
    _positive_int(row["source_physical_line"], "source_physical_line")
    if not row["source_member"]:
        raise ChainError("source_member must be nonblank")
