"""Build hash-pinned prequential features without fitting models, for either tour.

Stage ``features``. Ported from the archive's ``WTA02_models/build_features.py``, which is
the ``TIER01_models`` revision plus one line in ``CountHistory.player_summary``: the
assertion that a player's serve and return count history always arrive together is
replaced by a per-domain divergence counter, and ``missing_{domain}`` becomes
``serve_den == 0 and return_den == 0``. A match in which one side serves zero points gives
that side a return observation and no serve observation; four such rows exist in the
frozen ATP panel and four in the WTA panel, and on the ATP side the two expressions agree
on every summary call, so every ATP feature value is bit-identical. The rate formulas
already fall back to the surface or population prior on a zero denominator, so nothing was
protecting a computation. Divergences are counted per domain and reported in
``summary.json``, never silently absorbed.

Every feature definition, parameter default and other validation is unchanged. The
accepted season range comes from the configuration (``source_year_min`` /
``source_year_max``); the cutoff is ``lag_calendar_days`` (D-2) and is fixed.

What changed in the port: the divergence counter is threaded through
:class:`CountHistory` instead of living in a module global; ``ROOT``-relative path
resolution and the ``OUTPUT_ROOT = ROOT / "work"`` containment check are replaced by
``resolve_under_root`` (output must lie under the workspace); the ranking lookup is
imported by name from :mod:`tennislab.chronology.ranking_lookup` rather than loaded from
``work/`` through ``sys.path``, with the config's ``ranking_lookup_module`` binding read
and recorded as ``declared_binding``; the label writer is the separate
:func:`write_labels`; ``executed_builder`` becomes the package code receipt.

Building rows for a season means reading that season's winner/loser fields. With
``source_year_max >= 2025`` this stage is the outcome-access event for the reserved window
and must be logged as such before it runs.

The stream uses only primary-identity history dated at most D-2. Primary and provisional
targets are evaluated from the same states; provisional rows never update those states.
Labels and target status remain in a separate CSV, ``labels.csv``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import shutil
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    code_receipt,
    read_config,
    relative_to_root,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
)
from tennislab.chronology.ranking_lookup import LookupRequest, RankingLookup

__all__ = [
    "CountHistory",
    "Counts",
    "EloHistory",
    "Record",
    "WorkloadHistory",
    "build",
    "build_feature_row",
    "column_dictionary",
    "context_values",
    "feature_header",
    "label_row",
    "linear_interactions",
    "main",
    "rank_global_interactions",
    "replace",
    "stream_rows",
    "write_labels",
]

SURFACES = ("Hard", "Clay", "Grass", "Carpet")
PRIMARY_TIER = "primary"
BINARY_CONTEXTS = (
    "context_clay",
    "context_grass",
    "context_carpet",
    "context_best_of_5",
    "context_indoor",
    "context_indoor_unknown",
)
SIGNED_BASES = (
    "elo_overall_logit",
    "elo_surface_logit",
    "serve_overall_diff",
    "return_overall_diff",
    "serve_surface_diff",
    "return_surface_diff",
    "log_serve_volume_overall_diff",
    "log_serve_volume_surface_diff",
    "count_missing_overall_diff",
    "count_missing_surface_diff",
    "rank_points_log_diff",
    "rank_strength_diff",
    "rank_missing_diff",
    "rank_points_missing_diff",
    "matches_7d_diff",
    "matches_28d_diff",
    "log_points_7d_diff",
    "log_points_28d_diff",
    "points_missing_7d_diff",
    "points_missing_28d_diff",
    "rest_days_diff",
    "rest_unseen_diff",
)
RANK_BASES = (
    "rank_points_log_diff",
    "rank_strength_diff",
    "rank_missing_diff",
    "rank_points_missing_diff",
)
RANK_GLOBAL_CONTEXTS = ("ranking_global_age_days", "ranking_global_stale")
IDENTIFIER_COLUMNS = (
    "match_id",
    "calendar_year",
    "source_season",
    "match_date",
    "eligible_through_date",
    "tourney_id",
    "tourney_name",
    "tourney_level",
    "competition_type",
    "round",
    "surface",
    "best_of",
    "player_a",
    "player_b",
    "primary_target",
    "identity_tier",
)
MARKET_COLUMNS = (
    "ps_probability_a",
    "ps_logit_a",
    "ps_missing",
    "lagged_market_elo_overall_logit",
    "lagged_market_elo_surface_logit",
)
AUDIT_COLUMNS = (
    "date_basis",
    "archive_date_basis",
    "source_field_agreement",
    "court_recorded",
    "ranking_snapshot_date",
    "ranking_global_age_days",
    "ranking_global_stale",
    "rank_a",
    "rank_b",
    "rank_points_a",
    "rank_points_b",
    "rank_missing_a",
    "rank_missing_b",
    "rank_points_missing_a",
    "rank_points_missing_b",
    "ranking_snapshot_missing",
    "ranking_player_missing_a",
    "ranking_player_missing_b",
    "ranking_unknown_player_a",
    "ranking_unknown_player_b",
    "ranking_ambiguous_a",
    "ranking_ambiguous_b",
    "ranking_duplicate_status_a",
    "ranking_duplicate_status_b",
    "ranking_missing_reason_a",
    "ranking_missing_reason_b",
    "ranking_source_locators_a",
    "ranking_source_locators_b",
    "elo_history_absent_overall_a",
    "elo_history_absent_overall_b",
    "elo_history_absent_surface_a",
    "elo_history_absent_surface_b",
    "count_denominator_overall_a",
    "count_denominator_overall_b",
    "count_denominator_surface_a",
    "count_denominator_surface_b",
    "matches_7d_a",
    "matches_7d_b",
    "matches_28d_a",
    "matches_28d_b",
    "points_7d_a",
    "points_7d_b",
    "points_28d_a",
    "points_28d_b",
    "points_missing_7d_a",
    "points_missing_7d_b",
    "points_missing_28d_a",
    "points_missing_28d_b",
    "rest_days_a",
    "rest_days_b",
    "rest_unseen_a",
    "rest_unseen_b",
    "lagged_market_history_absent_overall_a",
    "lagged_market_history_absent_overall_b",
    "lagged_market_history_absent_surface_a",
    "lagged_market_history_absent_surface_b",
    "elo_latest_source_date",
    "count_latest_source_date",
    "workload_latest_source_date",
    "lagged_market_latest_source_date",
)

#: The barrier-protected label file: identity and chronology keys plus the outcome.
LABEL_HEADER = (
    "match_id",
    "calendar_year",
    "source_season",
    "match_date",
    "tourney_id",
    "identity_tier",
    "primary_target",
    "a_won",
    "status",
    "source_field_agreement",
)


def parse_bool(value: str, field: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ChainError(f"{field} must be exactly true or false: {value!r}")


def parse_positive_int(value: str, field: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ChainError(f"{field} must be a positive integer: {value!r}") from exc
    if parsed <= 0 or str(parsed) != value:
        raise ChainError(f"{field} must be a canonical positive integer: {value!r}")
    return parsed


def parse_nonnegative_int(value: str, field: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ChainError(f"{field} must be a nonnegative integer: {value!r}") from exc
    if parsed < 0 or str(parsed) != value:
        raise ChainError(f"{field} must be a canonical nonnegative integer: {value!r}")
    return parsed


def logit(probability: float) -> float:
    return math.log(probability / (1.0 - probability))


def encode(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ChainError(f"non-finite output value: {value}")
        return repr(value)
    return value


@dataclass(frozen=True)
class Counts:
    ace: int
    double_faults: int
    serve_points: int
    first_in: int
    first_won: int
    second_won: int
    break_points_saved: int
    break_points_faced: int

    @classmethod
    def from_row(cls, row: Mapping[str, str], side: str) -> Counts:
        names = {
            "ace": f"{side}_ace",
            "double_faults": f"{side}_df",
            "serve_points": f"{side}_svpt",
            "first_in": f"{side}_1stIn",
            "first_won": f"{side}_1stWon",
            "second_won": f"{side}_2ndWon",
            "break_points_saved": f"{side}_bpSaved",
            "break_points_faced": f"{side}_bpFaced",
        }
        values = {name: parse_nonnegative_int(row[field], field) for name, field in names.items()}
        counts = cls(**values)
        counts.validate()
        return counts

    @property
    def second_serve_points(self) -> int:
        return self.serve_points - self.first_in

    @property
    def service_points_won(self) -> int:
        return self.first_won + self.second_won

    def validate(self) -> None:
        if self.first_in > self.serve_points:
            raise ChainError("first serves in exceed service points")
        if self.first_won > self.first_in:
            raise ChainError("first-serve wins exceed first serves in")
        if self.second_won > self.second_serve_points:
            raise ChainError("second-serve wins exceed second-serve points")
        if self.double_faults > self.second_serve_points:
            raise ChainError("double faults exceed second-serve points")
        if self.second_won + self.double_faults > self.second_serve_points:
            raise ChainError(
                "joint second-serve wins plus double faults exceed second-serve points"
            )
        if self.service_points_won > self.serve_points:
            raise ChainError("service points won exceed service points")
        if self.ace > self.service_points_won:
            raise ChainError("aces exceed total service points won")
        if self.break_points_saved > self.break_points_faced:
            raise ChainError("break points saved exceed break points faced")


@dataclass(frozen=True)
class Record:
    match_id: str
    match_date: dt.date
    calendar_year: int
    source_season: int
    tourney_id: str
    tourney_name: str
    tourney_level: str
    competition_type: str
    round: str
    surface: str
    best_of: int
    court_recorded: str
    player_a: int
    player_b: int
    # None is an unresolved outcome: a target whose result is not yet known. Such a
    # row is a target like any other and never updates the result Elo state.
    a_won: bool | None
    identity_tier: str
    status: str
    date_basis: str
    archive_date_basis: str
    source_field_agreement: bool
    counts_a: Counts | None
    counts_b: Counts | None
    ps_probability_a: float | None

    def order_key(self) -> tuple[dt.date, str]:
        return self.match_date, self.match_id


def parse_record(
    row: Mapping[str, str], source_year_min: int, source_year_max: int
) -> tuple[Record | None, str | None]:
    reason: str | None = None
    if row["played"] != "true":
        reason = "played_not_true"
    elif row["walkover"] != "false":
        reason = "walkover"
    elif row["abandoned"] != "false":
        reason = "abandoned"
    elif row["status"] not in {"completed", "retired", "default"}:
        reason = "unrecognized_or_unresolved_status"
    elif row["identity_tier"] not in {"primary", "provisional"}:
        reason = "unrecognized_identity_tier"
    if reason:
        return None, reason

    match_date = dt.date.fromisoformat(row["match_date"])
    source_season = parse_positive_int(row["source_season"], "source_season")
    if source_season < source_year_min or source_season > source_year_max:
        return None, f"source_season_outside_{source_year_min}_{source_year_max}"
    player_a = parse_positive_int(row["player_a"], "player_a")
    player_b = parse_positive_int(row["player_b"], "player_b")
    if row["a_entity_id"] != row["player_a"] or row["b_entity_id"] != row["player_b"]:
        raise ChainError(f"entity/player ID mismatch for {row['match_id']}")
    if player_a >= player_b:
        raise ChainError(f"neutral orientation failed for {row['match_id']}")
    if row["surface"] not in SURFACES:
        raise ChainError(f"unsupported surface for {row['match_id']}: {row['surface']!r}")
    best_of = parse_positive_int(row["best_of"], "best_of")
    if best_of not in {3, 5}:
        raise ChainError(f"unsupported best_of for {row['match_id']}: {best_of}")
    if row["court_recorded"] not in {"Indoor", "Outdoor", ""}:
        raise ChainError(
            f"unsupported court_recorded for {row['match_id']}: {row['court_recorded']!r}"
        )

    counts_a = counts_b = None
    if row["count_block_status"] == "usable":
        try:
            counts_a = Counts.from_row(row, "a")
            counts_b = Counts.from_row(row, "b")
        except ValueError as exc:
            raise ChainError(f"usable count block invalid for {row['match_id']}: {exc}") from exc

    ps_probability_a = None
    ps_valid = parse_bool(row["PS_valid"], "PS_valid")
    if ps_valid:
        try:
            decimal_a = float(row["PS_decimal_a"])
            decimal_b = float(row["PS_decimal_b"])
        except ValueError as exc:
            raise ChainError(f"valid PS row has nonnumeric decimals for {row['match_id']}") from exc
        if not (
            math.isfinite(decimal_a)
            and math.isfinite(decimal_b)
            and decimal_a > 1.0
            and decimal_b > 1.0
        ):
            raise ChainError(f"valid PS row has invalid decimals for {row['match_id']}")
        reciprocal_a, reciprocal_b = 1.0 / decimal_a, 1.0 / decimal_b
        ps_probability_a = reciprocal_a / (reciprocal_a + reciprocal_b)

    return Record(
        match_id=row["match_id"],
        match_date=match_date,
        calendar_year=match_date.year,
        source_season=source_season,
        tourney_id=row["tourney_id"],
        tourney_name=row["tourney_name"],
        tourney_level=row["tourney_level"],
        competition_type=row["competition_type"],
        round=row["round"],
        surface=row["surface"],
        best_of=best_of,
        court_recorded=row["court_recorded"],
        player_a=player_a,
        player_b=player_b,
        # outcome-history read: the panel's a_won is carried into the label file only.
        # A blank is an outcome not yet known (a prospective target), never a value.
        a_won=None if row["a_won"] == "" else parse_bool(row["a_won"], "a_won"),
        identity_tier=row["identity_tier"],
        status=row["status"],
        date_basis=row["date_basis"],
        archive_date_basis=row["archive_date_basis"],
        source_field_agreement=parse_bool(row["source_field_agreement"], "source_field_agreement"),
        counts_a=counts_a,
        counts_b=counts_b,
        ps_probability_a=ps_probability_a,
    ), None


REQUIRED_PANEL_FIELDS = {
    "match_id", "match_date", "source_season", "player_a", "player_b",
    "a_entity_id", "b_entity_id", "a_won", "identity_tier", "status",
    "played", "walkover", "abandoned", "surface", "best_of", "court_recorded",
    "count_block_status", "PS_valid", "PS_decimal_a", "PS_decimal_b",
    "date_basis", "archive_date_basis", "source_field_agreement", "tourney_id", "tourney_name",
    "tourney_level", "competition_type", "round",
    "a_ace", "a_df", "a_svpt", "a_1stIn", "a_1stWon", "a_2ndWon", "a_bpSaved", "a_bpFaced",
    "b_ace", "b_df", "b_svpt", "b_1stIn", "b_1stWon", "b_2ndWon", "b_bpSaved", "b_bpFaced",
}  # fmt: skip


def load_records(
    path: Path,
    expected_sha256: str,
    expected_rows: int,
    source_year_min: int,
    source_year_max: int,
) -> tuple[list[Record], list[dict[str, str]], list[str]]:
    observed = sha256(path)
    if observed != expected_sha256:
        raise ChainError(f"panel SHA-256 mismatch: expected {expected_sha256}, observed {observed}")
    records: list[Record] = []
    rejections: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        header = list(reader.fieldnames or ())
        missing = sorted(REQUIRED_PANEL_FIELDS - set(header))
        if missing:
            raise ChainError(f"panel header missing fields: {missing}")
        for source_row, row in enumerate(reader, 2):
            if None in row:
                raise ChainError(f"malformed panel row {source_row}")
            record, reason = parse_record(row, source_year_min, source_year_max)
            if reason:
                rejections.append(
                    {
                        "source_row": str(source_row),
                        "match_id": row.get("match_id", ""),
                        "reason": reason,
                    }
                )
            else:
                if record is None:
                    raise ChainError(f"accepted panel row {source_row} produced no record")
                records.append(record)
    if len(records) + len(rejections) != expected_rows:
        raise ChainError(
            f"panel row count mismatch: expected {expected_rows}, "
            f"observed {len(records) + len(rejections)}"
        )
    records.sort(key=Record.order_key)
    keys = [record.match_id for record in records]
    if len(set(keys)) != len(keys):
        duplicates = [key for key, count in Counter(keys).items() if count > 1]
        raise ChainError(f"duplicate target match IDs: {duplicates[:10]}")
    return records, rejections, header


class EloHistory:
    """Same frozen-batch Elo arithmetic as JOINT004, with explicit history audit."""

    def __init__(self, initial: float, k: float, scale: float):
        self.initial = initial
        self.k = k
        self.scale = scale
        self.overall: dict[int, float] = {}
        self.surface: dict[tuple[int, str], float] = {}
        self.overall_matches: Counter[int] = Counter()
        self.surface_matches: Counter[tuple[int, str]] = Counter()
        self.latest_source_date: dt.date | None = None

    def overall_rating(self, player: int) -> float:
        return self.overall.get(player, self.initial)

    def surface_rating(self, player: int, surface: str) -> float:
        return self.surface.get((player, surface), self.initial)

    def probability(self, rating_a: float, rating_b: float) -> float:
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / self.scale))

    def feature_logit(self, player_a: int, player_b: int, surface: str) -> tuple[float, float]:
        factor = math.log(10.0) / self.scale
        return (
            (self.overall_rating(player_a) - self.overall_rating(player_b)) * factor,
            (self.surface_rating(player_a, surface) - self.surface_rating(player_b, surface))
            * factor,
        )

    def history_absent(self, player: int, surface: str) -> tuple[int, int]:
        return (
            int(self.overall_matches[player] == 0),
            int(self.surface_matches[(player, surface)] == 0),
        )

    def apply_batch(self, batch: Iterable[Record], pseudo_outcome: bool = False) -> None:
        overall_deltas: dict[int, float] = defaultdict(float)
        surface_deltas: dict[tuple[int, str], float] = defaultdict(float)
        used: list[Record] = []
        for record in batch:
            # outcome-history read: past results update the state; no score is computed.
            # A row without a price (pseudo outcome) or without a resolved outcome
            # updates nothing.
            y_a: float | None
            if pseudo_outcome:
                y_a = record.ps_probability_a
            else:
                y_a = None if record.a_won is None else float(record.a_won)
            if y_a is None:
                continue
            p_overall = self.probability(
                self.overall_rating(record.player_a), self.overall_rating(record.player_b)
            )
            p_surface = self.probability(
                self.surface_rating(record.player_a, record.surface),
                self.surface_rating(record.player_b, record.surface),
            )
            overall_delta = self.k * (y_a - p_overall)
            surface_delta = self.k * (y_a - p_surface)
            overall_deltas[record.player_a] += overall_delta
            overall_deltas[record.player_b] -= overall_delta
            surface_deltas[(record.player_a, record.surface)] += surface_delta
            surface_deltas[(record.player_b, record.surface)] -= surface_delta
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
            if self.latest_source_date is None or record.match_date > self.latest_source_date:
                self.latest_source_date = record.match_date


class CountHistory:
    """Serve/return history adapted from JOINT004 with the joint count bound upstream."""

    def __init__(
        self,
        half_life_days: float,
        prior_units: float,
        initial_serve: float,
        initial_return: float,
        diverged: Counter[str] | None = None,
    ):
        self.half_life_days = half_life_days
        self.prior_units = prior_units
        self.initial = {"serve": initial_serve, "return": initial_return}
        self.current_date: dt.date | None = None
        self.player_overall: dict[int, dict[str, list[float]]] = {}
        self.player_surface: dict[tuple[int, str], dict[str, list[float]]] = {}
        self.population_overall = self._empty()
        self.population_surface: dict[str, dict[str, list[float]]] = {}
        self.latest_source_date: dt.date | None = None
        # Per-domain count of summary calls where a player had serve history without
        # return history, or the reverse. Reported in summary.json; zero on the ATP panel.
        self.diverged: Counter[str] = Counter() if diverged is None else diverged

    @staticmethod
    def _empty() -> dict[str, list[float]]:
        return {"serve": [0.0, 0.0], "return": [0.0, 0.0]}

    @staticmethod
    def _add(
        destination: dict[str, list[float]],
        observation: dict[str, tuple[float, float]],
        weight: float,
    ) -> None:
        for rate, (numerator, denominator) in observation.items():
            destination[rate][0] += numerator * weight
            destination[rate][1] += denominator * weight

    @staticmethod
    def _decay(rate_map: dict[str, list[float]], factor: float) -> None:
        for values in rate_map.values():
            values[0] *= factor
            values[1] *= factor

    def advance(self, target_date: dt.date) -> None:
        if self.current_date is None:
            self.current_date = target_date
            return
        days = (target_date - self.current_date).days
        if days < 0:
            raise ChainError("target dates must be nondecreasing")
        if days:
            factor = 2.0 ** (-days / self.half_life_days)
            for rate_map in self.player_overall.values():
                self._decay(rate_map, factor)
            for rate_map in self.player_surface.values():
                self._decay(rate_map, factor)
            self._decay(self.population_overall, factor)
            for rate_map in self.population_surface.values():
                self._decay(rate_map, factor)
        self.current_date = target_date

    def add_match(self, record: Record, target_date: dt.date) -> None:
        if self.current_date != target_date:
            raise ChainError("count history must be advanced to target date")
        if record.counts_a is None or record.counts_b is None:
            return
        age = (target_date - record.match_date).days
        if age < 0:
            raise ChainError("future count observation")
        weight = 2.0 ** (-age / self.half_life_days)
        a, b = record.counts_a, record.counts_b
        observations = (
            (
                record.player_a,
                {
                    "serve": (a.service_points_won, a.serve_points),
                    "return": (b.serve_points - b.service_points_won, b.serve_points),
                },
            ),
            (
                record.player_b,
                {
                    "serve": (b.service_points_won, b.serve_points),
                    "return": (a.serve_points - a.service_points_won, a.serve_points),
                },
            ),
        )
        population_surface = self.population_surface.setdefault(record.surface, self._empty())
        for player, observation in observations:
            overall = self.player_overall.setdefault(player, self._empty())
            surface = self.player_surface.setdefault((player, record.surface), self._empty())
            self._add(overall, observation, weight)
            self._add(surface, observation, weight)
            self._add(self.population_overall, observation, weight)
            self._add(population_surface, observation, weight)
        if self.latest_source_date is None or record.match_date > self.latest_source_date:
            self.latest_source_date = record.match_date

    def player_summary(self, player: int, surface: str) -> dict[str, float | int]:
        overall = self.player_overall.get(player, self._empty())
        target_surface = self.player_surface.get((player, surface), self._empty())
        population_surface = self.population_surface.get(surface, self._empty())
        output: dict[str, float | int] = {}
        for rate in ("serve", "return"):
            pop_num, pop_den = self.population_overall[rate]
            overall_prior = pop_num / pop_den if pop_den > 0.0 else self.initial[rate]
            surface_num, surface_den = population_surface[rate]
            surface_prior = surface_num / surface_den if surface_den > 0.0 else overall_prior
            for domain, rates, prior in (
                ("overall", overall, overall_prior),
                ("surface", target_surface, surface_prior),
            ):
                numerator, denominator = rates[rate]
                output[f"{rate}_{domain}"] = (numerator + self.prior_units * prior) / (
                    denominator + self.prior_units
                )
                output[f"{rate}_{domain}_denominator"] = denominator
        for domain, rates in (("overall", overall), ("surface", target_surface)):
            serve_den = rates["serve"][1]
            return_den = rates["return"][1]
            if (serve_den == 0.0) != (return_den == 0.0):
                # A match in which one side served zero points gives that side a return
                # observation and no serve observation. Counted, not absorbed; see the
                # module docstring. The flag below means "no count history at all in
                # this domain", and the rates already fall back to a prior per side.
                self.diverged[domain] += 1
            output[f"missing_{domain}"] = int(serve_den == 0.0 and return_den == 0.0)
        return output


class WorkloadHistory:
    def __init__(self) -> None:
        self.by_player: dict[int, list[tuple[dt.date, int | None]]] = defaultdict(list)
        self.latest_source_date: dt.date | None = None

    def add_match(self, record: Record) -> None:
        total_points = None
        if record.counts_a is not None and record.counts_b is not None:
            total_points = record.counts_a.serve_points + record.counts_b.serve_points
        self.by_player[record.player_a].append((record.match_date, total_points))
        self.by_player[record.player_b].append((record.match_date, total_points))
        if self.latest_source_date is None or record.match_date > self.latest_source_date:
            self.latest_source_date = record.match_date

    def summary(
        self, player: int, target_date: dt.date, windows: tuple[int, ...], rest_cap: int
    ) -> dict[str, int]:
        observations = self.by_player.get(player, [])
        output: dict[str, int] = {}
        if observations:
            days = (target_date - observations[-1][0]).days
            if days < 0:
                raise ChainError("future workload observation")
            output["rest_days"] = min(days, rest_cap)
            output["rest_unseen"] = 0
        else:
            output["rest_days"] = rest_cap
            output["rest_unseen"] = 1
        for window in windows:
            lower = target_date - dt.timedelta(days=window)
            recent = [(day, points) for day, points in observations if day >= lower]
            output[f"matches_{window}d"] = len(recent)
            output[f"points_{window}d"] = sum(points for _, points in recent if points is not None)
            output[f"points_missing_{window}d"] = int(any(points is None for _, points in recent))
        return output


def context_values(record: Record) -> dict[str, int]:
    return {
        "context_clay": int(record.surface == "Clay"),
        "context_grass": int(record.surface == "Grass"),
        "context_carpet": int(record.surface == "Carpet"),
        "context_best_of_5": int(record.best_of == 5),
        "context_indoor": int(record.court_recorded == "Indoor"),
        "context_indoor_unknown": int(record.court_recorded not in {"Indoor", "Outdoor"}),
    }


def locators_json(result: Any) -> str:
    return json.dumps(
        [
            {
                "source_member": row.source_member,
                "source_physical_line": row.source_physical_line,
            }
            for row in result.source_locators
        ],
        separators=(",", ":"),
        sort_keys=True,
    )


def build_feature_row(
    record: Record,
    cutoff: dt.date,
    sports_elo: EloHistory,
    counts: CountHistory,
    workload: WorkloadHistory,
    market_elo: EloHistory,
    rank_a: Any,
    rank_b: Any,
    windows: tuple[int, ...],
    rest_cap: int,
) -> dict[str, Any]:
    if (
        rank_a.snapshot_date != rank_b.snapshot_date
        or rank_a.snapshot_age_days != rank_b.snapshot_age_days
    ):
        raise ChainError("A/B ranking global edition mismatch")
    if rank_a.stale_over_14_days != rank_b.stale_over_14_days:
        raise ChainError("A/B ranking global stale flag mismatch")
    contexts = context_values(record)
    count_a = counts.player_summary(record.player_a, record.surface)
    count_b = counts.player_summary(record.player_b, record.surface)
    workload_a = workload.summary(record.player_a, record.match_date, windows, rest_cap)
    workload_b = workload.summary(record.player_b, record.match_date, windows, rest_cap)
    elo_overall, elo_surface = sports_elo.feature_logit(
        record.player_a, record.player_b, record.surface
    )
    market_overall, market_surface = market_elo.feature_logit(
        record.player_a, record.player_b, record.surface
    )
    elo_absent_a = sports_elo.history_absent(record.player_a, record.surface)
    elo_absent_b = sports_elo.history_absent(record.player_b, record.surface)
    market_absent_a = market_elo.history_absent(record.player_a, record.surface)
    market_absent_b = market_elo.history_absent(record.player_b, record.surface)

    def rank_points_value(result: Any) -> float:
        return math.log1p(result.ranking_points) if result.ranking_points is not None else 0.0

    def rank_strength(result: Any) -> float:
        return -math.log(result.rank) if result.rank is not None else 0.0

    base: dict[str, float | int] = {
        "elo_overall_logit": elo_overall,
        "elo_surface_logit": elo_surface,
        "serve_overall_diff": float(count_a["serve_overall"]) - float(count_b["serve_overall"]),
        "return_overall_diff": float(count_a["return_overall"]) - float(count_b["return_overall"]),
        "serve_surface_diff": float(count_a["serve_surface"]) - float(count_b["serve_surface"]),
        "return_surface_diff": float(count_a["return_surface"]) - float(count_b["return_surface"]),
        "log_serve_volume_overall_diff": math.log1p(float(count_a["serve_overall_denominator"]))
        - math.log1p(float(count_b["serve_overall_denominator"])),
        "log_serve_volume_surface_diff": math.log1p(float(count_a["serve_surface_denominator"]))
        - math.log1p(float(count_b["serve_surface_denominator"])),
        "count_missing_overall_diff": int(count_a["missing_overall"])
        - int(count_b["missing_overall"]),
        "count_missing_surface_diff": int(count_a["missing_surface"])
        - int(count_b["missing_surface"]),
        "rank_points_log_diff": rank_points_value(rank_a) - rank_points_value(rank_b),
        "rank_strength_diff": rank_strength(rank_a) - rank_strength(rank_b),
        "rank_missing_diff": int(rank_a.rank_missing) - int(rank_b.rank_missing),
        "rank_points_missing_diff": int(rank_a.points_missing) - int(rank_b.points_missing),
        "matches_7d_diff": workload_a["matches_7d"] - workload_b["matches_7d"],
        "matches_28d_diff": workload_a["matches_28d"] - workload_b["matches_28d"],
        "log_points_7d_diff": math.log1p(workload_a["points_7d"])
        - math.log1p(workload_b["points_7d"]),
        "log_points_28d_diff": math.log1p(workload_a["points_28d"])
        - math.log1p(workload_b["points_28d"]),
        "points_missing_7d_diff": workload_a["points_missing_7d"] - workload_b["points_missing_7d"],
        "points_missing_28d_diff": workload_a["points_missing_28d"]
        - workload_b["points_missing_28d"],
        "rest_days_diff": workload_a["rest_days"] - workload_b["rest_days"],
        "rest_unseen_diff": workload_a["rest_unseen"] - workload_b["rest_unseen"],
    }
    if tuple(base) != SIGNED_BASES:
        raise ChainError("signed base order drift")
    row: dict[str, Any] = {
        "match_id": record.match_id,
        "calendar_year": record.calendar_year,
        "source_season": record.source_season,
        "match_date": record.match_date.isoformat(),
        "eligible_through_date": cutoff.isoformat(),
        "tourney_id": record.tourney_id,
        "tourney_name": record.tourney_name,
        "tourney_level": record.tourney_level,
        "competition_type": record.competition_type,
        "round": record.round,
        "surface": record.surface,
        "best_of": record.best_of,
        "player_a": record.player_a,
        "player_b": record.player_b,
        "primary_target": int(record.identity_tier == PRIMARY_TIER),
        "identity_tier": record.identity_tier,
        **contexts,
        **base,
    }
    for feature in SIGNED_BASES:
        for context in BINARY_CONTEXTS:
            row[f"{feature}_x_{context}"] = float(base[feature]) * contexts[context]
    global_age = rank_a.snapshot_age_days
    if global_age is None:
        global_age = 0
    global_stale = int(rank_a.stale_over_14_days)
    for feature in RANK_BASES:
        row[f"{feature}_x_ranking_global_age_days"] = float(base[feature]) * global_age
        row[f"{feature}_x_ranking_global_stale"] = float(base[feature]) * global_stale

    row.update(
        {
            "ps_probability_a": record.ps_probability_a,
            "ps_logit_a": (
                logit(record.ps_probability_a) if record.ps_probability_a is not None else None
            ),
            "ps_missing": int(record.ps_probability_a is None),
            "lagged_market_elo_overall_logit": market_overall,
            "lagged_market_elo_surface_logit": market_surface,
            "date_basis": record.date_basis,
            "archive_date_basis": record.archive_date_basis,
            "source_field_agreement": int(record.source_field_agreement),
            "court_recorded": record.court_recorded,
            "ranking_snapshot_date": (
                rank_a.snapshot_date.isoformat() if rank_a.snapshot_date else ""
            ),
            "ranking_global_age_days": global_age,
            "ranking_global_stale": global_stale,
            "rank_a": rank_a.rank,
            "rank_b": rank_b.rank,
            "rank_points_a": rank_a.ranking_points,
            "rank_points_b": rank_b.ranking_points,
            "rank_missing_a": int(rank_a.rank_missing),
            "rank_missing_b": int(rank_b.rank_missing),
            "rank_points_missing_a": int(rank_a.points_missing),
            "rank_points_missing_b": int(rank_b.points_missing),
            "ranking_snapshot_missing": int(rank_a.snapshot_missing),
            "ranking_player_missing_a": int(rank_a.player_missing_on_snapshot),
            "ranking_player_missing_b": int(rank_b.player_missing_on_snapshot),
            "ranking_unknown_player_a": int(rank_a.unknown_player_id),
            "ranking_unknown_player_b": int(rank_b.unknown_player_id),
            "ranking_ambiguous_a": int(rank_a.ambiguous_duplicate),
            "ranking_ambiguous_b": int(rank_b.ambiguous_duplicate),
            "ranking_duplicate_status_a": rank_a.duplicate_status,
            "ranking_duplicate_status_b": rank_b.duplicate_status,
            "ranking_missing_reason_a": rank_a.missing_reason or "",
            "ranking_missing_reason_b": rank_b.missing_reason or "",
            "ranking_source_locators_a": locators_json(rank_a),
            "ranking_source_locators_b": locators_json(rank_b),
            "elo_history_absent_overall_a": elo_absent_a[0],
            "elo_history_absent_overall_b": elo_absent_b[0],
            "elo_history_absent_surface_a": elo_absent_a[1],
            "elo_history_absent_surface_b": elo_absent_b[1],
            "count_denominator_overall_a": count_a["serve_overall_denominator"],
            "count_denominator_overall_b": count_b["serve_overall_denominator"],
            "count_denominator_surface_a": count_a["serve_surface_denominator"],
            "count_denominator_surface_b": count_b["serve_surface_denominator"],
            "matches_7d_a": workload_a["matches_7d"],
            "matches_7d_b": workload_b["matches_7d"],
            "matches_28d_a": workload_a["matches_28d"],
            "matches_28d_b": workload_b["matches_28d"],
            "points_7d_a": workload_a["points_7d"],
            "points_7d_b": workload_b["points_7d"],
            "points_28d_a": workload_a["points_28d"],
            "points_28d_b": workload_b["points_28d"],
            "points_missing_7d_a": workload_a["points_missing_7d"],
            "points_missing_7d_b": workload_b["points_missing_7d"],
            "points_missing_28d_a": workload_a["points_missing_28d"],
            "points_missing_28d_b": workload_b["points_missing_28d"],
            "rest_days_a": workload_a["rest_days"],
            "rest_days_b": workload_b["rest_days"],
            "rest_unseen_a": workload_a["rest_unseen"],
            "rest_unseen_b": workload_b["rest_unseen"],
            "lagged_market_history_absent_overall_a": market_absent_a[0],
            "lagged_market_history_absent_overall_b": market_absent_b[0],
            "lagged_market_history_absent_surface_a": market_absent_a[1],
            "lagged_market_history_absent_surface_b": market_absent_b[1],
            "elo_latest_source_date": (
                sports_elo.latest_source_date.isoformat() if sports_elo.latest_source_date else ""
            ),
            "count_latest_source_date": (
                counts.latest_source_date.isoformat() if counts.latest_source_date else ""
            ),
            "workload_latest_source_date": (
                workload.latest_source_date.isoformat() if workload.latest_source_date else ""
            ),
            "lagged_market_latest_source_date": (
                market_elo.latest_source_date.isoformat() if market_elo.latest_source_date else ""
            ),
        }
    )
    for field in (
        "elo_latest_source_date",
        "count_latest_source_date",
        "workload_latest_source_date",
        "lagged_market_latest_source_date",
    ):
        if row[field] and dt.date.fromisoformat(row[field]) > cutoff:
            raise ChainError(f"{field} exceeds D-2 cutoff for {record.match_id}")
    return row


def linear_interactions() -> tuple[str, ...]:
    return tuple(
        f"{feature}_x_{context}" for feature in SIGNED_BASES for context in BINARY_CONTEXTS
    )


def rank_global_interactions() -> tuple[str, ...]:
    return tuple(
        f"{feature}_x_{context}" for feature in RANK_BASES for context in RANK_GLOBAL_CONTEXTS
    )


def feature_header() -> tuple[str, ...]:
    return (
        IDENTIFIER_COLUMNS
        + BINARY_CONTEXTS
        + SIGNED_BASES
        + linear_interactions()
        + rank_global_interactions()
        + MARKET_COLUMNS
        + AUDIT_COLUMNS
    )


def label_row(record: Record) -> dict[str, Any]:
    """One ``labels.csv`` row: identity and chronology keys plus the outcome."""
    return {
        "match_id": record.match_id,
        "calendar_year": record.calendar_year,
        "source_season": record.source_season,
        "match_date": record.match_date.isoformat(),
        "tourney_id": record.tourney_id,
        "identity_tier": record.identity_tier,
        "primary_target": int(record.identity_tier == PRIMARY_TIER),
        "a_won": None if record.a_won is None else int(record.a_won),
        "status": record.status,
        "source_field_agreement": int(record.source_field_agreement),
    }


def prepare_rankings(
    records: list[Record], config: Mapping[str, Any]
) -> dict[tuple[dt.date, int], Any]:
    lookup = RankingLookup.from_gzip(
        resolve_under_root(config["ranking_source"]["path"], label="ranking_source"),
        edition_index_path=resolve_under_root(
            config["ranking_index"]["path"], label="ranking_index"
        ),
        expected_source_sha256=config["ranking_source"]["sha256"],
    )
    unique = sorted(
        {
            (record.match_date, player)
            for record in records
            for player in (record.player_a, record.player_b)
        }
    )
    results = lookup.lookup_many([LookupRequest(day, player) for day, player in unique])
    return dict(zip(unique, results, strict=True))


def stream_rows(
    records: list[Record],
    ranking: Mapping[tuple[dt.date, int], Any],
    parameters: Mapping[str, Any],
    diverged: Counter[str] | None = None,
) -> Iterator[tuple[Record, dict[str, Any]]]:
    records = sorted(records, key=Record.order_key)
    if len({record.match_id for record in records}) != len(records):
        raise ChainError("duplicate record match IDs")
    lag = int(parameters["lag_calendar_days"])
    windows = tuple(int(value) for value in parameters["workload_windows_days"])
    rest_cap = int(parameters["rest_days_cap"])
    primary = [record for record in records if record.identity_tier == PRIMARY_TIER]
    sports_elo = EloHistory(
        float(parameters["elo_initial_rating"]),
        float(parameters["elo_k"]),
        float(parameters["elo_scale"]),
    )
    market_elo = EloHistory(
        float(parameters["elo_initial_rating"]),
        float(parameters["elo_k"]),
        float(parameters["elo_scale"]),
    )
    counts = CountHistory(
        float(parameters["count_half_life_days"]),
        float(parameters["count_prior_denominator_units"]),
        float(parameters["initial_serve_rate"]),
        float(parameters["initial_return_rate"]),
        diverged,
    )
    workload = WorkloadHistory()
    source_cursor = 0
    target_cursor = 0
    while target_cursor < len(records):
        target_date = records[target_cursor].match_date
        target_end = target_cursor + 1
        while target_end < len(records) and records[target_end].match_date == target_date:
            target_end += 1
        cutoff = target_date - dt.timedelta(days=lag)
        counts.advance(target_date)
        while source_cursor < len(primary) and primary[source_cursor].match_date <= cutoff:
            source_date = primary[source_cursor].match_date
            source_end = source_cursor + 1
            while source_end < len(primary) and primary[source_end].match_date == source_date:
                source_end += 1
            batch = primary[source_cursor:source_end]
            sports_elo.apply_batch(batch, pseudo_outcome=False)
            market_elo.apply_batch(batch, pseudo_outcome=True)
            for source in batch:
                counts.add_match(source, target_date)
                workload.add_match(source)
            source_cursor = source_end
        for record in records[target_cursor:target_end]:
            yield (
                record,
                build_feature_row(
                    record,
                    cutoff,
                    sports_elo,
                    counts,
                    workload,
                    market_elo,
                    ranking[(record.match_date, record.player_a)],
                    ranking[(record.match_date, record.player_b)],
                    windows,
                    rest_cap,
                ),
            )
        target_cursor = target_end


def column_dictionary() -> dict[str, Any]:
    interactions = linear_interactions()
    rank_interactions = rank_global_interactions()
    linear = SIGNED_BASES + interactions + rank_interactions
    return {
        "dictionary_id": "MULTI01-prequential-feature-interface-v1",
        "orientation": "player_a and player_b are exact integer IDs with player_a < player_b; every signed feature is A-minus-B; a_won is separate",
        "history_contract": "primary identity rows only; source match_date <= target D-2; source-date Elo batches frozen; provisional targets never update state",
        "chronology_limit": "match_date is the qualified annual reported date, not a clock. The known suspended 2022-7694/291 case completed one day after actual start; D-2 from its reported date remains conservative for that case, but there is no universal pre-start proof.",
        "count_contract": "180-day half-life; 50 denominator-unit eligible population prior; missing count blocks skip count/point-volume updates but retain result Elo and match workload updates",
        "ordered_feature_file_columns": list(feature_header()),
        "identifier_and_split_columns": list(IDENTIFIER_COLUMNS),
        "binary_context_columns": list(BINARY_CONTEXTS),
        "signed_base_model_features": list(SIGNED_BASES),
        "signed_context_interactions": list(interactions),
        "rank_global_age_stale_interactions": list(rank_interactions),
        "linear_sports_model_features": list(linear),
        "hgb_sports_model_features": list(SIGNED_BASES + BINARY_CONTEXTS + RANK_GLOBAL_CONTEXTS),
        "fixed_overall_elo_features": ["elo_overall_logit"],
        "overall_surface_elo_features": ["elo_overall_logit", "elo_surface_logit"],
        "serve_return_rate_features": [
            "serve_overall_diff",
            "return_overall_diff",
            "serve_surface_diff",
            "return_surface_diff",
        ],
        "serve_volume_features": [
            "log_serve_volume_overall_diff",
            "log_serve_volume_surface_diff",
        ],
        "count_missing_features": ["count_missing_overall_diff", "count_missing_surface_diff"],
        "ranking_features": list(RANK_BASES),
        "workload_and_rest_features": list(SIGNED_BASES[14:]),
        "player_deviation_key_columns": ["player_a", "player_b"],
        "player_surface_deviation_context_columns": [
            "surface",
            "context_clay",
            "context_grass",
            "context_carpet",
        ],
        "market_family_fields": list(MARKET_COLUMNS),
        "contemporaneous_pinnacle_fields": ["ps_probability_a", "ps_logit_a", "ps_missing"],
        "lagged_market_elo_features": [
            "lagged_market_elo_overall_logit",
            "lagged_market_elo_surface_logit",
        ],
        "market_semantics": {
            "ps_probability_a": "normalized A-side probability from the target match annual PS decimal pair; latest-preplay-reported proxy without an exact clock or historical issuance proof",
            "ps_logit_a": "logit of ps_probability_a; blank with ps_probability_a when PS is missing",
            "lagged_market_elo": "K=32 overall and target-surface states updated in frozen D-2 source-date batches with past normalized PS probability as a continuous pseudo-outcome; actual winner is never used",
        },
        "audit_only_columns": list(AUDIT_COLUMNS),
        "label_file_columns": list(LABEL_HEADER),
        "missingness": {
            "sports_model_columns": "all finite; missing rank/points represented by zero value plus signed missing indicators",
            "ps_probability_a_and_ps_logit_a": "blank only when ps_missing=1; soft-book decimal odds are absent from output",
            "ranking": "latest global D-2 edition only; no player-specific fallback; ambiguous duplicate is missing with audit flags",
            "unknown_court": "context_indoor=0 and context_indoor_unknown=1; never encoded as known outdoor",
        },
        "forbidden_from_sports_predictors": [
            "a_won",
            "status",
            "score",
            "target primitive counts",
            "PS/B365 decimal odds",
            "source result orientation",
        ],
    }


def write_csv_row(writer: csv.DictWriter, row: Mapping[str, Any], header: Iterable[str]) -> None:
    missing = [field for field in header if field not in row]
    extra = sorted(set(row) - set(header))
    if missing or extra:
        raise ChainError(f"output schema mismatch: missing={missing}, extra={extra}")
    writer.writerow({field: encode(row[field]) for field in header})


def write_csv_simple(path: Path, rows: list[Mapping[str, Any]], fields: Iterable[str]) -> None:
    fieldnames = tuple(fields)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            write_csv_row(writer, row, fieldnames)


def write_labels(path: Path, records: Iterable[Record]) -> None:
    """Write ``labels.csv``, the barrier-protected label file, in target order.

    Its columns are :data:`LABEL_HEADER`: ``match_id``, ``calendar_year``,
    ``source_season``, ``match_date``, ``tourney_id``, ``identity_tier``,
    ``primary_target``, ``a_won``, ``status``, ``source_field_agreement``. No feature or
    price field ever enters this file, and no feature file column ever carries ``a_won``
    or ``status``.
    """
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LABEL_HEADER, lineterminator="\n")
        writer.writeheader()
        for record in records:
            write_csv_row(writer, label_row(record), LABEL_HEADER)


def write_features(
    path: Path,
    records: list[Record],
    ranking: Mapping[tuple[dt.date, int], Any],
    parameters: Mapping[str, Any],
    diverged: Counter[str],
) -> tuple[list[Record], dict[str, Counter[Any]]]:
    """Write ``features.csv`` and return the targets in written order with their tallies."""
    feature_fields = feature_header()
    counts_summary: dict[str, Counter[Any]] = {
        "identity_tier": Counter(), "calendar_year": Counter(), "source_season": Counter(),
        "status": Counter(), "surface": Counter(), "ps_missing": Counter(),
        "rank_missing_a": Counter(), "rank_missing_b": Counter(),
    }  # fmt: skip
    written: list[Record] = []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=feature_fields, lineterminator="\n")
        writer.writeheader()
        for record, feature in stream_rows(records, ranking, parameters, diverged):
            write_csv_row(writer, feature, feature_fields)
            counts_summary["identity_tier"][record.identity_tier] += 1
            counts_summary["calendar_year"][record.calendar_year] += 1
            counts_summary["source_season"][record.source_season] += 1
            counts_summary["status"][record.status] += 1
            counts_summary["surface"][record.surface] += 1
            counts_summary["ps_missing"][feature["ps_missing"]] += 1
            counts_summary["rank_missing_a"][feature["rank_missing_a"]] += 1
            counts_summary["rank_missing_b"][feature["rank_missing_b"]] += 1
            written.append(record)
    return written, counts_summary


def validate_written_outputs(
    features_path: Path,
    labels_path: Path,
    records: list[Record],
    dictionary: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    lag_days = int(parameters["lag_calendar_days"])
    stale_days = int(parameters["ranking_stale_days"])
    feature_columns = list(dictionary["ordered_feature_file_columns"])
    model_columns = list(
        dict.fromkeys(
            dictionary["linear_sports_model_features"]
            + dictionary["hgb_sports_model_features"]
            + dictionary["lagged_market_elo_features"]
        )
    )
    forbidden = {
        "a_won", "status", "score", "PS_decimal_a", "PS_decimal_b",
        "B365_decimal_a", "B365_decimal_b",
    }  # fmt: skip
    if forbidden & set(feature_columns):
        raise ChainError(
            f"forbidden target/odds fields in features: {sorted(forbidden & set(feature_columns))}"
        )
    checks: Counter[str] = Counter()
    with (
        features_path.open(newline="", encoding="utf-8") as feature_stream,
        labels_path.open(newline="", encoding="utf-8") as label_stream,
    ):
        feature_reader = csv.DictReader(feature_stream)
        label_reader = csv.DictReader(label_stream)
        if feature_reader.fieldnames != feature_columns:
            raise ChainError("written feature header differs from dictionary")
        if label_reader.fieldnames != list(LABEL_HEADER):
            raise ChainError("written label header differs from dictionary")
        feature_rows = iter(feature_reader)
        label_rows = iter(label_reader)
        for record in records:
            feature = next(feature_rows, None)
            label = next(label_rows, None)
            if feature is None or label is None:
                raise ChainError("feature/label output ended early")
            if feature["match_id"] != record.match_id or label["match_id"] != record.match_id:
                raise ChainError("feature/label key order mismatch")
            cutoff = record.match_date - dt.timedelta(days=lag_days)
            if feature["eligible_through_date"] != cutoff.isoformat():
                raise ChainError(f"wrong cutoff for {record.match_id}")
            if not int(feature["player_a"]) < int(feature["player_b"]):
                raise ChainError(f"non-neutral output orientation for {record.match_id}")
            if int(feature["primary_target"]) != int(record.identity_tier == PRIMARY_TIER):
                raise ChainError(f"wrong primary flag for {record.match_id}")
            # outcome-history read: the written label is checked against the parsed row.
            expected_label = "" if record.a_won is None else str(int(record.a_won))
            if label["a_won"] != expected_label or label["status"] != record.status:
                raise ChainError(f"label mismatch for {record.match_id}")
            expected_context = context_values(record)
            for field, value in expected_context.items():
                if int(feature[field]) != value:
                    raise ChainError(f"wrong {field} for {record.match_id}")
            for field in model_columns:
                if not math.isfinite(float(feature[field])):
                    raise ChainError(f"non-finite model field {field} for {record.match_id}")
            for signed in SIGNED_BASES:
                base_value = float(feature[signed])
                for context in BINARY_CONTEXTS:
                    if float(feature[f"{signed}_x_{context}"]) != base_value * int(
                        feature[context]
                    ):
                        raise ChainError(f"interaction mismatch for {record.match_id}")
            for rank_feature in RANK_BASES:
                base_value = float(feature[rank_feature])
                for context in RANK_GLOBAL_CONTEXTS:
                    if float(feature[f"{rank_feature}_x_{context}"]) != base_value * float(
                        feature[context]
                    ):
                        raise ChainError(f"rank global interaction mismatch for {record.match_id}")
            if record.ps_probability_a is None:
                if (
                    feature["ps_missing"] != "1"
                    or feature["ps_probability_a"]
                    or feature["ps_logit_a"]
                ):
                    raise ChainError(f"missing PS encoding mismatch for {record.match_id}")
            else:
                if feature["ps_missing"] != "0" or float(feature["ps_probability_a"]) != (
                    record.ps_probability_a
                ):
                    raise ChainError(f"PS probability mismatch for {record.match_id}")
                if float(feature["ps_logit_a"]) != logit(record.ps_probability_a):
                    raise ChainError(f"PS logit mismatch for {record.match_id}")
            snapshot = feature["ranking_snapshot_date"]
            if snapshot:
                age = (record.match_date - dt.date.fromisoformat(snapshot)).days
                if int(feature["ranking_global_age_days"]) != age:
                    raise ChainError(f"ranking age mismatch for {record.match_id}")
                if int(feature["ranking_global_stale"]) != int(age > stale_days):
                    raise ChainError(f"ranking stale mismatch for {record.match_id}")
            for field in (
                "elo_latest_source_date",
                "count_latest_source_date",
                "workload_latest_source_date",
                "lagged_market_latest_source_date",
            ):
                if feature[field] and dt.date.fromisoformat(feature[field]) > cutoff:
                    raise ChainError(f"state cutoff mismatch in {field} for {record.match_id}")
            checks["rows"] += 1
            checks["primary_rows"] += int(record.identity_tier == PRIMARY_TIER)
            checks["provisional_rows"] += int(record.identity_tier == "provisional")
            checks["ps_missing_rows"] += int(record.ps_probability_a is None)
        if next(feature_rows, None) is not None or next(label_rows, None) is not None:
            raise ChainError("feature/label output has extra rows")
    return {
        "status": "PASS",
        "checks": {
            "feature_and_label_key_order": "exact",
            "neutral_orientation": "player_a < player_b on every row",
            "cutoff": f"eligible_through_date equals match_date minus {lag_days} days on every row",
            "state_latest_dates": "blank or no later than row cutoff",
            "model_finiteness": f"all {len(model_columns)} unique sports/lagged-market model fields finite",
            "context_and_interaction_algebra": "exact on every row",
            "pinnacle_normalization_output": "matches in-memory normalized input on every row",
            "label_separation": "winner/status only in label file; decimal odds absent from feature file",
        },
        "row_counts": dict(checks),
    }


HASH_VERIFIED_BINDINGS = ("design", "panel_manifest", "ranking_source", "ranking_index")
FIXED_PARAMETERS = {
    "lag_calendar_days": 2,
    "count_prior_denominator_units": 50.0,
    "count_half_life_days": 180.0,
    "initial_serve_rate": 0.6,
    "initial_return_rate": 0.4,
    "elo_initial_rating": 1500.0,
    "elo_k": 32.0,
    "elo_scale": 400.0,
    "workload_windows_days": [7, 28],
    "rest_days_cap": 90,
    "ranking_stale_days": 14,
    "primary_history_identity_tier": "primary",
}


def load_config(path: Path) -> dict[str, Any]:
    config = read_config(path)
    for source in HASH_VERIFIED_BINDINGS:
        actual = sha256(resolve_under_root(config[source]["path"], label=source))
        if actual != config[source]["sha256"]:
            raise ChainError(f"{source} hash mismatch: {actual}")
    parameters = config["parameters"]
    # source_year_min / source_year_max are the configured panel window; every
    # other feature parameter stays exactly as MULTI01 froze it.
    for name in ("source_year_min", "source_year_max"):
        value = parameters.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or not 2000 <= value <= 2100:
            raise ChainError(f"{name} must be a plausible integer season")
    if parameters["source_year_min"] > parameters["source_year_max"]:
        raise ChainError("source_year_min exceeds source_year_max")
    expected = {
        "source_year_min": parameters["source_year_min"],
        "source_year_max": parameters["source_year_max"],
        **FIXED_PARAMETERS,
    }
    if parameters != expected:
        raise ChainError("fixed MULTI01 feature parameters changed")
    if int(parameters["ranking_stale_days"]) != 14:
        raise ChainError("the 14-day ranking staleness rule is fixed")
    return config


def build(config_path: Path, overwrite: bool = False) -> dict[str, Any]:
    config = load_config(config_path)
    # The archive required OUTPUT_ROOT = ROOT / "work" to be a parent; the port requires
    # the output to lie under the workspace, which resolve_under_root enforces.
    output = resolve_output_under_root(config["output_dir"], label="output_dir")
    if output.exists() and any(output.iterdir()):
        if not overwrite:
            raise ChainError(f"nonempty output exists: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    panel = config["panel"]
    records, rejections, input_header = load_records(
        resolve_under_root(panel["path"], label="panel"),
        panel["sha256"],
        panel["rows"],
        int(config["parameters"]["source_year_min"]),
        int(config["parameters"]["source_year_max"]),
    )
    ranking = prepare_rankings(records, config)
    dictionary = column_dictionary()
    atomic_json(output / "column_dictionary.json", dictionary)
    atomic_json(output / "resolved_config.json", config)
    write_csv_simple(output / "rejections.csv", rejections, ("source_row", "match_id", "reason"))

    features_path = output / "features.csv"
    labels_path = output / "labels.csv"
    diverged: Counter[str] = Counter()
    ordered, counts_summary = write_features(
        features_path, records, ranking, config["parameters"], diverged
    )
    write_labels(labels_path, ordered)
    if len(ordered) != len(records):
        raise ChainError("feature writer dropped a target")
    with features_path.open(newline="", encoding="utf-8") as features_stream:
        feature_keys = [row["match_id"] for row in csv.DictReader(features_stream)]
    with labels_path.open(newline="", encoding="utf-8") as labels_stream:
        label_keys = [row["match_id"] for row in csv.DictReader(labels_stream)]
    if feature_keys != label_keys:
        raise ChainError("feature/label key order mismatch")

    validation = validate_written_outputs(
        features_path, labels_path, records, dictionary, config["parameters"]
    )
    atomic_json(output / "validation.json", validation)
    feature_fields = feature_header()
    summary = {
        "status": config["status"],
        "input_rows": panel["rows"],
        "eligible_target_rows": len(records),
        "rejected_rows": len(rejections),
        "primary_history_and_target_rows": sum(
            record.identity_tier == "primary" for record in records
        ),
        "provisional_target_only_rows": sum(
            record.identity_tier == "provisional" for record in records
        ),
        "count_update_eligible_primary_rows": sum(
            record.identity_tier == "primary" and record.counts_a is not None for record in records
        ),
        "result_and_workload_update_eligible_primary_rows": sum(
            record.identity_tier == "primary" for record in records
        ),
        "market_state_update_eligible_primary_rows": sum(
            record.identity_tier == "primary" and record.ps_probability_a is not None
            for record in records
        ),
        "feature_columns": len(feature_fields),
        "signed_base_columns": len(SIGNED_BASES),
        "binary_context_columns": len(BINARY_CONTEXTS),
        "signed_context_interactions": len(linear_interactions()),
        "rank_global_interactions": len(rank_global_interactions()),
        "counts": {
            name: {
                str(key): value
                for key, value in sorted(counter.items(), key=lambda item: str(item[0]))
            }
            for name, counter in counts_summary.items()
        },
        "input_header_columns": len(input_header),
        "diverged_serve_return_history_summaries": dict(sorted(diverged.items())),
        "notes": [
            "No model was fit and no proper score was computed.",
            "Provisional targets use primary-only states and never update those states.",
            "Missing count blocks retain result Elo and workload-match updates; point-volume updates are missing and flagged.",
            "Pinnacle target probability is isolated in market-family fields and absent from sports-only predictor allowlists.",
            "Dates are qualified annual reported dates without clocks. The known suspended 2022-7694/291 case demonstrates that reported date is not universally actual start date; D-2 remains the declared retrospective rule.",
            "diverged_serve_return_history_summaries counts targets where a side had "
            "serve count history without return history (a match served zero points by "
            "one player). The missing_* flag means no count history in that domain and "
            "each rate falls back to its prior; nothing is imputed.",
        ],
    }
    atomic_json(output / "summary.json", summary)
    output_files = [
        "features.csv", "labels.csv", "rejections.csv", "column_dictionary.json",
        "resolved_config.json", "summary.json", "validation.json",
    ]  # fmt: skip
    manifest = {
        "manifest_id": "MULTI01-prequential-features-v1",
        "status": config["status"],
        "inputs": {
            "config": {
                "path": relative_to_root(config_path, label="config"),
                "sha256": sha256(config_path),
            },
            "panel": panel,
            "panel_manifest": config["panel_manifest"],
            "design": config["design"],
            "ranking_source": config["ranking_source"],
            "ranking_index": config["ranking_index"],
            "ranking_lookup_module": config["ranking_lookup_module"],
        },
        "declared_binding": {
            "ranking_lookup_module": config["ranking_lookup_module"],
            "module": "tennislab.chronology.ranking_lookup",
        },
        "executed_builder": code_receipt(__name__),
        "outputs": {
            name: {
                "bytes": (output / name).stat().st_size,
                "sha256": sha256(output / name),
            }
            for name in output_files
        },
    }
    atomic_json(output / "manifest.json", manifest)
    return {
        "output_dir": relative_to_root(output, label="output_dir"),
        **summary,
        "manifest_sha256": sha256(output / "manifest.json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    result = build(resolve_under_root(args.config, label="config"), overwrite=args.overwrite)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
