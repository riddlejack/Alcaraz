"""Metadata-only WTA 2024 preparation; no feature fits or target scores."""

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import tarfile
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--g-predictions", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    native = root / "native_raw"
    native.mkdir()
    archive = args.archive.resolve()
    tar = (
        archive
        / "data/raw/ARCHIVE01/snapshot/tennis-sackmann-archive-83733587353df8a41f2fd4f516147d5aa83f5a8d.tar.gz"
    )
    source_receipt = {"archive": str(tar), "sha256": sha(tar), "members": {}}
    with tarfile.open(tar) as tf:
        for member in tf:
            name = Path(member.name).name
            selected = name.startswith("wta_rankings_") and name.endswith(".csv")
            selected |= (
                bool(re.fullmatch(r"wta_matches_\d{4}\.csv", name))
                and 1985 <= int(name[-8:-4]) <= 2024
            )
            if not member.isfile() or not selected:
                continue
            dest = native / name
            if dest.exists():
                raise ValueError("duplicate source member")
            dest.write_bytes(tf.extractfile(member).read())
            source_receipt["members"][name] = {
                "tar_member": member.name,
                "sha256": sha(dest),
                "bytes": dest.stat().st_size,
            }
    raw = {}
    source_rows = []
    for p in sorted(native.glob("wta_matches_*.csv")):
        source_hash = sha(p)
        for line, r in enumerate(csv.DictReader(p.open(encoding="utf-8-sig")), 2):
            if not all(r.get(k) for k in ["winner_id", "loser_id", "tourney_date", "match_num"]):
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
    frequencies = collections.Counter(r["native_key"] for r in source_rows)
    duplicates = {k: n for k, n in frequencies.items() if n > 1}
    for r in source_rows:
        key = r["native_key"]
        if frequencies[key] > 1:
            key += "@" + r["source_file"] + ":" + str(r["source_line"])
        r["match_id"] = key
        raw[key] = r
    run = archive / "experiments/runs/WTA01/attempt_001/primary/run"
    panel_path = run / "prepare_panel/panel.csv"
    panel = {r["match_id"]: r for r in csv.DictReader(panel_path.open())}
    g = {
        r["match_id"]: r
        for r in csv.DictReader(args.g_predictions.open())
        if r["tour"] == "WTA" and r["year"] == "2024"
    }
    selected_path = run / "pipeline/selected/2024/hgb/full.csv"
    selected = {r["match_id"]: r for r in csv.DictReader(selected_path.open())}
    selection_path = run / "pipeline/selection/2024/hgb/full.json"
    selection = json.loads(selection_path.read_text())
    assert selection["selection_cutoff_inclusive"] == "2023-12-30"
    assert selection["outer_primary_rows"] == len(g) == 2404
    assert selection["selected_prediction_sha256"] == sha(selected_path)
    assert all(
        g[k]["calibrated_incumbent"] == selected[k]["p_a_wins"] == g[k]["raw_incumbent"] for k in g
    )
    assert set(g) <= set(raw) & set(panel)
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
    assert not set(g).intersection(mismatches)
    assert all(accepted[k] == g[k]["match_date"] for k in g)
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
                    "fit_target": date <= "2023-12-30" and release <= "2023-12-30" and k not in g,
                    "evaluation_target": k in g,
                }
            )
    plan.sort(key=lambda r: r["match_id"])
    save(root / "date_hierarchy_plan.json", plan)
    fit = [r for r in plan if r["fit_target"]]
    target = [r for r in plan if r["evaluation_target"]]
    for name, rows in [("fit", fit), ("target", target)]:
        (root / (name + "_membership.txt")).write_text(
            "\n".join(sorted(r["match_id"] for r in rows)) + "\n"
        )
    # Native top-10 IOC buckets, fit rows only; deterministic tie order uses the native chronological ordering.
    round_order = {"RR": 0, "R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7}

    def order(p):
        n = raw[p["match_id"]]
        return (
            p["target_date_proxy"],
            p["event_name"],
            round_order.get(p["round"], 0),
            int(n["match_num"]),
            n.get("winner_name", ""),
            n.get("loser_name", ""),
            n["sequence"],
        )

    ordered_fit = sorted(fit, key=order)
    iocs = collections.Counter()
    for side in ["winner", "loser"]:
        for r in ordered_fit:
            v = raw[r["match_id"]].get(side + "_ioc", "").strip().upper()
            if v:
                iocs[v] += 1
    vocabulary = [k for k, n in iocs.most_common(10)]
    save(
        root / "ioc_vocabulary.json",
        {"vocabulary": vocabulary, "counts": iocs, "basis": "fit-membership-only native IOC count"},
    )
    tasks = sorted(
        {r["eligible_through_date"] for r in plan if r["fit_target"] or r["evaluation_target"]}
    )
    releases = sorted(plan, key=lambda r: (r["available_date_proxy"], r["match_id"]))
    cursor = 0
    latest = None
    replay_rows = 0
    replay_batches = 0
    for cutoff in tasks:
        incoming = []
        while cursor < len(releases) and releases[cursor]["available_date_proxy"] <= cutoff:
            incoming.append(releases[cursor])
            cursor += 1
        incoming.sort(key=order)
        if incoming:
            if latest is not None and order(incoming[0]) < latest:
                replay_batches += 1
                replay_rows += cursor
            latest = max([order(r) for r in incoming] + ([latest] if latest else []))
    # Native ranking order and lowest-rank dedup, using task-specific SQLite spool.
    conn = sqlite3.connect(root / "ranking_sort.sqlite")
    conn.execute(
        "CREATE TABLE ranking(day INTEGER, player INTEGER, rank REAL, points REAL, PRIMARY KEY(day,player)) WITHOUT ROWID"
    )
    sql = "INSERT INTO ranking VALUES (?,?,?,?) ON CONFLICT(day,player) DO UPDATE SET rank=excluded.rank,points=excluded.points WHERE excluded.rank<ranking.rank"
    counts = collections.Counter()
    maximum = int(tasks[-1].replace("-", ""))
    for p in sorted(native.glob("wta_rankings_*.csv")):
        batch = []
        for r in csv.DictReader(p.open()):
            counts["input_rows"] += 1
            try:
                day = int(r["ranking_date"])
                dt.datetime.strptime(str(day), "%Y%m%d")
                player = int(r["player"])
                rank = float(r["rank"])
                if not math.isfinite(rank):
                    raise ValueError("nonfinite rank")
            except ValueError, TypeError, KeyError:
                counts["invalid_rows"] += 1
                continue
            if not 19840101 <= day <= maximum:
                counts["excluded_dates"] += 1
                continue
            try:
                points = float(r.get("points", ""))
                if not math.isfinite(points):
                    points = None
            except ValueError, TypeError:
                points = None
            batch.append((day, player, rank, points))
            counts["eligible_rows"] += 1
            if len(batch) == 10000:
                conn.executemany(sql, batch)
                batch = []
        conn.executemany(sql, batch)
    conn.commit()
    with (root / "rankings.csv").open("w") as f:
        w = csv.writer(f)
        w.writerow(["ranking_date", "player", "rank", "points"])
        w.writerows(conn.execute("SELECT day,player,rank,points FROM ranking ORDER BY day,player"))
    counts["output_rows"] = conn.execute("SELECT COUNT(*) FROM ranking").fetchone()[0]
    conn.close()
    sources = [
        tar,
        panel_path,
        args.g_predictions,
        selected_path,
        selection_path,
        run / "features/labels.csv",
    ]
    receipt = {
        "cohort": "WTA2024",
        "source_rows": len(plan),
        "fit_rows": len(fit),
        "target_rows": len(target),
        "fit_cutoff": "2023-12-30",
        "recent_rows": sum(r["target_date_proxy"] >= "2017-01-01" for r in fit),
        "fit_surface_counts": dict(collections.Counter(r["surface"] for r in fit)),
        "fit_level_counts": dict(collections.Counter(r["level"] for r in fit)),
        "date_basis_counts": dict(collections.Counter(r["release_basis"] for r in plan)),
        "duplicate_native_keys_preserved_with_transport_ids": duplicates,
        "non_target_identity_mismatches_not_promoted": mismatches,
        "date_flags": flags,
        "selection": {
            "candidate": selection["selected_candidate_id"],
            "slope": selection["selected_slope"],
            "years": selection["selection_years"],
        },
        "ranking_counts": dict(counts),
        "replay_schedule": {
            "cutoff_batches": len(tasks),
            "replay_batches": replay_batches,
            "cumulative_rows": replay_rows,
        },
        "report_inputs": {
            "g_predictions": str(args.g_predictions),
            "panel": str(panel_path),
            "labels": str(run / "features/labels.csv"),
        },
        "sources": {str(p): sha(p) for p in sources},
        "output_bindings": {str(p): sha(p) for p in root.glob("*") if p.is_file()},
        "target_exclusions": {
            "provisional_selected_rows": len(selected) - len(g),
            "extra_native_rows_outside_qualified_population": sum(
                r["source_year"] == 2024 and not r["evaluation_target"] for r in plan
            ),
        },
        "status": "metadata_only_no_candidate_scores",
    }
    save(root / "native_source_receipt.json", source_receipt)
    save(root / "preparation.json", receipt)
    print(
        json.dumps(
            {
                k: v
                for k, v in receipt.items()
                if k not in ["sources", "output_bindings", "report_inputs"]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
