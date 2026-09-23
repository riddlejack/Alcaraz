"""Paired, post-commitment scoring for the one frozen extension cohort."""

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    with Path(path).open() as f:
        return list(csv.DictReader(f))


def components(p, y):
    clipped = np.clip(p, 1e-15, 1 - 1e-15)
    return np.column_stack(
        (
            -y * np.log(clipped) - (1 - y) * np.log1p(-clipped),
            (p - y) ** 2,
            np.where(p == 0.5, 0.5, (p > 0.5) == y),
        )
    )


def bootstrap(deltas, weeks):
    dates = [dt.date.fromisocalendar(int(w[:4]), int(w[6:]), 1) for w in weeks]
    first, last = min(dates), max(dates)
    n = (last - first).days // 7 + 1
    idx = np.array([(d - first).days // 7 for d in dates])
    sums = np.column_stack([np.bincount(idx, weights=deltas[:, j], minlength=n) for j in range(3)])
    counts = np.bincount(idx, minlength=n)
    output = {}
    for length in [8, 4, 13]:
        rng = np.random.Generator(np.random.PCG64(20260917))
        draws = np.empty((5000, 3))
        for b in range(5000):
            choice = np.empty(n, dtype=int)
            choice[0] = rng.integers(n)
            for i in range(1, n):
                choice[i] = (
                    rng.integers(n) if rng.random() < 1 / length else (choice[i - 1] + 1) % n
                )
            denominator = counts[choice].sum()
            if denominator == 0:
                raise ValueError("empty bootstrap draw")
            draws[b] = sums[choice].sum(axis=0) / denominator
        output[str(length)] = {
            name: np.quantile(draws[:, j], [0.025, 0.975]).tolist()
            for j, name in enumerate(["log_loss", "brier", "accuracy"])
        }
        output[str(length)]["draw_sha256"] = hashlib.sha256(
            draws.astype("<f8").tobytes()
        ).hexdigest()
    return {
        "method": "stationary calendar-week bootstrap, paired match-weighted ratio",
        "primary_mean_block_weeks": 8,
        "replicates": 5000,
        "seed": 20260917,
        "grid_first_monday": first.isoformat(),
        "grid_last_monday": last.isoformat(),
        "grid_weeks": n,
        "nonempty_weeks": len(set(weeks)),
        "results": output,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("attempt", type=Path)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    attempt = args.attempt.resolve()
    auth_path = attempt / "authorization_copy.json"
    auth = json.loads(auth_path.read_text())
    barrier_path = attempt / "FORECAST_COMMITMENT.json"
    barrier = json.loads(barrier_path.read_text())
    if barrier["status"] != "forecast_complete_no_scores" or barrier[
        "authorization_sha256"
    ] != digest(auth_path):
        raise ValueError("commitment authorization mismatch")
    for name, expected in barrier["forecast_sha256"].items():
        if digest(attempt / "forecast" / name) != expected:
            raise ValueError("committed forecast artifact changed")
    if auth["bindings"].get(str(Path(__file__).resolve())) != digest(__file__):
        raise ValueError("scorer code not frozen")
    for name in ["target_features.csv", "training_features.csv"]:
        if digest(attempt / name) != barrier["fit_input_hashes"][name]:
            raise ValueError("committed feature input changed")
    membership_path = args.preparation / "target_membership.txt"
    if auth["bindings"].get(str(membership_path)) != digest(membership_path):
        raise ValueError("target membership binding mismatch")
    preparation = json.loads((args.preparation / "preparation.json").read_text())
    if auth["bindings"].get(str(args.preparation / "preparation.json")) != digest(
        args.preparation / "preparation.json"
    ):
        raise ValueError("preparation changed")
    for path in preparation["report_inputs"].values():
        if digest(path) != auth["bindings"].get(path):
            raise ValueError("report input binding mismatch")
    g_rows = [
        r
        for r in rows(preparation["report_inputs"]["g_predictions"])
        if r["tour"] == "WTA" and r["year"] == "2024"
    ]
    g = {r["match_id"]: r for r in g_rows}
    panel = {r["match_id"]: r for r in rows(preparation["report_inputs"]["panel"])}
    labels = {r["match_id"]: r for r in rows(preparation["report_inputs"]["labels"])}
    native_rows = rows(attempt / "forecast/native_forecasts.csv")
    native = {r["match_id"]: r for r in native_rows}
    features = {r["match_id"]: r for r in rows(attempt / "target_features.csv")}
    expected = set((args.preparation / "target_membership.txt").read_text().splitlines())
    if (
        set(g) != set(native)
        or set(g) != expected
        or len(native_rows) != len(native)
        or len(g_rows) != len(g)
    ):
        raise ValueError("target membership mismatch")
    records = []
    for key in sorted(g):
        meta, prediction, reference = panel[key], native[key], g[key]
        canonical = min(int(meta["a_source_id"]), int(meta["b_source_id"]))
        if int(prediction["canonical_a_source_id"]) != canonical:
            raise ValueError("orientation mismatch")
        p = float(prediction["p_a_native"]) if prediction["p_a_native"] else float("nan")
        valid = bool(np.isfinite(p) and 0 <= p <= 1 and prediction["native_status"] == "native")
        if valid:
            if canonical != int(meta["a_source_id"]):
                p = 1 - p
        else:
            if (
                prediction["native_status"] != "nonfinite_or_out_of_range"
                or prediction["p_a_native"]
            ):
                raise ValueError("undeclared native fallback reason or payload")
            p = float(reference["raw_k32_pooled"])
        own = float(reference["calibrated_incumbent"])
        y = int(labels[key]["a_won"])
        if not 0 <= p <= 1 or not 0 <= own <= 1 or y not in [0, 1]:
            raise ValueError("invalid probability/label")
        feature = features[key]
        # Career support reconstructed symmetrically from native snapshot sum/diff.
        total = float(feature["career_matches_sum"])
        difference = float(feature["career_matches_diff"])
        support = (total - abs(difference)) / 2
        records.append(
            {
                "match_id": key,
                "incumbent_p_a": own,
                "external_p_a": p,
                "native": valid,
                "native_status": prediction["native_status"],
                "a_won": y,
                "tournament_week": reference["tournament_week"],
                "event_id": meta["tourney_id"],
                "surface": meta["surface"],
                "completed": meta["completed"].lower() == "true",
                "minimum_native_history_matches": support,
                "history_support": "under_50" if support < 50 else "50_plus",
                "winner_disagreement": bool((own > 0.5) != (p > 0.5) and own != 0.5 and p != 0.5),
            }
        )
    a = np.array([r["incumbent_p_a"] for r in records])
    b = np.array([r["external_p_a"] for r in records])
    y = np.array([r["a_won"] for r in records])
    sa, sb = components(a, y), components(b, y)
    delta = sa - sb
    names = ["log_loss", "brier", "accuracy"]

    def summary(mask):
        mask = np.asarray(mask)
        if not mask.any():
            return {"n": 0, "incumbent": None, "external": None, "difference": None}
        return {
            "n": int(mask.sum()),
            "incumbent": dict(zip(names, sa[mask].mean(axis=0).tolist(), strict=True)),
            "external": dict(zip(names, sb[mask].mean(axis=0).tolist(), strict=True)),
            "difference": dict(zip(names, delta[mask].mean(axis=0).tolist(), strict=True)),
        }

    primary = summary(np.ones(len(records), dtype=bool))
    primary["uncertainty"] = bootstrap(delta, [r["tournament_week"] for r in records])
    slices = {
        "native_only": summary([r["native"] for r in records]),
        "completed_only": summary([r["completed"] for r in records]),
    }
    for field in ["surface", "history_support"]:
        for value in sorted({r[field] for r in records}):
            slices[field + ":" + value] = summary([r[field] == value for r in records])
    disagree = np.array([r["winner_disagreement"] for r in records])
    report = {
        "scope": "exposed retrospective WTA2024 full-system historical adaptation",
        "difference_direction": "Alcaraz minus external; lower loss and higher accuracy favor Alcaraz",
        "primary": primary,
        "native_coverage": {"rows": sum(r["native"] for r in records), "total": len(records)},
        "fallback_rows": sum(not r["native"] for r in records),
        "secondary_exploratory": slices,
        "winner_disagreements": {
            "n": int(disagree.sum()),
            "incumbent_correct": float(sa[disagree, 2].sum()),
            "external_correct": float(sb[disagree, 2].sum()),
        },
        "ties": {"incumbent": int((a == 0.5).sum()), "external": int((b == 0.5).sum())},
        "clipped": {
            "incumbent": int((a != np.clip(a, 1e-15, 1 - 1e-15)).sum()),
            "external": int((b != np.clip(b, 1e-15, 1 - 1e-15)).sum()),
        },
        "event_editions": len({r["event_id"] for r in records}),
        "forecast_commitment_sha256": digest(barrier_path),
        "scorer_sha256": digest(__file__),
    }
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "comparison.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    for name, subset in [
        ("paired_rows.csv", records),
        ("winner_disagreements.csv", [r for r in records if r["winner_disagreement"]]),
        ("fallback_membership.csv", [r for r in records if not r["native"]]),
    ]:
        with (args.output / name).open("w") as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(subset)
    print(json.dumps(primary, indent=2))


if __name__ == "__main__":
    main()
