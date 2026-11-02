"""The all-tier model: gradient boosting on the all-tier table, three training windows.

For a target season Y and a window of k seasons, the training rows are the table's
completed or retired rows of the training tiers (tour, qualifying and Challenger: Futures
rows are history, never examples) dated from Jan 1 of Y - k to Dec 30 of Y - 1. Each
candidate of the menu is fitted swap-augmented (every row once as is and once with a/b
swapped, signed features negated and the label flipped, each at half weight) and predicts
swap-symmetrised: p = (p(x) + 1 - p(swapped x)) / 2.

The targets are the previous version's: its aligned primary rows of season Y, joined to
the table on the match id. Selection is the previous version's procedure, past-only: for
target season Y each window's candidates are scored on the previous three seasons' target
rows dated up to Dec 30 of Y - 1 by fitting one no-intercept slope on their raw
forecasts (:func:`tennislab.models.pipeline.fit_nonnegative_slope`); the best calibrated
candidate wins (:func:`~tennislab.models.pipeline.select_calibrated_candidate`), and its
slope is applied to its raw Y forecasts. A selection row without an all-tier row has no
raw forecast and is left out of the slope fit.

:mod:`tennislab.alltier.pool` averages the three windows' log-odds into the all-tier
forecast and pools it with the previous version.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.chain.common import ChainError, sha256
from tennislab.models import pipeline


class AllTierModelError(ChainError):
    """Fail-closed configuration, membership or join error in the all-tier model."""


Key = tuple[str, str]

# ------------------------------------------------------------------ the previous run


def is_aligned_primary_label(row: Mapping[str, str]) -> bool:
    """The pipeline's aligned-primary rule on a labels row of a forecast row.

    A forecast exists only for rows with the dynamic block, so for a row of a prediction
    file this equals :func:`tennislab.models.pipeline.is_aligned_primary` under the
    ``aligned_primary`` cohort.
    """
    year = row["calendar_year"]
    return (
        row["primary_target"] == "1"
        and row["identity_tier"] == "primary"
        and row["source_season"] == year
        and pipeline.parse_iso(row["match_date"]).year == int(year)
    )


@dataclass
class PreviousRun:
    """The completed run of the previous version: its labels, memberships and forecasts."""

    root: Path
    learner: str
    bundle: str

    def __post_init__(self) -> None:
        self.read: dict[str, str] = {}
        self._labels: dict[Key, dict[str, str]] | None = None
        self._targets: dict[int, tuple[Key, ...]] = {}

    def _record(self, path: Path) -> Path:
        if not path.is_file():
            raise AllTierModelError(f"previous run lacks {path}")
        self.read[path.relative_to(self.root).as_posix()] = sha256(path)
        return path

    def labels(self) -> dict[Key, dict[str, str]]:
        if self._labels is None:
            path = self._record(self.root / "features" / "labels.csv")
            with path.open(newline="", encoding="utf-8") as handle:
                self._labels = {
                    (r["calendar_year"], r["match_id"]): r for r in csv.DictReader(handle)
                }
        return self._labels

    def selected_path(self, year: int) -> Path:
        return self.root / "pipeline" / "selected" / str(year) / self.learner / f"{self.bundle}.csv"

    def prediction_file(self, year: int) -> Path:
        """The selected file of ``year``, or else its first raw candidate file."""
        selected = self.selected_path(year)
        if selected.is_file():
            return selected
        folder = self.root / "pipeline" / "raw" / str(year) / self.learner / self.bundle
        files = sorted(folder.glob("*.csv")) if folder.is_dir() else []
        if not files:
            raise AllTierModelError(f"previous run has no {self.bundle} forecasts for {year}")
        return files[0]

    def targets(self, year: int) -> tuple[Key, ...]:
        """The aligned primary rows of ``year``, sorted by (season, match id)."""
        if year not in self._targets:
            labels = self.labels()
            path = self._record(self.prediction_file(year))
            keys = pipeline.prediction_map(path)
            self._targets[year] = tuple(
                sorted(k for k in keys if k in labels and is_aligned_primary_label(labels[k]))
            )
            if not self._targets[year]:
                raise AllTierModelError(f"no aligned primary targets in {year}")
        return self._targets[year]

    def selection(self, outer: int, years_back: int) -> dict[int, tuple[Key, ...]]:
        """Each past season's targets dated up to Dec 30 of ``outer - 1``.

        When the previous run recorded its own selection membership for ``outer``, the
        two must agree.
        """
        cutoff = dt.date(outer - 1, 12, 30)
        labels = self.labels()
        out = {
            year: tuple(
                k
                for k in self.targets(year)
                if pipeline.parse_iso(labels[k]["match_date"]) <= cutoff
            )
            for year in range(outer - years_back, outer)
        }
        recorded = self.root / "pipeline" / "selection" / str(outer) / pipeline.SELECTION_KEYS_FILE
        if recorded.is_file():
            self._record(recorded)
            if pipeline.read_selection_keys(recorded) != tuple(k for v in out.values() for k in v):
                raise AllTierModelError(f"selection membership for {outer} differs from the run's")
        return out

    def outcomes(self, keys: Iterable[Key]) -> np.ndarray:
        labels = self.labels()
        values = []
        for key in keys:
            text = labels[key]["a_won"]
            if text not in ("0", "1"):
                raise AllTierModelError(f"no outcome for selection row {key}")
            values.append(int(text))
        return np.array(values, dtype=np.int64)

    def forecasts(self, year: int) -> np.ndarray:
        """The previous version's selected forecasts on the targets of ``year``."""
        saved = pipeline.prediction_map(self._record(self.selected_path(year)))
        return np.array([saved[k] for k in self.targets(year)], dtype=float)


# ------------------------------------------------------------------ the table


class TableView:
    """The numeric table the model reads (``table.npz``)."""

    def __init__(self, path: Path):
        with np.load(path, allow_pickle=False) as z:
            self.signed = z["signed"]
            self.context = z["context"]
            targets = z["targets"]
            columns = list(z["target_cols"])
            self.tier = z["tier"]
            self.date = z["date"].astype("datetime64[D]")
            match_ids = z["lab_match_id"]
        self.y = targets[:, columns.index("a_won")]
        self.trainable = (targets[:, columns.index("is_completed")] == 1) | (
            targets[:, columns.index("is_retired")] == 1
        )
        self.row_of = {m: i for i, m in enumerate(match_ids) if m}

    def window_rows(self, year: int, years: int, tiers: Sequence[str]) -> np.ndarray:
        start = np.datetime64(dt.date(year - years, 1, 1))
        end = np.datetime64(dt.date(year - 1, 12, 30))
        mask = (
            self.trainable
            & (self.date >= start)
            & (self.date <= end)
            & np.isin(self.tier, list(tiers))
            & ~np.isnan(self.y)
        )
        return np.flatnonzero(mask)

    def rows_of(self, keys: Sequence[Key]) -> np.ndarray:
        """Table rows of the target keys, -1 where the table has no row."""
        return np.array([self.row_of.get(k[1], -1) for k in keys], dtype=np.int64)


def fit_symmetric(
    signed_train: np.ndarray,
    context_train: np.ndarray,
    y_train: np.ndarray,
    weight_train: np.ndarray,
    signed_test: np.ndarray,
    context_test: np.ndarray,
    params: Mapping[str, Any],
) -> np.ndarray:
    """Swap-augmented fit at half weight, swap-symmetrised prediction."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    X = np.vstack(
        (np.hstack((signed_train, context_train)), np.hstack((-signed_train, context_train)))
    )
    Y = np.concatenate((y_train, 1 - y_train)).astype(int)
    weights = 0.5 * np.concatenate((weight_train, weight_train))
    model = HistGradientBoostingClassifier(**params).fit(X, Y, sample_weight=weights)
    p1 = model.predict_proba(np.hstack((signed_test, context_test)))[:, 1]
    p2 = model.predict_proba(np.hstack((-signed_test, context_test)))[:, 1]
    return 0.5 * (p1 + 1 - p2)


# ------------------------------------------------------------------ settings


@dataclass(frozen=True)
class ModelSettings:
    windows: tuple[int, ...]
    training_tiers: tuple[str, ...]
    candidates: dict[str, dict[str, Any]]
    selection_years_back: int

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> ModelSettings:
        base = dict(section["base_params"])
        menu = section["candidates"]
        if not isinstance(menu, list) or not menu:
            raise AllTierModelError("candidates must be a nonempty ordered list")
        candidates: dict[str, dict[str, Any]] = {}
        for entry in menu:
            if entry["id"] in candidates:
                raise AllTierModelError(f"duplicate candidate {entry['id']}")
            candidates[entry["id"]] = {**base, **entry["params"]}
        windows = tuple(int(k) for k in section["windows"])
        if len(set(windows)) != len(windows) or min(windows) < 1:
            raise AllTierModelError("windows must be distinct positive season counts")
        return cls(
            windows=windows,
            training_tiers=tuple(section["training_tiers"]),
            candidates=candidates,
            selection_years_back=int(section["selection_years_back"]),
        )

    def raw_years(self, target_years: Sequence[int]) -> list[int]:
        back = self.selection_years_back
        return sorted({y for t in target_years for y in range(t - back, t + 1)})


# ------------------------------------------------------------------ raw fits

_TABLE: TableView | None = None


def _worker_init(table_path: str) -> None:
    global _TABLE
    _TABLE = TableView(Path(table_path))


def fit_raw(
    table: TableView,
    keys: Sequence[Key],
    year: int,
    window: int,
    params: Mapping[str, Any],
    tiers: Sequence[str],
) -> np.ndarray:
    """Raw forecasts on ``keys`` (NaN where the table has no row)."""
    train = table.window_rows(year, window, tiers)
    if len(train) == 0:
        raise AllTierModelError(f"empty training window: {year}, {window} seasons")
    test = table.rows_of(keys)
    found = test >= 0
    signed, context = table.signed[train], table.context[train]
    signed_test, context_test = table.signed[test[found]], table.context[test[found]]
    # A column with no value in the training rows carries nothing and cannot be binned; it
    # is left out of that fit (on the ATP table no window has one).
    keep_signed = ~np.isnan(signed).all(axis=0)
    keep_context = ~np.isnan(context).all(axis=0)
    if not keep_signed.all() or not keep_context.all():
        signed, signed_test = signed[:, keep_signed], signed_test[:, keep_signed]
        context, context_test = context[:, keep_context], context_test[:, keep_context]
    out = np.full(len(test), np.nan)
    out[found] = fit_symmetric(
        signed, context, table.y[train], np.ones(len(train)), signed_test, context_test, params
    )
    return out


def _fit_task(task: tuple) -> tuple[int, int, str, np.ndarray]:
    keys, year, window, candidate, params, tiers = task
    assert _TABLE is not None
    return year, window, candidate, fit_raw(_TABLE, keys, year, window, params, tiers)


def raw_path(output_dir: Path, year: int, window: int, candidate: str) -> Path:
    return output_dir / "raw" / str(year) / f"window{window:02d}" / f"{candidate}.csv"


def write_forecasts(path: Path, keys: Sequence[Key], values: np.ndarray) -> str:
    """``season,match_id,p_a_wins`` rows (``repr`` floats); NaN rows are left out."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("season", "match_id", "p_a_wins"))
        for key, value in zip(keys, values, strict=True):
            if np.isfinite(value):
                writer.writerow((*key, repr(float(value))))
    temporary.replace(path)
    return sha256(path)


def read_forecasts(path: Path, keys: Sequence[Key]) -> np.ndarray:
    """Forecasts on ``keys`` from a file of :func:`write_forecasts` (NaN when absent)."""
    saved = pipeline.prediction_map(path)
    unknown = set(saved) - set(keys)
    if unknown:
        raise AllTierModelError(f"{path} carries rows outside the targets: {sorted(unknown)[:3]}")
    return np.array([saved.get(k, np.nan) for k in keys], dtype=float)


def run_raw_fits(
    table_path: Path,
    previous: PreviousRun,
    settings: ModelSettings,
    years: Sequence[int],
    output_dir: Path,
    workers: int,
) -> dict[str, str]:
    """Fit every (year, window, candidate) whose raw file is not yet written."""
    todo = []
    for year in years:
        keys = previous.targets(year)
        for window in settings.windows:
            for candidate, params in settings.candidates.items():
                if not raw_path(output_dir, year, window, candidate).is_file():
                    todo.append((keys, year, window, candidate, params, settings.training_tiers))
    if todo:
        if workers > 1:
            import multiprocessing
            from concurrent.futures import ProcessPoolExecutor

            os.environ.setdefault("OMP_NUM_THREADS", "1")
            with ProcessPoolExecutor(
                max_workers=min(workers, len(todo)),
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_worker_init,
                initargs=(str(table_path),),
            ) as executor:
                for year, window, candidate, values in executor.map(_fit_task, todo):
                    keys = previous.targets(year)
                    write_forecasts(raw_path(output_dir, year, window, candidate), keys, values)
        else:
            _worker_init(str(table_path))
            for task in todo:
                year, window, candidate, values = _fit_task(task)
                write_forecasts(raw_path(output_dir, year, window, candidate), task[0], values)
    return {
        raw_path(output_dir, y, w, c).relative_to(output_dir).as_posix(): sha256(
            raw_path(output_dir, y, w, c)
        )
        for y in years
        for w in settings.windows
        for c in settings.candidates
    }


# ------------------------------------------------------------------ selection


def select_window(
    raw: Mapping[str, Mapping[int, np.ndarray]],
    previous: PreviousRun,
    outer: int,
    settings: ModelSettings,
) -> dict[str, Any]:
    """Past-only candidate choice and slope for one window and one target season."""
    membership = previous.selection(outer, settings.selection_years_back)
    years = sorted(membership)
    positions = {}
    for year in years:
        position = {k: i for i, k in enumerate(previous.targets(year))}
        positions[year] = np.array([position[k] for k in membership[year]], dtype=np.int64)
    outcomes = {year: previous.outcomes(membership[year]) for year in years}
    trials = {}
    without_forecast = {}
    for candidate in settings.candidates:
        kept_p, kept_y = {}, {}
        for year in years:
            p = raw[candidate][year][positions[year]]
            finite = np.isfinite(p)
            kept_p[year], kept_y[year] = p[finite], outcomes[year][finite]
            without_forecast[str(year)] = int(np.sum(~finite))
        trials[candidate] = pipeline.fit_nonnegative_slope(kept_p, kept_y, years)
    decision = pipeline.select_calibrated_candidate(trials, list(settings.candidates))
    if decision["status"] != "complete":
        raise AllTierModelError(f"selection for {outer} did not complete: {decision['status']}")
    return {
        "candidate": decision["selected_candidate_id"],
        "slope": decision["selected_slope"],
        "selection_rows": {str(y): len(membership[y]) for y in years},
        "selection_rows_without_forecast": without_forecast,
    }


def apply_slope(raw: np.ndarray, slope: float) -> np.ndarray:
    """The calibrated forecast where a raw forecast exists, NaN elsewhere."""
    out = np.full(len(raw), np.nan)
    finite = np.isfinite(raw)
    out[finite] = pipeline.apply_slope(raw[finite], slope)
    return out
