"""Synthetic public regression for the repaired Newton line-search precision loss."""

import datetime as dt
import math
import unittest

import numpy as np
from scipy.optimize import minimize

from tennislab.dynamics.dynamic import (
    DynamicConfig,
    DynamicServeReturnFilter,
    GaussianState,
    HistoryObservation,
    ServiceLine,
)


def _synthetic_precision_case():
    """Build a fixed-seed numerical stress case with no source-data inputs."""
    seed = 713
    prior_variance_scale = 0.03
    rng = np.random.default_rng(seed)
    config = DynamicConfig(
        global_initial_mean_logit=0.5,
        global_initial_sd=0.08,
        surface_mean_initial_sd=0.05,
        tournament_initial_sd=0.04,
        serve_initial_sd=0.15,
        return_initial_sd=0.15,
        surface_initial_sd=0.04,
        serve_process_sd_per_60_days=0.02,
        return_process_sd_per_60_days=0.02,
        surface_process_sd_per_60_days=0.0,
        solver_gradient_tolerance=1e-6,
        solver_newton_decrement_tolerance=1e-7,
        solver_max_iterations=50,
    )
    model = DynamicServeReturnFilter(config)
    batch_date = dt.date(2040, 1, 1)
    state_keys = [
        ("global", 0, ""),
        ("surface_mean", 0, "Grass"),
        ("tournament", 0, "SYNTH"),
        ("serve", 1001, ""),
        ("return", 1001, ""),
        ("surface", 1001, "Grass"),
        ("serve", 1002, ""),
        ("return", 1002, ""),
        ("surface", 1002, "Grass"),
    ]
    base_variance = {
        "global": 0.002,
        "surface_mean": 0.001,
        "tournament": 0.001,
        "serve": 0.004,
        "return": 0.004,
        "surface": 0.001,
    }
    for key in state_keys:
        kind = key[0]
        mean_center = 0.5 if kind == "global" else 0.0
        mean_sd = 0.12 if kind in {"serve", "return"} else 0.03
        mean = mean_center + rng.normal(0.0, mean_sd)
        variance = base_variance[kind] * np.exp(rng.normal(0.0, 0.6)) * prior_variance_scale
        point_observations = int(rng.integers(100, 5000))
        model.states[key] = GaussianState(mean, variance, batch_date, point_observations)

    attempts_a = int(rng.integers(45, 125))
    attempts_b = int(rng.integers(45, 125))
    probability_a = float(rng.uniform(0.45, 0.75))
    wins_a = int(rng.binomial(attempts_a, probability_a))
    probability_b = float(rng.uniform(0.45, 0.75))
    wins_b = int(rng.binomial(attempts_b, probability_b))
    assert (attempts_a, wins_a, attempts_b, wins_b) == (78, 41, 69, 48)
    batch = [
        HistoryObservation(
            match_id="SYNTH-00",
            match_date=batch_date,
            tourney_id="SYNTH",
            surface="Grass",
            player_a=1001,
            player_b=1002,
            service_a=ServiceLine(wins_a, attempts_a),
            service_b=ServiceLine(wins_b, attempts_b),
            history_eligible=True,
            exclusion_reason="",
        )
    ]
    return model, batch


def _optimization_problem(model, batch):
    keys = sorted(model.states)
    prior = np.asarray([model.states[key].mean for key in keys])
    precision = np.asarray([1.0 / model.states[key].variance for key in keys])
    contests = [
        (item, item.player_a, item.player_b, item.service_a)
        for item in batch
        if item.service_a is not None
    ] + [
        (item, item.player_b, item.player_a, item.service_b)
        for item in batch
        if item.service_b is not None
    ]
    matrix, wins, counts = [], [], []
    for item, server, returner, line in contests:
        terms = dict(model._terms(server, returner, item.surface, item.tourney_id))
        matrix.append([terms.get(key, 0.0) for key in keys])
        wins.append(line.points_won)
        counts.append(line.points_played)
    return (
        keys,
        prior,
        precision,
        np.asarray(matrix),
        np.asarray(wins),
        np.asarray(counts),
    )


def _probabilities(eta):
    probability = np.empty_like(eta)
    positive = eta >= 0.0
    probability[positive] = 1.0 / (1.0 + np.exp(-eta[positive]))
    exponent = np.exp(eta[~positive])
    probability[~positive] = exponent / (1.0 + exponent)
    return probability


def _legacy_absolute_loss_receipt(prior, precision, x, y, n, config):
    """Run the superseded absolute-loss Armijo comparison as a negative control."""

    def derivatives(values):
        eta = x @ values
        probability = _probabilities(eta)
        difference = values - prior
        objective = float(
            0.5 * np.dot(precision * difference, difference)
            + np.sum(n * np.logaddexp(0.0, eta) - y * eta)
        )
        gradient = precision * difference + x.T @ (n * probability - y)
        curvature = n * probability * (1.0 - probability)
        hessian = np.diag(precision) + x.T @ (curvature[:, None] * x)
        return objective, gradient, hessian

    values = prior.copy()
    line_search_failed = False
    for iteration in range(1, config.solver_max_iterations + 1):  # noqa: B007
        objective, gradient, hessian = derivatives(values)
        if np.max(np.abs(gradient)) <= config.solver_gradient_tolerance:
            break
        step = np.linalg.solve(hessian, gradient)
        directional = float(np.dot(gradient, step))
        scale = 1.0
        while scale >= 2.0**-30:
            candidate = values - scale * step
            candidate_objective, _, _ = derivatives(candidate)
            if candidate_objective <= objective - 1e-4 * scale * directional:
                values = candidate
                break
            scale *= 0.5
        else:
            line_search_failed = True
            break
    _, gradient, hessian = derivatives(values)
    final_step = np.linalg.solve(hessian, gradient)
    return (
        line_search_failed,
        iteration,
        float(np.max(np.abs(gradient))),
        math.sqrt(max(float(np.dot(gradient, final_step)), 0.0)),
    )


class NumericalRepairTests(unittest.TestCase):
    def test_synthetic_armijo_cancellation_batch_converges_without_relaxed_tolerance(self):
        model, batch = _synthetic_precision_case()
        keys, prior, precision, x, y, n = _optimization_problem(model, batch)

        legacy_failed, legacy_iterations, legacy_gradient, legacy_decrement = (
            _legacy_absolute_loss_receipt(prior, precision, x, y, n, model.config)
        )
        self.assertTrue(legacy_failed)
        self.assertEqual(legacy_iterations, 9)
        self.assertGreater(legacy_gradient, model.config.solver_gradient_tolerance)
        self.assertGreater(legacy_decrement, model.config.solver_newton_decrement_tolerance)

        def objective(values):
            eta = x @ values
            difference = values - prior
            return 0.5 * np.dot(precision * difference, difference) + np.sum(
                n * np.logaddexp(0.0, eta) - y * eta
            )

        def jacobian(values):
            eta = x @ values
            return precision * (values - prior) + x.T @ (n * _probabilities(eta) - y)

        expected_points = sum(
            line.points_played
            for item in batch
            for line in (item.service_a, item.service_b)
            if line is not None
        )
        model.apply_batch(batch)
        fitted = np.asarray([model.states[key].mean for key in keys])
        self.assertEqual(model.last_solver_acceptance, "maximum_gradient")
        self.assertLessEqual(model.last_solver_max_gradient, 1e-6)
        self.assertLess(model.last_solver_iterations, 10)
        self.assertEqual(model.matches_used, len(batch))
        self.assertEqual(model.points_used, expected_points)
        self.assertEqual(model.latest_source_date, batch[0].match_date)

        independent = minimize(
            objective,
            prior,
            jac=jacobian,
            method="BFGS",
            options={"gtol": 1e-8, "maxiter": 1000},
        )
        self.assertTrue(independent.success)
        self.assertLess(abs(objective(fitted) - independent.fun), 1e-9)
        np.testing.assert_allclose(fitted, independent.x, atol=2e-7, rtol=0.0)


if __name__ == "__main__":
    unittest.main()
