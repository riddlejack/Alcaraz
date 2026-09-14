"""Proper-score arithmetic as pure functions over arrays.

Nothing here reads a file or knows what a match is. ``tennislab.evaluation.report`` is
the only module that pairs these functions with target-year outcomes; every function
takes probabilities and 0/1 outcomes (or their per-row differences) that the caller has
already aligned, and returns arrays or plain numbers. The arithmetic is the archive
reporter's, unchanged: log loss clips to ``[clip, 1 - clip]`` and Brier does not; a
contrast is a signed sum of per-row losses in the coefficient order given; the block
bootstrap resamples whole blocks with replacement from one generator and divides summed
loss by summed size.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from tennislab.chain.common import ChainError


class ScoreError(ChainError):
    """Score arrays that are empty, misaligned or not probabilities."""


def individual_scores(
    probabilities: Sequence[float], outcomes: Sequence[int], clip: float
) -> tuple[np.ndarray, np.ndarray, int]:
    """Per-row log loss (clipped) and Brier score (unclipped), plus the clip count."""
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(outcomes, dtype=np.float64)
    if p.ndim != 1 or y.ndim != 1 or len(p) != len(y) or not len(p):
        raise ScoreError("invalid score arrays")
    clipped = np.clip(p, clip, 1.0 - clip)
    losses = -(y * np.log(clipped) + (1.0 - y) * np.log1p(-clipped))
    brier = (p - y) ** 2
    return losses, brier, int(np.count_nonzero(clipped != p))


def contrast_delta(
    components: Mapping[str, np.ndarray], coefficients: Mapping[str, float]
) -> np.ndarray:
    """The paired per-row difference ``sum(coefficient * component)`` in coefficient order."""
    return sum(coefficient * components[block] for block, coefficient in coefficients.items())


def block_bootstrap(
    loss_delta: np.ndarray,
    blocks: Sequence[Sequence[int]],
    replicates: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Resample whole blocks with replacement; each replicate's mean is summed loss over summed size."""
    if not len(blocks):
        raise ScoreError("bootstrap requires at least one block")
    group_sums = np.asarray(
        [[float(np.sum(loss_delta[list(block)])), len(block)] for block in blocks],
        dtype=np.float64,
    )
    chosen = rng.integers(0, len(blocks), size=(replicates, len(blocks)))
    sampled = group_sums[chosen].sum(axis=1)
    return sampled[:, 0] / sampled[:, 1]


def quantile_interval(values: np.ndarray) -> tuple[float, float]:
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def t_half_width(annual_values: Sequence[float], t_critical: float) -> float:
    """Across-year Student-t half width from the sample standard deviation of annual means."""
    if len(annual_values) < 2:
        raise ScoreError("an across-year interval needs at least two years")
    return t_critical * float(np.std(annual_values, ddof=1)) / math.sqrt(len(annual_values))


def reliability_bins(
    pairs: Sequence[tuple[float, int]], edges: Sequence[float]
) -> list[dict[str, Any]]:
    """Fixed-edge reliability: the last bin is closed on the right."""
    rows = []
    last = len(edges) - 2
    for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        selected = [
            pair for pair in pairs if lower <= pair[0] < upper or index == last and pair[0] == upper
        ]
        rows.append(
            {
                "bin": index,
                "lower": lower,
                "upper": upper,
                "n": len(selected),
                "mean_prediction": (
                    "" if not selected else float(np.mean([pair[0] for pair in selected]))
                ),
                "outcome_rate": (
                    "" if not selected else float(np.mean([pair[1] for pair in selected]))
                ),
            }
        )
    return rows
