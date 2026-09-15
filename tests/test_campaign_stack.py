"""Exact Lane E blend/stack arithmetic and optimizer controls."""

import math

import numpy as np
import pytest

from tennislab.campaign import stack


def _probabilities(rows: int = 12) -> np.ndarray:
    base = np.linspace(0.18, 0.82, rows)
    return np.column_stack(
        [np.clip(base + (index - 3.5) * 0.012, 0.01, 0.99) for index in range(8)]
    )


def test_fixed_probability_blend_uses_probability_space_and_swaps() -> None:
    def logit(probability: float) -> float:
        return math.log(probability / (1.0 - probability))

    value = stack.fixed_probability_blend([0.8], [logit(0.9)], [logit(0.5)])
    swapped = stack.fixed_probability_blend([0.2], [logit(0.1)], [logit(0.5)])
    assert value.tolist() == pytest.approx([0.75])
    assert swapped.tolist() == pytest.approx([0.25])
    assert float(value[0]) != pytest.approx(
        stack.sigmoid(np.asarray([(logit(0.8) + logit(0.7)) / 2]))[0]
    )


def test_stack_two_active_fixture_zero_coefficients_and_swap() -> None:
    probabilities = np.full((1, 8), 0.5)
    probabilities[0, :2] = (0.8, 0.6)
    coefficients = np.zeros(8)
    coefficients[:2] = 0.5
    expected = stack.sigmoid(np.asarray([(math.log(4.0) + math.log(1.5)) / 2.0], dtype=np.float64))
    observed = stack.apply_logit_stack(probabilities, coefficients)
    assert observed.tolist() == pytest.approx(expected.tolist())
    assert observed[0] != pytest.approx(0.7)
    assert stack.apply_logit_stack(probabilities, np.zeros(8)).tolist() == [0.5]
    swapped = stack.apply_logit_stack(1.0 - probabilities, coefficients)
    assert observed + swapped == pytest.approx([1.0])


def test_stack_clips_extremes_and_counts_each_member() -> None:
    probabilities = np.vstack((np.zeros(8), np.ones(8), np.full(8, 0.5)))
    logits, counts = stack.logit_member_matrix(probabilities)
    assert np.all(np.isfinite(logits))
    assert counts == (2,) * 8


def test_stack_analytical_gradient_matches_centered_difference() -> None:
    probabilities = _probabilities(10)
    logits, _ = stack.logit_member_matrix(probabilities)
    labels = np.asarray([0, 1] * 5, dtype=np.float64)
    coefficients = np.linspace(0.03, 0.24, 8)
    value, gradient = stack._objective_and_gradient(  # noqa: SLF001
        coefficients, {2014: logits}, {2014: labels}, (2014,)
    )
    assert math.isfinite(value)
    epsilon = 1e-6
    numerical = np.empty(8)
    for index in range(8):
        plus = coefficients.copy()
        minus = coefficients.copy()
        plus[index] += epsilon
        minus[index] -= epsilon
        upper = stack._objective_and_gradient(plus, {2014: logits}, {2014: labels}, (2014,))[0]
        lower = stack._objective_and_gradient(minus, {2014: logits}, {2014: labels}, (2014,))[0]
        numerical[index] = (upper - lower) / (2.0 * epsilon)
    np.testing.assert_allclose(gradient, numerical, atol=2e-9, rtol=0.0)


def test_stack_fit_converges_with_exact_controls() -> None:
    yearly = {year: _probabilities(16) for year in (2014, 2015, 2016)}
    labels = {year: [0] * 8 + [1] * 8 for year in yearly}
    fitted = stack.fit_logit_stack(yearly, labels, (2014, 2015, 2016))
    assert fitted.status == "complete"
    assert fitted.coefficients is not None
    assert np.all(fitted.coefficients >= 0.0)
    assert fitted.projected_gradient_inf_norm <= stack.STACK_PROJECTED_GRADIENT_TOL
    public = fitted.public_receipt()
    assert "objective_value" not in public
    assert public["objective_values_deferred_to_report"] is True
    assert len(public["criterion_commitment_sha256"]) == 64


def test_optimizer_failure_is_retained_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        success = False
        status = 2
        message = "planted optimizer failure"
        x = np.full(8, 0.125)
        nit = 1
        nfev = 2

    monkeypatch.setattr(stack.optimize, "minimize", lambda *args, **kwargs: Result())
    fitted = stack.fit_logit_stack({2014: _probabilities(8)}, {2014: [0, 1] * 4}, (2014,))
    assert fitted.status == "failed"
    assert fitted.error is not None
    assert "planted optimizer failure" in fitted.error["message"]
    assert fitted.coefficients is not None
    assert fitted.optimizer_status == 2
