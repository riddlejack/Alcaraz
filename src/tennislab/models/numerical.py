"""Bounded scikit-learn adapter for the frozen JOINT-004 feature interface.

Ported from the archive's ``references/MULTI01_models/numerical.py`` (the file the
TIER01 and WTA02 runners loaded by path at a pinned hash). The public fitting API
receives training labels; the prediction API never does. Feature construction,
chronological fold construction, scoring and scientific claims stay outside the
adapter and exchange exact match keys.

What is kept: the three estimator families (histogram gradient boosting, ridge or
logistic, random forest), swap-augmented tree fits and swap-symmetrised prediction, the
RMS scaling fitted on training rows only, the convergence receipt that fails a fit on
any ``ConvergenceWarning``, the exact-identity joblib fit cache, and the
``canonical_json``/``sha256_json`` conventions (``allow_nan=False``) every identity hash
is built from.

What is dropped: the synthetic-fixture CLI and the MULTI01 bundle validator (both
resolved paths against the source file's location), ``LabelTable.read_csv`` (a stage
reads outcomes only through ``tennislab.chain.labels``), and the trial scoring and
selection helpers the runners never called (a proper score on outcomes belongs to
``tennislab.evaluation``).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import time
import warnings
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import scipy
import scipy.sparse as sp
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from tennislab.chain.common import ChainError, sha256

KEY_COLUMNS = ("season", "match_id")
FORBIDDEN_FEATURE_COLUMNS = frozenset(
    {"a_won", "winner", "winner_id", "loser", "loser_id", "score", "status"}
)
LOGISTIC_FAMILIES = frozenset(
    {"trained_ratings_logistic", "joint_logistic", "player_deviation_logistic"}
)
TREE_FAMILIES = frozenset({"hist_gradient_boosting", "random_forest"})
ALL_FAMILIES = LOGISTIC_FAMILIES | TREE_FAMILIES


class NumericalError(ChainError):
    """A fail-closed input, fitting, prediction or cache error."""


sha256_file = sha256


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return repr(value)


def key_hash(keys: Sequence[tuple[str, str]]) -> str:
    payload = "".join(f"{season},{match_id}\n" for season, match_id in keys)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_finite(value: str, column: str, key: tuple[str, str]) -> float:
    if value == "":
        raise NumericalError(f"blank model value for {column} at {key}")
    try:
        number = float(value)
    except ValueError as error:
        raise NumericalError(f"invalid numeric value for {column} at {key}: {value!r}") from error
    if not math.isfinite(number):
        raise NumericalError(f"non-finite model value for {column} at {key}: {value!r}")
    return number


@dataclass(frozen=True)
class FeatureTable:
    header: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    source_path: str
    source_sha256: str

    @classmethod
    def read_csv(
        cls,
        path: Path,
        expected_sha256: str | None = None,
        expected_header: Sequence[str] | None = None,
    ) -> FeatureTable:
        observed_hash = sha256_file(path)
        if expected_sha256 is not None and observed_hash != expected_sha256:
            raise NumericalError(
                f"feature hash mismatch for {path}: {observed_hash} != {expected_sha256}"
            )
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            records = tuple(reader)
        if expected_header is not None and header != tuple(expected_header):
            raise NumericalError("feature header differs from frozen ordered header")
        return cls.from_rows(records, header, str(path), observed_hash)

    @classmethod
    def from_rows(
        cls,
        records: Iterable[dict[str, str]],
        header: Sequence[str],
        source_path: str = "<memory>",
        source_sha256: str | None = None,
    ) -> FeatureTable:
        header_tuple = tuple(header)
        missing_key_columns = [column for column in KEY_COLUMNS if column not in header_tuple]
        if missing_key_columns:
            raise NumericalError(f"feature table missing key columns: {missing_key_columns}")
        forbidden = sorted(FORBIDDEN_FEATURE_COLUMNS.intersection(header_tuple))
        if forbidden:
            raise NumericalError(f"feature table contains forbidden outcome columns: {forbidden}")
        normalized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for record in records:
            if set(record) != set(header_tuple):
                raise NumericalError("feature row columns differ from header")
            row = {column: str(record[column]) for column in header_tuple}
            key = (row["season"], row["match_id"])
            if not all(key):
                raise NumericalError("feature key cannot be blank")
            if key in seen:
                raise NumericalError(f"duplicate feature key: {key}")
            seen.add(key)
            normalized.append(row)
        normalized.sort(key=lambda row: (row["season"], row["match_id"]))
        if source_sha256 is None:
            source_sha256 = sha256_json({"header": header_tuple, "rows": normalized})
        return cls(header_tuple, tuple(normalized), source_path, source_sha256)

    @property
    def keys(self) -> tuple[tuple[str, str], ...]:
        return tuple((row["season"], row["match_id"]) for row in self.rows)

    def require_columns(self, columns: Sequence[str]) -> None:
        if len(set(columns)) != len(columns):
            raise NumericalError("ordered model columns contain duplicates")
        missing = [column for column in columns if column not in self.header]
        if missing:
            raise NumericalError(f"feature table missing ordered model columns: {missing}")

    def matrix(self, columns: Sequence[str]) -> np.ndarray:
        self.require_columns(columns)
        result = np.empty((len(self.rows), len(columns)), dtype=np.float64)
        for row_index, row in enumerate(self.rows):
            key = (row["season"], row["match_id"])
            for column_index, column in enumerate(columns):
                result[row_index, column_index] = parse_finite(row[column], column, key)
        return result

    def subset(self, keys: Iterable[tuple[str, str]]) -> FeatureTable:
        requested = tuple(sorted(set(keys)))
        by_key = {(row["season"], row["match_id"]): row for row in self.rows}
        missing = [key for key in requested if key not in by_key]
        if missing:
            raise NumericalError(f"feature subset keys missing: {missing[:5]}")
        records = [by_key[key] for key in requested]
        return FeatureTable.from_rows(
            records,
            self.header,
            f"{self.source_path}#subset",
            sha256_json({"parent_sha256": self.source_sha256, "keys_sha256": key_hash(requested)}),
        )


@dataclass(frozen=True)
class LabelTable:
    """Binary outcomes keyed like the feature table; built from values, never from a file."""

    values: dict[tuple[str, str], int]
    source_path: str
    source_sha256: str

    @classmethod
    def from_values(
        cls, values: dict[tuple[str, str], int], source_path: str = "<memory>"
    ) -> LabelTable:
        normalized: dict[tuple[str, str], int] = {}
        for key, value in values.items():
            if value not in {0, 1}:
                raise NumericalError(f"label must be binary at {key}")
            normalized[(str(key[0]), str(key[1]))] = int(value)
        return cls(normalized, source_path, sha256_json(sorted(normalized.items())))

    def align_exact(self, keys: Sequence[tuple[str, str]]) -> np.ndarray:
        if set(keys) != set(self.values):
            missing = sorted(set(keys) - set(self.values))
            extra = sorted(set(self.values) - set(keys))
            raise NumericalError(
                f"feature/label key mismatch; missing labels={missing[:5]}, extra labels={extra[:5]}"
            )
        return np.asarray([self.values[key] for key in keys], dtype=np.int8)

    def subset(self, keys: Iterable[tuple[str, str]]) -> LabelTable:
        requested = tuple(sorted(set(keys)))
        missing = [key for key in requested if key not in self.values]
        if missing:
            raise NumericalError(f"label subset keys missing: {missing[:5]}")
        values = {key: self.values[key] for key in requested}
        return LabelTable(
            values,
            f"{self.source_path}#subset",
            sha256_json({"parent_sha256": self.source_sha256, "keys_sha256": key_hash(requested)}),
        )


@dataclass(frozen=True)
class IdentityVocabulary:
    main_players: tuple[str, ...]
    clay_players: tuple[str, ...]
    grass_players: tuple[str, ...]
    carpet_players: tuple[str, ...] = ()

    @classmethod
    def fit(
        cls,
        features: FeatureTable,
        player_a_column: str,
        player_b_column: str,
        surface_column: str,
    ) -> IdentityVocabulary:
        features.require_columns((player_a_column, player_b_column, surface_column))
        main: set[str] = set()
        clay: set[str] = set()
        grass: set[str] = set()
        carpet: set[str] = set()
        for row in features.rows:
            players = (row[player_a_column], row[player_b_column])
            if any(player == "" for player in players):
                raise NumericalError("player identity cannot be blank")
            main.update(players)
            if row[surface_column] == "Clay":
                clay.update(players)
            elif row[surface_column] == "Grass":
                grass.update(players)
            elif row[surface_column] == "Carpet":
                carpet.update(players)
            elif row[surface_column] != "Hard":
                raise NumericalError(f"unsupported surface {row[surface_column]!r}")

        def stable(values: set[str]) -> tuple[str, ...]:
            try:
                return tuple(sorted(values, key=lambda value: (int(value), value)))
            except ValueError:
                return tuple(sorted(values))

        return cls(stable(main), stable(clay), stable(grass), stable(carpet))

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(
            [f"player_hard_reference::{player}" for player in self.main_players]
            + [f"player_clay_contrast::{player}" for player in self.clay_players]
            + [f"player_grass_contrast::{player}" for player in self.grass_players]
            + [f"player_carpet_contrast::{player}" for player in self.carpet_players]
        )

    def matrix(
        self,
        features: FeatureTable,
        player_a_column: str,
        player_b_column: str,
        surface_column: str,
        scale: float,
    ) -> sp.csr_matrix:
        if not math.isfinite(scale) or scale <= 0:
            raise NumericalError("identity deviation scale must be finite and positive")
        main_index = {player: index for index, player in enumerate(self.main_players)}
        clay_offset = len(self.main_players)
        clay_index = {player: clay_offset + index for index, player in enumerate(self.clay_players)}
        grass_offset = clay_offset + len(self.clay_players)
        grass_index = {
            player: grass_offset + index for index, player in enumerate(self.grass_players)
        }
        carpet_offset = grass_offset + len(self.grass_players)
        carpet_index = {
            player: carpet_offset + index for index, player in enumerate(self.carpet_players)
        }
        row_indices: list[int] = []
        column_indices: list[int] = []
        values: list[float] = []
        for row_index, row in enumerate(features.rows):
            player_a = row[player_a_column]
            player_b = row[player_b_column]
            for player, sign in ((player_a, 1.0), (player_b, -1.0)):
                column = main_index.get(player)
                if column is not None:
                    row_indices.append(row_index)
                    column_indices.append(column)
                    values.append(sign * scale)
                if row[surface_column] == "Clay":
                    column = clay_index.get(player)
                elif row[surface_column] == "Grass":
                    column = grass_index.get(player)
                elif row[surface_column] == "Carpet":
                    column = carpet_index.get(player)
                elif row[surface_column] == "Hard":
                    column = None
                else:
                    raise NumericalError(f"unsupported surface {row[surface_column]!r}")
                if column is not None:
                    row_indices.append(row_index)
                    column_indices.append(column)
                    values.append(sign * scale)
        return sp.csr_matrix(
            (values, (row_indices, column_indices)),
            shape=(len(features.rows), len(self.feature_names)),
            dtype=np.float64,
        )


def rms_scales(matrix: np.ndarray) -> np.ndarray:
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        raise NumericalError("RMS scaling requires a nonempty two-dimensional fit matrix")
    scales = np.sqrt(np.mean(np.square(matrix), axis=0))
    if not np.all(np.isfinite(scales)):
        raise NumericalError("non-finite RMS scale")
    return np.where(scales == 0.0, 1.0, scales)


def class_one_probabilities(estimator: Any, matrix: Any) -> np.ndarray:
    probabilities = np.asarray(estimator.predict_proba(matrix), dtype=np.float64)
    classes = list(estimator.classes_)
    if 1 not in classes:
        raise NumericalError(f"fitted estimator lacks class 1: {classes}")
    result = probabilities[:, classes.index(1)]
    if not np.all(np.isfinite(result)) or np.any(result < 0.0) or np.any(result > 1.0):
        raise NumericalError("estimator emitted invalid probabilities")
    return result


@dataclass
class FittedProcedure:
    config: dict[str, Any]
    estimator: Any
    rms_scale: np.ndarray | None
    identity_vocabulary: IdentityVocabulary | None
    estimator_feature_names: tuple[str, ...]

    @property
    def family(self) -> str:
        return str(self.config["family"])

    def _logistic_matrix(self, features: FeatureTable) -> Any:
        columns = tuple(self.config["numeric_columns"])
        numeric = features.matrix(columns)
        if self.rms_scale is None or len(self.rms_scale) != numeric.shape[1]:
            raise NumericalError("missing or incompatible fitted RMS scale")
        scaled = numeric / self.rms_scale
        if self.family != "player_deviation_logistic":
            return scaled
        if self.identity_vocabulary is None:
            raise NumericalError("player-deviation fit lacks identity vocabulary")
        identity = self.identity_vocabulary.matrix(
            features,
            self.config.get("player_a_column", "player_a"),
            self.config.get("player_b_column", "player_b"),
            self.config.get("surface_column", "surface"),
            float(self.config["deviation_scale"]),
        )
        return sp.hstack((sp.csr_matrix(scaled), identity), format="csr")

    def _tree_matrices(self, features: FeatureTable) -> tuple[np.ndarray, np.ndarray]:
        signed = features.matrix(tuple(self.config["signed_numeric_columns"]))
        context = features.matrix(tuple(self.config["context_columns"]))
        original = np.hstack((signed, context))
        swapped = np.hstack((-signed, context))
        return original, swapped

    def predict(self, features: FeatureTable) -> Predictions:
        """Emit probabilities without accepting or inspecting evaluation labels."""
        if self.family in LOGISTIC_FAMILIES:
            original = self._logistic_matrix(features)
            swapped = -original
        elif self.family in TREE_FAMILIES:
            original, swapped = self._tree_matrices(features)
        else:
            raise NumericalError(f"unsupported family: {self.family}")
        p_original = class_one_probabilities(self.estimator, original)
        p_swapped = class_one_probabilities(self.estimator, swapped)
        emitted = 0.5 * (p_original + 1.0 - p_swapped)
        if not np.all(np.isfinite(emitted)) or np.any(emitted < 0) or np.any(emitted > 1):
            raise NumericalError("symmetrization emitted invalid probabilities")
        complement_error = float(np.max(np.abs(emitted + (1.0 - emitted) - 1.0)))
        return Predictions(
            keys=features.keys,
            probabilities=emitted,
            source_feature_sha256=features.source_sha256,
            config_id=str(self.config["config_id"]),
            diagnostics={
                "raw_orientation_complement_max_abs_error": float(
                    np.max(np.abs(p_original + p_swapped - 1.0))
                ),
                "emitted_complement_identity_max_abs_error": complement_error,
            },
        )


@dataclass(frozen=True)
class Predictions:
    keys: tuple[tuple[str, str], ...]
    probabilities: np.ndarray
    source_feature_sha256: str
    config_id: str
    diagnostics: dict[str, float]

    def __post_init__(self) -> None:
        if len(self.keys) != len(self.probabilities):
            raise NumericalError("prediction key/value length mismatch")
        if len(set(self.keys)) != len(self.keys):
            raise NumericalError("duplicate prediction keys")

    @property
    def membership_sha256(self) -> str:
        return key_hash(self.keys)

    def write_csv(self, path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("season", "match_id", "p_a_wins"))
            for (season, match_id), probability in zip(self.keys, self.probabilities, strict=True):
                writer.writerow((season, match_id, repr(float(probability))))
        return sha256_file(path)


@dataclass
class FitAttempt:
    status: str
    config_id: str
    fit_seconds: float
    warnings: list[dict[str, str]] = field(default_factory=list)
    error: dict[str, str] | None = None
    fitted: FittedProcedure | BaggedProcedure | None = None
    cache_reused: bool = False
    # TUNE01: the early-stopping and bagging receipt of a bagged fit; None otherwise.
    tuning: dict[str, Any] | None = None


def validate_config(config: dict[str, Any], features: FeatureTable) -> None:
    required = {"config_id", "family", "estimator_params"}
    missing = sorted(required - set(config))
    if missing:
        raise NumericalError(f"config missing required fields: {missing}")
    family = config["family"]
    if family not in ALL_FAMILIES:
        raise NumericalError(f"unsupported family: {family}")
    if family in LOGISTIC_FAMILIES:
        columns = config.get("numeric_columns")
        if not isinstance(columns, list) or not columns:
            raise NumericalError("logistic config requires ordered numeric_columns")
        features.require_columns(columns)
        if config["estimator_params"].get("fit_intercept") is not False:
            raise NumericalError("logistic fit_intercept must be false for antisymmetry")
        if family == "player_deviation_logistic":
            if "deviation_scale" not in config:
                raise NumericalError("player-deviation config missing deviation_scale")
            features.require_columns(
                (
                    config.get("player_a_column", "player_a"),
                    config.get("player_b_column", "player_b"),
                    config.get("surface_column", "surface"),
                )
            )
    else:
        signed = config.get("signed_numeric_columns")
        context = config.get("context_columns")
        if not isinstance(signed, list) or not signed:
            raise NumericalError("tree config requires ordered signed_numeric_columns")
        if not isinstance(context, list) or not context:
            raise NumericalError("tree config requires ordered context_columns")
        features.require_columns((*signed, *context))


def _tree_augmentation(
    signed: np.ndarray,
    context: np.ndarray,
    labels: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows: list[np.ndarray] = []
    y_values: list[int] = []
    weights: list[float] = []
    for signed_row, context_row, label in zip(signed, context, labels, strict=True):
        original = np.concatenate((signed_row, context_row))
        swapped = np.concatenate((-signed_row, context_row))
        pair = [(original, int(label)), (swapped, 1 - int(label))]
        pair.sort(key=lambda item: (tuple(float(value) for value in item[0]), item[1]))
        for vector, target in pair:
            rows.append(vector)
            y_values.append(target)
            weights.append(0.5)
    return (
        np.asarray(rows, dtype=np.float64),
        np.asarray(y_values, dtype=np.int8),
        np.asarray(weights, dtype=np.float64),
    )


def fit_procedure(
    config: dict[str, Any],
    training_features: FeatureTable,
    training_labels: LabelTable,
    *,
    fit_input_observer: Callable[[Any, np.ndarray, np.ndarray | None, tuple[str, ...]], None]
    | None = None,
) -> FitAttempt:
    """Fit from canonical training rows. No evaluation data enter this call.

    A ``ConvergenceWarning`` is a receipt that the fit is invalid: the attempt is
    recorded as failed with the warning, never silently accepted.
    """
    start = time.perf_counter()
    try:
        validate_config(config, training_features)
        labels = training_labels.align_exact(training_features.keys)
        if len(set(labels.tolist())) != 2:
            raise NumericalError("fit labels must contain both binary classes")
        family = str(config["family"])
        identity_vocabulary: IdentityVocabulary | None = None
        scale: np.ndarray | None = None
        feature_names: tuple[str, ...]
        if family in LOGISTIC_FAMILIES:
            numeric_columns = tuple(config["numeric_columns"])
            numeric = training_features.matrix(numeric_columns)
            scale = rms_scales(numeric)
            scaled = numeric / scale
            if family == "player_deviation_logistic":
                identity_vocabulary = IdentityVocabulary.fit(
                    training_features,
                    config.get("player_a_column", "player_a"),
                    config.get("player_b_column", "player_b"),
                    config.get("surface_column", "surface"),
                )
                identity = identity_vocabulary.matrix(
                    training_features,
                    config.get("player_a_column", "player_a"),
                    config.get("player_b_column", "player_b"),
                    config.get("surface_column", "surface"),
                    float(config["deviation_scale"]),
                )
                fit_matrix: Any = sp.hstack((sp.csr_matrix(scaled), identity), format="csr")
                feature_names = numeric_columns + identity_vocabulary.feature_names
            else:
                fit_matrix = scaled
                feature_names = numeric_columns
            estimator: Any = LogisticRegression(**config["estimator_params"])
            sample_weight = None
        else:
            signed_columns = tuple(config["signed_numeric_columns"])
            context_columns = tuple(config["context_columns"])
            signed = training_features.matrix(signed_columns)
            context = training_features.matrix(context_columns)
            fit_matrix, labels, sample_weight = _tree_augmentation(signed, context, labels)
            feature_names = signed_columns + context_columns
            if family == "hist_gradient_boosting":
                estimator = HistGradientBoostingClassifier(**config["estimator_params"])
            else:
                estimator = RandomForestClassifier(**config["estimator_params"])

        if fit_input_observer is not None:
            fit_input_observer(fit_matrix, labels, sample_weight, feature_names)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if sample_weight is None:
                estimator.fit(fit_matrix, labels)
            else:
                estimator.fit(fit_matrix, labels, sample_weight=sample_weight)
        warning_records = [
            {"category": item.category.__name__, "message": str(item.message)} for item in caught
        ]
        convergence = [
            record
            for record, item in zip(warning_records, caught, strict=True)
            if issubclass(item.category, ConvergenceWarning)
        ]
        if convergence:
            return FitAttempt(
                status="failed",
                config_id=str(config["config_id"]),
                fit_seconds=time.perf_counter() - start,
                warnings=warning_records,
                error={
                    "type": "ConvergenceWarning",
                    "message": "convergence warning invalidates this fit",
                },
            )
        fitted = FittedProcedure(
            config=json.loads(json.dumps(config)),
            estimator=estimator,
            rms_scale=scale,
            identity_vocabulary=identity_vocabulary,
            estimator_feature_names=feature_names,
        )
        return FitAttempt(
            status="complete",
            config_id=str(config["config_id"]),
            fit_seconds=time.perf_counter() - start,
            warnings=warning_records,
            fitted=fitted,
        )
    except Exception as error:  # preserve every affected configuration failure
        return FitAttempt(
            status="failed",
            config_id=str(config.get("config_id", "<missing>")),
            fit_seconds=time.perf_counter() - start,
            error={"type": type(error).__name__, "message": str(error)},
        )


def fit_identity(
    config: dict[str, Any],
    fit_cutoff: str,
    training_features: FeatureTable,
    training_labels: LabelTable,
    frozen_manifest_sha256: str,
) -> dict[str, Any]:
    keys = training_features.keys
    return {
        "config_id": str(config["config_id"]),
        "config_sha256": sha256_json(config),
        "fit_cutoff": fit_cutoff,
        "frozen_manifest_sha256": frozen_manifest_sha256,
        "training_feature_sha256": training_features.source_sha256,
        "training_label_sha256": training_labels.source_sha256,
        "training_keys_sha256": key_hash(keys),
        "training_rows": len(keys),
    }


def _write_key_file(path: Path, keys: Sequence[tuple[str, str]]) -> str:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(KEY_COLUMNS)
        writer.writerows(keys)
    return sha256_file(path)


def _read_key_file(path: Path) -> tuple[tuple[str, str], ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise NumericalError("cached training key artifact is empty") from error
        if header != KEY_COLUMNS:
            raise NumericalError("cached training key artifact header drift")
        rows: list[tuple[str, str]] = []
        for row in reader:
            if len(row) != 2 or not all(row):
                raise NumericalError("invalid cached training key row")
            rows.append((row[0], row[1]))
    if len(set(rows)) != len(rows):
        raise NumericalError("duplicate cached training keys")
    return tuple(rows)


def save_fit_attempt(
    directory: Path,
    attempt: FitAttempt,
    identity: dict[str, Any],
    training_keys: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    keys_path = directory / "training_keys.csv"
    keys_file_hash = _write_key_file(keys_path, training_keys)
    metadata: dict[str, Any] = {
        "fit_identity": identity,
        "fit_identity_sha256": sha256_json(identity),
        "status": attempt.status,
        "config_id": attempt.config_id,
        "fit_seconds": attempt.fit_seconds,
        "warnings": attempt.warnings,
        "error": attempt.error,
        "training_keys_path": keys_path.name,
        "training_keys_file_sha256": keys_file_hash,
        # Written only for a bagged fit, so every other fit manifest keeps its shape.
        **({"tuning": attempt.tuning} if attempt.tuning is not None else {}),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
            "threads": {
                "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
                "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
                "MKL_NUM_THREADS": os.environ.get("MKL_NUM_THREADS"),
            },
        },
    }
    if attempt.status == "complete":
        if attempt.fitted is None:
            raise NumericalError("complete fit lacks fitted procedure")
        model_path = directory / "model.joblib"
        joblib.dump(attempt.fitted, model_path, compress=0)
        if isinstance(attempt.fitted, BaggedProcedure):
            members = attempt.fitted.members
            metadata.update(
                {
                    "model_path": model_path.name,
                    "model_sha256": sha256_file(model_path),
                    "rms_scales": None,
                    "estimator_feature_names": list(members[0].estimator_feature_names),
                    "identity_vocabulary": None,
                    "bag_members": len(members),
                    "member_estimator_get_params": [
                        json_safe(member.estimator.get_params(deep=True)) for member in members
                    ],
                }
            )
        else:
            metadata.update(
                {
                    "model_path": model_path.name,
                    "model_sha256": sha256_file(model_path),
                    "rms_scales": (
                        attempt.fitted.rms_scale.tolist()
                        if attempt.fitted.rms_scale is not None
                        else None
                    ),
                    "estimator_feature_names": list(attempt.fitted.estimator_feature_names),
                    "identity_vocabulary": (
                        json_safe(attempt.fitted.identity_vocabulary.__dict__)
                        if attempt.fitted.identity_vocabulary is not None
                        else None
                    ),
                    "estimator_get_params": json_safe(
                        attempt.fitted.estimator.get_params(deep=True)
                    ),
                }
            )
    metadata_path = directory / "fit_manifest.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    metadata["fit_manifest_file_sha256"] = sha256_file(metadata_path)
    return metadata


class FileFitCache:
    """Exact-identity cache; no fuzzy reuse by config name or cutoff alone."""

    def __init__(self, root: Path):
        self.root = root

    def fit_or_load(
        self,
        identity: dict[str, Any],
        training_keys: Sequence[tuple[str, str]],
        fit_callable: Callable[[], FitAttempt],
    ) -> tuple[FitAttempt, dict[str, Any]]:
        identity_hash = sha256_json(identity)
        directory = self.root / identity_hash
        manifest_path = directory / "fit_manifest.json"
        if manifest_path.exists():
            metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
            metadata["fit_manifest_file_sha256"] = sha256_file(manifest_path)
            if metadata.get("fit_identity") != identity:
                raise NumericalError("fit cache identity collision")
            keys_path = directory / metadata["training_keys_path"]
            if sha256_file(keys_path) != metadata["training_keys_file_sha256"]:
                raise NumericalError("cached training key artifact drift")
            cached_keys = _read_key_file(keys_path)
            if cached_keys != tuple(training_keys):
                raise NumericalError("cached training keys differ from requested keys")
            if metadata["status"] == "complete":
                model_path = directory / metadata["model_path"]
                if sha256_file(model_path) != metadata["model_sha256"]:
                    raise NumericalError("cached model artifact drift")
                fitted = joblib.load(model_path)
            else:
                fitted = None
            return (
                FitAttempt(
                    status=metadata["status"],
                    config_id=metadata["config_id"],
                    fit_seconds=metadata["fit_seconds"],
                    warnings=metadata["warnings"],
                    error=metadata["error"],
                    fitted=fitted,
                    cache_reused=True,
                    tuning=metadata.get("tuning"),
                ),
                metadata,
            )
        attempt = fit_callable()
        metadata = save_fit_attempt(directory, attempt, identity, training_keys)
        return attempt, metadata


# ------------------------------------------------------------------ TUNE01: bagged trees
#
# A tree candidate that is temporally early-stopped and row-subsample bagged
# (``references/TUNE01/menu.json``, analysis_spec §2).  For raw year R the pipeline hands
# over the training window's canonical keys split into the stopping-train keys (dated up
# to (R-2)-12-30) and the stopping-validation keys (the window's last year, R-1); the
# adapter never sees a date.  Five stopping members are fitted with the capped iteration
# count on role-0 subsamples of the stopping-train keys; the bag-averaged,
# swap-symmetrised validation log loss after each iteration is the curve; the patience
# rule picks the best iteration k*; five members are then refitted on role-1 subsamples
# of the whole window with ``max_iter = k*`` and their symmetrised probabilities are
# averaged.  Subsamples depend on the raw year, the role and the member only, never on the
# candidate.  The curve is a set of scores of an earlier fold's target year: only its
# sha256 leaves this module (RB14); the stopping members are never persisted.

CURVE_SCORE_CLIP = 1e-15
BAGGING_ROLES = {"stopping": 0, "refit": 1}
TUNING_KIND = "bagged_temporal_early_stopping"
TUNING_KEYS = frozenset(
    {
        "kind",
        "menu_sha256",
        "max_iter_cap",
        "patience",
        "tol",
        "members",
        "row_subsample_fraction",
        "base_seed",
    }
)


def _tuning_spec(config: dict[str, Any]) -> dict[str, Any]:
    tuning = config.get("tuning")
    if not isinstance(tuning, dict) or set(tuning) != TUNING_KEYS:
        raise NumericalError(
            f"bagged tree config needs exactly the tuning keys {sorted(TUNING_KEYS)}"
        )
    if tuning["kind"] != TUNING_KIND:
        raise NumericalError(f"unknown tuning kind: {tuning['kind']!r}")
    if config.get("family") != "hist_gradient_boosting":
        raise NumericalError("bagged early stopping is defined for hist_gradient_boosting only")
    for name in ("max_iter_cap", "patience", "members", "base_seed"):
        if not isinstance(tuning[name], int) or isinstance(tuning[name], bool) or tuning[name] < 1:
            raise NumericalError(f"tuning {name} must be a positive integer")
    if tuning["patience"] >= tuning["max_iter_cap"]:
        raise NumericalError("tuning patience must be below the iteration cap")
    fraction = tuning["row_subsample_fraction"]
    if not isinstance(fraction, float) or not 0.0 < fraction <= 1.0:
        raise NumericalError("tuning row_subsample_fraction must be a float in (0, 1]")
    if (
        not isinstance(tuning["tol"], float)
        or not math.isfinite(tuning["tol"])
        or tuning["tol"] < 0
    ):
        raise NumericalError("tuning tol must be a finite nonnegative float")
    params = config.get("estimator_params", {})
    if params.get("early_stopping") is not False:
        raise NumericalError("scikit-learn's internal early stopping must be off")
    return tuning


def bag_seed(base_seed: int, raw_year: int, role: int, member: int) -> list[int]:
    """The SeedSequence entropy of one bag member: ``[base, raw year, role, member]``."""
    return [int(base_seed), int(raw_year), int(role), int(member)]


def subsample_positions(n: int, seed: Sequence[int], fraction: float) -> np.ndarray:
    """``floor(fraction * n)`` distinct positions of a canonically sorted key tuple.

    ``Generator(PCG64(SeedSequence(seed))).choice(n, size, replace=False)``, sorted
    ascending, exactly as ``menu.json`` declares.
    """
    size = math.floor(fraction * n)
    if n < 1 or size < 1:
        raise NumericalError(f"cannot subsample {fraction} of {n} keys")
    generator = np.random.Generator(np.random.PCG64(np.random.SeedSequence(list(seed))))
    return np.sort(generator.choice(n, size=size, replace=False))


def early_stopping_decision(curve: Sequence[float], patience: int, tol: float) -> dict[str, Any]:
    """The patience rule on a validation curve L(1..K) (1-based iterations).

    ``k_stop`` is the smallest k > patience at which no iteration in the last ``patience``
    improved on the best value up to k - patience by more than ``tol``; ``k_star`` is the
    first minimiser of L over 1..k_stop.  When the rule never fires ``k_star`` is the first
    minimiser over the whole curve and the status is ``cap`` (``k_stop`` is then None).
    """
    values = [float(value) for value in curve]
    if not values or any(not math.isfinite(value) for value in values):
        raise NumericalError("early-stopping curve must be nonempty and finite")
    if patience < 1:
        raise NumericalError("patience must be positive")
    prefix_minimum: list[float] = []
    running = math.inf
    for value in values:
        running = min(running, value)
        prefix_minimum.append(running)
    k_stop: int | None = None
    for k in range(patience + 1, len(values) + 1):
        recent = min(values[k - patience : k])  # L(k - patience + 1) .. L(k)
        earlier = prefix_minimum[k - patience - 1]  # min L(1) .. L(k - patience)
        if recent > earlier - tol:
            k_stop = k
            break
    horizon = values if k_stop is None else values[:k_stop]
    k_star = horizon.index(min(horizon)) + 1
    return {
        "k_star": k_star,
        "k_stop": k_stop,
        "stop_status": "cap" if k_stop is None else "patience",
    }


def _fit_estimator(
    estimator: Any, matrix: np.ndarray, labels: np.ndarray, weights: np.ndarray
) -> tuple[list[dict[str, str]], bool]:
    """Fit in place; return the warning records and whether a ConvergenceWarning fired."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        estimator.fit(matrix, labels, sample_weight=weights)
    records = [
        {"category": item.category.__name__, "message": str(item.message)} for item in caught
    ]
    return records, any(issubclass(item.category, ConvergenceWarning) for item in caught)


def _max_tree_depth(estimator: Any) -> int:
    return max(
        int(predictor.get_max_depth())
        for iteration in estimator._predictors
        for predictor in iteration
    )


@dataclass(frozen=True)
class BaggedTreeInputs:
    """One raw year's rows for the bagged tree family, shared by every candidate.

    Rows ``2i`` and ``2i + 1`` of the augmented arrays are window match ``i`` (canonical
    key order) in both orientations, exactly as ``_tree_augmentation`` emits them, so a
    subsample's rows are the augmentation of the subsampled matches: a drawn match enters
    in both orientations at weight 0.5, an undrawn one in neither.
    """

    raw_year: int
    signed_columns: tuple[str, ...]
    context_columns: tuple[str, ...]
    fit_matrix: np.ndarray
    fit_labels: np.ndarray
    fit_weights: np.ndarray
    validation_original: np.ndarray
    validation_swapped: np.ndarray
    validation_labels: np.ndarray
    subsamples: dict[tuple[int, int], np.ndarray]
    receipt: dict[str, Any]

    def rows(self, role: int, member: int) -> np.ndarray:
        positions = self.subsamples[(role, member)]
        return np.column_stack((2 * positions, 2 * positions + 1)).reshape(-1)


def prepare_bagged_tree_inputs(
    config: dict[str, Any],
    training_features: FeatureTable,
    training_labels: LabelTable,
    *,
    stopping_train_keys: Sequence[tuple[str, str]],
    stopping_validation_keys: Sequence[tuple[str, str]],
    raw_year: int,
) -> BaggedTreeInputs:
    """Augment the window once and draw the role-0 and role-1 subsamples of raw year R."""
    validate_config(config, training_features)
    tuning = _tuning_spec(config)
    keys = training_features.keys
    labels = training_labels.align_exact(keys)
    position = {key: index for index, key in enumerate(keys)}
    train_set, validation_set = set(stopping_train_keys), set(stopping_validation_keys)
    if len(train_set) != len(stopping_train_keys) or len(validation_set) != len(
        stopping_validation_keys
    ):
        raise NumericalError("duplicate stopping keys")
    if not train_set or not validation_set:
        raise NumericalError("both stopping sets must be nonempty")
    if train_set & validation_set:
        raise NumericalError("stopping-train and stopping-validation keys overlap")
    outside = sorted((train_set | validation_set) - set(position))
    if outside:
        raise NumericalError(f"stopping keys outside the training window: {outside[:5]}")
    train_positions = np.asarray(sorted(position[key] for key in train_set), dtype=np.intp)
    validation_positions = np.asarray(
        sorted(position[key] for key in validation_set), dtype=np.intp
    )
    signed_columns = tuple(config["signed_numeric_columns"])
    context_columns = tuple(config["context_columns"])
    signed = training_features.matrix(signed_columns)
    context = training_features.matrix(context_columns)
    fit_matrix, fit_labels, fit_weights = _tree_augmentation(signed, context, labels)
    validation_signed = signed[validation_positions]
    validation_context = context[validation_positions]
    members = int(tuning["members"])
    fraction = float(tuning["row_subsample_fraction"])
    subsamples: dict[tuple[int, int], np.ndarray] = {}
    records: dict[str, list[dict[str, Any]]] = {}
    for role_name, role in BAGGING_ROLES.items():
        pool = train_positions if role == BAGGING_ROLES["stopping"] else np.arange(len(keys))
        records[role_name] = []
        for member in range(members):
            seed = bag_seed(tuning["base_seed"], raw_year, role, member)
            drawn = pool[subsample_positions(len(pool), seed, fraction)]
            subsamples[(role, member)] = drawn
            records[role_name].append(
                {
                    "member": member,
                    "seed_sequence": seed,
                    "keys": len(drawn),
                    "keys_sha256": key_hash([keys[index] for index in drawn]),
                }
            )
    receipt = {
        "raw_year": int(raw_year),
        "window_keys": len(keys),
        "window_keys_sha256": key_hash(keys),
        "stopping_train_keys": len(train_positions),
        "stopping_train_keys_sha256": key_hash([keys[index] for index in train_positions]),
        "stopping_validation_keys": len(validation_positions),
        "stopping_validation_keys_sha256": key_hash(
            [keys[index] for index in validation_positions]
        ),
        "keys_in_neither_stopping_set": len(keys)
        - len(train_positions)
        - len(validation_positions),
        "subsamples": records,
    }
    return BaggedTreeInputs(
        raw_year=int(raw_year),
        signed_columns=signed_columns,
        context_columns=context_columns,
        fit_matrix=fit_matrix,
        fit_labels=fit_labels,
        fit_weights=fit_weights,
        validation_original=np.hstack((validation_signed, validation_context)),
        validation_swapped=np.hstack((-validation_signed, validation_context)),
        validation_labels=labels[validation_positions].astype(np.float64),
        subsamples=subsamples,
        receipt=receipt,
    )


def bagged_validation_curve(
    estimators: Sequence[Any], original: np.ndarray, swapped: np.ndarray, labels: np.ndarray
) -> list[float]:
    """L(k) for every iteration k: the match-weighted mean log loss (clip 1e-15) of the
    member-averaged symmetrised probability 0.5 * (p(a, b) + 1 - p(b, a)).  Members are
    summed in member order and divided by their count, as ``BaggedProcedure`` averages."""
    streams = []
    for estimator in estimators:
        classes = list(estimator.classes_)
        if 1 not in classes:
            raise NumericalError(f"fitted estimator lacks class 1: {classes}")
        streams.append(
            (
                estimator.staged_predict_proba(original),
                estimator.staged_predict_proba(swapped),
                classes.index(1),
            )
        )
    curve: list[float] = []
    positive = labels == 1.0
    while True:
        total: np.ndarray | None = None
        exhausted = 0
        for stream_original, stream_swapped, column in streams:
            p_original = next(stream_original, None)
            p_swapped = next(stream_swapped, None)
            if p_original is None or p_swapped is None:
                exhausted += 1
                continue
            member = 0.5 * (p_original[:, column] + 1.0 - p_swapped[:, column])
            total = member if total is None else total + member
        if exhausted:
            if exhausted != len(streams):
                raise NumericalError("bag members have different iteration counts")
            break
        assert total is not None
        mean = np.clip(total / len(streams), CURVE_SCORE_CLIP, 1.0 - CURVE_SCORE_CLIP)
        losses = -np.log(np.where(positive, mean, 1.0 - mean))
        value = float(np.mean(losses))
        if not math.isfinite(value):
            raise NumericalError("nonfinite validation curve value")
        curve.append(value)
    return curve


@dataclass
class BaggedProcedure:
    """Members averaged in probability: each member's swap-symmetrised forecast is summed
    in member order and divided by the member count."""

    config: dict[str, Any]
    members: tuple[FittedProcedure, ...]

    @property
    def family(self) -> str:
        return str(self.config["family"])

    def predict(self, features: FeatureTable) -> Predictions:
        """Emit probabilities without accepting or inspecting evaluation labels."""
        if not self.members:
            raise NumericalError("a bagged procedure needs at least one member")
        outputs = [member.predict(features) for member in self.members]
        total = outputs[0].probabilities.copy()
        for output in outputs[1:]:
            total = total + output.probabilities
        emitted = total / len(outputs)
        if not np.all(np.isfinite(emitted)) or np.any(emitted < 0) or np.any(emitted > 1):
            raise NumericalError("bag averaging emitted invalid probabilities")
        return Predictions(
            keys=features.keys,
            probabilities=emitted,
            source_feature_sha256=features.source_sha256,
            config_id=str(self.config["config_id"]),
            diagnostics={
                "raw_orientation_complement_max_abs_error": max(
                    output.diagnostics["raw_orientation_complement_max_abs_error"]
                    for output in outputs
                ),
                "emitted_complement_identity_max_abs_error": float(
                    np.max(np.abs(emitted + (1.0 - emitted) - 1.0))
                ),
            },
        )


def _base_params(config: dict[str, Any], inputs: BaggedTreeInputs) -> dict[str, Any]:
    if (
        tuple(config["signed_numeric_columns"]) != inputs.signed_columns
        or tuple(config["context_columns"]) != inputs.context_columns
    ):
        raise NumericalError("bagged inputs were built for different model columns")
    return {key: value for key, value in config["estimator_params"].items() if key != "max_iter"}


def _fit_bag_member(
    base_params: dict[str, Any],
    inputs: BaggedTreeInputs,
    role: int,
    member: int,
    max_iter: int,
    warning_records: list[dict[str, str]],
) -> Any:
    rows = inputs.rows(role, member)
    estimator = HistGradientBoostingClassifier(**base_params, max_iter=max_iter)
    records, convergence = _fit_estimator(
        estimator, inputs.fit_matrix[rows], inputs.fit_labels[rows], inputs.fit_weights[rows]
    )
    warning_records.extend(records)
    if convergence:
        raise _BagConvergenceError(role, member)
    if int(estimator.n_iter_) != max_iter:
        raise NumericalError(
            f"member {role}/{member} ran {estimator.n_iter_} of {max_iter} iterations"
        )
    return estimator


def bagged_stopping_curve(
    config: dict[str, Any],
    inputs: BaggedTreeInputs,
    warning_records: list[dict[str, str]] | None = None,
) -> tuple[list[float], list[int]]:
    """Fit the stopping members (capped iterations, role-0 subsamples) and return the
    validation curve with each member's realised depth.  The members are discarded."""
    tuning = _tuning_spec(config)
    base_params = _base_params(config, inputs)
    records = [] if warning_records is None else warning_records
    stopping = [
        _fit_bag_member(
            base_params,
            inputs,
            BAGGING_ROLES["stopping"],
            member,
            int(tuning["max_iter_cap"]),
            records,
        )
        for member in range(int(tuning["members"]))
    ]
    curve = bagged_validation_curve(
        stopping, inputs.validation_original, inputs.validation_swapped, inputs.validation_labels
    )
    return curve, [_max_tree_depth(estimator) for estimator in stopping]


def fit_bagged_early_stopped(config: dict[str, Any], inputs: BaggedTreeInputs) -> FitAttempt:
    """Stopping fits, curve, patience rule and refits for one candidate and raw year.

    Every member is fitted from ``inputs``; the fit never sees a row outside the training
    window.  A ConvergenceWarning in any member fails the attempt with its receipt.
    """
    start = time.perf_counter()
    config_id = str(config.get("config_id", "<missing>"))
    warning_records: list[dict[str, str]] = []
    try:
        tuning = _tuning_spec(config)
        base_params = _base_params(config, inputs)
        members = int(tuning["members"])
        cap = int(tuning["max_iter_cap"])
        curve, stopping_depths = bagged_stopping_curve(config, inputs, warning_records)
        decision = early_stopping_decision(curve, int(tuning["patience"]), float(tuning["tol"]))
        k_star = int(decision["k_star"])
        feature_names = inputs.signed_columns + inputs.context_columns
        member_base = {key: value for key, value in config.items() if key != "tuning"}
        refits: list[FittedProcedure] = []
        for member in range(members):
            estimator = _fit_bag_member(
                base_params, inputs, BAGGING_ROLES["refit"], member, k_star, warning_records
            )
            member_config = {
                **member_base,
                "config_id": f"{config_id}::refit{member}",
                "estimator_params": {**base_params, "max_iter": k_star},
            }
            refits.append(
                FittedProcedure(
                    config=json.loads(json.dumps(member_config)),
                    estimator=estimator,
                    rms_scale=None,
                    identity_vocabulary=None,
                    estimator_feature_names=feature_names,
                )
            )
        receipt = {
            **decision,
            "max_iter_cap": cap,
            "patience": int(tuning["patience"]),
            "tol": float(tuning["tol"]),
            "curve_points": len(curve),
            "curve_sha256": sha256_json(curve),
            "stopping_member_max_depth": stopping_depths,
            "refit_member_n_iter": [int(item.estimator.n_iter_) for item in refits],
            "refit_member_max_depth": [_max_tree_depth(item.estimator) for item in refits],
            "menu_sha256": tuning["menu_sha256"],
            **inputs.receipt,
        }
        return FitAttempt(
            status="complete",
            config_id=config_id,
            fit_seconds=time.perf_counter() - start,
            warnings=warning_records,
            fitted=BaggedProcedure(config=json.loads(json.dumps(config)), members=tuple(refits)),
            tuning=receipt,
        )
    except _BagConvergenceError as error:
        return FitAttempt(
            status="failed",
            config_id=config_id,
            fit_seconds=time.perf_counter() - start,
            warnings=warning_records,
            error={
                "type": "ConvergenceWarning",
                "message": f"convergence warning invalidates this fit (member {error})",
            },
        )
    except Exception as error:  # preserve every affected configuration failure
        return FitAttempt(
            status="failed",
            config_id=config_id,
            fit_seconds=time.perf_counter() - start,
            error={"type": type(error).__name__, "message": str(error)},
        )


class _BagConvergenceError(Exception):
    def __init__(self, role: int, member: int):
        super().__init__(f"{role}/{member}")


def fit_cached_and_predict(
    cache: FileFitCache,
    identity: dict[str, Any],
    training_keys: Sequence[tuple[str, str]],
    fit_callable: Callable[[], FitAttempt],
    prediction_features: FeatureTable,
    prediction_path: Path,
) -> dict[str, Any]:
    """Fit (or load the exact identity), then write the unscored forecasts.

    Returns the attempt's receipt fields for the raw ledger; the fit wall clock covers
    the fit or cache load only.
    """
    started = time.monotonic()
    attempt, fit_manifest = cache.fit_or_load(identity, training_keys, fit_callable)
    result: dict[str, Any] = {
        "fit_wall_clock_seconds": round(time.monotonic() - started, 6),
        "status": attempt.status,
        "fit_cache_reused": attempt.cache_reused,
        "fit_manifest_sha256": fit_manifest["fit_manifest_file_sha256"],
        "warnings": attempt.warnings,
        "error": attempt.error,
    }
    if attempt.tuning is not None:
        result["tuning"] = attempt.tuning
    if attempt.status == "complete" and attempt.fitted is not None:
        try:
            emitted = attempt.fitted.predict(prediction_features)
            if emitted.keys != prediction_features.keys:
                raise NumericalError("numerical prediction membership drift")
            result.update(
                {
                    "prediction_sha256": emitted.write_csv(prediction_path),
                    "prediction_rows": len(emitted.keys),
                    "prediction_membership_sha256": emitted.membership_sha256,
                    "prediction_diagnostics": emitted.diagnostics,
                }
            )
        except Exception as error:
            result["status"] = "failed_prediction"
            result["error"] = {"type": type(error).__name__, "message": str(error)}
    return result


# One raw year's shared rows in a worker process (set by `init_bagged_worker`).
_WORKER_SHARED: dict[str, Any] = {}


def init_bagged_worker(shared: dict[str, Any]) -> None:
    """Initializer of a raw-stage worker process: install the year's shared rows and hand
    the access log to the stage's own process (RB14)."""
    from tennislab.chain import access

    access.detach()
    _WORKER_SHARED.clear()
    _WORKER_SHARED.update(shared)


def execute_bagged_task(task: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    """One bagged candidate for one raw year, from the year's shared rows."""
    inputs = shared["inputs"][task["block"]]
    return fit_cached_and_predict(
        FileFitCache(Path(shared["cache_root"])),
        task["identity"],
        shared["training_keys"],
        lambda: fit_bagged_early_stopped(task["config"], inputs),
        shared["prediction_features"],
        Path(task["prediction_path"]),
    )


def run_bagged_task(task: dict[str, Any]) -> dict[str, Any]:
    """Worker entry point: the task's receipt plus the files this process opened."""
    from tennislab.chain import access

    result = execute_bagged_task(task, _WORKER_SHARED)
    result["access"] = access.drain()
    return result
