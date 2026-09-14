from __future__ import annotations

import datetime as dt
import math

import numpy as np

from tennislab.benchmark.core import (
    HistoryMatch,
    RatingSuite,
    TargetMatch,
    decaying_k,
    elo_probability,
    rank_base_probability,
    rating_forecasts,
    winner_game_share,
)
from tennislab.benchmark.statistics import ScoredRow, simultaneous_intervals
from tennislab.dynamics import market


def history(match_id: str, day: int, *, a_won: bool = True, level: str = "A") -> HistoryMatch:
    return HistoryMatch(
        match_id=match_id,
        tour="ATP",
        match_date=dt.date(2020, 1, day),
        player_a="1",
        player_b="2",
        surface="Hard",
        level=level,
        a_won=a_won,
        score="6-4 6-4",
    )


def target(match_id: str, cutoff: dt.date) -> TargetMatch:
    return TargetMatch(
        match_id=match_id,
        tour="ATP",
        match_date=cutoff + dt.timedelta(days=2),
        eligible_through_date=cutoff,
        tournament_week="2020-W02",
        player_a="1",
        player_b="2",
        surface="Hard",
        level="A",
    )


def test_equations_and_first_update() -> None:
    assert elo_probability(1500.0, 1500.0) == 0.5
    assert decaying_k(0) == 250.0 / 5.0**0.4
    assert winner_game_share("6-4 7-6(5) [10-8] RET") == 13 / 23

    suite = RatingSuite()
    suite.apply_batch([history("m1", 1)])
    assert suite.k32.overall["1"] == 1516.0
    ordinary = decaying_k(0) * 0.5
    assert math.isclose(suite.kovalchik.ratings["1"], 1500.0 + ordinary)
    assert math.isclose(
        suite.welo.ratings["1"], 1500.0 + ordinary * winner_game_share("6-4 6-4")
    )


def test_declared_missingness_fallbacks() -> None:
    assert rank_base_probability(None, 12.0) == 0.5
    suite = RatingSuite()
    row = history("unparsed", 1)
    suite.apply_batch(
        [
            HistoryMatch(
                match_id=row.match_id,
                tour=row.tour,
                match_date=row.match_date,
                player_a=row.player_a,
                player_b=row.player_b,
                surface=row.surface,
                level=row.level,
                a_won=row.a_won,
                score="RET",
                retired=True,
            )
        ]
    )
    assert suite.fallback_counts()["welo_unparsed_games_standard_updates"] == 1
    assert math.isclose(suite.welo.ratings["1"], 1500.0 + decaying_k(0) * 0.5)


def test_major_is_kovalchik_only_and_surface_blend_is_distinct() -> None:
    regular = RatingSuite()
    major = RatingSuite()
    regular.apply_batch([history("r", 1, level="A")])
    major.apply_batch([history("g", 1, level="G")])
    regular_delta = regular.kovalchik.ratings["1"] - 1500.0
    major_delta = major.kovalchik.ratings["1"] - 1500.0
    assert math.isclose(major_delta / regular_delta, 1.1)
    assert major.fivethirtyeight.overall["1"] == regular.fivethirtyeight.overall["1"]
    expected_rating = 0.71 * major.fivethirtyeight.overall["1"] + 0.29 * major.fivethirtyeight.surface[("1", "Hard")]
    expected = elo_probability(expected_rating, 3000.0 - expected_rating)
    assert math.isclose(major.fivethirtyeight.probability("1", "2", "Hard"), expected)


def test_same_day_shuffle_and_future_outcome_are_invariant() -> None:
    rows_a = [history("m1", 1, a_won=True), history("m2", 1, a_won=False)]
    rows_b = list(reversed(rows_a))
    future_true = history("future", 20, a_won=True)
    future_false = history("future", 20, a_won=False)
    query = target("q", dt.date(2020, 1, 10))
    first, _ = rating_forecasts([*rows_a, future_true], [query], ["G"])
    shuffled, _ = rating_forecasts([*rows_b, future_false], [query], ["G"])
    assert first == shuffled


def test_swap_complementarity() -> None:
    suite = RatingSuite()
    suite.apply_batch([history("m1", 1)])
    p = elo_probability(suite.kovalchik.ratings["1"], suite.kovalchik.ratings["2"])
    assert math.isclose(p + elo_probability(suite.kovalchik.ratings["2"], suite.kovalchik.ratings["1"]), 1.0)


def test_planted_zero_slope_boundary() -> None:
    fitted = market.fit(np.asarray([0.9, 0.8, 0.2, 0.1]), np.asarray([0, 0, 1, 1]))
    assert fitted.market_slope <= 1e-12
    assert np.allclose(fitted.predict(np.asarray([0.9, 0.1])), 0.5)


def test_stationary_bootstrap_is_deterministic_and_shared() -> None:
    rows = [
        ScoredRow(
            year=year,
            week=f"{year}-W{week:02d}",
            values={"incumbent": 0.50 + week / 100, "a": 0.55, "b": 0.60},
        )
        for year in (2019, 2020)
        for week in (1, 3, 4)
    ]
    kwargs = {
        "replicates": 100,
        "maximum_draws": 1000,
        "seed": 17,
        "mean_block": 2,
    }
    first = simultaneous_intervals(
        rows, {"a": ("incumbent", "a"), "b": ("incumbent", "b")}, **kwargs
    )
    second = simultaneous_intervals(
        rows, {"a": ("incumbent", "a"), "b": ("incumbent", "b")}, **kwargs
    )
    assert first == second
    assert first["valid_replicates"] == 100
    assert first["critical_value"] >= 0
