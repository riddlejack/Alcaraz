"""The tier-inclusive pooled Elo replay and the lower-tier experience counts.

Stage ``tier_elo``. Ported from the archive's ``TIER01_models/tier_elo.py`` (revision 2,
per-training-window offsets); there is no WTA02 copy.

What is reused, and what is new. The arithmetic is :mod:`tennislab.ratings.elo`
(``PooledElo``, its probability, its ``feature_logit``, its frozen source-date batches
and its D-2 ``replay``), imported by name; the config's ``elo_engine`` path-and-hash
binding is recorded as ``declared_binding`` and never selects the code that runs.
:class:`TierPooledElo` subclasses the engine and changes exactly two things:

1. **a fixed per-tier K multiplier** -- tour 1.0, Challenger 0.8, qualifying 0.8,
   Futures 0.6, read from the row's ``source`` column (``TIER01-<tier>`` from
   ``tier_stream``; ``MULTI01-panel`` for a tour row). ``apply_batch`` is the one method
   re-implemented, and the only difference from the parent is ``self.k * multiplier``.
2. **a tier-aware initial rating.** A player whose first *state-updating* appearance is
   a lower-tier match starts at ``initial + offset`` instead of 1500, fixed lazily at the
   row that first involves the player, for both the overall and the per-surface state.

**The offset is a learned constant with a receipt.** It is measured by
:func:`measure_offset` -- the mean, over players whose first tour-level match falls on or
before a horizon and who have eligible lower-tier history before it, of their
lower-tier-only overall rating at the D-2 cutoff minus 1500 -- and negated. In
``per_training_window`` mode the offset for a row dated in year Y is measured on rows
strictly before the start of Y's training window, ``max(history_floor_year, Y -
training_window_years)-01-01``; the panel is replayed once per distinct horizon and each
row takes the replay its year maps to. ``tier_offsets_by_year.csv`` records, per season,
the window start, the horizon the offset was measured through, the value, the mean gap
and the player count; the run refuses a declared value that drifts from the
re-measurement by more than 1e-6. ``single`` mode is revision 1 and is retained.

Also emitted, per panel row and side, from the same monotone D-2 cursor: the prior
lower-tier match and title counts (capped at 300 and 20, raw counts kept beside them),
the debut tier, whether the offset was applied, days since the last lower-tier match and
the tier-inclusive history-absent flags.

**Outcome reads.** An Elo state is made of past outcomes. ``labels.csv`` is read once,
as history, through :class:`tennislab.chain.labels.LabelHistory` with the purpose
:data:`ELO_STATE_PURPOSE` and a year ceiling of ``panel_end_year``; every returned row's
identity, chronology and split fields are checked against ``features.csv``. No label is
written -- ``a_won`` reaches no output row -- and a target's own outcome cannot reach its
own features because the cursor stops ``lag_calendar_days`` before its date.

    python -m tennislab.ratings.tier_elo --config <configs/tier_elo.json> [--output-dir D]
    python -m tennislab.ratings.tier_elo --config <...> --measure-offset
    python -m tennislab.ratings.tier_elo --config <...> --without-lower-tier
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_csv,
    atomic_json,
    code_receipt,
    read_config,
    read_csv_rows,
    relative_to_root,
    require_hash,
    resolve_under_root,
    year_plan,
)
from tennislab.chain.labels import LabelHistory
from tennislab.ratings import elo

TOUR_SOURCE = "MULTI01-panel"
TIER_SOURCE_PREFIX = "TIER01-"
TIERS = ("challenger", "qualifying", "futures")
# The declared history purpose of this stage's one outcome read. `chain.labels.PURPOSES`
# names the pipeline's three purposes only; see `EloStateHistory`.
ELO_STATE_PURPOSE = "elo_state_replay"

DEFAULT_PARAMETERS = {
    "lag_calendar_days": 2,
    "elo_start_year": 2005,
    "experience_start_year": 1991,
    "offset_measurement_end_year": 2016,
    "prior_match_cap": 300,
    "prior_title_cap": 20,
    "k_multipliers": {"tour": 1.0, "challenger": 0.8, "qualifying": 0.8, "futures": 0.6},
    "lower_tier_initial_offset": None,
    # "single" is revision 1: one offset measured through offset_measurement_end_year and
    # used everywhere. "per_training_window" re-measures it inside every chronological
    # training boundary.
    "offset_mode": "single",
    "lower_tier_initial_offset_by_year": None,
}
DECLARED_MULTIPLIERS = {"tour": 1.0, "challenger": 0.8, "qualifying": 0.8, "futures": 0.6}
OFFSET_MODES = ("single", "per_training_window")

FEATURE_FIELDS = (
    "match_id",
    "match_date",
    "surface",
    "player_a",
    "player_b",
    "tier_elo_overall_logit",
    "tier_elo_surface_logit",
    "tier_prior_matches_a",
    "tier_prior_matches_b",
    "tier_prior_titles_a",
    "tier_prior_titles_b",
    "tier_prior_matches_raw_a",
    "tier_prior_matches_raw_b",
    "tier_prior_titles_raw_a",
    "tier_prior_titles_raw_b",
    "tier_first_tier_a",
    "tier_first_tier_b",
    "tier_initial_offset_applied_a",
    "tier_initial_offset_applied_b",
    "tier_last_lower_match_days_a",
    "tier_last_lower_match_days_b",
    "tier_history_absent_overall_a",
    "tier_history_absent_overall_b",
    "tier_history_absent_surface_a",
    "tier_history_absent_surface_b",
    "elo_overall_logit_base",
    "elo_surface_logit_base",
)
OFFSET_FIELDS = (
    "season",
    "training_window_start",
    "offset_measured_through",
    "lower_tier_initial_offset",
    "mean_gap",
    "players_measured",
)


class TierEloError(ChainError):
    """Fail-closed binding, chronology or declared-constant error."""


class EloStateHistory(LabelHistory):
    """The label accessor opened for the Elo state replay (purpose ``elo_state_replay``)."""

    def __init__(self, path: Path, expected_sha256: str, *, year_ceiling: int) -> None:
        if isinstance(year_ceiling, bool) or year_ceiling <= 0:
            raise TierEloError("year_ceiling must be a positive integer")
        super().__init__(
            path, expected_sha256, purpose=ELO_STATE_PURPOSE, year_ceiling=year_ceiling
        )


def read_csv_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rb") as handle:
        text = handle.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text, newline="")))


# ------------------------------------------------------------------ the engine


def offset_window_start(year: int, plan: Any) -> dt.date:
    """The first day of the training window a raw model for ``year`` is fitted on.

    ``pipeline.training_window``: ``max(history_floor_year, year - training_window_years)``,
    January 1. A row dated before the history floor is never a fit row and never a
    target; it is given the floor year's window so that one offset covers it.
    """
    effective = max(int(year), int(plan.history_floor_year))
    start_year = max(int(plan.history_floor_year), effective - int(plan.training_window_years))
    return dt.date(start_year, 1, 1)


def offset_year_horizon(year: int, plan: Any) -> int:
    """The last calendar year an offset for ``year``'s rows may read: strictly before the
    start of that year's training window."""
    return offset_window_start(year, plan).year - 1


def tier_of_source(source: str) -> str:
    if source == TOUR_SOURCE:
        return "tour"
    if source.startswith(TIER_SOURCE_PREFIX):
        tier = source[len(TIER_SOURCE_PREFIX) :]
        if tier in TIERS:
            return tier
    raise TierEloError(f"unknown stream source {source!r}")


class TierPooledElo(elo.PooledElo):
    """``PooledElo`` with a fixed per-tier K multiplier and a tier-aware initial rating."""

    def __init__(self, multipliers: Mapping[str, float], offset: float) -> None:
        super().__init__()
        self.multipliers = dict(multipliers)
        self.offset = float(offset)
        self.debut_initial: dict[Any, float] = {}
        self.debut_tier: dict[Any, str] = {}
        self.applied_rows_by_tier: Counter[str] = Counter()

    # --- read-only views: the only change is the default for an unseen player
    def initial_for(self, player: Any) -> float:
        return self.debut_initial.get(player, self.initial)

    def overall_rating(self, player: Any) -> float:
        return self.overall.get(player, self.initial_for(player))

    def surface_rating(self, player: Any, surface: str) -> float:
        return self.surface.get((player, surface), self.initial_for(player))

    def note_debut(self, player: Any, tier: str) -> None:
        """Fix a player's initial rating from the tier of the row that first uses it."""
        if player in self.debut_initial:
            return
        self.debut_tier[player] = tier
        self.debut_initial[player] = self.initial if tier == "tour" else self.initial + self.offset

    # --- state update: the parent's frozen batch with one multiplied K
    def apply_batch(self, batch: Sequence[Any]) -> None:
        overall_deltas: dict[Any, float] = defaultdict(float)
        surface_deltas: dict[tuple[Any, str], float] = defaultdict(float)
        used: list[Any] = []
        for record in batch:
            tier = tier_of_source(record.source)
            multiplier = self.multipliers[tier]
            player_a, player_b = record.player_a, record.player_b
            self.note_debut(player_a, tier)
            self.note_debut(player_b, tier)
            y_a = float(record.a_won)  # outcome-history read: the state update
            p_overall = self.probability(
                self.overall_rating(player_a), self.overall_rating(player_b)
            )
            p_surface = self.probability(
                self.surface_rating(player_a, record.surface),
                self.surface_rating(player_b, record.surface),
            )
            overall_delta = self.k * multiplier * (y_a - p_overall)
            surface_delta = self.k * multiplier * (y_a - p_surface)
            overall_deltas[player_a] += overall_delta
            overall_deltas[player_b] -= overall_delta
            surface_deltas[(player_a, record.surface)] += surface_delta
            surface_deltas[(player_b, record.surface)] -= surface_delta
            used.append(record)
            self.applied_rows_by_tier[tier] += 1
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


def make_engine(multipliers: Mapping[str, float], offset: float) -> TierPooledElo:
    return TierPooledElo(multipliers, offset)


# ------------------------------------------------------------------ the streams


def tour_rows(
    features_path: Path, labels_path: Path, labels_sha256: str, *, year_ceiling: int
) -> list[dict[str, str]]:
    """The CONFIRM2026 regression's ``panel_stream_rows``, unchanged in substance.

    Targets are every panel row; the state-updating sources are the primary-identity
    rows, which is the subset MULTI01's own ``EloHistory`` consumed. The outcomes come
    from the label accessor, which verifies each row's metadata against the feature row.
    """
    _, feature_rows = read_csv_rows(features_path)
    keys = [(row["source_season"], row["match_id"]) for row in feature_rows]
    if len(set(keys)) != len(keys):
        raise TierEloError("duplicate feature key")
    metadata = dict(zip(keys, feature_rows, strict=True))
    history = EloStateHistory(labels_path, labels_sha256, year_ceiling=year_ceiling)
    labels = history.selected(keys, metadata).values  # outcome-history read
    rows: list[dict[str, str]] = []
    for key, row in zip(keys, feature_rows, strict=True):
        a_won = labels[key]
        winner, loser = (
            (row["player_a"], row["player_b"]) if a_won == 1 else (row["player_b"], row["player_a"])
        )
        rows.append(
            {
                "date": row["match_date"],
                "tour": "ATP",
                "tournament": row["tourney_name"],
                "level": row["tourney_level"],
                "round": row["round"],
                "surface": row["surface"],
                "best_of": row["best_of"],
                "winner_id": winner,
                "loser_id": loser,
                "winner_name": "",
                "loser_name": "",
                "source": TOUR_SOURCE,
                "match_id": row["match_id"],
                "identity_tier": row["identity_tier"],
                "elo_overall_logit": row["elo_overall_logit"],
                "elo_surface_logit": row["elo_surface_logit"],
            }
        )
    rows.sort(key=lambda item: (item["date"], item["match_id"]))
    return rows


def lower_rows(
    path: Path, *, elo_start_year: int, experience_start_year: int, panel_end_year: int
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(rows admitted to the Elo state, rows admitted to the experience counters)."""
    rows = read_csv_gz(path)
    elo_stream: list[dict[str, str]] = []
    experience: list[dict[str, str]] = []
    for row in rows:
        season = int(row["season"])
        if season > panel_end_year:
            raise TierEloError(f"lower-tier row from a season after the panel: {season}")
        if season >= experience_start_year:
            experience.append(row)
        if season >= elo_start_year:
            elo_stream.append(row)
    elo_stream.sort(key=lambda item: (item["date"], item["match_id"]))
    experience.sort(key=lambda item: (item["date"], item["match_id"]))
    return elo_stream, experience


class Experience:
    """Prior lower-tier match and title counts per player, advanced by a monotone cursor."""

    def __init__(self, rows: Sequence[Mapping[str, str]]) -> None:
        self.rows = rows
        self.cursor = 0
        self.matches: Counter[int] = Counter()
        self.titles: Counter[int] = Counter()
        self.last_date: dict[int, dt.date] = {}

    def advance_to(self, cutoff: dt.date) -> None:
        while self.cursor < len(self.rows):
            row = self.rows[self.cursor]
            date = dt.date.fromisoformat(row["date"])
            if date > cutoff:
                break
            winner, loser = int(row["winner_id"]), int(row["loser_id"])
            for player in (winner, loser):
                self.matches[player] += 1
                self.last_date[player] = date
            if row["is_final"] == "1":
                self.titles[winner] += 1
            self.cursor += 1


# ------------------------------------------------------------------ the offset


def measure_offset(
    tour: Sequence[Mapping[str, str]],
    lower: Sequence[Mapping[str, str]],
    *,
    multipliers: Mapping[str, float],
    lag_days: int,
    end_year: int,
    allow_empty: bool = False,
) -> dict[str, Any]:
    """The declared measurement. Reads no row dated after ``end_year``.

    ``allow_empty`` is used only by ``per_training_window`` mode, whose earliest
    boundaries can precede every lower-tier row in the stream. With no evidence there is
    no measured gap, so the offset is 0.0 -- a lower-tier debutant starts at the tour
    default -- and the emptiness is recorded rather than imputed.
    """
    horizon = dt.date(end_year, 12, 31)
    lower_in_window = [row for row in lower if dt.date.fromisoformat(row["date"]) <= horizon]
    sources = elo.parse_results(lower_in_window)
    engine = make_engine(multipliers, 0.0)

    first_tour: dict[int, dt.date] = {}
    for row in tour:
        if row["identity_tier"] != "primary":
            continue
        date = dt.date.fromisoformat(row["date"])
        if date > horizon:
            continue
        for side in ("winner_id", "loser_id"):
            player = int(row[side])
            if player not in first_tour or date < first_tour[player]:
                first_tour[player] = date

    seen: set[int] = set()
    for row in lower_in_window:
        seen.add(int(row["winner_id"]))
        seen.add(int(row["loser_id"]))

    gaps: list[float] = []
    cursor = 0
    for player, date in sorted(first_tour.items(), key=lambda item: (item[1], item[0])):
        if player not in seen:
            continue
        cutoff = date - dt.timedelta(days=lag_days)
        cursor = engine.advance_to(sources, cutoff, cursor)
        key = elo.player_key(str(player), "")
        if engine.overall_matches[key] == 0:
            continue
        gaps.append(engine.overall_rating(key) - engine.initial)
    if not gaps:
        if not allow_empty:
            raise TierEloError("no player supports the initial-rating measurement")
        return {
            "players_measured": 0,
            "mean_first_tour_level_rating_gap": 0.0,
            "median_first_tour_level_rating_gap": 0.0,
            "lower_tier_initial_offset": 0.0,
            "measurement_window": [end_year, end_year],
            "lower_tier_rows_used": len(lower_in_window),
            "basis": (
                "no player has eligible lower-tier history before "
                f"{horizon.isoformat()}, so no gap is measurable and the offset is 0.0"
            ),
        }
    gap = sum(gaps) / len(gaps)
    return {
        "players_measured": len(gaps),
        "mean_first_tour_level_rating_gap": gap,
        "median_first_tour_level_rating_gap": sorted(gaps)[len(gaps) // 2],
        "lower_tier_initial_offset": -gap,
        "measurement_window": [min(int(row["season"]) for row in lower_in_window), end_year],
        "lower_tier_rows_used": len(lower_in_window),
        "basis": (
            "mean over players whose first tour-level match is at or before "
            f"{horizon.isoformat()} and who have an eligible lower-tier match before it, "
            "of (lower-tier-only pooled-Elo overall rating at the D-2 cutoff) - 1500; "
            "the offset is the negative of that gap"
        ),
    }


def offsets_by_year_rows(
    offset_by_year: Mapping[int, int], per_year_offsets: Mapping[int, Mapping[str, Any]], plan: Any
) -> list[dict[str, Any]]:
    """The receipt: each season's offset beside the horizon it was measured through."""
    return [
        {
            "season": year,
            "training_window_start": offset_window_start(year, plan).isoformat(),
            "offset_measured_through": f"{horizon}-12-31",
            "lower_tier_initial_offset": repr(
                per_year_offsets[horizon]["lower_tier_initial_offset"]
            ),
            "mean_gap": repr(per_year_offsets[horizon]["mean_first_tour_level_rating_gap"]),
            "players_measured": per_year_offsets[horizon]["players_measured"],
        }
        for year, horizon in sorted(offset_by_year.items())
    ]


# ------------------------------------------------------------------ the run


def replay_with(
    active_offset: float,
    *,
    multipliers: Mapping[str, float],
    targets: Sequence[Any],
    sources: Sequence[Any],
    ordered: Sequence[Mapping[str, str]],
    experience_rows: Sequence[Mapping[str, str]],
    lag_days: int,
    match_cap: int,
    title_cap: int,
) -> tuple[list[dict[str, Any]], TierPooledElo, dict[str, float], list[dict[str, Any]]]:
    """One complete D-2 replay of the panel at one initial-rating offset.

    Per-training-window mode calls this once per chronological training boundary,
    because the offset is a property of the *replay* -- ``note_debut`` fixes a player's
    initial rating at his first state-updating row and every later state carries it --
    and not something a row can be re-scaled by afterwards.
    """
    engine = make_engine(multipliers, active_offset)
    experience = Experience(experience_rows)
    emitted: list[dict[str, Any]] = []
    differences: list[dict[str, Any]] = []
    worst = {"overall": 0.0, "surface": 0.0}
    for prediction, row in zip(
        elo.replay(targets, lag_days=lag_days, sources=sources, engine=engine),
        ordered,
        strict=True,
    ):
        target_date = dt.date.fromisoformat(row["date"])
        cutoff = target_date - dt.timedelta(days=lag_days)
        if prediction.eligible_through != cutoff:
            raise TierEloError(f"D-{lag_days} cutoff violated at {row['match_id']}")
        experience.advance_to(cutoff)
        players = {
            "a": int(min(int(row["winner_id"]), int(row["loser_id"]))),
            "b": int(max(int(row["winner_id"]), int(row["loser_id"]))),
        }
        record: dict[str, Any] = {
            "match_id": row["match_id"],
            "match_date": row["date"],
            "surface": row["surface"],
            "player_a": players["a"],
            "player_b": players["b"],
            "tier_elo_overall_logit": repr(float(prediction.elo_overall_logit)),
            "tier_elo_surface_logit": repr(float(prediction.elo_surface_logit)),
            "tier_history_absent_overall_a": prediction.history_absent_overall_a,
            "tier_history_absent_overall_b": prediction.history_absent_overall_b,
            "tier_history_absent_surface_a": prediction.history_absent_surface_a,
            "tier_history_absent_surface_b": prediction.history_absent_surface_b,
            "elo_overall_logit_base": row["elo_overall_logit"],
            "elo_surface_logit_base": row["elo_surface_logit"],
        }
        for side in ("a", "b"):
            player = players[side]
            raw_matches = experience.matches[player]
            raw_titles = experience.titles[player]
            last = experience.last_date.get(player)
            key = elo.player_key(str(player), "")
            record[f"tier_prior_matches_{side}"] = min(raw_matches, match_cap)
            record[f"tier_prior_titles_{side}"] = min(raw_titles, title_cap)
            record[f"tier_prior_matches_raw_{side}"] = raw_matches
            record[f"tier_prior_titles_raw_{side}"] = raw_titles
            record[f"tier_first_tier_{side}"] = engine.debut_tier.get(key, "")
            record[f"tier_initial_offset_applied_{side}"] = int(
                engine.debut_tier.get(key, "tour") != "tour"
            )
            record[f"tier_last_lower_match_days_{side}"] = (
                "" if last is None else (target_date - last).days
            )
        emitted.append(record)
        overall_difference = abs(
            float(prediction.elo_overall_logit) - float(row["elo_overall_logit"])
        )
        surface_difference = abs(
            float(prediction.elo_surface_logit) - float(row["elo_surface_logit"])
        )
        worst["overall"] = max(worst["overall"], overall_difference)
        worst["surface"] = max(worst["surface"], surface_difference)
        if max(overall_difference, surface_difference) > 0.0 and len(differences) < 20:
            differences.append(
                {
                    "match_id": row["match_id"],
                    "match_date": row["date"],
                    "overall": overall_difference,
                    "surface": surface_difference,
                }
            )
    if experience.cursor > len(experience.rows):
        raise TierEloError("experience cursor overran its stream")
    return emitted, engine, worst, differences


def run(
    config: Mapping[str, Any],
    *,
    include_lower_tier: bool | None = None,
    measure_only: bool = False,
) -> dict[str, Any]:
    section = config.get("tier_elo")
    if not isinstance(section, dict):
        raise TierEloError("configuration has no tier_elo object")
    plan = year_plan(config)
    parameters = dict(DEFAULT_PARAMETERS)
    parameters.update(section.get("parameters", {}))
    multipliers = dict(parameters["k_multipliers"])
    if multipliers != DECLARED_MULTIPLIERS:
        raise TierEloError(
            f"K multipliers are declared at freeze: {DECLARED_MULTIPLIERS}, refusing {multipliers}"
        )
    lag_days = int(parameters["lag_calendar_days"])
    match_cap = int(parameters["prior_match_cap"])
    title_cap = int(parameters["prior_title_cap"])
    if (match_cap, title_cap) != (300, 20):
        raise TierEloError("TIER01 fixes the experience caps at 300 matches and 20 titles")
    if include_lower_tier is None:
        include_lower_tier = bool(section.get("include_lower_tier", True))

    declared_binding = dict(section.get("elo_engine") or {})
    paths = {}
    hashes = {}
    for name in ("features", "labels", "tier_results"):
        entry = section[name]
        paths[name] = resolve_under_root(entry["path"], label=name)
        hashes[name] = require_hash(paths[name], entry.get("sha256") or None, label=name)

    tour = tour_rows(
        paths["features"], paths["labels"], hashes["labels"], year_ceiling=plan.panel_end_year
    )
    elo_lower, experience_rows = lower_rows(
        paths["tier_results"],
        elo_start_year=int(parameters["elo_start_year"]),
        experience_start_year=int(parameters["experience_start_year"]),
        panel_end_year=plan.panel_end_year,
    )
    if not include_lower_tier:
        elo_lower, experience_rows = [], []

    offset_mode = str(parameters["offset_mode"])
    if offset_mode not in OFFSET_MODES:
        raise TierEloError(f"offset_mode must be one of {sorted(OFFSET_MODES)}")
    offset_by_year: dict[int, int] = {}
    per_year_offsets: dict[int, dict[str, Any]] = {}
    measurement = None
    offset = 0.0
    if include_lower_tier:
        if offset_mode == "single":
            # The measurement mirrors the replay's own state construction, so it reads the
            # Elo-eligible lower-tier stream (2005+), not the longer experience stream.
            measurement = measure_offset(
                tour,
                elo_lower,
                multipliers=multipliers,
                lag_days=lag_days,
                end_year=int(parameters["offset_measurement_end_year"]),
            )
            declared = parameters.get("lower_tier_initial_offset")
            if measure_only:
                return {"offset_measurement": measurement, "declared": declared}
            if declared is None:
                raise TierEloError(
                    "lower_tier_initial_offset is not declared; run --measure-offset first "
                    "and write the value into the configuration"
                )
            offset = float(declared)
            if abs(offset - measurement["lower_tier_initial_offset"]) > 1e-6:
                raise TierEloError(
                    f"declared initial-rating offset {offset} differs from the pre-"
                    f"{parameters['offset_measurement_end_year']} measurement "
                    f"{measurement['lower_tier_initial_offset']}"
                )
        else:
            offset_by_year = {
                year: offset_year_horizon(year, plan)
                for year in range(int(parameters["elo_start_year"]), plan.panel_end_year + 1)
            }
            for horizon in sorted(set(offset_by_year.values())):
                per_year_offsets[horizon] = measure_offset(
                    tour,
                    elo_lower,
                    multipliers=multipliers,
                    lag_days=lag_days,
                    end_year=horizon,
                    allow_empty=True,
                )
            declared_by_year = parameters.get("lower_tier_initial_offset_by_year") or {}
            if measure_only:
                return {
                    "offset_mode": offset_mode,
                    "offset_horizon_by_year": {
                        str(k): v for k, v in sorted(offset_by_year.items())
                    },
                    "offset_measurement_by_horizon": {
                        str(k): v for k, v in sorted(per_year_offsets.items())
                    },
                    "declared": declared_by_year,
                }
            if not declared_by_year:
                raise TierEloError(
                    "lower_tier_initial_offset_by_year is not declared; run "
                    "--measure-offset first and write the values into the configuration"
                )
            for year, horizon in sorted(offset_by_year.items()):
                measured = per_year_offsets[horizon]["lower_tier_initial_offset"]
                if str(year) not in declared_by_year:
                    raise TierEloError(f"no declared initial-rating offset for year {year}")
                if abs(float(declared_by_year[str(year)]) - measured) > 1e-6:
                    raise TierEloError(
                        f"declared initial-rating offset for {year} "
                        f"{declared_by_year[str(year)]} differs from the measurement "
                        f"{measured} taken strictly before "
                        f"{offset_window_start(year, plan).isoformat()}"
                    )
            offset = float(
                per_year_offsets[offset_by_year[plan.panel_end_year]]["lower_tier_initial_offset"]
            )
    elif measure_only:
        raise TierEloError("--measure-offset needs the lower-tier stream")
    else:
        offset_mode = "single"

    targets = elo.parse_results(tour)
    sources = elo.parse_results(
        [row for row in tour if row["identity_tier"] == "primary"] + list(elo_lower)
    )
    ordered = sorted(tour, key=lambda item: (item["date"], item["match_id"]))
    replay_arguments = {
        "multipliers": multipliers,
        "targets": targets,
        "sources": sources,
        "ordered": ordered,
        "experience_rows": experience_rows,
        "lag_days": lag_days,
        "match_cap": match_cap,
        "title_cap": title_cap,
    }

    # In `per_training_window` mode the offset is re-measured inside every chronological
    # training boundary and the panel is replayed once per distinct boundary; a row dated
    # in year Y takes the replay whose offset was measured strictly before the start of
    # Y's training window. In `single` mode one offset serves every year.
    differences: list[dict[str, Any]] = []
    worst = {"overall": 0.0, "surface": 0.0}
    if offset_mode == "single":
        emitted, engine, worst, differences = replay_with(offset, **replay_arguments)
        engines: dict[Any, TierPooledElo] = {None: engine}
    else:
        emitted_by_id: dict[str, dict[str, Any]] = {}
        engines = {}
        for horizon in sorted(set(offset_by_year.values())):
            years = {year for year, value in offset_by_year.items() if value == horizon}
            active = float(per_year_offsets[horizon]["lower_tier_initial_offset"])
            rows, engine, this_worst, these_differences = replay_with(active, **replay_arguments)
            engines[horizon] = engine
            worst["overall"] = max(worst["overall"], this_worst["overall"])
            worst["surface"] = max(worst["surface"], this_worst["surface"])
            if not differences:
                differences = these_differences
            for record in rows:
                if int(str(record["match_date"])[:4]) in years:
                    emitted_by_id[str(record["match_id"])] = record
        emitted = [emitted_by_id[row["match_id"]] for row in ordered]
        engine = engines[sorted(engines)[-1]]

    if len(emitted) != len({row["match_id"] for row in tour}):
        raise TierEloError("emitted rows differ from the panel row count")

    output_dir = resolve_under_root(section["output_dir"], label="output_dir")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise TierEloError(f"refusing to overwrite a nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "tier_elo_features.csv": atomic_csv(
            output_dir / "tier_elo_features.csv", FEATURE_FIELDS, emitted
        )
    }

    coverage: dict[int, Counter[str]] = defaultdict(Counter)
    for record in emitted:
        bucket = coverage[int(str(record["match_date"])[:4])]
        bucket["rows"] += 1
        bucket["any_side_lower_history"] += int(
            any(record[f"tier_prior_matches_raw_{side}"] > 0 for side in ("a", "b"))
        )
        bucket["both_sides_lower_history"] += int(
            all(record[f"tier_prior_matches_raw_{side}"] > 0 for side in ("a", "b"))
        )
        bucket["any_side_lower_title"] += int(
            any(record[f"tier_prior_titles_raw_{side}"] > 0 for side in ("a", "b"))
        )
        bucket["any_side_offset_applied"] += int(
            any(record[f"tier_initial_offset_applied_{side}"] == 1 for side in ("a", "b"))
        )
    coverage_fields = (
        "season",
        "rows",
        "any_side_lower_history",
        "both_sides_lower_history",
        "any_side_lower_title",
        "any_side_offset_applied",
    )
    outputs["tier_elo_coverage_by_year.csv"] = atomic_csv(
        output_dir / "tier_elo_coverage_by_year.csv",
        coverage_fields,
        [
            {"season": year, **{name: coverage[year][name] for name in coverage_fields[1:]}}
            for year in sorted(coverage)
        ],
    )
    if offset_by_year:
        outputs["tier_offsets_by_year.csv"] = atomic_csv(
            output_dir / "tier_offsets_by_year.csv",
            OFFSET_FIELDS,
            offsets_by_year_rows(offset_by_year, per_year_offsets, plan),
        )

    summary = {
        "id": "TIER01-tier-elo",
        "status": "complete",
        "artifact_kind": "tier_inclusive_pooled_elo_and_experience_counts_no_fit_no_score",
        "include_lower_tier": include_lower_tier,
        "year_plan": plan.as_document(),
        "parameters": {
            **parameters,
            "lower_tier_initial_offset": offset,
            "offset_mode": offset_mode,
        },
        "offset_measurement": measurement,
        "offset_by_training_window": {
            "mode": offset_mode,
            "basis": (
                "each raw model year's offset is measured on lower-tier results and "
                "first-tour arrivals strictly before the start of that year's training "
                "window, max(history_floor_year, year - training_window_years)-01-01, "
                "and never later (astra_review_2026-09-12 finding 4)"
            ),
            "horizon_by_year": {str(k): v for k, v in sorted(offset_by_year.items())},
            "offset_by_horizon": {
                str(k): v["lower_tier_initial_offset"] for k, v in sorted(per_year_offsets.items())
            },
            "players_by_horizon": {
                str(k): v["players_measured"] for k, v in sorted(per_year_offsets.items())
            },
            "replays": len(engines),
        },
        "inputs": {
            name: {"path": relative_to_root(paths[name], label=name), "sha256": hashes[name]}
            for name in paths
        },
        "code": {
            "tier_elo": code_receipt(__name__),
            "elo_engine": code_receipt(elo.__name__),
            "declared_binding": declared_binding,
        },
        "outcome_reads": [
            {"purpose": ELO_STATE_PURPOSE, "rows": len(tour), "year_ceiling": plan.panel_end_year}
        ],
        "stream": {
            "tour_target_rows": len(targets),
            "tour_source_rows": sum(1 for row in tour if row["identity_tier"] == "primary"),
            "lower_tier_elo_rows": len(elo_lower),
            "lower_tier_experience_rows": len(experience_rows),
            "source_rows_applied": engine.applied_rows,
            "source_rows_applied_by_tier": dict(sorted(engine.applied_rows_by_tier.items())),
            "players_with_a_lower_tier_debut": sum(
                1 for tier in engine.debut_tier.values() if tier != "tour"
            ),
        },
        "regression_against_multi01_elo": {
            "rows_compared": len(emitted),
            "max_abs_diff_elo_overall_logit": worst["overall"],
            "max_abs_diff_elo_surface_logit": worst["surface"],
            "exact": worst["overall"] == 0.0 and worst["surface"] == 0.0,
            "examples": differences,
            "note": (
                "exact equality is the contract only with include_lower_tier=false; with "
                "the lower-tier stream in, a nonzero difference is the experiment"
            ),
        },
        "outputs": outputs,
        "limits": [
            "The K multipliers are declared, not selected; a later frozen study may "
            "select them on pre-2017 data only.",
            "The initial-rating offset is one number for every lower tier and every era.",
            "Lower-tier rows carry an event-anchor date shifted by tier_stream's declared "
            "offset, not a match clock, so within-event ordering is not represented.",
        ],
    }
    outputs["summary.json"] = atomic_json(output_dir / "summary.json", summary)
    summary["outputs"] = outputs
    return summary


def dry_run(config: Mapping[str, Any]) -> dict[str, Any]:
    plan = year_plan(config)
    section = config["tier_elo"]
    for name in ("features", "labels", "tier_results"):
        entry = section[name]
        path = resolve_under_root(entry["path"], label=name)
        require_hash(path, entry.get("sha256") or None, label=name)
    return {"status": "dry_run_ok", "year_plan": plan.as_document()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--measure-offset",
        action="store_true",
        help="print the initial-rating measurement and stop",
    )
    parser.add_argument(
        "--without-lower-tier",
        action="store_true",
        help="the regression: replay the tour stream alone",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    config = read_config(args.config)
    if args.output_dir is not None:
        config["tier_elo"]["output_dir"] = str(args.output_dir)
    if args.dry_run:
        print(json.dumps(dry_run(config), sort_keys=True))
        return 0
    if args.measure_offset:
        print(json.dumps(run(config, measure_only=True), indent=2, sort_keys=True))
        return 0
    summary = run(config, include_lower_tier=False if args.without_lower_tier else None)
    regression = summary["regression_against_multi01_elo"]
    print(
        json.dumps(
            {
                "include_lower_tier": summary["include_lower_tier"],
                "rows": regression["rows_compared"],
                "max_abs_diff_overall": regression["max_abs_diff_elo_overall_logit"],
                "max_abs_diff_surface": regression["max_abs_diff_elo_surface_logit"],
                "lower_tier_initial_offset": summary["parameters"]["lower_tier_initial_offset"],
                "source_rows_applied_by_tier": summary["stream"]["source_rows_applied_by_tier"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
