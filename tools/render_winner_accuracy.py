"""Derive aggregate winner-picking accuracy from the accepted ladder artifacts.

This tool reads only saved forecasts and labels. It does not fit, select, calibrate,
or issue a model. The matched population is the same identical priced cohort used by
``tennislab report --ladder`` and is checked against ``docs/ladder.json`` by year.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import ChainError, read_config
from tennislab.evaluation.ladder import (
    load_labels,
    load_rung,
    market_forecasts,
    rung_forecasts,
)

ACCEPTED_RUNS = {
    "ATP": Path("experiments/runs/TIER01/attempt_002/run"),
    "WTA": Path("experiments/runs/WTA02/attempt_002/run"),
}


def score_picks(
    ids: Sequence[str], probabilities: Mapping[str, float], labels: Mapping[str, Mapping[str, str]]
) -> dict[str, int | float]:
    """Score directional picks, giving an exact 0.5 forecast half credit."""
    correct = 0
    ties = 0
    for match_id in ids:
        probability = probabilities[match_id]
        outcome = int(labels[match_id]["a_won"])
        if probability == 0.5:
            ties += 1
        elif (probability > 0.5) == bool(outcome):
            correct += 1
    n = len(ids)
    return {
        "n": n,
        "correct": correct,
        "ties": ties,
        "accuracy": (correct + 0.5 * ties) / n,
    }


def build_accuracy(
    config: Mapping[str, Any],
    configs_dir: Path,
    archive_root: Path,
    ladder: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "definition": {
            "pick": "player A when p_a_wins > 0.5; player B when p_a_wins < 0.5",
            "tie": "p_a_wins == 0.5; reported separately and worth half credit",
            "accuracy": "(correct + 0.5 * ties) / n",
            "cohort": config["cohort"],
        },
        "source": {
            "ladder_config": "configs/ladder.json",
            "ladder_counts": "docs/ladder.json",
            "accepted_runs": {tour: str(path) for tour, path in ACCEPTED_RUNS.items()},
            "note": "saved forecasts and labels only; no fit, selection, calibration, or issuance",
        },
        "tours": {},
    }
    for tour, spec in config["tours"].items():
        if tour not in ACCEPTED_RUNS or tour not in ladder["tours"]:
            continue
        run_root = archive_root / ACCEPTED_RUNS[tour]
        labels = load_labels(run_root)
        rungs = [load_rung(configs_dir, name) for name in spec["rungs"]]
        reference = spec["reference"]
        references = config["references"]
        model_order = [rung.name for rung in rungs] + [reference]
        expected_rows = {
            int(row["year"]): int(row["n"]) for row in ladder["tours"][tour]["per_year"]
        }
        cache: dict[str, Any] = {}
        per_year: list[dict[str, Any]] = []
        totals = {name: {"n": 0, "correct": 0, "ties": 0} for name in model_order}
        for year in sorted(expected_rows):
            forecasts = {
                rung.name: rung_forecasts(rung, run_root, year, spec["learner"], cache)
                for rung in rungs
            }
            for name, reference_spec in references.items():
                forecasts[name] = market_forecasts(run_root, year, reference_spec["file"])
            ids = sorted(
                match_id
                for match_id in set.intersection(*(set(values) for values in forecasts.values()))
                if labels.get(match_id, {}).get("primary_target") == "1"
                and labels[match_id]["a_won"] in ("0", "1")
            )
            if len(ids) != expected_rows[year]:
                raise ChainError(
                    f"{tour} {year}: accuracy cohort has {len(ids)} rows; "
                    f"ladder has {expected_rows[year]}"
                )
            model_stats = {name: score_picks(ids, forecasts[name], labels) for name in model_order}
            for name, stats in model_stats.items():
                for field in ("n", "correct", "ties"):
                    totals[name][field] += int(stats[field])
            per_year.append({"year": year, "n": len(ids), "models": model_stats})
        overall = {}
        for name, counts in totals.items():
            n = counts["n"]
            overall[name] = {
                **counts,
                "accuracy": (counts["correct"] + 0.5 * counts["ties"]) / n,
            }
        result["tours"][tour] = {
            "model_order": model_order,
            "per_year": per_year,
            "overall": overall,
        }
    return result


def write_csv(path: Path, result: Mapping[str, Any]) -> None:
    fields = ["tour", "period", "year", "model", "n", "correct", "ties", "accuracy"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for tour, block in result["tours"].items():
            for row in block["per_year"]:
                for model in block["model_order"]:
                    writer.writerow(
                        {
                            "tour": tour,
                            "period": "year",
                            "year": row["year"],
                            "model": model,
                            **row["models"][model],
                        }
                    )
            for model in block["model_order"]:
                writer.writerow(
                    {
                        "tour": tour,
                        "period": "overall",
                        "year": "",
                        "model": model,
                        **block["overall"][model],
                    }
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/ladder.json"))
    parser.add_argument("--configs-dir", type=Path, default=Path("configs"))
    parser.add_argument("--ladder", type=Path, default=Path("docs/ladder.json"))
    parser.add_argument("--output-json", type=Path, default=Path("docs/winner_accuracy.json"))
    parser.add_argument("--output-csv", type=Path, default=Path("docs/winner_accuracy.csv"))
    archive = os.environ.get("TENNISLAB_ARCHIVE")
    parser.add_argument("--archive-root", type=Path, default=Path(archive) if archive else None)
    args = parser.parse_args()
    if args.archive_root is None:
        raise ChainError("pass --archive-root or set TENNISLAB_ARCHIVE")
    config = read_config(args.config)
    ladder = json.loads(args.ladder.read_text(encoding="utf-8"))
    result = build_accuracy(config, args.configs_dir, args.archive_root, ladder)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(args.output_csv, result)
    for tour, block in result["tours"].items():
        model = block["model_order"][-2]
        stats = block["overall"][model]
        print(
            tour,
            model,
            f"{stats['correct']}/{stats['n']}",
            f"ties={stats['ties']}",
            f"accuracy={stats['accuracy']:.6%}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
