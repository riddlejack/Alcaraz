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
    fitted: FittedProcedure | None = None
    cache_reused: bool = False


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
                "estimator_get_params": json_safe(attempt.fitted.estimator.get_params(deep=True)),
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
                ),
                metadata,
            )
        attempt = fit_callable()
        metadata = save_fit_attempt(directory, attempt, identity, training_keys)
        return attempt, metadata
