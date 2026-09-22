"""Gauge-free pair geometry from native serve/return forecasts.

The export is intentionally smaller than the native state.  It exposes the
two serve logits only through pair geometry, plus the corresponding geometry
of their retained diagonal-projection covariance.  It never exports component
state levels or outcome labels.

``export_pair_geometry`` consumes :meth:`PrequentialServeReturn.forecast`
output.  ``export_selected_geometry`` is the narrow adapter for the historical
``selected_matches.csv`` rows whose uncertainty fields use shorter names.
Both share :func:`pair_geometry` as the only numerical transform.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Mapping
from typing import Any, Literal

from tennislab.chain.common import ChainError

__all__ = [
    "STATE_GEOMETRY_FEATURES",
    "StateExportError",
    "export_pair_geometry",
    "export_selected_geometry",
    "pair_geometry",
]

StateAncestry = Literal["main", "tier"]

# Signed predictors first, followed by invariant context.  This is also the
# insertion order returned by pair_geometry and both adapters.
STATE_GEOMETRY_FEATURES = (
    "serve_logit_diff",
    "serve_logit_variance_asymmetry",
    "serve_logit_sum",
    "serve_logit_variance_diff",
    "serve_logit_variance_sum",
)

_FORBIDDEN_LABEL_FIELDS = frozenset(
    {
        "a_won",
        "b_won",
        "label",
        "match_winner",
        "outcome",
        "winner",
        "winner_id",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


class StateExportError(ChainError):
    """The forecast row cannot support the declared label-free state export."""


def _is_missing(value: object) -> bool:
    return value is None or value == ""


def _number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise StateExportError(f"{field} must be numeric")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise StateExportError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise StateExportError(f"{field} must be finite")
    return result


def _canonical_date(value: object, field: str) -> dt.date:
    if not isinstance(value, str):
        raise StateExportError(f"{field} must be a canonical ISO date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise StateExportError(f"{field} must be a canonical ISO date") from exc
    if parsed.isoformat() != value:
        raise StateExportError(f"{field} must be a canonical ISO date")
    return parsed


def _validate_ancestry(state_ancestry: str) -> StateAncestry:
    if state_ancestry not in {"main", "tier"}:
        raise StateExportError("state_ancestry must be 'main' or 'tier'")
    return state_ancestry  # type: ignore[return-value]


def _validate_label_barrier(row: Mapping[str, Any]) -> None:
    present = sorted(_FORBIDDEN_LABEL_FIELDS & {str(field).lower() for field in row})
    if present:
        raise StateExportError(f"outcome label fields are forbidden: {', '.join(present)}")


def _empty_geometry() -> dict[str, float | int | None]:
    return {
        "serve_logit_diff": None,
        "serve_logit_variance_asymmetry": None,
        "serve_logit_sum": None,
        "serve_logit_variance_diff": None,
        "serve_logit_variance_sum": None,
        "state_geometry_missing": 1,
    }


def pair_geometry(
    p_a_serve: object,
    p_b_serve: object,
    variance_a: object,
    variance_b: object,
    covariance: object,
) -> dict[str, float | int | None]:
    """Return five pair quantities, or one explicit all-feature missing row.

    A zero is a measured value.  A missing value is represented by ``None`` in
    all five features and ``state_geometry_missing == 1``; no partial geometry
    is emitted or imputed.  Nonmissing covariance must define a finite positive
    semidefinite 2x2 matrix.

    Under an A/B swap, ``serve_logit_diff`` and
    ``serve_logit_variance_asymmetry`` change sign.  The other three features
    are invariant.
    """

    values = (p_a_serve, p_b_serve, variance_a, variance_b, covariance)
    if any(_is_missing(value) for value in values):
        present = (
            (p_a_serve, "p_a_serve"),
            (p_b_serve, "p_b_serve"),
            (variance_a, "variance_a"),
            (variance_b, "variance_b"),
            (covariance, "covariance"),
        )
        parsed = {
            field: _number(value, field) for value, field in present if not _is_missing(value)
        }
        for field in ("p_a_serve", "p_b_serve"):
            if field in parsed and not 0.0 < parsed[field] < 1.0:
                raise StateExportError("serve probabilities must lie strictly inside (0,1)")
        for field in ("variance_a", "variance_b"):
            if field in parsed and parsed[field] < 0.0:
                raise StateExportError("serve-logit variances must be nonnegative")
        return _empty_geometry()

    p_a = _number(p_a_serve, "p_a_serve")
    p_b = _number(p_b_serve, "p_b_serve")
    if not 0.0 < p_a < 1.0 or not 0.0 < p_b < 1.0:
        raise StateExportError("serve probabilities must lie strictly inside (0,1)")
    var_a = _number(variance_a, "variance_a")
    var_b = _number(variance_b, "variance_b")
    cov = _number(covariance, "covariance")
    if var_a < 0.0 or var_b < 0.0:
        raise StateExportError("serve-logit variances must be nonnegative")

    scale = max(1e-300, var_a * var_b, cov * cov)
    if var_a * var_b - cov * cov < -1e-12 * scale:
        raise StateExportError("serve-logit covariance matrix is not positive semidefinite")

    eta_a = math.log(p_a / (1.0 - p_a))
    eta_b = math.log(p_b / (1.0 - p_b))
    variance_diff = var_a + var_b - 2.0 * cov
    variance_sum = var_a + var_b + 2.0 * cov
    tolerance = 1e-12 * max(1e-300, var_a, var_b, abs(cov))
    if variance_diff < -tolerance or variance_sum < -tolerance:
        raise StateExportError("derived serve-logit variance is negative")

    return {
        "serve_logit_diff": eta_a - eta_b,
        "serve_logit_variance_asymmetry": var_a - var_b,
        "serve_logit_sum": eta_a + eta_b,
        "serve_logit_variance_diff": max(0.0, variance_diff),
        "serve_logit_variance_sum": max(0.0, variance_sum),
        "state_geometry_missing": 0,
    }


def export_pair_geometry(
    forecast: Mapping[str, Any], *, state_ancestry: StateAncestry
) -> dict[str, Any]:
    """Extract pair geometry and chronology from a native forecast mapping."""

    _validate_label_barrier(forecast)
    ancestry = _validate_ancestry(state_ancestry)
    match_date = _canonical_date(forecast.get("match_date"), "match_date")
    cutoff = _canonical_date(forecast.get("eligible_through_date"), "eligible_through_date")
    if cutoff > match_date:
        raise StateExportError("eligible_through_date exceeds match_date")

    latest_value = forecast.get("latest_dynamic_source_date")
    latest: str | None = None
    if not _is_missing(latest_value):
        latest_date = _canonical_date(latest_value, "latest_dynamic_source_date")
        if latest_date > cutoff:
            raise StateExportError("latest_dynamic_source_date exceeds eligible_through_date")
        latest = latest_date.isoformat()

    geometry = pair_geometry(
        forecast.get("dynamic_p_a_serve"),
        forecast.get("dynamic_p_b_serve"),
        forecast.get("dynamic_a_serve_latent_variance"),
        forecast.get("dynamic_b_serve_latent_variance"),
        forecast.get("dynamic_a_b_serve_logit_covariance_diagonal_projection"),
    )
    return {
        **geometry,
        "state_ancestry": ancestry,
        "eligible_through_date": cutoff.isoformat(),
        "latest_state_source_date": latest,
    }


def export_selected_geometry(
    row: Mapping[str, Any],
    *,
    state_ancestry: StateAncestry,
    source_sha256: str,
    replay_config_sha256: str,
) -> dict[str, Any]:
    """Adapt a saved native selected-match row without inventing provenance.

    Historical SR02/TIER01 selected rows do not retain the actual latest state
    source date.  The adapter therefore reports it as unavailable and declares
    the replay's retrospective D-2 cutoff convention explicitly.
    """

    _validate_label_barrier(row)
    ancestry = _validate_ancestry(state_ancestry)
    if not _SHA256.fullmatch(source_sha256):
        raise StateExportError("source_sha256 must be lowercase SHA-256 hex")
    if not _SHA256.fullmatch(replay_config_sha256):
        raise StateExportError("replay_config_sha256 must be lowercase SHA-256 hex")
    match_date = _canonical_date(row.get("match_date"), "match_date")
    cutoff = match_date - dt.timedelta(days=2)
    geometry = pair_geometry(
        row.get("dynamic_p_a_serve"),
        row.get("dynamic_p_b_serve"),
        row.get("dynamic_a_logit_variance"),
        row.get("dynamic_b_logit_variance"),
        row.get("dynamic_a_b_logit_covariance"),
    )
    return {
        **geometry,
        "state_ancestry": ancestry,
        "eligible_through_date": cutoff.isoformat(),
        "cutoff_convention": "match_date_minus_2_calendar_days_retrospective",
        "latest_state_source_date": None,
        "source_sha256": source_sha256,
        "replay_config_sha256": replay_config_sha256,
    }
