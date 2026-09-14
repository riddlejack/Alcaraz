"""Public batch regression for the real warmup precision failure.

Archive ``references/SR02_models/test_numerical_repair.py``; the fixture is the archive's
``fixtures/solver_precision_2005-06-25.json`` copied under ``tests/fixtures``.
"""

import datetime as dt
import json
import unittest
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from tennislab.dynamics.dynamic import (
    DynamicConfig,
    DynamicServeReturnFilter,
    GaussianState,
    HistoryObservation,
    ServiceLine,
)


class NumericalRepairTests(unittest.TestCase):
    def test_real_warmup_batch_converges_without_relaxed_tolerance(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "solver_precision_2005-06-25.json").read_text()
        )
        model = DynamicServeReturnFilter(DynamicConfig(**fixture["config"]))
        keys = []
        for item in fixture["prior_states"]:
            key = tuple(item["key"])
            keys.append(key)
            model.states[key] = GaussianState(
                item["mean"],
                item["variance"],
                dt.date.fromisoformat(item["last_date"]),
                item["point_observations"],
            )
        batch = []
        for record in fixture["batch"]:
            row = dict(record)
            row["match_date"] = dt.date.fromisoformat(row["match_date"])
            for side in ("service_a", "service_b"):
                row[side] = ServiceLine(**row[side]) if row[side] else None
            batch.append(HistoryObservation(**row))
        prior = np.array([model.states[k].mean for k in keys])
        precision = np.array([1 / model.states[k].variance for k in keys])
        matrix, wins, counts = [], [], []
        for item in batch:
            for server, returner, line in [
                (item.player_a, item.player_b, item.service_a),
                (item.player_b, item.player_a, item.service_b),
            ]:
                if line:
                    terms = dict(model._terms(server, returner, item.surface, item.tourney_id))
                    matrix.append([terms.get(k, 0) for k in keys])
                    wins.append(line.points_won)
                    counts.append(line.points_played)
        x = np.array(matrix)
        y = np.array(wins)
        n = np.array(counts)

        def objective(v):
            eta = x @ v
            d = v - prior
            return 0.5 * np.dot(precision * d, d) + np.sum(n * np.logaddexp(0, eta) - y * eta)

        def jac(v):
            return precision * (v - prior) + x.T @ (n / (1 + np.exp(-(x @ v))) - y)

        model.apply_batch(batch)
        fitted = np.array([model.states[k].mean for k in keys])
        self.assertLessEqual(model.last_solver_max_gradient, 1e-6)
        self.assertLess(model.last_solver_iterations, 10)
        independent = minimize(
            objective, prior, jac=jac, method="BFGS", options={"gtol": 1e-8, "maxiter": 1000}
        )
        self.assertLess(abs(objective(fitted) - independent.fun), 1e-9)
        np.testing.assert_allclose(fitted, independent.x, atol=2e-7, rtol=0)


if __name__ == "__main__":
    unittest.main()
