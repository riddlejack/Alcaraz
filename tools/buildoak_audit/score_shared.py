"""Score a committed shared-data WTA diagnostic against immutable accepted forecasts."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from tools.buildoak_audit.reconstruct import (
    components,
    digest,
    metrics,
    paired_intervals,
    read,
    unique,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commitment_path = args.attempt / "FORECAST_COMMITMENT.json"
    commitment = json.loads(commitment_path.read_text())
    if commitment["status"] != "forecast_complete_no_scores":
        raise ValueError("missing forecast commitment")
    authorization = args.attempt / "authorization_copy.json"
    if digest(authorization) != commitment["authorization_sha256"]:
        raise ValueError("changed forecast authorization")
    auth = json.loads(authorization.read_text())
    scoring_paths = (
        args.baseline,
        args.panel,
        Path(__file__).resolve(),
        Path(__file__).with_name("reconstruct.py").resolve(),
    )
    for path in scoring_paths:
        if digest(path) != auth["audit_scoring_bindings"].get(str(path.resolve())):
            raise ValueError(f"unbound scoring input or code: {path}")
    bindings = {
        str(commitment_path): digest(commitment_path),
        str(authorization): digest(authorization),
        str(args.baseline): digest(args.baseline),
        str(args.panel): digest(args.panel),
        str(Path(__file__).with_name("reconstruct.py").resolve()): digest(
            Path(__file__).with_name("reconstruct.py")
        ),
        str(Path(__file__).resolve()): digest(__file__),
    }
    for name, expected in commitment["forecast_sha256"].items():
        path = args.attempt / "forecast" / name
        if digest(path) != expected:
            raise ValueError(f"changed committed artifact: {path}")
        bindings[str(path)] = expected
    baseline = unique(read(args.baseline))
    panel = unique(read(args.panel))
    forecasts = unique(read(args.attempt / "forecast/native_forecasts.csv"))
    if set(baseline) != set(forecasts) or len(forecasts) != 2404:
        raise ValueError("shared-data denominator mismatch")
    records = []
    for key in sorted(baseline):
        original, native, meta = baseline[key], forecasts[key], panel[key]
        canonical = min(int(meta["a_source_id"]), int(meta["b_source_id"]))
        if canonical != int(native["canonical_a_source_id"]) or native["native_status"] != "native":
            raise ValueError("native coverage or orientation mismatch")
        probability = float(native["p_a_native"])
        if int(meta["a_source_id"]) != canonical:
            probability = 1 - probability
        if not 0 <= probability <= 1:
            raise ValueError("invalid native probability")
        record = dict(original)
        record["external_full_system_p_a"] = record.pop("external_p_a")
        record["external_shared_data_p_a"] = probability
        record["winner_disagreement"] = (float(record["incumbent_p_a"]) > 0.5) != (
            probability > 0.5
        )
        records.append(record)
    labels = np.array([int(r["a_won"]) for r in records])
    weeks = [r["tournament_week"] for r in records]
    values = {
        name: components(np.array([float(r[field]) for r in records]), labels)
        for name, field in (
            ("incumbent", "incumbent_p_a"),
            ("external_full_system", "external_full_system_p_a"),
            ("external_shared_data", "external_shared_data_p_a"),
        )
    }
    completed = np.array([r["completed"].lower() == "true" for r in records])
    disagreement = np.array([r["winner_disagreement"] for r in records])
    contrasts = {}
    for name, left, right in (
        ("primary_full_system_incumbent_minus_external", "incumbent", "external_full_system"),
        ("controlled_shared_data_incumbent_minus_external", "incumbent", "external_shared_data"),
        (
            "input_intervention_external_shared_minus_full",
            "external_shared_data",
            "external_full_system",
        ),
    ):
        delta = values[left] - values[right]
        contrasts[name] = {
            "point": metrics(delta, difference=True),
            "uncertainty": paired_intervals(delta, weeks, 20260917),
            "completed_only": metrics(delta[completed], difference=True),
        }
    report = {
        "scope": "exposed_WTA2024_full_system_primary_plus_controlled_shared_data",
        "bindings": bindings,
        "metrics": {name: metrics(value) for name, value in values.items()},
        "contrasts": contrasts,
        "native_coverage": {"n": len(records), "native": len(records), "fallback": 0},
        "shared_data_winner_disagreements": {
            "n": int(disagreement.sum()),
            "incumbent_correct": float(values["incumbent"][disagreement, 2].sum()),
            "external_correct": float(values["external_shared_data"][disagreement, 2].sum()),
        },
        "limitations": [
            "fixed-forecast conditional uncertainty",
            "exposed recipes and development",
            "shared-data control does not replace primary full-system comparison",
            "declared historical D-2 reported-date proxies, not verified publication clocks",
            "input intervention combines history, observation cleaning and final supervised membership",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=False)
    for name, rows in (
        ("paired_rows.csv", records),
        ("winner_disagreements.csv", [r for r in records if r["winner_disagreement"]]),
    ):
        with (args.output / name).open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(rows)
    report["outputs"] = {p.name: digest(p) for p in args.output.glob("*.csv")}
    (args.output / "comparison.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    print(json.dumps(report["metrics"]))


if __name__ == "__main__":
    main()
