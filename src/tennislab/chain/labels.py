"""The accessors through which a stage before ``evaluation.report`` reads outcomes.

Every module that runs before the reporter may read outcomes only as *history*:
outcomes of matches inside a training window, inside a past selection window, or as a
state replay. It does so through one of two accessors, each opened for an explicit
``purpose`` with a ``year_ceiling`` that refuses any requested key from a later season
and, for a fold, the ``fold_outer_year`` the read serves. The reporter and the
post-barrier component evaluation are the only readers of a target year's outcomes.

* :class:`LabelHistory` reads ``labels.csv`` (the feature stage's label file) by
  ``(source_season, match_id)`` and verifies every returned row's identity, chronology
  and split fields against the feature metadata the caller already holds.
* :class:`PanelOutcomeHistory` reads the panel's ``a_won`` by ``match_id`` for the SR03
  slope calibration, which runs before ``labels.csv`` exists, with the same ceiling and
  an explicit ``cutoff_date``.
* :func:`projected_rows` parses an outcome-bearing table for its *metadata*: the outcome
  columns are dropped before any row is returned, and only a resolution flag (is the
  outcome recorded at all) survives. A fold reader may parse the panel only this way.

Both parse the whole file and filter the requested keys. The receipt each read appends
to :mod:`tennislab.chain.access` therefore records ``rows_parsed`` (what was physically
accessible) separately from ``rows_returned`` and ``max_season_returned`` (what the
caller received); it never claims the other rows were unavailable. Decision RB14.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain import access
from tennislab.chain.common import ChainError, sha256

LABEL_COLUMNS = (
    "match_id",
    "calendar_year",
    "source_season",
    "match_date",
    "tourney_id",
    "identity_tier",
    "primary_target",
    "a_won",
    "status",
    "source_field_agreement",
)
METADATA_FIELDS = (
    "calendar_year",
    "source_season",
    "match_date",
    "tourney_id",
    "identity_tier",
    "primary_target",
    "source_field_agreement",
)
PURPOSES = frozenset(
    {
        "training_fit",
        "past_selection_calibration",
        "past_market_calibration",
        # tier_elo: every panel outcome as Elo state history under the D-2 cursor.
        "elo_state_replay",
        # sr03_calibration: the training-window outcomes of one slope fit.
        "calibration_slope_fit",
        # sr03_calibration: the panel's metadata, outcome columns projected out.
        "calibration_metadata",
        # any stage declared none that needs a table's metadata: outcome columns dropped.
        "metadata_projection",
        # the post-barrier component evaluation of the persisted SR03 predictions.
        "component_scoring",
    }
)


class LabelHistoryError(ChainError):
    """An outcome read that is not a declared history read, or whose rows drift."""


def _check_purpose_and_ceiling(purpose: str, year_ceiling: int | None) -> None:
    if purpose not in PURPOSES:
        raise LabelHistoryError(
            f"undeclared outcome-history purpose {purpose!r}; expected one of {sorted(PURPOSES)}"
        )
    if year_ceiling is not None and (isinstance(year_ceiling, bool) or year_ceiling <= 0):
        raise LabelHistoryError("year_ceiling must be a positive integer")


class LabelHistory:
    """A hash-bound label file opened for a declared history purpose.

    ``year_ceiling`` is the last season whose outcomes the purpose may see; a requested
    key from a later season fails closed even when the caller's own filter admitted it.
    ``fold_outer_year`` names the fold the read serves, so the chain driver can check
    that the ceiling precedes it.
    """

    def __init__(
        self,
        path: Path,
        expected_sha256: str,
        *,
        purpose: str,
        year_ceiling: int | None = None,
        fold_outer_year: int | None = None,
    ) -> None:
        _check_purpose_and_ceiling(purpose, year_ceiling)
        if fold_outer_year is not None and year_ceiling is not None:
            if year_ceiling >= fold_outer_year:
                raise LabelHistoryError(
                    f"{purpose}: ceiling {year_ceiling} does not precede fold {fold_outer_year}"
                )
        self.path = Path(path)
        self.expected_sha256 = expected_sha256
        self.purpose = purpose
        self.year_ceiling = year_ceiling
        self.fold_outer_year = fold_outer_year
        self.reads: list[dict[str, Any]] = []

    def _receipt(self, **fields: Any) -> dict[str, Any]:
        receipt = {
            "accessor": type(self).__name__,
            "path": self.path.name,
            "sha256": self.expected_sha256,
            "purpose": self.purpose,
            "year_ceiling": self.year_ceiling,
            "fold_outer_year": self.fold_outer_year,
            **fields,
        }
        self.reads.append(receipt)
        access.record_receipt(receipt)
        return receipt

    def selected(
        self,
        keys: Sequence[tuple[str, str]],
        metadata: Mapping[tuple[str, str], Mapping[str, str]],
    ) -> Any:
        """Read outcomes for only ``keys`` and verify their joined metadata.

        Returns a ``tennislab.models.numerical.LabelTable`` built from values, so the
        adapter never opens the file itself.
        """
        from tennislab.models.numerical import LabelTable

        if sha256(self.path) != self.expected_sha256:
            raise LabelHistoryError("label file hash mismatch")
        allowed = set(keys)
        if self.year_ceiling is not None:
            late = sorted(key for key in allowed if int(key[0]) > self.year_ceiling)
            if late:
                raise LabelHistoryError(
                    f"{self.purpose}: requested outcomes after the {self.year_ceiling} "
                    f"ceiling: {late[:5]}"
                )
        values: dict[tuple[str, str], int] = {}
        seen: set[tuple[str, str]] = set()
        parsed = 0
        with self.path.open(newline="", encoding="utf-8") as handle:  # outcome-history read
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != LABEL_COLUMNS:
                raise LabelHistoryError("label header differs from fixed JOINT04 header")
            for row in reader:
                parsed += 1
                key = (row["source_season"], row["match_id"])
                if key in seen:
                    raise LabelHistoryError(f"duplicate label key: {key}")
                seen.add(key)
                if key not in allowed:
                    continue
                expected = metadata[key]
                for field in METADATA_FIELDS:
                    if row[field] != expected[field]:
                        raise LabelHistoryError(f"feature/label {field} mismatch at {key}")
                if row["a_won"] not in {"0", "1"}:
                    raise LabelHistoryError(f"invalid selected label at {key}")
                values[key] = int(row["a_won"])
        if set(values) != allowed:
            missing = sorted(allowed - set(values))
            raise LabelHistoryError(f"missing selected labels: {missing[:5]}")
        self._receipt(
            rows_parsed=parsed,
            rows_returned=len(values),
            max_season_returned=max((int(key[0]) for key in values), default=None),
        )
        return LabelTable.from_values(values, str(self.path) + "#selected")


class PanelOutcomeHistory:
    """The panel's ``a_won`` for a fixed set of match ids, as declared history.

    The panel carries every season's outcome; this accessor returns only the requested
    ids and refuses any whose ``source_season`` exceeds ``year_ceiling`` or whose
    ``match_date`` is after ``cutoff_date``. A blank ``a_won`` (an outcome not yet known)
    is refused rather than guessed.
    """

    def __init__(
        self,
        path: Path,
        expected_sha256: str,
        *,
        purpose: str,
        year_ceiling: int | None = None,
        cutoff_date: dt.date | None = None,
        fold_outer_year: int | None = None,
    ) -> None:
        _check_purpose_and_ceiling(purpose, year_ceiling)
        if fold_outer_year is not None and year_ceiling is not None:
            if year_ceiling >= fold_outer_year:
                raise LabelHistoryError(
                    f"{purpose}: ceiling {year_ceiling} does not precede fold {fold_outer_year}"
                )
        self.path = Path(path)
        self.expected_sha256 = expected_sha256
        self.purpose = purpose
        self.year_ceiling = year_ceiling
        self.cutoff_date = cutoff_date
        self.fold_outer_year = fold_outer_year
        self.reads: list[dict[str, Any]] = []

    def selected(self, match_ids: Sequence[str]) -> dict[str, int]:
        if sha256(self.path) != self.expected_sha256:
            raise LabelHistoryError("panel hash mismatch")
        allowed = set(match_ids)
        values: dict[str, int] = {}
        seen: set[str] = set()
        parsed = 0
        max_season: int | None = None
        max_date: dt.date | None = None
        with self.path.open(newline="", encoding="utf-8") as handle:  # outcome-history read
            reader = csv.DictReader(handle)
            required = {"match_id", "source_season", "match_date", "a_won"}
            if not required <= set(reader.fieldnames or ()):
                raise LabelHistoryError("panel lacks the outcome columns")
            for row in reader:
                parsed += 1
                match_id = row["match_id"]
                if match_id in seen:
                    raise LabelHistoryError(f"duplicate panel match id: {match_id}")
                seen.add(match_id)
                if match_id not in allowed:
                    continue
                season = int(row["source_season"])
                date = dt.date.fromisoformat(row["match_date"][:10])
                if self.year_ceiling is not None and season > self.year_ceiling:
                    raise LabelHistoryError(
                        f"{self.purpose}: requested outcome of season {season} after the "
                        f"{self.year_ceiling} ceiling: {match_id}"
                    )
                if self.cutoff_date is not None and date > self.cutoff_date:
                    raise LabelHistoryError(
                        f"{self.purpose}: requested outcome dated {date} after the cutoff "
                        f"{self.cutoff_date}: {match_id}"
                    )
                text = row["a_won"].strip().lower()
                if text in {"1", "true"}:
                    values[match_id] = 1
                elif text in {"0", "false"}:
                    values[match_id] = 0
                else:
                    raise LabelHistoryError(f"unresolved outcome (blank a_won) at {match_id}")
                max_season = season if max_season is None else max(max_season, season)
                max_date = date if max_date is None else max(max_date, date)
        if set(values) != allowed:
            missing = sorted(allowed - set(values))
            raise LabelHistoryError(f"missing selected outcomes: {missing[:5]}")
        receipt = {
            "accessor": type(self).__name__,
            "path": self.path.name,
            "sha256": self.expected_sha256,
            "purpose": self.purpose,
            "year_ceiling": self.year_ceiling,
            "cutoff_date": None if self.cutoff_date is None else self.cutoff_date.isoformat(),
            "fold_outer_year": self.fold_outer_year,
            "rows_parsed": parsed,
            "rows_returned": len(values),
            "max_season_returned": max_season,
            "max_match_date_returned": None if max_date is None else max_date.isoformat(),
        }
        self.reads.append(receipt)
        access.record_receipt(receipt)
        return values


OUTCOME_COLUMNS = frozenset(
    {
        "a_won",
        "winner_id",
        "loser_id",
        "winner_name",
        "loser_name",
        "a_source_side",
        "b_source_side",
        "score",
    }
)


def projected_rows(
    path: Path,
    expected_sha256: str,
    *,
    purpose: str,
    resolution_flag: tuple[str, str] | None = ("a_won", "outcome_known"),
) -> list[dict[str, str]]:
    """Every row of an outcome-bearing table with its outcome columns removed.

    ``resolution_flag = (column, name)`` adds a boolean-valued ``name`` saying whether
    ``column`` is non-blank, so a caller can tell a resolved match from a prospective one
    without seeing the value. The read is receipted like the accessors.
    """
    _check_purpose_and_ceiling(purpose, None)
    if sha256(path) != expected_sha256:
        raise LabelHistoryError("table hash mismatch")
    rows: list[dict[str, str]] = []
    dropped: set[str] = set()
    with Path(path).open(newline="", encoding="utf-8") as handle:  # projected read
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        dropped = {field for field in fields if field.lower() in OUTCOME_COLUMNS}
        for row in reader:
            projected = {key: value for key, value in row.items() if key not in dropped}
            if resolution_flag is not None:
                column, name = resolution_flag
                projected[name] = "1" if row.get(column, "") != "" else "0"
            rows.append(projected)
    receipt = {
        "accessor": "projected_rows",
        "path": Path(path).name,
        "sha256": expected_sha256,
        "purpose": purpose,
        "year_ceiling": None,
        "fold_outer_year": None,
        "rows_parsed": len(rows),
        "rows_returned": len(rows),
        "max_season_returned": None,
        "outcome_columns_dropped": sorted(dropped),
    }
    access.record_receipt(receipt)
    return rows
