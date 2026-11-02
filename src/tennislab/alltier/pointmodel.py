"""Match-win probability from serve-point probabilities, with points independent.

Exact Markov chains for a game, a seven-point tiebreak and a tiebreak set; the set
probability is averaged over the two possible first servers, then combined into a
best-of-3 or best-of-5 match. Every function works elementwise on numpy arrays.
"""

from __future__ import annotations

import numpy as np


def game(p: np.ndarray) -> np.ndarray:
    """P(the server holds) when he wins each point with probability ``p``."""
    q = 1 - p
    return p**4 * (1 + 4 * q + 10 * q * q) + 20 * (p * q) ** 3 * p * p / (1 - 2 * p * q)


def tiebreak(pa: np.ndarray, pb: np.ndarray) -> np.ndarray:
    """P(a wins a seven-point tiebreak) when a serves its first point."""
    states = {(0, 0): np.ones_like(pa)}
    win = np.zeros_like(pa)
    for total in range(0, 12):
        for i in range(0, min(total, 6) + 1):
            j = total - i
            if j > 6 or (i, j) not in states:
                continue
            reach = states.pop((i, j))
            a_serves = (total % 4) in (0, 3)
            point = pa if a_serves else 1 - pb
            for ni, nj, step in ((i + 1, j, point), (i, j + 1, 1 - point)):
                if ni == 7:
                    win = win + reach * step
                elif nj == 7:
                    pass
                else:
                    states[(ni, nj)] = states.get((ni, nj), 0) + reach * step
    a_two = pa * (1 - pb)
    b_two = (1 - pa) * pb
    return win + states.get((6, 6), 0) * a_two / (a_two + b_two)


def tiebreak_set(pa: np.ndarray, pb: np.ndarray) -> np.ndarray:
    """P(a wins a tiebreak set) when a serves its first game."""
    hold_a, hold_b = game(pa), game(pb)
    states = {(0, 0): np.ones_like(pa)}
    win = np.zeros_like(pa)
    for total in range(0, 12):
        for i in range(0, total + 1):
            j = total - i
            if (i, j) not in states:
                continue
            reach = states.pop((i, j))
            step_a = hold_a if total % 2 == 0 else 1 - hold_b
            for ni, nj, step in ((i + 1, j, step_a), (i, j + 1, 1 - step_a)):
                if (ni == 6 and nj <= 4) or ni == 7:
                    win = win + reach * step
                elif (nj == 6 and ni <= 4) or nj == 7:
                    pass
                else:
                    states[(ni, nj)] = states.get((ni, nj), 0) + reach * step
    return win + states.get((6, 6), 0) * tiebreak(pa, pb)


def match_win_prob(pa: np.ndarray, pb: np.ndarray, best_of: np.ndarray) -> np.ndarray:
    """P(a wins the match): ``pa``/``pb`` are each side's serve-point probabilities."""
    s = 0.5 * (tiebreak_set(pa, pb) + (1 - tiebreak_set(pb, pa)))
    s3 = s * s * (3 - 2 * s)
    u = 1 - s
    s5 = s**3 * (1 + 3 * u + 6 * u * u)
    return np.where(best_of == 5, s5, s3)


def match_logit(pa: np.ndarray, pb: np.ndarray, best_of: np.ndarray) -> np.ndarray:
    """The logit of :func:`match_win_prob`, clipped at 1e-12 from either end."""
    pm = np.clip(match_win_prob(pa, pb, best_of), 1e-12, 1 - 1e-12)
    return np.log(pm) - np.log1p(-pm)
