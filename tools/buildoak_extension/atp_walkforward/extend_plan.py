"""Extend the frozen D97 ATP date hierarchy plan with the rows of later native match files.

Every frozen row is kept verbatim. Rows of the new native files are dated by the D97 hierarchy
(``TMB/project_date_hierarchy.py``): the accepted panel's reported date, else a unique pinned
Q1 market date from the join candidates, else the event anchor released at the reported final
or at anchor + 21 days. New rows carry the frozen plan's role flags under the D97 constants
(fit boundary 2023-12-30, 2024 targets), which ``prepare_year*.py`` recomputes per target year.
The script also re-derives the whole hierarchy from the extended panel and join as a
diagnostic and records every field that would differ from the frozen rows. Metadata only: no
feature construction, fit or outcome column is read (the panel is read by column index for
``match_id``, ``a_source_id``, ``b_source_id`` and ``match_date``).
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path

D97_FIT_CUTOFF = "2023-12-30"
MATCH_FILE = re.compile(r"atp_matches_(\d{4})\.csv")
RANKING_FILE = re.compile(r"atp_rankings_[0-9a-z]+\.csv")
PANEL_COLUMNS = ("match_id", "a_source_id", "b_source_id", "match_date")


def sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def read_native(path: Path, digest: str) -> dict[str, dict]:
    """D97 raw rows of one native file, in D97 field order."""
    rows: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if not all(row.get(k) for k in ["winner_id", "loser_id", "tourney_date", "match_num"]):
                continue
            key = row["tourney_id"] + "/" + str(int(row["match_num"]))
            if key in rows:
                raise ValueError("duplicate native match ID: " + key)
            rows[key] = {
                "match_id": key,
                "event_id": row["tourney_id"],
                "event_name": row["tourney_name"],
                "anchor": dt.datetime.strptime(row["tourney_date"], "%Y%m%d").date().isoformat(),
                "source_year": int(path.stem[-4:]),
                "source_sha256": digest,
                "round": row["round"],
                "ids": sorted([row["winner_id"], row["loser_id"]]),
                "level": row["tourney_level"],
            }
    return rows


def read_panel(path: Path) -> dict[str, dict]:
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = [header.index(name) for name in PANEL_COLUMNS]
        panel: dict[str, dict] = {}
        for row in reader:
            values = dict(zip(PANEL_COLUMNS, (row[i] for i in index), strict=True))
            if values["match_id"] in panel:
                raise ValueError("duplicate panel match_id: " + values["match_id"])
            panel[values["match_id"]] = values
    return panel


def hierarchy(raw: dict[str, dict], panel: dict, panel_path: Path, join_path: Path, targets: set):
    """The D97 hierarchy over ``raw`` (project_date_hierarchy.py, unchanged logic)."""
    accepted = {}
    for key, row in panel.items():
        if key not in raw:
            continue
        if sorted([row["a_source_id"], row["b_source_id"]]) != raw[key]["ids"]:
            raise ValueError("accepted source identity conflict: " + key)
        accepted[key] = {
            "date": row["match_date"],
            "basis": "accepted_reported_date",
            "provenance": {"file": str(panel_path), "match_id": key},
        }
    q1 = collections.defaultdict(list)
    with join_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            key = row["archive_source_key"]
            if key not in raw or key in accepted:
                continue
            if row["classification"] != "candidate_q1_pinned_ch01":
                continue
            if (
                row["candidate_count"] == "1"
                and row["round_agreement"] == "true"
                and row["date_window_agreement"] == "true"
                and sorted([row["archive_a_source_id"], row["archive_b_source_id"]])
                == raw[key]["ids"]
                and row["archive_round"] == raw[key]["round"]
                and row["archive_tourney_id"] == raw[key]["event_id"]
                and row["archive_source_file_sha256"] == raw[key]["source_sha256"]
            ):
                q1[key].append(
                    {
                        "date": row["market_match_date"],
                        "basis": "promoted_q1_reported_date",
                        "provenance": {
                            "file": row["market_source_path"],
                            "sha256": row["market_source_sha256"],
                            "row": row["market_source_row"],
                            "classification": row["classification"],
                        },
                    }
                )
    for key, candidates in q1.items():
        if len(candidates) != 1:
            raise ValueError("nonunique Q1 date: " + key)
        accepted[key] = candidates[0]
    events = collections.defaultdict(list)
    for key, row in raw.items():
        events[(row["event_id"], row["anchor"])].append(key)
    flags = []
    plan = []
    for event, keys in sorted(events.items()):
        dated = [(key, accepted[key]["date"]) for key in keys if key in accepted]
        finals = [(key, date) for key, date in dated if raw[key]["round"] == "F"]
        latest = max((date for key, date in dated), default=event[1])
        final_date = max((date for key, date in finals), default=None)
        event_end = None
        if final_date is not None:
            if final_date >= event[1] and final_date >= latest:
                event_end = final_date
            else:
                flags.append(
                    {
                        "event_id": event[0],
                        "anchor": event[1],
                        "reason": "reported_final_precedes_anchor_or_later_known_event_row",
                        "final_date": final_date,
                        "latest_reported_date": latest,
                    }
                )
        assumed = (dt.date.fromisoformat(event[1]) + dt.timedelta(days=21)).isoformat()
        if latest > assumed:
            flags.append(
                {
                    "event_id": event[0],
                    "anchor": event[1],
                    "reason": "known_event_date_exceeds_21_day_assumption",
                    "latest_reported_date": latest,
                }
            )
        for key in keys:
            row = dict(raw[key])
            reported = accepted.get(key)
            if reported:
                target_date = reported["date"]
                release_date = target_date
                basis = reported["basis"]
                provenance = reported["provenance"]
            else:
                target_date = row["anchor"]
                release_date = event_end or max(assumed, latest)
                basis = (
                    "reported_event_final_batch_proxy"
                    if event_end
                    else "assumed_21_day_batch_proxy"
                )
                provenance = {
                    "event_id": event[0],
                    "anchor": event[1],
                    "reported_final_matches": [k for k, date in finals if date == event_end],
                    "latest_admitted_reported_date": latest,
                }
            row.update(
                target_date_proxy=target_date,
                available_date_proxy=release_date,
                eligible_through_date=(
                    dt.date.fromisoformat(target_date) - dt.timedelta(days=2)
                ).isoformat(),
                release_basis=basis,
                date_provenance=provenance,
                fit_target=target_date <= D97_FIT_CUTOFF
                and release_date <= D97_FIT_CUTOFF
                and key not in targets,
                evaluation_target=key in targets,
            )
            plan.append(row)
    plan.sort(key=lambda r: r["match_id"])
    return plan, flags


def serialize(plan: list[dict]) -> str:
    return json.dumps(plan, separators=(",", ":")) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frozen-plan", type=Path, required=True, help="D97 date_hierarchy_plan.json"
    )
    parser.add_argument("--frozen-native-raw", type=Path, required=True, help="D97 native_raw/")
    parser.add_argument("--new-native", type=Path, action="append", required=True)
    parser.add_argument(
        "--panel", type=Path, required=True, help="extended prepare_panel/panel.csv"
    )
    parser.add_argument(
        "--join-candidates",
        type=Path,
        required=True,
        help="extended join/common_panel_candidates.csv",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    native_dir = root / "native_raw"
    native_dir.mkdir()

    frozen_path = args.frozen_plan.resolve()
    frozen_bytes = frozen_path.read_bytes()
    frozen = json.loads(frozen_bytes)
    frozen_ids = [r["match_id"] for r in frozen]
    if frozen_ids != sorted(set(frozen_ids)):
        raise ValueError("frozen plan is not unique and in match_id order")
    if serialize(frozen).encode() != frozen_bytes:
        raise ValueError("frozen plan does not re-serialize to its own bytes")
    frozen_by_id = {r["match_id"]: r for r in frozen}
    frozen_targets = {r["match_id"] for r in frozen if r["evaluation_target"]}

    # Native files: the frozen run's files unchanged, plus the new files.
    copied = {}
    frozen_raw: dict[str, dict] = {}
    for path in sorted(args.frozen_native_raw.resolve().iterdir()):
        if not (MATCH_FILE.fullmatch(path.name) or RANKING_FILE.fullmatch(path.name)):
            continue
        destination = native_dir / path.name
        shutil.copyfile(path, destination)
        digest = sha(destination)
        if digest != sha(path):
            raise ValueError("copy differs from source: " + path.name)
        copied[path.name] = {"source": str(path), "sha256": digest, "role": "frozen_run_input"}
        if MATCH_FILE.fullmatch(path.name):
            frozen_raw.update(read_native(destination, digest))
    frozen_hashes = {r["source_sha256"] for r in frozen}
    frozen_match_hashes = {v["sha256"] for k, v in copied.items() if MATCH_FILE.fullmatch(k)}
    if frozen_hashes != frozen_match_hashes:
        raise ValueError("frozen native match files differ from the plan's source hashes")
    if set(frozen_raw) != set(frozen_by_id):
        raise ValueError("frozen native rows differ from the frozen plan rows")
    new_raw: dict[str, dict] = {}
    for path in args.new_native:
        path = path.resolve()
        if not MATCH_FILE.fullmatch(path.name):
            raise ValueError("new native file name must match atp_matches_YYYY.csv")
        destination = native_dir / path.name
        if destination.exists():
            raise ValueError("new native file replaces a frozen file: " + path.name)
        shutil.copyfile(path, destination)
        digest = sha(destination)
        copied[path.name] = {"source": str(path), "sha256": digest, "role": "new_native_file"}
        rows = read_native(destination, digest)
        overlap = set(rows) & (set(frozen_raw) | set(new_raw))
        if overlap:
            raise ValueError(
                "new native keys collide with existing keys: " + str(sorted(overlap)[:5])
            )
        new_raw.update(rows)
    frozen_events = {r["event_id"] for r in frozen}
    shared_events = sorted({r["event_id"] for r in new_raw.values()} & frozen_events)
    if shared_events:
        raise ValueError("new rows share an event with frozen rows: " + str(shared_events[:5]))

    # New rows by the D97 hierarchy; events never mix frozen and new rows (checked above).
    panel_path = args.panel.resolve()
    join_path = args.join_candidates.resolve()
    panel = read_panel(panel_path)
    new_rows, new_flags = hierarchy(new_raw, panel, panel_path, join_path, frozen_targets)
    if any(r["evaluation_target"] for r in new_rows):
        raise ValueError("a new row is a frozen evaluation target")
    extended = sorted(frozen + new_rows, key=lambda r: r["match_id"])
    kept = [r for r in extended if r["match_id"] in frozen_by_id]
    if serialize(kept).encode() != frozen_bytes:
        raise ValueError("frozen rows are not verbatim in the extended plan")
    plan_path = root / "date_hierarchy_plan.json"
    plan_path.write_text(serialize(extended))

    # Diagnostic: the whole hierarchy re-derived from the extended panel and join.
    rederived, all_flags = hierarchy(
        frozen_raw | new_raw, panel, panel_path, join_path, frozen_targets
    )
    rederived_by_id = {r["match_id"]: r for r in rederived}
    field_differences: collections.Counter = collections.Counter()
    provenance_path_only = 0
    examples: dict[str, list] = collections.defaultdict(list)
    for key, old in frozen_by_id.items():
        new = rederived_by_id[key]
        differing = [f for f in old if old[f] != new[f]]
        if differing == ["date_provenance"]:
            a, b = dict(old["date_provenance"]), dict(new["date_provenance"])
            if set(a) == set(b) == {"file", "match_id"} and a["match_id"] == b["match_id"]:
                provenance_path_only += 1
                continue
        for field in differing:
            field_differences[field] += 1
            if len(examples[field]) < 5:
                examples[field].append(
                    {"match_id": key, "frozen": old[field], "rederived": new[field]}
                )
    new_by_id = {r["match_id"]: r for r in new_rows}
    new_rows_differing = sum(new_by_id[k] != rederived_by_id[k] for k in new_by_id)

    panel_frozen_date_mismatch = sum(
        1
        for key, row in frozen_by_id.items()
        if row["release_basis"] == "accepted_reported_date"
        and (key not in panel or panel[key]["match_date"] != row["target_date_proxy"])
    )
    counts = collections.Counter(
        (r["source_year"], r["release_basis"], r["level"]) for r in new_rows
    )
    receipt = {
        "status": "metadata_only_no_candidate_scores",
        "tour": "atp",
        "procedure": "D97 date hierarchy (TMB/project_date_hierarchy.py) applied to new native rows only",
        "frozen_plan": {"path": str(frozen_path), "sha256": sha(frozen_path), "rows": len(frozen)},
        "extended_plan": {
            "path": str(plan_path),
            "sha256": sha(plan_path),
            "rows": len(extended),
            "frozen_rows_verbatim": len(kept),
            "new_rows": len(new_rows),
        },
        "new_rows": {
            "by_release_basis": dict(collections.Counter(r["release_basis"] for r in new_rows)),
            "by_level": dict(sorted(collections.Counter(r["level"] for r in new_rows).items())),
            "by_source_year_basis_level": [
                {"source_year": y, "release_basis": b, "level": lv, "rows": n}
                for (y, b, lv), n in sorted(counts.items())
            ],
            "target_date_range": [
                min(r["target_date_proxy"] for r in new_rows),
                max(r["target_date_proxy"] for r in new_rows),
            ],
            "events": len({(r["event_id"], r["anchor"]) for r in new_rows}),
            "date_flags": new_flags,
            "role_flags_under_d97_constants": {
                "fit_target": sum(r["fit_target"] for r in new_rows),
                "evaluation_target": sum(r["evaluation_target"] for r in new_rows),
            },
        },
        "rederivation_diagnostic": {
            "basis": "whole D97 hierarchy recomputed from the extended panel and join; frozen rows compared field by field",
            "frozen_rows_identical_except_panel_path_in_provenance": provenance_path_only,
            "frozen_rows_with_other_differences_by_field": dict(field_differences),
            "examples": dict(examples),
            "new_rows_differing_from_rederivation": new_rows_differing,
            "date_flags_total": len(all_flags),
            "frozen_accepted_rows_whose_panel_date_differs_or_is_missing": panel_frozen_date_mismatch,
        },
        "inputs": {
            "panel": {
                "path": str(panel_path),
                "sha256": sha(panel_path),
                "columns_read": list(PANEL_COLUMNS),
            },
            "join_candidates": {"path": str(join_path), "sha256": sha(join_path)},
            "native_files": copied,
        },
        "outputs": {str(p): sha(p) for p in sorted(root.rglob("*")) if p.is_file()},
    }
    (root / "EXTENSION_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {k: receipt[k] for k in ["extended_plan", "new_rows", "rederivation_diagnostic"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
