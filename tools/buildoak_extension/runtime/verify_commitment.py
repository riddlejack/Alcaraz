"""Read-only reconstruction of a buildoak forecast commitment."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_commitment.py ATTEMPT AUTHORIZATION")
    attempt = Path(sys.argv[1]).resolve()
    authorization = Path(sys.argv[2]).resolve()
    auth = json.loads(authorization.read_text())
    commitment = json.loads((attempt / "FORECAST_COMMITMENT.json").read_text())
    if commitment["status"] != "forecast_complete_no_scores":
        raise ValueError("forecast commitment status mismatch")
    if (attempt / "FAILURE.json").exists():
        raise ValueError("attempt also contains failure receipt")
    if commitment["authorization_sha256"] != digest(authorization):
        raise ValueError("authorization commitment mismatch")
    if commitment["plan_sha256"] != digest(Path(auth["plan_path"])):
        raise ValueError("plan commitment mismatch")
    if commitment["tour"] != auth["tour"]:
        raise ValueError("tour commitment mismatch")
    for name, expected in commitment["fit_input_hashes"].items():
        if digest(attempt / name) != expected:
            raise ValueError("committed feature input changed: " + name)
    forecast = attempt / "forecast"
    actual = {path.name: digest(path) for path in sorted(forecast.iterdir()) if path.is_file()}
    if actual != commitment["forecast_sha256"]:
        raise ValueError("forecast artifact commitment mismatch")
    receipt = json.loads((forecast / "fit_receipt.json").read_text())
    if receipt["tour"] != auth["tour"] or receipt["fit_rows"] != auth["fit_rows"]:
        raise ValueError("fit receipt authorization mismatch")
    if receipt["target_rows"] != auth["target_rows"]:
        raise ValueError("forecast membership mismatch")
    with (forecast / "native_forecasts.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != auth["target_rows"] or len({row["match_id"] for row in rows}) != len(rows):
        raise ValueError("forecast row identity mismatch")
    target_membership = [
        Path(path) for path in auth["bindings"] if Path(path).name == "target_membership.txt"
    ]
    if target_membership:
        if len(target_membership) != 1:
            raise ValueError("ambiguous target membership binding")
        expected_keys = target_membership[0].read_text().splitlines()
        if len(expected_keys) != len(set(expected_keys)) or set(expected_keys) != {
            row["match_id"] for row in rows
        }:
            raise ValueError("forecast keys differ from frozen target membership")
    with (attempt / "target_features.csv").open() as handle:
        feature_rows = list(csv.DictReader(handle))
    identities = {row["match_id"]: str(int(float(row["player_a_id"]))) for row in feature_rows}
    if len(identities) != len(feature_rows) or set(identities) != {row["match_id"] for row in rows}:
        raise ValueError("feature/forecast identity membership mismatch")
    native_rows = 0
    fallback_rows = 0
    for row in rows:
        if str(int(float(row["canonical_a_source_id"]))) != identities[row["match_id"]]:
            raise ValueError("forecast canonical identity mismatch")
        if row["native_status"] == "native":
            probability = float(row["p_a_native"])
            if not math.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("invalid native probability")
            native_rows += 1
        elif row["native_status"] == "nonfinite_or_out_of_range":
            if row["p_a_native"]:
                raise ValueError("invalid native row must have blank probability")
            fallback_rows += 1
        else:
            raise ValueError("unrecognized native status")
    if receipt["native_rows"] != native_rows or native_rows + fallback_rows != auth["target_rows"]:
        raise ValueError("native/fallback count mismatch")
    identity_payload = "".join(f"{key}\t{identities[key]}\n" for key in sorted(identities)).encode()
    result = {
        "status": "PASS",
        "read_only": True,
        "tour": auth["tour"],
        "fit_rows": receipt["fit_rows"],
        "target_rows": receipt["target_rows"],
        "fit_members": len(receipt["fit_menu"]),
        "native_rows": native_rows,
        "reason_coded_fallback_rows": fallback_rows,
        "target_identity_sha256": hashlib.sha256(identity_payload).hexdigest(),
        "artifacts": sorted(actual),
        "commitment_sha256": digest(attempt / "FORECAST_COMMITMENT.json"),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
