"""Probability-pooled Elo (CONFIRM2026 declared fallback model).

Base revision: ``references/CONFIRM2026_elo/elo_engine.py`` (the only revision; no
TIER01/WTA02 variant of this file exists). Arithmetic, iteration order, name
normalisation and serialization are carried over unchanged -- this module feeds the
CONFIRM2026 Elo baseline, whose outputs are compared byte-for-byte.

What changed in the port: the sibling-import surface is gone (callers import
``tennislab.ratings.elo``), and the ``_cli`` resolves every path it reads or writes
through :func:`tennislab.chain.common.resolve_under_root`. Nothing else.

Arithmetic and parameters are copied from the two validated implementations, not
re-derived:

* State update, frozen source-date batches and the D-2 eligibility rule:
  ``work/MULTI01_features/build_features.py`` class ``EloHistory``
  lines 420-482 (``overall_rating``/``surface_rating`` line 436-440,
  ``probability`` line 442-443, ``feature_logit`` line 445-451,
  ``history_absent`` line 453-454, ``apply_batch`` line 452-482) and its driver
  ``stream_rows`` lines 857-906 (source cursor, ``cutoff = target_date - lag``,
  per-source-date batch, ``pseudo_outcome=False`` for the sports stream).
* Parameters: ``work/MULTI01_features/config.json`` ``parameters``
  (``elo_initial_rating`` 1500.0, ``elo_k`` 32.0, ``elo_scale`` 400.0,
  ``lag_calendar_days`` 2) and ``experiments/ELO-DATE-002-C1.json``
  ``model_parameters`` (identical, plus ``pooled_overall_weight`` 0.5,
  ``pooled_surface_weight`` 0.5, ``pooling_domain`` ``probability_space_mean``).
* Pooling rule: ``experiments/ELO-DATE-002-C1.design.md`` line 7,
  ``p_pooled(A) = 0.5 * p_overall(A) + 0.5 * p_surface(A)`` -- the mean of two
  probabilities, NOT the Elo logistic of a blended rating difference. The legacy
  rating blend at ``src/retrospective.rs:419-422`` (``SURFACE_BLEND``) is the
  superseded pre-C1 form and is deliberately not used here. Overall and surface
  states each keep updating on their own unpooled probability, per the same line.

There is no K schedule: K is the single constant 32.0 in both sources (no
provisional/career-length/level multiplier exists in either implementation).

Known crudeness, stated because the model is a declared weak baseline:
``best_of`` is accepted and carried through the row but does NOT enter the
probability. Pooled Elo has no best-of term.

Exceptions are the archive's own ``ValueError``; they are not narrowed to
``ChainError`` because this is a library other unported archive programs still call
(``bracket.py``, ``daily_ledger.py``, ``regression.py``) and they catch/expect
``ValueError``. ``ChainError`` is itself a ``ValueError``, so a later narrowing stays
source-compatible.

Public interface kept for:

* ``references/TIER01_models/tier_elo.py`` and ``references/WTA02_models/`` (module
  loaded through the ``elo_engine`` config binding): ``PooledElo``,
  ``parse_results``, ``player_key``, ``replay``.
* ``references/TIER01_models/crosswalk_v2.py`` and
  ``references/WTA02_models/crosswalk_v2.py`` (``_elo_engine``): ``normalize_name``.
* ``references/CONFIRM2026_elo/regression.py``: ``MODEL_ID``, ``POOLING_DOMAIN``,
  ``parse_results``, ``replay``.
* ``references/CONFIRM2026_elo/bracket.py``,
  ``references/CONFIRM2026_elo/daily_ledger.py``: ``MODEL_ID``, ``POOLING_DOMAIN``,
  ``PooledElo`` (``advance_to``, ``pooled_probability``, ``state_hash``),
  ``player_key``, ``read_results_csv``, ``probability_function``.
* ``references/CONFIRM2026_elo/crosswalk.py`` -> ``tennislab.panel.elo_crosswalk``:
  ``normalize_name``.
* ``experiments/runs/CONFIRM2026/elo_001/`` (``replay.py``, ``issue_ledger*.py``,
  ``run_bracket*.py``): ``MODEL_ID``, ``POOLING_DOMAIN``, ``key_label``,
  ``parse_results``, ``player_key``, ``replay``, ``state_as_of``, and on the engine
  ``serialize``, ``state_hash``, ``applied_rows``, ``latest_source_date``,
  ``overall``, ``surface``.
* The archive unit tests (now ``tests/test_elo.py``): ``INITIAL_RATING``,
  ``ELO_K``, ``ELO_SCALE``, ``POOLED_OVERALL_WEIGHT``, ``POOLED_SURFACE_WEIGHT``,
  ``POOLING_DOMAIN``, ``DEFAULT_LAG_DAYS``, ``PooledElo.prospective``,
  ``Prediction``, ``Result``, ``SURFACES``, ``RESULT_COLUMNS``, ``PlayerKey``.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tennislab.chain.common import resolve_under_root

MODEL_ID = "CONFIRM2026-pooled-elo-v1"

# Copied verbatim from work/MULTI01_features/config.json parameters and
# experiments/ELO-DATE-002-C1.json model_parameters.
INITIAL_RATING = 1500.0
ELO_K = 32.0
ELO_SCALE = 400.0
POOLED_OVERALL_WEIGHT = 0.5
POOLED_SURFACE_WEIGHT = 0.5
POOLING_DOMAIN = "probability_space_mean"
DEFAULT_LAG_DAYS = 2

# work/MULTI01_features/build_features.py line 27.
SURFACES = ("Hard", "Clay", "Grass", "Carpet")

RESULT_COLUMNS = (
    "date",
    "tour",
    "tournament",
    "level",
    "round",
    "surface",
    "best_of",
    "winner_id",
    "loser_id",
    "winner_name",
    "loser_name",
    "source",
)

# Player identity key: ids sort numerically and ahead of name-only keys, so the
# neutral orientation "lower id is side A" is the same integer ordering
# build_features.py enforces (player_a < player_b, line 320).
PlayerKey = tuple[int, int, str]


def normalize_name(name: str) -> str:
    """Lowercase, ASCII-fold, drop punctuation, collapse whitespace."""
    folded = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    ascii_only = ascii_only.encode("ascii", "ignore").decode("ascii").lower()
    kept = "".join(ch if ch.isalnum() else " " for ch in ascii_only)
    return " ".join(kept.split())


def player_key(raw_id: str, name: str) -> PlayerKey:
    """Ids take priority over names."""
    raw_id = (raw_id or "").strip()
    if raw_id:
        try:
            return (0, int(raw_id), "")
        except ValueError as exc:
            raise ValueError(f"non-integer player id {raw_id!r}") from exc
    normalized = normalize_name(name or "")
    if not normalized:
        raise ValueError("row carries neither player id nor player name")
    return (1, 0, normalized)


def key_label(key: PlayerKey) -> str:
    return str(key[1]) if key[0] == 0 else f"name:{key[2]}"


@dataclass(frozen=True)
class Result:
    """One played match in the canonical CONFIRM2026 results schema."""

    date: dt.date
    tour: str
    tournament: str
    level: str
    round: str
    surface: str
    best_of: int | None
    winner: PlayerKey
    loser: PlayerKey
    winner_name: str
    loser_name: str
    source: str
    row_index: int

    @property
    def player_a(self) -> PlayerKey:
        return min(self.winner, self.loser)

    @property
    def player_b(self) -> PlayerKey:
        return max(self.winner, self.loser)

    @property
    def a_won(self) -> bool:
        return self.winner <= self.loser

    def order_key(self) -> tuple[dt.date, int]:
        return self.date, self.row_index


def parse_results(
    rows: Iterable[Mapping[str, str]], *, strict_surface: bool = True
) -> list[Result]:
    results: list[Result] = []
    for index, row in enumerate(rows):
        missing = [column for column in RESULT_COLUMNS if column not in row]
        if missing:
            raise ValueError(f"results row {index} missing columns {missing}")
        surface = (row["surface"] or "").strip()
        if surface not in SURFACES:
            if strict_surface:
                raise ValueError(f"results row {index} unsupported surface {surface!r}")
            continue
        best_of_raw = (row["best_of"] or "").strip()
        best_of = int(best_of_raw) if best_of_raw else None
        if best_of is not None and best_of not in {3, 5}:
            raise ValueError(f"results row {index} unsupported best_of {best_of}")
        tour = (row["tour"] or "").strip().upper()
        if tour not in {"ATP", "WTA"}:
            raise ValueError(f"results row {index} unsupported tour {tour!r}")
        winner = player_key(row["winner_id"], row["winner_name"])
        loser = player_key(row["loser_id"], row["loser_name"])
        if winner == loser:
            raise ValueError(f"results row {index} has the same player on both sides")
        results.append(
            Result(
                date=dt.date.fromisoformat((row["date"] or "").strip()),
                tour=tour,
                tournament=(row["tournament"] or "").strip(),
                level=(row["level"] or "").strip(),
                round=(row["round"] or "").strip(),
                surface=surface,
                best_of=best_of,
                winner=winner,
                loser=loser,
                winner_name=(row["winner_name"] or "").strip(),
                loser_name=(row["loser_name"] or "").strip(),
                source=(row["source"] or "").strip(),
                row_index=index,
            )
        )
    # Stable sort on date only: within a date the input file order is preserved,
    # which is what makes a bit-exact replay of another table possible (supply
    # its rows in its own within-date order).
    results.sort(key=Result.order_key)
    return results


def read_results_csv(path: str | Path, *, strict_surface: bool = True) -> list[Result]:
    with open(path, newline="", encoding="utf-8") as handle:
        return parse_results(csv.DictReader(handle), strict_surface=strict_surface)


@dataclass(frozen=True)
class Prediction:
    """Pre-match probabilities under the state eligible for this match."""

    date: dt.date
    eligible_through: dt.date
    surface: str
    best_of: int | None
    player_a: PlayerKey
    player_b: PlayerKey
    p_overall_a: float
    p_surface_a: float
    p_pooled_a: float
    elo_overall_logit: float
    elo_surface_logit: float
    history_absent_overall_a: int
    history_absent_overall_b: int
    history_absent_surface_a: int
    history_absent_surface_b: int
    a_won: bool | None

    @property
    def p_pooled_b(self) -> float:
        return 1.0 - self.p_pooled_a

    def as_dict(self) -> dict[str, object]:
        return {
            "date": self.date.isoformat(),
            "eligible_through": self.eligible_through.isoformat(),
            "surface": self.surface,
            "best_of": self.best_of,
            "player_a": key_label(self.player_a),
            "player_b": key_label(self.player_b),
            "p_pooled_a": self.p_pooled_a,
            "p_pooled_b": self.p_pooled_b,
            "p_overall_a": self.p_overall_a,
            "p_surface_a": self.p_surface_a,
            "elo_overall_logit": self.elo_overall_logit,
            "elo_surface_logit": self.elo_surface_logit,
            "history_absent_overall_a": self.history_absent_overall_a,
            "history_absent_overall_b": self.history_absent_overall_b,
            "history_absent_surface_a": self.history_absent_surface_a,
            "history_absent_surface_b": self.history_absent_surface_b,
            "a_won": self.a_won,
        }


class PooledElo:
    """Probability-pooled Elo state with frozen source-date batch updates."""

    def __init__(
        self,
        initial: float = INITIAL_RATING,
        k: float = ELO_K,
        scale: float = ELO_SCALE,
        overall_weight: float = POOLED_OVERALL_WEIGHT,
        surface_weight: float = POOLED_SURFACE_WEIGHT,
    ):
        if abs(overall_weight + surface_weight - 1.0) > 1e-12:
            raise ValueError("pooling weights must sum to 1")
        self.initial = initial
        self.k = k
        self.scale = scale
        self.overall_weight = overall_weight
        self.surface_weight = surface_weight
        self.overall: dict[PlayerKey, float] = {}
        self.surface: dict[tuple[PlayerKey, str], float] = {}
        self.overall_matches: Counter[PlayerKey] = Counter()
        self.surface_matches: Counter[tuple[PlayerKey, str]] = Counter()
        self.latest_source_date: dt.date | None = None
        self.applied_rows = 0

    # --- read-only views -------------------------------------------------
    def overall_rating(self, player: PlayerKey) -> float:
        return self.overall.get(player, self.initial)

    def surface_rating(self, player: PlayerKey, surface: str) -> float:
        return self.surface.get((player, surface), self.initial)

    def probability(self, rating_a: float, rating_b: float) -> float:
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / self.scale))

    def feature_logit(
        self, player_a: PlayerKey, player_b: PlayerKey, surface: str
    ) -> tuple[float, float]:
        factor = math.log(10.0) / self.scale
        return (
            (self.overall_rating(player_a) - self.overall_rating(player_b)) * factor,
            (self.surface_rating(player_a, surface) - self.surface_rating(player_b, surface))
            * factor,
        )

    def history_absent(self, player: PlayerKey, surface: str) -> tuple[int, int]:
        return (
            int(self.overall_matches[player] == 0),
            int(self.surface_matches[(player, surface)] == 0),
        )

    def pooled_probability(
        self, player_a: PlayerKey, player_b: PlayerKey, surface: str
    ) -> tuple[float, float, float]:
        """Return (p_overall_a, p_surface_a, p_pooled_a) for the current state."""
        if surface not in SURFACES:
            raise ValueError(f"unsupported surface {surface!r}")
        p_overall = self.probability(self.overall_rating(player_a), self.overall_rating(player_b))
        p_surface = self.probability(
            self.surface_rating(player_a, surface), self.surface_rating(player_b, surface)
        )
        return (
            p_overall,
            p_surface,
            self.overall_weight * p_overall + self.surface_weight * p_surface,
        )

    # --- (c) prospective pricing ---------------------------------------
    def prospective(
        self,
        player_x: PlayerKey,
        player_y: PlayerKey,
        surface: str,
        best_of: int | None = None,
        date: dt.date | None = None,
    ) -> dict[str, object]:
        """Price an arbitrary pairing from the current state.

        ``best_of`` and ``date`` are recorded for the receipt only; pooled Elo
        has no best-of term and no time decay, so neither changes the number.
        """
        if best_of is not None and best_of not in {3, 5}:
            raise ValueError(f"unsupported best_of {best_of}")
        p_overall, p_surface, p_pooled = self.pooled_probability(player_x, player_y, surface)
        absent_overall_x, absent_surface_x = self.history_absent(player_x, surface)
        absent_overall_y, absent_surface_y = self.history_absent(player_y, surface)
        return {
            "player_x": key_label(player_x),
            "player_y": key_label(player_y),
            "surface": surface,
            "best_of": best_of,
            "best_of_used_by_model": False,
            "date": date.isoformat() if date else None,
            "state_through": (
                self.latest_source_date.isoformat() if self.latest_source_date else None
            ),
            "p_x": p_pooled,
            "p_y": 1.0 - p_pooled,
            "p_overall_x": p_overall,
            "p_surface_x": p_surface,
            "cold_start_overall": bool(absent_overall_x or absent_overall_y),
            "cold_start_surface": bool(absent_surface_x or absent_surface_y),
        }

    # --- state update ---------------------------------------------------
    def apply_batch(self, batch: Sequence[Result]) -> None:
        """One frozen source-date batch (build_features.py:452-482)."""
        overall_deltas: dict[PlayerKey, float] = defaultdict(float)
        surface_deltas: dict[tuple[PlayerKey, str], float] = defaultdict(float)
        used: list[Result] = []
        for record in batch:
            y_a = float(record.a_won)  # outcome-history read
            player_a, player_b = record.player_a, record.player_b
            p_overall = self.probability(
                self.overall_rating(player_a), self.overall_rating(player_b)
            )
            p_surface = self.probability(
                self.surface_rating(player_a, record.surface),
                self.surface_rating(player_b, record.surface),
            )
            overall_delta = self.k * (y_a - p_overall)
            surface_delta = self.k * (y_a - p_surface)
            overall_deltas[player_a] += overall_delta
            overall_deltas[player_b] -= overall_delta
            surface_deltas[(player_a, record.surface)] += surface_delta
            surface_deltas[(player_b, record.surface)] -= surface_delta
            used.append(record)
        for player in sorted(overall_deltas):
            self.overall[player] = self.overall_rating(player) + overall_deltas[player]
        for key in sorted(surface_deltas):
            self.surface[key] = self.surface_rating(*key) + surface_deltas[key]
        for record in used:
            self.overall_matches[record.player_a] += 1
            self.overall_matches[record.player_b] += 1
            self.surface_matches[(record.player_a, record.surface)] += 1
            self.surface_matches[(record.player_b, record.surface)] += 1
            if self.latest_source_date is None or record.date > self.latest_source_date:
                self.latest_source_date = record.date
        self.applied_rows += len(used)

    # --- (b) state as of a date ----------------------------------------
    def advance_to(self, sources: Sequence[Result], cutoff: dt.date, cursor: int = 0) -> int:
        """Apply every source row dated <= cutoff, in frozen source-date batches."""
        while cursor < len(sources) and sources[cursor].date <= cutoff:
            source_date = sources[cursor].date
            end = cursor + 1
            while end < len(sources) and sources[end].date == source_date:
                end += 1
            self.apply_batch(sources[cursor:end])
            cursor = end
        return cursor

    # --- serialization / receipts ---------------------------------------
    def serialize(self) -> str:
        payload = {
            "model_id": MODEL_ID,
            "pooling_domain": POOLING_DOMAIN,
            "parameters": {
                "initial_rating": self.initial,
                "elo_k": self.k,
                "elo_scale": self.scale,
                "pooled_overall_weight": self.overall_weight,
                "pooled_surface_weight": self.surface_weight,
            },
            "latest_source_date": (
                self.latest_source_date.isoformat() if self.latest_source_date else None
            ),
            "applied_rows": self.applied_rows,
            "overall": [
                [key_label(k), repr(v), self.overall_matches[k]]
                for k, v in sorted(self.overall.items())
            ],
            "surface": [
                [key_label(k[0]), k[1], repr(v), self.surface_matches[k]]
                for k, v in sorted(self.surface.items())
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def state_hash(self) -> str:
        return hashlib.sha256(self.serialize().encode("utf-8")).hexdigest()


def state_as_of(
    sources: Sequence[Result],
    cutoff: dt.date,
    *,
    engine: PooledElo | None = None,
) -> PooledElo:
    """(b) Replay ``sources`` and return the state eligible through ``cutoff``."""
    engine = engine or PooledElo()
    engine.advance_to(sources, cutoff)
    return engine


def replay(
    results: Sequence[Result],
    *,
    lag_days: int = DEFAULT_LAG_DAYS,
    sources: Sequence[Result] | None = None,
    engine: PooledElo | None = None,
) -> Iterator[Prediction]:
    """(a) Pre-match probability for every played match, neutral orientation.

    ``results`` are the target matches to price. ``sources`` default to the same
    table (a self-replay from 2005); pass a different table to price matches
    from a history that is not itself the target set. ``lag_days`` is the
    eligibility rule: state uses only rows dated <= target date - lag_days
    (2 reproduces the MULTI01/JOINT04 retrospective contract; 0 is the natural
    prospective rule, where yesterday's results are known).
    """
    engine = engine or PooledElo()
    sources = list(results) if sources is None else list(sources)
    targets = list(results)
    cursor = 0
    index = 0
    while index < len(targets):
        target_date = targets[index].date
        end = index + 1
        while end < len(targets) and targets[end].date == target_date:
            end += 1
        cutoff = target_date - dt.timedelta(days=lag_days)
        cursor = engine.advance_to(sources, cutoff, cursor)
        if engine.latest_source_date is not None and engine.latest_source_date > cutoff:
            raise ValueError(f"state date {engine.latest_source_date} exceeds cutoff {cutoff}")
        for record in targets[index:end]:
            player_a, player_b = record.player_a, record.player_b
            p_overall, p_surface, p_pooled = engine.pooled_probability(
                player_a, player_b, record.surface
            )
            overall_logit, surface_logit = engine.feature_logit(player_a, player_b, record.surface)
            absent_overall_a, absent_surface_a = engine.history_absent(player_a, record.surface)
            absent_overall_b, absent_surface_b = engine.history_absent(player_b, record.surface)
            yield Prediction(
                date=record.date,
                eligible_through=cutoff,
                surface=record.surface,
                best_of=record.best_of,
                player_a=player_a,
                player_b=player_b,
                p_overall_a=p_overall,
                p_surface_a=p_surface,
                p_pooled_a=p_pooled,
                elo_overall_logit=overall_logit,
                elo_surface_logit=surface_logit,
                history_absent_overall_a=absent_overall_a,
                history_absent_overall_b=absent_overall_b,
                history_absent_surface_a=absent_surface_a,
                history_absent_surface_b=absent_surface_b,
                a_won=record.a_won,  # outcome-history read
            )
        index = end


def probability_function(engine: PooledElo, surface: str, best_of: int | None = None):
    """Adapter for bracket.py / daily_ledger.py: (x, y) -> P(x beats y)."""

    def probability(player_x: PlayerKey, player_y: PlayerKey) -> float:
        return engine.pooled_probability(player_x, player_y, surface)[2]

    _ = best_of  # recorded by callers; not a model input
    return probability


def _cli(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Replay a results table and emit pooled-Elo predictions."
    )
    parser.add_argument("results", help="CSV in the canonical CONFIRM2026 results schema")
    parser.add_argument("--out", help="write predictions as JSON lines")
    parser.add_argument("--lag-days", type=int, default=DEFAULT_LAG_DAYS)
    parser.add_argument("--state-out", help="write the final serialized state")
    args = parser.parse_args(argv)

    results = read_results_csv(resolve_under_root(args.results, label="results"))
    engine = PooledElo()
    out_path = resolve_under_root(args.out, label="out") if args.out else None
    handle = open(out_path, "w", encoding="utf-8") if out_path else None
    count = 0
    try:
        for prediction in replay(results, lag_days=args.lag_days, engine=engine):
            count += 1
            if handle:
                handle.write(json.dumps(prediction.as_dict(), sort_keys=True) + "\n")
    finally:
        if handle:
            handle.close()
    if args.state_out:
        resolve_under_root(args.state_out, label="state_out").write_text(
            engine.serialize() + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "rows_priced": count,
                "rows_applied_to_state": engine.applied_rows,
                "latest_source_date": (
                    engine.latest_source_date.isoformat() if engine.latest_source_date else None
                ),
                "state_sha256": engine.state_hash(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
