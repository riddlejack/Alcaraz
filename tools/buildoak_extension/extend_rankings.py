"""Rankings stream through a later last target cutoff, by the frozen sort and dedup procedure.

ATP follows D97 ``TMB/prepare_rankings.py`` (player parsed as ``int(float(...))``); WTA follows
``prepare.py`` (player parsed as ``int(...)``). Both read the ``<tour>_rankings_*.csv`` files of
one native directory in lexicographic order, keep 1984-01-01 through the given cutoff, keep the
lowest rank per (date, player) with the first source row on ties, and write the stream sorted
by (date, player). The frozen stream must be a byte prefix of the new one: dedup is per
(date, player), so moving the cutoff only appends later dates.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import sqlite3
from pathlib import Path

SQL = (
    "INSERT INTO ranking VALUES (?,?,?,?) ON CONFLICT(day,player) DO UPDATE SET "
    "rank=excluded.rank,points=excluded.points WHERE excluded.rank<ranking.rank"
)


def sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tour", choices=["atp", "wta"], required=True)
    parser.add_argument("--native-raw", type=Path, required=True)
    parser.add_argument("--through", required=True, help="last target cutoff, YYYY-MM-DD")
    parser.add_argument("--frozen-rankings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="rankings CSV (new file)")
    args = parser.parse_args()
    maximum = int(dt.date.fromisoformat(args.through).strftime("%Y%m%d"))
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("refusing to overwrite " + str(output))
    database = output.with_suffix(".sqlite")
    if database.exists():
        raise SystemExit("refusing to reuse " + str(database))
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE ranking (day INTEGER, player INTEGER, rank REAL, points REAL, "
        "PRIMARY KEY(day,player)) WITHOUT ROWID"
    )
    counts: collections.Counter = collections.Counter()
    sources = {}
    for path in sorted(args.native_raw.resolve().glob(f"{args.tour}_rankings_*.csv")):
        sources[str(path)] = sha(path)
        pending = []
        with path.open() as handle:
            for row in csv.DictReader(handle):
                counts["input_rows"] += 1
                try:
                    day = int(row["ranking_date"])
                    dt.datetime.strptime(str(day), "%Y%m%d")
                    if args.tour == "atp":
                        player = int(float(row["player"]))
                    else:
                        player = int(row["player"])
                    rank = float(row["rank"])
                    if not math.isfinite(rank):
                        raise ValueError("rank not finite")
                except ValueError, TypeError, KeyError:
                    counts["invalid"] += 1
                    continue
                if not 19840101 <= day <= maximum:
                    counts["excluded_date"] += 1
                    continue
                try:
                    points = float(row.get("points", ""))
                    if not math.isfinite(points):
                        points = None
                except ValueError, TypeError:
                    points = None
                pending.append((day, player, rank, points))
                counts["eligible_rows_before_dedup"] += 1
                if len(pending) >= 10000:
                    connection.executemany(SQL, pending)
                    pending = []
        connection.executemany(SQL, pending)
    connection.commit()
    with output.open("w") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ranking_date", "player", "rank", "points"])
        writer.writerows(
            connection.execute("SELECT day,player,rank,points FROM ranking ORDER BY day,player")
        )
    counts["output_rows"] = connection.execute("SELECT count(*) FROM ranking").fetchone()[0]
    counts["duplicate_player_date_rows"] = (
        counts["eligible_rows_before_dedup"] - counts["output_rows"]
    )
    connection.close()

    frozen = args.frozen_rankings.resolve()
    frozen_size = frozen.stat().st_size
    with output.open("rb") as new_handle, frozen.open("rb") as old_handle:
        prefix = new_handle.read(frozen_size) == old_handle.read()
    with frozen.open(newline="") as handle:
        rows = list(csv.reader(handle))
    frozen_last = rows[-1][0]
    with output.open(newline="") as handle:
        appended = collections.Counter(
            row[0][:4]
            for row in csv.reader(handle)
            if row[0] != "ranking_date" and row[0] > frozen_last
        )
    receipt = {
        "status": "sorted_and_native_min_rank_deduplicated",
        "tour": args.tour,
        "procedure": "TMB/prepare_rankings.py"
        if args.tour == "atp"
        else "tools/buildoak_extension/prepare.py",
        "scope": f"1984-01-01 through last target cutoff {args.through}",
        "counts": dict(counts),
        "source_sha256": sources,
        "output": {"path": str(output), "sha256": sha(output), "bytes": output.stat().st_size},
        "frozen": {
            "path": str(frozen),
            "sha256": sha(frozen),
            "bytes": frozen_size,
            "rows": len(rows) - 1,
            "last_ranking_date": frozen_last,
        },
        "frozen_is_byte_prefix": prefix,
        "appended_rows_by_year": dict(sorted(appended.items())),
    }
    output.with_name(output.stem + "_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    if not prefix:
        raise SystemExit("frozen rankings are not a byte prefix of the extended stream")


if __name__ == "__main__":
    main()
