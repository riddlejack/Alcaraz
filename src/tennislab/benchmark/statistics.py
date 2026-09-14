"""Equal-year scoring and shared weekly stationary-bootstrap inference."""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from tennislab.benchmark.core import BenchmarkError


@dataclass(frozen=True)
class ScoredRow:
    year: int
    week: str
    values: Mapping[str, float]


def log_loss(probability: float, outcome: int, clip: float = 1e-15) -> float:
    if outcome not in (0, 1) or not math.isfinite(probability):
        raise BenchmarkError("invalid scoring input")
    p = min(max(probability, clip), 1.0 - clip)
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1.0 - p))


def equal_year_means(rows: Sequence[ScoredRow]) -> dict[str, float]:
    by_year: defaultdict[int, list[ScoredRow]] = defaultdict(list)
    for row in rows:
        by_year[row.year].append(row)
    if not by_year:
        raise BenchmarkError("cannot summarize an empty cohort")
    names = tuple(rows[0].values)
    annual: dict[str, list[float]] = {name: [] for name in names}
    for year_rows in by_year.values():
        for name in names:
            annual[name].append(float(np.mean([row.values[name] for row in year_rows])))
    return {name: float(np.mean(values)) for name, values in annual.items()}


def _iso_monday(value: str) -> dt.date:
    year, week = (int(piece) for piece in value.split("-W"))
    return dt.date.fromisocalendar(year, week, 1)


def _week_grid(rows: Sequence[ScoredRow]) -> list[str]:
    mondays = [_iso_monday(row.week) for row in rows]
    start, stop = min(mondays), max(mondays)
    result: list[str] = []
    cursor = start
    while cursor <= stop:
        iso = cursor.isocalendar()
        result.append(f"{iso.year:04d}-W{iso.week:02d}")
        cursor += dt.timedelta(days=7)
    return result


def _stationary_indices(length: int, mean_block: int, rng: np.random.Generator) -> np.ndarray:
    if length <= 0 or mean_block <= 0:
        raise BenchmarkError("invalid stationary-bootstrap dimensions")
    indices = np.empty(length, dtype=int)
    indices[0] = int(rng.integers(length))
    restarts = rng.random(length - 1) < (1.0 / mean_block)
    fresh = rng.integers(length, size=length - 1)
    for index in range(1, length):
        indices[index] = int(fresh[index - 1]) if restarts[index - 1] else (indices[index - 1] + 1) % length
    return indices


def simultaneous_intervals(
    rows: Sequence[ScoredRow],
    contrasts: Mapping[str, tuple[str, str]],
    *,
    replicates: int,
    maximum_draws: int,
    seed: int,
    mean_block: int,
    level: float = 0.95,
    degenerate_tolerance: float = 1e-15,
) -> dict[str, object]:
    """Stationary bootstrap on full per-year week grids, shared across procedures."""
    if not contrasts:
        raise BenchmarkError("the multiplicity family is empty")
    points = equal_year_means(rows)
    point_contrasts = {
        name: points[left] - points[right] for name, (left, right) in contrasts.items()
    }
    by_year: defaultdict[int, list[ScoredRow]] = defaultdict(list)
    for row in rows:
        by_year[row.year].append(row)
    prepared: dict[int, tuple[list[str], dict[str, list[ScoredRow]]]] = {}
    for year, year_rows in sorted(by_year.items()):
        grid = _week_grid(year_rows)
        by_week: defaultdict[str, list[ScoredRow]] = defaultdict(list)
        for row in year_rows:
            by_week[row.week].append(row)
        prepared[year] = (grid, dict(by_week))

    rng = np.random.Generator(np.random.PCG64(seed))
    samples: dict[str, list[float]] = {name: [] for name in contrasts}
    draws = 0
    while len(next(iter(samples.values()))) < replicates and draws < maximum_draws:
        draws += 1
        annual: dict[str, list[float]] = {name: [] for name in points}
        valid = True
        for grid, by_week in prepared.values():
            chosen = _stationary_indices(len(grid), mean_block, rng)
            picked = [row for index in chosen for row in by_week.get(grid[int(index)], ())]
            if not picked:
                valid = False
                break
            for procedure in points:
                annual[procedure].append(float(np.mean([row.values[procedure] for row in picked])))
        if not valid:
            continue
        means = {name: float(np.mean(values)) for name, values in annual.items()}
        for name, (left, right) in contrasts.items():
            samples[name].append(means[left] - means[right])
    valid_replicates = len(next(iter(samples.values())))
    if valid_replicates != replicates:
        raise BenchmarkError(
            f"stationary bootstrap obtained {valid_replicates}/{replicates} valid draws in {draws} attempts"
        )

    arrays = {name: np.asarray(values, dtype=float) for name, values in samples.items()}
    standard_errors = {
        name: float(np.std(values, ddof=1)) if replicates > 1 else 0.0
        for name, values in arrays.items()
    }
    active = [name for name, value in standard_errors.items() if value > degenerate_tolerance]
    if active:
        t_values = np.column_stack(
            [
                (arrays[name] - point_contrasts[name]) / standard_errors[name]
                for name in active
            ]
        )
        critical = float(
            np.quantile(np.max(np.abs(t_values), axis=1), level, method="linear")
        )
    else:
        critical = 0.0
    intervals: dict[str, object] = {}
    for name, point in point_contrasts.items():
        se = standard_errors[name]
        degenerate = se <= degenerate_tolerance
        half_width = 0.0 if degenerate else critical * se
        intervals[name] = {
            "estimate": point,
            "standard_error": se,
            "lower": point - half_width,
            "upper": point + half_width,
            "degenerate": degenerate,
        }
    return {
        "point_means": points,
        "intervals": intervals,
        "critical_value": critical,
        "valid_replicates": valid_replicates,
        "draws_attempted": draws,
        "mean_block_weeks": mean_block,
        "seed": seed,
        "rng": "numpy.PCG64",
    }
