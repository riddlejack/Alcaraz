"""Reconstruct a saved BuildOak comparison without fitting or changing forecasts."""

import argparse
import csv
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream))


def unique(rows):
    result = {row["match_id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate match identity")
    return result


def components(p, y):
    q = np.clip(p, 1e-15, 1 - 1e-15)
    return np.column_stack(
        (
            -y * np.log(q) - (1 - y) * np.log1p(-q),
            (p - y) ** 2,
            np.where(p == 0.5, 0.5, (p > 0.5) == y),
        )
    )


def metrics(values, *, difference=False):
    result = dict(zip(("log_loss", "brier", "accuracy"), values.mean(axis=0).tolist(), strict=True))
    return {
        "n": len(values),
        **result,
        ("correct_credit_delta" if difference else "correct_credit"): float(values[:, 2].sum()),
    }


def paired_intervals(values, weeks, seed):
    dates = [dt.date.fromisocalendar(int(w[:4]), int(w[6:]), 1) for w in weeks]
    first, last = min(dates), max(dates)
    n = (last - first).days // 7 + 1
    indices = np.array([(day - first).days // 7 for day in dates])
    counts = np.bincount(indices, minlength=n)
    sums = np.stack(
        [np.bincount(indices, weights=values[:, j], minlength=n) for j in range(3)], axis=1
    )
    results = {}
    for length in (8, 4, 13):
        rng = np.random.Generator(np.random.PCG64(seed))
        draws = np.empty((5000, 3))
        for draw in draws:
            chosen = [int(rng.integers(n))]
            for _ in range(1, n):
                chosen.append(
                    int(rng.integers(n)) if rng.random() < 1 / length else (chosen[-1] + 1) % n
                )
            denominator = counts[chosen].sum()
            if not denominator:
                raise ValueError("empty bootstrap draw")
            # Preserve the scalar ATP and joint WTA original reduction orders.
            total = (
                np.array([sums[chosen, j].sum() for j in range(3)])
                if seed == 20260915
                else sums[chosen].sum(axis=0)
            )
            draw[:] = total / denominator
        results[str(length)] = {
            key: {
                "percentile_95": np.quantile(draws[:, j], [0.025, 0.975]).tolist(),
                "draw_sha256": hashlib.sha256(draws[:, j].astype("<f8").tobytes()).hexdigest(),
            }
            for j, key in enumerate(("log_loss", "brier", "accuracy"))
        }
        results[str(length)]["joint_draw_sha256"] = hashlib.sha256(
            draws.astype("<f8").tobytes()
        ).hexdigest()
    return {
        "seed": seed,
        "replicates": 5000,
        "grid_first_monday": str(first),
        "grid_last_monday": str(last),
        "grid_weeks": n,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--tour", choices=["ATP", "WTA"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    auth = json.loads(args.authorization.read_text())
    commitment_path = args.attempt / "FORECAST_COMMITMENT.json"
    commitment = json.loads(commitment_path.read_text())
    bindings = {
        str(args.authorization.resolve()): digest(args.authorization),
        str(commitment_path): digest(commitment_path),
        str(Path(__file__).resolve()): digest(__file__),
    }
    if commitment["authorization_sha256"] != digest(args.authorization):
        raise ValueError("authorization changed")
    for filename, expected in commitment["forecast_sha256"].items():
        path = args.attempt / "forecast" / filename
        if digest(path) != expected:
            raise ValueError(f"forecast binding mismatch: {path}")
        bindings[str(path)] = expected
    for path in auth["report_inputs"].values():
        observed = digest(path)
        if observed != auth["bindings"][path]:
            raise ValueError(f"input binding mismatch: {path}")
        bindings[path] = observed
    native = unique(read(args.attempt / "forecast/native_forecasts.csv"))
    incumbent = unique(
        [
            r
            for r in read(auth["report_inputs"]["g_predictions"])
            if r["tour"] == args.tour and r["year"] == "2024"
        ]
    )
    panel = unique(read(auth["report_inputs"]["panel"]))
    labels = unique(read(auth["report_inputs"]["labels"]))
    saved_path = args.attempt / "report/paired_rows.csv"
    saved = unique(read(saved_path))
    bindings[str(saved_path)] = digest(saved_path)
    expected_n = 2681 if args.tour == "ATP" else 2404
    if not (set(native) == set(incumbent) == set(saved) and len(native) == expected_n):
        raise ValueError("changed target denominator")
    source_path = auth["native_match_files"][-1]
    if digest(source_path) != auth["bindings"][source_path]:
        raise ValueError("native annual source changed")
    bindings[source_path] = digest(source_path)
    source_rows = read(source_path)
    source_targets = {r["tourney_id"] + "/" + str(int(r["match_num"])): r for r in source_rows}
    if len(source_targets) != len(source_rows):
        raise ValueError("duplicate native annual source key")
    source_disagreements = []
    records = []
    identities = set()
    for key in sorted(native):
        row, meta, g = native[key], panel[key], incumbent[key]
        a, b = int(meta["a_source_id"]), int(meta["b_source_id"])
        identity = (meta["tourney_id"], meta["round"], min(a, b), max(a, b))
        if identity in identities:
            raise ValueError("duplicate event/round/player pairing")
        identities.add(identity)
        if int(row["canonical_a_source_id"]) != min(a, b) or row["native_status"] != "native":
            raise ValueError("native orientation or coverage changed")
        external = float(row["p_a_native"])
        if a != min(a, b):
            external = 1 - external
        own, y = float(g["calibrated_incumbent"]), int(labels[key]["a_won"])
        if y != int(meta["a_won"].lower() == "true"):
            raise ValueError("panel/label conflict")
        source = source_targets[key]
        winner, loser = (a, b) if y else (b, a)
        if (int(source["winner_id"]), int(source["loser_id"])) != (winner, loser):
            source_disagreements.append(key)
        if not (0 <= own <= 1 and 0 <= external <= 1 and y in (0, 1)):
            raise ValueError("invalid score input")
        if (own, external, y) != (
            float(saved[key]["incumbent_p_a"]),
            float(saved[key]["external_p_a"]),
            int(saved[key]["a_won"]),
        ):
            raise ValueError("accepted row arithmetic mismatch")
        records.append(
            {
                "match_id": key,
                "incumbent_p_a": own,
                "external_p_a": external,
                "a_won": y,
                "tournament_week": g["tournament_week"],
                "event_id": meta["tourney_id"],
                "completed": meta["completed"].lower() == "true",
                "winner_disagreement": (own > 0.5) != (external > 0.5),
            }
        )
    y = np.array([r["a_won"] for r in records])
    a = np.array([r["incumbent_p_a"] for r in records])
    b = np.array([r["external_p_a"] for r in records])
    va, vb = components(a, y), components(b, y)
    delta = va - vb
    completed = np.array([r["completed"] for r in records])
    disagree = np.array([r["winner_disagreement"] for r in records])
    report = {
        "scope": f"unchanged_exposed_{args.tour}_2024_saved_forecast_reconstruction",
        "bindings": bindings,
        "primary": {
            "incumbent": metrics(va),
            "external": metrics(vb),
            "difference": metrics(delta, difference=True),
        },
        "coverage": {
            "qualified_targets": expected_n,
            "native": len(native),
            "fallback": 0,
            "unique_event_round_pairs": len(identities),
            "editions": len({r["event_id"] for r in records}),
        },
        "source_label_check": {
            "native_raw_year_n": len(source_rows),
            "qualified_n": expected_n,
            "winner_identity_disagreements": source_disagreements,
        },
        "winner_disagreements": {
            "n": int(disagree.sum()),
            "incumbent_correct": float(va[disagree, 2].sum()),
            "external_correct": float(vb[disagree, 2].sum()),
        },
        "completed_only": {
            "incumbent": metrics(va[completed]),
            "external": metrics(vb[completed]),
            "difference": metrics(delta[completed], difference=True),
        },
        "uncertainty": paired_intervals(
            delta,
            [r["tournament_week"] for r in records],
            20260915 if args.tour == "ATP" else 20260917,
        ),
        "orientation_score_control_max_error": {
            "incumbent": float(np.max(np.abs(va - components(1 - a, 1 - y)))),
            "external": float(np.max(np.abs(vb - components(1 - b, 1 - y)))),
        },
        "ties": {"incumbent": int((a == 0.5).sum()), "external": int((b == 0.5).sum())},
        "runtime_seconds": time.monotonic() - started,
    }
    accepted_path = args.attempt / "report/comparison.json"
    accepted = json.loads(accepted_path.read_text())
    bindings[str(accepted_path)] = digest(accepted_path)
    for system in ("incumbent", "external"):
        for metric in ("log_loss", "brier", "accuracy"):
            np.testing.assert_allclose(
                report["primary"][system][metric],
                accepted["primary"][system][metric],
                rtol=0,
                atol=1e-14,
            )
            sensitivity = (
                accepted["secondary"]["completed_only"]
                if args.tour == "ATP"
                else accepted["secondary_exploratory"]["completed_only"]
            )
            np.testing.assert_allclose(
                report["completed_only"][system][metric],
                sensitivity[system][metric],
                rtol=0,
                atol=1e-14,
            )
    for length in ("8", "4", "13"):
        observed = report["uncertainty"]["results"][length]
        original = accepted["primary"]["uncertainty"]["results"][length]
        if args.tour == "ATP":
            np.testing.assert_allclose(
                observed["log_loss"]["percentile_95"], original["percentile_95"], rtol=0, atol=1e-14
            )
            if observed["log_loss"]["draw_sha256"] != original["draw_sha256"]:
                raise ValueError("ATP original scalar draw hash mismatch")
        else:
            for metric in ("log_loss", "brier", "accuracy"):
                np.testing.assert_allclose(
                    observed[metric]["percentile_95"], original[metric], rtol=0, atol=1e-14
                )
            if observed["joint_draw_sha256"] != original["draw_sha256"]:
                raise ValueError("WTA original joint draw hash mismatch")
    report["accepted_aggregate_reproduction"] = (
        "PASS_with_absolute_numeric_tolerance_1e-14_and_exact_original_draw_hashes"
    )
    args.output.mkdir(parents=True, exist_ok=False)
    for filename, rows in (
        ("paired_rows.csv", records),
        ("winner_disagreements.csv", [r for r in records if r["winner_disagreement"]]),
    ):
        with (args.output / filename).open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(rows)
    report["outputs"] = {p.name: digest(p) for p in args.output.glob("*.csv")}
    (args.output / "reconstruction.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "tour": args.tour,
                "primary": report["primary"],
                "runtime_seconds": report["runtime_seconds"],
            }
        )
    )


if __name__ == "__main__":
    main()
