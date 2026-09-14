"""Build the global-edition index for a configured ranking stream.

Stage ``edition_index``. Ported from the archive's ``WTA02_models/build_edition_index.py``,
which is the ``TIER01_models`` revision plus ``--unordered-source``. The ATP normalized
stream happens to be in nondecreasing effective-date order because the ATP decade files
are, and the builder grouped editions by streaming consecutive equal dates and refused
anything else. The WTA decade files are not: the ``rankings`` stage records 3,712
date-order decreases in the WTA stream, so a strictly streaming build refuses the file.
With ``--unordered-source`` the editions are accumulated per date and emitted in date
order -- the same index content a sorted source would produce, no row value changed and no
row dropped -- and the decrease count is recorded in the summary. Without the flag the
original refusal stands, so an ATP build is unchanged.

What changed in the port: the pinned row validator is imported by name from
:mod:`tennislab.chronology.ranking_lookup` instead of being loaded from a path at a
pinned hash (``--lookup-module-sha256`` is still accepted and recorded as a declared
binding, and never selects the code that runs); paths resolve through
``resolve_under_root``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    relative_to_root,
    resolve_under_root,
    sha256,
)
from tennislab.chronology.ranking_lookup import EXPECTED_HEADER, validate_row

SCHEMA_VERSION = "MULTI01-ranking-global-edition-index-v1"
LOOKUP_CONTRACT = {
    "cutoff": "target_date minus 2 calendar days",
    "global_edition_selection": "latest effective_date on or before cutoff",
    "player_selection": "exact player_id on selected global edition only; never personal carry-forward",
    "duplicate_policy": "collapse identical raw rank/points while retaining all locators; conflicting values are ambiguous and missing",
    "staleness": "no maximum age; flag snapshot_age_days greater than 14",
}


def build(
    source: Path,
    output_dir: Path,
    expected_source_sha256: str | None = None,
    lookup_module_sha256: str | None = None,
    unordered_source: bool = False,
) -> dict[str, object]:
    source_sha = sha256(source)
    if expected_source_sha256 is not None and source_sha != expected_source_sha256:
        raise ChainError(f"ranking source SHA-256 mismatch: {source_sha}")
    output_dir.mkdir(parents=True, exist_ok=True)

    edition_rows: list[dict[str, object]] = []
    dates: list[dt.date] = []
    row_count = 0
    missing_points = 0
    exact_duplicate_groups = 0
    conflicting_duplicate_groups = 0
    duplicate_excess_rows = 0
    known_player_ids: set[int] = set()
    current_date: dt.date | None = None
    current_count = 0
    order_decreases = 0
    player_values: dict[int, list[tuple[str, str]]] = defaultdict(list)
    # --unordered-source path: one accumulator per effective date, emitted in date order.
    by_date_count: dict[dt.date, int] = defaultdict(int)
    by_date_players: dict[dt.date, dict[int, list[tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    def finish_edition() -> None:
        nonlocal exact_duplicate_groups, conflicting_duplicate_groups, duplicate_excess_rows
        if current_date is None:
            return
        edition_rows.append(
            {"effective_date": current_date.isoformat(), "row_count": current_count}
        )
        dates.append(current_date)
        for values in player_values.values():
            if len(values) <= 1:
                continue
            duplicate_excess_rows += len(values) - 1
            if len(set(values)) == 1:
                exact_duplicate_groups += 1
            else:
                conflicting_duplicate_groups += 1

    with gzip.open(source, "rt", encoding="utf-8-sig", errors="strict", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_HEADER:
            raise ChainError(f"unexpected ranking header: {reader.fieldnames}")
        for row in reader:
            validate_row(row)
            row_date = dt.date.fromisoformat(row["effective_date"])
            if current_date is not None and row_date < current_date:
                order_decreases += 1
                if not unordered_source:
                    raise ChainError("ranking editions are not in nondecreasing date order")
            row_count += 1
            missing_points += row["ranking_points"] == ""
            player_id = int(row["player_id"])
            known_player_ids.add(player_id)
            if unordered_source:
                current_date = row_date
                by_date_count[row_date] += 1
                by_date_players[row_date][player_id].append((row["rank"], row["ranking_points"]))
                continue
            if row_date != current_date:
                finish_edition()
                current_date = row_date
                current_count = 0
                player_values = defaultdict(list)
            current_count += 1
            player_values[player_id].append((row["rank"], row["ranking_points"]))
        if unordered_source:
            for date_value in sorted(by_date_count):
                current_date = date_value
                current_count = by_date_count[date_value]
                player_values = by_date_players[date_value]
                finish_edition()
        else:
            finish_edition()

    gap_rows = [
        {
            "earlier_effective_date": earlier.isoformat(),
            "later_effective_date": later.isoformat(),
            "gap_days": (later - earlier).days,
        }
        for earlier, later in zip(dates, dates[1:], strict=False)
    ]
    longest = max(gap_rows, key=lambda row: int(row["gap_days"]))
    rows_2020 = [row for row in gap_rows if str(row["earlier_effective_date"]).startswith("2020-")]
    longest_2020 = max(rows_2020, key=lambda row: int(row["gap_days"])) if rows_2020 else None
    index = {
        "schema_version": SCHEMA_VERSION,
        "source_path": relative_to_root(source, label="ranking source"),
        "source_sha256": source_sha,
        "source_bytes": source.stat().st_size,
        "source_rows": row_count,
        "source_header": EXPECTED_HEADER,
        "known_player_ids": sorted(known_player_ids),
        "editions": edition_rows,
    }
    index_path = output_dir / "edition_index.json"
    index_sha256 = atomic_json(index_path, index)
    summary: dict[str, Any] = {
        "status": "PASS",
        "source_path": index["source_path"],
        "source_sha256": source_sha,
        "source_rows": row_count,
        "global_editions": len(dates),
        "distinct_player_ids": len(known_player_ids),
        "first_effective_date": dates[0].isoformat(),
        "last_effective_date": dates[-1].isoformat(),
        "rows_with_missing_points": missing_points,
        "source_effective_date_order_decreases": order_decreases,
        "source_order_policy": (
            "accumulated per effective date and emitted in date order"
            if unordered_source
            else "streamed in nondecreasing source order"
        ),
        "byte_equivalent_duplicate_groups": exact_duplicate_groups,
        "conflicting_duplicate_groups": conflicting_duplicate_groups,
        "duplicate_excess_rows": duplicate_excess_rows,
        "longest_global_edition_gap": longest,
        "longest_2020_global_edition_gap": longest_2020,
        "edition_index_path": "edition_index.json",
        "edition_index_sha256": index_sha256,
        "lookup_contract": dict(LOOKUP_CONTRACT),
    }
    if lookup_module_sha256 is not None:
        summary["declared_binding"] = {
            "ranking_lookup_module_sha256": lookup_module_sha256,
            "module": "tennislab.chronology.ranking_lookup",
        }
    atomic_json(output_dir / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="qualified rankings .csv.gz")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--lookup-module-sha256")
    parser.add_argument(
        "--unordered-source",
        action="store_true",
        help="accumulate editions per effective date instead of requiring source order",
    )
    args = parser.parse_args(argv)
    summary = build(
        resolve_under_root(args.source, label="source"),
        resolve_under_root(args.output_dir, label="output_dir"),
        args.expected_source_sha256,
        args.lookup_module_sha256,
        args.unordered_source,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
