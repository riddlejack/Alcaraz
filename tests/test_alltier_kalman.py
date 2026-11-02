"""The serve/return filter: one hand-computed step, idle widening, the two-day rule, the
temper identity and the tuning protocol."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tennislab.alltier import kalman

SETTINGS = kalman.KalmanSettings.from_mapping(
    {"V0": 0.01, "q": 1e-4, "V_surf": 0.0, "temper_lower": 1.0, "mu_rate": 0.002}
)


def two_rows(day2: int, tier: str = "tour", settings=SETTINGS, surface: str = "Hard"):
    """Row 0: player 1 beats player 2 on day 0 with 40/60 and 30/55 serve points won;
    row 1 reads both players on ``day2``."""
    return kalman.run_filter(
        [0, day2], [1, 1], [2, 2], [1, 1], [2, 2], [tier, tier], [surface, surface],
        [True, False], [60.0, 0.0], [40.0, 0.0], [55.0, 0.0], [30.0, 0.0], settings,
    )  # fmt: skip


def test_one_step_by_hand():
    state, _ = two_rows(day2=10)
    v0, q = SETTINGS.V0, SETTINGS.q
    mu0 = math.log(0.62 / 0.38)
    p = 1 / (1 + math.exp(-mu0))
    g1, i1 = 40 - 60 * p, 60 * p * (1 - p)  # player 1 serving
    g2, i2 = 30 - 55 * p, 55 * p * (1 - p)  # player 2 serving
    s1 = v0 * g1 / (1 + i1 * 2 * v0)
    r2 = -v0 * g1 / (1 + i1 * 2 * v0)
    s2 = v0 * g2 / (1 + i2 * 2 * v0)
    r1 = -v0 * g2 / (1 + i2 * 2 * v0)
    var_s1 = v0 - v0 * v0 * i1 / (1 + i1 * 2 * v0)
    var_r1 = v0 - v0 * v0 * i2 / (1 + i2 * 2 * v0)
    widened = min(v0, var_s1 + q * 10) + min(v0, var_r1 + q * 10)
    mu = mu0 + SETTINGS.mu_rate * (g1 / i1 + g2 / i2)
    s_a, r_a, s_b, r_b, var_a, _, eta_a, eta_b = state[1]
    assert (s_a, r_a, s_b, r_b) == pytest.approx((s1, r1, s2, r2), rel=1e-12)
    assert var_a == pytest.approx(widened, rel=1e-12)
    assert eta_a == pytest.approx(mu + s1 - r2, rel=1e-12)
    assert eta_b == pytest.approx(mu + s2 - r1, rel=1e-12)
    # Row 0 read the newcomer prior.
    assert tuple(state[0][:4]) == (0.0, 0.0, 0.0, 0.0)
    assert state[0][4] == pytest.approx(2 * v0)


def test_two_day_rule_and_variance_cap():
    before, _ = two_rows(day2=1)
    after, _ = two_rows(day2=2)
    assert tuple(before[1][:4]) == (0.0, 0.0, 0.0, 0.0)
    assert after[1][0] != 0.0
    long_idle, _ = two_rows(day2=5000)
    assert long_idle[1][4] == pytest.approx(2 * SETTINGS.V0)


def test_surface_deviation_moves_only_on_its_surface():
    settings = SETTINGS.replace(V_surf=0.002, q=1e-6)
    on_clay, _ = kalman.run_filter(
        [0, 5, 5], [1, 1, 1], [2, 2, 2], [1, 1, 1], [2, 2, 2], ["tour"] * 3,
        ["Clay", "Clay", "Grass"], [True, False, False], [60.0, 0, 0], [45.0, 0, 0],
        [60.0, 0, 0], [30.0, 0, 0], settings,
    )  # fmt: skip
    # The base skills agree; the clay row also reads the clay deviations.
    assert on_clay[1][0] == on_clay[2][0]
    assert on_clay[1][6] != on_clay[2][6]
    assert on_clay[1][4] < on_clay[2][4]


def test_global_temper_equals_scaled_variances():
    rng = np.random.default_rng(5)
    n = 300
    day = np.sort(rng.integers(0, 200, n)).tolist()
    a = rng.integers(0, 15, n)
    b = (a + 1 + rng.integers(0, 14, n)) % 15
    pts = rng.integers(40, 90, n).astype(float)
    won = (pts * rng.uniform(0.5, 0.7, n)).round()
    args = (
        day, a.tolist(), b.tolist(), a.tolist(), b.tolist(), ["challenger"] * n, ["Hard"] * n,
        [True] * n, pts.tolist(), won.tolist(), pts.tolist(), (pts - won).tolist(),
    )  # fmt: skip
    base = SETTINGS.replace(V_surf=0.002)
    tau = 0.5
    tempered, _ = kalman.run_filter(*args, base.replace(temper_lower=tau))
    scaled, _ = kalman.run_filter(
        *args, base.replace(V0=tau * base.V0, q=tau * base.q, V_surf=tau * base.V_surf)
    )
    assert np.allclose(tempered[:, :4], scaled[:, :4], rtol=1e-9, atol=1e-15)


def test_tuning_protocol_picks_the_best_scored_setting():
    rng = np.random.default_rng(9)
    n = 400
    a = rng.integers(0, 12, n)
    b = (a + 1 + rng.integers(0, 11, n)) % 12
    pts = rng.integers(40, 90, n).astype(float)
    won = (pts * (0.55 + 0.02 * (a % 4))).round()
    rows = {
        "day": np.sort(rng.integers(0, 300, n)).tolist(),
        "player_a": a.tolist(),
        "player_b": b.tolist(),
        "winner": a.tolist(),
        "loser": b.tolist(),
        "tiers": ["tour"] * n,
        "surfaces": ["Hard"] * n,
        "observed": [True] * n,
        "winner_serve_points": pts.tolist(),
        "winner_serve_won": won.tolist(),
        "loser_serve_points": pts.tolist(),
        "loser_serve_won": (pts - won).tolist(),
    }
    protocol = {
        "mu_rate": 0.002,
        "grid": {"V0": [0.01, 0.05], "q": [1e-5, 1e-4]},
        "edge_extensions": {
            "V0": {"low": [0.005], "high": [0.1]},
            "q": {"low": [3e-6], "high": [3e-4]},
        },
        "surface_variance": [0.001],
        "lower_tier_temper": [0.5],
        "refinement": {"V0_divisor": 2, "q_multiplier": 3, "V_surf_divisors_of_V0": [5]},
    }
    record = kalman.tune(rows, protocol, (100, 300))
    scores = [r["loglik"] for r in record["grid"]]
    assert record["chosen"]["loglik"] == max(scores)
    assert record["grid"][0]["stage"] == "reference_skills_off"
    assert record["settings_scored"] == 1 + 4 + 2 + 1 + 1 + 2 + 1
    assert all(r["rows"] == record["grid"][0]["rows"] > 0 for r in record["grid"])
