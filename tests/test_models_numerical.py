"""The bounded adapter: fit-local transforms, swap complements, convergence receipts, cache."""

import math
from pathlib import Path

import numpy as np
import pytest

from tennislab.chain.common import ChainError
from tennislab.models import numerical as num
from tennislab.models.pipeline import RIDGE_PARAMS


def _linear_table() -> num.FeatureTable:
    return num.FeatureTable.from_rows(
        [
            {"season": "2011", "match_id": str(i), "x": str(value)}
            for i, value in enumerate((-3.0, -1.0, 1.0, 3.0))
        ],
        ("season", "match_id", "x"),
    )


def test_transforms_are_fit_only_on_training_rows() -> None:
    train = _linear_table()
    labels = num.LabelTable.from_values({key: index % 2 for index, key in enumerate(train.keys)})
    config = {
        "config_id": "isolation",
        "family": "joint_logistic",
        "numeric_columns": ["x"],
        "estimator_params": RIDGE_PARAMS,
    }
    first = num.fit_procedure(config, train, labels).fitted
    num.FeatureTable.from_rows(
        [{"season": "2012", "match_id": "x", "x": "999999"}], ("season", "match_id", "x")
    )
    second = num.fit_procedure(config, train, labels).fitted
    assert first is not None and second is not None
    assert first.rms_scale.tolist() == second.rms_scale.tolist()
    assert first.estimator.coef_.tolist() == second.estimator.coef_.tolist()


def test_swapped_carpet_unknown_player_complements() -> None:
    header = ("season", "match_id", "x", "player_a", "player_b", "surface")
    train_rows = [
        {
            "season": "2011",
            "match_id": str(i),
            "x": str((-1) ** i * (i + 1)),
            "player_a": str(i + 1),
            "player_b": str(i + 11),
            "surface": "Carpet",
        }
        for i in range(8)
    ]
    train = num.FeatureTable.from_rows(train_rows, header)
    labels = num.LabelTable.from_values({key: index % 2 for index, key in enumerate(train.keys)})
    config = {
        "config_id": "deviation",
        "family": "player_deviation_logistic",
        "numeric_columns": ["x"],
        "deviation_scale": 0.25,
        "player_a_column": "player_a",
        "player_b_column": "player_b",
        "surface_column": "surface",
        "estimator_params": RIDGE_PARAMS,
    }
    fit = num.fit_procedure(config, train, labels)
    assert fit.status == "complete"
    assert fit.fitted is not None
    original = num.FeatureTable.from_rows(
        [
            {
                "season": "2024",
                "match_id": "original",
                "x": "1.75",
                "player_a": "1",
                "player_b": "9999",
                "surface": "Carpet",
            }
        ],
        header,
    )
    swapped = num.FeatureTable.from_rows(
        [
            {
                "season": "2024",
                "match_id": "swapped",
                "x": "-1.75",
                "player_a": "9999",
                "player_b": "1",
                "surface": "Carpet",
            }
        ],
        header,
    )
    p = fit.fitted.predict(original).probabilities[0]
    q = fit.fitted.predict(swapped).probabilities[0]
    assert math.isclose(float(p + q), 1.0, abs_tol=1e-14)


def test_feature_table_refuses_outcome_columns_and_duplicate_keys() -> None:
    with pytest.raises(ChainError):
        num.FeatureTable.from_rows(
            [{"season": "2011", "match_id": "a", "a_won": "1"}], ("season", "match_id", "a_won")
        )
    with pytest.raises(ChainError):
        num.FeatureTable.from_rows(
            [
                {"season": "2011", "match_id": "a", "x": "1"},
                {"season": "2011", "match_id": "a", "x": "2"},
            ],
            ("season", "match_id", "x"),
        )


def test_a_single_class_fit_is_a_failed_attempt_not_an_exception() -> None:
    train = _linear_table()
    labels = num.LabelTable.from_values(dict.fromkeys(train.keys, 1))
    config = {
        "config_id": "one_class",
        "family": "joint_logistic",
        "numeric_columns": ["x"],
        "estimator_params": RIDGE_PARAMS,
    }
    attempt = num.fit_procedure(config, train, labels)
    assert attempt.status == "failed"
    assert attempt.error is not None
    assert "both binary classes" in attempt.error["message"]


def test_convergence_warning_fails_the_fit_with_a_receipt() -> None:
    train = _linear_table()
    labels = num.LabelTable.from_values({key: index % 2 for index, key in enumerate(train.keys)})
    config = {
        "config_id": "starved",
        "family": "joint_logistic",
        "numeric_columns": ["x"],
        "estimator_params": {**RIDGE_PARAMS, "max_iter": 1, "tol": 1e-30},
    }
    attempt = num.fit_procedure(config, train, labels)
    assert attempt.status == "failed"
    assert attempt.error == {
        "type": "ConvergenceWarning",
        "message": "convergence warning invalidates this fit",
    }
    assert any(item["category"] == "ConvergenceWarning" for item in attempt.warnings)


def test_fit_cache_reuses_only_the_exact_identity(tmp_path: Path) -> None:
    train = _linear_table()
    labels = num.LabelTable.from_values({key: index % 2 for index, key in enumerate(train.keys)})
    config = {
        "config_id": "cached",
        "family": "joint_logistic",
        "numeric_columns": ["x"],
        "estimator_params": RIDGE_PARAMS,
    }
    identity = num.fit_identity(config, "2010-12-30", train, labels, "0" * 64)
    cache = num.FileFitCache(tmp_path / "fits")
    calls = 0

    def fit() -> num.FitAttempt:
        nonlocal calls
        calls += 1
        return num.fit_procedure(config, train, labels)

    first, manifest = cache.fit_or_load(identity, train.keys, fit)
    second, reloaded = cache.fit_or_load(identity, train.keys, fit)
    assert calls == 1
    assert first.cache_reused is False and second.cache_reused is True
    assert manifest["fit_identity_sha256"] == reloaded["fit_identity_sha256"]
    assert second.fitted is not None
    np.testing.assert_array_equal(second.fitted.rms_scale, first.fitted.rms_scale)
    other = dict(identity, fit_cutoff="2011-12-30")
    cache.fit_or_load(other, train.keys, fit)
    assert calls == 2
    with pytest.raises(ChainError):
        cache.fit_or_load(identity, train.keys[:-1], fit)


def test_prediction_csv_uses_repr_floats(tmp_path: Path) -> None:
    predictions = num.Predictions(
        keys=(("2020", "a"), ("2020", "b")),
        probabilities=np.asarray([0.1, 0.25]),
        source_feature_sha256="x",
        config_id="c",
        diagnostics={},
    )
    path = tmp_path / "p.csv"
    predictions.write_csv(path)
    assert path.read_text() == "season,match_id,p_a_wins\n2020,a,0.1\n2020,b,0.25\n"
