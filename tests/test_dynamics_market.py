"""Archive ``references/SR02_models/test_market.py``, importing from the package."""

import unittest

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from tennislab.dynamics.market import fit, select


class MarketAdapterTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(4201)
        self.z = rng.normal(0, 1.2, 800)
        self.r = rng.normal(0, 0.6, 800)
        self.q = expit(self.z)
        self.p = expit(self.z + self.r)
        self.y = rng.binomial(1, expit(1.15 * self.z + 0.8 * self.r))

    def test_independent_optimizer_and_objective(self):
        result = fit(self.q, self.y, self.p, 0.01)
        rms = np.sqrt(np.mean(self.r**2))

        def independent(beta):
            probability = expit(beta[0] * self.z + beta[1] * self.r / rms)
            return (
                np.mean(-self.y * np.log(probability) - (1 - self.y) * np.log1p(-probability))
                + 0.005 * beta[1] ** 2
            )

        reference = minimize(
            independent,
            [0.8, 0.2],
            method="SLSQP",
            bounds=[(0, None), (None, None)],
            options={"ftol": 1e-13, "maxiter": 500},
        )
        self.assertTrue(reference.success)
        np.testing.assert_allclose(
            [result.market_slope, result.residual_coefficient], reference.x, atol=1e-6
        )
        self.assertAlmostEqual(result.objective, reference.fun, places=11)
        self.assertLessEqual(result.objective, fit(self.q, self.y).objective + 1e-10)

    def test_swapping_players_complements_fit_and_predictions(self):
        original = fit(self.q, self.y, self.p, 0.01)
        swapped = fit(1 - self.q, 1 - self.y, 1 - self.p, 0.01)
        np.testing.assert_allclose(
            [original.market_slope, original.residual_coefficient],
            [swapped.market_slope, swapped.residual_coefficient],
            atol=1e-9,
        )
        np.testing.assert_allclose(
            original.predict(self.q, self.p), 1 - swapped.predict(1 - self.q, 1 - self.p), atol=1e-9
        )

    def test_zero_residual_is_exact_market_control(self):
        control = fit(self.q, self.y)
        for penalty in [0.001, 0.01, 0.1, 1]:
            same = fit(self.q, self.y, self.q, penalty)
            self.assertEqual(same.market_slope, control.market_slope)
            self.assertEqual(same.residual_coefficient, 0)
            np.testing.assert_array_equal(same.predict(self.q, self.q), control.predict(self.q))

    def test_market_only_does_not_read_sports_input(self):
        control = fit(self.q, self.y, sports=object(), penalty=None)
        np.testing.assert_array_equal(control.predict(self.q, object()), control.predict(self.q))

    def test_constant_market_records_unidentified_slope(self):
        result = fit(np.full(6, 0.5), [0, 1, 1, 0, 1, 1])
        self.assertEqual(result.status, "constant_market_fixed_unit_slope")
        self.assertEqual(result.market_slope, 1)
        np.testing.assert_array_equal(result.predict(np.full(6, 0.5)), np.full(6, 0.5))

    def test_nonnegative_market_boundary(self):
        result = fit(self.q, self.z < 0)
        self.assertAlmostEqual(result.market_slope, 0, places=12)
        self.assertLessEqual(result.projected_gradient, 1e-6)

    def test_tie_rule_favors_exact_fallback_then_stronger_shrinkage(self):
        trials = [
            {"penalty": 0.01, "loss": 0.6},
            {"penalty": 1, "loss": 0.6 - 1e-12},
            {"penalty": None, "loss": 0.6},
        ]
        self.assertIsNone(select(trials)["penalty"])
        self.assertEqual(select(trials[:2])["penalty"], 1)

    def test_invalid_values_and_broadcast_are_rejected(self):
        for args in [
            ([0, 0.5], [0, 1]),
            ([0.5, 1], [0, 1]),
            ([0.5, float("nan")], [0, 1]),
            ([0.5, 0.6], [0, 2]),
            ([0.5, 0.6], [0, 1], [0.5], 0.01),
            ([0.5], [0], [0.6], -1),
        ]:
            with self.assertRaises(ValueError):
                fit(*args)


if __name__ == "__main__":
    unittest.main()
