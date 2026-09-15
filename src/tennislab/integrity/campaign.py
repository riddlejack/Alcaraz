"""Small production-facing fit-frame and raw-member validation interface.

Callers provide observed frames and hash-bound reference data, never a verdict flag.
These assertions establish their declared boundary, not truth of untraced upstream
data. No real target labels are needed by these structural checks.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from tennislab.models import numerical as num


class CampaignIntegrityError(ValueError):
    """A concrete campaign dataflow or membership contract was violated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CampaignIntegrityError(message)


def matrix_digest(matrix: np.ndarray) -> str:
    data = np.asarray(matrix, dtype="<f8", order="C")
    _require(bool(np.all(np.isfinite(data))), "nonfinite actual matrix")
    return hashlib.sha256(str(data.shape).encode() + data.tobytes()).hexdigest()


def assert_learned_horizon(fit_through: str, earliest_use: str, *, stage: str) -> None:
    """A learned constant or transform must precede every row that it influences."""
    _require(
        dt.date.fromisoformat(fit_through) < dt.date.fromisoformat(earliest_use),
        f"{stage} horizon {fit_through} does not precede earliest use {earliest_use}",
    )


def assert_fit_frame(
    config: Mapping[str, Any],
    features: num.FeatureTable,
    labels: num.LabelTable,
    *,
    approved_signed: Sequence[str],
    approved_context: Sequence[str],
    reference: num.FeatureTable,
    expected_keys: Sequence[tuple[str, str]],
    metadata: Mapping[tuple[str, str], Mapping[str, str]],
    fit_start: str,
    fit_through: str,
    prediction_year: int,
) -> dict[str, Any]:
    """Validate the actual pre-transform X/y passed to the numerical adapter.

    The whitelist must come from the frozen feature contract, not config itself.
    Reference is assembled independently from the frozen source bytes. The caller
    must bind this assertion to each fit; importing this function alone proves none.
    """
    tree = config["family"] in num.TREE_FAMILIES
    signed = tuple(config.get("signed_numeric_columns" if tree else "numeric_columns", ()))
    context = tuple(config.get("context_columns", ())) if tree else ()
    _require(
        signed == tuple(approved_signed) and context == tuple(approved_context),
        "actual fit columns/order differ from frozen sports contract",
    )
    columns = signed + context
    _require(bool(columns) and len(set(columns)) == len(columns), "empty/duplicate model columns")
    _require(
        features.keys == tuple(sorted(expected_keys))
        and len(features.keys) == len(set(expected_keys)),
        "actual fit membership/order differs",
    )
    _require(bool(features.keys), "empty actual fit frame")
    start, stop = dt.date.fromisoformat(fit_start), dt.date.fromisoformat(fit_through)
    _require(
        start <= stop < dt.date(prediction_year, 1, 1), "fit horizon does not precede raw year"
    )
    for key in features.keys:
        date = dt.date.fromisoformat(metadata[key]["match_date"])
        _require(start <= date <= stop, f"fit key {key} outside declared window")
        cutoff = dt.date.fromisoformat(metadata[key]["eligible_through_date"])
        _require(cutoff <= date - dt.timedelta(days=2), f"late target cutoff at {key}")
    y = labels.align_exact(features.keys)
    actual = features.matrix(columns)
    expected = reference.subset(features.keys).matrix(columns)
    _require(np.array_equal(actual, expected), "actual fit values differ from bound source frame")
    return {
        "rows": len(features.keys),
        "columns": list(columns),
        "matrix_sha256": matrix_digest(actual),
        "labels_sha256": labels.source_sha256,
        "training_keys_sha256": num.key_hash(features.keys),
        "fit_start": fit_start,
        "fit_through": fit_through,
        "prediction_year": prediction_year,
        "classes": sorted(set(y.tolist())),
    }


def assert_source_uses(uses: Sequence[Mapping[str, str]]) -> None:
    """Check observed per-use provenance edges, including target/next-outcome copies."""
    _require(bool(uses), "missing observed source uses")
    for row in uses:
        target, source = row["target_match_id"], row["source_match_id"]
        _require(source != target, f"target outcome source used for {target}")
        _require(
            row["source_kind"] in {"sports_history", "prematch_context"},
            f"forbidden source kind {row['source_kind']} for {target}",
        )
        _require(
            dt.date.fromisoformat(row["source_date"])
            <= dt.date.fromisoformat(row["eligible_through_date"]),
            f"late source {source} for {target}",
        )


def assert_raw_member(
    receipt: Mapping[str, Any],
    *,
    raw_year: int,
    member_id: str,
    expected_keys: Sequence[tuple[str, str]],
) -> None:
    _require(receipt.get("member_id") == member_id, "raw member identity differs")
    _require(receipt.get("prediction_year") == raw_year, "raw member year differs")
    _require(
        receipt.get("procedure") == "predeclared_raw_candidate",
        "same-fold selected/calibrated member",
    )
    _require(
        receipt.get("selection_years") == [] and receipt.get("calibration_years") == [],
        "raw member carries selected/calibrated lineage",
    )
    _require(
        receipt.get("prediction_keys_sha256") == num.key_hash(expected_keys),
        "raw member membership differs",
    )
    for stage in ("base_fit", "preprocessing", "state_policy", "offset"):
        value = receipt.get("horizons", {}).get(stage)
        if stage == "offset" and receipt.get("offset_applicability") == "not_applicable_non_tier":
            _require(
                value is None and receipt.get("feature_bundle") in {"base", "full"},
                "non-tier offset exemption requires an explicit non-tier bundle and null horizon",
            )
            continue
        _require(
            isinstance(value, str) and dt.date.fromisoformat(value) < dt.date(raw_year, 1, 1),
            f"{stage} horizon does not precede raw member year",
        )
    for name in ("features_sha256", "training_keys_sha256", "preprocessing_sha256"):
        value = receipt.get(name)
        _require(
            isinstance(value, str) and len(value) == 64 and len(set(value)) > 1,
            f"missing bound {name}",
        )


def assert_forecasts(
    keys: Sequence[tuple[str, str]],
    probabilities: Sequence[float],
    *,
    expected_keys: Sequence[tuple[str, str]],
    canonical_ids: Sequence[str],
) -> None:
    _require(tuple(keys) == tuple(expected_keys), "prediction key membership/order differs")
    _require(len(keys) > 0 and len(keys) == len(set(keys)), "empty/duplicate prediction keys")
    _require(
        len(canonical_ids) == len(keys) and len(set(canonical_ids)) == len(keys),
        "duplicate canonical realized match in scoring inventory",
    )
    p = np.asarray(probabilities)
    _require(
        p.shape == (len(keys),)
        and bool(np.all(np.isfinite(p)))
        and bool(np.all((p >= 0) & (p <= 1))),
        "invalid prediction probabilities",
    )


def assert_swap(original: Sequence[float], swapped: Sequence[float]) -> None:
    p, q = np.asarray(original), np.asarray(swapped)
    _require(
        p.size > 0 and p.shape == q.shape and bool(np.all(np.isfinite(p + q))),
        "invalid swap arrays",
    )
    _require(
        bool(np.allclose(p + q, 1.0, rtol=0.0, atol=1e-12)),
        "player-swap probabilities do not complement",
    )


def null_score(probabilities: Sequence[float], labels: Sequence[int]) -> dict[str, Any]:
    """Registered once-at-end fair-null likelihood-ratio test. Caller checks identity."""
    p, y = np.asarray(probabilities, dtype=float), np.asarray(labels, dtype=float)
    _require(p.ndim == 1 and p.size > 0 and y.shape == p.shape, "invalid null score shape")
    _require(
        bool(np.all(np.isfinite(p))) and bool(np.all((p >= 0) & (p <= 1))),
        "invalid null probabilities",
    )
    _require(bool(np.all(np.isin(y, [0, 1]))), "invalid null labels")
    clipped = np.clip(p, 1e-6, 1.0 - 1e-6)
    losses = -y * np.log(clipped) - (1.0 - y) * np.log1p(-clipped)
    log_lr = float(np.sum(math.log(2.0) - losses))
    threshold = math.log(4800.0)
    return {
        "n": len(p),
        "log_loss": float(np.mean(losses)),
        "oracle_conditional_expected_log_loss": float(
            np.mean(-0.5 * np.log(clipped) - 0.5 * np.log1p(-clipped))
        ),
        "log_likelihood_ratio": log_lr,
        "alarm_log_threshold": threshold,
        "mean_loss_lower_threshold": math.log(2.0) - threshold / len(p),
        "probability_clip_count": int(np.sum(p != clipped)),
        "alarm": log_lr >= threshold,
        "familywise_alpha": 0.01,
        "registered_test_count": 48,
    }
