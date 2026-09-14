#!/usr/bin/env python3
"""Generate the fully synthetic samples under ``data/sample*`` and pin their hashes.

Nothing here comes from a real source: the players, events, results, serve counts,
rankings and prices are drawn from a seeded ``numpy`` generator. The files follow the
formats the ported stages read after the market join (the ``format_corrections`` panel
schema, the SR02 base rule mapping and rule config, the saved SR02 selections, a
Sackmann-layout tarball for the ``rankings`` stage, a player master for the sidecar) so
that ``tennislab reproduce-small`` and the label-barrier test can run the chain from
``rule_mapping`` to ``report`` without the research archive.

Two scenarios share one generator:

* ``base`` (the default) writes ``data/sample`` and ``configs/chains/sample_atp.json``:
  the JOINT04 chain, bundles ``base`` and ``full``, contrast ``full_minus_base``.
* ``tier`` writes ``data/sample_tier`` and ``configs/chains/sample_atp_tier.json``: the
  same world with a lower tier beneath it (qualifying rounds at the tour events,
  Challenger main draws, Futures, two satellite circuits per season) in the tarball's
  ``atp/atp_matches_qual_chall_YYYY.csv`` and ``atp/atp_matches_futures_YYYY.csv``
  members, the ARCHIVE01-style inventory and custody manifest ``tier_stream`` verifies,
  and the per-training-window initial-rating offsets ``tier_elo`` re-measures and
  refuses to see drift in. The offsets are measured here by running ``tier_stream`` on
  the written tarball and ``tier_elo.measure_offset`` on its stream, so the committed
  chain config declares exactly what the chain re-measures.

    uv run python tools/make_sample.py                      # regenerate data/sample in place
    uv run python tools/make_sample.py --scenario tier      # regenerate data/sample_tier
    uv run python tools/make_sample.py --workspace <dir>    # write a copy under another root
    uv run python tools/make_sample.py --workspace <dir> --unknown-outcomes-final-year

The ``--workspace`` form writes ``<dir>/data/sample[_tier]`` and
``<dir>/configs/chains/sample_atp[_tier].json`` (the committed chain config with every
sample hash re-pinned), which is how the tests build a workspace. The flag blanks every
outcome of the last season, as a prospective run would have them, so the label-barrier
test can run the chain on a target year whose results are not yet known; it applies to
the base scenario only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SEED = 20260913
FIRST_SEASON = 2011
LAST_SEASON = 2020
BASE_RULES_THROUGH = 2019  # the base rule mapping ends here; 2020 is carried forward
FIRST_PLAYER_ID = 200001
TAR_ROOT = "synthetic-sample-archive"
SURFACES = ("Hard", "Clay", "Grass", "Carpet")


@dataclass(frozen=True)
class Scenario:
    """One committed sample: where it lives and whether it carries the lower tier."""

    name: str
    sample_dir: Path
    chain_config: Path
    player_count: int
    tier: bool
    # Tier scenario only: the first season of the lower-tier stream (experience counts
    # start here, a few seasons before the panel) and the first season a qualifying or
    # Challenger row carries a serve-count block (the SR02 feed starts here).
    tier_first_year: int = 0
    serve_counts_start_year: int = 0


SCENARIOS = {
    "base": Scenario(
        "base", Path("data", "sample"), Path("configs", "chains", "sample_atp.json"), 60, False
    ),
    "tier": Scenario(
        "tier",
        Path("data", "sample_tier"),
        Path("configs", "chains", "sample_atp_tier.json"),
        120,
        True,
        tier_first_year=2008,
        serve_counts_start_year=2012,
    ),
}
# Tier scenario: the player cohorts by index. The first block is on the tour from the
# first season; the second reaches the tour in a later season (drawn per player) after
# lower-tier seasons; the last never reaches the tour inside the window.
TIER_TOUR_FROM_START = 50
TIER_DEVELOPING = 40

# One season's calendar: 25 events, one every second week, with a fixed level, surface
# and court. The last event's code changes in the final season (315 -> 316) so the
# rule carry-forward has to fall back to the tour default for a new event.
EVENT_TEMPLATE: tuple[tuple[str, str, str, str], ...] = (
    ("301", "A", "Hard", "Outdoor"),
    ("302", "A", "Hard", "Indoor"),
    ("501", "G", "Hard", "Outdoor"),
    ("401", "M", "Hard", "Outdoor"),
    ("303", "A", "Clay", "Outdoor"),
    ("402", "M", "Clay", "Outdoor"),
    ("304", "A", "Clay", "Outdoor"),
    ("305", "A", "Clay", "Outdoor"),
    ("502", "G", "Clay", "Outdoor"),
    ("306", "A", "Grass", "Outdoor"),
    ("403", "M", "Grass", "Outdoor"),
    ("503", "G", "Grass", "Outdoor"),
    ("307", "A", "Hard", "Outdoor"),
    ("308", "A", "Clay", "Outdoor"),
    ("404", "M", "Hard", "Outdoor"),
    ("309", "A", "Hard", "Outdoor"),
    ("504", "G", "Hard", "Outdoor"),
    ("310", "A", "Hard", "Indoor"),
    ("311", "A", "Hard", "Outdoor"),
    ("405", "M", "Hard", "Indoor"),
    ("312", "A", "Carpet", "Indoor"),
    ("313", "A", "Hard", "Indoor"),
    ("406", "M", "Hard", "Indoor"),
    ("314", "A", "Hard", "Indoor"),
    ("315", "A", "Carpet", "Indoor"),
)
DRAW_BY_LEVEL = {"A": 16, "M": 32, "G": 32}
ROUNDS_32 = ("R32", "R16", "QF", "SF", "F")
ROUNDS_16 = ("R16", "QF", "SF", "F")
ROUNDS_8 = ("QF", "SF", "F")
ROUND_DAYS = {"R32": (0, 1), "R16": (2, 3), "QF": (4, 4), "SF": (5, 5), "F": (6, 6)}
ROUND_DAYS_16 = {"R16": (0, 1), "QF": (2, 2), "SF": (3, 3), "F": (4, 4)}
# Tier scenario: a grand slam spans two weeks, so its semifinals and final fall after
# the qualifying rows' reported date (anchor + 7) and the same-event ablation has a
# target whose event term the qualifying rows could have updated.
ROUND_DAYS_SLAM = {"R32": (0, 1), "R16": (2, 3), "QF": (7, 8), "SF": (10, 10), "F": (12, 12)}
QUALIFYING_ROUNDS = ("Q1", "Q2", "Q3")  # a draw of eight: four, two and one match
CHALLENGERS_PER_SEASON = 10
FUTURES_PER_SEASON = 8
SATELLITE_CIRCUITS = ((1, 4, 10), (2, 3, 30))  # (number, legs, anchor week)

PANEL_HEADER = (
    "B365_decimal_a,B365_decimal_b,B365_valid,PS_decimal_a,PS_decimal_b,PS_valid,a_1stIn,"
    "a_1stWon,a_2ndWon,a_SvGms,a_ace,a_age_years,a_bpFaced,a_bpSaved,a_df,a_entity_id,a_entry,"
    "a_hand,a_height_cm,a_identity_correction,a_identity_metadata_status,a_ioc,a_rank,"
    "a_rank_points,a_seed,a_source_id,a_source_name,a_source_side,a_svpt,a_won,abandoned,"
    "additional_count_evidence,archive_date_basis,b_1stIn,b_1stWon,b_2ndWon,b_SvGms,b_ace,"
    "b_age_years,b_bpFaced,b_bpSaved,b_df,b_entity_id,b_entry,b_hand,b_height_cm,"
    "b_identity_correction,b_identity_metadata_status,b_ioc,b_rank,b_rank_points,b_seed,"
    "b_source_id,b_source_name,b_source_side,b_svpt,best_of,competition_type,completed,"
    "count_block_status,count_correction_applied,court_recorded,date_basis,defaulted,draw_size,"
    "identity_basis,identity_tier,market_source_path,market_source_row,market_source_sha256,"
    "match_date,match_id,match_num,minutes,played,player_a,player_b,population_basis,"
    "ranking_metadata_basis,retired,round,score,season,source_correction,"
    "source_field_agreement,source_file_sha256,source_key,source_line_number,source_member,"
    "source_row_number,source_season,started_evidence,status,surface,tourney_anchor_date,"
    "tourney_id,tourney_level,tourney_name,walkover"
).split(",")
RULE_FIELDS = (
    "source_key",
    "match_id",
    "source_season",
    "tourney_id",
    "round",
    "best_of",
    "rule_group",
    "rule_basis",
    "match_rule",
)
BIO_HEADER = ("player_id", "name_first", "name_last", "hand", "dob", "ioc", "height", "wikidata_id")
RANKING_HEADER = ("ranking_date", "rank", "player", "points")
MATCH_HEADER = (
    "tourney_id,tourney_name,surface,draw_size,tourney_level,tourney_date,match_num,winner_id,"
    "winner_seed,winner_entry,winner_name,winner_hand,winner_ht,winner_ioc,winner_age,loser_id,"
    "loser_seed,loser_entry,loser_name,loser_hand,loser_ht,loser_ioc,loser_age,score,best_of,"
    "round,minutes,w_ace,w_df,w_svpt,w_1stIn,w_1stWon,w_2ndWon,w_SvGms,w_bpSaved,w_bpFaced,"
    "l_ace,l_df,l_svpt,l_1stIn,l_1stWon,l_2ndWon,l_SvGms,l_bpSaved,l_bpFaced,winner_rank,"
    "winner_rank_points,loser_rank,loser_rank_points"
).split(",")
INVENTORY_HEADER = ("path", "bytes", "sha256", "git_blob_sha1", "git_mode")
COUNT_SUFFIXES = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")

REGULAR_SET = {"mode": "tiebreak", "tiebreak_at_games": 6, "tiebreak_points": 7}
ORDINARY_DECIDING_SET = {"mode": "tiebreak", "tiebreak_at_games": 6, "tiebreak_points": 7}
SLAM_DECIDING_SET = {"mode": "tiebreak", "tiebreak_at_games": 6, "tiebreak_points": 10}
ORDINARY_RULE = {
    "rule_group": "ordinary_atp_best_of_three",
    "rule_basis": "synthetic",
    "match_rule": json.dumps(
        {"sets_to_win": 2, "regular_set": REGULAR_SET, "deciding_set": ORDINARY_DECIDING_SET},
        sort_keys=True,
        separators=(",", ":"),
    ),
}
SLAM_RULE = {
    "rule_group": "sample_grand_slam_best_of_five",
    "rule_basis": "synthetic",
    "match_rule": json.dumps(
        {"sets_to_win": 3, "regular_set": REGULAR_SET, "deciding_set": SLAM_DECIDING_SET},
        sort_keys=True,
        separators=(",", ":"),
    ),
}
DYNAMIC_CANDIDATE = "q050_g040_moderate"
CONTROL_CANDIDATE = "h180_o250_s250"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_blob_sha1(payload: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(payload) + payload).hexdigest()


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def first_monday(year: int) -> dt.date:
    day = dt.date(year, 1, 3)
    while day.weekday() != 0:
        day += dt.timedelta(days=1)
    return day


# ------------------------------------------------------------------ the synthetic world


class World:
    """Players with latent strengths, a weekly ranking stream and a decade of events."""

    def __init__(self, rng: np.random.Generator, scenario: Scenario):
        self.rng = rng
        self.scenario = scenario
        self.player_count = scenario.player_count
        self.players = self._players()
        self.strength = {
            player["player_id"]: float(value)
            for player, value in zip(
                self.players, rng.normal(0.0, 1.0, self.player_count), strict=True
            )
        }
        self.surface_shift = {
            (player["player_id"], surface): float(value)
            for player in self.players
            for surface, value in zip(SURFACES, rng.normal(0.0, 0.25, len(SURFACES)), strict=True)
        }
        self.serve_skill = {
            player["player_id"]: float(value)
            for player, value in zip(
                self.players, rng.normal(0.0, 0.03, self.player_count), strict=True
            )
        }
        # The season a player first enters a tour main draw. Every base player is on
        # the tour from the first season; the tier scenario adds a developing cohort and
        # a cohort that stays below the tour, both weaker.
        self.tour_from = {player["player_id"]: FIRST_SEASON for player in self.players}
        if scenario.tier:
            for index, player in enumerate(self.players):
                pid = player["player_id"]
                if index < TIER_TOUR_FROM_START:
                    continue
                if index < TIER_TOUR_FROM_START + TIER_DEVELOPING:
                    self.tour_from[pid] = int(rng.integers(FIRST_SEASON + 1, LAST_SEASON + 1))
                    self.strength[pid] -= 0.6
                else:
                    self.tour_from[pid] = LAST_SEASON + 1
                    self.strength[pid] -= 1.2
        self.rankings = self._rankings()
        self.ranking_dates = sorted({date for date, _, _, _ in self.rankings})
        self.rank_at: dict[tuple[dt.date, int], tuple[int, int]] = {
            (date, player): (rank, points) for date, rank, player, points in self.rankings
        }

    def _players(self) -> list[dict[str, str]]:
        rng = self.rng
        players = []
        for index in range(self.player_count):
            birth = dt.date(1982, 1, 1) + dt.timedelta(days=int(rng.integers(0, 16 * 365)))
            hand = "L" if rng.random() < 0.12 else "R"
            height = int(rng.integers(170, 206))
            players.append(
                {
                    "player_id": str(FIRST_PLAYER_ID + index),
                    "name_first": "P",
                    "name_last": f"{index + 1:02d}",
                    "hand": hand,
                    "dob": birth.strftime("%Y%m%d"),
                    "ioc": "SYN",
                    "height": "" if rng.random() < 0.05 else str(height),
                    "wikidata_id": "",
                }
            )
        return players

    def _rankings(self) -> list[tuple[dt.date, int, int, int]]:
        """Weekly Monday editions: latent strength plus a slow random walk."""
        rng = self.rng
        ids = [int(player["player_id"]) for player in self.players]
        drift = np.zeros(self.player_count)
        rows: list[tuple[dt.date, int, int, int]] = []
        date = first_monday(FIRST_SEASON)
        end = dt.date(LAST_SEASON, 12, 31)
        while date <= end:
            drift = 0.97 * drift + rng.normal(0.0, 0.08, self.player_count)
            score = np.array([self.strength[str(pid)] for pid in ids]) + drift
            order = np.argsort(-score, kind="stable")
            for rank, index in enumerate(order, start=1):
                points = int(round(9000 * 0.93 ** (rank - 1))) + 100
                rows.append((date, rank, ids[index], points))
            date += dt.timedelta(days=7)
        return rows

    def ranking_on(self, day: dt.date, player: int) -> tuple[int, int] | None:
        """The latest edition on or before ``day``; None before the first edition."""
        index = int(np.searchsorted(np.array(self.ranking_dates), day, side="right")) - 1
        if index < 0:
            return None
        return self.rank_at.get((self.ranking_dates[index], player))

    def player(self, player_id: int) -> dict[str, str]:
        return self.players[player_id - FIRST_PLAYER_ID]

    def ids(self, *, tour_in: int | None = None, below_tour_in: int | None = None) -> list[int]:
        """Player ids in id order; optionally those on, or those below, the tour in a season."""
        chosen = []
        for player in self.players:
            pid = player["player_id"]
            if tour_in is not None and self.tour_from[pid] > tour_in:
                continue
            if below_tour_in is not None and self.tour_from[pid] <= below_tour_in:
                continue
            chosen.append(int(pid))
        return chosen

    def win_probability(self, a: int, b: int, surface: str) -> float:
        delta = (
            self.strength[str(a)]
            - self.strength[str(b)]
            + self.surface_shift[(str(a), surface)]
            - self.surface_shift[(str(b), surface)]
        )
        return sigmoid(1.1 * delta)


def service_line(rng: np.random.Generator, points: int, win_rate: float) -> dict[str, int]:
    """One player's serve counts, consistent with the panel stage's identity checks."""
    first_in = int(rng.binomial(points, 0.62))
    second = points - first_in
    first_won = int(rng.binomial(first_in, min(0.95, win_rate + 0.09)))
    second_won = int(rng.binomial(second, max(0.05, win_rate - 0.12)))
    double_faults = int(rng.binomial(second - second_won, 0.12))
    aces = int(rng.binomial(first_won, 0.14))
    faced = int(rng.poisson(5))
    saved = int(rng.binomial(faced, 0.6))
    return {
        "svpt": points,
        "1stIn": first_in,
        "1stWon": first_won,
        "2ndWon": second_won,
        "df": double_faults,
        "ace": aces,
        "SvGms": max(1, int(round(points / 6.4))),
        "bpSaved": saved,
        "bpFaced": faced,
    }


def score_text(rng: np.random.Generator, best_of: int, status: str) -> str:
    sets = []
    needed = 2 if best_of == 3 else 3
    won = 0
    lost = 0
    while won < needed and lost < needed:
        if rng.random() < 0.62:
            sets.append(f"6-{int(rng.integers(0, 5))}")
            won += 1
        else:
            sets.append(f"{int(rng.integers(0, 5))}-6")
            lost += 1
    if status == "retired":
        return " ".join(sets[:-1] + ["3-1 RET"])
    if status == "default":
        return " ".join(sets[:-1] + ["2-2 DEF"])
    return " ".join(sets)


def decimal_pair(rng: np.random.Generator, probability: float, margin: float) -> tuple[str, str]:
    # Both decimals must exceed 1 after the overround: keep the implied probability
    # of either side below 1 / (1 + margin).
    clipped = min(0.92, max(0.08, probability + float(rng.normal(0.0, 0.03))))
    decimal_a = 1.0 / (clipped * (1.0 + margin))
    decimal_b = 1.0 / ((1.0 - clipped) * (1.0 + margin))
    return f"{decimal_a:.3f}", f"{decimal_b:.3f}"


def weighted_draw(world: World, candidates: list[int], draw: int, temperature: float) -> list[int]:
    ids = np.array(candidates)
    strength = np.array([world.strength[str(pid)] for pid in ids])
    weights = np.exp(temperature * strength)
    weights /= weights.sum()
    chosen = world.rng.choice(ids, size=draw, replace=False, p=weights)
    return sorted(int(pid) for pid in chosen)


def event_participants(world: World, draw: int, level: str, season: int) -> list[int]:
    """Top-heavy for the higher levels, mixed for the ordinary events."""
    temperature = 1.2 if level in {"G", "M"} else 0.5
    return weighted_draw(world, world.ids(tour_in=season), draw, temperature)


def bracket(world: World, players: list[int]) -> list[int]:
    """Seed by strength with noise and pair the strongest against the weakest."""
    noisy = {pid: world.strength[str(pid)] + float(world.rng.normal(0.0, 0.5)) for pid in players}
    ordered = sorted(players, key=lambda pid: -noisy[pid])
    half = len(ordered) // 2
    slots: list[int] = []
    for index in range(half):
        slots.extend([ordered[index], ordered[-1 - index]])
    return slots


def serve_rate(world: World, pid: int, bonus: float) -> float:
    rate = 0.635 + 0.04 * world.strength[str(pid)] + world.serve_skill[str(pid)] + bonus
    return min(0.9, max(0.4, rate))


def generate_matches(world: World) -> list[dict[str, Any]]:
    """Every match of every event of every season, in play order, with its counts."""
    rng = world.rng
    matches: list[dict[str, Any]] = []
    for season in range(FIRST_SEASON, LAST_SEASON + 1):
        anchor = first_monday(season)
        for position, (code, level, surface, court) in enumerate(EVENT_TEMPLATE):
            if season == LAST_SEASON and code == "315":
                code = "316"  # a new event: no carry-source edition
            start = anchor + dt.timedelta(days=14 * position)
            draw = DRAW_BY_LEVEL[level]
            rounds = ROUNDS_32 if draw == 32 else ROUNDS_16
            days = ROUND_DAYS if draw == 32 else ROUND_DAYS_16
            if world.scenario.tier and level == "G":
                days = ROUND_DAYS_SLAM
            best_of = 5 if level == "G" else 3
            tourney_id = f"{season}-{code}"
            participants = event_participants(world, draw, level, season)
            alive = bracket(world, participants)
            seeds = {
                pid: seed
                for seed, pid in enumerate(
                    sorted(alive, key=lambda p: -world.strength[str(p)])[:8], 1
                )
            }
            match_num = 0
            for round_name in rounds:
                next_round: list[int] = []
                first_day, second_day = days[round_name]
                for pair_index in range(0, len(alive), 2):
                    left, right = alive[pair_index], alive[pair_index + 1]
                    match_num += 1
                    day = first_day if (pair_index // 2) % 2 == 0 else second_day
                    date = start + dt.timedelta(days=day)
                    a, b = min(left, right), max(left, right)
                    p_a = world.win_probability(a, b, surface)
                    a_won = bool(rng.random() < p_a)
                    winner, loser = (a, b) if a_won else (b, a)
                    next_round.append(winner)
                    draw_status = rng.random()
                    status = "completed"
                    if draw_status < 0.025:
                        status = "retired"
                    elif draw_status < 0.03:
                        status = "default"
                    usable = rng.random() >= 0.015
                    base_points = 112 if best_of == 5 else 72
                    spread = 24 if best_of == 5 else 16
                    counts: dict[str, dict[str, int]] = {}
                    if usable:
                        for side, pid, bonus in (("a", a, 0.04), ("b", b, -0.04)):
                            edge = bonus if a_won else -bonus
                            points = max(30, int(rng.normal(base_points, spread)))
                            counts[side] = service_line(rng, points, serve_rate(world, pid, edge))
                    matches.append(
                        {
                            "season": season,
                            "tourney_id": tourney_id,
                            "code": code,
                            "level": level,
                            "surface": surface,
                            "court": court,
                            "draw": draw,
                            "start": start,
                            "date": date,
                            "round": round_name,
                            "match_num": match_num,
                            "best_of": best_of,
                            "a": a,
                            "b": b,
                            "a_won": a_won,
                            "p_a": p_a,
                            "status": status,
                            "usable": usable,
                            "counts": counts,
                            "seed_a": seeds.get(a),
                            "seed_b": seeds.get(b),
                            "provisional": rng.random() < 0.015,
                            "ps_valid": rng.random() < 0.95,
                            "b365_valid": rng.random() < 0.97,
                            "agreement": rng.random() < 0.97,
                            "score": score_text(rng, best_of, status),
                            "minutes": int(rng.integers(55, 130 if best_of == 3 else 240)),
                            "entry_a": "Q"
                            if rng.random() < 0.08
                            else ("WC" if rng.random() < 0.04 else ""),
                            "entry_b": "Q"
                            if rng.random() < 0.08
                            else ("WC" if rng.random() < 0.04 else ""),
                            "participants": participants,
                        }
                    )
                alive = next_round
    return matches


# ------------------------------------------------------------------ the lower tier


def lower_tier_draw(
    world: World,
    *,
    season: int,
    family: str,
    tourney_id: str,
    tourney_name: str,
    level: str,
    surface: str,
    anchor: dt.date,
    players: list[int],
    rounds: tuple[str, ...],
    qualifying: bool,
) -> list[dict[str, Any]]:
    """One lower-tier draw in the Sackmann raw layout; the tier split is the audit's.

    Qualifying rows are ``Q1..Q3`` under the main draw's own tourney id and level;
    everything else at level ``C`` is a Challenger main draw; every Futures-family row
    is Futures. Serve counts appear in the qualifying/Challenger family from
    ``serve_counts_start_year`` and never in Futures, as the audit found.
    """
    rng = world.rng
    alive = bracket(world, players)
    rows: list[dict[str, Any]] = []
    match_num = 0
    counted_family = family == "atp_qual_chall" and season >= world.scenario.serve_counts_start_year
    for round_name in rounds:
        next_round: list[int] = []
        for pair_index in range(0, len(alive), 2):
            left, right = alive[pair_index], alive[pair_index + 1]
            match_num += 1
            a_won = bool(rng.random() < world.win_probability(left, right, surface))
            winner, loser = (left, right) if a_won else (right, left)
            next_round.append(winner)
            draw_status = rng.random()
            status = "completed"
            if draw_status < 0.03:
                status = "retired"
            elif draw_status < 0.045:
                status = "walkover"  # excluded by tier_stream: no result, no counts
            counts: dict[str, dict[str, int]] = {}
            if counted_family and status != "walkover" and rng.random() < 0.85:
                for side, pid, edge in (("w", winner, 0.04), ("l", loser, -0.04)):
                    points = max(30, int(rng.normal(72, 16)))
                    counts[side] = service_line(rng, points, serve_rate(world, pid, edge))
            rows.append(
                {
                    "season": season,
                    "family": family,
                    "tourney_id": tourney_id,
                    "tourney_name": tourney_name,
                    "level": level,
                    "surface": surface,
                    "draw": len(players),
                    "anchor": anchor,
                    "round": round_name,
                    "match_num": match_num,
                    "winner": winner,
                    "loser": loser,
                    "status": status,
                    "score": "W/O" if status == "walkover" else score_text(rng, 3, status),
                    "minutes": "" if status == "walkover" else str(int(rng.integers(50, 125))),
                    "counts": counts,
                    "qualifying": qualifying,
                }
            )
        alive = next_round
    return rows


def generate_lower_tier(world: World, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qualifying, Challenger, Futures and satellite rows for every tier-stream season."""
    scenario = world.scenario
    rng = world.rng
    main_draws: dict[tuple[int, str], dict[str, Any]] = {}
    for match in matches:
        main_draws.setdefault(
            (match["season"], match["code"]),
            {
                "level": match["level"],
                "surface": match["surface"],
                "start": match["start"],
                "participants": set(match["participants"]),
            },
        )
    rows: list[dict[str, Any]] = []
    for season in range(scenario.tier_first_year, LAST_SEASON + 1):
        monday = first_monday(season)
        on_tour = world.ids(tour_in=season)
        below = world.ids(below_tour_in=season)
        # Qualifying at every tour event: a draw of eight from the tour players left out
        # of the main draw and the players below the tour, under the main draw's id.
        for position, (code, level, surface, _court) in enumerate(EVENT_TEMPLATE):
            if season == LAST_SEASON and code == "315":
                code = "316"
            edition = main_draws.get((season, code))
            if edition is None:  # a season before the panel: no main draw to exclude
                edition = {
                    "level": level,
                    "surface": surface,
                    "start": monday + dt.timedelta(days=14 * position),
                    "participants": set(),
                }
            candidates = [pid for pid in on_tour if pid not in edition["participants"]] + below
            rows += lower_tier_draw(
                world,
                season=season,
                family="atp_qual_chall",
                tourney_id=f"{season}-{code}",
                tourney_name=f"Sample {code}",
                level=edition["level"],
                surface=edition["surface"],
                anchor=edition["start"],
                players=weighted_draw(world, candidates, 8, 0.8),
                rounds=QUALIFYING_ROUNDS,
                qualifying=True,
            )
        # Challenger main draws: the players below the tour and the weaker tour players.
        weak_tour = sorted(on_tour, key=lambda pid: world.strength[str(pid)])[: len(on_tour) // 3]
        for number in range(CHALLENGERS_PER_SEASON):
            surface = SURFACES[int(rng.integers(0, 3))]
            rows += lower_tier_draw(
                world,
                season=season,
                family="atp_qual_chall",
                tourney_id=f"{season}-C{number + 1:02d}",
                tourney_name=f"Sample Challenger {number + 1:02d}",
                level="C",
                surface=surface,
                anchor=monday + dt.timedelta(days=7 * (2 + 5 * number)),
                players=weighted_draw(world, below + weak_tour, 16, 0.5),
                rounds=ROUNDS_16,
                qualifying=False,
            )
        # Futures: the players below the tour only.
        for number in range(FUTURES_PER_SEASON):
            surface = SURFACES[int(rng.integers(0, 2))]
            rows += lower_tier_draw(
                world,
                season=season,
                family="atp_futures",
                tourney_id=f"{season}-F{number + 1:02d}",
                tourney_name=f"Sample Futures {number + 1:02d}",
                level="F",
                surface=surface,
                anchor=monday + dt.timedelta(days=7 * (1 + 6 * number)),
                players=weighted_draw(world, below, 16, 0.5),
                rounds=ROUNDS_16,
                qualifying=False,
            )
        # Satellite circuits: every leg shares the circuit's anchor and its id ends in the
        # leg letter, the shape tier_stream's satellite_circuit_dating redates.
        for number, legs, week in SATELLITE_CIRCUITS:
            anchor = monday + dt.timedelta(days=7 * week)
            surface = SURFACES[int(rng.integers(0, 2))]
            base = f"{season}-M-SA-SYN-{number:02d}A-{season}"
            for leg in "abcd"[:legs]:
                rows += lower_tier_draw(
                    world,
                    season=season,
                    family="atp_futures",
                    tourney_id=f"{base}{leg}",
                    tourney_name=f"Sample Satellite {number} leg {leg}",
                    level="S",
                    surface=surface,
                    anchor=anchor,
                    players=weighted_draw(world, below, 8, 0.5),
                    rounds=ROUNDS_8,
                    qualifying=False,
                )
    return rows


def lower_tier_member_row(world: World, row: dict[str, Any]) -> dict[str, str]:
    record: dict[str, str] = dict.fromkeys(MATCH_HEADER, "")
    record.update(
        {
            "tourney_id": row["tourney_id"],
            "tourney_name": row["tourney_name"],
            "surface": row["surface"],
            "draw_size": str(row["draw"]),
            "tourney_level": row["level"],
            "tourney_date": row["anchor"].strftime("%Y%m%d"),
            "match_num": str(row["match_num"]),
            "score": row["score"],
            "best_of": "3",
            "round": row["round"],
            "minutes": row["minutes"],
        }
    )
    for prefix, side, pid in (("winner", "w", row["winner"]), ("loser", "l", row["loser"])):
        player = world.player(pid)
        record[f"{prefix}_id"] = str(pid)
        record[f"{prefix}_name"] = f"{player['name_first']} {player['name_last']}"
        record[f"{prefix}_hand"] = player["hand"]
        record[f"{prefix}_ht"] = player["height"]
        record[f"{prefix}_ioc"] = player["ioc"]
        if side in row["counts"]:
            for suffix in COUNT_SUFFIXES:
                record[f"{side}_{suffix}"] = str(row["counts"][side][suffix])
    return record


# ------------------------------------------------------------------ file writers


def panel_row(world: World, match: dict[str, Any], line: int, unknown: bool) -> dict[str, str]:
    a, b = match["a"], match["b"]
    date: dt.date = match["date"]
    row: dict[str, str] = dict.fromkeys(PANEL_HEADER, "")
    for side, pid in (("a", a), ("b", b)):
        player = world.player(pid)
        ranking = world.ranking_on(date, pid)
        birth = dt.datetime.strptime(player["dob"], "%Y%m%d").date()
        row[f"{side}_entity_id"] = str(pid)
        row[f"{side}_source_id"] = str(pid)
        row[f"{side}_source_name"] = f"{player['name_first']} {player['name_last']}"
        row[f"{side}_hand"] = player["hand"]
        row[f"{side}_height_cm"] = player["height"]
        row[f"{side}_ioc"] = player["ioc"]
        row[f"{side}_age_years"] = f"{(date - birth).days / 365.25:.1f}"
        row[f"{side}_rank"] = "" if ranking is None else str(ranking[0])
        row[f"{side}_rank_points"] = "" if ranking is None else str(ranking[1])
        seed = match[f"seed_{side}"]
        row[f"{side}_seed"] = "" if seed is None else str(seed)
        row[f"{side}_entry"] = match[f"entry_{side}"]
        row[f"{side}_identity_metadata_status"] = "synthetic"
        if match["usable"]:
            for suffix in COUNT_SUFFIXES:
                row[f"{side}_{suffix}"] = str(match["counts"][side][suffix])
    p_a = match["p_a"]
    if match["ps_valid"]:
        row["PS_decimal_a"], row["PS_decimal_b"] = decimal_pair(world.rng, p_a, 0.03)
    if match["b365_valid"]:
        row["B365_decimal_a"], row["B365_decimal_b"] = decimal_pair(world.rng, p_a, 0.06)
    row["PS_valid"] = "true" if match["ps_valid"] else "false"
    row["B365_valid"] = "true" if match["b365_valid"] else "false"
    status = match["status"]
    row.update(
        {
            "a_won": "" if unknown else ("true" if match["a_won"] else "false"),
            "a_source_side": "" if unknown else ("w" if match["a_won"] else "l"),
            "b_source_side": "" if unknown else ("l" if match["a_won"] else "w"),
            "abandoned": "false",
            "archive_date_basis": "synthetic_event_anchor",
            "best_of": str(match["best_of"]),
            "competition_type": "individual_tour",
            "completed": "true" if status == "completed" else "false",
            "count_block_status": "usable" if match["usable"] else "missing_all",
            "count_correction_applied": "false",
            "court_recorded": match["court"],
            "date_basis": "synthetic_reported_date",
            "defaulted": "true" if status == "default" else "false",
            "draw_size": str(match["draw"]),
            "identity_basis": "synthetic_provisional" if match["provisional"] else "synthetic",
            "identity_tier": "provisional" if match["provisional"] else "primary",
            "market_source_path": "synthetic",
            "market_source_row": str(line),
            "match_date": date.isoformat(),
            "match_id": f"{match['tourney_id']}/{match['match_num']}",
            "match_num": str(match["match_num"]),
            "minutes": str(match["minutes"]),
            "played": "true",
            "player_a": str(a),
            "player_b": str(b),
            "population_basis": f"level_{match['level']}",
            "ranking_metadata_basis": "synthetic",
            "retired": "true" if status == "retired" else "false",
            "round": match["round"],
            "score": "" if unknown else match["score"],
            "season": str(match["season"]),
            "source_field_agreement": "true" if match["agreement"] else "false",
            "source_key": f"{match['tourney_id']}/{match['match_num']}",
            "source_line_number": str(line),
            "source_member": f"atp_matches_{match['season']}.csv",
            "source_row_number": str(line - 1),
            "source_season": str(match["season"]),
            "started_evidence": "synthetic" if status == "default" else "",
            "status": status,
            "surface": match["surface"],
            "tourney_anchor_date": match["start"].strftime("%Y%m%d"),
            "tourney_id": match["tourney_id"],
            "tourney_level": match["level"],
            "tourney_name": f"Sample {match['code']}",
            "walkover": "false",
        }
    )
    return row


def csv_bytes(header: tuple[str, ...] | list[str], rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(header), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def json_bytes(document: Any) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sackmann_match_row(world: World, match: dict[str, Any]) -> dict[str, str]:
    winner, loser = (match["a"], match["b"]) if match["a_won"] else (match["b"], match["a"])
    row: dict[str, str] = dict.fromkeys(MATCH_HEADER, "")
    row.update(
        {
            "tourney_id": match["tourney_id"],
            "tourney_name": f"Sample {match['code']}",
            "surface": match["surface"],
            "draw_size": str(match["draw"]),
            "tourney_level": match["level"],
            "tourney_date": match["start"].strftime("%Y%m%d"),
            "match_num": str(match["match_num"]),
            "score": match["score"],
            "best_of": str(match["best_of"]),
            "round": match["round"],
            "minutes": str(match["minutes"]),
        }
    )
    for prefix, pid in (("winner", winner), ("loser", loser)):
        player = world.player(pid)
        ranking = world.ranking_on(match["date"], pid)
        row[f"{prefix}_id"] = str(pid)
        row[f"{prefix}_name"] = f"{player['name_first']} {player['name_last']}"
        row[f"{prefix}_hand"] = player["hand"]
        row[f"{prefix}_ht"] = player["height"]
        row[f"{prefix}_ioc"] = player["ioc"]
        row[f"{prefix}_rank"] = "" if ranking is None else str(ranking[0])
        row[f"{prefix}_rank_points"] = "" if ranking is None else str(ranking[1])
    return row


def tarball_bytes(members: dict[str, bytes]) -> bytes:
    """A deterministic gzip tarball: fixed mtime, owner and mode, sorted members."""
    raw = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(members):
                info = tarfile.TarInfo(f"{TAR_ROOT}/{name}")
                info.size = len(members[name])
                info.mtime = 0
                info.mode = 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(members[name]))
    return raw.getvalue()


def design_text(scenario: Scenario, counts: dict[str, int]) -> str:
    tier = (
        "\nThe tier scenario adds a lower tier beneath the same tour: qualifying rounds at\n"
        "every tour event under the main draw's own id, Challenger main draws, Futures and\n"
        "satellite circuits, read by `tier_stream` from the tarball's qualifying/Challenger\n"
        "and Futures members, and the five TIER01 stages run beside the JOINT04 chain. The\n"
        f"published contrast is `full_tier_minus_full`. Lower-tier seasons\n"
        f"{scenario.tier_first_year}-{LAST_SEASON}; {counts['lower_tier_rows']} lower-tier rows.\n"
        if scenario.tier
        else ""
    )
    return (
        "# Synthetic sample design\n\n"
        "This document is the bound design, bio contract and panel manifest companion for\n"
        "the committed sample. The sample is fully synthetic: every player, event, result,\n"
        "serve count, ranking and price was drawn from a seeded generator\n"
        f"(`tools/make_sample.py`, seed {SEED}). No real player, match, result or market\n"
        "price appears in it, and nothing in it is evidence about tennis.\n\n"
        "The chain it exercises starts after the market join: rule carry-forward, the saved\n"
        "SR02 replay, SR03 calibration, ranking qualification, the edition index, features,\n"
        "the trait sidecar, the predictor and reporting configs, the model pipeline, the\n"
        "barrier and the report. The published contrast is `full_minus_base` with the HGB\n"
        f"learner. Seasons {FIRST_SEASON}-{LAST_SEASON}; {counts['players']} players;\n"
        f"{counts['panel_rows']} panel rows.\n" + tier
    )


def write_sample(
    workspace: Path, *, scenario: Scenario, unknown_final_year: bool, template: Path
) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    world = World(rng, scenario)
    matches = generate_matches(world)
    lower = generate_lower_tier(world, matches) if scenario.tier else []
    sample = workspace / scenario.sample_dir
    sample.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}

    # The panel, in play order, with the source locators of the tarball's match files.
    panel_rows: list[dict[str, str]] = []
    line_by_season: dict[int, int] = {}
    for match in matches:
        line = line_by_season.get(match["season"], 1) + 1
        line_by_season[match["season"]] = line
        unknown = unknown_final_year and match["season"] == LAST_SEASON
        panel_rows.append(panel_row(world, match, line, unknown))
    files["panel.csv"] = csv_bytes(PANEL_HEADER, panel_rows)

    # The base rule mapping through the carry-from year, one row per panel row.
    rule_rows = [
        {
            "source_key": row["source_key"],
            "match_id": row["match_id"],
            "source_season": row["source_season"],
            "tourney_id": row["tourney_id"],
            "round": row["round"],
            "best_of": row["best_of"],
            **(SLAM_RULE if row["tourney_level"] == "G" else ORDINARY_RULE),
        }
        for row in panel_rows
        if int(row["source_season"]) <= BASE_RULES_THROUGH
    ]
    rule_rows.sort(
        key=lambda row: (int(row["source_season"]), row["tourney_id"], row["source_key"])
    )
    files["base_rules.csv"] = csv_bytes(RULE_FIELDS, rule_rows)
    files["rules.json"] = json_bytes(
        {
            "id": "SAMPLE-scoring-rules",
            "scope": f"synthetic {FIRST_SEASON}-{LAST_SEASON} sample panel",
            "year_field": "source_season",
            "regular_set": REGULAR_SET,
            "grand_slams": {
                code: {
                    "name": f"Sample G{code}",
                    "eras": [[FIRST_SEASON, LAST_SEASON, "tiebreak", 6, 10, "synthetic"]],
                }
                for code, level, _, _ in EVENT_TEMPLATE
                if level == "G"
            },
            "ordinary_atp": {
                "levels": ["A", "M", "F"],
                "best_of": 3,
                "deciding_set": ORDINARY_DECIDING_SET,
                "basis": ORDINARY_RULE["rule_basis"],
            },
            "unknown_policy": "fail_mapping_no_guessed_rule",
        }
    )

    # The saved SR02 selections: one candidate per family for every selection year.
    selection_rows = [
        {
            "candidate_family": family,
            "selection_year": str(year),
            "selected_candidate_id": candidate,
            "selection_start": f"{year - 3}-01-01",
            "selection_cutoff": f"{year - 1}-12-30",
            "selection_reason": "synthetic_fixed_candidate",
        }
        for family, candidate in (("dynamic", DYNAMIC_CANDIDATE), ("control", CONTROL_CANDIDATE))
        for year in range(FIRST_SEASON, LAST_SEASON + 1)
    ]
    files["selections.csv"] = csv_bytes(
        (
            "candidate_family",
            "selection_year",
            "selected_candidate_id",
            "selection_start",
            "selection_cutoff",
            "selection_reason",
        ),
        selection_rows,
    )

    # The player master: the sidecar's bio table and the tarball's atp_players.csv.
    files["players.csv"] = csv_bytes(BIO_HEADER, world.players)

    # The Sackmann-layout tarball the rankings stage (and, in the tier scenario,
    # tier_stream) reads.
    ranking_rows = {"00s": [], "10s": [], "20s": []}
    for date, rank, player, points in world.rankings:
        decade = "10s" if date.year < 2020 else "20s"
        ranking_rows[decade].append(
            {
                "ranking_date": date.strftime("%Y%m%d"),
                "rank": str(rank),
                "player": str(player),
                "points": str(points),
            }
        )
    members: dict[str, bytes] = {
        "LICENSE": b"Synthetic sample data generated by tools/make_sample.py; no licence terms attach.\n",
        "README.md": b"# Synthetic sample archive\n\nSackmann-layout members generated by tools/make_sample.py. Nothing here is real.\n",
        "atp/UPSTREAM_README.md": b"Synthetic; there is no upstream.\n",
        "atp/matches_data_dictionary.txt": b"Synthetic match files in the Sackmann column layout.\n",
        "atp/atp_players.csv": files["players.csv"],
    }
    for decade, rows in ranking_rows.items():
        members[f"atp/atp_rankings_{decade}.csv"] = csv_bytes(RANKING_HEADER, rows)
    for season in range(FIRST_SEASON, LAST_SEASON + 1):
        members[f"atp/atp_matches_{season}.csv"] = csv_bytes(
            MATCH_HEADER,
            [sackmann_match_row(world, match) for match in matches if match["season"] == season],
        )
    if scenario.tier:
        for season in range(scenario.tier_first_year, LAST_SEASON + 1):
            for family, stem in (("atp_qual_chall", "qual_chall"), ("atp_futures", "futures")):
                members[f"atp/atp_matches_{stem}_{season}.csv"] = csv_bytes(
                    MATCH_HEADER,
                    [
                        lower_tier_member_row(world, row)
                        for row in lower
                        if row["season"] == season and row["family"] == family
                    ],
                )
    files["archive.tar.gz"] = tarball_bytes(members)
    if scenario.tier:
        # The custody chain tier_stream verifies: the inventory pins every member, the
        # manifest pins the tarball and the inventory, the chain config pins all three.
        files["snapshot_file_inventory.csv"] = csv_bytes(
            INVENTORY_HEADER,
            [
                {
                    "path": name,
                    "bytes": str(len(payload)),
                    "sha256": sha256_bytes(payload),
                    "git_blob_sha1": git_blob_sha1(payload),
                    "git_mode": "100644",
                }
                for name, payload in sorted(members.items())
            ],
        )
        files["archive_manifest.json"] = json_bytes(
            {
                "id": "SAMPLE-TIER-archive",
                "scope": "synthetic Sackmann-layout mirror generated by tools/make_sample.py; "
                "the custody shape of ARCHIVE01, none of its data",
                "generator": "tools/make_sample.py",
                "seed": SEED,
                "files": [
                    {
                        "path": (scenario.sample_dir / name).as_posix(),
                        "bytes": len(files[name]),
                        "sha256": sha256_bytes(files[name]),
                    }
                    for name in ("archive.tar.gz", "snapshot_file_inventory.csv")
                ],
            }
        )

    counts = {
        "players": len(world.players),
        "panel_rows": len(panel_rows),
        "base_rule_rows": len(rule_rows),
        "ranking_rows": len(world.rankings),
        "seasons": LAST_SEASON - FIRST_SEASON + 1,
        "events": len({row["tourney_id"] for row in panel_rows}),
    }
    if scenario.tier:
        counts["lower_tier_rows"] = len(lower)
        counts["lower_tier_seasons"] = LAST_SEASON - scenario.tier_first_year + 1
    files["design.md"] = design_text(scenario, counts).encode("utf-8")
    panel_sha = sha256_bytes(files["panel.csv"])
    files["panel_manifest.json"] = json_bytes(
        {
            "id": "SAMPLE-panel",
            "status": "synthetic_no_corrections",
            "panel_path": (scenario.sample_dir / "panel.csv").as_posix(),
            "panel_sha256": panel_sha,
            "rows": len(panel_rows),
            "generator": "tools/make_sample.py",
            "seed": SEED,
        }
    )
    files["sr02_primary.json"] = json_bytes(
        sr02_primary_config(
            scenario, panel_sha, len(panel_rows), sha256_bytes(files["base_rules.csv"])
        )
    )

    for name, payload in files.items():
        (sample / name).write_bytes(payload)
    hashes = {name: sha256_bytes(payload) for name, payload in files.items()}
    template_document = json.loads(template.read_text(encoding="utf-8"))
    offsets = (
        measure_tier_offsets(workspace, scenario, hashes, template_document, panel_rows)
        if scenario.tier
        else None
    )
    receipt = {
        "generator": "tools/make_sample.py",
        "seed": SEED,
        "synthetic": True,
        "unknown_outcomes_final_year": unknown_final_year,
        "counts": counts,
        "files": hashes,
    }
    if scenario.tier:
        receipt["scenario"] = scenario.name
        receipt["tier_initial_rating_offset_by_year"] = offsets
    (sample / "manifest.json").write_bytes(json_bytes(receipt))
    write_chain_config(
        template_document, workspace / scenario.chain_config, scenario, hashes, offsets
    )
    return receipt


def measure_tier_offsets(
    workspace: Path,
    scenario: Scenario,
    hashes: dict[str, str],
    template_document: dict[str, Any],
    panel_rows: list[dict[str, str]],
) -> dict[str, float]:
    """The per-training-window initial-rating offsets the chain config declares.

    Runs the package's own ``tier_stream`` on the written tarball (so the stream is the
    one the chain will build, satellite dating included) and ``tier_elo.measure_offset``
    on it at every horizon ``tier_elo`` will use, with the tour stream the features
    stage will hand it (every panel row; primary-identity rows fix first tour arrival).
    ``tier_elo`` re-measures at run time and refuses a declared value that drifts.
    """
    from tennislab.chain.common import year_plan
    from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache
    from tennislab.ratings import tier_elo, tier_stream

    chain = template_document["chain"]
    plan = year_plan(template_document)
    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace.resolve())
    reset_workspace_cache()
    try:
        with tempfile.TemporaryDirectory(dir=workspace, prefix="tier_measure.") as scratch:
            sample = scenario.sample_dir.as_posix()
            stream = tier_stream.build(
                {
                    "year_plan": template_document["year_plan"],
                    "tier_stream": {
                        "archive": {
                            "path": f"{sample}/archive.tar.gz",
                            "sha256": hashes["archive.tar.gz"],
                            "tar_root": TAR_ROOT,
                        },
                        "inventory": {
                            "path": f"{sample}/snapshot_file_inventory.csv",
                            "sha256": hashes["snapshot_file_inventory.csv"],
                        },
                        "archive_manifest": {
                            "path": f"{sample}/archive_manifest.json",
                            "sha256": hashes["archive_manifest.json"],
                        },
                        "last_year": LAST_SEASON,
                        "parameters": {
                            "first_year": scenario.tier_first_year,
                            "elo_start_year": FIRST_SEASON,
                            "experience_start_year": scenario.tier_first_year,
                            "serve_counts_start_year": scenario.serve_counts_start_year,
                            "reported_date_offset_days": chain["tier_reported_date_offset_days"],
                            "satellite_circuit_dating": chain["tier_satellite_circuit_dating"],
                        },
                        "output_dir": scratch,
                    },
                }
            )
            if stream["totals"].get("circuit_bases", 0) == 0:
                raise RuntimeError("the tier scenario exercises no satellite circuit")
            elo_lower, _ = tier_elo.lower_rows(
                Path(scratch) / "tier_results.csv.gz",
                elo_start_year=FIRST_SEASON,
                experience_start_year=scenario.tier_first_year,
                panel_end_year=LAST_SEASON,
            )
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()
    tour = [
        {
            "date": row["match_date"],
            "identity_tier": row["identity_tier"],
            "winner_id": row["player_a"] if row["a_won"] == "true" else row["player_b"],
            "loser_id": row["player_b"] if row["a_won"] == "true" else row["player_a"],
        }
        for row in panel_rows
    ]
    by_horizon: dict[int, dict[str, Any]] = {}
    offsets: dict[str, float] = {}
    for year in range(FIRST_SEASON, LAST_SEASON + 1):
        horizon = tier_elo.offset_year_horizon(year, plan)
        if horizon not in by_horizon:
            by_horizon[horizon] = tier_elo.measure_offset(
                tour,
                elo_lower,
                multipliers=tier_elo.DECLARED_MULTIPLIERS,
                lag_days=2,
                end_year=horizon,
                allow_empty=True,
            )
        offsets[str(year)] = float(by_horizon[horizon]["lower_tier_initial_offset"])
    if all(value == 0.0 for value in offsets.values()):
        raise RuntimeError("no training window measured a nonzero initial-rating offset")
    return offsets


def sr02_primary_config(
    scenario: Scenario, panel_sha: str, panel_rows: int, rules_sha: str
) -> dict[str, Any]:
    """A frozen SR02 primary config in the shape the replay and calibration read.

    The dynamic-filter block and both candidate menus follow the archive's SR02-C1
    shape; only the candidates the saved selections name are listed.
    """
    return {
        "experiment_id": "SAMPLE-SR02",
        "proposal_status": "frozen_for_real_execution",
        "parent_experiment": "synthetic sample",
        "chronology": {
            "availability_lag_calendar_days": 2,
            "history_identity_tier": "primary",
            "history_statuses": ["completed", "retired", "default"],
            "same_source_date_updates": "one_frozen_batch",
            "source_date_field": "match_date",
        },
        "dynamic_filter": {
            "global_initial_mean_logit": 0.5,
            "global_initial_sd": 0.12,
            "return_initial_sd": 0.2,
            "return_process_sd_per_60_days": 0.04,
            "serve_initial_sd": 0.2,
            "serve_process_sd_per_60_days": 0.04,
            "solver_gradient_tolerance": 1e-06,
            "solver_max_iterations": 50,
            "solver_newton_decrement_tolerance": 1e-07,
            "surface_initial_sd": 0.08,
            "surface_mean_initial_sd": 0.08,
            "surface_process_sd_per_60_days": 0.0,
            "tournament_initial_sd": 0.06,
        },
        "hyperparameter_selection_proposal": {
            "candidate_menu": [
                {
                    "candidate_id": DYNAMIC_CANDIDATE,
                    "global_initial_sd": 0.15,
                    "prior_bundle": "moderate",
                    "role_initial_sd": 0.3,
                    "role_process_sd_per_60_days": 0.05,
                    "shared_surface_initial_sd": 0.04,
                    "surface_mean_initial_sd": 0.1,
                    "tournament_initial_sd": 0.08,
                }
            ],
            "fallback_candidate_id": DYNAMIC_CANDIDATE,
            "status": "frozen_before_real_fit",
        },
        "unadjusted_baseline": {
            "name": "unadjusted_decayed_marginal_logit_additive",
            "count_half_life_days": 180.0,
            "overall_prior_denominator_units": 50.0,
            "surface_prior_denominator_units": 50.0,
            "selection_proposal": {
                "candidate_menu": [
                    {
                        "candidate_id": CONTROL_CANDIDATE,
                        "half_life_days": 180.0,
                        "overall_prior_units": 250.0,
                        "surface_prior_units": 250.0,
                    }
                ],
                "fallback_candidate_id": CONTROL_CANDIDATE,
            },
        },
        "selection_years": list(range(FIRST_SEASON, LAST_SEASON + 1)),
        "input": {
            "manifest_path": (scenario.sample_dir / "panel_manifest.json").as_posix(),
            "panel_path": (scenario.sample_dir / "panel.csv").as_posix(),
            "panel_rows": panel_rows,
            "panel_sha256": panel_sha,
        },
        "match_conversion": {
            "missing_rule": "emit_point_probabilities_and_refuse_match_probability",
            "rule_mapping_path": (scenario.sample_dir / "base_rules.csv").as_posix(),
            "rule_mapping_sha256": rules_sha,
        },
        "execution_binding": {
            "dynamic_path": "tennislab.dynamics.dynamic",
            "dynamic_sha256": "",
            "runner_path": "tennislab.dynamics.path_runner",
            "runner_sha256": "",
        },
    }


def write_chain_config(
    document: dict[str, Any],
    target: Path,
    scenario: Scenario,
    hashes: dict[str, str],
    offsets: dict[str, float] | None,
) -> None:
    """Re-pin every sample hash in the chain config; every other field is the template's.

    The tier scenario also declares the measured initial-rating offsets, the one chain
    field the generator computes rather than copies.
    """
    chain = document["chain"]
    inputs = chain["inputs"]
    prefix = scenario.sample_dir.as_posix() + "/"

    def sample_name(entry: dict[str, Any]) -> str | None:
        path = entry.get("path", "")
        return path[len(prefix) :] if path.startswith(prefix) else None

    for entry in inputs.values():
        if isinstance(entry, dict) and (name := sample_name(entry)) in hashes:
            entry["sha256"] = hashes[name]
    overrides = chain["stage_config_overrides"]
    overrides["rule_mapping"]["rule_carry_forward"]["extended_panel"]["sha256"] = hashes[
        "panel.csv"
    ]
    overrides["rankings"]["archive"]["sha256"] = hashes["archive.tar.gz"]
    if offsets is not None:
        chain["tier_initial_rating_offset_by_year"] = offsets
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json_bytes(document))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="base",
        help="which committed sample to write (default: base)",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="root under which data/sample[_tier] and configs/chains/sample_atp[_tier].json "
        "are written",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help="the chain config whose sample hashes are re-pinned (default: the committed "
        "one for the scenario)",
    )
    parser.add_argument(
        "--unknown-outcomes-final-year",
        action="store_true",
        help="blank every outcome of the final season, as a prospective run would have it "
        "(base scenario only)",
    )
    args = parser.parse_args(argv)
    scenario = SCENARIOS[args.scenario]
    if args.unknown_outcomes_final_year and scenario.tier:
        parser.error("--unknown-outcomes-final-year applies to the base scenario only")
    receipt = write_sample(
        args.workspace,
        scenario=scenario,
        unknown_final_year=args.unknown_outcomes_final_year,
        template=args.template if args.template is not None else scenario.chain_config,
    )
    print(
        json.dumps(
            {"counts": receipt["counts"], "files": receipt["files"]}, indent=2, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
