"""Typed dates, the availability cutoff, and the two bounds the archive got wrong.

Every date the chain attaches to a row carries a :class:`DateBasis`. A basis says what
the date *is*: a reported per-match date, an event anchor, or a bound. Only a reported
date or a bound proves that a result was available by a cutoff; a date synthesised as
"event start plus one day per round" is a guess about a clock and is never admissible
as availability evidence (SCAR_TISSUE A1, the 2026 Canada final).

Two bounds are functions here so their regression cases live beside them:

* :func:`satellite_circuit_end` — a satellite circuit's legs share one start anchor and
  are played in later weeks; every leg is dated at the circuit's last possible
  completion, anchor + 7 × legs (SCAR_TISSUE A3, Spain 1 2006).
* :func:`event_end_bound` — a draw-page row with no per-match date is dated at the
  event's end, never earlier (SCAR_TISSUE A1, A2).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

DAYS_PER_CIRCUIT_LEG = 7


class DateBasis(StrEnum):
    """What a row's date is. The string values are the archive's own vocabulary."""

    REPORTED_MATCH_DATE = "tennis_data_reported_date"
    EVENT_ANCHOR = "event_anchor_only_no_match_date_or_clock"
    INFERRED_EVENT_END = "inferred_event_end"
    SATELLITE_CIRCUIT_END = "satellite_circuit_end"
    START_PLUS_ROUND_ORDER = "tournament_start_plus_round_order"

    @property
    def is_bound(self) -> bool:
        return self in (DateBasis.INFERRED_EVENT_END, DateBasis.SATELLITE_CIRCUIT_END)

    @property
    def proves_availability(self) -> bool:
        """A reported date or an upper bound proves availability; a guessed clock does not."""
        return self is DateBasis.REPORTED_MATCH_DATE or self.is_bound


@dataclass(frozen=True)
class TypedDate:
    value: dt.date
    basis: DateBasis

    def available_by(self, cutoff: dt.date) -> bool:
        """True only when this date's basis proves the row was known by ``cutoff``."""
        return self.basis.proves_availability and self.value <= cutoff


def availability_cutoff(target_date: dt.date, lag_calendar_days: int) -> dt.date:
    """The last calendar day whose rows may inform a forecast for ``target_date``."""
    if lag_calendar_days < 0:
        raise ValueError("lag_calendar_days must be non-negative")
    return target_date - dt.timedelta(days=lag_calendar_days)


def satellite_circuit_end(anchor: dt.date, legs: int) -> dt.date:
    """The last possible completion of a multi-leg circuit: anchor + 7 days per leg."""
    if legs < 1:
        raise ValueError("a circuit has at least one leg")
    return anchor + dt.timedelta(days=DAYS_PER_CIRCUIT_LEG * legs)


def event_end_bound(event_start: dt.date, event_end: dt.date) -> TypedDate:
    """Date a row with no per-match date at the event's end, as a bound."""
    if event_end < event_start:
        raise ValueError("event_end precedes event_start")
    return TypedDate(event_end, DateBasis.INFERRED_EVENT_END)
