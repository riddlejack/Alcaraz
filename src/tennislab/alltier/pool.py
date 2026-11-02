"""The current Alcaraz: the previous version and the all-tier model, pooled in log-odds.

For every target, the all-tier forecast is sigmoid of the mean of its windows' log-odds,
and the current Alcaraz is sigmoid(w_previous * logit(previous) + w_all-tier * that mean),
with the weights fixed in the configuration (0.5 and 0.5), never fitted. A target without
an all-tier row takes the previous version's log-odds in place of the mean, in both
outputs; a season in which more than ``max_missing_share`` of the targets lack a row
stops the run. Probabilities are clipped at the pipeline's 1e-6 before any logit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from tennislab.chain.common import ChainError
from tennislab.models import pipeline


class PoolError(ChainError):
    """A season with too many targets missing from the all-tier table, or a bad weight."""


def logit(p: np.ndarray) -> np.ndarray:
    clipped = np.clip(p, pipeline.LOGIT_CLIP, 1 - pipeline.LOGIT_CLIP)
    return np.log(clipped / (1 - clipped))


def mean_logit(members: Sequence[np.ndarray]) -> np.ndarray:
    """The members' mean log-odds; NaN where a member has no forecast."""
    return np.mean([logit(m) for m in members], axis=0)


def combine(
    members: Sequence[np.ndarray],
    previous: np.ndarray,
    weights: Mapping[str, float],
    max_missing_share: float,
    label: str = "",
) -> tuple[np.ndarray, np.ndarray, int]:
    """(all-tier forecast, current forecast, targets without an all-tier row)."""
    if set(weights) != {"previous", "alltier"}:
        raise PoolError("pool weights must name exactly 'previous' and 'alltier'")
    z_all = mean_logit(members)
    missing = np.isnan(z_all)
    if missing.mean() > max_missing_share:
        raise PoolError(
            f"{label}: {int(missing.sum())} of {len(missing)} targets without an all-tier row"
        )
    z_previous = logit(previous)
    z_all = np.where(missing, z_previous, z_all)
    current = pipeline.sigmoid(
        float(weights["previous"]) * z_previous + float(weights["alltier"]) * z_all
    )
    return pipeline.sigmoid(z_all), current, int(missing.sum())
