"""The one accessor through which a stage before ``evaluation.report`` reads outcomes.

Every module that runs before the reporter may read ``labels.csv`` only as *history*:
outcomes of matches inside a training window, inside a past selection window, or as a
membership count. It does so through :class:`LabelHistory`, which opens the file once
per read with an explicit ``purpose`` and an optional ``year_ceiling`` that refuses any
requested key from a later season. The reporter is the only module that opens the file
to score a target year, and it does not use this class.

The read itself is the archive runner's ``label_subset``: only a previously fixed key
set is returned, and every returned row's identity, chronology and split fields are
checked against the feature metadata the caller already holds.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

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
    }
)


class LabelHistoryError(ChainError):
    """An outcome read that is not a declared history read, or whose rows drift."""


class LabelHistory:
    """A hash-bound label file opened for a declared history purpose.

    ``year_ceiling`` is the last season whose outcomes the purpose may see; a requested
    key from a later season fails closed even when the caller's own filter admitted it.
    """

    def __init__(
        self,
        path: Path,
        expected_sha256: str,
        *,
        purpose: str,
        year_ceiling: int | None = None,
    ) -> None:
        if purpose not in PURPOSES:
            raise LabelHistoryError(
                f"undeclared outcome-history purpose {purpose!r}; expected one of {sorted(PURPOSES)}"
            )
        if year_ceiling is not None and (isinstance(year_ceiling, bool) or year_ceiling <= 0):
            raise LabelHistoryError("year_ceiling must be a positive integer")
        self.path = Path(path)
        self.expected_sha256 = expected_sha256
        self.purpose = purpose
        self.year_ceiling = year_ceiling
        self.reads: list[dict[str, Any]] = []

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
        with self.path.open(newline="", encoding="utf-8") as handle:  # outcome-history read
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != LABEL_COLUMNS:
                raise LabelHistoryError("label header differs from fixed JOINT04 header")
            for row in reader:
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
        self.reads.append(
            {"purpose": self.purpose, "rows": len(values), "year_ceiling": self.year_ceiling}
        )
        return LabelTable.from_values(values, str(self.path) + "#selected")
