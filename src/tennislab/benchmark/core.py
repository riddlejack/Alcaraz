"""Interpretable public-method tennis baselines for Lane G.

The implementation is deliberately small. Ratings are queried before a date batch and
all deltas in that batch are computed from the same pre-update state. This is the central
chronology invariant; deterministic sorting is serialization, not an information source.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

INITIAL = 1500.0
SCALE = 400.0
DECAY_NUMERATOR = 250.0
DECAY_OFFSET = 5.0
DECAY_EXPONENT = 0.4
MAJOR_MULTIPLIER = 1.1
OVERALL_WEIGHT = 0.71
SURFACE_WEIGHT = 0.29
SUPPORTED_SURFACES = frozenset({"Hard", "Clay", "Grass", "Carpet"})


class BenchmarkError(ValueError):
    """Fail-closed benchmark contract error."""


@dataclass(frozen=True)
class HistoryMatch:
    match_id: str
    tour: str
    match_date: dt.date
    player_a: str
    player_b: str
    surface: str
    level: str
    a_won: bool
    score: str = ""
    played: bool = True
    retired: bool = False

    def __post_init__(self) -> None:
        _validate_pair(self.player_a, self.player_b)


@dataclass(frozen=True)
class TargetMatch:
    match_id: str
    tour: str
    match_date: dt.date
    eligible_through_date: dt.date
    tournament_week: str
    player_a: str
    player_b: str
    surface: str
    level: str
    rank_a: float | None = None
    rank_b: float | None = None

    def __post_init__(self) -> None:
        _validate_pair(self.player_a, self.player_b)
        if self.eligible_through_date > self.match_date:
            raise BenchmarkError(f"{self.match_id}: cutoff follows match date")


def _validate_pair(player_a: str, player_b: str) -> None:
    try:
        a, b = int(player_a), int(player_b)
    except ValueError as exc:
        raise BenchmarkError("player IDs must be decimal integers") from exc
    if a >= b:
        raise BenchmarkError(f"neutral orientation requires player_a < player_b: {a}, {b}")


def elo_probability(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / SCALE))


def decaying_k(prior_matches: int) -> float:
    if prior_matches < 0:
        raise BenchmarkError("prior match count cannot be negative")
    return DECAY_NUMERATOR / (prior_matches + DECAY_OFFSET) ** DECAY_EXPONENT


def rank_base_probability(rank_a: float | None, rank_b: float | None) -> float:
    if rank_a is None or rank_b is None:
        return 0.5
    if not math.isfinite(rank_a) or not math.isfinite(rank_b) or rank_a <= 0 or rank_b <= 0:
        return 0.5
    x = math.log(rank_b / rank_a)
    return 1.0 / (1.0 + math.exp(-x))


_SET_TOKEN = re.compile(r"^(\d+)-(\d+)(?:\(\d+\))?$|^\[(\d+)-(\d+)\]$")


def winner_game_share(score: str) -> float | None:
    """Winner's conventional-game share; brackets are match-tiebreak points and omitted."""
    winner_games = 0
    loser_games = 0
    for raw in score.replace("RET", "").replace("DEF", "").split():
        match = _SET_TOKEN.match(raw.strip())
        if not match or match.group(3) is not None:
            continue
        left, right = int(match.group(1)), int(match.group(2))
        winner_games += left
        loser_games += right
    total = winner_games + loser_games
    return winner_games / total if total else None


class _K32:
    def __init__(self) -> None:
        self.overall: defaultdict[str, float] = defaultdict(lambda: INITIAL)
        self.surface: defaultdict[tuple[str, str], float] = defaultdict(lambda: INITIAL)

    def probability(self, a: str, b: str, surface: str) -> float:
        overall = elo_probability(self.overall[a], self.overall[b])
        if surface not in SUPPORTED_SURFACES:
            return overall
        by_surface = elo_probability(self.surface[(a, surface)], self.surface[(b, surface)])
        return 0.5 * overall + 0.5 * by_surface

    def apply_batch(self, rows: Sequence[HistoryMatch]) -> None:
        overall_delta: defaultdict[str, float] = defaultdict(float)
        surface_delta: defaultdict[tuple[str, str], float] = defaultdict(float)
        for row in rows:
            y = float(row.a_won)
            p_overall = elo_probability(self.overall[row.player_a], self.overall[row.player_b])
            change = 32.0 * (y - p_overall)
            overall_delta[row.player_a] += change
            overall_delta[row.player_b] -= change
            if row.surface in SUPPORTED_SURFACES:
                a_key, b_key = (row.player_a, row.surface), (row.player_b, row.surface)
                p_surface = elo_probability(self.surface[a_key], self.surface[b_key])
                change_surface = 32.0 * (y - p_surface)
                surface_delta[a_key] += change_surface
                surface_delta[b_key] -= change_surface
        for player, change in overall_delta.items():
            self.overall[player] += change
        for key, change in surface_delta.items():
            self.surface[key] += change


class _DecayingOverall:
    def __init__(self, *, major_multiplier: bool, weighted: bool = False) -> None:
        self.ratings: defaultdict[str, float] = defaultdict(lambda: INITIAL)
        self.counts: Counter[str] = Counter()
        self.major_multiplier = major_multiplier
        self.weighted = weighted
        self.missing_score_updates = 0

    def probability(self, a: str, b: str) -> float:
        return elo_probability(self.ratings[a], self.ratings[b])

    def apply_batch(self, rows: Sequence[HistoryMatch], major_codes: frozenset[str]) -> None:
        delta: defaultdict[str, float] = defaultdict(float)
        increments: Counter[str] = Counter()
        for row in rows:
            y = float(row.a_won)
            p = self.probability(row.player_a, row.player_b)
            multiplier = (
                MAJOR_MULTIPLIER if self.major_multiplier and row.level in major_codes else 1.0
            )
            weight = 1.0
            if self.weighted:
                parsed = winner_game_share(row.score)
                if parsed is None:
                    self.missing_score_updates += 1
                else:
                    weight = parsed
            a_k = decaying_k(self.counts[row.player_a]) * multiplier
            b_k = decaying_k(self.counts[row.player_b]) * multiplier
            delta[row.player_a] += a_k * (y - p) * weight
            delta[row.player_b] += b_k * ((1.0 - y) - (1.0 - p)) * weight
            increments[row.player_a] += 1
            increments[row.player_b] += 1
        for player, change in delta.items():
            self.ratings[player] += change
        self.counts.update(increments)


class _FiveThirtyEight:
    def __init__(self) -> None:
        self.overall: defaultdict[str, float] = defaultdict(lambda: INITIAL)
        self.surface: defaultdict[tuple[str, str], float] = defaultdict(lambda: INITIAL)
        self.overall_counts: Counter[str] = Counter()
        self.surface_counts: Counter[tuple[str, str]] = Counter()

    def probability(self, a: str, b: str, surface: str) -> float:
        if surface not in SUPPORTED_SURFACES:
            return elo_probability(self.overall[a], self.overall[b])
        a_rating = OVERALL_WEIGHT * self.overall[a] + SURFACE_WEIGHT * self.surface[(a, surface)]
        b_rating = OVERALL_WEIGHT * self.overall[b] + SURFACE_WEIGHT * self.surface[(b, surface)]
        return elo_probability(a_rating, b_rating)

    def apply_batch(self, rows: Sequence[HistoryMatch]) -> None:
        overall_delta: defaultdict[str, float] = defaultdict(float)
        surface_delta: defaultdict[tuple[str, str], float] = defaultdict(float)
        overall_increments: Counter[str] = Counter()
        surface_increments: Counter[tuple[str, str]] = Counter()
        for row in rows:
            y = float(row.a_won)
            p_overall = elo_probability(self.overall[row.player_a], self.overall[row.player_b])
            a_k = decaying_k(self.overall_counts[row.player_a])
            b_k = decaying_k(self.overall_counts[row.player_b])
            overall_delta[row.player_a] += a_k * (y - p_overall)
            overall_delta[row.player_b] += b_k * ((1.0 - y) - (1.0 - p_overall))
            overall_increments[row.player_a] += 1
            overall_increments[row.player_b] += 1
            if row.surface in SUPPORTED_SURFACES:
                a_key, b_key = (row.player_a, row.surface), (row.player_b, row.surface)
                p_surface = elo_probability(self.surface[a_key], self.surface[b_key])
                a_surface_k = decaying_k(self.surface_counts[a_key])
                b_surface_k = decaying_k(self.surface_counts[b_key])
                surface_delta[a_key] += a_surface_k * (y - p_surface)
                surface_delta[b_key] += b_surface_k * ((1.0 - y) - (1.0 - p_surface))
                surface_increments[a_key] += 1
                surface_increments[b_key] += 1
        for player, change in overall_delta.items():
            self.overall[player] += change
        for key, change in surface_delta.items():
            self.surface[key] += change
        self.overall_counts.update(overall_increments)
        self.surface_counts.update(surface_increments)


class RatingSuite:
    """Four rating services advanced together through immutable date batches."""

    def __init__(self, major_codes: Iterable[str] = ("G",)) -> None:
        self.major_codes = frozenset(major_codes)
        self.k32 = _K32()
        self.kovalchik = _DecayingOverall(major_multiplier=True)
        self.fivethirtyeight = _FiveThirtyEight()
        self.welo = _DecayingOverall(major_multiplier=False, weighted=True)

    def probabilities(self, target: TargetMatch) -> dict[str, float]:
        return {
            "k32_pooled": self.k32.probability(target.player_a, target.player_b, target.surface),
            "kovalchik_overall_major": self.kovalchik.probability(target.player_a, target.player_b),
            "fivethirtyeight_surface": self.fivethirtyeight.probability(
                target.player_a, target.player_b, target.surface
            ),
            "welo": self.welo.probability(target.player_a, target.player_b),
        }

    def apply_batch(self, rows: Sequence[HistoryMatch]) -> None:
        admitted = [row for row in rows if row.played]
        self.k32.apply_batch(admitted)
        self.kovalchik.apply_batch(admitted, self.major_codes)
        self.fivethirtyeight.apply_batch(admitted)
        self.welo.apply_batch(admitted, self.major_codes)

    def fallback_counts(self) -> Mapping[str, int]:
        return {"welo_unparsed_games_standard_updates": self.welo.missing_score_updates}


def rating_forecasts(
    history: Sequence[HistoryMatch], targets: Sequence[TargetMatch], major_codes: Iterable[str]
) -> tuple[dict[str, dict[str, float]], Mapping[str, int]]:
    """Forecast targets with only history through each target's declared cutoff."""
    identifiers = [row.match_id for row in history]
    if len(identifiers) != len(set(identifiers)):
        raise BenchmarkError("duplicate history match_id")
    target_ids = [row.match_id for row in targets]
    if len(target_ids) != len(set(target_ids)):
        raise BenchmarkError("duplicate target match_id")
    ordered_history = sorted(history, key=lambda row: (row.match_date, row.match_id))
    ordered_targets = sorted(targets, key=lambda row: (row.eligible_through_date, row.match_id))
    suite = RatingSuite(major_codes)
    result: dict[str, dict[str, float]] = {}
    cursor = 0
    for target in ordered_targets:
        while (
            cursor < len(ordered_history)
            and ordered_history[cursor].match_date <= target.eligible_through_date
        ):
            date = ordered_history[cursor].match_date
            end = cursor
            while end < len(ordered_history) and ordered_history[end].match_date == date:
                end += 1
            suite.apply_batch(ordered_history[cursor:end])
            cursor = end
        result[target.match_id] = suite.probabilities(target)
    return result, suite.fallback_counts()
