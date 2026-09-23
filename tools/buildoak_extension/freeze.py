"""Bind the single reviewed cohort, copied adapter, runtime and score contract."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    prep = root / "preparation"
    info = json.loads((prep / "preparation.json").read_text())
    if info["cohort"] != "WTA2024" or info["target_rows"] != 2404:
        raise ValueError("frozen cohort drift")
    review = json.loads(args.review.read_text())
    if review.get("verdict") != "APPROVE":
        raise ValueError("independent design/runtime approval required")
    if review.get("image_id") != args.image_id:
        raise ValueError("runtime image differs from independent approval")
    for path, expected in review["bindings"].items():
        if digest(Path(path)) != expected:
            raise ValueError("reviewed artifact changed: " + path)
    native = sorted((prep / "native_raw").glob("wta_matches_*.csv"))
    ranking = prep / "rankings.csv"
    files = set(
        native
        + [
            ranking,
            args.review.resolve(),
            root / "DESIGN.md",
            root / "RUNTIME.md",
            root / "SOURCE_BINDINGS.json",
        ]
    )
    source_bindings = json.loads((root / "SOURCE_BINDINGS.json").read_text())["bindings"]
    for path, expected in source_bindings.items():
        if digest(Path(path)) != expected:
            raise ValueError("retained source provenance changed: " + path)
    files.update(Path(p) for p in source_bindings)
    files.update(Path(p) for p in info["sources"])
    files.update(p for p in prep.iterdir() if p.is_file() and p.suffix != ".sqlite")
    files.update(p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    bindings = {str(p): digest(p) for p in sorted(files)}
    # Verify the immutable image actually contains the checked adapter bytes.
    adapter = HERE / "runtime/adapter"
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
    command = [
        "docker",
        "--context",
        "colima-buildoak-extension-20260917",
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
        args.image_id,
        "python",
        "-c",
        probe,
    ]
    actual = json.loads(subprocess.check_output(command, text=True))
    if actual != image_files:
        raise ValueError("container/host adapter mismatch")
    auth = {
        "status": "AUTHORIZED_BUILDOAK_EXTENSION_FORECAST",
        "tour": "wta",
        "attempt_id": "buildoak-wta2024-extension-20260917-attempt-001",
        "allowed_stages": ["features", "fit", "forecast"],
        "output_directory": str(root / "attempt_001"),
        "plan_path": str(prep / "date_hierarchy_plan.json"),
        "docker_context": "colima-buildoak-extension-20260917",
        "image_id": args.image_id,
        "fit_cutoff": info["fit_cutoff"],
        "fit_rows": info["fit_rows"],
        "target_rows": info["target_rows"],
        "recent_rows": info["recent_rows"],
        "native_match_files": [str(p) for p in native],
        "ranking_files": [str(ranking)],
        "ioc_buckets": json.loads((prep / "ioc_vocabulary.json").read_text())["vocabulary"],
        "wall_seconds": 14400,
        "cpu_seconds": 28800,
        "cpus": 4,
        "memory_bytes": 8 * 1024**3,
        "scratch_bytes": 10 * 1024**3,
        "feature_response_bytes": 64 * 1024**2,
        "fit_stdout_bytes": 96 * 1024**2,
        "fit_artifact_bytes": 64 * 1024**2,
        "bindings": bindings,
        "image_adapter_files": image_files,
        "independent_review": str(args.review.resolve()),
        "report_inputs": info["report_inputs"],
        "source_revision": "237d1e7ae020de062a994dd7f987881fa2c9a795",
        "scoring": {
            "primary": "paired match-weighted logloss Alcaraz minus external",
            "clip": 1e-15,
            "tie_accuracy": 0.5,
            "bootstrap_seed": 20260917,
            "replicates": 5000,
            "block_lengths": [8, 4, 13],
        },
        "membership": {
            name: digest(prep / (name + "_membership.txt")) for name in ["fit", "target"]
        },
    }
    with (root / "AUTHORIZATION.json").open("x") as f:
        f.write(json.dumps(auth, indent=2) + "\n")
    print(
        json.dumps(
            {
                "authorization": str(root / "AUTHORIZATION.json"),
                "sha256": digest(root / "AUTHORIZATION.json"),
                "bindings": len(bindings),
                "image_verified": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
