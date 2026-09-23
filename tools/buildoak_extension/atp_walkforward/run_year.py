"""Launch one frozen ATP walk-forward attempt in a fresh process and summarize it.

Runs the unchanged extension controller under ``caffeinate -i`` with exclusive log files,
samples container CPU/memory while it runs, then executes the read-only commitment
verifier. It never opens target outcomes and never scores.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTROLLER = HERE.parent / "runtime" / "empirical_controller.py"
VERIFIER = HERE.parent / "runtime" / "verify_commitment.py"
UNITS = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "KB": 1e3, "MB": 1e6, "GB": 1e9}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def parse_bytes(text: str) -> float:
    match = re.fullmatch(r"\s*([0-9.]+)\s*([A-Za-z]+)\s*", text)
    if not match:
        return float("nan")
    return float(match.group(1)) * UNITS.get(match.group(2).upper(), float("nan"))


class Sampler(threading.Thread):
    """Poll ``docker stats`` for this attempt's containers; one host thread, no VM cost."""

    def __init__(self, base: list[str], prefix: str, path: Path, interval: float) -> None:
        super().__init__(daemon=True)
        self.base = base
        self.prefix = prefix
        self.path = path
        self.interval = interval
        self.stop = threading.Event()
        self.peak: dict[str, float] = {}
        self.cpu_seconds: dict[str, float] = {}
        self.samples = 0

    def run(self) -> None:
        last = time.monotonic()
        with self.path.open("x") as handle:
            while not self.stop.is_set():
                try:
                    out = subprocess.run(
                        self.base + ["stats", "--no-stream", "--format", "{{json .}}"],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    ).stdout
                except subprocess.SubprocessError, OSError:
                    out = ""
                elapsed = time.monotonic() - last
                last = time.monotonic()
                stamp = now()
                for line in out.splitlines():
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    name = row.get("Name", "")
                    if not name.startswith(self.prefix):
                        continue
                    cpu = float(str(row.get("CPUPerc", "0%")).rstrip("%") or 0) / 100
                    memory = parse_bytes(str(row.get("MemUsage", "")).split("/")[0])
                    self.peak[name] = max(self.peak.get(name, 0.0), memory)
                    self.cpu_seconds[name] = self.cpu_seconds.get(name, 0.0) + cpu * elapsed
                    self.samples += 1
                    handle.write(
                        json.dumps(
                            {
                                "utc": stamp,
                                "container": name,
                                "cpu_fraction": cpu,
                                "memory_bytes": memory,
                            }
                        )
                        + "\n"
                    )
                handle.flush()
                self.stop.wait(self.interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="attempt directory")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--no-caffeinate", action="store_true")
    parser.add_argument("--sample-seconds", type=float, default=20.0)
    args = parser.parse_args()
    root = args.root.resolve()
    authorization = root / "AUTHORIZATION.json"
    auth = json.loads(authorization.read_text())
    if (root / "LAUNCH.json").exists() or Path(auth["output_directory"]).exists():
        raise SystemExit("attempt already launched; use a fresh attempt directory")
    if auth["output_directory"] != str(root / "run"):
        raise SystemExit("authorization output directory must be ROOT/run")
    command = [args.python, str(CONTROLLER), str(authorization)]
    caffeinate = shutil.which("caffeinate")
    if caffeinate and not args.no_caffeinate:
        command = [caffeinate, "-i"] + command
    base = ["docker", "--context", auth["docker_context"]]
    started = time.monotonic()
    with (
        (root / "controller_stdout.log").open("xb") as out,
        (root / "controller_stderr.log").open("xb") as err,
    ):
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=out, stderr=err, cwd=root, close_fds=True
        )
        launch = {
            "status": "producer_launched",
            "attempt_id": auth["attempt_id"],
            "target_year": auth.get("walkforward", {}).get("target_year"),
            "authorization_sha256": digest(authorization),
            "controller_sha256": digest(CONTROLLER),
            "python": args.python,
            "python_version": subprocess.check_output(
                [args.python, "--version"], text=True
            ).strip(),
            "launcher_pid": os.getpid(),
            "producer_pid": process.pid,
            "started_utc": now(),
            "command": command,
            "cwd": str(root),
        }
        (root / "LAUNCH.json").write_text(json.dumps(launch, indent=2) + "\n")
        print(json.dumps(launch, indent=2), flush=True)
        sampler = Sampler(
            base, auth["attempt_id"], root / "resource_samples.jsonl", args.sample_seconds
        )
        sampler.start()
        returncode = process.wait()
        sampler.stop.set()
        sampler.join(timeout=90)
    wall = time.monotonic() - started
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    completion = {
        "status": "producer_exited",
        "returncode": returncode,
        "ended_utc": now(),
        "wall_seconds": wall,
        "host_child_user_cpu_seconds": usage.ru_utime,
        "host_child_system_cpu_seconds": usage.ru_stime,
        "container_peak_memory_bytes": sampler.peak,
        "container_cpu_seconds_sampled": sampler.cpu_seconds,
        "resource_samples": sampler.samples,
    }
    (root / "LAUNCH_COMPLETION.json").write_text(json.dumps(completion, indent=2) + "\n")
    print(json.dumps(completion, indent=2), flush=True)
    if returncode != 0:
        raise SystemExit("controller failed; the attempt directory preserves the failure")
    run = root / "run"
    with (
        (root / "verification.json").open("x") as out,
        (root / "verification_stderr.log").open("x") as err,
    ):
        verified = subprocess.run(
            [args.python, str(VERIFIER), str(run), str(authorization)],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=600,
        ).returncode
    if verified != 0:
        raise SystemExit("read-only verification failed; inspect verification_stderr.log")
    receipt = json.loads((run / "forecast" / "fit_receipt.json").read_text())
    receipts = [json.loads(line) for line in (run / "release_receipts.jsonl").open()]
    commitment = json.loads((run / "FORECAST_COMMITMENT.json").read_text())
    summary = {
        "status": "forecast_committed_and_verified_no_scores",
        "target_year": auth.get("walkforward", {}).get("target_year"),
        "fit_cutoff": auth["fit_cutoff"],
        "elo_reference_date": auth.get("walkforward", {}).get("elo_reference_date"),
        "fit_rows": receipt["fit_rows"],
        "target_rows": receipt["target_rows"],
        "native_rows": receipt["native_rows"],
        "feature_columns": len(receipt["feature_columns"]),
        "fit_members": [
            {k: entry[k] for k in ["member", "role", "rows", "trees"]}
            for entry in receipt["fit_menu"]
        ],
        "recent_blend": receipt["activation"]["temporal"],
        "segments": receipt["activation"]["segments"],
        "cutoff_batches": len(receipts),
        "chronology_replays": receipts[-1]["cumulative_chronology_replays"],
        "cumulative_rows_replayed": receipts[-1]["cumulative_replayed_rows"],
        "controller_wall_seconds": commitment["wall_seconds"],
        "fit_worker_wall_seconds": receipt["wall_seconds"],
        "launcher_wall_seconds": wall,
        "container_peak_memory_bytes": sampler.peak,
        "container_cpu_seconds_sampled": sampler.cpu_seconds,
        "forecast_sha256": commitment["forecast_sha256"],
        "fit_input_hashes": commitment["fit_input_hashes"],
        "image_id": commitment["image_id"],
    }
    (root / "REPLAY_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
