"""Exact S1 probability blend and S3 positive-L2 nonnegative logit stack."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import optimize

from tennislab.campaign.members import MEMBER_IDS
from tennislab.chain.common import canonical_hash_nonempty
from tennislab.models.pipeline import sigmoid

STACK_LOGIT_CLIP = 1e-6
STACK_L2 = 0.001
STACK_INITIAL = 1.0 / 8.0
STACK_MAXITER = 5000
STACK_FTOL = 1e-12
STACK_GTOL = 1e-8
STACK_PROJECTED_GRADIENT_TOL = 1e-6


class StackError(ValueError):
    """The fixed stack input, objective, optimizer, or probability contract failed."""


@dataclass(frozen=True)
class StackFit:
    status: str
    coefficients: np.ndarray | None
    objective_value: float | None
    gradient: np.ndarray | None
    projected_gradient_inf_norm: float | None
    iterations: int | None
    function_evaluations: int | None
    optimizer_status: int | None
    optimizer_message: str
    probability_clip_counts: tuple[int, ...]
    rows_by_year: dict[int, int]
    error: dict[str, str] | None = None

    def criterion_document(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "coefficients": None if self.coefficients is None else self.coefficients.tolist(),
            "objective_value": self.objective_value,
            "gradient": None if self.gradient is None else self.gradient.tolist(),
            "projected_gradient_inf_norm": self.projected_gradient_inf_norm,
            "iterations": self.iterations,
            "function_evaluations": self.function_evaluations,
            "optimizer_status": self.optimizer_status,
            "optimizer_message": self.optimizer_message,
            "probability_clip_counts": list(self.probability_clip_counts),
            "rows_by_year": {str(year): count for year, count in sorted(self.rows_by_year.items())},
            "error": self.error,
        }

    def public_receipt(self) -> dict[str, Any]:
        """Forecast-time fit receipt with all score/objective values commitment-only."""
        return {
            "status": self.status,
            "coefficients": None if self.coefficients is None else self.coefficients.tolist(),
            "projected_gradient_inf_norm": self.projected_gradient_inf_norm,
            "iterations": self.iterations,
            "function_evaluations": self.function_evaluations,
            "optimizer_status": self.optimizer_status,
            "optimizer_message": self.optimizer_message,
            "probability_clip_counts": list(self.probability_clip_counts),
            "rows_by_year": {str(year): count for year, count in sorted(self.rows_by_year.items())},
            "member_order": list(MEMBER_IDS),
            "objective_values_deferred_to_report": True,
            "criterion_commitment_sha256": canonical_hash_nonempty(
                self.criterion_document(), label="stack criterion"
            ),
            "error": self.error,
        }


def _as_member_matrix(values: Sequence[Sequence[float]], *, label: str) -> np.ndarray:
    probabilities = np.asarray(values, dtype=np.float64)
    if probabilities.ndim != 2 or probabilities.shape[1] != len(MEMBER_IDS):
        raise StackError(f"{label} must be an n-by-{len(MEMBER_IDS)} member matrix")
    if probabilities.shape[0] == 0:
        raise StackError(f"{label} cannot be empty")
    if not np.all(np.isfinite(probabilities)):
        raise StackError(f"{label} contains nonfinite probabilities")
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise StackError(f"{label} contains probabilities outside [0,1]")
    return probabilities


def logit_member_matrix(
    probabilities: Sequence[Sequence[float]], *, label: str = "raw members"
) -> tuple[np.ndarray, tuple[int, ...]]:
    values = _as_member_matrix(probabilities, label=label)
    clipped = np.clip(values, STACK_LOGIT_CLIP, 1.0 - STACK_LOGIT_CLIP)
    counts = tuple(
        int(np.count_nonzero(clipped[:, index] != values[:, index])) for index in range(8)
    )
    return np.log(clipped / (1.0 - clipped)), counts


def pooled_result_elo(
    overall_logits: Sequence[float], surface_logits: Sequence[float]
) -> np.ndarray:
    overall = np.asarray(overall_logits, dtype=np.float64)
    surface = np.asarray(surface_logits, dtype=np.float64)
    if overall.ndim != 1 or surface.ndim != 1 or overall.shape != surface.shape or not len(overall):
        raise StackError("result Elo logits must be nonempty aligned vectors")
    if not np.all(np.isfinite(overall)) or not np.all(np.isfinite(surface)):
        raise StackError("result Elo logits must be finite")
    return 0.5 * (sigmoid(overall) + sigmoid(surface))


def fixed_probability_blend(
    incumbent: Sequence[float], overall_logits: Sequence[float], surface_logits: Sequence[float]
) -> np.ndarray:
    s0 = np.asarray(incumbent, dtype=np.float64)
    elo = pooled_result_elo(overall_logits, surface_logits)
    if s0.ndim != 1 or s0.shape != elo.shape:
        raise StackError("incumbent and Elo inputs must be aligned")
    if not np.all(np.isfinite(s0)) or np.any(s0 < 0.0) or np.any(s0 > 1.0):
        raise StackError("incumbent probabilities must lie in [0,1]")
    return 0.5 * (s0 + elo)


def _objective_and_gradient(
    coefficients: np.ndarray,
    logits_by_year: Mapping[int, np.ndarray],
    labels_by_year: Mapping[int, np.ndarray],
    required_years: Sequence[int],
) -> tuple[float, np.ndarray]:
    value = 0.5 * STACK_L2 * float(np.dot(coefficients, coefficients))
    gradient = STACK_L2 * coefficients
    year_weight = 1.0 / len(required_years)
    for year in required_years:
        matrix = logits_by_year[year]
        labels = labels_by_year[year]
        eta = matrix @ coefficients
        value += year_weight * float(np.mean(np.logaddexp(0.0, eta) - labels * eta))
        gradient = gradient + year_weight * (matrix.T @ (sigmoid(eta) - labels)) / len(labels)
    return value, gradient


def projected_gradient_inf_norm(coefficients: np.ndarray, gradient: np.ndarray) -> float:
    projection = coefficients - np.maximum(0.0, coefficients - gradient)
    return float(np.max(np.abs(projection)))


def fit_logit_stack(
    yearly_probabilities: Mapping[int, Sequence[Sequence[float]]],
    yearly_labels: Mapping[int, Sequence[int]],
    required_years: Sequence[int],
) -> StackFit:
    """Fit the one reviewed stack; failures are returned and never auto-repaired."""
    years = tuple(int(year) for year in required_years)
    try:
        if not years or len(set(years)) != len(years) or tuple(sorted(years)) != years:
            raise StackError("stack years must be a nonempty sorted unique sequence")
        if set(yearly_probabilities) != set(years) or set(yearly_labels) != set(years):
            raise StackError("stack inputs must cover exactly the required years")
        logits_by_year: dict[int, np.ndarray] = {}
        labels_by_year: dict[int, np.ndarray] = {}
        clip_counts = np.zeros(len(MEMBER_IDS), dtype=np.int64)
        rows_by_year: dict[int, int] = {}
        for year in years:
            logits, counts = logit_member_matrix(
                yearly_probabilities[year], label=f"raw members for {year}"
            )
            labels = np.asarray(yearly_labels[year], dtype=np.float64)
            if labels.ndim != 1 or len(labels) != len(logits):
                raise StackError(f"stack labels are misaligned in {year}")
            if not np.all(np.isin(labels, (0.0, 1.0))):
                raise StackError(f"stack labels must be binary in {year}")
            logits_by_year[year] = logits
            labels_by_year[year] = labels
            clip_counts += np.asarray(counts, dtype=np.int64)
            rows_by_year[year] = len(labels)

        def objective(coefficients: np.ndarray) -> tuple[float, np.ndarray]:
            return _objective_and_gradient(coefficients, logits_by_year, labels_by_year, years)

        result = optimize.minimize(
            objective,
            np.full(len(MEMBER_IDS), STACK_INITIAL, dtype=np.float64),
            method="L-BFGS-B",
            jac=True,
            bounds=[(0.0, None)] * len(MEMBER_IDS),
            options={"maxiter": STACK_MAXITER, "ftol": STACK_FTOL, "gtol": STACK_GTOL},
        )
        coefficients = np.asarray(result.x, dtype=np.float64)
        objective_value, gradient = objective(coefficients)
        projected = projected_gradient_inf_norm(coefficients, gradient)
        failure: str | None = None
        if not result.success:
            failure = f"optimizer failed: status={result.status}: {result.message}"
        elif (
            not math.isfinite(objective_value)
            or not np.all(np.isfinite(coefficients))
            or not np.all(np.isfinite(gradient))
            or np.any(coefficients < 0.0)
        ):
            failure = "optimizer emitted nonfinite or negative fit values"
        elif projected > STACK_PROJECTED_GRADIENT_TOL:
            failure = (
                f"projected-gradient infinity norm {projected} exceeds "
                f"{STACK_PROJECTED_GRADIENT_TOL}"
            )
        fitted = StackFit(
            status="failed" if failure else "complete",
            coefficients=coefficients,
            objective_value=objective_value,
            gradient=gradient,
            projected_gradient_inf_norm=projected,
            iterations=int(result.nit),
            function_evaluations=int(result.nfev),
            optimizer_status=int(result.status),
            optimizer_message=str(result.message),
            probability_clip_counts=tuple(int(value) for value in clip_counts),
            rows_by_year=rows_by_year,
            error=None if failure is None else {"type": "StackError", "message": failure},
        )
        if failure is not None:
            return fitted
        predicted = [
            apply_logit_stack(values, coefficients) for values in yearly_probabilities.values()
        ]
        if any(not np.all(np.isfinite(values)) for values in predicted):
            return StackFit(
                **{
                    **fitted.__dict__,
                    "status": "failed",
                    "error": {
                        "type": "StackError",
                        "message": "stack emitted nonfinite fitted probabilities",
                    },
                }
            )
        return fitted
    except Exception as error:
        return StackFit(
            status="failed",
            coefficients=None,
            objective_value=None,
            gradient=None,
            projected_gradient_inf_norm=None,
            iterations=None,
            function_evaluations=None,
            optimizer_status=None,
            optimizer_message="",
            probability_clip_counts=tuple(0 for _ in MEMBER_IDS),
            rows_by_year={},
            error={"type": type(error).__name__, "message": str(error)},
        )


def apply_logit_stack(
    probabilities: Sequence[Sequence[float]], coefficients: Sequence[float]
) -> np.ndarray:
    logits, _ = logit_member_matrix(probabilities)
    weights = np.asarray(coefficients, dtype=np.float64)
    if weights.shape != (len(MEMBER_IDS),):
        raise StackError(f"stack needs exactly {len(MEMBER_IDS)} coefficients")
    if not np.all(np.isfinite(weights)) or np.any(weights < 0.0):
        raise StackError("stack coefficients must be finite and nonnegative")
    emitted = sigmoid(logits @ weights)
    if not np.all(np.isfinite(emitted)) or np.any(emitted < 0.0) or np.any(emitted > 1.0):
        raise StackError("stack emitted invalid probabilities")
    return emitted
