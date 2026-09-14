"""The model ladder: per tour and per year, each rung against the next and against the
market, on identical priced populations.

Reads only completed run trees (the pipeline's selected calibrated forecasts, the
market forecasts, the feature table for the Elo rung, and the label file). One
estimand per table: match-weighted and equal-year means are separate columns; the
interval type is declared in ``configs/ladder.json`` and never switched afterwards;
numbers are rounded to the declared decimals.

This module scores target-year outcomes and therefore lives in ``evaluation``; nothing
before the report barrier imports it.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.chain.common import ChainError, read_config, relative_to_root
from tennislab.config import workspace
from tennislab.evidence import host_placeholders, write_evidence

CLIP = 1e-15


@dataclass(frozen=True)
class Rung:
    name: str
    description: str
    forecast: Mapping[str, Any]
    bundle: str | None = None
    learner: str | None = None


def load_rung(configs_dir: Path, name: str) -> Rung:
    document = read_config(configs_dir / f"{name}.json")
    return Rung(
        name=document["name"],
        description=document["description"],
        forecast=document["forecast"],
        bundle=document.get("bundle"),
        learner=document.get("learner"),
    )


def _read_forecasts(path: Path) -> dict[str, float]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    out: dict[str, float] = {}
    for row in rows:
        p = float(row["p_a_wins"])
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ChainError(f"non-probability in {path}: {row}")
        out[row["match_id"]] = p
    return out


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def load_labels(run_root: Path) -> dict[str, dict[str, str]]:
    with (run_root / "features" / "labels.csv").open(newline="", encoding="utf-8") as handle:
        return {row["match_id"]: row for row in csv.DictReader(handle)}


def pooled_elo_from_features(run_root: Path, columns: Sequence[str]) -> dict[int, dict[str, float]]:
    """The C1 pooled Elo probability per match, by calendar year, from the feature table."""
    out: dict[int, dict[str, float]] = {}
    overall, surface = columns
    with (run_root / "features" / "features.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            year = int(row["calendar_year"])
            p = 0.5 * _sigmoid(float(row[overall])) + 0.5 * _sigmoid(float(row[surface]))
            out.setdefault(year, {})[row["match_id"]] = p
    return out


def rung_forecasts(
    rung: Rung, run_root: Path, year: int, learner: str, cache: dict[str, Any]
) -> dict[str, float]:
    kind = rung.forecast["kind"]
    if kind == "selected_calibrated":
        path = (
            run_root
            / "pipeline"
            / "selected"
            / str(year)
            / (rung.learner or learner)
            / f"{rung.bundle}.csv"
        )
        return _read_forecasts(path)
    if kind == "pooled_elo_from_features":
        key = "pooled_elo"
        if key not in cache:
            cache[key] = pooled_elo_from_features(run_root, rung.forecast["columns"])
        return cache[key].get(year, {})
    raise ChainError(f"unknown forecast kind {kind!r} for rung {rung.name}")


def market_forecasts(run_root: Path, year: int, file: str) -> dict[str, float]:
    return _read_forecasts(run_root / "pipeline" / "market" / str(year) / file)


def log_loss_terms(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, int]:
    clipped = np.clip(p, CLIP, 1.0 - CLIP)
    clips = int(np.sum((p < CLIP) | (p > 1.0 - CLIP)))
    return -(y * np.log(clipped) + (1 - y) * np.log(1 - clipped)), clips


def bootstrap_mean(
    values_by_year: Sequence[np.ndarray], replicates: int, seed: int, level: float
) -> tuple[float, float]:
    """Percentile interval for the match-weighted mean, resampling matches within year."""
    rng = np.random.default_rng(seed)
    total = sum(len(v) for v in values_by_year)
    means = np.empty(replicates)
    for r in range(replicates):
        acc = 0.0
        for v in values_by_year:
            if len(v):
                acc += float(np.sum(v[rng.integers(0, len(v), len(v))]))
        means[r] = acc / total
    alpha = (1.0 - level) / 2.0
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))


def build_ladder(
    config: Mapping[str, Any], configs_dir: Path, run_roots: Mapping[str, Path]
) -> dict[str, Any]:
    interval = config["interval"]
    decimals = int(config["rounding_decimals"])
    result: dict[str, Any] = {"interval": interval, "rounding_decimals": decimals, "tours": {}}
    for tour, spec in config["tours"].items():
        if tour not in run_roots:
            continue
        run_root = run_roots[tour]
        rungs = [load_rung(configs_dir, name) for name in spec["rungs"]]
        reference = spec["reference"]
        references = {name: config["references"][name] for name in config["references"]}
        labels = load_labels(run_root)
        years = sorted(
            int(p.name) for p in (run_root / "pipeline" / "selected").iterdir() if p.name.isdigit()
        )
        cache: dict[str, Any] = {}
        columns = [rung.name for rung in rungs] + list(references)
        per_year: list[dict[str, Any]] = []
        terms: dict[str, list[np.ndarray]] = {name: [] for name in columns}
        clips: dict[str, int] = dict.fromkeys(columns, 0)
        for year in years:
            forecasts = {
                rung.name: rung_forecasts(rung, run_root, year, spec["learner"], cache)
                for rung in rungs
            }
            for name, ref in references.items():
                forecasts[name] = market_forecasts(run_root, year, ref["file"])
            ids = set.intersection(*(set(f) for f in forecasts.values()))
            ids = sorted(
                m
                for m in ids
                if labels.get(m, {}).get("primary_target") == "1"
                and labels[m]["a_won"] in ("0", "1")
            )
            if not ids:
                raise ChainError(f"{tour} {year}: empty identical priced population")
            y = np.array([int(labels[m]["a_won"]) for m in ids], dtype=float)
            row: dict[str, Any] = {"tour": tour, "year": year, "n": len(ids)}
            year_terms: dict[str, np.ndarray] = {}
            for name in columns:
                p = np.array([forecasts[name][m] for m in ids], dtype=float)
                t, c = log_loss_terms(p, y)
                year_terms[name] = t
                terms[name].append(t)
                clips[name] += c
                row[f"log_loss_{name}"] = float(np.mean(t))
            for i, rung in enumerate(rungs):
                nxt = rungs[i + 1].name if i + 1 < len(rungs) else None
                if nxt:
                    row[f"delta_{rung.name}_minus_{nxt}"] = float(
                        np.mean(year_terms[rung.name] - year_terms[nxt])
                    )
                row[f"delta_{rung.name}_minus_{reference}"] = float(
                    np.mean(year_terms[rung.name] - year_terms[reference])
                )
            per_year.append(row)
        pooled: dict[str, Any] = {
            "tour": tour,
            "years": years,
            "n": int(sum(len(t) for t in terms[columns[0]])),
        }
        for name in columns:
            all_terms = np.concatenate(terms[name])
            pooled[f"log_loss_{name}_match_weighted"] = float(np.mean(all_terms))
            pooled[f"log_loss_{name}_equal_year"] = float(
                np.mean([np.mean(t) for t in terms[name]])
            )
            pooled[f"clip_count_{name}"] = clips[name]
        contrasts: list[dict[str, Any]] = []
        for i, rung in enumerate(rungs):
            targets = [rungs[i + 1].name] if i + 1 < len(rungs) else []
            targets.append(reference)
            for other in targets:
                diffs = [a - b for a, b in zip(terms[rung.name], terms[other], strict=True)]
                lower, upper = bootstrap_mean(
                    diffs,
                    int(interval["replicates"]),
                    int(interval["seed"]),
                    float(interval["level"]),
                )
                contrasts.append(
                    {
                        "contrast": f"{rung.name}_minus_{other}",
                        "match_weighted_delta": float(np.mean(np.concatenate(diffs))),
                        "equal_year_delta": float(np.mean([np.mean(d) for d in diffs])),
                        "years_negative": int(sum(np.mean(d) < 0 for d in diffs)),
                        "years": len(diffs),
                        "interval_lower": lower,
                        "interval_upper": upper,
                    }
                )
        result["tours"][tour] = {
            "run_root": str(run_root),
            "rungs": [{"name": r.name, "description": r.description} for r in rungs],
            "reference": reference,
            "per_year": per_year,
            "pooled": pooled,
            "contrasts": contrasts,
        }
    return result


def degrees_of_freedom_summary(registries_dir: Path) -> dict[str, Any]:
    """How many recorded passes touched the development windows (SCAR_TISSUE B8)."""
    with (registries_dir / "leaderboard.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    ledger = [
        json.loads(line)
        for line in (registries_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_cohort: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for row in rows:
        by_cohort[row["cohort_id"]] = by_cohort.get(row["cohort_id"], 0) + 1
        family = row["entry_id"].split("-")[0]
        by_family[family] = by_family.get(family, 0) + 1
    overlap_2017_2024 = sum(
        count
        for cohort, count in by_cohort.items()
        if any(str(year) in cohort for year in range(2017, 2025))
    )
    return {
        "leaderboard_entries": len(rows),
        "experiment_ledger_entries": len(ledger),
        "leaderboard_entries_on_cohorts_naming_a_year_in_2017_2024": overlap_2017_2024,
        "entries_by_cohort": dict(sorted(by_cohort.items(), key=lambda kv: -kv[1])),
        "entries_by_family": dict(sorted(by_family.items(), key=lambda kv: -kv[1])),
        "note": "Every entry is an exposed pass over development data; years are robustness evidence, not replications. Nothing on disk is holdout.",
    }


def render_markdown(ladder: Mapping[str, Any], dof: Mapping[str, Any] | None) -> str:
    d = int(ladder["rounding_decimals"])
    iv = ladder["interval"]
    lines = [
        "# Results",
        "",
        "Generated by `tennislab report --ladder`; do not edit by hand. Log loss, lower is",
        "better. Every number on a row is computed on the same matches (primary targets present",
        f"in every rung's forecast file and priced by the market). Intervals: {iv['type']},",
        f"{iv['replicates']} replicates, seed {iv['seed']}, {int(iv['level'] * 100)}% percentile; conditional on",
        "the saved forecasts, excluding fitting and selection variance. Rounded to",
        f"{d} decimals. Years are robustness evidence, not replications.",
        "",
    ]
    for tour, block in ladder["tours"].items():
        rungs = [r["name"] for r in block["rungs"]]
        ref = block["reference"]
        cols = (
            rungs + [ref, "pinnacle_calibrated"] if ref != "pinnacle_calibrated" else rungs + [ref]
        )
        cols = [c for c in cols if f"log_loss_{c}" in block["per_year"][0]]
        lines += [f"## {tour}", "", "Rungs:", ""]
        for r in block["rungs"]:
            lines.append(f"- **{r['name']}**: {r['description']}")
        lines += [
            "",
            "### Per year",
            "",
            "| year | n | " + " | ".join(cols) + " |",
            "|---|---:|" + "---:|" * len(cols),
        ]
        for row in block["per_year"]:
            lines.append(
                f"| {row['year']} | {row['n']:,} | "
                + " | ".join(f"{row['log_loss_' + c]:.{d}f}" for c in cols)
                + " |"
            )
        p = block["pooled"]
        lines.append(
            f"| **all, match-weighted** | {p['n']:,} | "
            + " | ".join(f"**{p['log_loss_' + c + '_match_weighted']:.{d}f}**" for c in cols)
            + " |"
        )
        lines.append(
            f"| all, equal-year mean | {len(p['years'])} years | "
            + " | ".join(f"{p['log_loss_' + c + '_equal_year']:.{d}f}" for c in cols)
            + " |"
        )
        lines += [
            "",
            "### Paired contrasts (log loss delta, negative favours the first)",
            "",
            "| contrast | match-weighted | equal-year | years negative | interval |",
            "|---|---:|---:|---:|---:|",
        ]
        for c in block["contrasts"]:
            lines.append(
                f"| {c['contrast']} | {c['match_weighted_delta']:+.{d}f} | {c['equal_year_delta']:+.{d}f} | "
                f"{c['years_negative']}/{c['years']} | [{c['interval_lower']:+.{d}f}, {c['interval_upper']:+.{d}f}] |"
            )
        lines.append("")
    if dof:
        lines += [
            "## Research degrees of freedom",
            "",
            f"- Leaderboard entries in the archive: {dof['leaderboard_entries']}",
            f"- Experiment ledger entries: {dof['experiment_ledger_entries']}",
            f"- Leaderboard entries on cohorts naming a year in 2017–2024: {dof['leaderboard_entries_on_cohorts_naming_a_year_in_2017_2024']}",
            "",
            "| family | entries |",
            "|---|---:|",
        ]
        for family, count in list(dof["entries_by_family"].items())[:25]:
            lines.append(f"| {family} | {count} |")
        lines += ["", dof["note"], ""]
    return "\n".join(lines)


def write_csv(path: Path, ladder: Mapping[str, Any], decimals: int) -> None:
    rows: list[dict[str, Any]] = []
    for block in ladder["tours"].values():
        for row in block["per_year"]:
            rows.append(
                {k: (round(v, decimals) if isinstance(v, float) else v) for k, v in row.items()}
            )
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_ladder_json(output: Path, ladder: Mapping[str, Any]) -> None:
    """``run_root`` names the host; the tracked file carries placeholders and the original
    goes to ``local/evidence/`` under the workspace (see :mod:`tennislab.evidence`)."""
    archive = os.environ.get("TENNISLAB_ARCHIVE")
    root = workspace().root
    placeholders = host_placeholders(
        repo_root=root, archive_root=Path(archive) if archive else None
    )
    text = json.dumps(ladder, indent=2, sort_keys=True) + "\n"
    write_evidence(root, relative_to_root(output, label="output_json"), text, placeholders)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/ladder.json"))
    parser.add_argument("--configs-dir", type=Path, default=Path("configs"))
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        metavar="TOUR=RUN_ROOT",
        help="a completed run root (the directory holding features/ and pipeline/)",
    )
    parser.add_argument("--registries", type=Path, default=Path("data/registries"))
    parser.add_argument("--output-markdown", type=Path, default=Path("docs/RESULTS.md"))
    parser.add_argument("--output-csv", type=Path, default=Path("docs/ladder.csv"))
    parser.add_argument("--output-json", type=Path, default=Path("docs/ladder.json"))
    args = parser.parse_args(argv)
    if not args.run:
        raise ChainError("pass at least one --run TOUR=RUN_ROOT")
    run_roots = {}
    for item in args.run:
        tour, _, root = item.partition("=")
        run_roots[tour.upper()] = Path(root)
    config = read_config(args.config)
    ladder = build_ladder(config, args.configs_dir, run_roots)
    dof = degrees_of_freedom_summary(args.registries) if args.registries.is_dir() else None
    ladder["research_degrees_of_freedom"] = dof
    args.output_markdown.write_text(render_markdown(ladder, dof), encoding="utf-8")
    write_csv(args.output_csv, ladder, int(config["rounding_decimals"]))
    write_ladder_json(args.output_json, ladder)
    for tour, block in ladder["tours"].items():
        p = block["pooled"]
        print(
            tour,
            "n",
            p["n"],
            {k: round(v, 4) for k, v in p.items() if k.endswith("_match_weighted")},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
