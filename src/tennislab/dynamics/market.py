"""Small symmetric market-residual adapter using SciPy's bounded optimizer.

Ported verbatim from the archive's ``references/SR02_models/market.py``; validation
errors are :class:`~tennislab.dynamics.dynamic.DynamicsError`. The L-BFGS-B call, its
options and the convergence receipt (``objective``, ``projected_gradient``,
``iterations``, ``status``) are unchanged.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from tennislab.dynamics.dynamic import DynamicsError

CLIP = 1e-12


def probabilities(value):
    p = np.asarray(value, dtype=float)
    if p.ndim != 1 or not len(p) or not np.isfinite(p).all() or np.any((p <= 0) | (p >= 1)):
        raise DynamicsError("Expected nonempty finite probabilities strictly between zero and one")
    return np.clip(p, CLIP, 1 - CLIP)


def logits(value):
    p = probabilities(value)
    return np.log(p) - np.log1p(-p)


def labels(value, n):
    y = np.asarray(value, dtype=float)
    if y.shape != (n,) or not np.isin(y, [0, 1]).all():
        raise DynamicsError("Expected aligned binary outcomes")
    return y


def scores(p, y):
    p = probabilities(p)
    y = labels(y, len(p))
    return {
        "n": len(p),
        "log_loss": float(np.mean(-y * np.log(p) - (1 - y) * np.log1p(-p))),
        "brier": float(np.mean((p - y) ** 2)),
    }


@dataclass(frozen=True)
class Fit:
    market_slope: float
    residual_coefficient: float
    residual_rms: float
    penalty: float | None
    n: int
    objective: float
    projected_gradient: float
    iterations: int
    status: str

    def predict(self, market, sports=None):
        z = logits(market)
        if self.residual_coefficient == 0:
            return expit(self.market_slope * z)
        if sports is None:
            raise DynamicsError("Augmented prediction requires sports probability")
        zs = logits(sports)
        if zs.shape != z.shape:
            raise DynamicsError("Market and sports shapes differ")
        return expit(
            self.market_slope * z + self.residual_coefficient * (zs - z) / self.residual_rms
        )

    def record(self):
        return asdict(self)


def fit(market, y, sports=None, penalty=None):
    """No penalty means the exact market-only calibration control.

    Only the standardized sports residual is penalized. The market slope is
    nonnegative and unpenalized, with no intercept to preserve swap symmetry.
    """
    z = logits(market)
    y = labels(y, len(z))
    rms, active = 1.0, False
    if penalty is not None:
        if not math.isfinite(penalty) or penalty <= 0 or sports is None:
            raise DynamicsError(
                "Augmentation requires positive finite penalty and sports probability"
            )
        sports_logit = logits(sports)
        if sports_logit.shape != z.shape:
            raise DynamicsError("Market and sports shapes differ")
        residual = sports_logit - z
        rms = float(np.sqrt(np.mean(residual**2)))
        active = rms > 1e-12
    if not active:
        rms = 1.0
    x = np.column_stack((z, residual / rms)) if active else z[:, None]
    penalties = np.array([0.0, penalty]) if active else np.array([0.0])

    def objective(beta):
        eta = x @ beta
        loss = float(np.mean(np.logaddexp(0, eta) - y * eta) + 0.5 * np.sum(penalties * beta**2))
        gradient = x.T @ (expit(eta) - y) / len(y) + penalties * beta
        return loss, gradient

    if not np.any(z) and not active:
        value, _ = objective(np.array([1.0]))
        return Fit(
            1.0, 0.0, rms, penalty, len(y), value, 0.0, 0, "constant_market_fixed_unit_slope"
        )
    result = minimize(
        objective,
        np.array([1.0, 0.0]) if active else np.array([1.0]),
        method="L-BFGS-B",
        jac=True,
        bounds=[(0, None)] + ([(None, None)] if active else []),
        options={"gtol": 1e-9, "ftol": 1e-14, "maxiter": 1000, "maxls": 50},
    )
    value, gradient = objective(result.x)
    projected = gradient.copy()
    if result.x[0] <= 1e-12:
        projected[0] = min(projected[0], 0.0)
    error = float(np.max(np.abs(projected)))
    if (
        not result.success
        or not np.isfinite(result.x).all()
        or not math.isfinite(value)
        or error > 1e-6
    ):
        raise DynamicsError(f"Market fit failed: {result.message}; projected gradient={error}")
    return Fit(
        float(result.x[0]),
        float(result.x[1]) if active else 0.0,
        rms,
        penalty,
        len(y),
        value,
        error,
        int(result.nit),
        "converged" if active or penalty is None else "zero_residual_exact_market_control",
    )


def select(trials, tie_tolerance=1e-10):
    """Trials contain mean prior-year loss and penalty; None is exact fallback."""
    if not trials or any(not math.isfinite(t["loss"]) for t in trials):
        raise DynamicsError("Missing or nonfinite candidate validation loss")
    best = min(t["loss"] for t in trials)
    tied = [t for t in trials if t["loss"] <= best + tie_tolerance]
    return min(
        tied,
        key=lambda t: (t["penalty"] is not None, -t["penalty"] if t["penalty"] is not None else 0),
    )
