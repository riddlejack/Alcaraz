"""Extend the frozen WTA extension plan with the rows of later native match files.

Every frozen row is kept verbatim. Rows of the new native files are dated by the frozen WTA
preparation's hierarchy (``tools/buildoak_extension/prepare.py``): the accepted panel's reported
date when the panel identity agrees, else the event anchor released at the reported final or at
anchor + 21 days. New rows carry the frozen plan's role flags under its constants (fit boundary
2023-12-30, 2024 targets), which ``prepare_year.py`` recomputes per target year. A new native key
that duplicates any existing key is refused, because a transport ID would then change a frozen
row. The script also re-derives the whole hierarchy from the extended panel as a diagnostic.
Metadata only: the panel is read by column index for ``match_id``, ``a_source_id``,
``b_source_id`` and ``match_date``; no outcome column is kept.
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

FROZEN_FIT_CUTOFF = "2023-12-30"
MATCH_FILE = re.compile(r"wta_matches_(\d{4})\.csv")
RANKING_FILE = re.compile(r"wta_rankings_[0-9a-z]+\.csv")
PANEL_COLUMNS = ("match_id", "a_source_id", "b_source_id", "match_date")


def sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def save_text(plan: list[dict]) -> str:
    # The frozen WTA preparation's serialization (prepare.py ``save``).
    return json.dumps(plan, indent=2, allow_nan=False) + "\n"


def read_native(paths: list[Path]) -> list[dict]:
    source_rows = []
    for p in paths:
        source_hash = sha(p)
        with p.open(encoding="utf-8-sig") as handle:
            for line, r in enumerate(csv.DictReader(handle), 2):
                if not all(
                    r.get(k) for k in ["winner_id", "loser_id", "tourney_date", "match_num"]
                ):
                    continue
                key = r["tourney_id"] + "/" + str(int(r["match_num"]))
                r.update(
                    native_key=key,
                    source_year=int(p.stem[-4:]),
                    source_sha256=source_hash,
                    sequence=len(source_rows),
                    source_file=p.name,
                    source_line=line,
                )
                source_rows.append(r)
    return source_rows


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


def hierarchy(raw: dict[str, dict], panel: dict, targets: set):
    """The frozen WTA hierarchy over ``raw`` (prepare.py, unchanged logic)."""
    accepted = {}
    mismatches = []
    for k, p in panel.items():
        if k not in raw:
            continue
        n = raw[k]
        if sorted([p["a_source_id"], p["b_source_id"]]) != sorted([n["winner_id"], n["loser_id"]]):
            mismatches.append(k)
            continue
        accepted[k] = p["match_date"]
    events = collections.defaultdict(list)
    for k, n in raw.items():
        anchor = dt.datetime.strptime(n["tourney_date"], "%Y%m%d").date().isoformat()
        n["anchor"] = anchor
        events[(n["tourney_id"], anchor)].append(k)
    plan = []
    flags = []
    for (event, anchor), keys in sorted(events.items()):
        dated = [(k, accepted[k]) for k in keys if k in accepted]
        latest = max((d for k, d in dated), default=anchor)
        finals = [(k, d) for k, d in dated if raw[k]["round"] == "F"]
        final = max((d for k, d in finals), default=None)
        end = final if final and final >= max(anchor, latest) else None
        assumed = (dt.date.fromisoformat(anchor) + dt.timedelta(days=21)).isoformat()
        if (final and not end) or latest > assumed:
            flags.append({"event": event, "anchor": anchor, "final": final, "latest": latest})
        for k in keys:
            n = raw[k]
            date = accepted.get(k, anchor)
            release = date if k in accepted else end or max(assumed, latest)
            basis = (
                "accepted_reported_date"
                if k in accepted
                else "reported_event_final_batch_proxy"
                if end
                else "assumed_21_day_batch_proxy"
            )
            plan.append(
                {
                    "match_id": k,
                    "event_id": event,
                    "event_name": n["tourney_name"],
                    "anchor": anchor,
                    "round": n["round"],
                    "level": n["tourney_level"],
                    "surface": n["surface"] or "Unknown",
                    "source_year": n["source_year"],
                    "source_sha256": n["source_sha256"],
                    "source_file": n["source_file"],
                    "source_line": n["source_line"],
                    "native_key": n["native_key"],
                    "target_date_proxy": date,
                    "available_date_proxy": release,
                    "eligible_through_date": (
                        dt.date.fromisoformat(date) - dt.timedelta(days=2)
                    ).isoformat(),
                    "release_basis": basis,
                    "fit_target": date <= FROZEN_FIT_CUTOFF
                    and release <= FROZEN_FIT_CUTOFF
                    and k not in targets,
                    "evaluation_target": k in targets,
                }
            )
    plan.sort(key=lambda r: r["match_id"])
    return plan, flags, mismatches


def keyed(source_rows: list[dict]) -> dict[str, dict]:
    """Transport IDs for duplicate native keys, as the frozen preparation assigns them."""
    frequencies = collections.Counter(r["native_key"] for r in source_rows)
    raw = {}
    for r in source_rows:
        key = r["native_key"]
        if frequencies[key] > 1:
            key += "@" + r["source_file"] + ":" + str(r["source_line"])
        r["match_id"] = key
        raw[key] = r
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-plan", type=Path, required=True)
    parser.add_argument("--frozen-native-raw", type=Path, required=True)
    parser.add_argument("--new-native", type=Path, action="append", required=True)
    parser.add_argument(
        "--panel", type=Path, required=True, help="extended prepare_panel/panel.csv"
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
    if save_text(frozen).encode() != frozen_bytes:
        raise ValueError("frozen plan does not re-serialize to its own bytes")
    frozen_by_id = {r["match_id"]: r for r in frozen}
    frozen_targets = {r["match_id"] for r in frozen if r["evaluation_target"]}

    copied = {}
    frozen_files = []
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
            frozen_files.append(destination)
    new_files = []
    for path in args.new_native:
        path = path.resolve()
        if not MATCH_FILE.fullmatch(path.name):
            raise ValueError("new native file name must match wta_matches_YYYY.csv")
        destination = native_dir / path.name
        if destination.exists():
            raise ValueError("new native file replaces a frozen file: " + path.name)
        shutil.copyfile(path, destination)
        copied[path.name] = {
            "source": str(path),
            "sha256": sha(destination),
            "role": "new_native_file",
        }
        new_files.append(destination)

    frozen_source = read_native(sorted(frozen_files))
    if {r["source_sha256"] for r in frozen_source} != {r["source_sha256"] for r in frozen}:
        raise ValueError("frozen native match files differ from the plan's source hashes")
    all_source = read_native(sorted(frozen_files + new_files))
    frozen_keys = collections.Counter(r["native_key"] for r in frozen_source)
    new_source = [r for r in all_source if r["source_file"] in {p.name for p in new_files}]
    new_keys = collections.Counter(r["native_key"] for r in new_source)
    duplicated = sorted(k for k in new_keys if new_keys[k] > 1 or k in frozen_keys)
    if duplicated:
        raise ValueError("new native keys duplicate existing keys: " + str(duplicated[:5]))
    raw_all = keyed(all_source)
    frozen_raw = {
        k: v for k, v in raw_all.items() if v["source_file"] not in {p.name for p in new_files}
    }
    new_raw = {k: v for k, v in raw_all.items() if k not in frozen_raw}
    if set(frozen_raw) != set(frozen_by_id):
        raise ValueError("frozen native rows differ from the frozen plan rows")
    shared_events = sorted(
        {r["tourney_id"] for r in new_raw.values()} & {r["event_id"] for r in frozen}
    )
    if shared_events:
        raise ValueError("new rows share an event with frozen rows: " + str(shared_events[:5]))

    panel_path = args.panel.resolve()
    panel = read_panel(panel_path)
    new_rows, new_flags, new_mismatches = hierarchy(new_raw, panel, frozen_targets)
    if any(r["evaluation_target"] for r in new_rows):
        raise ValueError("a new row is a frozen evaluation target")
    extended = sorted(frozen + new_rows, key=lambda r: r["match_id"])
    kept = [r for r in extended if r["match_id"] in frozen_by_id]
    if save_text(kept).encode() != frozen_bytes:
        raise ValueError("frozen rows are not verbatim in the extended plan")
    plan_path = root / "date_hierarchy_plan.json"
    plan_path.write_text(save_text(extended))

    # Diagnostic: the whole hierarchy re-derived from the extended panel.
    rederived, all_flags, all_mismatches = hierarchy(raw_all, panel, frozen_targets)
    rederived_by_id = {r["match_id"]: r for r in rederived}
    field_differences: collections.Counter = collections.Counter()
    examples: dict[str, list] = collections.defaultdict(list)
    for key, old in frozen_by_id.items():
        new = rederived_by_id[key]
        for field in [f for f in old if old[f] != new[f]]:
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
        "tour": "wta",
        "procedure": "frozen WTA hierarchy (tools/buildoak_extension/prepare.py) applied to new native rows only",
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
            "by_surface": dict(sorted(collections.Counter(r["surface"] for r in new_rows).items())),
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
            "identity_mismatches_not_promoted": new_mismatches,
            "transport_ids": sorted(k for k in new_by_id if "@" in k),
            "role_flags_under_frozen_constants": {
                "fit_target": sum(r["fit_target"] for r in new_rows),
                "evaluation_target": sum(r["evaluation_target"] for r in new_rows),
            },
        },
        "rederivation_diagnostic": {
            "basis": "whole frozen WTA hierarchy recomputed from the extended panel; frozen rows compared field by field",
            "frozen_rows_with_differences_by_field": dict(field_differences),
            "examples": dict(examples),
            "new_rows_differing_from_rederivation": new_rows_differing,
            "date_flags_total": len(all_flags),
            "identity_mismatches_total": len(all_mismatches),
            "frozen_accepted_rows_whose_panel_date_differs_or_is_missing": panel_frozen_date_mismatch,
        },
        "inputs": {
            "panel": {
                "path": str(panel_path),
                "sha256": sha(panel_path),
                "columns_read": list(PANEL_COLUMNS),
            },
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
