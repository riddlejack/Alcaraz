"""Pair retained tennis-data WTA rows with the WTA mirror panel through the frozen crosswalk.

Stage ``join`` (WTA). Ported from the archive's
``references/WTA02_models/wta_market_join.py``; there is no TIER01 counterpart of this
file (the ATP tour has :mod:`tennislab.panel.join`), so nothing was merged. It is a
separate program rather than a WTA mode of the ATP join because the ATP join's evidence
is ATP evidence -- CH01's player and event crosswalks, MULTI01's alias-context file, the
recovered 2018 workbook and two named source-date anomaly rules -- none of which exists
for the WTA side, which instead has a qualified, frozen event-edition crosswalk with its
own verification.

What this program does, and only this:

1. Reads the retained WTAODDS01 workbooks with **every** column, and proves it read the
   same rows the frozen crosswalk read by reproducing ``wta_sources.load_td_season``'s
   own identifying tuples row for row.
2. Rebuilds each season's surname classes with ``wta_sources.season_surname_canon``, the
   function the crosswalk used, and checks the links it produces against the frozen
   ``surname_class_links.csv``. A link is *evidence about a key*, not a player-identity
   claim, so every row whose pairing depends on one is marked ``link_dependent`` and can
   only reach the provisional tier downstream.
3. For every **accepted** crosswalk edition, pairs tennis-data rows to mirror panel rows
   on the crosswalk's own key -- (winner surname class, loser surname class, round) under
   the round alignment the crosswalk froze for that edition -- and admits a pair only
   when the key identifies exactly one row on each side.
4. Reports, never resolves: a key with multiplicity on either side, a tennis-data row
   with no mirror counterpart, a reversed winner label, a missing or out-of-window date.
5. Carries the prices and the field-agreement flags both sources can speak to: surface,
   best_of, status and the score.

It computes no probability, fits nothing, reads no ranking and repairs no source value.
Seasons 2025 and 2026 are refused unless the join config carries
``reserved_release_acknowledged: true``.

What changed from the archive revision: ``wta_sources`` is imported by name as
:mod:`tennislab.sources.wta_sources` instead of being loaded by path (its config entry
stays a declared binding, still resolved and hashed into ``inputs.sources_module``), and
``inputs.code`` is the package module's receipt instead of the archive file's path and
hash.

RESERVED WINDOW. It reads WTA winner/loser fields as history; it is downstream of the
panel build, the declared exposure event.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import tarfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_csv,
    atomic_json,
    code_receipt,
    declared_binding,
    read_config,
    read_csv_rows,
    relative_to_root,
    require_hash,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
    year_plan,
)
from tennislab.sources import wta_sources as sources

FORBIDDEN_SEASONS = (2025, 2026)
DATE_WINDOW = (-2, 21)
CARRIED_STATUS = "accepted_carried_forward"
ACCEPTED_STATUSES = ("accepted", "accepted_split", CARRIED_STATUS)
PRICE_BOOKS = ("PS", "B365")

MARKET_FIELDS = (
    "season",
    "market_source_path",
    "market_source_row",
    "market_source_sha256",
    "market_location",
    "market_tournament",
    "market_event_number",
    "market_date",
    "market_tier",
    "market_court",
    "market_surface",
    "market_round",
    "market_best_of",
    "market_winner",
    "market_loser",
    "market_comment",
    "market_set_games",
    "PSW",
    "PSL",
    "PS_pair_quality",
    "B365W",
    "B365L",
    "B365_pair_quality",
    "tourney_id",
    "tourney_name",
    "crosswalk_status",
    "round_alignment",
    "pair_key",
    "archive_source_key",
    "archive_match_num",
    "archive_round",
    "archive_status",
    "archive_score",
    "archive_surface",
    "archive_best_of",
    "archive_anchor_date",
    "archive_a_won",
    "pairing_status",
    "pairing_basis",
    "link_dependent",
    "edition_depends_on_surname_link",
    "date_window_agreement",
    "round_agreement",
    "surface_agreement",
    "best_of_agreement",
    "status_agreement",
    "score_agreement",
    "winner_agreement",
    "market_date_basis",
)
UNPAIRED_MIRROR_FIELDS = (
    "season",
    "source_key",
    "tourney_id",
    "tourney_name",
    "round",
    "status",
    "reason",
)
LINK_CHECK_FIELDS = ("season", "td_player", "mirror_surname", "evidence", "agreement")


# --------------------------------------------------------------------- helpers


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()[:10]
    return str(value).strip()


def decimal_price(value: Any) -> float | None:
    raw = text(value)
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    return parsed


def price_quality(win: Any, lose: Any) -> str:
    """The ATP join's own vocabulary: both decimals present, numeric and above 1."""
    left, right = decimal_price(win), decimal_price(lose)
    if left is None and right is None:
        return "both_missing"
    if left is None or right is None:
        return "one_sided"
    if left > 1.0 and right > 1.0:
        return "valid_decimal_gt_1"
    return "invalid_decimal"


SET_SCORE = re.compile(r"^(\d+)-(\d+)(?:\((\d+)\))?$")


def mirror_set_games(score: str) -> list[tuple[int, int]] | None:
    """Set games from a mirror score string, or None when it is not a played score."""
    games: list[tuple[int, int]] = []
    for token in (score or "").split():
        upper = token.upper()
        if upper in {"RET", "DEF", "DEF.", "W/O", "WALKOVER", "ABN", "ABD", "UNFINISHED"}:
            break
        match = SET_SCORE.match(token)
        if match is None:
            return None
        games.append((int(match.group(1)), int(match.group(2))))
    return games or None


def market_set_games(row: Mapping[str, Any]) -> list[tuple[int, int]] | None:
    games: list[tuple[int, int]] = []
    for index in (1, 2, 3):
        win, lose = text(row.get(f"W{index}")), text(row.get(f"L{index}"))
        if not win and not lose:
            continue
        try:
            games.append((int(float(win)), int(float(lose))))
        except ValueError:
            return None
    return games or None


def score_agreement(market: Mapping[str, Any], archive_score: str) -> str:
    """Set-by-set agreement. The WTA workbooks carry W1/L1..W3/L3; the ATP ones do not."""
    market_games = market_set_games(market)
    archive_games = mirror_set_games(archive_score)
    if market_games is None or archive_games is None:
        return "not_observable"
    return "agree" if market_games == archive_games else "disagree"


def normalized_surface(value: str) -> str:
    return re.sub(r"[^a-z]", "", (value or "").lower())


def parse_anchor(value: str) -> dt.date | None:
    raw = (value or "").strip()
    if len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
    except ValueError:
        return None


def parse_market_date(value: str) -> dt.date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


# ------------------------------------------------------------------- td reader


def frozen_horizon() -> int:
    return max(int(season) for season in sources.SEASONS)


def load_td_season_any(season: int, path: Path) -> list[dict[str, Any]]:
    """``wta_sources.load_td_season`` for a frozen season; the same reading for a later one.

    WTA02. The frozen loader addresses its workbooks by season under WTAODDS01's own
    directory and refuses 2025/2026. A bridge season's workbook lives where the bridge's
    manifest says, so it is read here with the frozen module's own ``_read_xlsx``,
    ``_blank``, ``_text`` and ``_as_date``, producing the identical dict shape.
    """
    if season <= frozen_horizon():
        return sources.load_td_season(season)
    header, raw = sources._read_xlsx(str(path))
    index = {name: position for position, name in enumerate(header) if name}
    out: list[dict[str, Any]] = []
    for number, values in enumerate(raw, start=2):
        if sources._blank(values):
            continue

        def col(name: str, values: Any = values) -> Any:
            position = index.get(name)
            return values[position] if position is not None and position < len(values) else None

        out.append(
            {
                "season": season,
                "row": number,
                "wta": sources._text(col("WTA")),
                "location": sources._text(col("Location")),
                "tournament": sources._text(col("Tournament")),
                "date": sources._as_date(col("Date")),
                "tier": sources._text(col("Tier")),
                "court": sources._text(col("Court")),
                "surface": sources._text(col("Surface")),
                "round": sources._text(col("Round")),
                "best_of": sources._text(col("Best of")),
                "winner": sources._text(col("Winner")),
                "loser": sources._text(col("Loser")),
                "comment": sources._text(col("Comment")),
            }
        )
    return out


def load_mirror_season_any(
    season: int, composed_archive: Path | None, tar_root: str
) -> list[dict[str, Any]]:
    """``wta_sources.load_mirror_season`` for a frozen season; the composed archive later."""
    if season <= frozen_horizon():
        return sources.load_mirror_season(season)
    if composed_archive is None:
        raise ChainError(f"season {season} needs the bridge's composed archive; none declared")
    member = f"{tar_root}/wta/wta_matches_{season}.csv"
    with tarfile.open(composed_archive, "r:gz") as tar:
        handle = tar.extractfile(member)
        if handle is None:
            raise ChainError(f"composed archive lacks {member}")
        payload = handle.read().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(payload)))
    for row in rows:
        row["season"] = season
    return rows


def load_market_season(
    season: int, path: Path, frozen: Sequence[Mapping[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Every column of one workbook, with the frozen loader's own row identity re-checked.

    ``wta_sources.load_td_season`` keeps only the identifying columns, so this reads the
    sheet again through the same two readers and then proves the two row sequences are
    the same rows: same count, same (location, tournament, round, winner, loser, date).
    A drift here would mean the crosswalk and the join are looking at different rows.
    """
    extension = sources.TD_EXT.get(season, "xlsx")
    reader = sources._read_xls if extension == "xls" else sources._read_xlsx
    header, raw = reader(str(path))
    index = {name: position for position, name in enumerate(header) if name}
    rows: list[dict[str, Any]] = []
    for number, values in enumerate(raw, start=2):
        if sources._blank(values):
            continue
        record: dict[str, Any] = {"season": season, "row": number}
        for name, position in index.items():
            record[name] = values[position] if position < len(values) else None
        record["market_date"] = sources._as_date(record.get("Date"))
        rows.append(record)
    if frozen is None:
        frozen = sources.load_td_season(season)
    if len(frozen) != len(rows):
        raise ChainError(f"{season}: workbook row count differs from the frozen loader")
    for mine, theirs in zip(rows, frozen, strict=True):
        signature = (
            mine["row"],
            text(mine.get("Location")),
            text(mine.get("Tournament")),
            text(mine.get("Round")),
            text(mine.get("Winner")),
            text(mine.get("Loser")),
            mine["market_date"],
        )
        expected = (
            theirs["row"],
            theirs["location"],
            theirs["tournament"],
            theirs["round"],
            theirs["winner"],
            theirs["loser"],
            theirs["date"],
        )
        if signature != expected:
            raise ChainError(f"{season}: workbook row {mine['row']} differs from the frozen loader")
    return rows


# ----------------------------------------------------------------- round depth


def market_depths(rows: Sequence[Mapping[str, Any]], alignment: str) -> list[str]:
    ordinal = sources.td_max_ordinal(text(row.get("Round")) for row in rows)
    if alignment == "relative_round_depth":
        relative = sources.relative_depths(
            sources.td_round_order(text(row.get("Round")), ordinal) for row in rows
        )
        return [
            f"rel{relative[sources.td_round_order(text(row.get('Round')), ordinal)]}"
            for row in rows
        ]
    return [str(sources.td_round_depth(text(row.get("Round")), ordinal)) for row in rows]


def archive_depths(rows: Sequence[Mapping[str, str]], alignment: str) -> list[str]:
    if alignment == "relative_round_depth":
        relative = sources.relative_depths(
            sources.MIRROR_ROUND_ORDER.get(row["round"].strip(), 200) for row in rows
        )
        return [
            f"rel{relative[sources.MIRROR_ROUND_ORDER.get(row['round'].strip(), 200)]}"
            for row in rows
        ]
    return [row["round"].strip() for row in rows]


# ------------------------------------------------------------------ the pairing


def pair_edition(
    market_rows: Sequence[Mapping[str, Any]],
    archive_rows: Sequence[Mapping[str, str]],
    td_canon: Mapping[str, str],
    mirror_canon: Mapping[str, str],
    alignment: str,
) -> tuple[dict[int, dict[str, Any]], dict[str, str]]:
    """Pair one accepted edition's rows. Returns (market row number -> outcome, mirror reasons).

    A pair is admitted only when its key selects exactly one row on each side. Anything
    else is labelled and left alone: ``ambiguous_pair_key`` (the key repeats),
    ``no_mirror_counterpart``, ``winner_orientation_conflict`` (the reversed key is the
    one that matches).
    """
    market_keys = market_depths(market_rows, alignment)
    archive_keys = archive_depths(archive_rows, alignment)

    market_groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for position, (row, depth) in enumerate(zip(market_rows, market_keys, strict=True)):
        key = (
            td_canon.get(text(row.get("Winner")), ""),
            td_canon.get(text(row.get("Loser")), ""),
            depth,
        )
        market_groups[key].append(position)
    archive_groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for position, (row, depth) in enumerate(zip(archive_rows, archive_keys, strict=True)):
        # outcome-history read: the mirror's own orientation forms the pairing key.
        winner = row["a_source_name"] if row["a_won"] == "true" else row["b_source_name"]
        loser = row["b_source_name"] if row["a_won"] == "true" else row["a_source_name"]
        key = (mirror_canon.get(winner, ""), mirror_canon.get(loser, ""), depth)
        archive_groups[key].append(position)

    outcomes: dict[int, dict[str, Any]] = {}
    used_archive: set[int] = set()
    for key, positions in sorted(market_groups.items()):
        archive_positions = archive_groups.get(key, [])
        reversed_key = (key[1], key[0], key[2])
        reversed_positions = archive_groups.get(reversed_key, [])
        for position in positions:
            record: dict[str, Any] = {"pair_key": "|".join(key), "archive": None}
            if len(positions) > 1 or len(archive_positions) > 1:
                record["pairing_status"] = "ambiguous_pair_key"
                record["pairing_basis"] = (
                    f"market_rows={len(positions)};mirror_rows={len(archive_positions)}"
                )
                record["winner_agreement"] = ""
            elif len(archive_positions) == 1:
                record["pairing_status"] = "matched"
                record["pairing_basis"] = f"unique_pair_key:{alignment}"
                record["winner_agreement"] = "agree"
                record["archive"] = archive_positions[0]
                used_archive.add(archive_positions[0])
            elif len(reversed_positions) == 1 and reversed_positions[0] not in used_archive:
                record["pairing_status"] = "winner_orientation_conflict"
                record["pairing_basis"] = f"reversed_pair_key:{alignment}"
                record["winner_agreement"] = "reversed"
                record["archive"] = reversed_positions[0]
            elif reversed_positions:
                record["pairing_status"] = "winner_orientation_conflict"
                record["pairing_basis"] = f"reversed_pair_key_ambiguous:{len(reversed_positions)}"
                record["winner_agreement"] = "reversed"
            else:
                record["pairing_status"] = "no_mirror_counterpart"
                record["pairing_basis"] = "pair_key_absent_from_mirror_edition"
                record["winner_agreement"] = ""
            outcomes[market_rows[position]["row"]] = record

    mirror_reasons: dict[str, str] = {}
    for key, positions in archive_groups.items():
        for position in positions:
            if position in used_archive:
                continue
            row = archive_rows[position]
            if len(positions) > 1 or len(market_groups.get(key, [])) > 1:
                mirror_reasons[row["source_key"]] = "ambiguous_pair_key"
            elif key in market_groups or (key[1], key[0], key[2]) in market_groups:
                mirror_reasons[row["source_key"]] = "market_row_not_admitted"
            else:
                mirror_reasons[row["source_key"]] = "no_market_counterpart"
    return outcomes, mirror_reasons


# ------------------------------------------------------------------- the stage


def run(output_dir: Path, config_path: Path) -> dict[str, Any]:
    document = read_config(config_path)
    plan = year_plan(document)
    section = document.get("wta_join")
    if not isinstance(section, dict):
        raise ChainError("configuration has no wta_join object")

    sources_binding = declared_binding(section["sources_module"], label="sources_module")

    event_map_dir = resolve_under_root(section["event_map_dir"], label="event_map_dir")
    frozen_crosswalk_path = event_map_dir / "wta_event_crosswalk.csv"
    crosswalk_path = frozen_crosswalk_path
    links_path = event_map_dir / "surname_class_links.csv"
    conflicts_path = event_map_dir / "winner_orientation_conflicts.csv"
    residuals_path = event_map_dir / "accepted_edition_key_residuals.csv"
    defects_path = event_map_dir / "td_row_date_defects.csv"
    manifest_entry = section["event_map_manifest"]
    manifest_path = resolve_under_root(manifest_entry["path"], label="event_map_manifest")
    manifest_hash = require_hash(
        manifest_path, manifest_entry.get("sha256"), label="event_map_manifest"
    )
    bound = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    for path in (
        frozen_crosswalk_path,
        links_path,
        conflicts_path,
        residuals_path,
        defects_path,
    ):
        declared = bound.get(path.name)
        if declared is None:
            raise ChainError(f"event-map manifest does not bind {path.name}")
        require_hash(path, declared["sha256"], label=path.name)
    acknowledged = section.get("reserved_release_acknowledged") is True
    frozen_max_season = frozen_horizon()
    # WTA02: the carry-forward stage's extended crosswalk, whose leading rows must be the
    # frozen file's rows exactly (checked below) and whose added rows are carried
    # editions of seasons past the frozen horizon.
    extended_entry = section.get("event_crosswalk")
    extended_hash = None
    if extended_entry:
        extended_path = resolve_under_root(
            extended_entry["path"] if isinstance(extended_entry, Mapping) else extended_entry,
            label="event_crosswalk",
        )
        extended_hash = require_hash(
            extended_path,
            extended_entry.get("sha256") if isinstance(extended_entry, Mapping) else None,
            label="event_crosswalk",
        )
        _, frozen_rows = read_csv_rows(frozen_crosswalk_path)
        _, extended_rows = read_csv_rows(extended_path)
        if len(extended_rows) < len(frozen_rows):
            raise ChainError("extended event crosswalk is shorter than the frozen one")
        for position, (frozen_row, extended_row) in enumerate(
            zip(frozen_rows, extended_rows, strict=False), start=2
        ):
            for field, value in frozen_row.items():
                if extended_row.get(field, "") != value:
                    raise ChainError(
                        f"extended event crosswalk differs from the frozen rows at line "
                        f"{position}, field {field}"
                    )
        for row in extended_rows[len(frozen_rows) :]:
            if row["status"] != CARRIED_STATUS or int(row["season"]) <= frozen_max_season:
                raise ChainError(
                    "extended event crosswalk carries a row that is neither frozen nor a "
                    f"carried later-season edition: {row['season']} {row['td_location']}"
                )
        crosswalk_path = extended_path
    composed_archive: Path | None = None
    composed_hash = None
    tar_root = ""

    market_manifest_entry = section["market_manifest"]
    market_manifest_path = resolve_under_root(
        market_manifest_entry["path"], label="market_manifest"
    )
    market_manifest_hash = require_hash(
        market_manifest_path, market_manifest_entry.get("sha256"), label="market_manifest"
    )
    market_records = {
        int(record["year"]): record
        for record in json.loads(market_manifest_path.read_text(encoding="utf-8"))["records"]
        if record.get("tour") == "WTA" and "year" in record and record.get("year")
    }
    # WTA02: the bridge's per-row provenance says which market rows were synthesized from
    # a draw page and dated at the event's end; the panel labels those dates
    # `inferred_event_end`. A retained WTAODDS01 season has no provenance file and every
    # row is a tennis-data reported date.
    date_basis_by_row: dict[tuple[int, int], str] = {}
    provenance_path = market_manifest_path.parent / "market_row_provenance.csv"
    if provenance_path.is_file():
        _, provenance_rows = read_csv_rows(provenance_path)
        for row in provenance_rows:
            date_basis_by_row[(int(row["market_season"]), int(row["market_source_row"]))] = (
                row.get("market_date_basis") or "tennis_data_reported_date"
            )

    panel_dir = resolve_under_root(section["archive_panel_dir"], label="archive_panel_dir")
    panel_path = panel_dir / "source_panel.csv"
    panel_hash = require_hash(
        panel_path, section.get("archive_panel_sha256"), label="archive_panel"
    )
    launch_path = panel_dir / "archive_panel_launch.json"
    if launch_path.is_file():
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
        record = launch.get("composed_archive") or {}
        if record.get("path"):
            composed_archive = resolve_under_root(record["path"], label="composed_archive")
            composed_hash = require_hash(
                composed_archive, record.get("sha256"), label="composed_archive"
            )
            tar_root = str(sources.TAR_PREFIX)

    start = int(section.get("panel_start_year", 2007))
    end = int(section.get("panel_end_year", plan.panel_end_year))
    if end > plan.panel_end_year:
        raise ChainError(f"join span end {end} exceeds panel_end_year {plan.panel_end_year}")
    for season in range(start, end + 1):
        if season in FORBIDDEN_SEASONS and not acknowledged:
            raise ChainError(
                f"season {season} is inside the reserved window; the join config must "
                "carry reserved_release_acknowledged: true after the exposure event is logged"
            )

    _, panel_rows = read_csv_rows(panel_path)
    panel_by_season: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in panel_rows:
        panel_by_season[int(row["season"])].append(row)

    _, crosswalk_rows = read_csv_rows(crosswalk_path)
    _, frozen_links = read_csv_rows(links_path)
    _, frozen_conflicts = read_csv_rows(conflicts_path)
    _, frozen_defects = read_csv_rows(defects_path)

    emitted: list[dict[str, Any]] = []
    unpaired_mirror: list[dict[str, Any]] = []
    link_checks: list[dict[str, Any]] = []
    per_season: list[dict[str, Any]] = []
    observed_conflicts: list[dict[str, str]] = []
    new_seasons = [season for season in range(start, end + 1) if season > frozen_max_season]

    for season in range(start, end + 1):
        record = market_records.get(season)
        if record is None:
            raise ChainError(f"WTAODDS01 manifest has no WTA record for {season}")
        workbook = resolve_under_root(record["path"], label=f"workbook {season}")
        workbook_hash = require_hash(workbook, record["sha256"], label=f"workbook {season}")
        td_identity_rows = load_td_season_any(season, workbook)
        market_rows = load_market_season(season, workbook, frozen=td_identity_rows)
        archive_rows = panel_by_season.get(season, [])

        mirror_full = load_mirror_season_any(season, composed_archive, tar_root)
        td_canon, mirror_canon, links = sources.season_surname_canon(td_identity_rows, mirror_full)
        linked_players = {entry["td_player"] for entry in links}
        expected_links = {row["td_player"] for row in frozen_links if int(row["season"]) == season}
        for player in sorted(linked_players | expected_links):
            link_checks.append(
                {
                    "season": season,
                    "td_player": player,
                    "mirror_surname": next(
                        (
                            entry.get("mirror_surname", "")
                            for entry in links
                            if entry["td_player"] == player
                        ),
                        "",
                    ),
                    "evidence": next(
                        (
                            entry.get("evidence", "")
                            for entry in links
                            if entry["td_player"] == player
                        ),
                        "",
                    ),
                    "agreement": (
                        "both"
                        if player in linked_players and player in expected_links
                        else "observed_only"
                        if player in linked_players
                        else "frozen_only"
                    ),
                }
            )

        editions = defaultdict(list)
        for row in crosswalk_rows:
            if int(row["season"]) != season or row["status"] not in ACCEPTED_STATUSES:
                continue
            editions[(row["td_location"], row["td_tournament"])].append(row)
        unresolved = {
            (row["td_location"], row["td_tournament"]): row["status"]
            for row in crosswalk_rows
            if int(row["season"]) == season and row["status"] not in ACCEPTED_STATUSES
        }

        archive_by_tourney: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in archive_rows:
            archive_by_tourney[row["tourney_id"]].append(row)

        market_by_block: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in market_rows:
            market_by_block[(text(row.get("Location")), text(row.get("Tournament")))].append(row)

        outcomes: dict[int, dict[str, Any]] = {}
        edition_meta: dict[int, dict[str, str]] = {}
        mirror_reasons: dict[str, str] = {}
        claimed_mirror_editions: set[str] = set()
        for block, rows in sorted(market_by_block.items()):
            mapped = editions.get(block, [])
            if not mapped:
                status = unresolved.get(block, "absent_from_crosswalk")
                for row in rows:
                    outcomes[row["row"]] = {
                        "pair_key": "",
                        "archive": None,
                        "pairing_status": "edition_unresolved",
                        "pairing_basis": f"crosswalk_status={status}",
                        "winner_agreement": "",
                    }
                    edition_meta[row["row"]] = {
                        "tourney_id": "",
                        "tourney_name": "",
                        "crosswalk_status": status,
                        "round_alignment": "",
                        "edition_depends_on_surname_link": "",
                    }
                continue
            for entry in mapped:
                if len(mapped) > 1:
                    subset = [
                        row for row in rows if text(row.get("WTA")) == entry["td_event_number"]
                    ]
                else:
                    subset = rows
                if not subset:
                    raise ChainError(
                        f"{season}: split edition {block} has no rows for event number "
                        f"{entry['td_event_number']!r}"
                    )
                tourney_id = entry["tourney_id"]
                if tourney_id in claimed_mirror_editions:
                    raise ChainError(f"{season}: mirror edition {tourney_id} claimed twice")
                claimed_mirror_editions.add(tourney_id)
                alignment = entry["round_alignment"] or "absolute_round_label"
                edition_archive = archive_by_tourney.get(tourney_id, [])
                paired, reasons = pair_edition(
                    subset, edition_archive, td_canon, mirror_canon, alignment
                )
                for number, outcome in paired.items():
                    outcome["archive_row"] = (
                        edition_archive[outcome["archive"]]
                        if outcome["archive"] is not None
                        else None
                    )
                    outcomes[number] = outcome
                    edition_meta[number] = {
                        "tourney_id": tourney_id,
                        "tourney_name": entry["tourney_name"],
                        "crosswalk_status": entry["status"],
                        "round_alignment": alignment,
                        "edition_depends_on_surname_link": entry["depends_on_surname_link"],
                    }
                mirror_reasons.update(reasons)

        for row in market_rows:
            outcome = outcomes[row["row"]]
            meta = edition_meta[row["row"]]
            archive_row = outcome.get("archive_row")
            market_date = row["market_date"]
            anchor = parse_anchor(archive_row["tourney_anchor_date"]) if archive_row else None
            if market_date is None:
                window = ""
            elif anchor is None:
                window = "not_observable"
            else:
                gap = (market_date - anchor).days
                window = str(DATE_WINDOW[0] <= gap <= DATE_WINDOW[1]).lower()
            winner_name, loser_name = text(row.get("Winner")), text(row.get("Loser"))
            emitted.append(
                {
                    "season": season,
                    "market_source_path": relative_to_root(workbook),
                    "market_source_row": row["row"],
                    "market_source_sha256": workbook_hash,
                    "market_location": text(row.get("Location")),
                    "market_tournament": text(row.get("Tournament")),
                    "market_event_number": text(row.get("WTA")),
                    "market_date": "" if market_date is None else market_date.isoformat(),
                    "market_tier": text(row.get("Tier")),
                    "market_court": text(row.get("Court")),
                    "market_surface": text(row.get("Surface")),
                    "market_round": text(row.get("Round")),
                    "market_best_of": text(row.get("Best of")),
                    "market_winner": winner_name,
                    "market_loser": loser_name,
                    "market_comment": text(row.get("Comment")),
                    "market_set_games": json.dumps(market_set_games(row)),
                    "PSW": text(row.get("PSW")),
                    "PSL": text(row.get("PSL")),
                    "PS_pair_quality": price_quality(row.get("PSW"), row.get("PSL")),
                    "B365W": text(row.get("B365W")),
                    "B365L": text(row.get("B365L")),
                    "B365_pair_quality": price_quality(row.get("B365W"), row.get("B365L")),
                    **meta,
                    "pair_key": outcome["pair_key"],
                    "archive_source_key": archive_row["source_key"] if archive_row else "",
                    "archive_match_num": archive_row["match_num"] if archive_row else "",
                    "archive_round": archive_row["round"] if archive_row else "",
                    "archive_status": archive_row["status"] if archive_row else "",
                    "archive_score": archive_row["score"] if archive_row else "",
                    "archive_surface": archive_row["surface"] if archive_row else "",
                    "archive_best_of": archive_row["best_of"] if archive_row else "",
                    "archive_anchor_date": archive_row["tourney_anchor_date"]
                    if archive_row
                    else "",
                    "archive_a_won": archive_row["a_won"] if archive_row else "",
                    "pairing_status": outcome["pairing_status"],
                    "pairing_basis": outcome["pairing_basis"],
                    "link_dependent": str(
                        winner_name in linked_players or loser_name in linked_players
                    ).lower(),
                    "date_window_agreement": window,
                    "round_agreement": (
                        ""
                        if archive_row is None
                        else "agree"
                        if outcome["pairing_status"] in {"matched", "winner_orientation_conflict"}
                        else "disagree"
                    ),
                    "surface_agreement": (
                        ""
                        if archive_row is None
                        else "agree"
                        if normalized_surface(text(row.get("Surface")))
                        == normalized_surface(archive_row["surface"])
                        else "disagree"
                    ),
                    "best_of_agreement": (
                        ""
                        if archive_row is None
                        else "agree"
                        if text(row.get("Best of")) == archive_row["best_of"]
                        else "disagree"
                    ),
                    "status_agreement": (
                        ""
                        if archive_row is None
                        else "agree"
                        if MARKET_STATUS.get(text(row.get("Comment")), "") == archive_row["status"]
                        else "disagree"
                    ),
                    "score_agreement": (
                        "" if archive_row is None else score_agreement(row, archive_row["score"])
                    ),
                    "winner_agreement": outcome["winner_agreement"],
                    "market_date_basis": date_basis_by_row.get(
                        (season, int(row["row"])), "tennis_data_reported_date"
                    ),
                }
            )
            if outcome["pairing_status"] == "winner_orientation_conflict" and archive_row:
                observed_conflicts.append(
                    {
                        "season": str(season),
                        "td_row": str(row["row"]),
                        "tourney_id": meta["tourney_id"],
                        "mirror_match_num": archive_row["match_num"],
                    }
                )

        for row in archive_rows:
            reason = mirror_reasons.get(row["source_key"])
            if reason is None and row["tourney_id"] not in claimed_mirror_editions:
                reason = "edition_not_mapped_to_a_market_edition"
            if reason is None:
                continue
            unpaired_mirror.append(
                {
                    "season": season,
                    "source_key": row["source_key"],
                    "tourney_id": row["tourney_id"],
                    "tourney_name": row["tourney_name"],
                    "round": row["round"],
                    "status": row["status"],
                    "reason": reason,
                }
            )

        season_rows = [row for row in emitted if row["season"] == season]
        per_season.append(
            {
                "season": season,
                "beyond_frozen_crosswalk_horizon": season > frozen_max_season,
                "market_rows": len(market_rows),
                "archive_rows": len(archive_rows),
                "matched": sum(1 for row in season_rows if row["pairing_status"] == "matched"),
                "matched_in_carried_editions": sum(
                    1
                    for row in season_rows
                    if row["pairing_status"] == "matched"
                    and row["crosswalk_status"] == CARRIED_STATUS
                ),
                "carried_editions": len(
                    {
                        row["tourney_id"]
                        for row in season_rows
                        if row["crosswalk_status"] == CARRIED_STATUS
                    }
                ),
                "pairing_status_counts": dict(
                    sorted(Counter(row["pairing_status"] for row in season_rows).items())
                ),
                "matched_with_valid_ps": sum(
                    1
                    for row in season_rows
                    if row["pairing_status"] == "matched"
                    and row["PS_pair_quality"] == "valid_decimal_gt_1"
                ),
                "link_dependent_matched": sum(
                    1
                    for row in season_rows
                    if row["pairing_status"] == "matched" and row["link_dependent"] == "true"
                ),
                "edition_link_dependent_matched": sum(
                    1
                    for row in season_rows
                    if row["pairing_status"] == "matched"
                    and row["edition_depends_on_surname_link"] == "True"
                ),
                "disagreements": {
                    field: dict(
                        sorted(
                            Counter(
                                row[field]
                                for row in season_rows
                                if row["pairing_status"] == "matched"
                            ).items()
                        )
                    )
                    for field in (
                        "surface_agreement",
                        "best_of_agreement",
                        "status_agreement",
                        "score_agreement",
                        "date_window_agreement",
                    )
                },
            }
        )

    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "market_rows.csv": atomic_csv(output_dir / "market_rows.csv", MARKET_FIELDS, emitted),
        "mirror_rows_without_market.csv": atomic_csv(
            output_dir / "mirror_rows_without_market.csv", UNPAIRED_MIRROR_FIELDS, unpaired_mirror
        ),
        "surname_link_check.csv": atomic_csv(
            output_dir / "surname_link_check.csv", LINK_CHECK_FIELDS, link_checks
        ),
    }

    frozen_conflict_keys = {
        (row["season"], row["tourney_id"], row["mirror_match_num"]) for row in frozen_conflicts
    }
    observed_conflict_keys = {
        (row["season"], row["tourney_id"], row["mirror_match_num"])
        for row in observed_conflicts
        if int(row["season"]) <= frozen_max_season
    }
    new_season_conflicts = sorted(
        (row["season"], row["tourney_id"], row["mirror_match_num"])
        for row in observed_conflicts
        if int(row["season"]) > frozen_max_season
    )
    defect_rows = {(row["season"], row["td_row"]) for row in frozen_defects}
    observed_defects = {
        (str(row["season"]), str(row["market_source_row"]))
        for row in emitted
        if row["date_window_agreement"] == "false" and int(row["season"]) <= frozen_max_season
    }
    new_season_defects = sorted(
        (str(row["season"]), str(row["market_source_row"]))
        for row in emitted
        if row["date_window_agreement"] == "false" and int(row["season"]) > frozen_max_season
    )
    matched = [row for row in emitted if row["pairing_status"] == "matched"]
    manifest = {
        "id": "WTA02-market-join",
        "tour": "WTA",
        "status": "market_rows_paired_no_model_no_repair",
        "span": [start, end],
        "frozen_crosswalk_horizon": frozen_max_season,
        "seasons_beyond_frozen_horizon": new_seasons,
        "reserved_release_acknowledged": acknowledged,
        "year_plan": plan.as_document(),
        "inputs": {
            "archive_panel": {"path": relative_to_root(panel_path), "sha256": panel_hash},
            "composed_archive": (
                None
                if composed_archive is None
                else {"path": relative_to_root(composed_archive), "sha256": composed_hash}
            ),
            "event_crosswalk": {
                "path": relative_to_root(crosswalk_path),
                "sha256": sha256(crosswalk_path),
            },
            "event_crosswalk_extended": extended_hash is not None,
            "event_map_dir": relative_to_root(event_map_dir),
            "event_map_manifest": {
                "path": relative_to_root(manifest_path),
                "sha256": manifest_hash,
            },
            "market_manifest": {
                "path": relative_to_root(market_manifest_path),
                "sha256": market_manifest_hash,
            },
            "sources_module": sources_binding,
            "code": code_receipt(__name__),
        },
        "market_rows": len(emitted),
        "matched_rows": len(matched),
        "pairing_status_counts": dict(
            sorted(Counter(row["pairing_status"] for row in emitted).items())
        ),
        "matched_with_valid_ps": sum(
            1 for row in matched if row["PS_pair_quality"] == "valid_decimal_gt_1"
        ),
        "link_dependent_matched_rows": sum(1 for row in matched if row["link_dependent"] == "true"),
        "edition_link_dependent_matched_rows": sum(
            1 for row in matched if row["edition_depends_on_surname_link"] == "True"
        ),
        "mirror_rows_without_market": len(unpaired_mirror),
        "mirror_reason_counts": dict(
            sorted(Counter(row["reason"] for row in unpaired_mirror).items())
        ),
        "per_season": per_season,
        "carried_editions_by_season": {
            str(season): len(
                {
                    row["tourney_id"]
                    for row in emitted
                    if row["season"] == season and row["crosswalk_status"] == CARRIED_STATUS
                }
            )
            for season in new_seasons
        },
        "matched_rows_in_carried_editions": sum(
            1 for row in matched if row["crosswalk_status"] == CARRIED_STATUS
        ),
        "matched_rows_by_market_date_basis": dict(
            sorted(Counter(row["market_date_basis"] for row in matched).items())
        ),
        "new_season_observations": {
            "orientation_conflicts": new_season_conflicts,
            "out_of_window_rows": new_season_defects,
            "surname_links": sorted(
                (row["season"], row["td_player"])
                for row in link_checks
                if int(row["season"]) > frozen_max_season
            ),
            "note": "seasons past the frozen crosswalk horizon have no frozen counts to "
            "agree with; these are reported, never compared",
        },
        "disagreement_tests": {
            "scope": f"frozen span {start}-{min(end, frozen_max_season)} only",
            "surname_links_observed_only": sorted(
                (row["season"], row["td_player"])
                for row in link_checks
                if row["agreement"] == "observed_only" and int(row["season"]) <= frozen_max_season
            ),
            "surname_links_frozen_only": sorted(
                (row["season"], row["td_player"])
                for row in link_checks
                if row["agreement"] == "frozen_only"
            ),
            "frozen_orientation_conflicts": len(frozen_conflict_keys),
            "observed_orientation_conflicts": len(observed_conflict_keys),
            "orientation_conflicts_agree": observed_conflict_keys == frozen_conflict_keys,
            "orientation_conflicts_observed_only": sorted(
                observed_conflict_keys - frozen_conflict_keys
            ),
            "orientation_conflicts_frozen_only": sorted(
                frozen_conflict_keys - observed_conflict_keys
            ),
            "frozen_date_defect_rows": sorted(defect_rows),
            "observed_out_of_window_rows": sorted(observed_defects),
        },
        "outputs": outputs,
        "limits": [
            "Event identity comes from the frozen crosswalk and is not re-derived here; "
            "the 3 ambiguous and 1 unmapped editions are labelled edition_unresolved.",
            "A season past the frozen horizon pairs through carried editions "
            "(accepted_carried_forward), the declared WTA02 assumption; a block with no "
            "carried edition is edition_unresolved and counted.",
            "A surname class is a key-folding aid, not a player identity. Rows whose "
            "pairing depends on a link carry link_dependent=true and cannot be primary.",
            "Reversed winner labels, repeated keys, missing dates and out-of-window dates "
            "are reported and excluded downstream; no row is repaired and no side is chosen.",
            "These workbooks carry no odds observation time, so no price here is a "
            "pre-match quote at a declared cutoff.",
        ],
    }
    atomic_json(output_dir / "join_manifest.json", manifest)
    return manifest


MARKET_STATUS = {
    "Completed": "completed",
    "Retired": "retired",
    "Walkover": "walkover",
    "Sched": "",
    "Cancelled": "",
    "": "",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        document = read_config(args.config)
        plan = year_plan(document)
        section = document["wta_join"]
        declared_binding(section["sources_module"], label="sources_module")
        for name in ("event_map_manifest", "market_manifest"):
            entry = section[name]
            require_hash(
                resolve_under_root(entry["path"], label=name), entry.get("sha256"), label=name
            )
        event_map_dir = resolve_under_root(section["event_map_dir"], label="event_map_dir")
        if not (event_map_dir / "wta_event_crosswalk.csv").is_file():
            raise ChainError(f"event map not found: {event_map_dir}")
        for season in range(int(section.get("panel_start_year", 2007)), plan.panel_end_year + 1):
            if (
                season in FORBIDDEN_SEASONS
                and section.get("reserved_release_acknowledged") is not True
            ):
                raise ChainError(f"season {season} is reserved and not acknowledged")
        print(json.dumps({"status": "dry_run_ok", "year_plan": plan.as_document()}, sort_keys=True))
        return 0
    manifest = run(resolve_output_under_root(args.output, label="output"), args.config)
    print(
        json.dumps(
            {
                "market_rows": manifest["market_rows"],
                "matched_rows": manifest["matched_rows"],
                "pairing_status_counts": manifest["pairing_status_counts"],
                "matched_with_valid_ps": manifest["matched_with_valid_ps"],
                "orientation_conflicts_agree": manifest["disagreement_tests"][
                    "orientation_conflicts_agree"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
