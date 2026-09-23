"""Generate WTA fixtures and exercise the real controller in fresh processes."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTROLLER = HERE / "empirical_controller.py"
VERIFIER = HERE / "verify_commitment.py"
BENCH_SCHEMA = HERE / "adapter" / "bench_schema.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(index: int, date: str) -> dict:
    winner = 1 if index % 2 else 2
    loser = 3 - winner
    row = {
        "tourney_id": f"SYNTHETIC-{index:05d}",
        "match_num": 1,
        "tourney_date": date.replace("-", ""),
        "tourney_name": "Synthetic WTA Open",
        "tourney_level": "I" if index % 3 == 0 else "W",
        "surface": "Hard" if index % 2 == 0 else "Clay",
        "round": "R32",
        "draw_size": 32,
        "best_of": 3,
        "score": "6-4 6-4",
        "minutes": 80,
    }
    for role, player in [("winner", winner), ("loser", loser)]:
        values = {
            "id": player,
            "name": f"Player {player}",
            "age": 25 + player,
            "ht": 170 + player,
            "seed": None,
            "rank": 10 * player,
            "rank_points": 1000 / player,
            "entry": "",
            "hand": "R",
            "ioc": "USA" if player == 1 else "GBR",
        }
        for key, value in values.items():
            row[f"{role}_{key}"] = value
    return row


def run_logged(command: list[str], stdout_path: Path, stderr_path: Path, timeout: int) -> None:
    with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
        process = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=timeout
        )
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker-context", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--attempt-id", default="buildoak-wta-synthetic-active-recent")
    parser.add_argument("--fit-rows", type=int, default=15000)
    args = parser.parse_args()
    if args.fit_rows < 15000:
        raise SystemExit("fit-rows must retain the native 15000-row recent activation threshold")
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "synthetic_wta.csv"
    plan_path = output / "date_hierarchy_plan.json"
    rows = []
    plan = []
    batch_size = 100
    source_line = 2
    for index in range(args.fit_rows):
        batch = index // batch_size
        date = (dt.date(2018, 1, 2) + dt.timedelta(days=7 * batch)).isoformat()
        row = fixture(index, date)
        rows.append(row)
        match_id = row["tourney_id"] + "/1"
        plan.append(
            {
                "match_id": match_id,
                "tour": "wta",
                "source_file": raw.name,
                "source_line": source_line,
                "target_date_proxy": date,
                "available_date_proxy": date,
                "eligible_through_date": (
                    dt.date.fromisoformat(date) - dt.timedelta(days=1)
                ).isoformat(),
                "fit_target": True,
                "evaluation_target": False,
            }
        )
        source_line += 1
    for offset, date in enumerate(["2024-01-05", "2024-01-20"], start=args.fit_rows):
        row = fixture(offset, date)
        rows.append(row)
        plan.append(
            {
                "match_id": row["tourney_id"] + "/1",
                "tour": "wta",
                "source_file": raw.name,
                "source_line": source_line,
                "target_date_proxy": date,
                "available_date_proxy": date,
                "eligible_through_date": (
                    dt.date.fromisoformat(date) - dt.timedelta(days=1)
                ).isoformat(),
                "fit_target": False,
                "evaluation_target": True,
            }
        )
        source_line += 1
    with raw.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    attempt = output / "attempt"
    auth = {
        "status": "AUTHORIZED_BUILDOAK_EXTENSION_FORECAST",
        "synthetic_only": True,
        "allowed_stages": ["features", "fit", "forecast"],
        "attempt_id": args.attempt_id,
        "output_directory": str(attempt),
        "plan_path": str(plan_path),
        "docker_context": args.docker_context,
        "tour": "wta",
        "wall_seconds": 1800,
        "cpu_seconds": 3600,
        "cpus": 4,
        "memory_bytes": 8 * 1024**3,
        "scratch_bytes": 4 * 1024**3,
        "feature_response_bytes": 64 * 1024**2,
        "fit_stdout_bytes": 96 * 1024**2,
        "fit_artifact_bytes": 64 * 1024**2,
        "image_id": args.image_id,
        "native_match_files": [str(raw)],
        "ranking_files": [],
        "fit_cutoff": "2023-12-30",
        "fit_rows": args.fit_rows,
        "target_rows": 2,
        "recent_rows": args.fit_rows,
        "ioc_buckets": ["USA", "GBR"],
    }
    bound = [CONTROLLER, BENCH_SCHEMA, plan_path, raw]
    auth["bindings"] = {str(path.resolve()): digest(path) for path in bound}
    authorization = output / "SYNTHETIC_AUTHORIZATION.json"
    authorization.write_text(json.dumps(auth, indent=2) + "\n")
    started = time.monotonic()
    run_logged(
        [sys.executable, str(CONTROLLER), str(authorization)],
        output / "controller_stdout.log",
        output / "controller_stderr.log",
        timeout=1860,
    )
    run_logged(
        [sys.executable, str(VERIFIER), str(attempt), str(authorization)],
        output / "verification.json",
        output / "verification_stderr.log",
        timeout=60,
    )
    verification = json.loads((output / "verification.json").read_text())
    receipt = json.loads((attempt / "forecast" / "fit_receipt.json").read_text())
    if not receipt["activation"]["temporal"]["active"]:
        raise ValueError("synthetic rehearsal did not activate native WTA recent model")
    expected_roles = [entry["role"] for entry in receipt["fit_menu"]]
    if expected_roles.count("full_global") != 2 or expected_roles.count("recent_global") != 2:
        raise ValueError("weighted WTA global/recent components not fully retained")
    if expected_roles.count("segment_specialist") != 2:
        raise ValueError("WTA Hard and I specialists not both retained")
    result = {
        "status": "PASS",
        "synthetic_only": True,
        "tour": "wta",
        "fit_rows": args.fit_rows,
        "native_threshold_unchanged": 15000,
        "fit_members": len(receipt["fit_menu"]),
        "verification": verification,
        "image_id": args.image_id,
        "wall_seconds": time.monotonic() - started,
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
