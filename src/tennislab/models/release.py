"""Load a hash-bound tennis-lab model release bundle.

Hash validation detects corruption or substitution relative to the supplied manifest;
it does not authenticate an attacker-supplied manifest.  Because joblib is pickle-based,
verify the official archive checksum through a trusted channel before unpacking or loading
it.  This module reuses :mod:`tennislab.models.numerical` for inference; it does not
implement a second model engine.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from tennislab.models import numerical
from tennislab.models.pipeline import apply_slope
from tennislab.ratings import elo


class ReleaseBundleError(ValueError):
    """The release bundle is missing, changed, or incompatible."""


@dataclass(frozen=True)
class LoadedCheckpoint:
    """One selected annual estimator and its separately fitted calibration slope."""

    model: numerical.FittedProcedure
    slope: float
    metadata: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(root: Path, value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ReleaseBundleError(f"{field} must be a nonempty relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReleaseBundleError(f"{field} must stay inside the bundle")
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise ReleaseBundleError(f"{field} escapes the bundle") from error
    return target


def load_manifest(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = root_path / "MANIFEST.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseBundleError(f"cannot read bundle manifest: {error}") from error
    if document.get("schema_version") != 1:
        raise ReleaseBundleError("unsupported bundle manifest schema")
    if not isinstance(document.get("files"), list):
        raise ReleaseBundleError("bundle manifest files must be a list")
    if not isinstance(document.get("models"), list):
        raise ReleaseBundleError("bundle manifest models must be a list")
    return document


def verify_bundle(root: str | Path) -> dict[str, Any]:
    """Verify every payload file and reject missing or unlisted payloads."""

    root_path = Path(root).resolve()
    document = load_manifest(root_path)
    declared: dict[str, dict[str, Any]] = {}
    for entry in document["files"]:
        if not isinstance(entry, dict):
            raise ReleaseBundleError("bundle file entry must be an object")
        relative = entry.get("path")
        path = _safe_relative(root_path, relative, field="files.path")
        if relative in declared:
            raise ReleaseBundleError(f"duplicate bundle file entry: {relative}")
        if not path.is_file():
            raise ReleaseBundleError(f"missing bundle file: {relative}")
        observed_size = path.stat().st_size
        observed_hash = sha256_file(path)
        if observed_size != entry.get("bytes"):
            raise ReleaseBundleError(f"bundle file size changed: {relative}")
        if observed_hash != entry.get("sha256"):
            raise ReleaseBundleError(f"bundle file hash changed: {relative}")
        declared[str(relative)] = entry

    root_manifest = root_path / "MANIFEST.json"
    actual = {
        path.relative_to(root_path).as_posix()
        for path in root_path.rglob("*")
        if path.is_file() and path != root_manifest
    }
    if actual != set(declared):
        missing = sorted(set(declared) - actual)
        extra = sorted(actual - set(declared))
        raise ReleaseBundleError(f"bundle inventory mismatch; missing={missing}, extra={extra}")
    return document


def _model_entry(document: Mapping[str, Any], tour: str, rung: str, year: int) -> dict[str, Any]:
    matches = [
        entry
        for entry in document["models"]
        if entry.get("tour") == tour.upper()
        and entry.get("rung") == rung
        and entry.get("target_year") == year
    ]
    if len(matches) != 1:
        raise ReleaseBundleError(
            f"expected one checkpoint for {tour.upper()}/{rung}/{year}, found {len(matches)}"
        )
    return dict(matches[0])


def load_checkpoint(root: str | Path, *, tour: str, rung: str, year: int) -> LoadedCheckpoint:
    """Load one selected checkpoint after verifying the complete bundle."""

    root_path = Path(root).resolve()
    document = verify_bundle(root_path)
    metadata = _model_entry(document, tour, rung, year)
    path = _safe_relative(root_path, metadata.get("model_path"), field="model_path")
    expected_hash = metadata.get("model_sha256")
    if sha256_file(path) != expected_hash:
        raise ReleaseBundleError("selected model hash differs from its checkpoint record")

    # Frozen archive fits used this temporary module name.  The class implementation is
    # the accepted product port, and its fitted state was independently compared.
    sys.modules.setdefault("joint04_multi01_numerical", numerical)
    model = joblib.load(path)
    if not isinstance(model, numerical.FittedProcedure):
        raise ReleaseBundleError(f"unexpected checkpoint type: {type(model)!r}")
    if model.config.get("config_id") != metadata.get("config_id"):
        raise ReleaseBundleError("checkpoint config identity differs from the manifest")
    if list(model.estimator_feature_names) != metadata.get("estimator_feature_names"):
        raise ReleaseBundleError("checkpoint feature schema differs from the manifest")
    slope = float(metadata["calibration_slope"])
    if not math.isfinite(slope) or slope < 0.0:
        raise ReleaseBundleError("invalid checkpoint calibration slope")
    return LoadedCheckpoint(model=model, slope=slope, metadata=metadata)


def predict_feature_row(
    checkpoint: LoadedCheckpoint,
    values: Mapping[str, int | float | str],
    *,
    season: str = "synthetic",
    match_id: str = "synthetic-001",
) -> dict[str, float]:
    """Predict from one already-constructed model feature row.

    ``values`` is deliberately a feature-schema interface, not a player-name feature
    builder.  The bundle README records the historical state still needed for that route.
    """

    required = tuple(checkpoint.model.estimator_feature_names)
    missing = [column for column in required if column not in values]
    if missing:
        raise ReleaseBundleError(f"feature row is missing columns: {missing}")
    row: dict[str, str] = {"season": season, "match_id": match_id}
    for column in required:
        try:
            number = float(values[column])
        except (TypeError, ValueError) as error:
            raise ReleaseBundleError(f"non-numeric feature {column}") from error
        if not math.isfinite(number):
            raise ReleaseBundleError(f"non-finite feature {column}")
        row[column] = repr(number)
    table = numerical.FeatureTable.from_rows([row], ("season", "match_id", *required))
    raw = float(checkpoint.model.predict(table).probabilities[0])
    calibrated = float(apply_slope([raw], checkpoint.slope)[0])
    return {"raw_probability_a": raw, "calibrated_probability_a": calibrated}


def _player_key_from_label(label: object) -> elo.PlayerKey:
    if not isinstance(label, str) or not label:
        raise ReleaseBundleError("invalid Elo player key")
    if label.startswith("name:"):
        return (1, 0, label.removeprefix("name:"))
    try:
        return (0, int(label), "")
    except ValueError as error:
        raise ReleaseBundleError(f"invalid Elo player id: {label!r}") from error


def load_elo_state(root: str | Path, *, tour: str) -> elo.PooledElo:
    """Load one tour's source-ID-keyed pooled-Elo state and verify its state hash."""

    root_path = Path(root).resolve()
    document = verify_bundle(root_path)
    state_path = _safe_relative(
        root_path, document.get("elo", {}).get("state_path"), field="elo.state_path"
    )
    wrapper = json.loads(state_path.read_text(encoding="utf-8"))
    chosen_tour = tour.upper()
    try:
        tour_entry = wrapper["tours"][chosen_tour]
        state = tour_entry["serialized"]
        parameters = state["parameters"]
    except (KeyError, TypeError) as error:
        raise ReleaseBundleError(f"Elo state has no tour {chosen_tour}") from error
    engine = elo.PooledElo(
        initial=float(parameters["initial_rating"]),
        k=float(parameters["elo_k"]),
        scale=float(parameters["elo_scale"]),
        overall_weight=float(parameters["pooled_overall_weight"]),
        surface_weight=float(parameters["pooled_surface_weight"]),
    )
    for label, rating, matches in state["overall"]:
        key = _player_key_from_label(label)
        engine.overall[key] = float(rating)
        engine.overall_matches[key] = int(matches)
    for label, surface, rating, matches in state["surface"]:
        key = (_player_key_from_label(label), str(surface))
        engine.surface[key] = float(rating)
        engine.surface_matches[key] = int(matches)
    engine.latest_source_date = (
        dt.date.fromisoformat(state["latest_source_date"])
        if state.get("latest_source_date")
        else None
    )
    engine.applied_rows = int(state["applied_rows"])
    expected_hash = str(tour_entry["state_sha256"])
    if engine.state_hash() != expected_hash:
        raise ReleaseBundleError(f"reconstructed {chosen_tour} Elo state hash differs")
    return engine


def predict_elo(
    engine: elo.PooledElo,
    *,
    player_a_id: str = "",
    player_a_name: str = "",
    player_b_id: str = "",
    player_b_name: str = "",
    surface: str,
) -> dict[str, object]:
    """Price a source-ID pairing, or a name only when that name key exists in state."""

    player_a = elo.player_key(player_a_id, player_a_name)
    player_b = elo.player_key(player_b_id, player_b_name)
    for label, player in (("player A", player_a), ("player B", player_b)):
        if player[0] == 1 and player not in engine.overall:
            raise ReleaseBundleError(
                f"unresolved {label} name identity; this Elo snapshot is keyed by numeric "
                "source player ID, so supply player_a_id/player_b_id or an accepted crosswalk"
            )
    return engine.prospective(player_a, player_b, surface)
