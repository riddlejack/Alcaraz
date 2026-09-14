"""Synthetic regression bank for the repaired Newton line-search precision loss."""

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

SYNTHETIC_SEEDS = range(1, 2001)


def _synthetic_precision_case(seed):
    """Build one fixed-seed stress case with no source-data inputs."""
    prior_variance_scale = 3e-6
    match_count = 12
    rng = np.random.default_rng(seed)
    config = DynamicConfig(
        global_initial_mean_logit=0.35,
        global_initial_sd=0.8,
        surface_mean_initial_sd=0.45,
        tournament_initial_sd=0.3,
        serve_initial_sd=0.7,
        return_initial_sd=0.65,
        surface_initial_sd=0.4,
        serve_process_sd_per_60_days=0.0,
        return_process_sd_per_60_days=0.0,
        surface_process_sd_per_60_days=0.0,
        solver_gradient_tolerance=1e-6,
        solver_newton_decrement_tolerance=1e-7,
        solver_max_iterations=50,
    )
    model = DynamicServeReturnFilter(config)
    batch_date = dt.date(2042, 3, 17)
    players = list(range(4101, 4101 + match_count * 2))
    active_keys = {
        key
        for player_a, player_b in zip(players[::2], players[1::2], strict=True)
        for server, returner in ((player_a, player_b), (player_b, player_a))
        for key, _ in model._terms(server, returner, "Hard", "SYNTHETIC-ARENA")
    }
    for index, key in enumerate(sorted(active_keys)):
        mean = 0.18 * math.sin((index + 1) * 0.73) + rng.normal(0.0, 0.025)
        variance = prior_variance_scale * (0.7 + 0.6 * rng.random())
        model.states[key] = GaussianState(mean, variance, batch_date, 500 + 7 * index)

    batch = []
    for index, (player_a, player_b) in enumerate(zip(players[::2], players[1::2], strict=True)):
        attempts_a = int(rng.integers(52, 103))
        attempts_b = int(rng.integers(52, 103))
        probability_a = 0.52 + 0.16 * rng.random()
        probability_b = 0.52 + 0.16 * rng.random()
        wins_a = int(rng.binomial(attempts_a, probability_a))
        wins_b = int(rng.binomial(attempts_b, probability_b))
        batch.append(
            HistoryObservation(
                match_id=f"synthetic-match-{index + 1:02d}",
                match_date=batch_date,
                tourney_id="SYNTHETIC-ARENA",
                surface="Hard",
                player_a=player_a,
                player_b=player_b,
                service_a=ServiceLine(wins_a, attempts_a),
                service_b=ServiceLine(wins_b, attempts_b),
                history_eligible=True,
                exclusion_reason="",
            )
        )
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


def _derivatives(values, prior, precision, x, y, n):
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


def _legacy_absolute_loss_receipt(prior, precision, x, y, n, config):
    """Run the superseded absolute-loss Armijo comparison as a negative control."""
    values = prior.copy()
    status = "did_not_converge"
    for iteration in range(1, config.solver_max_iterations + 1):  # noqa: B007
        objective, gradient, hessian = _derivatives(values, prior, precision, x, y, n)
        max_gradient = float(np.max(np.abs(gradient)))
        if max_gradient <= config.solver_gradient_tolerance:
            status = "maximum_gradient"
            break
        step = np.linalg.solve(hessian, gradient)
        directional = float(np.dot(gradient, step))
        scale = 1.0
        while scale >= 2.0**-30:
            candidate = values - scale * step
            candidate_objective, _, _ = _derivatives(candidate, prior, precision, x, y, n)
            if candidate_objective <= objective - 1e-4 * scale * directional:
                values = candidate
                break
            scale *= 0.5
        else:
            decrement = math.sqrt(max(directional, 0.0))
            status = (
                "newton_decrement"
                if decrement <= config.solver_newton_decrement_tolerance
                else "line_search_failed"
            )
            break
    objective, gradient, hessian = _derivatives(values, prior, precision, x, y, n)
    max_gradient = float(np.max(np.abs(gradient)))
    final_step = np.linalg.solve(hessian, gradient)
    decrement = math.sqrt(max(float(np.dot(gradient, final_step)), 0.0))
    if status == "did_not_converge":
        if max_gradient <= config.solver_gradient_tolerance:
            status = "maximum_gradient"
        elif decrement <= config.solver_newton_decrement_tolerance:
            status = "newton_decrement"
    return {
        "status": status,
        "iterations": iteration,
        "max_gradient": max_gradient,
        "newton_decrement": decrement,
        "objective": objective,
    }


def _objective_and_jacobian(prior, precision, x, y, n):
    def objective(values):
        eta = x @ values
        difference = values - prior
        return 0.5 * np.dot(precision * difference, difference) + np.sum(
            n * np.logaddexp(0.0, eta) - y * eta
        )

    def jacobian(values):
        eta = x @ values
        return precision * (values - prior) + x.T @ (n * _probabilities(eta) - y)

    return objective, jacobian


def _independent_bfgs(prior, precision, objective, jacobian):
    """Run BFGS in prior-SD coordinates without changing the objective or gates."""
    scale = 1.0 / np.sqrt(precision)

    def scaled_objective(values):
        return objective(prior + scale * values)

    def scaled_jacobian(values):
        return scale * jacobian(prior + scale * values)

    result = minimize(
        scaled_objective,
        np.zeros_like(prior),
        jac=scaled_jacobian,
        method="BFGS",
        options={"gtol": 1e-8, "maxiter": 1000},
    )
    return result, prior + scale * result.x


class NumericalRepairTests(unittest.TestCase):
    def test_synthetic_armijo_cancellation_batch_converges_without_relaxed_tolerance(self):
        selected = None
        legacy_failures = 0
        for seed in SYNTHETIC_SEEDS:
            model, batch = _synthetic_precision_case(seed)
            problem = _optimization_problem(model, batch)
            keys, prior, precision, x, y, n = problem
            legacy = _legacy_absolute_loss_receipt(prior, precision, x, y, n, model.config)
            if legacy["status"] not in {"line_search_failed", "did_not_converge"}:
                continue
            legacy_failures += 1
            objective, jacobian = _objective_and_jacobian(prior, precision, x, y, n)
            independent, independent_values = _independent_bfgs(
                prior, precision, objective, jacobian
            )
            independent_max_gradient = float(np.max(np.abs(jacobian(independent_values))))
            if independent.success and independent_max_gradient <= 1e-8:
                selected = (
                    seed,
                    model,
                    batch,
                    keys,
                    prior,
                    objective,
                    independent,
                    independent_values,
                    independent_max_gradient,
                    legacy,
                )
                break

        self.assertIsNotNone(
            selected,
            f"no portable regression case in {len(SYNTHETIC_SEEDS)} seeds; "
            f"legacy_failures={legacy_failures}",
        )
        (
            seed,
            model,
            batch,
            keys,
            _prior,
            objective,
            independent,
            independent_values,
            independent_max_gradient,
            legacy,
        ) = selected
        self.assertGreater(legacy["max_gradient"], model.config.solver_gradient_tolerance)
        self.assertGreater(
            legacy["newton_decrement"], model.config.solver_newton_decrement_tolerance
        )

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

        objective_difference = abs(objective(fitted) - independent.fun)
        parameter_difference = float(np.max(np.abs(fitted - independent_values)))
        self.assertLessEqual(independent_max_gradient, 1e-8)
        self.assertLess(objective_difference, 1e-9)
        self.assertLessEqual(parameter_difference, 2e-7)
        print(
            "synthetic_precision_receipt",
            f"seed={seed}",
            f"seeds_examined={seed}",
            f"legacy_failures_examined={legacy_failures}",
            f"legacy_status={legacy['status']}",
            f"legacy_iterations={legacy['iterations']}",
            f"legacy_max_gradient={legacy['max_gradient']:.17g}",
            f"legacy_newton_decrement={legacy['newton_decrement']:.17g}",
            f"current_iterations={model.last_solver_iterations}",
            f"current_max_gradient={model.last_solver_max_gradient:.17g}",
            f"bfgs_max_gradient={independent_max_gradient:.17g}",
            f"bfgs_objective_difference={objective_difference:.17g}",
            f"bfgs_parameter_difference={parameter_difference:.17g}",
        )


if __name__ == "__main__":
    unittest.main()
