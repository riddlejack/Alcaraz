from __future__ import annotations

import json
from pathlib import Path

import pytest

from tennislab.models.release import (
    ReleaseBundleError,
    load_elo_state,
    predict_elo,
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
