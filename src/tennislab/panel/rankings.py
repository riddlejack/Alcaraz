"""Extract and mechanically qualify a pinned ranking stream for a configured span and tour.

Stage ``rankings``. Ported from the archive's ``WTA02_models/qualify_rankings.py``, which
is a superset of the ``TIER01_models`` revision: the TIER01 file's literal ``atp/`` member
names are the ``ATP`` entry of a per-tour profile, the WTA ranking files carry a fifth
``tours`` column that is asserted and not read, the WTA subtree has no
``matches_data_dictionary.txt``, and ``qualification.json`` gains a ``tour`` key. Row
validation, the duplicate policy, the identity policy, the retrospective join and the
14-day staleness rule are the TIER01 behaviour unchanged; the tour selects which archive
members are opened, not how a row is judged.

What changed in the port: the module-level ``WINDOW``/``OUT_DIR``/``RANKING_MEMBERS``
globals and their ``configure_window``/``configure_tour`` installers are replaced by a
frozen :class:`Selection` threaded through the pure functions; paths resolve through
``resolve_under_root`` instead of a root computed from the source file's location.

Reading ``<tour>_matches_<year>.csv`` means reading that season's winner and loser. With
``result_year_max`` inside a reserved window this stage touches reserved outcomes and must
be logged as such before it runs.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import gzip
import io
import json
import statistics
import tarfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    read_config,
    relative_to_root,
    resolve_under_root,
    sha256,
    sha256_bytes,
)

ARCHIVE_COMMIT = "83733587353df8a41f2fd4f516147d5aa83f5a8d"
ARCHIVE_ROOT = f"tennis-sackmann-archive-{ARCHIVE_COMMIT}"
ARCHIVE_SHA256 = "2a1ef3a848210f1067657e3399980365d734f8134463ab4114b67ef8c3d47bb4"
ARCHIVE_PATH = f"data/raw/ARCHIVE01/snapshot/{ARCHIVE_ROOT}.tar.gz"


@dataclass(frozen=True)
class ArchivePin:
    """The tarball the stage reads: its path, the hash it must carry, its member root.

    The default is ARCHIVE01, the pinned Sackmann mirror every accepted run read. A
    config may declare another tarball with the same member layout under ``archive``
    (``path``, ``sha256``, ``tar_root`` and optionally ``commit``); the sample chain
    does, with a synthetic tarball. ``commit`` is what the manifests record as
    ``archive_commit`` and defaults to the member root.
    """

    path: str = ARCHIVE_PATH
    sha256: str = ARCHIVE_SHA256
    root: str = ARCHIVE_ROOT
    commit: str = ARCHIVE_COMMIT

    @classmethod
    def from_config(cls, document: dict[str, Any] | None) -> ArchivePin:
        if not document or "archive" not in document:
            return cls()
        section = document["archive"]
        try:
            root = str(section["tar_root"])
            return cls(
                path=str(section["path"]),
                sha256=str(section["sha256"]),
                root=root,
                commit=str(section.get("commit", root)),
            )
        except (KeyError, TypeError) as error:
            raise ChainError(
                "config archive must be an object with path, sha256 and tar_root"
            ) from error


DEFAULT_ARCHIVE = ArchivePin()

DEFAULT_WINDOW: dict[str, int] = {
    "ranking_year_min": 2000,
    "ranking_year_max": 2024,
    "result_year_min": 2005,
    "result_year_max": 2024,
}
# The 20s file is the last decade file in the pinned mirror; any window that reaches
# beyond it must also read the current file.
CURRENT_MEMBER_FROM_YEAR = 2026

BIO_HEADER = ["player_id", "name_first", "name_last", "hand", "dob", "ioc", "height", "wikidata_id"]
NORMALIZED_HEADER = [
    "effective_date",
    "rank",
    "player_id",
    "ranking_points",
    "source_member",
    "source_physical_line",
]
REQUIRED_RESULT_FIELDS = {
    "tourney_date",
    "winner_id",
    "winner_name",
    "winner_rank",
    "winner_rank_points",
    "loser_id",
    "loser_name",
    "loser_rank",
    "loser_rank_points",
}


@dataclass(frozen=True)
class TourProfile:
    """One tour's archive member names. ATP's lists are the TIER01 literals unchanged."""

    tour: str
    decade_ranking_members: tuple[str, ...]
    current_ranking_member: str
    ranking_header: tuple[str, ...]
    result_member: str
    player_member: str
    document_members: tuple[str, ...]


TOUR_PROFILES: dict[str, TourProfile] = {
    "ATP": TourProfile(
        tour="ATP",
        decade_ranking_members=(
            "atp/atp_rankings_00s.csv",
            "atp/atp_rankings_10s.csv",
            "atp/atp_rankings_20s.csv",
        ),
        current_ranking_member="atp/atp_rankings_current.csv",
        ranking_header=("ranking_date", "rank", "player", "points"),
        result_member="atp/atp_matches_{year}.csv",
        player_member="atp/atp_players.csv",
        document_members=(
            "LICENSE",
            "README.md",
            "atp/UPSTREAM_README.md",
            "atp/matches_data_dictionary.txt",
            "atp/atp_players.csv",
        ),
    ),
    "WTA": TourProfile(
        tour="WTA",
        decade_ranking_members=(
            "wta/wta_rankings_00s.csv",
            "wta/wta_rankings_10s.csv",
            "wta/wta_rankings_20s.csv",
        ),
        current_ranking_member="wta/wta_rankings_current.csv",
        # The WTA ranking files carry a fifth column, `tours` (tournaments played).
        # It is asserted so a schema change is caught, and it is not read.
        ranking_header=("ranking_date", "rank", "player", "points", "tours"),
        result_member="wta/wta_matches_{year}.csv",
        player_member="wta/wta_players.csv",
        document_members=(
            "LICENSE",
            "README.md",
            "wta/UPSTREAM_README.md",
            "wta/wta_players.csv",
        ),
    ),
}


@dataclass(frozen=True)
class Selection:
    """The configured tour and span, and the archive members they select."""

    profile: TourProfile
    window: dict[str, int]
    ranking_members: tuple[str, ...]
    result_members: tuple[str, ...]
    selected_members: tuple[str, ...]

    @property
    def ranking_header(self) -> list[str]:
        return list(self.profile.ranking_header)

    @property
    def player_member(self) -> str:
        return self.profile.player_member

    def normalized_output_name(self) -> str:
        return (
            f"rankings_{self.window['ranking_year_min']}_{self.window['ranking_year_max']}.csv.gz"
        )


def select(tour: str, window: dict[str, Any] | None = None) -> Selection:
    """Install one tour profile and the configured ranking/result span."""
    key = str(tour).upper()
    if key not in TOUR_PROFILES:
        raise ChainError(f"unknown tour {tour!r}; expected one of {sorted(TOUR_PROFILES)}")
    profile = TOUR_PROFILES[key]
    merged = dict(DEFAULT_WINDOW)
    merged.update(window or {})
    if set(merged) != set(DEFAULT_WINDOW):
        raise ChainError(f"window keys must be exactly {sorted(DEFAULT_WINDOW)}")
    for name, value in merged.items():
        if not isinstance(value, int) or isinstance(value, bool) or not 1990 <= value <= 2100:
            raise ChainError(f"{name} must be a plausible integer season")
    if merged["ranking_year_min"] > merged["ranking_year_max"]:
        raise ChainError("ranking_year_min exceeds ranking_year_max")
    if merged["result_year_min"] > merged["result_year_max"]:
        raise ChainError("result_year_min exceeds result_year_max")
    ranking_members = list(profile.decade_ranking_members)
    if merged["ranking_year_max"] >= CURRENT_MEMBER_FROM_YEAR:
        ranking_members.append(profile.current_ranking_member)
    result_members = [
        profile.result_member.format(year=year)
        for year in range(merged["result_year_min"], merged["result_year_max"] + 1)
    ]
    return Selection(
        profile=profile,
        window=merged,
        ranking_members=tuple(ranking_members),
        result_members=tuple(result_members),
        selected_members=tuple(list(profile.document_members) + ranking_members + result_members),
    )


def parse_positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed > 0 else None


def parse_nonnegative_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed >= 0 else None


def parse_yyyymmdd(value: str) -> dt.date | None:
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        return None
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def normalized_name(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return "".join(character for character in folded.casefold() if character.isalnum())


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def extract_selected(
    archive_path: Path,
    raw_dir: Path,
    out_dir: Path,
    selection: Selection,
    pin: ArchivePin = DEFAULT_ARCHIVE,
) -> list[dict[str, Any]]:
    if raw_dir.exists():
        raise ChainError(f"refusing to overwrite extracted raw directory: {raw_dir}")
    if sha256(archive_path) != pin.sha256:
        raise ChainError("preserved archive SHA-256 does not match the declared pin")
    raw_dir.mkdir(parents=True)
    records = []
    with tarfile.open(archive_path, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers() if member.isfile()}
        for relative in selection.selected_members:
            archive_name = f"{pin.root}/{relative}"
            member = members.get(archive_name)
            if member is None:
                raise ChainError(f"archive member missing: {archive_name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ChainError(f"cannot read archive member: {archive_name}")
            data = extracted.read()
            if len(data) != member.size:
                raise ChainError(f"archive member size mismatch: {archive_name}")
            destination = raw_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            records.append(
                {
                    "archive_member": relative,
                    "archive_member_bytes": member.size,
                    "archive_member_sha256": sha256_bytes(data),
                    "extracted_path": str(destination.relative_to(out_dir)),
                    "extracted_bytes": destination.stat().st_size,
                    "extracted_sha256": sha256(destination),
                    "input_output_hash_equal": sha256_bytes(data) == sha256(destination),
                }
            )
    return records


def read_biographies(
    raw_dir: Path, selection: Selection
) -> tuple[dict[int, dict[str, str]], list[dict[str, Any]], dict[str, Any]]:
    path = raw_dir / selection.player_member
    biographies: dict[int, dict[str, str]] = {}
    conflicts: list[dict[str, Any]] = []
    invalid_ids = 0
    duplicate_ids = 0
    rows = 0
    with path.open(encoding="utf-8-sig", errors="strict", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != BIO_HEADER:
            raise ChainError(f"unexpected biography header: {reader.fieldnames}")
        for row in reader:
            rows += 1
            player_id = parse_positive_int(row["player_id"])
            if player_id is None:
                invalid_ids += 1
                conflicts.append(
                    {
                        "conflict_type": "biography_invalid_player_id",
                        "player_id": row["player_id"],
                        "result_name": "",
                        "biography_name": f"{row['name_first']} {row['name_last']}".strip(),
                        "occurrences": 1,
                        "years": "",
                        "first_source_file": selection.player_member,
                        "first_physical_line": reader.line_num,
                        "first_tourney_date": "",
                        "first_side": "",
                    }
                )
                continue
            if player_id in biographies:
                duplicate_ids += 1
                existing = biographies[player_id]
                conflicts.append(
                    {
                        "conflict_type": "biography_duplicate_player_id",
                        "player_id": player_id,
                        "result_name": "",
                        "biography_name": (
                            f"{existing['name_first']} {existing['name_last']} | "
                            f"{row['name_first']} {row['name_last']}"
                        ),
                        "occurrences": 1,
                        "years": "",
                        "first_source_file": selection.player_member,
                        "first_physical_line": reader.line_num,
                        "first_tourney_date": "",
                        "first_side": "",
                    }
                )
                continue
            biographies[player_id] = row
    return (
        biographies,
        conflicts,
        {
            "rows": rows,
            "valid_unique_player_ids": len(biographies),
            "invalid_player_id_rows": invalid_ids,
            "duplicate_player_id_rows": duplicate_ids,
            "header": BIO_HEADER,
        },
    )


def read_results(
    raw_dir: Path, selection: Selection
) -> tuple[
    list[dict[str, Any]], dict[int, dict[str, Any]], list[dict[str, Any]], dict[str, list[str]]
]:
    appearances: list[dict[str, Any]] = []
    annual: dict[int, dict[str, Any]] = {}
    anomalies: list[dict[str, Any]] = []
    headers: dict[str, list[str]] = {}
    window = selection.window
    for year in range(window["result_year_min"], window["result_year_max"] + 1):
        relative = selection.profile.result_member.format(year=year)
        stats: dict[str, Any] = {
            "year": year,
            "source_member": relative,
            "match_rows": 0,
            "player_appearances": 0,
            "valid_player_id_appearances": 0,
            "missing_or_invalid_player_id_appearances": 0,
            "invalid_tourney_date_rows": 0,
            "tourney_date_year_differs_from_file_year_rows": 0,
            "distinct_player_ids_set": set(),
        }
        with (raw_dir / relative).open(encoding="utf-8-sig", errors="strict", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not REQUIRED_RESULT_FIELDS.issubset(reader.fieldnames):
                raise ChainError(f"result header missing required fields: {relative}")
            headers[relative] = reader.fieldnames
            for row in reader:
                stats["match_rows"] += 1
                match_date = parse_yyyymmdd(row["tourney_date"])
                if match_date is None:
                    stats["invalid_tourney_date_rows"] += 1
                    anomalies.append(
                        {
                            "anomaly_type": "result_invalid_tourney_date",
                            "source_file": relative,
                            "physical_line": reader.line_num,
                            "ranking_date": row["tourney_date"],
                            "rank": "",
                            "player": "",
                            "points": "",
                            "detail": "expected valid YYYYMMDD",
                        }
                    )
                elif match_date.year != year:
                    stats["tourney_date_year_differs_from_file_year_rows"] += 1
                    anomalies.append(
                        {
                            "anomaly_type": "result_tourney_date_year_differs_from_file_year",
                            "source_file": relative,
                            "physical_line": reader.line_num,
                            "ranking_date": row["tourney_date"],
                            "rank": "",
                            "player": "",
                            "points": "",
                            "detail": (
                                f"valid date year {match_date.year}; "
                                f"nominal result-file season {year}"
                            ),
                        }
                    )
                # outcome-history read: winner_id/loser_id name that season's result sides.
                for side in ("winner", "loser"):
                    stats["player_appearances"] += 1
                    player_id = parse_positive_int(row[f"{side}_id"])
                    if player_id is None:
                        stats["missing_or_invalid_player_id_appearances"] += 1
                    else:
                        stats["valid_player_id_appearances"] += 1
                        stats["distinct_player_ids_set"].add(player_id)
                    appearances.append(
                        {
                            "year": year,
                            "source_file": relative,
                            "physical_line": reader.line_num,
                            "tourney_date_raw": row["tourney_date"],
                            "tourney_date": match_date,
                            "side": side,
                            "player_id_raw": row[f"{side}_id"],
                            "player_id": player_id,
                            "result_name": row[f"{side}_name"],
                            "embedded_rank_raw": row[f"{side}_rank"],
                            "embedded_points_raw": row[f"{side}_rank_points"],
                        }
                    )
        annual[year] = stats
    return appearances, annual, anomalies, headers


Snapshot = tuple[dt.date, int, int | None, str, int]


def qualify_ranking_stream(
    raw_dir: Path,
    biographies: dict[int, dict[str, str]],
    result_player_ids: set[int],
    output_path: Path,
    selection: Selection,
) -> tuple[
    dict[int, dict[str, Any]],
    list[dict[str, Any]],
    dict[int, list[Snapshot]],
    dict[str, list[str]],
    dict[str, int],
]:
    annual: dict[int, dict[str, Any]] = {}
    anomalies: list[dict[str, Any]] = []
    snapshots: dict[int, list[Snapshot]] = defaultdict(list)
    headers: dict[str, list[str]] = {}
    excluded_by_file: dict[str, int] = defaultdict(int)
    window = selection.window
    expected_header = selection.ranking_header

    with output_path.open("wb") as raw_out:
        with gzip.GzipFile(fileobj=raw_out, mode="wb", mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text_out:
                writer = csv.writer(text_out, lineterminator="\n")
                writer.writerow(NORMALIZED_HEADER)
                for relative in selection.ranking_members:
                    previous_date: dt.date | None = None
                    current_date: dt.date | None = None
                    current_players: dict[int, tuple[int, str, str]] = {}
                    reported_duplicate_keys: set[tuple[dt.date, int]] = set()
                    with (raw_dir / relative).open(
                        encoding="utf-8-sig", errors="strict", newline=""
                    ) as handle:
                        reader = csv.DictReader(handle)
                        if reader.fieldnames != expected_header:
                            raise ChainError(
                                f"unexpected ranking header in {relative}: {reader.fieldnames}"
                            )
                        headers[relative] = reader.fieldnames
                        for row in reader:
                            date_value = parse_yyyymmdd(row["ranking_date"])
                            if date_value is None:
                                anomalies.append(
                                    {
                                        "anomaly_type": "ranking_invalid_date",
                                        "source_file": relative,
                                        "physical_line": reader.line_num,
                                        "ranking_date": row["ranking_date"],
                                        "rank": row["rank"],
                                        "player": row["player"],
                                        "points": row["points"],
                                        "detail": "expected valid YYYYMMDD",
                                    }
                                )
                                continue
                            if (
                                not window["ranking_year_min"]
                                <= date_value.year
                                <= window["ranking_year_max"]
                            ):
                                excluded_by_file[relative] += 1
                                continue
                            stats = annual.setdefault(
                                date_value.year,
                                {
                                    "year": date_value.year,
                                    "source_member": relative,
                                    "rows": 0,
                                    "valid_rows": 0,
                                    "invalid_numeric_rows": 0,
                                    "dates_set": set(),
                                    "players_set": set(),
                                    "bio_players_set": set(),
                                    "rows_with_biography": 0,
                                    "points_present_rows": 0,
                                    "points_missing_rows": 0,
                                    "duplicate_key_groups_set": set(),
                                    "duplicate_conflicting_groups_set": set(),
                                    "duplicate_key_excess_rows": 0,
                                    "date_order_decreases": 0,
                                },
                            )
                            stats["rows"] += 1
                            stats["dates_set"].add(date_value)
                            rank = parse_positive_int(row["rank"])
                            player_id = parse_positive_int(row["player"])
                            points = (
                                None
                                if row["points"] == ""
                                else parse_nonnegative_int(row["points"])
                            )
                            invalid_fields = []
                            if rank is None:
                                invalid_fields.append("rank")
                            if player_id is None:
                                invalid_fields.append("player")
                            if row["points"] != "" and points is None:
                                invalid_fields.append("points")
                            if invalid_fields:
                                stats["invalid_numeric_rows"] += 1
                                anomalies.append(
                                    {
                                        "anomaly_type": "ranking_invalid_numeric",
                                        "source_file": relative,
                                        "physical_line": reader.line_num,
                                        "ranking_date": row["ranking_date"],
                                        "rank": row["rank"],
                                        "player": row["player"],
                                        "points": row["points"],
                                        "detail": "invalid fields: " + ",".join(invalid_fields),
                                    }
                                )
                                continue
                            assert rank is not None and player_id is not None
                            if previous_date is not None and date_value < previous_date:
                                stats["date_order_decreases"] += 1
                                anomalies.append(
                                    {
                                        "anomaly_type": "ranking_date_order_decrease",
                                        "source_file": relative,
                                        "physical_line": reader.line_num,
                                        "ranking_date": row["ranking_date"],
                                        "rank": row["rank"],
                                        "player": row["player"],
                                        "points": row["points"],
                                        "detail": f"previous valid date {previous_date:%Y%m%d}",
                                    }
                                )
                            previous_date = date_value
                            if current_date != date_value:
                                current_date = date_value
                                current_players = {}
                            if player_id in current_players:
                                key = (date_value, player_id)
                                stats["duplicate_key_groups_set"].add(key)
                                stats["duplicate_key_excess_rows"] += 1
                                first_line, first_rank, first_points = current_players[player_id]
                                if (first_rank, first_points) != (row["rank"], row["points"]):
                                    stats["duplicate_conflicting_groups_set"].add(key)
                                if key not in reported_duplicate_keys:
                                    anomalies.append(
                                        {
                                            "anomaly_type": "ranking_duplicate_date_player_first",
                                            "source_file": relative,
                                            "physical_line": first_line,
                                            "ranking_date": date_value.strftime("%Y%m%d"),
                                            "rank": first_rank,
                                            "player": player_id,
                                            "points": first_points,
                                            "detail": "first row in duplicate key group",
                                        }
                                    )
                                    reported_duplicate_keys.add(key)
                                anomalies.append(
                                    {
                                        "anomaly_type": "ranking_duplicate_date_player_repeat",
                                        "source_file": relative,
                                        "physical_line": reader.line_num,
                                        "ranking_date": row["ranking_date"],
                                        "rank": row["rank"],
                                        "player": row["player"],
                                        "points": row["points"],
                                        "detail": "repeat row in duplicate key group",
                                    }
                                )
                            else:
                                current_players[player_id] = (
                                    reader.line_num,
                                    row["rank"],
                                    row["points"],
                                )
                            stats["valid_rows"] += 1
                            stats["players_set"].add(player_id)
                            if player_id in biographies:
                                stats["rows_with_biography"] += 1
                                stats["bio_players_set"].add(player_id)
                            if points is None:
                                stats["points_missing_rows"] += 1
                            else:
                                stats["points_present_rows"] += 1
                            writer.writerow(
                                [
                                    date_value.isoformat(),
                                    rank,
                                    player_id,
                                    "" if points is None else points,
                                    relative,
                                    reader.line_num,
                                ]
                            )
                            if player_id in result_player_ids:
                                snapshots[player_id].append(
                                    (date_value, rank, points, relative, reader.line_num)
                                )
    for rows in snapshots.values():
        rows.sort(key=lambda item: (item[0], item[1], item[4]))
    return annual, anomalies, snapshots, headers, dict(excluded_by_file)


def summarize_rankings(
    annual: dict[int, dict[str, Any]], selection: Selection
) -> list[dict[str, Any]]:
    rows = []
    window = selection.window
    for year in range(window["ranking_year_min"], window["ranking_year_max"] + 1):
        stats = annual.get(year)
        if stats is None:
            rows.append({"year": year, "source_member": "", "rows": 0})
            continue
        dates = sorted(stats["dates_set"])
        gaps = [(right - left).days for left, right in zip(dates, dates[1:], strict=False)]
        weekday_counts = {name: 0 for name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
        for date_value in dates:
            weekday_counts[date_value.strftime("%a")] += 1
        valid = stats["valid_rows"]
        players = len(stats["players_set"])
        rows.append(
            {
                "year": year,
                "source_member": stats["source_member"],
                "rows": stats["rows"],
                "valid_rows": valid,
                "invalid_numeric_rows": stats["invalid_numeric_rows"],
                "distinct_effective_dates": len(dates),
                "first_effective_date": dates[0].isoformat(),
                "last_effective_date": dates[-1].isoformat(),
                "effective_date_weekdays": ";".join(
                    f"{key}:{value}" for key, value in weekday_counts.items() if value
                ),
                "median_gap_days": statistics.median(gaps) if gaps else "",
                "max_gap_days": max(gaps) if gaps else "",
                "distinct_player_ids": players,
                "rows_with_biography": stats["rows_with_biography"],
                "row_biography_coverage_fraction": (
                    round(stats["rows_with_biography"] / valid, 8) if valid else ""
                ),
                "distinct_player_ids_in_biography": len(stats["bio_players_set"]),
                "distinct_player_biography_coverage_fraction": (
                    round(len(stats["bio_players_set"]) / players, 8) if players else ""
                ),
                "ranking_points_present_rows": stats["points_present_rows"],
                "ranking_points_missing_rows": stats["points_missing_rows"],
                "ranking_points_coverage_fraction": (
                    round(stats["points_present_rows"] / valid, 8) if valid else ""
                ),
                "duplicate_date_player_groups": len(stats["duplicate_key_groups_set"]),
                "duplicate_date_player_exact_groups": len(
                    stats["duplicate_key_groups_set"] - stats["duplicate_conflicting_groups_set"]
                ),
                "duplicate_date_player_conflicting_groups": len(
                    stats["duplicate_conflicting_groups_set"]
                ),
                "duplicate_date_player_excess_rows": stats["duplicate_key_excess_rows"],
                "date_order_decreases": stats["date_order_decreases"],
            }
        )
    return rows


def add_compact_conflict(
    conflicts: dict[tuple[Any, ...], dict[str, Any]],
    key: tuple[Any, ...],
    conflict_type: str,
    appearance: dict[str, Any],
    result_value: str,
    source_value: str,
) -> None:
    if key not in conflicts:
        conflicts[key] = {
            "conflict_type": conflict_type,
            "player_id": appearance["player_id_raw"],
            "result_value": result_value,
            "ranking_or_biography_value": source_value,
            "occurrences": 0,
            "years_set": set(),
            "first_source_file": appearance["source_file"],
            "first_physical_line": appearance["physical_line"],
            "first_tourney_date": appearance["tourney_date_raw"],
            "first_side": appearance["side"],
        }
    conflicts[key]["occurrences"] += 1
    conflicts[key]["years_set"].add(appearance["year"])


def join_results(
    appearances: list[dict[str, Any]],
    annual: dict[int, dict[str, Any]],
    biographies: dict[int, dict[str, str]],
    snapshots: dict[int, list[Snapshot]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    identity_conflicts: dict[tuple[Any, ...], dict[str, Any]] = {}
    ranking_conflicts: dict[tuple[Any, ...], dict[str, Any]] = {}
    distinct_bio: dict[int, set[int]] = defaultdict(set)
    distinct_prior: dict[int, set[int]] = defaultdict(set)
    gap_values: dict[int, list[int]] = defaultdict(list)

    for stats in annual.values():
        stats.update(
            {
                "appearances_with_biography": 0,
                "appearances_with_prior_ranking": 0,
                "appearances_with_unique_prior_ranking": 0,
                "appearances_with_ambiguous_prior_ranking": 0,
                "prior_ranking_within_7_days": 0,
                "prior_ranking_within_14_days": 0,
                "prior_ranking_within_28_days": 0,
                "same_date_ranking_appearances": 0,
                "earlier_date_ranking_appearances": 0,
                "embedded_rank_present": 0,
                "rank_comparable": 0,
                "rank_equal": 0,
                "rank_conflicts": 0,
                "embedded_points_present": 0,
                "points_comparable": 0,
                "points_equal": 0,
                "points_conflicts": 0,
            }
        )

    for appearance in appearances:
        year = appearance["year"]
        stats = annual[year]
        player_id = appearance["player_id"]
        if player_id is None:
            add_compact_conflict(
                identity_conflicts,
                ("result_missing_or_invalid_player_id", appearance["player_id_raw"]),
                "result_missing_or_invalid_player_id",
                appearance,
                appearance["result_name"],
                "",
            )
            continue
        biography = biographies.get(player_id)
        if biography is None:
            add_compact_conflict(
                identity_conflicts,
                ("result_player_id_missing_biography", player_id, appearance["result_name"]),
                "result_player_id_missing_biography",
                appearance,
                appearance["result_name"],
                "",
            )
        else:
            stats["appearances_with_biography"] += 1
            distinct_bio[year].add(player_id)
            bio_name = f"{biography['name_first']} {biography['name_last']}".strip()
            if normalized_name(appearance["result_name"]) != normalized_name(bio_name):
                add_compact_conflict(
                    identity_conflicts,
                    (
                        "normalized_result_biography_name_mismatch",
                        player_id,
                        appearance["result_name"],
                        bio_name,
                    ),
                    "normalized_result_biography_name_mismatch",
                    appearance,
                    appearance["result_name"],
                    bio_name,
                )

        ranking_rows = snapshots.get(player_id, [])
        match_date = appearance["tourney_date"]
        latest = None
        latest_group: list[Snapshot] = []
        if match_date is not None and ranking_rows:
            ranking_dates = [item[0] for item in ranking_rows]
            position = bisect.bisect_right(ranking_dates, match_date)
            if position:
                latest = ranking_rows[position - 1]
                left = bisect.bisect_left(ranking_dates, latest[0])
                latest_group = ranking_rows[left:position]
        embedded_rank = parse_positive_int(appearance["embedded_rank_raw"])
        embedded_points = (
            None
            if appearance["embedded_points_raw"] == ""
            else parse_nonnegative_int(appearance["embedded_points_raw"])
        )
        if appearance["embedded_rank_raw"] != "":
            stats["embedded_rank_present"] += 1
        if appearance["embedded_points_raw"] != "":
            stats["embedded_points_present"] += 1
        if latest is None:
            add_compact_conflict(
                ranking_conflicts,
                ("no_ranking_snapshot_on_or_before_tourney_date", year, player_id),
                "no_ranking_snapshot_on_or_before_tourney_date",
                appearance,
                appearance["embedded_rank_raw"],
                "",
            )
            continue
        ranking_date, snapshot_rank, snapshot_points, _, _ = latest
        stats["appearances_with_prior_ranking"] += 1
        distinct_prior[year].add(player_id)
        assert match_date is not None
        gap = (match_date - ranking_date).days
        gap_values[year].append(gap)
        if gap <= 7:
            stats["prior_ranking_within_7_days"] += 1
        if gap <= 14:
            stats["prior_ranking_within_14_days"] += 1
        if gap <= 28:
            stats["prior_ranking_within_28_days"] += 1
        if gap == 0:
            stats["same_date_ranking_appearances"] += 1
        else:
            stats["earlier_date_ranking_appearances"] += 1
        if len(latest_group) != 1:
            stats["appearances_with_ambiguous_prior_ranking"] += 1
            rendered = ";".join(
                f"rank={item[1]},points={'' if item[2] is None else item[2]},line={item[4]}"
                for item in latest_group
            )
            add_compact_conflict(
                ranking_conflicts,
                ("ambiguous_duplicate_latest_ranking", year, player_id, ranking_date, rendered),
                "ambiguous_duplicate_latest_ranking",
                appearance,
                appearance["embedded_rank_raw"],
                f"{ranking_date.isoformat()}:{rendered}",
            )
            continue
        stats["appearances_with_unique_prior_ranking"] += 1
        if embedded_rank is not None:
            stats["rank_comparable"] += 1
            if embedded_rank == snapshot_rank:
                stats["rank_equal"] += 1
            else:
                stats["rank_conflicts"] += 1
                add_compact_conflict(
                    ranking_conflicts,
                    (
                        "embedded_rank_mismatch",
                        year,
                        player_id,
                        embedded_rank,
                        snapshot_rank,
                        ranking_date,
                    ),
                    "embedded_rank_mismatch",
                    appearance,
                    str(embedded_rank),
                    f"{snapshot_rank}@{ranking_date.isoformat()}",
                )
        if embedded_points is not None and snapshot_points is not None:
            stats["points_comparable"] += 1
            if embedded_points == snapshot_points:
                stats["points_equal"] += 1
            else:
                stats["points_conflicts"] += 1
                add_compact_conflict(
                    ranking_conflicts,
                    (
                        "embedded_points_mismatch",
                        year,
                        player_id,
                        embedded_points,
                        snapshot_points,
                        ranking_date,
                    ),
                    "embedded_points_mismatch",
                    appearance,
                    str(embedded_points),
                    f"{snapshot_points}@{ranking_date.isoformat()}",
                )

    annual_rows = []
    for year in sorted(annual):
        stats = annual[year]
        ids = stats.pop("distinct_player_ids_set")
        valid_appearances = stats["valid_player_id_appearances"]
        prior = stats["appearances_with_prior_ranking"]
        gaps = gap_values[year]
        annual_rows.append(
            {
                **stats,
                "distinct_player_ids": len(ids),
                "distinct_player_ids_in_biography": len(distinct_bio[year]),
                "biography_appearance_coverage_fraction": (
                    round(stats["appearances_with_biography"] / valid_appearances, 8)
                    if valid_appearances
                    else ""
                ),
                "distinct_player_ids_with_prior_ranking": len(distinct_prior[year]),
                "prior_ranking_appearance_coverage_fraction": (
                    round(prior / valid_appearances, 8) if valid_appearances else ""
                ),
                "median_ranking_age_days": statistics.median(gaps) if gaps else "",
                "max_ranking_age_days": max(gaps) if gaps else "",
                "embedded_rank_match_fraction_when_comparable": (
                    round(stats["rank_equal"] / stats["rank_comparable"], 8)
                    if stats["rank_comparable"]
                    else ""
                ),
                "embedded_points_match_fraction_when_comparable": (
                    round(stats["points_equal"] / stats["points_comparable"], 8)
                    if stats["points_comparable"]
                    else ""
                ),
            }
        )

    def compact_rows(values: dict[tuple[Any, ...], dict[str, Any]]) -> list[dict[str, Any]]:
        output = []
        for row in values.values():
            row = dict(row)
            row["years"] = ";".join(str(year) for year in sorted(row.pop("years_set")))
            output.append(row)
        return sorted(
            output,
            key=lambda row: (
                row["conflict_type"],
                str(row["player_id"]),
                row["first_source_file"],
                row["first_physical_line"],
            ),
        )

    return annual_rows, compact_rows(identity_conflicts), compact_rows(ranking_conflicts)


def add_ranking_biography_conflicts(
    identity_rows: list[dict[str, Any]],
    biographies: dict[int, dict[str, str]],
    normalized_path: Path,
) -> None:
    # One locator per ranking-only player id; scan normalized output so locators remain
    # reproducible.
    seen: set[int] = set()
    firsts: dict[int, tuple[str, int, str]] = {}
    years: dict[int, set[int]] = defaultdict(set)
    with gzip.open(normalized_path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            player_id = int(row["player_id"])
            if player_id in biographies:
                continue
            years[player_id].add(int(row["effective_date"][:4]))
            if player_id not in seen:
                firsts[player_id] = (
                    row["source_member"],
                    int(row["source_physical_line"]),
                    row["effective_date"],
                )
                seen.add(player_id)
    for player_id in sorted(firsts):
        source, line, effective_date = firsts[player_id]
        identity_rows.append(
            {
                "conflict_type": "ranking_player_id_missing_biography",
                "player_id": player_id,
                "result_value": "",
                "ranking_or_biography_value": "",
                "occurrences": "",
                "years": ";".join(str(year) for year in sorted(years[player_id])),
                "first_source_file": source,
                "first_physical_line": line,
                "first_tourney_date": effective_date.replace("-", ""),
                "first_side": "",
            }
        )
    identity_rows.sort(
        key=lambda row: (
            row["conflict_type"],
            str(row["player_id"]),
            row["first_source_file"],
            int(row["first_physical_line"]),
        )
    )


ANNUAL_RANKING_FIELDS = [
    "year", "source_member", "rows", "valid_rows", "invalid_numeric_rows",
    "distinct_effective_dates", "first_effective_date", "last_effective_date",
    "effective_date_weekdays", "median_gap_days", "max_gap_days", "distinct_player_ids",
    "rows_with_biography", "row_biography_coverage_fraction", "distinct_player_ids_in_biography",
    "distinct_player_biography_coverage_fraction", "ranking_points_present_rows",
    "ranking_points_missing_rows", "ranking_points_coverage_fraction",
    "duplicate_date_player_groups", "duplicate_date_player_exact_groups",
    "duplicate_date_player_conflicting_groups", "duplicate_date_player_excess_rows",
    "date_order_decreases",
]  # fmt: skip
RESULT_FIELDS = [
    "year", "source_member", "match_rows", "player_appearances", "valid_player_id_appearances",
    "missing_or_invalid_player_id_appearances", "invalid_tourney_date_rows",
    "tourney_date_year_differs_from_file_year_rows", "appearances_with_biography",
    "appearances_with_prior_ranking", "same_date_ranking_appearances",
    "earlier_date_ranking_appearances", "appearances_with_unique_prior_ranking",
    "appearances_with_ambiguous_prior_ranking", "prior_ranking_within_7_days",
    "prior_ranking_within_14_days", "prior_ranking_within_28_days",
    "embedded_rank_present", "rank_comparable", "rank_equal", "rank_conflicts",
    "embedded_points_present", "points_comparable", "points_equal", "points_conflicts",
    "distinct_player_ids", "distinct_player_ids_in_biography",
    "biography_appearance_coverage_fraction", "distinct_player_ids_with_prior_ranking",
    "prior_ranking_appearance_coverage_fraction", "median_ranking_age_days",
    "max_ranking_age_days", "embedded_rank_match_fraction_when_comparable",
    "embedded_points_match_fraction_when_comparable",
]  # fmt: skip
ANOMALY_FIELDS = [
    "anomaly_type", "source_file", "physical_line", "ranking_date", "rank", "player",
    "points", "detail",
]  # fmt: skip
CONFLICT_FIELDS = [
    "conflict_type", "player_id", "result_value", "ranking_or_biography_value", "occurrences",
    "years", "first_source_file", "first_physical_line", "first_tourney_date", "first_side",
]  # fmt: skip


def build(
    archive_path: Path,
    out_dir: Path,
    selection: Selection,
    pin: ArchivePin = DEFAULT_ARCHIVE,
) -> dict[str, Any]:
    """The stage's whole work: extract, qualify, join, write. Returns the qualification."""
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized = out_dir / selection.normalized_output_name()
    output_paths = [
        out_dir / "raw",
        out_dir / "extraction_manifest.json",
        normalized,
        out_dir / "annual_rankings.csv",
        out_dir / "annual_results_join.csv",
        out_dir / "ranking_anomalies.csv",
        out_dir / "identity_conflicts.csv",
        out_dir / "result_rank_join_anomalies.csv",
        out_dir / "qualification.json",
    ]
    existing = [str(path) for path in output_paths if path.exists()]
    if existing:
        raise ChainError("refusing to overwrite outputs: " + ", ".join(existing))

    extracted = extract_selected(archive_path, out_dir / "raw", out_dir, selection, pin)
    extraction_manifest = {
        "qualification_id": "MULTI01_rankings",
        "archive_path": relative_to_root(archive_path, label="archive"),
        "archive_commit": pin.commit,
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": sha256(archive_path),
        "selected_member_count": len(extracted),
        "selected_members": extracted,
    }
    atomic_json(out_dir / "extraction_manifest.json", extraction_manifest)

    biographies, bio_conflicts, biography_summary = read_biographies(out_dir / "raw", selection)
    appearances, result_annual, result_parse_anomalies, result_headers = read_results(
        out_dir / "raw", selection
    )
    result_player_ids = {item["player_id"] for item in appearances if item["player_id"] is not None}
    ranking_annual, ranking_anomalies, snapshots, ranking_headers, excluded = (
        qualify_ranking_stream(
            out_dir / "raw", biographies, result_player_ids, normalized, selection
        )
    )
    annual_rankings = summarize_rankings(ranking_annual, selection)
    annual_results, identity_conflicts, rank_join_conflicts = join_results(
        appearances, result_annual, biographies, snapshots
    )

    # Normalize the biography-conflict records to the same compact schema.
    initial_identity_rows = [
        {
            "conflict_type": row["conflict_type"],
            "player_id": row["player_id"],
            "result_value": row["result_name"],
            "ranking_or_biography_value": row["biography_name"],
            "occurrences": row["occurrences"],
            "years": row["years"],
            "first_source_file": row["first_source_file"],
            "first_physical_line": row["first_physical_line"],
            "first_tourney_date": row["first_tourney_date"],
            "first_side": row["first_side"],
        }
        for row in bio_conflicts
    ]
    identity_conflicts = initial_identity_rows + identity_conflicts
    add_ranking_biography_conflicts(identity_conflicts, biographies, normalized)

    write_csv(out_dir / "annual_rankings.csv", ANNUAL_RANKING_FIELDS, annual_rankings)
    write_csv(out_dir / "annual_results_join.csv", RESULT_FIELDS, annual_results)
    write_csv(
        out_dir / "ranking_anomalies.csv",
        ANOMALY_FIELDS,
        sorted(
            ranking_anomalies + result_parse_anomalies,
            key=lambda row: (row["source_file"], int(row["physical_line"]), row["anomaly_type"]),
        ),
    )
    write_csv(out_dir / "identity_conflicts.csv", CONFLICT_FIELDS, identity_conflicts)
    write_csv(out_dir / "result_rank_join_anomalies.csv", CONFLICT_FIELDS, rank_join_conflicts)

    output_files = [
        selection.normalized_output_name(), "annual_rankings.csv", "annual_results_join.csv",
        "ranking_anomalies.csv", "identity_conflicts.csv", "result_rank_join_anomalies.csv",
    ]  # fmt: skip
    window = selection.window
    qualification: dict[str, Any] = {
        "qualification_id": "MULTI01_rankings",
        "scope": (
            f"Mechanical {selection.profile.tour} ranking stream qualification for "
            f"{window['ranking_year_min']}-{window['ranking_year_max']} "
            f"against result seasons {window['result_year_min']}-{window['result_year_max']}; "
            "no model fitting and no identity correction."
        ),
        "window": dict(window),
        "ranking_members": list(selection.ranking_members),
        "staleness_rule_days": 14,
        "coverage_limitation": (
            "The normalized stream ends at the last effective date the pinned archive holds. "
            "Targets dated more than 14 days after that date carry ranking_global_stale=1, and "
            "targets with no prior edition carry rank_missing=1; neither is imputed."
        ),
        "archive_commit": pin.commit,
        "archive_sha256": pin.sha256,
        "definitions": {
            "source_grain": "one player row per source ranking_date and rank position, subject to reported duplicate-key checks",
            "effective_date": "ISO conversion of source ranking_date; a provider-recorded ranking snapshot date, not independently verified publication time",
            "retrospective_join": "latest valid ranking snapshot with effective_date on or before result tourney_date",
            "publication_limitation": "weekly effective date does not prove when the snapshot became publicly readable; same-date use needs an explicit retrospective assumption or prior-date sensitivity",
            "identity_join": "exact positive integer player_id only; normalized names flag conflicts but never create or merge identities",
            "ranking_points": "source integer points when present; blank remains missing and is never imputed",
        },
        "headers": {
            "ranking_files": ranking_headers,
            "biography_file": BIO_HEADER,
            "result_files": result_headers,
            "normalized_output": list(NORMALIZED_HEADER),
        },
        "biography_summary": biography_summary,
        "rank_rows_in_window": sum(int(row.get("rows", 0)) for row in annual_rankings),
        "valid_rank_rows_in_window": sum(int(row.get("valid_rows", 0)) for row in annual_rankings),
        "ranking_points_present_rows": sum(
            int(row.get("ranking_points_present_rows", 0)) for row in annual_rankings
        ),
        "ranking_duplicate_date_player_groups": sum(
            int(row.get("duplicate_date_player_groups", 0)) for row in annual_rankings
        ),
        "ranking_duplicate_date_player_exact_groups": sum(
            int(row.get("duplicate_date_player_exact_groups", 0)) for row in annual_rankings
        ),
        "ranking_duplicate_date_player_conflicting_groups": sum(
            int(row.get("duplicate_date_player_conflicting_groups", 0)) for row in annual_rankings
        ),
        "ranking_invalid_numeric_rows": sum(
            int(row.get("invalid_numeric_rows", 0)) for row in annual_rankings
        ),
        "ranking_date_order_decreases": sum(
            int(row.get("date_order_decreases", 0)) for row in annual_rankings
        ),
        "out_of_scope_ranking_rows_excluded_by_member": excluded,
        "result_match_rows_in_window": sum(row["match_rows"] for row in annual_results),
        "result_player_appearances_in_window": sum(
            row["player_appearances"] for row in annual_results
        ),
        "identity_conflict_summary_rows": len(identity_conflicts),
        "rank_join_anomaly_summary_rows": len(rank_join_conflicts),
        "ranking_anomaly_locator_rows": len(ranking_anomalies),
        "result_invalid_tourney_date_rows": sum(
            row["invalid_tourney_date_rows"] for row in annual_results
        ),
        "result_tourney_date_year_differs_from_file_year_rows": sum(
            row["tourney_date_year_differs_from_file_year_rows"] for row in annual_results
        ),
        "outputs": [
            {
                "path": path,
                "bytes": (out_dir / path).stat().st_size,
                "sha256": sha256(out_dir / path),
            }
            for path in output_files
        ],
    }
    qualification["tour"] = selection.profile.tour
    atomic_json(out_dir / "qualification.json", qualification)
    return qualification


def validate_existing(archive_path: Path, out_dir: Path, pin: ArchivePin = DEFAULT_ARCHIVE) -> None:
    manifest = json.loads((out_dir / "extraction_manifest.json").read_text())
    qualification = json.loads((out_dir / "qualification.json").read_text())
    selection = select(qualification.get("tour", "ATP"), qualification.get("window"))
    if sha256(archive_path) != pin.sha256:
        raise ChainError("archive hash drift")
    if manifest["archive_sha256"] != pin.sha256 or qualification["archive_sha256"] != pin.sha256:
        raise ChainError("recorded archive hash drift")
    for record in manifest["selected_members"]:
        path = out_dir / record["extracted_path"]
        if (
            path.stat().st_size != record["extracted_bytes"]
            or sha256(path) != (record["extracted_sha256"])
        ):
            raise ChainError(f"extracted member drift: {path}")
        if record["archive_member_sha256"] != record["extracted_sha256"]:
            raise ChainError(f"input/output hash mismatch: {path}")
    for record in qualification["outputs"]:
        path = out_dir / record["path"]
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ChainError(f"derived output drift: {path}")
    if selection.normalized_output_name() not in {
        record["path"] for record in qualification["outputs"]
    }:
        raise ChainError("recorded outputs do not name the normalized stream for this window")
    print("MULTI01 ranking extraction and derived hashes validated")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["build", "validate"])
    parser.add_argument(
        "--archive",
        type=Path,
        help="the tarball to read (default: the config's archive.path, else ARCHIVE01)",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="JSON holding the ranking/result window keys")
    parser.add_argument("--tour", default="ATP", choices=sorted(TOUR_PROFILES))
    parser.add_argument("--ranking-year-min", type=int)
    parser.add_argument("--ranking-year-max", type=int)
    parser.add_argument("--result-year-min", type=int)
    parser.add_argument("--result-year-max", type=int)
    args = parser.parse_args(argv)

    window: dict[str, Any] = {}
    tour = args.tour
    pin = DEFAULT_ARCHIVE
    if args.config is not None:
        document = read_config(resolve_under_root(args.config, label="config"))
        window.update({key: document[key] for key in DEFAULT_WINDOW if key in document})
        tour = document.get("tour", args.tour)
        pin = ArchivePin.from_config(document)
    for key in DEFAULT_WINDOW:
        value = getattr(args, key)
        if value is not None:
            window[key] = value
    selection = select(tour, window)
    archive_path = resolve_under_root(args.archive or pin.path, label="archive")
    out_dir = resolve_under_root(args.output_dir, label="output_dir")
    if args.mode == "build":
        qualification = build(archive_path, out_dir, selection, pin)
        print(json.dumps(qualification, indent=2, sort_keys=True))
    else:
        validate_existing(archive_path, out_dir, pin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
