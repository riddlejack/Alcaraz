"""The two regression cases the rebuild plan names, plus the availability rule."""

import datetime as dt

import pytest

from tennislab.chronology.dating import (
    DateBasis,
    TypedDate,
    availability_cutoff,
    event_end_bound,
    satellite_circuit_end,
)


def test_spain_1_2006_four_legs_are_dated_at_the_circuit_end() -> None:
    # Astra finding 3: circuit anchor 2006-02-27, four legs (a/b/c/d), played to 03-26.
    # The old rule (anchor + 7) released every leg on 2006-03-06.
    anchor = dt.date(2006, 2, 27)
    assigned = satellite_circuit_end(anchor, legs=4)
    assert assigned == dt.date(2006, 3, 27)
    assert assigned != anchor + dt.timedelta(days=7)
    assert assigned >= dt.date(2006, 3, 26)  # never earlier than the last leg's play
    # A single-edition event is unchanged at anchor + 7.
    assert satellite_circuit_end(anchor, legs=1) == dt.date(2006, 3, 6)


def test_canada_final_2026_cannot_enter_a_cincinnati_feature_under_d_minus_2() -> None:
    # Astra finding 1: the Canada final was played 2026-08-13 but a draw-page rule
    # (event start plus one day per round) dated it 08-09. Cincinnati targets on
    # 08-11 and 08-12 then consumed it under the two-day lag.
    canada_start, canada_end = dt.date(2026, 8, 3), dt.date(2026, 8, 13)
    guessed = TypedDate(dt.date(2026, 8, 9), DateBasis.START_PLUS_ROUND_ORDER)
    bounded = event_end_bound(canada_start, canada_end)
    for target in (dt.date(2026, 8, 11), dt.date(2026, 8, 12)):
        cutoff = availability_cutoff(target, lag_calendar_days=2)
        assert not guessed.available_by(cutoff)  # a guessed clock is never evidence
        assert not bounded.available_by(cutoff)  # the bound postdates the cutoff
    # A target after the bound may use it.
    later = availability_cutoff(dt.date(2026, 8, 16), lag_calendar_days=2)
    assert bounded.available_by(later)


def test_reported_dates_prove_availability_and_anchors_do_not() -> None:
    cutoff = dt.date(2024, 6, 1)
    assert TypedDate(dt.date(2024, 5, 30), DateBasis.REPORTED_MATCH_DATE).available_by(cutoff)
    assert not TypedDate(dt.date(2024, 5, 30), DateBasis.EVENT_ANCHOR).available_by(cutoff)
    assert TypedDate(dt.date(2024, 5, 30), DateBasis.SATELLITE_CIRCUIT_END).basis.is_bound


def test_bounds_refuse_impossible_inputs() -> None:
    with pytest.raises(ValueError):
        satellite_circuit_end(dt.date(2006, 2, 27), legs=0)
    with pytest.raises(ValueError):
        event_end_bound(dt.date(2026, 8, 13), dt.date(2026, 8, 3))
    with pytest.raises(ValueError):
        availability_cutoff(dt.date(2026, 8, 13), -1)
