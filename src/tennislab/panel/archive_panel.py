"""Normalize a span of the pinned Sackmann mirror into a neutral-orientation match panel.

Stage ``archive_panel``. Ported from the archive's ``build_archive_panel.py`` and its
launcher ``run_archive_panel.py`` (WTA02 revision, which carries the ATP behaviour
unchanged under ``tour = "ATP"``). The builder is a pure function of an
:class:`ArchiveSource` and a :class:`TourProfile`; the launcher verifies the bridge's
composed archive against the original mirror before handing it to the builder.

Reading ``<tour>_matches_<year>.csv`` means reading that season's winner and loser.
With ``panel_end_year`` inside a reserved window this stage is the outcome-access event
and must be logged as such before it runs.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import tarfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    code_receipt,
    read_config,
    relative_to_root,
    require_hash,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
    sha256_bytes,
    year_plan,
)

MIRROR_SHA256 = "2a1ef3a848210f1067657e3399980365d734f8134463ab4114b67ef8c3d47bb4"
MIRROR_PATH = (
    "data/raw/ARCHIVE01/snapshot/"
    "tennis-sackmann-archive-83733587353df8a41f2fd4f516147d5aa83f5a8d.tar.gz"
)
ARCHIVE_PREFIX = "tennis-sackmann-archive-83733587353df8a41f2fd4f516147d5aa83f5a8d"

IDENTITY_PATH = "data/manifests/CH01/identity_corrections.json"
IDENTITY_SHA256 = "0cd1085294fc8c4c292918a4b7003e44cd0d9f12b77d3f3b5983372d9961ef56"
SR01_MANIFEST_PATH = "data/manifests/SR01.json"
SR01_MANIFEST_SHA256 = "79415f8d7bb7b0058b37f7aa87c905a023a4df9ec44aab5aa1ef1ff8591eed14"
COUNT_CORRECTION_PATH = "data/curated/SR01/attempt_002/derived_correction.json"
COUNT_CORRECTION_SHA256 = "92db8cbd006457e68ea6359e0c8605f79f4051e546660984a2268a0b52ecfc93"


@dataclass(frozen=True)
class TourProfile:
    """Every tour-specific constant of the panel build, in one object."""

    tour: str
    tar_root: str
    player_member: str
    player_sha256: str
    match_member: str
    default_panel_start_year: int
    apply_identity_corrections: bool
    apply_count_correction: bool
    expected_corrections: dict[str, int]
    tour_finals_rows: int | None
    tour_finals_events: int | None
    tour_finals_expectation: str
    scope: str


TOUR_PROFILES: dict[str, TourProfile] = {
    "ATP": TourProfile(
        tour="ATP",
        tar_root=f"{ARCHIVE_PREFIX}/atp",
        player_member=f"{ARCHIVE_PREFIX}/atp/atp_players.csv",
        player_sha256="89e81bb3a02561dee29afe53dbcdabe4ae22f725fb5d0303617366a57e3b7a83",
        match_member="atp_matches_{year}.csv",
        default_panel_start_year=2005,
        apply_identity_corrections=True,
        apply_count_correction=True,
        expected_corrections={"global_alias": 1, "record_identity": 1, "count_match": 1},
        tour_finals_rows=15,
        tour_finals_events=1,
        tour_finals_expectation="expected one 15-row Masters Cup/Tour Finals event",
        scope=(
            "ATP annual singles {start}-{end}, A/M/G plus Olympics and main ATP Finals; "
            "ATP/United/Laver Cups and NextGen excluded"
        ),
    ),
    "WTA": TourProfile(
        tour="WTA",
        tar_root=f"{ARCHIVE_PREFIX}/wta",
        player_member=f"{ARCHIVE_PREFIX}/wta/wta_players.csv",
        player_sha256="601a747a3e6e291d5ae8778b0e75f30db5536dbf9cd3d654a95d991311ad8870",
        match_member="wta_matches_{year}.csv",
        default_panel_start_year=2007,
        # No WTA identity-correction or count-correction evidence exists. Nothing is
        # applied and nothing is assumed in its place.
        apply_identity_corrections=False,
        apply_count_correction=False,
        expected_corrections={},
        # The WTA year-end population is not one 15-row event: the Elite Trophy /
        # Tournament of Champions shares level F, 2015's WTA Finals is level W and
        # 2020 has none at all. The inventory is reported, never asserted.
        tour_finals_rows=None,
        tour_finals_events=None,
        tour_finals_expectation=(
            "expected at least one year-end event (level F, or the 2015 W-level WTA Finals)"
        ),
        scope=(
            "WTA annual tour-level singles {start}-{end}, levels G/PM/P/I/W/F/T1-T5/CC "
            "plus Olympics; Fed/BJK Cup (D), exhibition (E), junior (J), seniors "
            "(50+H/35+H) and named team events excluded"
        ),
    ),
}


def profile_for(tour: str) -> TourProfile:
    key = str(tour).upper()
    if key not in TOUR_PROFILES:
        raise ChainError(f"unknown tour {tour!r}; expected one of {sorted(TOUR_PROFILES)}")
    return TOUR_PROFILES[key]


@dataclass(frozen=True)
class ArchiveSource:
    """The tarball the panel is read from and the hash it must carry."""

    path: Path
    sha256: str


PLAYER_FIELDS = (
    "player_id",
    "name_first",
    "name_last",
    "hand",
    "dob",
    "ioc",
    "height",
    "wikidata_id",
)
RAW_FIELDS = (
    "tourney_id",
    "tourney_name",
    "surface",
    "draw_size",
    "tourney_level",
    "tourney_date",
    "match_num",
    "winner_id",
    "winner_seed",
    "winner_entry",
    "winner_name",
    "winner_hand",
    "winner_ht",
    "winner_ioc",
    "winner_age",
    "loser_id",
    "loser_seed",
    "loser_entry",
    "loser_name",
    "loser_hand",
    "loser_ht",
    "loser_ioc",
    "loser_age",
    "score",
    "best_of",
    "round",
    "minutes",
    "w_ace",
    "w_df",
    "w_svpt",
    "w_1stIn",
    "w_1stWon",
    "w_2ndWon",
    "w_SvGms",
    "w_bpSaved",
    "w_bpFaced",
    "l_ace",
    "l_df",
    "l_svpt",
    "l_1stIn",
    "l_1stWon",
    "l_2ndWon",
    "l_SvGms",
    "l_bpSaved",
    "l_bpFaced",
    "winner_rank",
    "winner_rank_points",
    "loser_rank",
    "loser_rank_points",
)
COUNT_FIELDS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")
TEAM_EVENTS = {"atp cup", "united cup", "laver cup"}
NEXTGEN_EVENTS = {"nextgen finals", "next gen finals"}
TOUR_FINALS_EVENTS = {"masters cup", "tour finals"}
SURFACES = {"Hard", "Clay", "Grass", "Carpet"}
WTA_TOUR_LEVELS = {"G", "PM", "P", "I", "W", "F", "T1", "T2", "T3", "T4", "T5", "CC"}
WTA_TEAM_EVENT_PREFIXES = ("fed cup", "bjk cup", "billie jean king cup", "united cup", "hopman cup")
WTA_EXCLUDED_LEVELS = {
    "D": "excluded_team",
    "E": "excluded_exhibition",
    "J": "excluded_junior",
    "50+H": "excluded_seniors",
    "35+H": "excluded_seniors",
}
WTA_FINALS_NAME_TOKENS = ("wta finals", "wta championships", "wta tour championships")

PANEL_FIELDS = (
    "season",
    "source_member",
    "source_file_sha256",
    "source_line_number",
    "source_row_number",
    "source_key",
    "tourney_id",
    "tourney_name",
    "tourney_level",
    "population_basis",
    "competition_type",
    "tourney_anchor_date",
    "date_basis",
    "surface",
    "draw_size",
    "match_num",
    "ranking_metadata_basis",
    "round",
    "best_of",
    "minutes",
    "score",
    "status",
    "played",
    "completed",
    "retired",
    "walkover",
    "defaulted",
    "abandoned",
    "a_won",
    "a_source_side",
    "b_source_side",
    "a_source_id",
    "a_entity_id",
    "a_source_name",
    "a_identity_correction",
    "a_identity_metadata_status",
    "a_seed",
    "a_entry",
    "a_hand",
    "a_height_cm",
    "a_ioc",
    "a_age_years",
    "a_rank",
    "a_rank_points",
    "b_source_id",
    "b_entity_id",
    "b_source_name",
    "b_identity_correction",
    "b_identity_metadata_status",
    "b_seed",
    "b_entry",
    "b_hand",
    "b_height_cm",
    "b_ioc",
    "b_age_years",
    "b_rank",
    "b_rank_points",
    "count_block_status",
    "count_correction_applied",
    *(f"a_{name}" for name in COUNT_FIELDS),
    *(f"b_{name}" for name in COUNT_FIELDS),
    "raw_row_json",
)
ANOMALY_FIELDS = (
    "season",
    "source_member",
    "source_line_number",
    "source_key",
    "category",
    "field",
    "raw_value",
    "detail",
    "action",
)
CORRECTION_FIELDS = (
    "season",
    "source_key",
    "correction_type",
    "source_side",
    "field",
    "raw_value",
    "corrected_value",
    "provenance_path",
    "provenance_sha256",
    "note",
)
ANNUAL_FIELDS = (
    "season",
    "source_member",
    "source_file_sha256",
    "source_rows",
    "included_rows",
    "excluded_team_rows",
    "excluded_nextgen_rows",
    "excluded_other_level_rows",
    "tour_finals_id",
    "tour_finals_name",
    "tour_finals_source_level",
    "tour_finals_rows",
    "olympics_id",
    "olympics_source_level",
    "olympics_rows",
    "status_completed",
    "status_retired",
    "status_walkover",
    "status_default",
    "status_abandoned",
    "status_unknown",
    "played_true",
    "played_false",
    "played_unknown",
    "surface_hard",
    "surface_clay",
    "surface_grass",
    "surface_carpet",
    "surface_missing",
    "surface_other",
    "best_of_3",
    "best_of_5",
    "best_of_other",
    "counts_usable",
    "counts_missing_all",
    "counts_partial_missing",
    "counts_quarantined_invalid",
    "global_identity_alias_sides",
    "record_identity_correction_sides",
    "count_corrected_matches",
    "anomaly_rows",
)


def classify_status(score: str) -> tuple[str, str]:
    text = score.strip().upper()
    if text == "WALKOVER" or "W/O" in text:
        return "walkover", "false"
    if re.search(r"\bRET\b", text):
        return "retired", "true"
    if re.search(r"\bDEF(?:AULT)?\b", text):
        return "default", ""
    if re.search(r"\b(?:ABN|ABD|ABANDONED)\b", text):
        return "abandoned", ""
    if not text or re.search(r"[A-Z]", text):
        return "unknown", ""
    return "completed", "true"


def atp_event_rule(row: dict[str, str]) -> tuple[bool, str, str]:
    name = row["tourney_name"].strip().lower()
    if name in TEAM_EVENTS:
        return False, "excluded_team", "team"
    if name in NEXTGEN_EVENTS:
        return False, "excluded_nextgen", "nextgen"
    if name in TOUR_FINALS_EVENTS:
        return True, "main_tour_finals", "tour_finals"
    if "olympic" in name:
        basis = "olympics_consistency_override" if row["tourney_level"] == "O" else "level_A"
        return True, basis, "olympics"
    if row["tourney_level"] in {"A", "M", "G"}:
        return True, f"level_{row['tourney_level']}", "individual_tour"
    return False, "excluded_other_level", "other"


def wta_event_rule(row: dict[str, str]) -> tuple[bool, str, str]:
    """Tour-level WTA singles, with the audit's exclusions named one by one."""
    name = row["tourney_name"].strip().lower()
    level = row["tourney_level"].strip()
    if any(name.startswith(prefix) for prefix in WTA_TEAM_EVENT_PREFIXES):
        return False, "excluded_team", "team"
    if level in WTA_EXCLUDED_LEVELS:
        return False, WTA_EXCLUDED_LEVELS[level], "team" if level == "D" else "other"
    if "olympic" in name:
        basis = "olympics_consistency_override" if level == "O" else f"level_{level}"
        return True, basis, "olympics"
    if level == "F" or (level in WTA_TOUR_LEVELS and name in WTA_FINALS_NAME_TOKENS):
        return True, "main_tour_finals", "tour_finals"
    if level in WTA_TOUR_LEVELS:
        return True, f"level_{level}", "individual_tour"
    return False, "excluded_other_level", "other"


def event_rule(tour: str, row: dict[str, str]) -> tuple[bool, str, str]:
    return wta_event_rule(row) if tour == "WTA" else atp_event_rule(row)


def is_tour_finals(tour: str, row: dict[str, str]) -> bool:
    if tour == "WTA":
        return event_rule(tour, row)[2] == "tour_finals"
    return row["tourney_name"].strip().lower() in TOUR_FINALS_EVENTS


def count_violations(counts: dict[str, int]) -> list[str]:
    second_opportunities = counts["svpt"] - counts["1stIn"]
    checks = {
        "first_in_le_serve_points": counts["1stIn"] <= counts["svpt"],
        "first_won_le_first_in": counts["1stWon"] <= counts["1stIn"],
        "second_won_le_second_opportunities": counts["2ndWon"] <= second_opportunities,
        "double_faults_le_second_opportunities": counts["df"] <= second_opportunities,
        "second_won_plus_df_le_second_opportunities": (
            counts["2ndWon"] + counts["df"] <= second_opportunities
        ),
        "aces_le_total_service_points_won": counts["ace"] <= counts["1stWon"] + counts["2ndWon"],
        "break_points_saved_le_faced": counts["bpSaved"] <= counts["bpFaced"],
        "service_points_won_le_serve_points": counts["1stWon"] + counts["2ndWon"] <= counts["svpt"],
    }
    return [name for name, valid in checks.items() if not valid]


def add_anomaly(
    anomalies: list[dict[str, str]],
    year: int,
    member: str,
    line: str,
    key: str,
    category: str,
    field: str,
    raw: str,
    detail: str,
    action: str,
) -> None:
    anomalies.append(
        dict(
            zip(
                ANOMALY_FIELDS,
                (
                    str(year),
                    member,
                    line,
                    key,
                    category,
                    field,
                    raw,
                    detail,
                    action,
                ),
                strict=True,
            )
        )
    )


def parse_count(raw: str) -> int | None:
    if raw == "":
        return None
    if not re.fullmatch(r"[0-9]+", raw):
        raise ValueError(f"non-canonical count {raw!r}")
    return int(raw)


def side_record(
    row: dict[str, str], source_side: str, entity_id: int, correction: str, metadata_status: str
) -> dict[str, str]:
    prefix = "winner" if source_side == "w" else "loser"
    fields = {
        "source_side": source_side,
        "source_id": row[f"{prefix}_id"],
        "entity_id": str(entity_id),
        "source_name": row[f"{prefix}_name"],
        "identity_correction": correction,
        "identity_metadata_status": metadata_status,
        "seed": row[f"{prefix}_seed"],
        "entry": row[f"{prefix}_entry"],
    }
    if metadata_status == "quarantined_wrong_source_identity":
        fields.update(
            {name: "" for name in ("hand", "height_cm", "ioc", "age_years", "rank", "rank_points")}
        )
    else:
        fields.update(
            {
                "hand": row[f"{prefix}_hand"],
                "height_cm": row[f"{prefix}_ht"],
                "ioc": row[f"{prefix}_ioc"],
                "age_years": row[f"{prefix}_age"],
                "rank": row[f"{prefix}_rank"],
                "rank_points": row[f"{prefix}_rank_points"],
            }
        )
    return fields


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(
    source: ArchiveSource,
    profile: TourProfile,
    output_dir: Path,
    panel_start_year: int,
    panel_end_year: int,
) -> dict[str, Any]:
    """Read the annual members of ``source`` and write the panel and its reports."""
    if not 2000 <= panel_start_year <= panel_end_year <= 2100:
        raise ChainError("panel years must satisfy 2000 <= start <= end <= 2100")
    tour = profile.tour
    identity_path = resolve_under_root(IDENTITY_PATH, label="identity_corrections")
    sr01_manifest_path = resolve_under_root(SR01_MANIFEST_PATH, label="sr01_manifest")
    count_correction_path = resolve_under_root(COUNT_CORRECTION_PATH, label="count_correction")
    expected_files = {source.path: source.sha256}
    if profile.apply_identity_corrections:
        expected_files[identity_path] = IDENTITY_SHA256
    if profile.apply_count_correction:
        expected_files[sr01_manifest_path] = SR01_MANIFEST_SHA256
        expected_files[count_correction_path] = COUNT_CORRECTION_SHA256
    for path, expected in expected_files.items():
        require_hash(path, expected, label=str(path))
    global_aliases: dict[int, int] = {}
    record_corrections: dict[str, Any] = {}
    if profile.apply_identity_corrections:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        global_aliases = {
            int(key): int(value) for key, value in identity["global_source_id_aliases"].items()
        }
        record_corrections = identity["record_identity_corrections"]
    correction_key = None
    count_replacements: dict[str, tuple[int, int]] = {}
    if profile.apply_count_correction:
        sr01_manifest = json.loads(sr01_manifest_path.read_text(encoding="utf-8"))
        count_correction = json.loads(count_correction_path.read_text(encoding="utf-8"))
        if sr01_manifest["files"]["derived_correction.json"] != COUNT_CORRECTION_SHA256:
            raise ChainError("SR01 manifest does not pin the count correction")
        correction_key = (
            f"{count_correction['match_key']['tourney_id']}/"
            f"{count_correction['match_key']['match_num']}"
        )
        count_replacements = {
            field: (int(values["original"]), int(values["corrected"]))
            for field, values in count_correction["assert_before_replace"].items()
        }
    identity_relative = relative_to_root(identity_path)
    count_correction_relative = relative_to_root(count_correction_path)

    panel: list[dict[str, Any]] = []
    annual: list[dict[str, Any]] = []
    anomalies: list[dict[str, str]] = []
    correction_log: list[dict[str, str]] = []
    annual_hashes: dict[str, str] = {}
    excluded_named_events: Counter[tuple[int, str, str, str]] = Counter()
    excluded_reason_counts: Counter[str] = Counter()
    applied: Counter[str] = Counter()

    with tarfile.open(source.path, "r:gz") as archive:
        player_payload = archive.extractfile(profile.player_member).read()
        if sha256_bytes(player_payload) != profile.player_sha256:
            raise ChainError("archived player-master hash mismatch")
        player_reader = csv.DictReader(
            io.TextIOWrapper(io.BytesIO(player_payload), encoding="utf-8-sig", newline="")
        )
        if tuple(player_reader.fieldnames or ()) != PLAYER_FIELDS:
            raise ChainError("archived player-master schema mismatch")
        player_ids = [row["player_id"] for row in player_reader]
        if len(player_ids) != len(set(player_ids)) or any(
            not value.isdigit() or int(value) <= 0 for value in player_ids
        ):
            raise ChainError("archived player-master IDs are invalid or duplicated")
        player_id_set = set(player_ids)
        for year in range(panel_start_year, panel_end_year + 1):
            member = f"{profile.tar_root}/" + profile.match_member.format(year=year)
            payload = archive.extractfile(member).read()
            file_hash = sha256_bytes(payload)
            annual_hashes[member] = file_hash
            reader = csv.DictReader(
                io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8-sig", newline="")
            )
            if tuple(reader.fieldnames or ()) != RAW_FIELDS:
                add_anomaly(
                    anomalies,
                    year,
                    member,
                    "",
                    "",
                    "schema_mismatch",
                    "header",
                    ",".join(reader.fieldnames or ()),
                    "expected the frozen 49-column schema",
                    "build_stopped",
                )
                raise ChainError(f"schema mismatch in {member}")
            stats: Counter[str] = Counter()
            finals: Counter[tuple[str, str, str]] = Counter()
            olympics: Counter[tuple[str, str]] = Counter()
            seen_keys: set[str] = set()
            anomaly_start = len(anomalies)
            for source_row_number, row in enumerate(reader, 1):
                stats["source_rows"] += 1
                source_key = f"{row['tourney_id']}/{row['match_num']}"
                include, basis, competition_type = event_rule(tour, row)
                if not include:
                    stats[basis] += 1
                    excluded_reason_counts[basis] += 1
                    if basis in {"excluded_team", "excluded_nextgen"}:
                        excluded_named_events[
                            (year, row["tourney_name"], row["tourney_level"], basis)
                        ] += 1
                    continue
                stats["included_rows"] += 1
                if source_key in seen_keys:
                    add_anomaly(
                        anomalies,
                        year,
                        member,
                        str(reader.line_num),
                        source_key,
                        "duplicate_source_key",
                        "source_key",
                        source_key,
                        "duplicate (tourney_id,match_num) within annual file",
                        "row_not_emitted",
                    )
                    continue
                seen_keys.add(source_key)
                if is_tour_finals(tour, row):
                    finals[(row["tourney_id"], row["tourney_name"], row["tourney_level"])] += 1
                if competition_type == "olympics":
                    olympics[(row["tourney_id"], row["tourney_level"])] += 1

                status, played = classify_status(row["score"])
                stats[f"status_{status}"] += 1
                stats[f"played_{'unknown' if played == '' else played}"] += 1
                if status == "unknown":
                    add_anomaly(
                        anomalies,
                        year,
                        member,
                        str(reader.line_num),
                        source_key,
                        "unknown_status",
                        "score",
                        row["score"],
                        "status vocabulary not recognized",
                        "status_retained_unknown",
                    )
                surface_key = (
                    row["surface"].lower()
                    if row["surface"] in SURFACES
                    else "missing"
                    if not row["surface"]
                    else "other"
                )
                stats[f"surface_{surface_key}"] += 1
                if row["surface"] not in SURFACES:
                    add_anomaly(
                        anomalies,
                        year,
                        member,
                        str(reader.line_num),
                        source_key,
                        "surface_label",
                        "surface",
                        row["surface"],
                        "outside Hard/Clay/Grass/Carpet",
                        "raw_label_retained",
                    )
                stats[f"best_of_{row['best_of'] if row['best_of'] in {'3', '5'} else 'other'}"] += 1
                try:
                    datetime.strptime(row["tourney_date"], "%Y%m%d")
                except ValueError:
                    add_anomaly(
                        anomalies,
                        year,
                        member,
                        str(reader.line_num),
                        source_key,
                        "invalid_anchor_date",
                        "tourney_date",
                        row["tourney_date"],
                        "not an eight-digit calendar date",
                        "raw_anchor_retained",
                    )

                side_info: dict[str, tuple[int, str, str]] = {}
                invalid_id = False
                for source_side, prefix in (("w", "winner"), ("l", "loser")):
                    raw_id = row[f"{prefix}_id"]
                    if not raw_id.isdigit() or int(raw_id) <= 0:
                        invalid_id = True
                        add_anomaly(
                            anomalies,
                            year,
                            member,
                            str(reader.line_num),
                            source_key,
                            "invalid_player_id",
                            f"{prefix}_id",
                            raw_id,
                            "positive integer required",
                            "row_not_emitted",
                        )
                        continue
                    source_id = int(raw_id)
                    if raw_id not in player_id_set:
                        invalid_id = True
                        add_anomaly(
                            anomalies,
                            year,
                            member,
                            str(reader.line_num),
                            source_key,
                            "player_id_absent_from_master",
                            f"{prefix}_id",
                            raw_id,
                            "ID is not present in the pinned archive player master",
                            "row_not_emitted",
                        )
                        continue
                    entity_id = source_id
                    correction = ""
                    metadata_status = "source_identity_metadata_retained"
                    record = record_corrections.get(source_key, {}).get(prefix)
                    if record:
                        if source_id != int(record["expected_source_id"]):
                            raise ChainError(
                                f"record identity original drift at {source_key} {prefix}"
                            )
                        entity_id = int(record["canonical_player_id"])
                        correction = "record_identity_correction"
                        metadata_status = "quarantined_wrong_source_identity"
                        stats["record_identity_correction_sides"] += 1
                        applied["record_identity"] += 1
                        correction_log.append(
                            dict(
                                zip(
                                    CORRECTION_FIELDS,
                                    (
                                        str(year),
                                        source_key,
                                        correction,
                                        source_side,
                                        f"{prefix}_id",
                                        raw_id,
                                        str(entity_id),
                                        identity_relative,
                                        IDENTITY_SHA256,
                                        "Identity-bound age/height/IOC/hand/rank/rank-points blanked; "
                                        "match-side entry and counts retained.",
                                    ),
                                    strict=True,
                                )
                            )
                        )
                    elif source_id in global_aliases:
                        entity_id = global_aliases[source_id]
                        correction = "global_source_id_alias"
                        stats["global_identity_alias_sides"] += 1
                        applied["global_alias"] += 1
                        correction_log.append(
                            dict(
                                zip(
                                    CORRECTION_FIELDS,
                                    (
                                        str(year),
                                        source_key,
                                        correction,
                                        source_side,
                                        f"{prefix}_id",
                                        raw_id,
                                        str(entity_id),
                                        identity_relative,
                                        IDENTITY_SHA256,
                                        "Duplicate source ID mapped to the established canonical entity; "
                                        "raw identity retained.",
                                    ),
                                    strict=True,
                                )
                            )
                        )
                    side_info[source_side] = (entity_id, correction, metadata_status)
                    if str(entity_id) not in player_id_set:
                        raise ChainError(
                            f"corrected entity ID absent from player master: {entity_id}"
                        )
                if invalid_id:
                    continue
                if side_info["w"][0] == side_info["l"][0]:
                    add_anomaly(
                        anomalies,
                        year,
                        member,
                        str(reader.line_num),
                        source_key,
                        "same_entity_both_sides",
                        "entity_id",
                        str(side_info["w"][0]),
                        "identity corrections collapse both match sides",
                        "row_not_emitted",
                    )
                    continue

                corrected_raw_counts = {
                    f"{side}_{name}": row[f"{side}_{name}"]
                    for side in ("w", "l")
                    for name in COUNT_FIELDS
                }
                count_corrected = correction_key is not None and source_key == correction_key
                if count_corrected:
                    applied["count_match"] += 1
                    stats["count_corrected_matches"] += 1
                    for field, (expected, replacement) in count_replacements.items():
                        if parse_count(corrected_raw_counts[field]) != expected:
                            raise ChainError(
                                f"count correction original drift at {source_key} {field}"
                            )
                        corrected_raw_counts[field] = str(replacement)
                        correction_log.append(
                            dict(
                                zip(
                                    CORRECTION_FIELDS,
                                    (
                                        str(year),
                                        source_key,
                                        "sr01_four_field_count_correction",
                                        field[0],
                                        field,
                                        str(expected),
                                        str(replacement),
                                        count_correction_relative,
                                        COUNT_CORRECTION_SHA256,
                                        "Official Roland-Garros denominator reconciliation.",
                                    ),
                                    strict=True,
                                )
                            )
                        )

                parsed: dict[str, int | None] = {}
                malformed = False
                for field, value in corrected_raw_counts.items():
                    try:
                        parsed[field] = parse_count(value)
                    except ValueError as exc:
                        malformed = True
                        parsed[field] = None
                        add_anomaly(
                            anomalies,
                            year,
                            member,
                            str(reader.line_num),
                            source_key,
                            "malformed_count",
                            field,
                            value,
                            str(exc),
                            "all_primitive_counts_blank_label_retained",
                        )
                values = list(parsed.values())
                if malformed:
                    count_status = "quarantined_invalid"
                elif all(value is None for value in values):
                    count_status = "missing_all"
                elif any(value is None for value in values):
                    count_status = "partial_missing"
                else:
                    violations = []
                    for side in ("w", "l"):
                        side_counts = {name: int(parsed[f"{side}_{name}"]) for name in COUNT_FIELDS}
                        violations.extend((side, check) for check in count_violations(side_counts))
                    if violations:
                        count_status = "quarantined_invalid"
                        for side, check in violations:
                            add_anomaly(
                                anomalies,
                                year,
                                member,
                                str(reader.line_num),
                                source_key,
                                "invalid_count_identity",
                                side,
                                json.dumps(
                                    {name: parsed[f"{side}_{name}"] for name in COUNT_FIELDS},
                                    sort_keys=True,
                                ),
                                check,
                                "all_primitive_counts_blank_label_retained",
                            )
                    else:
                        count_status = "usable"
                stats[f"counts_{count_status}"] += 1

                a_side, b_side = sorted(("w", "l"), key=lambda side: side_info[side][0])
                a_info, b_info = side_info[a_side], side_info[b_side]
                a = side_record(row, a_side, *a_info)
                b = side_record(row, b_side, *b_info)
                panel_row: dict[str, Any] = {
                    "season": str(year),
                    "source_member": member,
                    "source_file_sha256": file_hash,
                    "source_line_number": str(reader.line_num),
                    "source_row_number": str(source_row_number),
                    "source_key": source_key,
                    "tourney_id": row["tourney_id"],
                    "tourney_name": row["tourney_name"],
                    "tourney_level": row["tourney_level"],
                    "population_basis": basis,
                    "competition_type": competition_type,
                    "tourney_anchor_date": row["tourney_date"],
                    "date_basis": "event_anchor_only_no_match_date_or_clock",
                    "surface": row["surface"],
                    "ranking_metadata_basis": (
                        "archive_match_row_snapshot_no_independent_ranking_date_or_publication_time"
                    ),
                    "draw_size": row["draw_size"],
                    "match_num": row["match_num"],
                    "round": row["round"],
                    "best_of": row["best_of"],
                    "minutes": row["minutes"],
                    "score": row["score"],
                    "status": status,
                    "played": played,
                    "completed": str(status == "completed").lower(),
                    "retired": str(status == "retired").lower(),
                    "walkover": str(status == "walkover").lower(),
                    "defaulted": str(status == "default").lower(),
                    "abandoned": str(status == "abandoned").lower(),
                    "a_won": str(a_side == "w").lower(),
                    "count_block_status": count_status,
                    "count_correction_applied": str(count_corrected).lower(),
                    "raw_row_json": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                }
                for label, values_for_side in (("a", a), ("b", b)):
                    panel_row.update(
                        {f"{label}_{key}": value for key, value in values_for_side.items()}
                    )
                for label, source_side in (("a", a_side), ("b", b_side)):
                    for name in COUNT_FIELDS:
                        panel_row[f"{label}_{name}"] = (
                            "" if count_status != "usable" else str(parsed[f"{source_side}_{name}"])
                        )
                panel.append(panel_row)

            expected_events, expected_rows = profile.tour_finals_events, profile.tour_finals_rows
            finals_inventory_differs = (
                (expected_events is not None and len(finals) != expected_events)
                or (expected_rows is not None and sum(finals.values()) != expected_rows)
                or (expected_events is None and expected_rows is None and not finals)
            )
            if finals_inventory_differs:
                add_anomaly(
                    anomalies,
                    year,
                    member,
                    "",
                    "",
                    "tour_finals_inventory",
                    "tourney_name",
                    json.dumps({"events": [list(key) + [count] for key, count in finals.items()]}),
                    profile.tour_finals_expectation,
                    "reported_not_guessed",
                )
            final_key = next(iter(finals), ("", "", ""))
            olympics_key = next(iter(olympics), ("", ""))
            if final_key[2] != "F":
                add_anomaly(
                    anomalies,
                    year,
                    member,
                    "",
                    final_key[0],
                    "source_taxonomy_variation",
                    "tourney_level",
                    final_key[2],
                    "main Tour Finals is level F in the other scoped seasons",
                    "source_level_retained_population_identified_by_event",
                )
            if olympics_key and olympics_key[1] == "O":
                add_anomaly(
                    anomalies,
                    year,
                    member,
                    "",
                    olympics_key[0],
                    "source_taxonomy_variation",
                    "tourney_level",
                    "O",
                    "prior scoped Olympics are level A",
                    "source_level_retained_included_by_declared_olympics_rule",
                )
            annual.append(
                {
                    "season": year,
                    "source_member": member,
                    "source_file_sha256": file_hash,
                    "source_rows": stats["source_rows"],
                    "included_rows": stats["included_rows"],
                    "excluded_team_rows": stats["excluded_team"],
                    "excluded_nextgen_rows": stats["excluded_nextgen"],
                    "excluded_other_level_rows": stats["excluded_other_level"],
                    "tour_finals_id": final_key[0],
                    "tour_finals_name": final_key[1],
                    "tour_finals_source_level": final_key[2],
                    "tour_finals_rows": sum(finals.values()),
                    "olympics_id": olympics_key[0],
                    "olympics_source_level": olympics_key[1],
                    "olympics_rows": sum(olympics.values()),
                    **{field: stats[field] for field in ANNUAL_FIELDS[15:-1]},
                    "anomaly_rows": len(anomalies) - anomaly_start,
                }
            )

    if applied != Counter(**profile.expected_corrections):
        raise ChainError(f"correction application count drift: {dict(applied)}")
    if len({row["source_key"] for row in panel}) != len(panel):
        raise ChainError("source keys are not globally unique")
    if any(int(row["a_entity_id"]) >= int(row["b_entity_id"]) for row in panel):
        raise ChainError("neutral entity orientation failed")
    if any(row["status"] == "walkover" and row["played"] != "false" for row in panel):
        raise ChainError("walkover marked played")
    if any(row["status"] == "retired" and row["played"] != "true" for row in panel):
        raise ChainError("retirement not retained as played")
    if any("rate" in field.lower() or "percentage" in field.lower() for field in PANEL_FIELDS):
        raise ChainError("derived rate leaked into primitive panel")

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "source_panel.csv", PANEL_FIELDS, panel)
    write_csv(output_dir / "annual_stats.csv", ANNUAL_FIELDS, annual)
    write_csv(output_dir / "anomalies.csv", ANOMALY_FIELDS, anomalies)
    write_csv(output_dir / "correction_log.csv", CORRECTION_FIELDS, correction_log)
    inputs = {
        "archive": {"path": relative_to_root(source.path), "sha256": source.sha256},
        "annual_match_schema": list(RAW_FIELDS),
        "annual_members_sha256": annual_hashes,
        "player_master": {
            "member": profile.player_member,
            "sha256": profile.player_sha256,
            "unique_positive_ids": len(player_id_set),
        },
        "identity_corrections": {"path": identity_relative, "sha256": IDENTITY_SHA256},
        "sr01_manifest": {
            "path": relative_to_root(sr01_manifest_path),
            "sha256": SR01_MANIFEST_SHA256,
        },
        "count_correction": {
            "path": count_correction_relative,
            "sha256": COUNT_CORRECTION_SHA256,
        },
    }
    (output_dir / "input_manifest.json").write_text(
        json.dumps(inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    side_total = 2 * len(panel)
    metadata_fields = ("hand", "height_cm", "ioc", "age_years", "rank", "rank_points")
    metadata_coverage = {
        field: {
            "present_sides": sum(
                bool(row[f"{side}_{field}"]) for row in panel for side in ("a", "b")
            ),
            "total_sides": side_total,
        }
        for field in metadata_fields
    }
    status_by_count_block: dict[str, dict[str, int]] = {}
    for status in sorted({row["status"] for row in panel}):
        status_by_count_block[status] = dict(
            sorted(
                Counter(
                    row["count_block_status"] for row in panel if row["status"] == status
                ).items()
            )
        )
    report = {
        "tour": tour,
        "scope": profile.scope.format(start=panel_start_year, end=panel_end_year),
        "panel_start_year": panel_start_year,
        "panel_end_year": panel_end_year,
        "panel_rows": len(panel),
        "seasons": panel_end_year - panel_start_year + 1,
        "status_counts": dict(sorted(Counter(row["status"] for row in panel).items())),
        "competition_type_counts": dict(
            sorted(Counter(row["competition_type"] for row in panel).items())
        ),
        "surface_counts": dict(
            sorted(Counter(row["surface"] or "<missing>" for row in panel).items())
        ),
        "count_block_counts": dict(
            sorted(Counter(row["count_block_status"] for row in panel).items())
        ),
        "count_block_by_status": status_by_count_block,
        "played_counts": dict(sorted(Counter(row["played"] or "unknown" for row in panel).items())),
        "source_level_counts": dict(sorted(Counter(row["tourney_level"] for row in panel).items())),
        "round_counts": dict(sorted(Counter(row["round"] or "<missing>" for row in panel).items())),
        "best_of_counts": dict(
            sorted(Counter(row["best_of"] or "<missing>" for row in panel).items())
        ),
        "side_metadata_coverage": metadata_coverage,
        "entry_code_counts": dict(
            sorted(
                Counter(
                    row[f"{side}_entry"] or "<blank_standard_or_unspecified>"
                    for row in panel
                    for side in ("a", "b")
                ).items()
            )
        ),
        "excluded_named_event_counts": [
            {
                "season": year,
                "tourney_name": name,
                "source_level": level,
                "reason": reason,
                "rows": count,
            }
            for (year, name, level, reason), count in sorted(excluded_named_events.items())
        ],
        "default_rows": [
            {
                "source_key": row["source_key"],
                "tourney_name": row["tourney_name"],
                "score": row["score"],
                "played": "unknown",
            }
            for row in panel
            if row["status"] == "default"
        ],
        "partial_or_quarantined_count_rows": [
            {
                "source_key": row["source_key"],
                "status": row["status"],
                "count_block_status": row["count_block_status"],
            }
            for row in panel
            if row["count_block_status"] in {"partial_missing", "quarantined_invalid"}
        ],
        "correction_applications": dict(applied),
        "correction_policy": (
            "CH01 identity corrections and the SR01 count correction applied"
            if profile.apply_identity_corrections
            else "no identity or count correction exists for this tour; none applied"
        ),
        "excluded_reason_counts": dict(sorted(excluded_reason_counts.items())),
        "anomaly_records": len(anomalies),
        "source_key_unique": True,
        "neutral_orientation": "a_entity_id < b_entity_id",
        "player_id_validation": (
            f"all source and corrected entity IDs occur in the {len(player_id_set)}-ID "
            "pinned player master"
        ),
        "date_basis": "tourney_date retained only as event anchor; no match date or clock inferred",
        "ranking_metadata_basis": (
            "rank/rank_points are preserved archive match-row fields; no reconstructed weekly "
            "value or independent ranking date/publication-time claim"
        ),
        "primitive_count_policy": (
            "No rates. Missing blocks remain missing. Invalid/malformed blocks blank all "
            "derived primitive counts while retaining row and label."
        ),
        "output_sha256": {
            name: sha256(output_dir / name)
            for name in (
                "source_panel.csv",
                "annual_stats.csv",
                "anomalies.csv",
                "correction_log.csv",
                "input_manifest.json",
            )
        },
    }
    (output_dir / "quality_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


# ----------------------------------------------------------------- the launcher


def verify_composition(original: Path, composed: Path, record: dict[str, Any]) -> dict[str, Any]:
    """The bridge's composed archive must be the mirror plus the bridge's own annual rows."""
    declared = {item["member"]: item for item in record["members"]}
    observed: dict[str, str] = {}
    with tarfile.open(composed, "r:gz") as archive:
        for info in archive.getmembers():
            if not info.isfile():
                continue
            handle = archive.extractfile(info)
            if handle is None:
                raise ChainError(f"cannot read composed member {info.name}")
            observed[info.name] = sha256_bytes(handle.read())
    if set(observed) != set(declared):
        raise ChainError(
            "composed archive membership differs from bridge_summary.json: "
            f"{sorted(set(observed) ^ set(declared))}"
        )
    unchanged = [
        name for name, item in declared.items() if item["route"] == "mirror_bytes_unchanged"
    ]
    with tarfile.open(original, "r:gz") as archive:
        for name in unchanged:
            handle = archive.extractfile(archive.getmember(name))
            if handle is None:
                raise ChainError(f"cannot read mirror member {name}")
            if sha256_bytes(handle.read()) != observed[name]:
                raise ChainError(
                    f"member marked mirror_bytes_unchanged differs from the mirror: {name}"
                )
    for name, item in declared.items():
        if observed[name] != item["sha256"]:
            raise ChainError(f"composed member hash differs from bridge_summary.json: {name}")
    return {
        "members": len(observed),
        "mirror_bytes_unchanged": len(unchanged),
        "bridge_extended": [
            name for name, item in sorted(declared.items()) if item["route"] == "bridge_extended"
        ],
        "member_sha256": dict(sorted(observed.items())),
    }


def extract_player_master(archive: Path, profile: TourProfile, destination: Path) -> dict[str, Any]:
    """Write the archive's own player master beside the panel, bytes unchanged."""
    with tarfile.open(archive, "r:gz") as handle:
        member = handle.extractfile(profile.player_member)
        if member is None:
            raise ChainError(f"cannot read player master {profile.player_member}")
        payload = member.read()
    observed = sha256_bytes(payload)
    if observed != profile.player_sha256:
        raise ChainError(f"player master hash mismatch: {observed} != {profile.player_sha256}")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "players.csv"
    target.write_bytes(payload)
    return {"path": relative_to_root(target), "sha256": observed, "bytes": len(payload)}


def require_bridge(tour: str, panel_end_year: int, bridge_declared: Any) -> None:
    """A panel that reaches past the mirror's last complete season must come through the bridge."""
    if panel_end_year > 2024 and bridge_declared is None:
        raise ChainError(
            f"{tour} panel_end_year {panel_end_year} is past 2024 and declares no "
            "bridge_summary; the pinned mirror carries no complete reserved season"
        )


def run(config_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    document = read_config(config_path)
    plan = year_plan(document)
    section = document.get("archive_panel")
    if not isinstance(section, dict):
        raise ChainError("configuration has no archive_panel object")
    tour = str(section.get("tour", document.get("tour", "ATP"))).upper()
    profile = profile_for(tour)

    original = resolve_under_root(section["original_archive"], label="original_archive")
    original_hash = require_hash(original, MIRROR_SHA256, label="original mirror archive")

    bridge_declared = section.get("bridge_summary")
    require_bridge(tour, int(section.get("panel_end_year", plan.panel_end_year)), bridge_declared)
    if bridge_declared is None:
        summary_path = None
        composed, composed_hash = original, original_hash
        composition: dict[str, Any] = {
            "members": None,
            "mirror_bytes_unchanged": None,
            "bridge_extended": [],
            "member_sha256": {},
            "basis": "no bridge: the pinned mirror tarball is read directly",
        }
    else:
        summary_path = resolve_under_root(bridge_declared, label="bridge_summary")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        record = summary["composed_archive"]
        composed = resolve_under_root(record["path"], label="composed_archive")
        composed_hash = require_hash(composed, record["sha256"], label="composed_archive")
        composition = verify_composition(original, composed, record)
        if composition["member_sha256"].get(profile.player_member) != profile.player_sha256:
            raise ChainError(
                f"composed player master differs from the mirror's: {profile.player_member}"
            )

    start = int(section.get("panel_start_year", profile.default_panel_start_year))
    end = int(section.get("panel_end_year", plan.panel_end_year))
    destination = output_dir or resolve_output_under_root(section["output_dir"], label="output_dir")

    report = build(ArchiveSource(composed, composed_hash), profile, destination, start, end)

    player_master: dict[str, Any] = {
        "member": profile.player_member,
        "sha256": profile.player_sha256,
        "identical_to_mirror": True,
    }
    if section.get("write_player_master", tour != "ATP"):
        player_master["extracted"] = extract_player_master(original, profile, destination)
    launch = {
        "id": f"tennislab-archive-panel-launch-{tour}",
        "tour": tour,
        "year_plan": plan.as_document(),
        "panel_span": [start, end],
        "original_archive": {"path": relative_to_root(original), "sha256": original_hash},
        "composed_archive": {"path": relative_to_root(composed), "sha256": composed_hash},
        "bridge_summary": (
            None
            if summary_path is None
            else {"path": relative_to_root(summary_path), "sha256": sha256(summary_path)}
        ),
        "player_master": player_master,
        "composition": composition,
        "build_report_rows": report.get("panel_rows", report.get("rows")),
        "code": code_receipt(__name__),
    }
    atomic_json(destination / "archive_panel_launch.json", launch)
    return {"launch": launch, "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        document = read_config(args.config)
        plan = year_plan(document)
        section = document["archive_panel"]
        tour = str(section.get("tour", document.get("tour", "ATP"))).upper()
        profile_for(tour)
        require_bridge(
            tour,
            int(section.get("panel_end_year", plan.panel_end_year)),
            section.get("bridge_summary"),
        )
        original = resolve_under_root(section["original_archive"], label="original_archive")
        require_hash(original, MIRROR_SHA256, label="original mirror archive")
        if section.get("bridge_summary") is not None:
            summary_path = resolve_under_root(section["bridge_summary"], label="bridge_summary")
            if not summary_path.is_file():
                raise ChainError(f"bridge summary not yet written: {summary_path}")
        print(json.dumps({"status": "dry_run_ok", "year_plan": plan.as_document()}, sort_keys=True))
        return 0
    result = run(args.config, args.output_dir)
    print(
        json.dumps(
            {
                "composed_archive": result["launch"]["composed_archive"]["path"],
                "panel_span": result["launch"]["panel_span"],
                "bridge_extended_members": result["launch"]["composition"]["bridge_extended"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
