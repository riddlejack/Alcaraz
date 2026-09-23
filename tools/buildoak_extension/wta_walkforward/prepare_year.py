"""Metadata-only preparation of one WTA walk-forward target year.

Derives a per-year date hierarchy plan from the frozen WTA 2024 extension plan. Every row
keeps its frozen dates, release basis, provenance and source locator; only the fit and
evaluation roles change with the target year. The plan keeps the frozen schema and
serialization, so the 2024 plan, memberships and IOC vocabulary reproduce the accepted
files byte for byte. No feature construction, estimator fit or outcome scoring happens
here; the labels file is read only for ``match_id``, ``calendar_year`` and
``primary_target``.
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
# Native WTA settings (tennis_predict.models); the fit worker applies them from the pinned
# source, so these are projections to be checked against its receipt, not overrides.
RECENT_START = "2017-01-01"
MIN_RECENT_ROWS = 15000
IOC_BUCKET_COUNT = 10
FROZEN_FIELDS = {
    "match_id",
    "event_id",
    "event_name",
    "anchor",
    "round",
    "level",
    "surface",
    "source_year",
    "source_sha256",
    "source_file",
    "source_line",
    "native_key",
    "target_date_proxy",
    "available_date_proxy",
    "eligible_through_date",
    "release_basis",
    "fit_target",
    "evaluation_target",
}
LABEL_COLUMNS = ("match_id", "calendar_year", "primary_target")


def sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def save(path: Path, value) -> None:
    # The frozen WTA preparation's serialization (tools/buildoak_extension/prepare.py).
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def primary_targets(labels: Path) -> dict[str, int]:
    """match_id -> calendar_year for primary targets; no other labels column is kept."""
    with labels.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = [header.index(name) for name in LABEL_COLUMNS]
        primary: dict[str, int] = {}
        for row in reader:
            key, year, flag = (row[i] for i in index)
            if flag == "1":
                if key in primary:
                    raise ValueError("duplicate primary target in labels: " + key)
                primary[key] = int(year)
    return primary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--frozen-plan", type=Path, required=True)
    parser.add_argument("--native-raw", type=Path, required=True)
    parser.add_argument("--rankings", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True, help="WTA01 selected full.csv")
    parser.add_argument("--selection-json", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True, help="WTA01 features/labels.csv")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fit-cutoff", default=None, help="default: (year-1)-12-30")
    parser.add_argument("--file-pattern", default=r"wta_matches_(\d{4})\.csv")
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
    by_locator: dict[tuple[str, int], dict] = {}
    for row in frozen:
        if set(row) != FROZEN_FIELDS:
            raise ValueError("frozen plan row fields differ from the WTA extension schema")
        if row["match_id"] in by_id:
            raise ValueError("duplicate frozen plan match_id: " + row["match_id"])
        locator = (row["source_file"], int(row["source_line"]))
        if locator in by_locator:
            raise ValueError("duplicate frozen plan locator: " + str(locator))
        by_id[row["match_id"]] = row
        by_locator[locator] = row
    if [r["match_id"] for r in frozen] != sorted(by_id):
        raise ValueError("frozen plan is not in match_id order")

    # Native raw files: every row must be the frozen plan row at the same source locator.
    pattern = re.compile(args.file_pattern)
    native_files = sorted(
        p for p in args.native_raw.resolve().iterdir() if p.is_file() and pattern.fullmatch(p.name)
    )
    if not native_files:
        raise ValueError("no native match files matched")
    native_sha: dict[str, str] = {}
    native_meta: dict[str, dict] = {}
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
                plan_row = by_locator.get((path.name, line))
                if plan_row is None:
                    raise ValueError(f"native row missing from frozen plan: {path.name}:{line}")
                match_id = plan_row["match_id"]
                anchor = dt.datetime.strptime(row["tourney_date"], "%Y%m%d").date().isoformat()
                checks = {
                    "native_key": (plan_row["native_key"], key),
                    "match_id": (match_id in {key, f"{key}@{path.name}:{line}"}, True),
                    "source_year": (plan_row["source_year"], file_year),
                    "source_sha256": (plan_row["source_sha256"], native_sha[path.name]),
                    "event_id": (plan_row["event_id"], row["tourney_id"]),
                    "event_name": (plan_row["event_name"], row["tourney_name"]),
                    "anchor": (plan_row["anchor"], anchor),
                    "round": (plan_row["round"], row["round"]),
                    "level": (plan_row["level"], row["tourney_level"]),
                    "surface": (plan_row["surface"], row["surface"] or "Unknown"),
                }
                for field, (frozen_value, native_value) in checks.items():
                    if frozen_value != native_value:
                        raise ValueError(f"frozen plan {field} differs from native: {match_id}")
                if match_id in native_meta:
                    raise ValueError("duplicate transport match_id: " + match_id)
                native_meta[match_id] = {
                    "match_num": int(row["match_num"]),
                    "winner_name": row.get("winner_name", ""),
                    "loser_name": row.get("loser_name", ""),
                    "winner_ioc": row.get("winner_ioc", ""),
                    "loser_ioc": row.get("loser_ioc", ""),
                    "sequence": sequence,
                }
                sequence += 1
    if set(native_meta) != set(by_id):
        raise ValueError("frozen plan rows are not all present in the native files")

    # Target cohort: WTA01 primary targets of this year with a saved selected forecast.
    primary = primary_targets(args.labels)
    with args.selected.open(newline="") as handle:
        selected_ids = [r["match_id"] for r in csv.DictReader(handle)]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("duplicate selected forecast key")
    cohort = sorted(k for k in selected_ids if primary.get(k) == year)
    selection = json.loads(args.selection_json.read_text())
    if selection.get("outer_primary_rows") != len(cohort):
        raise ValueError("cohort size differs from the accepted selection's primary rows")
    if selection.get("selection_cutoff_inclusive") != fit_cutoff:
        raise ValueError("selection cutoff differs from the fit boundary")
    if selection.get("selected_prediction_sha256") != sha(args.selected):
        raise ValueError("selected forecast file differs from the accepted selection")
    # WTA01 pipeline key_hash over sorted (season, match_id) pairs.
    key_payload = "".join(f"{year},{key}\n" for key in cohort).encode()
    cohort_key_hash = hashlib.sha256(key_payload).hexdigest()
    if selection.get("outer_primary_membership_sha256") != cohort_key_hash:
        raise ValueError("cohort differs from the accepted selection's primary membership")
    for key in cohort:
        plan_row = by_id.get(key)
        if plan_row is None:
            raise ValueError("cohort key missing from frozen plan: " + key)
        if plan_row["release_basis"] != "accepted_reported_date":
            raise ValueError("cohort key without accepted reported date: " + key)
        if plan_row["target_date_proxy"][:4] != str(year):
            raise ValueError("cohort key outside the target year: " + key)
        if plan_row["eligible_through_date"] < fit_cutoff:
            raise ValueError("target cutoff precedes the fit boundary: " + key)
    cohort_set = set(cohort)

    # Year-specific roles on the frozen hierarchy; every other field is unchanged.
    plan = []
    for row in frozen:
        row = dict(row)
        key = row["match_id"]
        released = (
            row["target_date_proxy"] <= fit_cutoff and row["available_date_proxy"] <= fit_cutoff
        )
        row["fit_target"] = bool(released and key not in cohort_set)
        row["evaluation_target"] = key in cohort_set
        plan.append(row)
    fit = [r for r in plan if r["fit_target"]]
    target = [r for r in plan if r["evaluation_target"]]
    if len(target) != len(cohort):
        raise ValueError("evaluation membership drift")
    save(root / "date_hierarchy_plan.json", plan)
    for name, rows in [("fit", fit), ("target", target)]:
        (root / (name + "_membership.txt")).write_text(
            "\n".join(sorted(r["match_id"] for r in rows)) + "\n"
        )

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

    # Native top-10 IOC buckets from fit rows only, counted in the frozen preparation's
    # order (winners then losers over the chronological fit rows); only bucket membership
    # enters the features, so a tie at the 10/11 boundary is refused.
    ordered_fit = sorted(fit, key=order)
    iocs: collections.Counter = collections.Counter()
    for side in ["winner_ioc", "loser_ioc"]:
        for row in ordered_fit:
            value = native_meta[row["match_id"]][side].strip().upper()
            if value:
                iocs[value] += 1
    ranked = iocs.most_common()
    vocabulary = [code for code, _ in iocs.most_common(IOC_BUCKET_COUNT)]
    tenth = ranked[IOC_BUCKET_COUNT - 1] if len(ranked) >= IOC_BUCKET_COUNT else None
    eleventh = ranked[IOC_BUCKET_COUNT] if len(ranked) > IOC_BUCKET_COUNT else None
    cutoff_tie = bool(tenth and eleventh and tenth[1] == eleventh[1])
    if cutoff_tie:
        raise ValueError("IOC vocabulary tie at the bucket boundary; resolve before freezing")
    save(
        root / "ioc_vocabulary.json",
        {"vocabulary": vocabulary, "counts": iocs, "basis": "fit-membership-only native IOC count"},
    )

    # Metadata-only chronology replay projection with the worker key and controller schedule.
    tasks = sorted(
        {r["eligible_through_date"] for r in plan if r["fit_target"] or r["evaluation_target"]}
    )
    batch_sizes = collections.Counter(
        r["eligible_through_date"] for r in plan if r["fit_target"] or r["evaluation_target"]
    )
    releases = sorted(plan, key=lambda r: (r["available_date_proxy"], r["match_id"]))
    cursor = 0
    latest = None
    replays = 0
    replay_rows = 0
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
        "largest_target_batch": max(batch_sizes.values()),
        "basis": "exact worker chronological key and controller cutoff/release schedule",
    }
    save(root / "replay_schedule_projection.json", projection)

    recent_rows = sum(r["target_date_proxy"] >= RECENT_START for r in fit)
    surfaces = collections.Counter(r["surface"] for r in fit)
    levels = collections.Counter(r["level"] for r in fit)
    receipt = {
        "status": "metadata_only_no_candidate_scores",
        "tour": "wta",
        "cohort": f"WTA{year}_primary_targets",
        "target_year": year,
        "fit_cutoff": fit_cutoff,
        "elo_reference_date": fit_cutoff,
        "native_rows": len(plan),
        "fit_rows": len(fit),
        "target_rows": len(target),
        "state_only_rows": len(plan) - len(fit) - len(target),
        "recent_rows": recent_rows,
        "fit_menu_projection": {
            "global": {
                "rows": len(fit),
                "components": [
                    {"weight": 0.65, "trees": 800, "max_depth": 4},
                    {"weight": 0.35, "trees": 650, "max_depth": 3},
                ],
                "seed": 42,
            },
            "segment_Hard": {
                "rows": surfaces.get("Hard", 0),
                "trees": 900,
                "global_weight": 0.1,
                "projected_active": surfaces.get("Hard", 0) > 0,
            },
            "segment_I": {
                "rows": levels.get("I", 0),
                "trees": 900,
                "global_weight": 0.1,
                "projected_active": levels.get("I", 0) > 0,
            },
            "recent_global": {
                "rows": recent_rows,
                "recent_start": RECENT_START,
                "minimum_rows": MIN_RECENT_ROWS,
                "recent_weight": 0.35,
                "projected_active": recent_rows >= MIN_RECENT_ROWS,
            },
        },
        "fit_surface_counts": dict(sorted(surfaces.items())),
        "fit_level_counts": dict(sorted(levels.items())),
        "release_basis_counts": dict(
            sorted(collections.Counter(r["release_basis"] for r in plan).items())
        ),
        "target_date_range": [
            min(r["target_date_proxy"] for r in target),
            max(r["target_date_proxy"] for r in target),
        ],
        "ioc_vocabulary": {
            "vocabulary": vocabulary,
            "tenth": tenth,
            "eleventh": eleventh,
            "cutoff_tie": cutoff_tie,
        },
        "cohort_checks": {
            "selected_forecast_rows": len(selected_ids),
            "excluded_non_primary_selected_rows": len(selected_ids) - len(cohort),
            "outer_primary_rows": selection["outer_primary_rows"],
            "outer_primary_membership_sha256": cohort_key_hash,
            "selected_candidate_id": selection.get("selected_candidate_id"),
            "labels_columns_read": list(LABEL_COLUMNS),
        },
        "replay_schedule": projection,
        "sources": {
            "frozen_plan": {"path": str(frozen_path), "sha256": sha(frozen_path)},
            "native_match_files": {str(p): native_sha[p.name] for p in native_files},
            "rankings": {"path": str(args.rankings.resolve()), "sha256": sha(args.rankings)},
            "selected": {"path": str(args.selected.resolve()), "sha256": sha(args.selected)},
            "selection_json": {
                "path": str(args.selection_json.resolve()),
                "sha256": sha(args.selection_json),
            },
            "labels": {"path": str(args.labels.resolve()), "sha256": sha(args.labels)},
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
