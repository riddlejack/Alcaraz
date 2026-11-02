"""The all-tier table's raw rows: every archive match of every tier, dated and oriented.

One row per match in ``atp_matches_YYYY.csv`` (tour), ``atp_matches_qual_chall_YYYY.csv``
and ``atp_matches_futures_YYYY.csv`` from each family's first year to ``max_year``. The
tarball, its inventory and the archive manifest are verified as in ``tier_stream``, and
every member is checked against the inventory before it is parsed; a member of a year
above ``max_year`` is never opened, and a row whose ``tourney_date`` year exceeds
``max_year`` is dropped as soon as it is parsed.

**Exclusions.** Team events among tour rows (level ``D``, ``Atp Cup``, ``Laver Cup`` and
any tourney with a Dusseldorf round-robin row, the World Team Cup), and rows with a
missing player id or the winner equal to the loser. Walkovers, defaults and unparseable
scores stay: they are rows of the table, flagged by its targets.

**Dates.** A lower-tier row takes its release date from the previous version's tier
stream (``tier_results.csv.gz``), joined on family and ``tourney_id/match_num``; a row the
stream leaves out (walkovers and other non-results) takes the latest stream date of its
edition, or ``tourney_date + 7`` if the edition has none. A tour row joined to the
previous version's panel (on ``source_key``, with the same two players) takes the panel's
match date; any other tour row takes ``tourney_date`` plus a per-round offset (the median
schedule of two-week Slams, big Masters draws and ordinary weeks).

**Orientation.** Panel rows keep the panel's ``player_a``/``player_b``; every other row has
a = the smaller player id.

**Static facts.** Age, height and hand come from the row, with ``atp_players.csv`` filling
a missing value (age from the date of birth at ``tourney_date``); ages outside 13-60 and
heights outside 155-215 cm are treated as missing.

Only these files are read: the panel for ``source_key``, ``match_id``, ``match_date``,
``player_a``, ``player_b`` and ``season``; the tier stream for ``match_id``, ``date``,
``tier`` and ``season``. Rows of either above ``max_year`` are skipped on ``season``.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import math
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.chain.common import ChainError, relative_to_root, require_hash, resolve_under_root
from tennislab.ratings.tier_stream import verify_custody

csv.field_size_limit(1 << 24)

EPOCH_ORDINAL = dt.date(1970, 1, 1).toordinal()
FAMILIES = {
    "atp_tour": "atp/atp_matches_{year}.csv",
    "atp_qual_chall": "atp/atp_matches_qual_chall_{year}.csv",
    "atp_futures": "atp/atp_matches_futures_{year}.csv",
}
PLAYERS_MEMBER = "atp/atp_players.csv"
SIDE_FIELDS = ("id", "seed", "entry", "hand", "ht", "age", "rank", "rank_points")
MATCH_FIELDS = (
    "tourney_id",
    "tourney_name",
    "surface",
    "draw_size",
    "tourney_level",
    "tourney_date",
    "match_num",
    *(f"{side}_{name}" for side in ("winner", "loser") for name in SIDE_FIELDS),
    "score",
    "best_of",
    "round",
    "minutes",
    *(f"{side}_{name}" for side in ("w", "l") for name in ("svpt", "1stWon", "2ndWon")),
)
QUALIFYING_ROUNDS = ("Q1", "Q2", "Q3", "Q4")
# Day offsets from tourney_date for tour rows the panel does not date.
OFFSET_SLAM = {"R128": 1, "R64": 3, "R32": 5, "R16": 7, "QF": 9, "SF": 11, "F": 13}
OFFSET_BIG_MASTERS = {"R128": 2, "R64": 4, "R32": 6, "R16": 7, "QF": 9, "SF": 11, "F": 12}
OFFSET_WEEK = {
    "R128": 1,
    "R64": 1,
    "R32": 1,
    "R16": 3,
    "QF": 4,
    "SF": 5,
    "F": 6,
    "RR": 2,
    "ER": 1,
    "BR": 6,
}
UNKNOWN_EDITION_OFFSET = 7
HANDS = ("R", "L", "A")


class AllTierSourceError(ChainError):
    """Fail-closed custody, schema or join error in the all-tier source rows."""


def to_day(value: dt.date) -> int:
    return value.toordinal() - EPOCH_ORDINAL


def iso_day(text: str) -> int:
    return to_day(dt.date.fromisoformat(text))


def day_iso(day: int) -> str:
    return dt.date.fromordinal(day + EPOCH_ORDINAL).isoformat()


def number(text: str) -> float:
    """A source cell as a float, NaN when blank or unparseable."""
    if not text or "_" in text:
        return math.nan
    try:
        return float(text)
    except ValueError:
        return math.nan


def numbers(values: Any) -> np.ndarray:
    return np.array([number(v) for v in values], dtype=float)


def compact_date(text: str) -> float:
    """A ``YYYYMMDD`` date as a day number, NaN when it is not a valid date."""
    try:
        return float(to_day(dt.datetime.strptime(text, "%Y%m%d").date()))
    except ValueError:
        return math.nan


@dataclass
class SourceRows:
    """Columns of the kept rows, in archive order (year, then tour/qual-chall/futures)."""

    columns: dict[str, np.ndarray]
    manifest: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.columns["row_id"])

    def __getitem__(self, name: str) -> np.ndarray:
        return self.columns[name]

    def subset(self, mask: np.ndarray) -> SourceRows:
        return SourceRows({k: v[mask] for k, v in self.columns.items()}, dict(self.manifest))

    def replace(self, **columns: np.ndarray) -> SourceRows:
        return SourceRows({**self.columns, **columns}, dict(self.manifest))


# ------------------------------------------------------------------ reading


def archive_members(
    section: Mapping[str, Any], wanted: set[str]
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """The payloads of ``wanted`` members, each verified against the pinned inventory."""
    paths, hashes = verify_custody(section)
    with paths["inventory"].open(newline="", encoding="utf-8") as handle:
        pinned = {row["path"]: row["sha256"] for row in csv.DictReader(handle)}
    tar_root = str(section["archive"]["tar_root"])
    payloads: dict[str, bytes] = {}
    with tarfile.open(paths["archive"], "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            name = member.name
            relative = name[len(tar_root) + 1 :] if name.startswith(tar_root + "/") else name
            if relative not in wanted:
                continue
            payload = archive.extractfile(member).read()
            if pinned.get(relative) != hashlib.sha256(payload).hexdigest():
                raise AllTierSourceError(
                    f"member absent from or differing from the inventory: {relative}"
                )
            payloads[relative] = payload
    missing = sorted(wanted - set(payloads))
    if missing:
        raise AllTierSourceError(f"members absent from the archive: {missing}")
    custody = {
        name: {"path": relative_to_root(paths[name]), "sha256": hashes[name]} for name in hashes
    }
    members = {name: hashlib.sha256(payloads[name]).hexdigest() for name in sorted(payloads)}
    return payloads, {"custody": custody, "members": members}


def parse_csv(payload: bytes, member: str) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    header = next(reader, None)
    if not header:
        raise AllTierSourceError(f"empty member: {member}")
    width = len(header)
    rows = []
    for row in reader:
        if not row:
            continue
        if len(row) != width:
            raise AllTierSourceError(f"ragged row in {member}: {row[:3]}")
        rows.append(row)
    return header, rows


def read_matches(payloads: Mapping[str, bytes], members: list[tuple[str, int, str]], max_year: int):
    """Column lists of every match row under the year ceiling, plus family and season."""
    columns: dict[str, list[Any]] = {name: [] for name in (*MATCH_FIELDS, "family", "season")}
    for family, year, member in members:
        header, rows = parse_csv(payloads[member], member)
        index = {name: i for i, name in enumerate(header)}
        absent = [name for name in MATCH_FIELDS if name not in index]
        if absent:
            raise AllTierSourceError(f"{member} lacks {absent}")
        date_at = index["tourney_date"]
        for row in rows:
            if int(row[date_at][:4]) > max_year:
                continue
            for name in MATCH_FIELDS:
                columns[name].append(row[index[name]])
            columns["family"].append(family)
            columns["season"].append(year)
    return columns


def read_panel(path: Path, max_year: int) -> dict[str, tuple[str, int, int, int]]:
    """source_key -> (match_id, match day, player_a, player_b), seasons up to ``max_year``."""
    out: dict[str, tuple[str, int, int, int]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        index = {name: i for i, name in enumerate(next(reader))}
        season = index["season"]
        for row in reader:
            if int(row[season]) > max_year:
                continue
            out[row[index["source_key"]]] = (
                row[index["match_id"]],
                iso_day(row[index["match_date"]]),
                int(row[index["player_a"]]),
                int(row[index["player_b"]]),
            )
    return out


def read_tier_dates(path: Path, max_year: int) -> dict[tuple[str, str], tuple[int, str]]:
    """(family, tourney_id/match_num) -> (release day, tier), seasons up to ``max_year``."""
    out: dict[tuple[str, str], tuple[int, str]] = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        index = {name: i for i, name in enumerate(next(reader))}
        season, match_id, date, tier = (index[n] for n in ("season", "match_id", "date", "tier"))
        for row in reader:
            if int(row[season]) > max_year:
                continue
            _, family, key = row[match_id].split(":", 2)
            out[(family, key)] = (iso_day(row[date]), row[tier])
    return out


def read_players(payload: bytes) -> tuple[dict[int, float], dict[int, str], dict[int, float]]:
    """Date of birth (day number), hand and height by player id; the first row of an id wins."""
    header, rows = parse_csv(payload, PLAYERS_MEMBER)
    index = {name: i for i, name in enumerate(header)}
    birth: dict[int, float] = {}
    hand: dict[int, str] = {}
    height: dict[int, float] = {}
    for row in rows:
        pid = number(row[index["player_id"]])
        if math.isnan(pid):
            continue
        pid_int = int(pid)
        if pid_int in birth:
            continue
        birth[pid_int] = compact_date(row[index["dob"]])
        hand[pid_int] = row[index["hand"]]
        height[pid_int] = number(row[index["height"]])
    return birth, hand, height


# ------------------------------------------------------------------ the rows


def tier_of_lower(family: str, level: str, round_name: str) -> str:
    if family == "atp_futures":
        return "futures"
    if level == "C" and round_name not in QUALIFYING_ROUNDS:
        return "challenger"
    return "qualifying"


def tour_offset(level: str, draw: float, round_name: str) -> int:
    if level == "G" or (level != "M" and draw >= 128):
        return OFFSET_SLAM.get(round_name, 7)
    if level == "M" and draw >= 96:
        return OFFSET_BIG_MASTERS.get(round_name, 6)
    return OFFSET_WEEK.get(round_name, 3)


def load_rows(section: Mapping[str, Any], max_year: int) -> SourceRows:
    """Read, exclude, date, orient and complete the rows of every tier up to ``max_year``."""
    first_years = {name: int(year) for name, year in section["first_year"].items()}
    if set(first_years) != set(FAMILIES):
        raise AllTierSourceError(f"first_year must name the families {sorted(FAMILIES)}")
    members = [
        (family, year, FAMILIES[family].format(year=year))
        for year in range(min(first_years.values()), max_year + 1)
        for family in FAMILIES
        if year >= first_years[family]
    ]
    payloads, custody = archive_members(
        section, {member for _, _, member in members} | {PLAYERS_MEMBER}
    )
    manifest: dict[str, Any] = {"max_year": max_year, "first_year": first_years, **custody}
    raw = read_matches(payloads, members, max_year)
    n0 = len(raw["family"])

    family = np.array(raw["family"], dtype=object)
    level = np.array(raw["tourney_level"], dtype=object)
    name = np.array(raw["tourney_name"], dtype=object)
    round_name = np.array(raw["round"], dtype=object)
    tourney = np.array(raw["tourney_id"], dtype=object)
    world_team_cup = {
        t
        for t, n, r in zip(tourney, name, round_name, strict=True)
        if n == "Dusseldorf" and r == "RR"
    }
    team = (family == "atp_tour") & (
        (level == "D")
        | np.isin(name, ["Atp Cup", "Laver Cup"])
        | np.array([t in world_team_cup for t in tourney], dtype=bool)
    )
    winner_num, loser_num = numbers(raw["winner_id"]), numbers(raw["loser_id"])
    bad_ids = np.isnan(winner_num) | np.isnan(loser_num) | (winner_num == loser_num)
    exclusions = {}
    for reason, mask in (("team_event", team), ("missing_or_equal_player_ids", bad_ids & ~team)):
        fams, counts = np.unique(family[mask], return_counts=True)
        exclusions[reason] = {str(f): int(c) for f, c in zip(fams, counts, strict=True)}
    keep = ~(team | bad_ids)
    manifest.update({"exclusions": exclusions, "source_rows_read": n0})

    cols = {k: np.array(v, dtype=object)[keep] for k, v in raw.items()}
    cols["season"] = np.array(raw["season"], dtype=np.int64)[keep]
    winner = np.array([int(v) for v in cols["winner_id"]], dtype=np.int64)
    loser = np.array([int(v) for v in cols["loser_id"]], dtype=np.int64)
    match_num = np.array([int(v) for v in cols["match_num"]], dtype=np.int64)
    key = np.array(
        [f"{t}/{m}" for t, m in zip(cols["tourney_id"], match_num, strict=True)], dtype=object
    )
    row_id = np.array([f"{f}:{k}" for f, k in zip(cols["family"], key, strict=True)], dtype=object)
    tday = np.array(
        [to_day(dt.datetime.strptime(v, "%Y%m%d").date()) for v in cols["tourney_date"]],
        dtype=np.int64,
    )

    inputs = section["previous_run"]
    panel_path = resolve_under_root(inputs["panel"]["path"], label="panel")
    tier_path = resolve_under_root(inputs["tier_results"]["path"], label="tier_results")
    manifest["previous_run"] = {
        "panel": {
            "path": relative_to_root(panel_path),
            "sha256": require_hash(panel_path, inputs["panel"].get("sha256"), label="panel"),
        },
        "tier_results": {
            "path": relative_to_root(tier_path),
            "sha256": require_hash(
                tier_path, inputs["tier_results"].get("sha256"), label="tier_results"
            ),
        },
    }
    panel = read_panel(panel_path, max_year)
    tier_dates = read_tier_dates(tier_path, max_year)

    n = len(key)
    fam = cols["family"]
    lvl = cols["tourney_level"]
    rnd = cols["round"]
    draw = np.nan_to_num(numbers(cols["draw_size"]), nan=0.0)
    day = np.zeros(n, dtype=np.int64)
    source = np.empty(n, dtype=object)
    tier = np.empty(n, dtype=object)
    match_id = np.full(n, "", dtype=object)
    player_a = np.minimum(winner, loser)
    player_b = np.maximum(winner, loser)
    edition_last: dict[tuple[str, str], int] = {}
    for i in range(n):
        if fam[i] != "atp_tour":
            hit = tier_dates.get((fam[i], key[i]))
            if hit is not None:
                day[i], source[i], tier[i] = hit[0], "tier_stream", hit[1]
                edition = (fam[i], key[i].rsplit("/", 1)[0])
                edition_last[edition] = max(edition_last.get(edition, -(10**9)), hit[0])
    panel_mismatch: list[str] = []
    joined_lower = disagreements = 0
    unjoined: dict[str, dict[str, int]] = {}
    for i in range(n):
        f = fam[i]
        if f == "atp_tour":
            tier[i] = "tour"
            hit = panel.get(key[i])
            if hit is not None and {hit[2], hit[3]} == {winner[i], loser[i]}:
                match_id[i], day[i], player_a[i], player_b[i] = hit
                source[i] = "panel"
                continue
            if hit is not None:
                panel_mismatch.append(key[i])
            day[i] = tday[i] + tour_offset(lvl[i], draw[i], rnd[i])
            source[i] = "round_offset"
            continue
        expected = tier_of_lower(f, lvl[i], rnd[i])
        if source[i] == "tier_stream":
            joined_lower += 1
            disagreements += int(tier[i] != expected)
            continue
        tier[i] = expected
        edition = (f, key[i].rsplit("/", 1)[0])
        if edition in edition_last:
            day[i], source[i] = edition_last[edition], "edition_release_date"
        else:
            day[i], source[i] = tday[i] + UNKNOWN_EDITION_OFFSET, "tourney_date_plus7"
        unjoined.setdefault(f, {}).setdefault(source[i], 0)
        unjoined[f][source[i]] += 1
    lower = fam != "atp_tour"
    manifest["join"] = {
        "lower_tier_rows": int(lower.sum()),
        "lower_tier_joined_to_tier_stream": joined_lower,
        "lower_tier_unjoined_by_family_and_fallback": unjoined,
        "tier_label_disagreements_with_level_rule": disagreements,
        "tier_stream_keys_not_in_source": len(
            set(tier_dates) - set(zip(fam[lower], key[lower], strict=True))
        ),
        "tour_rows": int((~lower).sum()),
        "tour_rows_joined_to_panel": int((source == "panel").sum()),
        "panel_keys_with_player_mismatch": panel_mismatch,
        "panel_keys_not_in_source": len(set(panel) - set(key[~lower])),
    }

    birth, hand, height = read_players(payloads[PLAYERS_MEMBER])
    out = {
        "row_id": row_id,
        "family": fam,
        "season": cols["season"],
        "tourney_id": cols["tourney_id"],
        "match_num": match_num,
        "tourney_level": lvl,
        "round": rnd,
        "surface": cols["surface"],
        "draw_size": cols["draw_size"],
        "best_of": cols["best_of"],
        "score": cols["score"],
        "minutes": cols["minutes"],
        "winner_id": winner,
        "loser_id": loser,
        "day": day,
        "date_source": source,
        "tier": tier,
        "match_id": match_id,
        "player_a": player_a,
        "player_b": player_b,
        "tourney_day": tday,
    }
    for name in ("w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon"):
        out[name] = cols[name]
    for side in ("winner", "loser"):
        for name in ("seed", "entry", "rank", "rank_points"):
            out[f"{side}_{name}"] = cols[f"{side}_{name}"]
        ids = out[f"{side}_id"]
        age = numbers(cols[f"{side}_age"])
        born = np.array([birth.get(int(x), np.nan) for x in ids], dtype=float)
        age = np.where(np.isnan(age), (tday - born) / 365.25, age)
        with np.errstate(invalid="ignore"):
            out[f"{side}_age"] = np.where((age >= 13) & (age <= 60), age, np.nan)
        ht = numbers(cols[f"{side}_ht"])
        ht = np.where(np.isnan(ht), [height.get(int(x), np.nan) for x in ids], ht)
        with np.errstate(invalid="ignore"):
            out[f"{side}_ht"] = np.where((ht >= 155) & (ht <= 215), ht, np.nan)
        raw_hand = cols[f"{side}_hand"]
        out[f"{side}_hand"] = np.array(
            [h if h in HANDS else hand.get(int(x), "") for h, x in zip(raw_hand, ids, strict=True)],
            dtype=object,
        )
    manifest["rows_kept"] = n
    return SourceRows(out, manifest)
