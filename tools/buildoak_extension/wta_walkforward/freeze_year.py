"""Freeze one WTA walk-forward attempt: bind inputs, code and image, write authorization.

The authorization drives the unchanged ``runtime/empirical_controller.py`` with
``tour: wta``. Everything the controller may read is bound by SHA-256, the preparation
and its sources are re-verified, and the immutable image must contain exactly the checked
adapter bytes. This step runs no source-derived numerical code on real inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / "runtime"
SOURCE_REVISION = "237d1e7ae020de062a994dd7f987881fa2c9a795"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
BOUND_SUFFIXES = {".py", ".adapter", ".runtime", ".buildoak", ".md"}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def verify_image_adapter(base: list[str], image_id: str) -> dict[str, str]:
    """The immutable image must hold the same adapter bytes as this checkout."""
    adapter = RUNTIME / "adapter"
    image_files = {
        str(p.relative_to(adapter)): digest(p)
        for p in adapter.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    probe = (
        "import pathlib,hashlib,json; names="
        + repr(sorted(image_files))
        + "; print(json.dumps({n:hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest() for n in names}))"
    )
    command = base + [
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "1",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        image_id,
        "python",
        "-c",
        probe,
    ]
    actual = json.loads(subprocess.check_output(command, text=True))
    if actual != image_files:
        raise ValueError("container/host adapter mismatch")
    return image_files


def git_state() -> dict:
    """Record the checkout revision and whether the extension tree is clean."""
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(HERE), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", str(HERE), "status", "--porcelain", "--", str(HERE.parent)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except OSError, subprocess.CalledProcessError:
        return {"commit": None, "extension_tree_clean": None}
    return {"commit": commit, "extension_tree_clean": status.strip() == ""}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="attempt directory")
    parser.add_argument("--preparation", type=Path, default=None, help="default: ROOT/preparation")
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--docker-context", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--bind", type=Path, action="append", default=[], help="extra bound file")
    parser.add_argument("--wall-seconds", type=int, default=14400)
    parser.add_argument("--cpu-seconds", type=int, default=28800)
    parser.add_argument("--cpus", type=float, default=2.0)
    parser.add_argument("--memory-gib", type=int, default=4)
    parser.add_argument("--scratch-gib", type=int, default=10)
    parser.add_argument("--synthetic-only", action="store_true")
    args = parser.parse_args()
    if not SAFE_NAME.fullmatch(args.attempt_id):
        raise ValueError("unsafe attempt id")
    if not args.image_id.startswith("sha256:"):
        raise ValueError("image must use its immutable ID")
    root = args.root.resolve()
    prep = (args.preparation or root / "preparation").resolve()
    info = json.loads((prep / "preparation.json").read_text())
    if info["status"] != "metadata_only_no_candidate_scores" or info["tour"] != "wta":
        raise ValueError("preparation status or tour mismatch")
    for path, expected in info["output_bindings"].items():
        if digest(Path(path)) != expected:
            raise ValueError("preparation output changed: " + path)
    for entry in info["sources"].values():
        if "path" in entry:
            if digest(Path(entry["path"])) != entry["sha256"]:
                raise ValueError("preparation source changed: " + entry["path"])
        else:
            for path, expected in entry.items():
                if digest(Path(path)) != expected:
                    raise ValueError("preparation source changed: " + path)
    base = ["docker", "--context", args.docker_context]
    inspected = subprocess.check_output(
        base + ["image", "inspect", args.image_id, "--format", "{{.Id}}"], text=True
    ).strip()
    if inspected != args.image_id:
        raise ValueError("Docker image ID mismatch")
    image_files = verify_image_adapter(base, args.image_id)
    native = [Path(p) for p in info["sources"]["native_match_files"]]
    ranking = Path(info["sources"]["rankings"]["path"])
    files = set(native) | {ranking, prep / "preparation.json"}
    files.update(Path(p) for p in info["output_bindings"])
    for name in ["frozen_plan", "selected", "selection_json", "labels"]:
        files.add(Path(info["sources"][name]["path"]))
    files.update(
        p
        for p in HERE.parent.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix in BOUND_SUFFIXES
    )
    files.update(p.resolve() for p in args.bind)
    bindings = {str(p.resolve()): digest(p) for p in sorted(files)}
    ioc = json.loads((prep / "ioc_vocabulary.json").read_text())["vocabulary"]
    if ioc != info["ioc_vocabulary"]["vocabulary"]:
        raise ValueError("IOC vocabulary differs from the preparation receipt")
    auth = {
        "code_commit": git_state(),
        "status": "AUTHORIZED_BUILDOAK_EXTENSION_FORECAST",
        "tour": "wta",
        "attempt_id": args.attempt_id,
        "allowed_stages": ["features", "fit", "forecast"],
        "output_directory": str(root / "run"),
        "plan_path": str(prep / "date_hierarchy_plan.json"),
        "docker_context": args.docker_context,
        "image_id": args.image_id,
        "fit_cutoff": info["fit_cutoff"],
        "fit_rows": info["fit_rows"],
        "target_rows": info["target_rows"],
        "recent_rows": info["recent_rows"],
        "native_match_files": [str(p) for p in native],
        "ranking_files": [str(ranking)],
        "ioc_buckets": ioc,
        "wall_seconds": args.wall_seconds,
        "cpu_seconds": args.cpu_seconds,
        "cpus": args.cpus,
        "memory_bytes": args.memory_gib * 1024**3,
        "scratch_bytes": args.scratch_gib * 1024**3,
        "feature_response_bytes": 64 * 1024**2,
        "fit_stdout_bytes": 96 * 1024**2,
        "fit_artifact_bytes": 64 * 1024**2,
        "bindings": bindings,
        "image_adapter_files": image_files,
        "source_revision": SOURCE_REVISION,
        "walkforward": {
            "target_year": info["target_year"],
            "elo_reference_date": info["elo_reference_date"],
            "frozen_plan_sha256": info["sources"]["frozen_plan"]["sha256"],
            "cohort": info["cohort"],
            "fit_menu_projection": info["fit_menu_projection"],
            "ioc_vocabulary": info["ioc_vocabulary"],
            "replay_schedule": info["replay_schedule"],
        },
        "membership": {
            name: digest(prep / (name + "_membership.txt")) for name in ["fit", "target"]
        },
        "extra_bindings": [str(p.resolve()) for p in args.bind],
    }
    if args.synthetic_only:
        auth["synthetic_only"] = True
    with (root / "AUTHORIZATION.json").open("x") as handle:
        handle.write(json.dumps(auth, indent=2) + "\n")
    print(
        json.dumps(
            {
                "authorization": str(root / "AUTHORIZATION.json"),
                "sha256": digest(root / "AUTHORIZATION.json"),
                "bindings": len(bindings),
                "image_verified": True,
                "target_year": info["target_year"],
                "fit_cutoff": info["fit_cutoff"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
