"""Byte-level comparison of a WTA walk-forward 2024 reproduction with the accepted attempt.

Required identical: both fit inputs and ``native_forecasts.csv``, each against the accepted
``FORECAST_COMMITMENT.json`` and the accepted files. Also compared: every other committed
forecast artefact (the six native model files and the fit receipt without its wall time),
the release receipts, the plan, both memberships and the IOC vocabulary. On a mismatch it
reports the first differing line and columns of target-side files only; it never reads
or summarizes outcomes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def first_difference(left: Path, right: Path) -> dict | None:
    with left.open() as a, right.open() as b:
        header_a = next(csv.reader([a.readline()]))
        header_b = next(csv.reader([b.readline()]))
        if header_a != header_b:
            return {
                "kind": "header",
                "only_left": sorted(set(header_a) - set(header_b)),
                "only_right": sorted(set(header_b) - set(header_a)),
                "same_set_different_order": set(header_a) == set(header_b),
            }
        for index, (row_a, row_b) in enumerate(zip(a, b, strict=False), start=2):
            if row_a != row_b:
                cells_a = next(csv.reader([row_a]))
                cells_b = next(csv.reader([row_b]))
                columns = [
                    header_a[i]
                    for i in range(min(len(cells_a), len(cells_b)))
                    if cells_a[i] != cells_b[i]
                ]
                return {"kind": "row", "line": index, "columns": columns[:20]}
        if a.read() or b.read():
            return {"kind": "length"}
    return None


def compare(left: Path, right: Path, committed: str | None) -> dict:
    entry = {
        "reproduction_sha256": digest(left) if left.exists() else None,
        "accepted_sha256": digest(right) if right.exists() else None,
        "accepted_commitment_sha256": committed,
    }
    entry["identical"] = entry["reproduction_sha256"] is not None and entry[
        "reproduction_sha256"
    ] == entry["accepted_sha256"] == (committed or entry["accepted_sha256"])
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True, help="walk-forward attempt root")
    parser.add_argument("--reference", type=Path, required=True, help="accepted attempt_001")
    parser.add_argument("--reference-preparation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    attempt = args.attempt.resolve()
    run = attempt / "run"
    prep = attempt / "preparation"
    reference = args.reference.resolve()
    reference_prep = args.reference_preparation.resolve()
    accepted = json.loads((reference / "FORECAST_COMMITMENT.json").read_text())
    produced = json.loads((run / "FORECAST_COMMITMENT.json").read_text())
    result: dict = {"status": None, "required_identical": {}, "informative": {}, "details": {}}
    for name in ["training_features.csv", "target_features.csv"]:
        key = "fit_inputs/" + name
        result["required_identical"][key] = compare(
            run / key, reference / key, accepted["fit_input_hashes"][name]
        )
    result["required_identical"]["forecast/native_forecasts.csv"] = compare(
        run / "forecast/native_forecasts.csv",
        reference / "forecast/native_forecasts.csv",
        accepted["forecast_sha256"]["native_forecasts.csv"],
    )
    for name, committed in sorted(accepted["forecast_sha256"].items()):
        if name not in {"native_forecasts.csv", "fit_receipt.json"}:
            result["informative"]["forecast/" + name] = compare(
                run / "forecast" / name, reference / "forecast" / name, committed
            )
    result["informative"]["release_receipts.jsonl"] = compare(
        run / "release_receipts.jsonl", reference / "release_receipts.jsonl", None
    )
    for name in [
        "date_hierarchy_plan.json",
        "fit_membership.txt",
        "target_membership.txt",
        "ioc_vocabulary.json",
    ]:
        result["informative"]["preparation/" + name] = compare(
            prep / name, reference_prep / name, None
        )
    result["informative"]["plan_sha256_in_commitments"] = {
        "reproduction": produced["plan_sha256"],
        "accepted": accepted["plan_sha256"],
        "identical": produced["plan_sha256"] == accepted["plan_sha256"],
    }
    produced_extra = sorted(set(produced["forecast_sha256"]) - set(accepted["forecast_sha256"]))
    result["informative"]["forecast_artifacts_only_in_reproduction"] = produced_extra
    for name in ["fit_inputs/target_features.csv", "forecast/native_forecasts.csv"]:
        entry = result["required_identical"][name]
        if not entry["identical"] and (run / name).exists():
            result["details"][name] = first_difference(run / name, reference / name)
    if not result["required_identical"]["fit_inputs/training_features.csv"]["identical"]:
        result["details"]["fit_inputs/training_features.csv"] = (
            "differs; row-level detail withheld (training rows carry labels)"
        )
    receipt = json.loads((run / "forecast/fit_receipt.json").read_text())
    accepted_receipt = json.loads((reference / "forecast/fit_receipt.json").read_text())
    differing = sorted(
        k for k in set(receipt) | set(accepted_receipt) if receipt.get(k) != accepted_receipt.get(k)
    )
    result["fit_receipt"] = {
        "fields_differing": differing,
        "identical_except_wall_seconds": differing in ([], ["wall_seconds"]),
        "feature_column_count": len(receipt["feature_columns"]),
        "members_reproduction": [(m["member"], m["rows"], m["trees"]) for m in receipt["fit_menu"]],
        "members_accepted": [
            (m["member"], m["rows"], m["trees"]) for m in accepted_receipt["fit_menu"]
        ],
        "activation_reproduction": receipt["activation"],
        "fit_worker_wall_seconds": {
            "reproduction": receipt["wall_seconds"],
            "accepted": accepted_receipt["wall_seconds"],
        },
    }
    result["commitments"] = {
        "accepted": {k: accepted[k] for k in ["image_id", "resource_limits", "wall_seconds"]},
        "reproduction": {k: produced[k] for k in ["image_id", "resource_limits", "wall_seconds"]},
    }
    required_ok = all(e["identical"] for e in result["required_identical"].values())
    memberships_ok = all(
        result["informative"]["preparation/" + name]["identical"]
        for name in ["fit_membership.txt", "target_membership.txt"]
    )
    result["status"] = "BYTE_IDENTICAL" if required_ok and memberships_ok else "MISMATCH"
    result["all_compared_files_identical"] = required_ok and all(
        e["identical"] for e in result["informative"].values() if isinstance(e, dict)
    )
    with args.output.open("x") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] != "BYTE_IDENTICAL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
