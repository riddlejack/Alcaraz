"""Trusted buildoak extension controller.

Raw rows and future results stay in this trusted host process. The projected
feature worker receives only neutral current fixtures and already released
history. The immutable image performs feature construction and native fitting;
it never receives target outcomes.
"""

from __future__ import annotations

import base64
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import selectors
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "adapter"))
from bench_schema import neutral_fixture  # noqa: E402

AUTHORIZATION_STATUS = "AUTHORIZED_BUILDOAK_EXTENSION_FORECAST"
MAX_CPUS = 4.0
MAX_MEMORY_BYTES = 16 * 1024**3
MAX_RESPONSE_BYTES = 64 * 1024**2
MAX_FIT_STDOUT_BYTES = 96 * 1024**2
MAX_FIT_ARTIFACT_BYTES = 64 * 1024**2
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def digest(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def normalized_bindings(auth: dict) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for supplied_path, expected in auth["bindings"].items():
        resolved = str(Path(supplied_path).resolve())
        if resolved in bindings and bindings[resolved] != expected:
            raise ValueError(f"conflicting binding for {resolved}")
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"invalid sha256 binding for {resolved}")
        bindings[resolved] = expected
    return bindings


def require_binding(path: str | Path, bindings: dict[str, str]) -> None:
    resolved = str(Path(path).resolve())
    if resolved not in bindings:
        raise ValueError(f"missing mandatory binding: {resolved}")
    if digest(resolved) != bindings[resolved]:
        raise ValueError(f"binding mismatch: {resolved}")


def docker_base(auth: dict) -> list[str]:
    context = auth.get("docker_context")
    host = auth.get("docker_host")
    if bool(context) == bool(host):
        raise ValueError("set exactly one of docker_context or docker_host")
    value = context or host
    if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value):
        raise ValueError("invalid Docker context/host")
    return ["docker", "--context", context] if context else ["docker", "--host", host]


def resource_limits(auth: dict) -> tuple[list[str], dict[str, int | float]]:
    cpus = float(auth["cpus"])
    memory = int(auth["memory_bytes"])
    cpu_seconds = int(auth["cpu_seconds"])
    if not (0 < cpus <= MAX_CPUS):
        raise ValueError(f"cpus must be in (0, {MAX_CPUS}]")
    if not (0 < memory <= MAX_MEMORY_BYTES):
        raise ValueError(f"memory_bytes must be in (0, {MAX_MEMORY_BYTES}]")
    if cpu_seconds <= 0:
        raise ValueError("cpu_seconds must be positive")
    values = {
        "cpus": cpus,
        "memory_bytes": memory,
        "feature_response_bytes": int(auth["feature_response_bytes"]),
        "fit_stdout_bytes": int(auth["fit_stdout_bytes"]),
        "fit_artifact_bytes": int(auth["fit_artifact_bytes"]),
        "scratch_bytes": int(auth["scratch_bytes"]),
    }
    for key in [
        "feature_response_bytes",
        "fit_stdout_bytes",
        "fit_artifact_bytes",
        "scratch_bytes",
    ]:
        if values[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if values["feature_response_bytes"] > MAX_RESPONSE_BYTES:
        raise ValueError("feature_response_bytes exceeds controller ceiling")
    if values["fit_stdout_bytes"] > MAX_FIT_STDOUT_BYTES:
        raise ValueError("fit_stdout_bytes exceeds controller ceiling")
    if values["fit_artifact_bytes"] > MAX_FIT_ARTIFACT_BYTES:
        raise ValueError("fit_artifact_bytes exceeds controller ceiling")
    flags = [
        "--network",
        "none",
        "--read-only",
        "--memory",
        str(memory),
        "--memory-swap",
        str(memory),
        "--cpus",
        format(cpus, "g"),
        "--pids-limit",
        "32",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--ulimit",
        f"cpu={cpu_seconds}:{cpu_seconds}",
    ]
    return flags, values


def stage_input_volume(base: list[str], image: str, inputs: Path, name: str) -> str:
    """Populate a dedicated volume without executing source-derived code."""
    volume = name + "-inputs"
    staging = name + "-input-staging"
    if subprocess.run(base + ["inspect", staging], capture_output=True).returncode == 0:
        raise ValueError("staging container already exists")
    if subprocess.run(base + ["volume", "inspect", volume], capture_output=True).returncode == 0:
        raise ValueError("input volume already exists; preserve prior attempt")
    subprocess.run(base + ["volume", "create", volume], capture_output=True, check=True)
    success = False
    try:
        subprocess.run(
            base
            + [
                "create",
                "--name",
                staging,
                "--network",
                "none",
                "--mount",
                f"type=volume,source={volume},target=/inputs",
                image,
                "true",
            ],
            capture_output=True,
            check=True,
        )
        # The staging container is never started; Docker copies these exact files.
        subprocess.run(
            base + ["cp", str(inputs) + "/.", staging + ":/inputs"], capture_output=True, check=True
        )
        success = True
        return volume
    finally:
        subprocess.run(base + ["rm", staging], capture_output=True)
        if not success:
            subprocess.run(base + ["volume", "rm", volume], capture_output=True)


def retain_fit_artifacts(stdout: str, destination: Path, max_bytes: int) -> dict:
    """Decode a bounded, inert artifact inventory before the tmpfs disappears."""
    message = json.loads(stdout)
    artifacts = message["artifacts_base64"]
    inventory = message["artifact_inventory"]
    if not isinstance(artifacts, dict) or sorted(artifacts) != sorted(inventory):
        raise ValueError("fit artifact inventory mismatch")
    required = {"native_forecasts.csv", "fit_receipt.json"}
    if not required <= set(artifacts):
        raise ValueError("required fit artifacts missing")
    if not any(name.startswith("global") and name.endswith(".json") for name in artifacts):
        raise ValueError("global native model artifact missing")
    destination.mkdir(exist_ok=False)
    total = 0
    for name in sorted(artifacts):
        if not SAFE_NAME.fullmatch(name) or not name.endswith((".json", ".csv")):
            raise ValueError(f"unsafe fit artifact name: {name!r}")
        content = base64.b64decode(artifacts[name], validate=True)
        total += len(content)
        if total > max_bytes:
            raise ValueError("fit artifact size ceiling")
        (destination / name).write_bytes(content)
    receipt = json.loads((destination / "fit_receipt.json").read_text())
    if receipt.get("artifact_inventory") != sorted(
        name for name in artifacts if name != "fit_receipt.json"
    ):
        raise ValueError("fit receipt inventory mismatch")
    for name, expected in receipt.get("artifact_sha256", {}).items():
        if (
            name == "fit_receipt.json"
            or name not in artifacts
            or digest(destination / name) != expected
        ):
            raise ValueError(f"fit receipt hash mismatch: {name}")
    if set(receipt.get("artifact_sha256", {})) != set(artifacts) - {"fit_receipt.json"}:
        raise ValueError("fit receipt hash coverage mismatch")
    return {key: value for key, value in message.items() if key != "artifacts_base64"}


def normalize(row: dict) -> dict:
    row = dict(row)
    # Native pd.concat supplies the union of these columns across annual files.
    for prefix in ["w", "l"]:
        for field in [
            "ace",
            "df",
            "svpt",
            "1stIn",
            "1stWon",
            "2ndWon",
            "SvGms",
            "bpSaved",
            "bpFaced",
        ]:
            row.setdefault(prefix + "_" + field, None)
    for key in ["match_num", "winner_id", "loser_id", "draw_size", "best_of"]:
        row[key] = int(float(row[key])) if row.get(key) else None
    for key in list(row):
        if (
            key.startswith(("w_", "l_"))
            or key in ["minutes"]
            or (
                key.startswith(("winner_", "loser_"))
                and key.split("_", 1)[1] in ["rank", "rank_points", "seed", "age", "ht"]
            )
        ):
            try:
                value = float(row[key]) if row[key] else None
                row[key] = value if value is None or math.isfinite(value) else None
            except ValueError, TypeError:
                row[key] = None
    return row


def ranking_groups(files: list[str]):
    """Native historical ranking files must be globally date ordered."""
    group: dict[int, dict] = {}
    current = None
    last = None
    for path in files:
        with Path(path).open() as handle:
            for row in csv.DictReader(handle):
                try:
                    when = dt.datetime.strptime(row["ranking_date"], "%Y%m%d").date().isoformat()
                    player = int(row["player"])
                    rank = float(row["rank"])
                except ValueError, KeyError:
                    continue
                if when < "1984-01-01":
                    continue
                if last is not None and when < last:
                    raise ValueError("ranking source date order drift")
                last = when
                if current is not None and when != current:
                    yield current, [group[player_id] for player_id in sorted(group)]
                    group = {}
                current = when
                try:
                    points = float(row.get("points", ""))
                except ValueError, TypeError:
                    points = None
                if player not in group or rank < group[player]["rank"]:
                    group[player] = {
                        "player_id": player,
                        "ranking_date": when,
                        "rank": rank,
                        "points": points,
                    }
    if current is not None:
        yield current, [group[player_id] for player_id in sorted(group)]


def validate_plan(
    plan: list[dict], tour: str
) -> tuple[dict[str, dict], dict[tuple[str, int], dict]]:
    required = {
        "match_id",
        "target_date_proxy",
        "available_date_proxy",
        "eligible_through_date",
        "fit_target",
        "evaluation_target",
        "source_file",
        "source_line",
    }
    by_id: dict[str, dict] = {}
    by_locator: dict[tuple[str, int], dict] = {}
    for row in plan:
        if not required <= set(row):
            raise ValueError("date hierarchy plan row missing fields")
        if row["match_id"] in by_id:
            raise ValueError(f"duplicate plan match_id: {row['match_id']}")
        if row["fit_target"] and row["evaluation_target"]:
            raise ValueError(f"plan row has both roles: {row['match_id']}")
        for field in ["target_date_proxy", "available_date_proxy", "eligible_through_date"]:
            dt.date.fromisoformat(row[field])
        if "tour" in row and str(row["tour"]).lower() != tour:
            raise ValueError(f"plan tour mismatch: {row['match_id']}")
        source_file = str(row["source_file"])
        source_line = int(row["source_line"])
        if Path(source_file).name != source_file or source_line < 2:
            raise ValueError(f"invalid source locator: {row['match_id']}")
        locator = (source_file, source_line)
        if locator in by_locator:
            raise ValueError(f"duplicate source locator: {source_file}:{source_line}")
        by_id[row["match_id"]] = row
        by_locator[locator] = row
    return by_id, by_locator


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: empirical_controller.py AUTHORIZATION.json")
    authorization = Path(sys.argv[1]).resolve()
    auth = json.loads(authorization.read_text())
    if auth.get("status") != AUTHORIZATION_STATUS:
        raise SystemExit("exact buildoak extension authorization required")
    allowed_stages = set(auth.get("allowed_stages", []))
    if not {"features", "fit", "forecast"} <= allowed_stages or not allowed_stages <= {
        "features",
        "fit",
        "forecast",
        "score",
    }:
        raise ValueError("producer-stage authorization mismatch")
    tour = str(auth["tour"]).lower()
    if tour not in {"atp", "wta"}:
        raise ValueError("tour must be atp or wta")
    if not SAFE_NAME.fullmatch(auth["attempt_id"]):
        raise ValueError("unsafe attempt_id")
    bindings = normalized_bindings(auth)
    plan_path = Path(auth["plan_path"]).resolve()
    mandatory = [Path(__file__), HERE / "adapter" / "bench_schema.py", plan_path]
    mandatory += [Path(path) for path in auth["native_match_files"]]
    mandatory += [Path(path) for path in auth["ranking_files"]]
    for path in mandatory:
        require_binding(path, bindings)
    base = docker_base(auth)
    limits, bounded = resource_limits(auth)
    output_directory = Path(auth["output_directory"])
    if not output_directory.is_absolute():
        raise ValueError("output_directory must be absolute")
    attempt = output_directory.resolve()
    attempt.mkdir(parents=True, exist_ok=False)
    (attempt / "authorization_copy.json").write_text(authorization.read_text())
    start = time.monotonic()
    deadline = start + int(auth["wall_seconds"])
    if int(auth["wall_seconds"]) <= 0:
        raise ValueError("wall_seconds must be positive")
    image = auth["image_id"]
    if not isinstance(image, str) or not image.startswith("sha256:"):
        raise ValueError("image must use immutable ID")
    inspected_image = subprocess.check_output(
        base + ["image", "inspect", image, "--format", "{{.Id}}"], text=True
    ).strip()
    if inspected_image != image:
        raise ValueError("Docker image ID mismatch")
    worker_name = auth["attempt_id"] + "-features"
    fit_name = auth["attempt_id"] + "-fit"
    for name in [worker_name, fit_name]:
        if subprocess.run(base + ["inspect", name], capture_output=True).returncode == 0:
            raise ValueError("container already exists; preserve prior attempt: " + name)

    def enforce_wall_cap() -> None:
        for name in [worker_name, fit_name]:
            subprocess.run(base + ["kill", name], capture_output=True, timeout=15)

    wall_timer = threading.Timer(int(auth["wall_seconds"]), enforce_wall_cap)
    wall_timer.daemon = True
    wall_timer.start()
    completed = False
    worker = None
    input_volume = None
    feature_stderr_handle = None
    try:
        plan = json.loads(plan_path.read_text())
        if not isinstance(plan, list):
            raise ValueError("date hierarchy plan must be a list")
        by_id, by_locator = validate_plan(plan, tour)
        source_basenames = [Path(path).name for path in auth["native_match_files"]]
        if len(source_basenames) != len(set(source_basenames)):
            raise ValueError("native_match_files basenames must be unique")
        raw: dict[str, dict] = {}
        native_sequence = 0
        for path in auth["native_match_files"]:
            with Path(path).open(encoding="utf-8-sig") as handle:
                for source_line, row in enumerate(csv.DictReader(handle), start=2):
                    if not all(
                        row.get(key)
                        for key in ["winner_id", "loser_id", "tourney_date", "match_num"]
                    ):
                        continue
                    locator = (Path(path).name, source_line)
                    if locator not in by_locator:
                        raise ValueError(f"native row missing from plan: {locator[0]}:{locator[1]}")
                    plan_row = by_locator[locator]
                    key = plan_row["match_id"]
                    if key in raw:
                        raise ValueError("duplicate transport match key: " + key)
                    native_key = row["tourney_id"] + "/" + str(int(row["match_num"]))
                    if key != native_key and not key.startswith(native_key + "@"):
                        raise ValueError(f"transport/native key mismatch: {key} != {native_key}")
                    record = normalize(row)
                    record["_native_sequence"] = native_sequence
                    record["_transport_id"] = key
                    native_sequence += 1
                    record["match_date"] = plan_row["target_date_proxy"]
                    record["available_date"] = plan_row["available_date_proxy"]
                    raw[key] = record
        if set(raw) != set(by_id):
            missing = sorted(set(by_id) - set(raw))[:5]
            raise ValueError(f"plan rows missing from native inputs: {missing}")
        tasks: dict[str, list[str]] = collections.defaultdict(list)
        for row in plan:
            if row["fit_target"] or row["evaluation_target"]:
                tasks[row["eligible_through_date"]].append(row["match_id"])
        releases = sorted(plan, key=lambda row: (row["available_date_proxy"], row["match_id"]))
        cursor = 0
        rank_stream = iter(ranking_groups(auth["ranking_files"]))
        next_ranks = next(rank_stream, None)
        feature_stderr_handle = (attempt / "feature_stderr.txt").open("w")
        worker = subprocess.Popen(
            base
            + ["run", "--name", worker_name, "-i"]
            + limits
            + [image, "python", "feature_worker.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=feature_stderr_handle,
            text=True,
            bufsize=1,
        )
        selector = selectors.DefaultSelector()
        selector.register(worker.stdout, selectors.EVENT_READ)

        def exchange(message: dict) -> dict:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("campaign wall cap")
            worker.stdin.write(json.dumps(message, allow_nan=False, separators=(",", ":")) + "\n")
            worker.stdin.flush()
            if not selector.select(timeout=max(0, deadline - time.monotonic())):
                raise TimeoutError("feature response wall cap")
            line = worker.stdout.readline(bounded["feature_response_bytes"] + 1)
            if len(line.encode()) > bounded["feature_response_bytes"]:
                raise ValueError("feature response size ceiling")
            if not line:
                raise RuntimeError("feature worker exited; inspect stderr")
            return json.loads(line)

        if exchange({"reference_date": auth["fit_cutoff"], "ioc_buckets": auth["ioc_buckets"]}) != {
            "ready": True
        }:
            raise ValueError("worker initialization mismatch")
        files = {
            role: (attempt / (role + "_features.csv")).open("w") for role in ["training", "target"]
        }
        writers: dict[str, csv.DictWriter] = {}
        counts: collections.Counter = collections.Counter()
        feature_header = None
        with (attempt / "release_receipts.jsonl").open("w") as receipts:
            for cutoff, keys in sorted(tasks.items()):
                history = []
                while cursor < len(releases) and releases[cursor]["available_date_proxy"] <= cutoff:
                    history.append(raw[releases[cursor]["match_id"]])
                    cursor += 1
                rankings = []
                while next_ranks is not None and next_ranks[0] <= cutoff:
                    rankings.extend(next_ranks[1])
                    next_ranks = next(rank_stream, None)
                message = {
                    "cutoff": cutoff,
                    "history": history,
                    "rankings": rankings,
                    "targets": [neutral_fixture(raw[key]) for key in sorted(keys)],
                }
                answer = exchange(message)
                if len(answer["outputs"]) != len(keys) or {
                    row["match_id"] for row in answer["outputs"]
                } != set(keys):
                    raise ValueError("worker target membership mismatch")
                receipts.write(json.dumps(answer["receipt"], separators=(",", ":")) + "\n")
                for output in answer["outputs"]:
                    key = output["match_id"]
                    role = "training" if by_id[key]["fit_target"] else "target"
                    if output["label"] is not None:
                        raise ValueError("worker emitted target outcome")
                    if role == "training":
                        output["label"] = int(raw[key]["winner_id"] < raw[key]["loser_id"])
                    if feature_header is None:
                        feature_header = list(output)
                    if list(output) != feature_header:
                        raise ValueError("feature schema drift")
                    if role not in writers:
                        writers[role] = csv.DictWriter(files[role], fieldnames=feature_header)
                        writers[role].writeheader()
                    writers[role].writerow(output)
                    counts[role] += 1
                if (
                    sum(path.stat().st_size for path in attempt.iterdir() if path.is_file())
                    > bounded["scratch_bytes"]
                ):
                    raise RuntimeError("scratch size ceiling")
        for handle in files.values():
            handle.close()
        worker.stdin.close()
        worker.wait(timeout=max(0.1, deadline - time.monotonic()))
        feature_stderr_handle.close()
        feature_stderr_handle = None
        if worker.returncode != 0:
            raise RuntimeError("feature worker failed")
        (attempt / "feature_container_inspect.json").write_bytes(
            subprocess.check_output(base + ["inspect", worker_name])
        )
        expected_counts = {"training": int(auth["fit_rows"]), "target": int(auth["target_rows"])}
        if dict(counts) != expected_counts:
            raise ValueError(f"projection counts differ: {dict(counts)} != {expected_counts}")
        inputs = attempt / "fit_inputs"
        inputs.mkdir()
        for name in ["training_features.csv", "target_features.csv"]:
            os.link(attempt / name, inputs / name)
        config = {
            "tour": tour,
            "fit_cutoff": auth["fit_cutoff"],
            "fit_rows": int(auth["fit_rows"]),
            "target_rows": int(auth["target_rows"]),
            "recent_rows": int(auth["recent_rows"]),
            "fit_artifact_bytes": bounded["fit_artifact_bytes"],
            "inputs": {
                name: digest(inputs / name)
                for name in ["training_features.csv", "target_features.csv"]
            },
        }
        (inputs / "fit_config.json").write_text(json.dumps(config, indent=2) + "\n")
        input_volume = stage_input_volume(base, image, inputs, fit_name)
        subprocess.run(
            base
            + ["create", "--name", fit_name]
            + limits
            + [
                "--mount",
                f"type=volume,source={input_volume},target=/inputs,readonly",
                image,
                "python",
                "fit_worker.py",
            ],
            check=True,
            capture_output=True,
        )
        fit = subprocess.run(
            base + ["start", "-a", fit_name],
            capture_output=True,
            text=True,
            timeout=max(0.1, deadline - time.monotonic()),
        )
        if len(fit.stdout.encode()) > bounded["fit_stdout_bytes"]:
            raise RuntimeError("fit stdout size ceiling")
        (attempt / "fit_stdout.txt").write_text(fit.stdout)
        (attempt / "fit_stderr.txt").write_text(fit.stderr)
        (attempt / "fit_container_inspect.json").write_bytes(
            subprocess.check_output(base + ["inspect", fit_name])
        )
        if fit.returncode != 0:
            raise RuntimeError("fit worker failed")
        retained = retain_fit_artifacts(
            fit.stdout, attempt / "forecast", bounded["fit_artifact_bytes"]
        )
        if retained.get("tour") != tour:
            raise ValueError("fit worker tour mismatch")
        commitment = {
            "status": "forecast_complete_no_scores",
            "tour": tour,
            "authorization_sha256": digest(authorization),
            "image_id": image,
            "plan_sha256": digest(plan_path),
            "fit_input_hashes": config["inputs"],
            "resource_limits": bounded,
            "wall_seconds": time.monotonic() - start,
            "forecast_sha256": {
                path.name: digest(path) for path in sorted((attempt / "forecast").iterdir())
            },
        }
        (attempt / "FORECAST_COMMITMENT.json").write_text(json.dumps(commitment, indent=2) + "\n")
        completed = True
        print(json.dumps(commitment, indent=2))
    except BaseException as error:
        (attempt / "FAILURE.json").write_text(
            json.dumps(
                {
                    "type": type(error).__name__,
                    "message": str(error),
                    "elapsed_seconds": time.monotonic() - start,
                },
                indent=2,
            )
            + "\n"
        )
        raise
    finally:
        wall_timer.cancel()
        if feature_stderr_handle is not None:
            feature_stderr_handle.close()
        for name in [worker_name, fit_name]:
            subprocess.run(base + ["kill", name], capture_output=True)
            subprocess.run(base + ["rm", name], capture_output=True)
        if worker is not None and worker.poll() is None:
            worker.wait(timeout=10)
        if input_volume is not None:
            subprocess.run(base + ["volume", "rm", input_volume], capture_output=True)
        if not completed:
            print("Preserved failed attempt; no automatic retry.", file=sys.stderr)


if __name__ == "__main__":
    main()
