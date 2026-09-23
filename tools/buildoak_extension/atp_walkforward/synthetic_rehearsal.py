"""Generate synthetic ATP sources and exercise the walk-forward entry points end to end.

Runs ``prepare_year.py``, ``freeze_year.py`` and ``run_year.py`` in fresh processes on a
small synthetic history whose release schedule forces chronology replays, then checks the
commitment, the native ATP menu (global plus level-A specialist), the inactive recent
blend and the replay receipts. Synthetic only; no real row enters this rehearsal.
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
IOCS = ["USA", "ESP", "FRA", "GER", "ARG", "AUS", "SWE", "ITA", "RUS", "CZE", "NED", "SUI"]
LEVELS = ["A", "M", "A", "G", "A", "D", "A", "M", "A", "A", "G", "A", "F"]
SURFACES = ["Hard", "Clay", "Grass", "Hard"]
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


def match_row(rng, year, week, event, level, anchor, round_name, match_num, winner, loser, players):
    row = {
        "tourney_id": event["id"],
        "tourney_name": event["name"],
        "surface": event["surface"],
        "draw_size": 8,
        "tourney_level": level,
        "tourney_date": anchor.strftime("%Y%m%d"),
        "match_num": match_num,
        "score": "6-4 6-3" if rng.random() < 0.7 else "7-6(4) 3-6 6-2",
        "best_of": 5 if level == "G" else 3,
        "round": round_name,
        "minutes": 90 + rng.randrange(60),
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
        svpt = 60 + rng.randrange(40)
        first_in = int(svpt * 0.6)
        values = {
            "ace": rng.randrange(12),
            "df": rng.randrange(6),
            "svpt": svpt,
            "1stIn": first_in,
            "1stWon": int(first_in * (0.75 if role == "winner" else 0.65)),
            "2ndWon": int((svpt - first_in) * 0.5),
            "SvGms": 10 + rng.randrange(4),
            "bpSaved": rng.randrange(5),
            "bpFaced": rng.randrange(8),
        }
        for stat in STATS:
            row[f"{prefix}_{stat}"] = values[stat]
    return row


def plan_row(row, event, anchor, year, level, round_name, winner, loser, batch, offset):
    if batch:
        target_date = anchor.isoformat()
        available = (anchor + dt.timedelta(days=21)).isoformat()
        basis = "assumed_21_day_batch_proxy"
    else:
        target_date = (anchor + dt.timedelta(days=offset)).isoformat()
        available = target_date
        basis = "accepted_reported_date"
    return {
        "match_id": f"{event['id']}/{row['match_num']}",
        "event_id": event["id"],
        "event_name": event["name"],
        "anchor": anchor.isoformat(),
        "source_year": year,
        "source_sha256": None,
        "round": round_name,
        "ids": sorted([str(winner["id"]), str(loser["id"])]),
        "level": level,
        "target_date_proxy": target_date,
        "available_date_proxy": available,
        "eligible_through_date": (
            dt.date.fromisoformat(target_date) - dt.timedelta(days=2)
        ).isoformat(),
        "release_basis": basis,
        "date_provenance": {"synthetic": True, "event_id": event["id"]},
        "fit_target": False,
        "evaluation_target": False,
    }


def generate(output: Path, start_year: int, target_year: int, players: int) -> dict:
    rng = random.Random(20260922)
    native = output / "native_raw"
    native.mkdir()
    roster = [
        {
            "id": 100001 + index,
            "name": f"Synthetic Player {index + 1}",
            "hand": "L" if index % 4 == 3 else "R",
            "ht": 178 + index,
            "ioc": IOCS[index % len(IOCS)],
            "born": 1990 + (index % 6),
        }
        for index in range(players)
    ]
    plan_rows = []
    files = {}
    for year in range(start_year, target_year + 1):
        rows = []
        for event_index, week in enumerate(range(2, 41, 2)):
            anchor = dt.date.fromisocalendar(year, week, 1)
            level = LEVELS[event_index % len(LEVELS)]
            # Events are two weeks apart; every third event releases as a 21-day batch,
            # after the next event's reported rows, so it arrives late and forces a replay.
            batch = event_index % 3 == 0
            event = {
                "id": f"{year}-S{event_index + 1:02d}",
                "name": f"Synthetic Open {event_index + 1}",
                "surface": SURFACES[event_index % len(SURFACES)],
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
                        level,
                        anchor,
                        round_name,
                        match_num,
                        winner,
                        loser,
                        players,
                    )
                    rows.append(row)
                    plan_rows.append(
                        plan_row(
                            row,
                            event,
                            anchor,
                            year,
                            level,
                            round_name,
                            winner,
                            loser,
                            batch,
                            offset,
                        )
                    )
                current = advancing
        path = native / f"atp_matches_{year}.csv"
        with path.open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        files[year] = digest(path)
    cutoff = f"{target_year - 1}-12-30"
    cohort = []
    for row in plan_rows:
        row["source_sha256"] = files[row["source_year"]]
        eligible = row["source_year"] == target_year and row["level"] != "D"
        row["evaluation_target"] = eligible and row["release_basis"] == "accepted_reported_date"
        row["fit_target"] = (
            row["target_date_proxy"] <= cutoff
            and row["available_date_proxy"] <= cutoff
            and not row["evaluation_target"]
        )
        if row["evaluation_target"]:
            cohort.append(row)
    plan_rows.sort(key=lambda r: r["match_id"])
    frozen = output / "frozen_plan.json"
    frozen.write_text(json.dumps(plan_rows, separators=(",", ":")) + "\n")
    carrier = output / "cohort_predictions.csv"
    with carrier.open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "tour",
                "year",
                "match_id",
                "match_date",
                "tournament_week",
                "raw_incumbent",
                "calibrated_incumbent",
            ]
        )
        for index, row in enumerate(cohort):
            iso = dt.date.fromisoformat(row["target_date_proxy"]).isocalendar()
            p = f"{0.4 + 0.02 * (index % 10):.17g}"
            writer.writerow(
                [
                    "ATP",
                    target_year,
                    row["match_id"],
                    row["target_date_proxy"],
                    f"{iso[0]}-W{iso[1]:02d}",
                    p,
                    p,
                ]
            )
    selected = output / "full_tier.csv"
    with selected.open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["season", "match_id", "p_a_wins"])
        for index, row in enumerate(cohort):
            writer.writerow([target_year, row["match_id"], f"{0.4 + 0.02 * (index % 10):.17g}"])
        # One provisional forecast row outside the cohort, as the real full_tier files carry.
        writer.writerow([target_year, f"{target_year}-S99/1", "0.5"])
    selection = output / "full_tier.json"
    selection.write_text(json.dumps({"outer_primary_rows": len(cohort), "synthetic": True}) + "\n")
    rankings = output / "rankings.csv"
    with rankings.open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ranking_date", "player", "rank", "points"])
        monday = dt.date.fromisocalendar(start_year, 1, 1)
        end = dt.date(target_year, 12, 31)
        while monday <= end:
            week = monday.isocalendar()[1]
            for player in roster:
                rank = 1 + (player["id"] + week) % players
                writer.writerow([monday.strftime("%Y%m%d"), player["id"], rank, 5000 - 300 * rank])
            monday += dt.timedelta(days=7)
    return {
        "native_rows": len(plan_rows),
        "cohort_rows": len(cohort),
        "years": [start_year, target_year],
        "frozen_plan": str(frozen),
        "native_raw": str(native),
        "rankings": str(rankings),
        "cohort": str(carrier),
        "selected": str(selected),
        "selection_json": str(selection),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-context", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--attempt-id", default="arms01-atp-synthetic-walkforward")
    parser.add_argument("--start-year", type=int, default=2013)
    parser.add_argument("--target-year", type=int, default=2018)
    parser.add_argument("--players", type=int, default=16)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    sources = generate(output, args.start_year, args.target_year, args.players)
    attempt = output / "attempt"
    attempt.mkdir()
    run_logged(
        [
            args.python,
            str(HERE / "prepare_year.py"),
            "--year",
            str(args.target_year),
            "--frozen-plan",
            sources["frozen_plan"],
            "--native-raw",
            sources["native_raw"],
            "--rankings",
            sources["rankings"],
            "--cohort",
            sources["cohort"],
            "--alcaraz-selected",
            sources["selected"],
            "--selection-json",
            sources["selection_json"],
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
            str(HERE / "run_year.py"),
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
    preparation = json.loads((attempt / "preparation" / "preparation.json").read_text())
    verification = json.loads((attempt / "verification.json").read_text())
    summary = json.loads((attempt / "REPLAY_SUMMARY.json").read_text())
    receipt = json.loads((attempt / "run" / "forecast" / "fit_receipt.json").read_text())
    if verification["status"] != "PASS":
        raise ValueError("read-only verification did not pass")
    members = {entry["member"] for entry in receipt["fit_menu"]}
    if members != {"global", "segment_A"}:
        raise ValueError(f"unexpected native ATP menu: {sorted(members)}")
    if receipt["activation"]["temporal"]["active"]:
        raise ValueError("recent blend activated on a history that ends before its start")
    if summary["chronology_replays"] < 1:
        raise ValueError("synthetic schedule produced no chronology replay")
    if not summary["target_rows"] == preparation["target_rows"] == sources["cohort_rows"]:
        raise ValueError("target membership drift")
    if preparation["state_only_rows"] < 1:
        raise ValueError("synthetic plan has no state-only rows")
    with (attempt / "run" / "forecast" / "native_forecasts.csv").open() as handle:
        forecasts = list(csv.DictReader(handle))
    membership = set((attempt / "preparation" / "target_membership.txt").read_text().split())
    if {r["match_id"] for r in forecasts} != membership:
        raise ValueError("forecast keys differ from the frozen target membership")
    result = {
        "status": "PASS",
        "synthetic_only": True,
        "tour": "atp",
        "target_year": args.target_year,
        "fit_cutoff": preparation["fit_cutoff"],
        "native_rows": preparation["native_rows"],
        "fit_rows": preparation["fit_rows"],
        "target_rows": preparation["target_rows"],
        "state_only_rows": preparation["state_only_rows"],
        "fit_members": sorted(members),
        "recent_blend": receipt["activation"]["temporal"],
        "chronology_replays": summary["chronology_replays"],
        "cutoff_batches": summary["cutoff_batches"],
        "projected_replays": preparation["replay_schedule"]["chronology_replays"],
        "projected_rows_replayed": preparation["replay_schedule"]["cumulative_rows_replayed"],
        "observed_rows_replayed": summary["cumulative_rows_replayed"],
        "verification": verification,
        "image_id": args.image_id,
        "wall_seconds": time.monotonic() - started,
    }
    if result["projected_replays"] != result["chronology_replays"]:
        raise ValueError("metadata projection and observed replay count differ")
    if result["projected_rows_replayed"] != result["observed_rows_replayed"]:
        raise ValueError("metadata projection and observed replayed rows differ")
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
