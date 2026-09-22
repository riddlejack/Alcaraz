"""Validate or launch one authorization-bound Ingram recovery attempt."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--attempt-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    freeze_path = args.freeze.resolve()
    authorization_path = args.authorization.resolve()
    attempt = args.attempt_dir.resolve()
    python = args.python.absolute()
    if not python.exists():
        raise RuntimeError("configured Python executable does not exist")
    runtime_dir = freeze_path.parent / "runtime"
    controller = runtime_dir / "bounded_controller.py"
    runner = runtime_dir / "sparse_runner.py"
    freeze_hash = sha256(freeze_path)
    authorization_hash = sha256(authorization_path)
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if (
        authorization.get("status") != "root_authorized_one_real_attempt"
        or authorization.get("freeze_sha256") != freeze_hash
        or Path(authorization.get("authorized_attempt_dir", "")).resolve() != attempt
        or authorization.get("automatic_retry") is not False
    ):
        raise RuntimeError("authorization does not bind this exact freeze and attempt")
    for name, receipt in freeze["bound_files"].items():
        if sha256(Path(receipt["path"])) != receipt["sha256"]:
            raise RuntimeError(f"bound file differs: {name}")
    policy = freeze["resource_policy"]
    receipt = attempt.with_name(f"{attempt.name}_controller.json")
    run_base = attempt.parent
    launch_receipt = run_base / f"ROOT_LAUNCH_RECEIPT_{attempt.name.upper()}.json"
    stdout_path = run_base / f"{attempt.name}_producer_stdout.log"
    stderr_path = run_base / f"{attempt.name}_producer_stderr.log"
    environment = {
        "PATH": f"{python.parent}:/usr/bin:/bin",
        "XDG_CACHE_HOME": str(attempt / "cache"),
        "TMPDIR": str(attempt / "tmp"),
        "PYTENSOR_FLAGS": f"base_compiledir={attempt / 'pytensor-cache' / 'controller'}",
        "PYTHONHASHSEED": "0",
        "LC_ALL": "C",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    command = [
        str(python),
        str(controller),
        "--attempt-dir",
        str(attempt),
        "--receipt",
        str(receipt),
        "--rss-mib",
        str(policy["aggregate_rss_mib"]),
        "--logical-cpu-threads",
        str(policy["logical_cpu_threads"]),
        "--scratch-gib",
        str(policy["scratch_gib"]),
        "--wall-seconds",
        str(policy["total_wall_seconds"]),
        "--",
        str(python),
        str(runner),
        "fit-all",
        "--freeze",
        str(freeze_path),
        "--freeze-sha256",
        freeze_hash,
        "--authorization",
        str(authorization_path),
        "--authorization-sha256",
        authorization_hash,
        "--attempt-dir",
        str(attempt),
    ]
    validation = {
        "status": "validated_not_launched" if args.validate_only else "launched_not_complete",
        "validated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "command": command,
        "environment_keys": sorted(environment),
        "authorization_sha256": authorization_hash,
        "freeze_sha256": freeze_hash,
        "controller_receipt": str(receipt),
        "attempt": str(attempt),
        "automatic_retry": False,
        "script_sha256": sha256(Path(__file__)),
    }
    if args.validate_only:
        print(json.dumps(validation, indent=2, sort_keys=True))
        return
    outputs = (attempt, receipt, launch_receipt, stdout_path, stderr_path)
    if any(path.exists() for path in outputs):
        raise RuntimeError("attempt output already exists; automatic retry is forbidden")
    run_base.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=runtime_dir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    sleep_guard = subprocess.Popen(
        ["/usr/bin/caffeinate", "-i", "-w", str(process.pid)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    validation.update(
        {
            "started_utc": dt.datetime.now(dt.UTC).isoformat(),
            "controller_pid": process.pid,
            "caffeinate_pid": sleep_guard.pid,
        }
    )
    with launch_receipt.open("x", encoding="utf-8") as destination:
        json.dump(validation, destination, indent=2, sort_keys=True)
        destination.write("\n")
    print(json.dumps(validation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
