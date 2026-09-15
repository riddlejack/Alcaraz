from __future__ import annotations

import json
from pathlib import Path

import pytest

from tennislab.models.release import ReleaseBundleError, load_elo_state, verify_bundle
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
