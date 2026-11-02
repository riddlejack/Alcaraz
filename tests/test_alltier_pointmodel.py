"""The iid-points match chain against an independent recursion and its symmetries."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pytest

from tennislab.alltier import pointmodel


def game_recursive(p: float) -> float:
    @lru_cache(None)
    def win(a: int, b: int) -> float:
        if a >= 4 and a - b >= 2:
            return 1.0
        if b >= 4 and b - a >= 2:
            return 0.0
        if a >= 3 and b >= 3 and a == b:
            return p * p / (p * p + (1 - p) * (1 - p))
        return p * win(a + 1, b) + (1 - p) * win(a, b + 1)

    return win(0, 0)


def tiebreak_recursive(pa: float, pb: float) -> float:
    def a_serves(point: int) -> bool:
        return (point % 4) in (0, 3)

    @lru_cache(None)
    def win(a: int, b: int) -> float:
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if a >= 6 and b >= 6 and a == b:
            two_a, two_b = pa * (1 - pb), (1 - pa) * pb
            return two_a / (two_a + two_b)
        point = pa if a_serves(a + b) else 1 - pb
        return point * win(a + 1, b) + (1 - point) * win(a, b + 1)

    return win(0, 0)


def set_recursive(pa: float, pb: float) -> float:
    ga, gb = game_recursive(pa), game_recursive(pb)

    @lru_cache(None)
    def win(a: int, b: int) -> float:
        if (a == 6 and b <= 4) or a == 7:
            return 1.0
        if (b == 6 and a <= 4) or b == 7:
            return 0.0
        if a == 6 and b == 6:
            return tiebreak_recursive(pa, pb)
        step = ga if (a + b) % 2 == 0 else 1 - gb
        return step * win(a + 1, b) + (1 - step) * win(a, b + 1)

    return win(0, 0)


@pytest.mark.parametrize("pa,pb", [(0.62, 0.62), (0.7, 0.55), (0.51, 0.66), (0.9, 0.3)])
def test_chain_matches_an_independent_recursion(pa, pb):
    a, b = np.array([pa]), np.array([pb])
    assert pointmodel.game(a)[0] == pytest.approx(game_recursive(pa), abs=1e-13)
    assert pointmodel.tiebreak(a, b)[0] == pytest.approx(tiebreak_recursive(pa, pb), abs=1e-13)
    assert pointmodel.tiebreak_set(a, b)[0] == pytest.approx(set_recursive(pa, pb), abs=1e-13)


def test_symmetry_and_equal_servers():
    rng = np.random.default_rng(3)
    pa, pb = rng.uniform(0.4, 0.85, 200), rng.uniform(0.4, 0.85, 200)
    for best_of in (3, 5):
        bo = np.full(200, best_of)
        total = pointmodel.match_win_prob(pa, pb, bo) + pointmodel.match_win_prob(pb, pa, bo)
        assert np.allclose(total, 1.0, atol=1e-13)
        assert np.allclose(pointmodel.match_win_prob(pa, pa, bo), 0.5, atol=1e-13)
        assert np.allclose(
            pointmodel.match_logit(pa, pb, bo), -pointmodel.match_logit(pb, pa, bo), atol=1e-11
        )


def test_best_of_five_is_more_decisive_than_best_of_three():
    pa, pb = np.array([0.66, 0.6]), np.array([0.62, 0.64])
    three = pointmodel.match_win_prob(pa, pb, np.array([3, 3]))
    five = pointmodel.match_win_prob(pa, pb, np.array([5, 5]))
    assert five[0] > three[0] > 0.5
    assert five[1] < three[1] < 0.5


def test_extremes_and_clip():
    assert pointmodel.game(np.array([0.5]))[0] == pytest.approx(0.5)
    assert pointmodel.game(np.array([1.0]))[0] == 1.0
    assert pointmodel.game(np.array([0.0]))[0] == 0.0
    p = pointmodel.match_win_prob(np.array([0.999]), np.array([0.2]), np.array([3]))
    assert p[0] > 1 - 1e-9
    logit = pointmodel.match_logit(np.array([1.0]), np.array([0.0]), np.array([5]))
    top = 1 - 1e-12
    assert logit[0] == np.log(top) - np.log1p(-top)
