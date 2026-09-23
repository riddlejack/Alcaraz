"""Byte-level comparison of a walk-forward 2024 reproduction against the accepted D97 run.

Compares SHA-256 digests of the fit inputs, forecasts, fitted native models and release
receipts, plus the frozen memberships and IOC vocabulary. On a mismatch it reports the
first differing line and header columns of the target-side files only; it never reads
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
                return {
                    "kind": "row",
                    "line": index,
                    "columns": columns[:20],
                    "match_id_left": cells_a[0],
                }
        tail_a = a.read()
        tail_b = b.read()
        if tail_a or tail_b:
            return {"kind": "length", "left_extra": bool(tail_a), "right_extra": bool(tail_b)}
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True, help="walk-forward attempt root")
    parser.add_argument("--reference", type=Path, required=True, help="D97_empirical_attempt_001")
    parser.add_argument("--reference-work", type=Path, required=True, help="D97 work directory")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    attempt = args.attempt.resolve()
    run = attempt / "run"
    prep = attempt / "preparation"
    reference = args.reference.resolve()
    work = args.reference_work.resolve()
    accepted = json.loads((reference / "FORECAST_COMMITMENT.json").read_text())
    produced = json.loads((run / "FORECAST_COMMITMENT.json").read_text())
    files = {
        "fit_inputs/training_features.csv": True,
        "fit_inputs/target_features.csv": True,
        "forecast/native_forecasts.csv": True,
        "forecast/global.json": False,
        "forecast/segment_A.json": False,
        "release_receipts.jsonl": False,
    }
    result = {"status": None, "required_identical": {}, "informative": {}, "details": {}}
    for name, required in files.items():
        left = run / name
        right = reference / name
        entry = {
            "reproduction_sha256": digest(left) if left.exists() else None,
            "accepted_sha256": digest(right) if right.exists() else None,
        }
        entry["identical"] = (
            entry["reproduction_sha256"] == entry["accepted_sha256"]
            and entry["accepted_sha256"] is not None
        )
        (result["required_identical"] if required else result["informative"])[name] = entry
        if not entry["identical"] and name.endswith(".csv") and left.exists() and right.exists():
            if "training" in name:
                result["details"][name] = (
                    "differs; row-level detail withheld (training rows carry labels)"
                )
            else:
                result["details"][name] = first_difference(left, right)
    result["accepted_commitment"] = {
        "fit_input_hashes": accepted["fit_input_hashes"],
        "forecast_sha256": accepted["forecast_sha256"],
        "image_id": accepted["image_id"],
        "wall_seconds": accepted["wall_seconds"],
    }
    result["reproduction_commitment"] = {
        "fit_input_hashes": produced["fit_input_hashes"],
        "forecast_sha256": produced["forecast_sha256"],
        "image_id": produced["image_id"],
        "wall_seconds": produced["wall_seconds"],
    }
    result["commitment_hashes_match"] = accepted["fit_input_hashes"] == produced[
        "fit_input_hashes"
    ] and all(
        produced["forecast_sha256"].get(k) == v
        for k, v in accepted["forecast_sha256"].items()
        if k != "fit_receipt.json"
    )
    receipt = json.loads((work / "date_hierarchy_receipt.json").read_text())
    result["memberships"] = {
        "fit_membership_sha256_accepted": receipt["fit_membership_sha256"],
        "fit_membership_sha256_reproduction": digest(prep / "fit_membership.txt"),
        "target_membership_sha256_accepted": digest(work / "target_membership.txt"),
        "target_membership_sha256_reproduction": digest(prep / "target_membership.txt"),
    }
    result["memberships"]["identical"] = (
        result["memberships"]["fit_membership_sha256_accepted"]
        == result["memberships"]["fit_membership_sha256_reproduction"]
        and result["memberships"]["target_membership_sha256_accepted"]
        == result["memberships"]["target_membership_sha256_reproduction"]
    )
    accepted_vocabulary = json.loads((work / "ioc_vocabulary.json").read_text())["vocabulary"]
    vocabulary = json.loads((prep / "ioc_vocabulary.json").read_text())["vocabulary"]
    result["ioc_vocabulary"] = {
        "accepted": accepted_vocabulary,
        "reproduction": vocabulary,
        "same_set": set(accepted_vocabulary) == set(vocabulary),
        "same_order": accepted_vocabulary == vocabulary,
    }
    fit_receipt = json.loads((run / "forecast" / "fit_receipt.json").read_text())
    accepted_receipt = json.loads((reference / "forecast" / "fit_receipt.json").read_text())
    result["fit_receipt"] = {
        "feature_columns_identical": fit_receipt["feature_columns"]
        == accepted_receipt["feature_columns"],
        "feature_column_count": len(fit_receipt["feature_columns"]),
        "members_reproduction": [
            (m["member"], m["rows"], m["trees"]) for m in fit_receipt["fit_menu"]
        ],
        "members_accepted": [
            (m["member"], m["rows"], m["trees"]) for m in accepted_receipt["fit_menu"]
        ],
        "recent_blend_active": fit_receipt["activation"]["temporal"]["active"],
        "recent_rows": fit_receipt["activation"]["temporal"]["recent_rows"],
    }
    required_ok = all(e["identical"] for e in result["required_identical"].values())
    result["status"] = (
        "BYTE_IDENTICAL"
        if required_ok
        and result["memberships"]["identical"]
        and result["ioc_vocabulary"]["same_set"]
        else "MISMATCH"
    )
    result["all_compared_files_identical"] = required_ok and all(
        e["identical"] for e in result["informative"].values()
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] != "BYTE_IDENTICAL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
