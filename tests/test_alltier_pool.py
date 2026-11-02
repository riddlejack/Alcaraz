"""The current Alcaraz: the fixed log-odds pool and the missing-row rule."""

from __future__ import annotations

import numpy as np
import pytest

from tennislab.alltier import pool
from tennislab.models import pipeline

WEIGHTS = {"previous": 0.5, "alltier": 0.5}


def logit(p):
    return np.log(p / (1 - p))


def test_pool_is_the_mean_of_log_odds():
    members = [np.array([0.6, 0.3]), np.array([0.7, 0.2]), np.array([0.65, 0.25])]
    previous = np.array([0.55, 0.4])
    alltier, current, missing = pool.combine(members, previous, WEIGHTS, 0.01)
    z = np.mean([logit(m) for m in members], axis=0)
    assert np.allclose(alltier, 1 / (1 + np.exp(-z)), rtol=0, atol=1e-15)
    assert np.allclose(
        current, 1 / (1 + np.exp(-(0.5 * logit(previous) + 0.5 * z))), rtol=0, atol=1e-15
    )
    assert missing == 0


def test_a_target_without_a_row_takes_the_previous_forecast():
    n = 200
    rng = np.random.default_rng(2)
    members = [rng.uniform(0.1, 0.9, n) for _ in range(3)]
    for m in members:
        m[17] = np.nan
    previous = rng.uniform(0.1, 0.9, n)
    alltier, current, missing = pool.combine(members, previous, WEIGHTS, 0.01)
    assert missing == 1
    expected = pipeline.sigmoid(pool.logit(previous[17:18]))[0]
    assert alltier[17] == expected and current[17] == expected
    assert current[17] == pytest.approx(previous[17], abs=1e-15)


def test_too_many_missing_rows_stop_the_season():
    members = [np.array([0.6, np.nan, 0.5])] * 3
    with pytest.raises(pool.PoolError):
        pool.combine(members, np.array([0.5, 0.5, 0.5]), WEIGHTS, 0.01, label="2020")
    with pytest.raises(pool.PoolError):
        pool.combine(members[:1], np.array([0.5, 0.5, 0.5]), {"previous": 1.0}, 1.0)


def test_logit_clip_matches_the_pipeline():
    p = np.array([0.0, 1e-9, 0.5, 1.0])
    clipped = np.clip(p, pipeline.LOGIT_CLIP, 1 - pipeline.LOGIT_CLIP)
    assert np.array_equal(pool.logit(p), np.log(clipped / (1 - clipped)))
