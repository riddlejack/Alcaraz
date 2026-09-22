"""Build the one-shot September 21 Ingram numerical-recovery freeze.

The predecessor freeze is immutable.  This builder copies its reviewed runtime
files byte-for-byte, changes only the declared numerical/resource successor,
and records an explicit machine-checkable delta.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

SOURCE_FREEZE_SHA256 = "5fb0d9f4e4447385653189ceb21a3caf4e66186a65d6af5accb3c4ac18a0a957"
COPIED_RUNTIME_FILES = (
    "bounded_controller.py",
    "ingram_model.py",
    "posterior_predict.py",
    "requirements.lock",
    "scorer.py",
    "sparse_ingram_model.py",
    "sparse_posterior_predict.py",
    "sparse_runner.py",
    "synthetic_end_to_end.py",
    "synthetic_multicore_rehearsal.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as destination:
        destination.write(content)


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    source_freeze_path = source_dir / "FROZEN_PRE_RUN_MULTICORE.json"
    if sha256(source_freeze_path) != SOURCE_FREEZE_SHA256:
        raise RuntimeError("predecessor freeze hash differs")
    if output_dir.exists():
        raise RuntimeError("recovery output directory already exists")
    output_dir.mkdir(parents=True)
    runtime_dir = output_dir / "runtime"
    runtime_dir.mkdir()

    copied_hashes: dict[str, str] = {}
    for name in COPIED_RUNTIME_FILES:
        source = source_dir / name
        destination = runtime_dir / name
        shutil.copyfile(source, destination)
        if sha256(source) != sha256(destination):
            raise RuntimeError(f"copied runtime file differs: {name}")
        copied_hashes[name] = sha256(destination)

    source_freeze = json.loads(source_freeze_path.read_text(encoding="utf-8"))
    successor = json.loads(json.dumps(source_freeze))
    successor["schema_version"] = "1.1"
    successor["authorization"] = {
        "prepare_and_synthetic_rehearsal": True,
        "real_fit": False,
        "required_next_action": (
            "independent review of this exact successor, then one bound authorization"
        ),
    }
    successor["sampler"]["draws_per_chain"] = 4000
    successor["resource_policy"].update(
        {
            "aggregate_rss_mib": 24576,
            "logical_cpu_threads": 8,
            "period_workers": 2,
            "period_processes": (
                "three fixed waves of two fresh period subprocesses; each period uses four "
                "native PyMC chain workers and a distinct PyTensor compile cache"
            ),
            "scratch_gib": 48,
            "total_wall_seconds": 86400,
        }
    )
    successor["workflow"].update(
        {
            "period_execution": (
                "three fixed waves of two period subprocesses; four native PyMC chain workers "
                "per period; BLAS one thread per worker"
            ),
            "numerical_recovery": (
                "only retained draws change, from 1,000 to 4,000 per chain; model, priors, "
                "inputs, periods, seeds, warmup, sampler settings, gates, prediction and score "
                "contracts are unchanged"
            ),
        }
    )
    successor["bound_files"] = {
        name: {"path": str((runtime_dir / name).resolve()), "sha256": digest}
        for name, digest in copied_hashes.items()
    }
    successor["lineage"] = {
        "predecessor_freeze_path": str(source_freeze_path),
        "predecessor_freeze_sha256": SOURCE_FREEZE_SHA256,
        "predecessor_failed_gate_path": str(
            source_dir
            / "runtime_real/INGRAM-PAPER-ATP2024-01/attempt_002/period_01/FAILED_GATE.json"
        ),
        "authorized_change": "draws_per_chain 1000 to 4000 plus bounded resource topology",
        "unchanged_model": True,
        "unchanged_data_and_target_membership": True,
        "automatic_retry": False,
    }

    freeze_path = output_dir / "FROZEN_RECOVERY.json"
    write_new(freeze_path, canonical_bytes(successor))
    freeze_hash = sha256(freeze_path)
    write_new(
        freeze_path.with_suffix(freeze_path.suffix + ".sha256"),
        f"{freeze_hash}\n".encode("ascii"),
    )

    expected_unchanged = (
        "candidate",
        "diagnostic_gates",
        "model",
        "periods",
        "prepare_receipt",
        "sources",
        "target_membership_sha256",
    )
    for field in expected_unchanged:
        if successor[field] != source_freeze[field]:
            raise RuntimeError(f"unauthorized scientific binding changed: {field}")
    sampler_delta = {
        key: (source_freeze["sampler"].get(key), successor["sampler"].get(key))
        for key in sorted(set(source_freeze["sampler"]) | set(successor["sampler"]))
        if source_freeze["sampler"].get(key) != successor["sampler"].get(key)
    }
    if sampler_delta != {"draws_per_chain": (1000, 4000)}:
        raise RuntimeError(f"sampler delta differs: {sampler_delta}")

    prior_attempt = source_dir / "runtime_real/INGRAM-PAPER-ATP2024-01/attempt_002"
    measured_period_bytes = {
        path.name: sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        for path in sorted(prior_attempt.glob("period_*"))
    }
    old_controller = json.loads(
        (source_dir / "runtime_real/INGRAM-PAPER-ATP2024-01/attempt_002_controller.json").read_text(
            encoding="utf-8"
        )
    )
    resource_basis = {
        "status": "pre_launch_resource_basis",
        "source_attempt": str(prior_attempt),
        "predecessor_draws_per_chain": 1000,
        "successor_draws_per_chain": 4000,
        "predecessor_stored_iterations_per_chain": 2000,
        "successor_planned_iterations_per_chain": 5000,
        "measured_period_bytes": measured_period_bytes,
        "measured_three_period_scratch_gib": old_controller["peak_scratch_gib"],
        "measured_three_period_peak_rss_mib": old_controller["peak_aggregate_rss_mib"],
        "measured_three_period_elapsed_seconds": old_controller["elapsed_seconds"],
        "measured_sampling_seconds_from_log": 3750,
        "derived_sampling_scale": 2.5,
        "derived_three_wave_sampling_hours": 7.8125,
        "planning_runtime_range_hours": [8, 12],
        "hard_wall_hours": 24,
        "trace_storage_conservative_multiplier_on_predecessor": 4,
        "hard_scratch_gib": 48,
        "available_gib_observed_before_freeze": 127,
        "basis_note": (
            "The 48 GiB cap conservatively applies the brief's four-times-retained-trace "
            "instruction to the measured predecessor footprint and leaves headroom for "
            "prediction arrays, compile caches, receipts and framework metadata."
        ),
    }
    write_new(output_dir / "PRE_RUN_RESOURCE_BASIS.json", canonical_bytes(resource_basis))

    delta = {
        "status": "successor_freeze_built_not_authorized",
        "source_freeze_sha256": SOURCE_FREEZE_SHA256,
        "successor_freeze_sha256": freeze_hash,
        "scientific_bindings_byte_equal_as_json": list(expected_unchanged),
        "sampler_delta": {
            key: {"before": before, "after": after}
            for key, (before, after) in sampler_delta.items()
        },
        "resource_delta": {
            "period_workers": [3, 2],
            "logical_cpu_threads": [12, 8],
            "scratch_gib": [25, 48],
            "total_wall_seconds": [172800, 86400],
            "aggregate_rss_mib": [24576, 24576],
        },
        "copied_runtime_files": copied_hashes,
    }
    write_new(output_dir / "SUCCESSOR_DELTA.json", canonical_bytes(delta))
    print(json.dumps(delta, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
