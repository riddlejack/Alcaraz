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


@dataclass(frozen=True)
class LoadedCampaignMember:
    """One raw Lane E numerical member from the research companion bundle."""

    model: numerical.FittedProcedure
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CampaignBundle:
    """A completely verified Lane E companion bundle.

    Opening verifies the complete file inventory. Loading a selected pickle rechecks that
    model and its source fit manifest immediately before deserialization.
    """

    root: Path
    manifest: dict[str, Any]

    @classmethod
    def open(cls, root: str | Path) -> CampaignBundle:
        root_path = Path(root).resolve()
        document = verify_bundle(root_path)
        if not isinstance(document.get("campaign_models"), list):
            raise ReleaseBundleError("bundle manifest campaign_models must be a list")
        if not isinstance(document.get("campaign_decisions"), list):
            raise ReleaseBundleError("bundle manifest campaign_decisions must be a list")
        return cls(root=root_path, manifest=document)

    def load_member(self, *, tour: str, raw_year: int, member_id: str) -> LoadedCampaignMember:
        metadata = _campaign_model_entry(self.manifest, tour, raw_year, member_id)
        model_path = _safe_relative(
            self.root, metadata.get("model_path"), field="campaign model_path"
        )
        fit_manifest_path = _safe_relative(
            self.root,
            metadata.get("fit_manifest_path"),
            field="campaign fit_manifest_path",
        )
        if sha256_file(model_path) != metadata.get("model_sha256"):
            raise ReleaseBundleError("selected campaign model hash differs from its record")
        if sha256_file(fit_manifest_path) != metadata.get("fit_manifest_sha256"):
            raise ReleaseBundleError("selected campaign fit manifest hash differs from its record")
        try:
            fit_manifest = json.loads(fit_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReleaseBundleError(f"cannot read campaign fit manifest: {error}") from error
        if fit_manifest.get("model_sha256") != metadata.get("model_sha256"):
            raise ReleaseBundleError("campaign source fit manifest model binding differs")
        if fit_manifest.get("config_id") != metadata.get("config_id"):
            raise ReleaseBundleError("campaign source fit manifest config identity differs")
        if fit_manifest.get("estimator_feature_names") != metadata.get("estimator_feature_names"):
            raise ReleaseBundleError("campaign source fit manifest feature schema differs")

        sys.modules.setdefault("joint04_multi01_numerical", numerical)
        model = joblib.load(model_path)
        if not isinstance(model, numerical.FittedProcedure):
            raise ReleaseBundleError(f"unexpected campaign model type: {type(model)!r}")
        if model.config.get("config_id") != metadata.get("config_id"):
            raise ReleaseBundleError("campaign model config identity differs from the manifest")
        if list(model.estimator_feature_names) != metadata.get("estimator_feature_names"):
            raise ReleaseBundleError("campaign model feature schema differs from the manifest")
        observed_type = f"{type(model.estimator).__module__}.{type(model.estimator).__qualname__}"
        if observed_type != metadata.get("estimator_type"):
            raise ReleaseBundleError("campaign estimator type differs from the manifest")
        return LoadedCampaignMember(model=model, metadata=metadata)

    def load_decision(self, *, tour: str, target_year: int) -> dict[str, Any]:
        metadata = _campaign_decision_entry(self.manifest, tour, target_year)
        path = _safe_relative(self.root, metadata.get("path"), field="campaign decision path")
        if sha256_file(path) != metadata.get("sha256"):
            raise ReleaseBundleError("selected campaign decision hash differs from its record")
        try:
            decision = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReleaseBundleError(f"cannot read campaign decision: {error}") from error
        _validate_campaign_decision(decision, metadata)
        return decision


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


def _campaign_model_entry(
    document: Mapping[str, Any], tour: str, raw_year: int, member_id: str
) -> dict[str, Any]:
    matches = [
        entry
        for entry in document.get("campaign_models", [])
        if entry.get("tour") == tour.upper()
        and entry.get("raw_year") == raw_year
        and entry.get("member_id") == member_id
    ]
    if len(matches) != 1:
        raise ReleaseBundleError(
            f"expected one campaign member for {tour.upper()}/{raw_year}/{member_id}, "
            f"found {len(matches)}"
        )
    return dict(matches[0])


def _campaign_decision_entry(
    document: Mapping[str, Any], tour: str, target_year: int
) -> dict[str, Any]:
    matches = [
        entry
        for entry in document.get("campaign_decisions", [])
        if entry.get("tour") == tour.upper() and entry.get("target_year") == target_year
    ]
    if len(matches) != 1:
        raise ReleaseBundleError(
            f"expected one campaign decision for {tour.upper()}/{target_year}, found {len(matches)}"
        )
    return dict(matches[0])


def _finite_nonnegative(value: object, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ReleaseBundleError(f"{field} must be numeric") from error
    if not math.isfinite(number) or number < 0.0:
        raise ReleaseBundleError(f"{field} must be finite and nonnegative")
    return number


def _validate_campaign_decision(decision: object, metadata: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ReleaseBundleError("campaign decision must be an object")
    if decision.get("outer_year") != metadata.get("target_year"):
        raise ReleaseBundleError("campaign decision target year differs from the manifest")
    try:
        s2 = decision["S2"]
        trials = s2["candidate_trials"]
        selection = s2["selection"]
        s3 = decision["S3"]
    except (KeyError, TypeError) as error:
        raise ReleaseBundleError("campaign decision lacks S2/S3 parameters") from error
    expected_candidates = ("rf_leaf50", "rf_leaf100")
    if not isinstance(trials, dict) or set(trials) != set(expected_candidates):
        raise ReleaseBundleError("campaign decision S2 candidate inventory differs")
    candidate_slopes = {
        member_id: _finite_nonnegative(trials[member_id].get("slope"), field="S2 slope")
        for member_id in expected_candidates
    }
    selected_member = selection.get("selected_candidate_id")
    if selected_member not in candidate_slopes:
        raise ReleaseBundleError("campaign decision selected S2 member differs")
    selected_slope = _finite_nonnegative(selection.get("selected_slope"), field="selected S2 slope")
    if selected_slope != candidate_slopes[selected_member]:
        raise ReleaseBundleError("campaign decision selected S2 slope differs")
    member_order = s3.get("member_order")
    coefficients = s3.get("coefficients")
    expected_order = metadata.get("s3_member_order")
    if member_order != expected_order:
        raise ReleaseBundleError("campaign decision S3 member order differs from the manifest")
    if not isinstance(coefficients, list) or len(coefficients) != len(expected_order or []):
        raise ReleaseBundleError("campaign decision S3 coefficients differ")
    checked_coefficients = [
        _finite_nonnegative(value, field="S3 coefficient") for value in coefficients
    ]
    if candidate_slopes != metadata.get("s2_candidate_slopes"):
        raise ReleaseBundleError("campaign decision S2 slopes differ from the manifest")
    if selected_member != metadata.get("s2_selected_member"):
        raise ReleaseBundleError("campaign decision selected S2 member differs from the manifest")
    if selected_slope != metadata.get("s2_selected_slope"):
        raise ReleaseBundleError("campaign decision selected S2 slope differs from the manifest")
    if checked_coefficients != metadata.get("s3_coefficients"):
        raise ReleaseBundleError("campaign decision S3 coefficients differ from the manifest")
    if decision.get("target_outcomes_read_or_scored") is not False:
        raise ReleaseBundleError("campaign decision does not preserve the forecast barrier")
    return decision


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


def open_campaign_bundle(root: str | Path) -> CampaignBundle:
    """Verify and open the retrospective Lane E research companion bundle."""

    return CampaignBundle.open(root)


def load_campaign_member(
    root: str | Path, *, tour: str, raw_year: int, member_id: str
) -> LoadedCampaignMember:
    """Load one raw campaign member by tour, raw year, and member ID."""

    return open_campaign_bundle(root).load_member(tour=tour, raw_year=raw_year, member_id=member_id)


def load_campaign_decision(root: str | Path, *, tour: str, target_year: int) -> dict[str, Any]:
    """Load one target-fold S2/S3 decision from a completely verified bundle."""

    return open_campaign_bundle(root).load_decision(tour=tour, target_year=target_year)


def _predict_raw_feature_row(
    model: numerical.FittedProcedure,
    values: Mapping[str, int | float | str],
    *,
    season: str,
    match_id: str,
) -> float:
    required = tuple(model.estimator_feature_names)
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
    return float(model.predict(table).probabilities[0])


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

    raw = _predict_raw_feature_row(checkpoint.model, values, season=season, match_id=match_id)
    calibrated = float(apply_slope([raw], checkpoint.slope)[0])
    return {"raw_probability_a": raw, "calibrated_probability_a": calibrated}


def predict_campaign_feature_row(
    member: LoadedCampaignMember,
    values: Mapping[str, int | float | str],
    *,
    season: str = "synthetic",
    match_id: str = "synthetic-001",
) -> dict[str, float]:
    """Predict one raw numerical member from an already-constructed feature row."""

    probability = _predict_raw_feature_row(member.model, values, season=season, match_id=match_id)
    return {"raw_probability_a": probability}


def combine_campaign_candidates(
    decision: Mapping[str, Any], raw_member_probabilities: Mapping[str, int | float]
) -> dict[str, float]:
    """Apply a saved fold's S2 slope and S3 coefficients to eight raw probabilities.

    This emits only the evaluated S2 and S3 research candidates. The incumbent S0 remains
    in the separate accepted release, and no candidate becomes the default through this API.
    """

    from tennislab.campaign.members import MEMBER_IDS
    from tennislab.campaign.stack import apply_logit_stack

    synthetic_metadata = {
        "target_year": decision.get("outer_year"),
        "s2_candidate_slopes": {
            member_id: decision.get("S2", {})
            .get("candidate_trials", {})
            .get(member_id, {})
            .get("slope")
            for member_id in ("rf_leaf50", "rf_leaf100")
        },
        "s2_selected_member": decision.get("S2", {})
        .get("selection", {})
        .get("selected_candidate_id"),
        "s2_selected_slope": decision.get("S2", {}).get("selection", {}).get("selected_slope"),
        "s3_member_order": list(MEMBER_IDS),
        "s3_coefficients": decision.get("S3", {}).get("coefficients"),
    }
    checked = _validate_campaign_decision(dict(decision), synthetic_metadata)
    if set(raw_member_probabilities) != set(MEMBER_IDS):
        raise ReleaseBundleError("campaign combination needs exactly the eight raw members")
    probabilities: dict[str, float] = {}
    for member_id in MEMBER_IDS:
        try:
            value = float(raw_member_probabilities[member_id])
        except (TypeError, ValueError) as error:
            raise ReleaseBundleError(f"invalid raw probability for {member_id}") from error
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ReleaseBundleError(f"invalid raw probability for {member_id}")
        probabilities[member_id] = value
    selected = checked["S2"]["selection"]
    s2 = float(
        apply_slope(
            [probabilities[str(selected["selected_candidate_id"])]],
            float(selected["selected_slope"]),
        )[0]
    )
    ordered = [[probabilities[member_id] for member_id in checked["S3"]["member_order"]]]
    s3 = float(apply_logit_stack(ordered, checked["S3"]["coefficients"])[0])
    return {"S2_probability_a": s2, "S3_probability_a": s3}


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
