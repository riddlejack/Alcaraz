from __future__ import annotations

import json
import math
from pathlib import Path

import joblib
import pytest

from tennislab.models import numerical
from tennislab.models.pipeline import RIDGE_PARAMS
from tennislab.models.release import (
    ReleaseBundleError,
    combine_campaign_candidates,
    load_campaign_member,
    load_elo_state,
    open_campaign_bundle,
    predict_campaign_feature_row,
    predict_elo,
    sha256_file,
    verify_bundle,
)
from tennislab.ratings.elo import PooledElo


def _write_manifest(root: Path, files: list[dict[str, object]], **extra: object) -> None:
    root.joinpath("MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "release_id": "synthetic-test",
                "files": files,
                "models": [],
                **extra,
            }
        ),
        encoding="utf-8",
    )


def test_verify_bundle_detects_payload_change(tmp_path: Path) -> None:
    payload = tmp_path / "payload.txt"
    payload.write_text("original\n", encoding="utf-8")
    import hashlib

    _write_manifest(
        tmp_path,
        [
            {
                "path": "payload.txt",
                "bytes": payload.stat().st_size,
                "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                "role": "synthetic",
            }
        ],
    )
    assert verify_bundle(tmp_path)["release_id"] == "synthetic-test"

    payload.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ReleaseBundleError, match="changed"):
        verify_bundle(tmp_path)


def test_verify_bundle_rejects_unlisted_file(tmp_path: Path) -> None:
    _write_manifest(tmp_path, [])
    (tmp_path / "extra.txt").write_text("not declared\n", encoding="utf-8")
    with pytest.raises(ReleaseBundleError, match="inventory mismatch"):
        verify_bundle(tmp_path)


def test_verify_bundle_rejects_nested_unlisted_manifest(tmp_path: Path) -> None:
    _write_manifest(tmp_path, [])
    nested = tmp_path / "nested" / "MANIFEST.json"
    nested.parent.mkdir()
    nested.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ReleaseBundleError, match="inventory mismatch"):
        verify_bundle(tmp_path)


def test_load_empty_elo_state_round_trips_state_hash(tmp_path: Path) -> None:
    import hashlib

    engine = PooledElo()
    state = json.loads(engine.serialize())
    wrapper = {
        "tours": {
            "ATP": {
                "serialized": state,
                "state_sha256": engine.state_hash(),
            }
        }
    }
    state_path = tmp_path / "elo" / "state.json"
    state_path.parent.mkdir()
    state_path.write_text(json.dumps(wrapper), encoding="utf-8")
    _write_manifest(
        tmp_path,
        [
            {
                "path": "elo/state.json",
                "bytes": state_path.stat().st_size,
                "sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
                "role": "synthetic Elo state",
            }
        ],
        elo={"state_path": "elo/state.json"},
    )

    loaded = load_elo_state(tmp_path, tour="ATP")
    assert loaded.state_hash() == engine.state_hash()


def test_predict_elo_uses_known_source_ids_and_rejects_unresolved_names() -> None:
    player_a = (0, 100644, "")
    player_b = (0, 101736, "")
    engine = PooledElo()
    engine.overall[player_a] = 1900.0
    engine.overall[player_b] = 1700.0
    engine.overall_matches[player_a] = 10
    engine.overall_matches[player_b] = 10
    engine.surface[(player_a, "Hard")] = 1850.0
    engine.surface[(player_b, "Hard")] = 1650.0
    engine.surface_matches[(player_a, "Hard")] = 5
    engine.surface_matches[(player_b, "Hard")] = 5

    result = predict_elo(
        engine,
        player_a_id="100644",
        player_b_id="101736",
        surface="Hard",
    )
    assert result["cold_start_overall"] is False
    assert result["cold_start_surface"] is False
    assert result["p_x"] > 0.5

    with pytest.raises(ReleaseBundleError, match="numeric source player ID"):
        predict_elo(
            engine,
            player_a_name="Novak Djokovic",
            player_b_name="Rafael Nadal",
            surface="Hard",
        )


def _write_synthetic_campaign_bundle(root: Path) -> None:
    table = numerical.FeatureTable.from_rows(
        [
            {"season": "2011", "match_id": str(index), "x": str(value)}
            for index, value in enumerate((-3.0, -1.0, 1.0, 3.0))
        ],
        ("season", "match_id", "x"),
    )
    labels = numerical.LabelTable.from_values(
        {key: index % 2 for index, key in enumerate(table.keys)}
    )
    fitted = numerical.fit_procedure(
        {
            "config_id": "ridge__full__ridge_c001",
            "family": "joint_logistic",
            "numeric_columns": ["x"],
            "estimator_params": RIDGE_PARAMS,
        },
        table,
        labels,
    ).fitted
    assert fitted is not None
    model_path = root / "models/atp/2014/ridge_c001/model.joblib"
    model_path.parent.mkdir(parents=True)
    joblib.dump(fitted, model_path, compress=0)
    fit_path = model_path.with_name("source_fit_manifest.json")
    fit_path.write_text(
        json.dumps(
            {
                "status": "complete",
                "config_id": "ridge__full__ridge_c001",
                "model_sha256": sha256_file(model_path),
                "estimator_feature_names": ["x"],
            }
        ),
        encoding="utf-8",
    )
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "role": "synthetic",
        }
        for path in (model_path, fit_path)
    ]
    _write_manifest(
        root,
        files,
        campaign_models=[
            {
                "tour": "ATP",
                "raw_year": 2014,
                "member_id": "ridge_c001",
                "config_id": "ridge__full__ridge_c001",
                "model_path": model_path.relative_to(root).as_posix(),
                "model_sha256": sha256_file(model_path),
                "fit_manifest_path": fit_path.relative_to(root).as_posix(),
                "fit_manifest_sha256": sha256_file(fit_path),
                "estimator_feature_names": ["x"],
                "estimator_type": ("sklearn.linear_model._logistic.LogisticRegression"),
            }
        ],
        campaign_decisions=[],
    )


def test_campaign_loader_uses_tour_raw_year_member_key_and_asymmetric_row(tmp_path: Path) -> None:
    _write_synthetic_campaign_bundle(tmp_path)
    bundle = open_campaign_bundle(tmp_path)
    member = bundle.load_member(tour="ATP", raw_year=2014, member_id="ridge_c001")
    first = predict_campaign_feature_row(member, {"x": 1.75})["raw_probability_a"]
    second = predict_campaign_feature_row(member, {"x": -1.75})["raw_probability_a"]
    assert first != second
    assert math.isclose(first + second, 1.0, abs_tol=1e-14)


def test_campaign_loader_rejects_corruption_before_joblib(tmp_path: Path, monkeypatch) -> None:
    _write_synthetic_campaign_bundle(tmp_path)
    model_path = tmp_path / "models/atp/2014/ridge_c001/model.joblib"
    model_path.write_bytes(model_path.read_bytes() + b"changed")
    called = False

    def forbidden_load(path: Path) -> object:
        nonlocal called
        called = True
        raise AssertionError(f"deserialized changed file: {path}")

    monkeypatch.setattr("tennislab.models.release.joblib.load", forbidden_load)
    with pytest.raises(ReleaseBundleError, match="changed"):
        load_campaign_member(tmp_path, tour="ATP", raw_year=2014, member_id="ridge_c001")
    assert called is False


def test_campaign_combination_applies_saved_s2_and_s3_parameters() -> None:
    order = [
        "result_elo",
        "hgb_leaf07_depth3",
        "hgb_leaf15_depth4",
        "ridge_c001",
        "ridge_c01",
        "ridge_c1",
        "rf_leaf50",
        "rf_leaf100",
    ]
    decision = {
        "outer_year": 2024,
        "target_outcomes_read_or_scored": False,
        "S2": {
            "candidate_trials": {
                "rf_leaf50": {"slope": 0.5},
                "rf_leaf100": {"slope": 2.0},
            },
            "selection": {
                "selected_candidate_id": "rf_leaf100",
                "selected_slope": 2.0,
            },
        },
        "S3": {"member_order": order, "coefficients": [1.0] + [0.0] * 7},
    }
    raw = {member_id: 0.5 for member_id in order}
    raw["result_elo"] = 0.7
    raw["rf_leaf100"] = 0.8
    result = combine_campaign_candidates(decision, raw)
    assert result["S3_probability_a"] == pytest.approx(0.7)
    assert result["S2_probability_a"] > 0.8
