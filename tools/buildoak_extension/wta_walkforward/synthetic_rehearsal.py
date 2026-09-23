"""Generate synthetic WTA sources and exercise the walk-forward entry points end to end.

Builds a frozen-format WTA plan whose roles belong to a later frozen year, then runs
``prepare_year.py``, ``freeze_year.py``, the tour-agnostic ``../atp_walkforward/run_year.py``
launcher and ``map_orientation.py`` in fresh processes for an earlier target year. The
release schedule forces chronology replays, one event reuses another's keys (transport
IDs), the labels file carries an unparseable outcome column, and panel orientation is
mixed. Checks the commitment, the native WTA menu (global ensemble, Hard and level-I
specialists), recent-blend activation against the projection, replay receipts and the
orientation mapping. Synthetic only; no real row enters this rehearsal.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE.parent / "atp_walkforward" / "run_year.py"
IOCS = ["USA", "RUS", "FRA", "GER", "CZE", "ITA", "AUS", "ESP", "JPN", "SUI", "SVK", "BEL"]
LEVELS = ["I", "P", "I", "G", "W", "I", "PM", "D", "I", "P"]
SURFACES = ["Hard", "Clay", "Grass", "Hard", "Carpet"]
ROUNDS = [("QF", 0, 4), ("SF", 2, 2), ("F", 4, 1)]
STATS = ["ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_logged(command: list[str], root: Path, stem: str, timeout: int) -> None:
    with (
        (root / f"{stem}_stdout.log").open("x") as out,
        (root / f"{stem}_stderr.log").open("x") as err,
    ):
        process = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout
        )
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def match_row(rng, year, week, event, anchor, round_name, match_num, winner, loser, players):
    row = {
        "tourney_id": event["id"],
        "tourney_name": event["name"],
        "surface": event["surface"],
        "draw_size": 8,
        "tourney_level": event["level"],
        "tourney_date": anchor.strftime("%Y%m%d"),
        "match_num": match_num,
        "score": "6-4 6-3" if rng.random() < 0.7 else "7-6(4) 3-6 6-2",
        "best_of": 3,
        "round": round_name,
        "minutes": 80 + rng.randrange(60),
    }
    for role, player in [("winner", winner), ("loser", loser)]:
        row[f"{role}_id"] = player["id"]
        row[f"{role}_seed"] = ""
        row[f"{role}_entry"] = "Q" if rng.random() < 0.1 else ""
        row[f"{role}_name"] = player["name"]
        row[f"{role}_hand"] = player["hand"]
        row[f"{role}_ht"] = player["ht"]
        row[f"{role}_ioc"] = player["ioc"]
        row[f"{role}_age"] = round(year - player["born"] + week / 52, 1)
        row[f"{role}_rank"] = 1 + (player["id"] + week) % players
        row[f"{role}_rank_points"] = 5000 - 300 * row[f"{role}_rank"]
    for role, prefix in [("winner", "w"), ("loser", "l")]:
        svpt = 50 + rng.randrange(40)
        first_in = int(svpt * 0.6)
        values = {
            "ace": rng.randrange(8),
            "df": rng.randrange(6),
            "svpt": svpt,
            "1stIn": first_in,
            "1stWon": int(first_in * (0.7 if role == "winner" else 0.6)),
            "2ndWon": int((svpt - first_in) * 0.45),
            "SvGms": 9 + rng.randrange(4),
            "bpSaved": rng.randrange(5),
            "bpFaced": rng.randrange(8),
        }
        for stat in STATS:
            row[f"{prefix}_{stat}"] = values[stat]
    return row


def generate(output: Path, start_year: int, frozen_year: int, players: int) -> dict:
    """Native files, a frozen-format plan with frozen_year roles, and WTA01-shaped inputs."""
    rng = random.Random(20260923)
    native = output / "native_raw"
    native.mkdir()
    roster = [
        {
            "id": 200001 + index,
            "name": f"Synthetic Player {index + 1}",
            "hand": "L" if index % 5 == 4 else "R",
            "ht": 165 + index,
            "ioc": IOCS[index % len(IOCS)],
            "born": 1992 + (index % 6),
        }
        for index in range(players)
    ]
    plan = []
    for year in range(start_year, frozen_year + 1):
        rows = []
        events = []
        for event_index, week in enumerate(range(2, 41, 2)):
            events.append((event_index, week, f"{year}-S{event_index + 1:02d}"))
        # One reused historical key set: a second event with the first event's ID.
        if year == start_year + 1:
            events.append((len(events), 42, f"{year}-S01"))
        for event_index, week, event_id in events:
            anchor = dt.date.fromisocalendar(year, week, 1)
            # Every third event releases as a 21-day batch after the next event's reported
            # rows, so it arrives late and forces a chronology replay.
            batch = event_index % 3 == 0
            event = {
                "id": event_id,
                "name": f"Synthetic WTA Open {event_index + 1}",
                "surface": SURFACES[event_index % len(SURFACES)],
                "level": LEVELS[event_index % len(LEVELS)],
            }
            current = rng.sample(roster, 8)
            match_num = 0
            for round_name, offset, count in ROUNDS:
                advancing = []
                for pairing in [current[2 * i : 2 * i + 2] for i in range(count)]:
                    match_num += 1
                    strength = [p["id"] % 7 + rng.random() * 4 for p in pairing]
                    winner, loser = (
                        (pairing[0], pairing[1])
                        if strength[0] >= strength[1]
                        else (pairing[1], pairing[0])
                    )
                    advancing.append(winner)
                    row = match_row(
                        rng,
                        year,
                        week,
                        event,
                        anchor,
                        round_name,
                        match_num,
                        winner,
                        loser,
                        players,
                    )
                    rows.append(row)
                    if batch:
                        target_date = anchor.isoformat()
                        available = (anchor + dt.timedelta(days=21)).isoformat()
                        basis = "assumed_21_day_batch_proxy"
                    else:
                        target_date = (anchor + dt.timedelta(days=offset)).isoformat()
                        available = target_date
                        basis = "accepted_reported_date"
                    plan.append(
                        {
                            "match_id": f"{event_id}/{match_num}",
                            "event_id": event_id,
                            "event_name": event["name"],
                            "anchor": anchor.isoformat(),
                            "round": round_name,
                            "level": event["level"],
                            "surface": event["surface"],
                            "source_year": year,
                            "source_sha256": None,
                            "source_file": f"wta_matches_{year}.csv",
                            "source_line": len(rows) + 1,
                            "native_key": f"{event_id}/{match_num}",
                            "target_date_proxy": target_date,
                            "available_date_proxy": available,
                            "eligible_through_date": (
                                dt.date.fromisoformat(target_date) - dt.timedelta(days=2)
                            ).isoformat(),
                            "release_basis": basis,
                            "fit_target": False,
                            "evaluation_target": False,
                            "_ids": (winner["id"], loser["id"]),
                        }
                    )
                current = advancing
        path = native / f"wta_matches_{year}.csv"
        with path.open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        for row in plan:
            if row["source_year"] == year:
                row["source_sha256"] = digest(path)
    counts: dict[str, int] = {}
    for row in plan:
        counts[row["native_key"]] = counts.get(row["native_key"], 0) + 1
    for row in plan:
        if counts[row["native_key"]] > 1:
            row["match_id"] = f"{row['native_key']}@{row['source_file']}:{row['source_line']}"
    ids = {row["match_id"]: row.pop("_ids") for row in plan}
    # Primary targets per year: reported-date rows outside level D; every seventh is kept
    # as a provisional forecast row (primary_target 0), as the WTA01 selected files carry.
    primary: dict[int, list[str]] = {}
    provisional: dict[int, list[str]] = {}
    for index, row in enumerate(plan):
        if row["release_basis"] != "accepted_reported_date" or row["level"] == "D":
            continue
        bucket = provisional if index % 7 == 0 else primary
        bucket.setdefault(row["source_year"], []).append(row["match_id"])
    frozen_cutoff = f"{frozen_year - 1}-12-30"
    frozen_targets = set(primary[frozen_year])
    for row in plan:
        row["evaluation_target"] = row["match_id"] in frozen_targets
        row["fit_target"] = (
            row["target_date_proxy"] <= frozen_cutoff
            and row["available_date_proxy"] <= frozen_cutoff
            and not row["evaluation_target"]
        )
    plan.sort(key=lambda r: r["match_id"])
    frozen = output / "frozen_plan.json"
    frozen.write_text(json.dumps(plan, indent=2) + "\n")
    labels = output / "labels.csv"
    with labels.open("x", newline="") as handle:
        writer = csv.writer(handle)
        # The outcome column is deliberately unparseable: preparation must never read it.
        writer.writerow(["match_id", "calendar_year", "primary_target", "a_won"])
        for year in sorted(set(primary) | set(provisional)):
            for key in primary.get(year, []):
                writer.writerow([key, year, 1, "unread"])
            for key in provisional.get(year, []):
                writer.writerow([key, year, 0, "unread"])
    panel = output / "panel.csv"
    with panel.open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["match_id", "a_source_id", "b_source_id", "a_won"])
        for index, key in enumerate(sorted(ids)):
            low, high = sorted(ids[key])
            writer.writerow([key] + ([low, high] if index % 2 else [high, low]) + ["unread"])
    for year in sorted(primary):
        folder = output / "selected" / str(year)
        folder.mkdir(parents=True)
        selected = folder / "full.csv"
        with selected.open("x", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["season", "match_id", "p_a_wins"])
            for index, key in enumerate(sorted(primary[year] + provisional.get(year, []))):
                writer.writerow([year, key, f"{0.4 + 0.02 * (index % 10):.17g}"])
        cohort = sorted(primary[year])
        (folder / "full.json").write_text(
            json.dumps(
                {
                    "outer_primary_rows": len(cohort),
                    "outer_primary_membership_sha256": hashlib.sha256(
                        "".join(f"{year},{k}\n" for k in cohort).encode()
                    ).hexdigest(),
                    "selection_cutoff_inclusive": f"{year - 1}-12-30",
                    "selected_prediction_sha256": digest(selected),
                    "selected_candidate_id": "synthetic",
                },
                indent=2,
            )
            + "\n"
        )
    rankings = output / "rankings.csv"
    with rankings.open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ranking_date", "player", "rank", "points"])
        monday = dt.date.fromisocalendar(start_year, 1, 1)
        while monday <= dt.date(frozen_year, 12, 31):
            week = monday.isocalendar()[1]
            for player in roster:
                rank = 1 + (player["id"] + week) % players
                writer.writerow([monday.strftime("%Y%m%d"), player["id"], rank, 5000 - 300 * rank])
            monday += dt.timedelta(days=7)
    return {
        "native_rows": len(plan),
        "transport_ids": sum(1 for r in plan if "@" in r["match_id"]),
        "primary_rows": {str(y): len(v) for y, v in sorted(primary.items())},
        "frozen_plan": str(frozen),
        "native_raw": str(native),
        "rankings": str(rankings),
        "labels": str(labels),
        "panel": str(panel),
        "selected_root": str(output / "selected"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-context", default=None)
    parser.add_argument("--image-id", default=None)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--attempt-id", default="arms01-wta-synthetic-walkforward")
    parser.add_argument("--start-year", type=int, default=2013)
    parser.add_argument("--target-year", type=int, default=2018)
    parser.add_argument("--frozen-year", type=int, default=2019)
    parser.add_argument("--players", type=int, default=16)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--generate-only", action="store_true")
    args = parser.parse_args()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    sources = generate(output, args.start_year, args.frozen_year, args.players)
    (output / "SOURCES.json").write_text(json.dumps(sources, indent=2) + "\n")
    if args.generate_only:
        return
    if not (args.docker_context and args.image_id):
        raise SystemExit("--docker-context and --image-id are required unless --generate-only")
    year = args.target_year
    selected = Path(sources["selected_root"]) / str(year)
    attempt = output / "attempt"
    attempt.mkdir()
    run_logged(
        [
            args.python,
            str(HERE / "prepare_year.py"),
            "--year",
            str(year),
            "--frozen-plan",
            sources["frozen_plan"],
            "--native-raw",
            sources["native_raw"],
            "--rankings",
            sources["rankings"],
            "--selected",
            str(selected / "full.csv"),
            "--selection-json",
            str(selected / "full.json"),
            "--labels",
            sources["labels"],
            "--output",
            str(attempt / "preparation"),
        ],
        output,
        "prepare",
        300,
    )
    run_logged(
        [
            args.python,
            str(HERE / "freeze_year.py"),
            "--root",
            str(attempt),
            "--attempt-id",
            args.attempt_id,
            "--docker-context",
            args.docker_context,
            "--image-id",
            args.image_id,
            "--wall-seconds",
            "1800",
            "--cpu-seconds",
            "3600",
            "--cpus",
            "2",
            "--memory-gib",
            "4",
            "--scratch-gib",
            "2",
            "--synthetic-only",
        ],
        output,
        "freeze",
        300,
    )
    run_logged(
        [
            args.python,
            str(LAUNCHER),
            "--root",
            str(attempt),
            "--python",
            args.python,
            "--sample-seconds",
            "5",
        ],
        output,
        "run",
        1900,
    )
    mapped = attempt / "report" / "panel_orientation_forecasts.csv"
    run_logged(
        [
            args.python,
            str(HERE / "map_orientation.py"),
            "--run",
            str(attempt / "run"),
            "--verification",
            str(attempt / "verification.json"),
            "--membership",
            str(attempt / "preparation" / "target_membership.txt"),
            "--panel",
            sources["panel"],
            "--output",
            str(mapped),
        ],
        output,
        "map",
        300,
    )
    preparation = json.loads((attempt / "preparation" / "preparation.json").read_text())
    verification = json.loads((attempt / "verification.json").read_text())
    summary = json.loads((attempt / "REPLAY_SUMMARY.json").read_text())
    receipt = json.loads((attempt / "run" / "forecast" / "fit_receipt.json").read_text())
    mapping = json.loads((mapped.parent / "panel_orientation_forecasts_receipt.json").read_text())
    projected = preparation["fit_menu_projection"]
    if verification["status"] != "PASS":
        raise ValueError("read-only verification did not pass")
    members = {entry["member"] for entry in receipt["fit_menu"]}
    expected = {"global_component_01", "global_component_02", "segment_Hard", "segment_I"}
    if projected["recent_global"]["projected_active"]:
        expected |= {"recent_global_component_01", "recent_global_component_02"}
    if members != expected:
        raise ValueError(f"unexpected native WTA menu: {sorted(members)}")
    if (
        receipt["activation"]["temporal"]["active"]
        != projected["recent_global"]["projected_active"]
    ):
        raise ValueError("recent-blend activation differs from the projection")
    if receipt["activation"]["temporal"]["recent_rows"] != preparation["recent_rows"]:
        raise ValueError("recent rows differ from the projection")
    segments = {s["value"]: s["rows"] for s in receipt["activation"]["segments"]}
    if segments != {"Hard": projected["segment_Hard"]["rows"], "I": projected["segment_I"]["rows"]}:
        raise ValueError("specialist rows differ from the projection")
    if summary["chronology_replays"] < 1:
        raise ValueError("synthetic schedule produced no chronology replay")
    if (
        not summary["target_rows"]
        == preparation["target_rows"]
        == int(sources["primary_rows"][str(year)])
    ):
        raise ValueError("target membership drift")
    if preparation["state_only_rows"] < 1:
        raise ValueError("synthetic plan has no state-only rows")
    if not 0 < mapping["flipped_rows"] < mapping["rows"] == preparation["target_rows"]:
        raise ValueError("orientation mapping did not exercise both panel orientations")
    with (attempt / "run" / "forecast" / "native_forecasts.csv").open() as handle:
        forecasts = list(csv.DictReader(handle))
    membership = set((attempt / "preparation" / "target_membership.txt").read_text().split())
    if {r["match_id"] for r in forecasts} != membership:
        raise ValueError("forecast keys differ from the frozen target membership")
    result = {
        "status": "PASS",
        "synthetic_only": True,
        "tour": "wta",
        "target_year": year,
        "frozen_plan_year": args.frozen_year,
        "fit_cutoff": preparation["fit_cutoff"],
        "native_rows": preparation["native_rows"],
        "transport_id_rows": sources["transport_ids"],
        "fit_rows": preparation["fit_rows"],
        "target_rows": preparation["target_rows"],
        "state_only_rows": preparation["state_only_rows"],
        "excluded_non_primary_selected_rows": preparation["cohort_checks"][
            "excluded_non_primary_selected_rows"
        ],
        "fit_members": sorted(members),
        "segments": receipt["activation"]["segments"],
        "recent_blend": receipt["activation"]["temporal"],
        "chronology_replays": summary["chronology_replays"],
        "cutoff_batches": summary["cutoff_batches"],
        "projected_replays": preparation["replay_schedule"]["chronology_replays"],
        "projected_rows_replayed": preparation["replay_schedule"]["cumulative_rows_replayed"],
        "observed_rows_replayed": summary["cumulative_rows_replayed"],
        "mapped_rows": mapping["rows"],
        "mapped_flipped_rows": mapping["flipped_rows"],
        "verification": verification,
        "image_id": args.image_id,
        "wall_seconds": time.monotonic() - started,
    }
    if result["projected_replays"] != result["chronology_replays"]:
        raise ValueError("metadata projection and observed replay count differ")
    if result["projected_rows_replayed"] != result["observed_rows_replayed"]:
        raise ValueError("metadata projection and observed replayed rows differ")
    if result["cutoff_batches"] != preparation["replay_schedule"]["cutoff_batches"]:
        raise ValueError("metadata projection and observed cutoff batches differ")
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
