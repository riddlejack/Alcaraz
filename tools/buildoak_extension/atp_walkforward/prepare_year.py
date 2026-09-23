"""Metadata-only preparation of one ATP walk-forward target year.

Derives a per-year date hierarchy plan from the frozen ATP 2024 plan (D97). Every row
keeps its frozen dates, release basis and provenance; only the fit/evaluation roles
change with the target year, and the extension controller's source locators are added.
No feature construction, estimator fit or outcome scoring happens here.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

ROUND_ORDER = {"RR": 0, "R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7}
# Native ATP recent-era blend settings (tennis_predict.models TEMPORAL_BLEND_SPECS_BY_TOUR);
# the fit worker re-derives them from the pinned source and refuses a mismatch.
RECENT_START = "2019-01-01"
MIN_RECENT_ROWS = 15000
IOC_BUCKET_COUNT = 10
FROZEN_FIELDS = {
    "match_id",
    "event_id",
    "event_name",
    "anchor",
    "source_year",
    "source_sha256",
    "round",
    "ids",
    "level",
    "target_date_proxy",
    "available_date_proxy",
    "eligible_through_date",
    "release_basis",
    "date_provenance",
    "fit_target",
    "evaluation_target",
}


def sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def membership_text(keys) -> str:
    return "\n".join(sorted(keys)) + "\n"


def normalize_ioc(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--frozen-plan", type=Path, required=True)
    parser.add_argument("--native-raw", type=Path, required=True)
    parser.add_argument("--rankings", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True, help="G-L predictions.csv carrier")
    parser.add_argument("--alcaraz-selected", type=Path, required=True, help="full_tier.csv")
    parser.add_argument("--selection-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fit-cutoff", default=None, help="default: (year-1)-12-30")
    parser.add_argument("--file-pattern", default=r"atp_matches_(\d{4})\.csv")
    args = parser.parse_args()
    year = args.year
    fit_cutoff = args.fit_cutoff or f"{year - 1}-12-30"
    dt.date.fromisoformat(fit_cutoff)
    if not fit_cutoff < f"{year}-01-01":
        raise ValueError("fit cutoff must precede the target year")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)

    frozen_path = args.frozen_plan.resolve()
    frozen = json.loads(frozen_path.read_text())
    if not isinstance(frozen, list) or not frozen:
        raise ValueError("frozen plan must be a nonempty list")
    by_id: dict[str, dict] = {}
    for row in frozen:
        if set(row) != FROZEN_FIELDS:
            raise ValueError("frozen plan row fields differ from the D97 schema")
        if row["match_id"] in by_id:
            raise ValueError("duplicate frozen plan match_id: " + row["match_id"])
        by_id[row["match_id"]] = row

    # Native raw files: locators, identities, IOC codes and the chronological tie fields.
    pattern = re.compile(args.file_pattern)
    native_files = sorted(
        p for p in args.native_raw.resolve().iterdir() if p.is_file() and pattern.fullmatch(p.name)
    )
    if not native_files:
        raise ValueError("no native match files matched")
    locators: dict[str, tuple[str, int]] = {}
    native_meta: dict[str, dict] = {}
    native_sha: dict[str, str] = {}
    sequence = 0
    for path in native_files:
        file_year = int(pattern.fullmatch(path.name).group(1))
        native_sha[path.name] = sha(path)
        with path.open(encoding="utf-8-sig") as handle:
            for line, row in enumerate(csv.DictReader(handle), start=2):
                if not all(
                    row.get(k) for k in ["winner_id", "loser_id", "tourney_date", "match_num"]
                ):
                    continue
                key = row["tourney_id"] + "/" + str(int(row["match_num"]))
                if key in locators:
                    raise ValueError("duplicate native key: " + key)
                plan_row = by_id.get(key)
                if plan_row is None:
                    raise ValueError("native row missing from frozen plan: " + key)
                if plan_row["source_year"] != file_year:
                    raise ValueError("frozen plan source year differs from file: " + key)
                if plan_row["source_sha256"] != native_sha[path.name]:
                    raise ValueError("native file hash differs from frozen plan: " + path.name)
                if sorted([row["winner_id"], row["loser_id"]]) != plan_row["ids"]:
                    raise ValueError("frozen identity differs from native row: " + key)
                locators[key] = (path.name, line)
                native_meta[key] = {
                    "match_num": int(row["match_num"]),
                    "winner_name": row.get("winner_name", ""),
                    "loser_name": row.get("loser_name", ""),
                    "winner_ioc": normalize_ioc(row.get("winner_ioc")),
                    "loser_ioc": normalize_ioc(row.get("loser_ioc")),
                    "sequence": sequence,
                }
                sequence += 1
    if set(locators) != set(by_id):
        raise ValueError("frozen plan rows are not all present in the native files")

    # Target cohort: accepted all-target keys for this year (the same carrier D97 used).
    with args.cohort.open() as handle:
        cohort = {
            r["match_id"]: r
            for r in csv.DictReader(handle)
            if r["tour"] == "ATP" and r["year"] == str(year)
        }
    if not cohort:
        raise ValueError("cohort carrier has no ATP rows for the target year")
    with args.alcaraz_selected.open() as handle:
        selected = {r["match_id"]: r for r in csv.DictReader(handle)}
    selection = json.loads(args.selection_json.read_text())
    if selection.get("outer_primary_rows") != len(cohort):
        raise ValueError("cohort size differs from the accepted selection's primary rows")
    if not set(cohort) <= set(selected):
        raise ValueError("cohort keys missing from the accepted full_tier forecasts")
    for key, row in cohort.items():
        if not row["calibrated_incumbent"] == row["raw_incumbent"] == selected[key]["p_a_wins"]:
            raise ValueError("cohort carrier probability differs from full_tier: " + key)
        plan_row = by_id.get(key)
        if plan_row is None:
            raise ValueError("cohort key missing from frozen plan: " + key)
        if plan_row["release_basis"] != "accepted_reported_date":
            raise ValueError("cohort key without accepted reported date: " + key)
        if plan_row["target_date_proxy"] != row["match_date"]:
            raise ValueError("cohort date differs from frozen plan: " + key)
        if plan_row["target_date_proxy"][:4] != str(year):
            raise ValueError("cohort key outside the target year: " + key)
        if plan_row["eligible_through_date"] < fit_cutoff:
            raise ValueError("target cutoff precedes the fit boundary: " + key)

    # Year-specific roles on the frozen hierarchy.
    plan = []
    for key in sorted(by_id):
        row = dict(by_id[key])
        released = (
            row["target_date_proxy"] <= fit_cutoff and row["available_date_proxy"] <= fit_cutoff
        )
        row["fit_target"] = bool(released and key not in cohort)
        row["evaluation_target"] = key in cohort
        row["tour"] = "atp"
        row["native_key"] = key
        row["source_file"], row["source_line"] = locators[key]
        plan.append(row)
    fit = [r for r in plan if r["fit_target"]]
    target = [r for r in plan if r["evaluation_target"]]
    if len(target) != len(cohort):
        raise ValueError("evaluation membership drift")
    plan_path = root / "date_hierarchy_plan.json"
    plan_path.write_text(json.dumps(plan, separators=(",", ":"), allow_nan=False) + "\n")
    (root / "fit_membership.txt").write_text(membership_text(r["match_id"] for r in fit))
    (root / "target_membership.txt").write_text(membership_text(r["match_id"] for r in target))

    # IOC vocabulary from fit rows only: the same normalized counts as the native
    # tracked_ioc_buckets; only bucket membership enters the features, not bucket order.
    iocs: collections.Counter = collections.Counter()
    for row in fit:
        meta = native_meta[row["match_id"]]
        for side in ["winner_ioc", "loser_ioc"]:
            if meta[side]:
                iocs[meta[side]] += 1
    ranked = sorted(iocs.items(), key=lambda item: (-item[1], item[0]))
    top = ranked[:IOC_BUCKET_COUNT]
    eleventh = ranked[IOC_BUCKET_COUNT] if len(ranked) > IOC_BUCKET_COUNT else None
    cutoff_tie = bool(eleventh and top and eleventh[1] == top[-1][1])
    if cutoff_tie:
        raise ValueError("IOC vocabulary tie at the bucket boundary; resolve before freezing")
    save(
        root / "ioc_vocabulary.json",
        {
            "fit_rows": len(fit),
            "top10": top,
            "eleventh": eleventh,
            "cutoff_tie": cutoff_tie,
            "vocabulary": [code for code, _ in top],
            "basis": "normalized IOC counts over fit rows only, as native tracked_ioc_buckets",
        },
    )

    # Metadata-only chronology replay projection with the exact worker key and schedule.
    def order(row):
        meta = native_meta[row["match_id"]]
        return (
            row["target_date_proxy"],
            row["event_name"],
            ROUND_ORDER.get(row["round"], 0),
            meta["match_num"],
            meta["winner_name"],
            meta["loser_name"],
            meta["sequence"],
        )

    tasks = sorted(
        {r["eligible_through_date"] for r in plan if r["fit_target"] or r["evaluation_target"]}
    )
    releases = sorted(plan, key=lambda r: (r["available_date_proxy"], r["match_id"]))
    cursor = 0
    latest = None
    replays = 0
    replay_rows = 0
    largest_batch = max(
        collections.Counter(
            r["eligible_through_date"] for r in plan if r["fit_target"] or r["evaluation_target"]
        ).values()
    )
    for cutoff in tasks:
        incoming = []
        while cursor < len(releases) and releases[cursor]["available_date_proxy"] <= cutoff:
            incoming.append(releases[cursor])
            cursor += 1
        incoming.sort(key=order)
        if incoming:
            if latest is not None and order(incoming[0]) < latest:
                replays += 1
                replay_rows += cursor
            latest = max([order(r) for r in incoming] + ([latest] if latest else []))
    projection = {
        "target_year": year,
        "cutoff_batches": len(tasks),
        "first_cutoff": tasks[0],
        "last_cutoff": tasks[-1],
        "history_rows_released_through_last_cutoff": cursor,
        "rows_never_released": len(plan) - cursor,
        "chronology_replays": replays,
        "cumulative_rows_replayed": replay_rows,
        "largest_target_batch": largest_batch,
        "basis": "exact worker chronological key and controller cutoff/release schedule",
    }
    save(root / "replay_schedule_projection.json", projection)

    recent_rows = sum(r["target_date_proxy"] >= RECENT_START for r in fit)
    levels = collections.Counter(r["level"] for r in fit)
    receipt = {
        "status": "metadata_only_no_candidate_scores",
        "cohort": f"ATP{year}_all_targets",
        "target_year": year,
        "fit_cutoff": fit_cutoff,
        "elo_reference_date": fit_cutoff,
        "native_rows": len(plan),
        "fit_rows": len(fit),
        "target_rows": len(target),
        "state_only_rows": len(plan) - len(fit) - len(target),
        "recent_rows": recent_rows,
        "fit_menu_projection": {
            "global": {"rows": len(fit), "trees": 900, "seed": 42},
            "segment_A": {"rows": levels.get("A", 0), "trees": 800, "global_weight": 0.0},
            "segment_250": {"rows": levels.get("250", 0), "trees": 1000, "global_weight": 0.775},
            "recent_global": {
                "rows": recent_rows,
                "recent_start": RECENT_START,
                "minimum_rows": MIN_RECENT_ROWS,
                "projected_active": recent_rows >= MIN_RECENT_ROWS,
            },
        },
        "fit_level_counts": dict(sorted(levels.items())),
        "release_basis_counts": dict(collections.Counter(r["release_basis"] for r in plan)),
        "target_date_range": [
            min(r["target_date_proxy"] for r in target),
            max(r["target_date_proxy"] for r in target),
        ],
        "replay_schedule": projection,
        "sources": {
            "frozen_plan": {"path": str(frozen_path), "sha256": sha(frozen_path)},
            "native_match_files": {str(p): native_sha[p.name] for p in native_files},
            "rankings": {"path": str(args.rankings.resolve()), "sha256": sha(args.rankings)},
            "cohort_carrier": {"path": str(args.cohort.resolve()), "sha256": sha(args.cohort)},
            "alcaraz_selected": {
                "path": str(args.alcaraz_selected.resolve()),
                "sha256": sha(args.alcaraz_selected),
            },
            "selection_json": {
                "path": str(args.selection_json.resolve()),
                "sha256": sha(args.selection_json),
            },
        },
        "output_bindings": {str(p): sha(p) for p in sorted(root.iterdir()) if p.is_file()},
    }
    save(root / "preparation.json", receipt)
    print(
        json.dumps(
            {k: v for k, v in receipt.items() if k not in ["sources", "output_bindings"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
