"""Generate auditable Tennis-Data/archive join candidates without resolving exceptions.

Stage ``join`` (ATP). Ported from the archive's ``TIER01_models/join_candidates.py``;
the ``WTA02_models`` copy of that file is byte-identical, so there is one revision and
nothing to merge. The WTA tour has its own join program (``tennislab.panel.wta_join``).

What changed from the archive revision:

* the module-level path globals and ``configure()``'s rebinding of them become a frozen
  :class:`JoinSettings` built once from the config document and passed explicitly, so
  ``prepare`` and ``join`` cannot disagree about which inputs they read;
* the qualified annual-workbook adapter (``work/MULTI01_market_acquisition/
  profile_annual.py``) is imported by name as :mod:`tennislab.sources.profile_annual`
  instead of being loaded by path. The config's ``market_profile_adapter`` entry stays a
  declared binding: it is still resolved and hashed into ``audit.json``;
* ``implementation.original_adapter`` and ``implementation.tests`` stay declared
  bindings too -- they name the MULTI01 parent this file was copied from and its test
  file, both still resolved and hashed -- while ``implementation.adapter`` becomes the
  package's own code receipt.

The scientific content -- the Q1-Q4 classification, the alias resolution, the
date-correction candidates and every agreement flag -- is untouched.

RESERVED WINDOW. The join reads the panel's winner/loser orientation as *history* to
validate a candidate; it computes no score. It is downstream of the panel build, the
declared outcome-access event.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    code_receipt,
    read_config,
    relative_to_root,
    resolve_under_root,
    sha256,
)
from tennislab.sources import profile_annual

DEFAULT_MARKET_DIR = "work/MULTI01_market_acquisition"
DEFAULT_ARCHIVE_PANEL_DIR = "work/MULTI01_archive_panel"
DEFAULT_SPAN = {"start": 2005, "end": 2024}
ORIGINAL_ADAPTER = "references/MULTI01_inputs/MULTI01_join/join_candidates.py"
TESTS_PATH = "references/MULTI01_inputs/MULTI01_join/test_join_candidates.py"

RECOVERED_2018 = "work/MULTI01_2018_recovery/2018.xlsx"
RECOVERED_2018_RECEIPT = "work/MULTI01_2018_recovery/2018.receipt.json"
RECOVERED_2018_SHA256 = "3e52c70872c87736110bfe22f682bd224bb5883bf5367a7f8997aab991c7162a"
CH01_EVENTS = "data/manifests/CH01/event_crosswalk_v2.json"
CH01_PLAYERS = "data/manifests/CH01/player_crosswalk.json"
CH01_LINEAGE = {
    2023: "data/curated/CH01/attempt_002/lineage_2023.csv",
    2024: "data/curated/CH01/attempt_002/lineage_2024.csv",
}
NORMAL_DATE_MIN = -2
NORMAL_DATE_MAX = 21
FIXED_ROUNDS = {"F": "The Final", "SF": "Semifinals", "QF": "Quarterfinals", "RR": "Round Robin"}
STATUS_MAP = {
    "Completed": "completed",
    "Retired": "retired",
    "Walkover": "walkover",
    "Awarded": "default",
    "Disqualified": "default",
}


@dataclass(frozen=True)
class JoinSettings:
    """The join's resolved inputs and its annual-summary span."""

    archive_panel_dir: Path
    market_dir: Path
    market_manifest: Path
    market_profile_adapter: Path
    span: dict[str, int]

    @property
    def source_panel(self) -> Path:
        return self.archive_panel_dir / "source_panel.csv"

    @property
    def source_quality(self) -> Path:
        return self.archive_panel_dir / "quality_report.json"

    def describe(self) -> dict[str, Any]:
        return {
            "archive_panel_dir": relative_to_root(self.archive_panel_dir),
            "market_dir": relative_to_root(self.market_dir),
            "market_manifest": relative_to_root(self.market_manifest),
            "market_profile_adapter": relative_to_root(self.market_profile_adapter),
            "span": dict(self.span),
        }


def configure(config: dict[str, Any] | None) -> JoinSettings:
    """Resolve the input paths and the annual-summary span from a config document.

    Keys, all optional, under a ``join`` object or at the top level:
    ``archive_panel_dir``, ``market_dir``, ``market_manifest``,
    ``market_profile_adapter``, plus ``year_plan`` (or an explicit
    ``panel_start_year``/``panel_end_year``) for the summary span. Anything omitted keeps
    MULTI01's own value, so an empty config reproduces MULTI01.
    """
    config = config or {}
    section = config.get("join", config)

    def _path(key: str, default: str | Path) -> Path:
        value = section.get(key)
        return resolve_under_root(default if value is None else value, label=f"join {key}")

    archive_panel_dir = _path("archive_panel_dir", DEFAULT_ARCHIVE_PANEL_DIR)
    market_dir = _path("market_dir", DEFAULT_MARKET_DIR)
    market_manifest = _path("market_manifest", market_dir / "acquisition_manifest.json")
    market_profile_adapter = _path(
        "market_profile_adapter", f"{DEFAULT_MARKET_DIR}/profile_annual.py"
    )
    plan = config.get("year_plan") or {}
    start = int(
        section.get("panel_start_year", plan.get("panel_start_year", DEFAULT_SPAN["start"]))
    )
    end = int(section.get("panel_end_year", plan.get("panel_end_year", DEFAULT_SPAN["end"])))
    if not 2000 <= start <= end <= 2100:
        raise ChainError(
            f"join summary span must satisfy 2000 <= start <= end <= 2100: {start}-{end}"
        )
    return JoinSettings(
        archive_panel_dir=archive_panel_dir,
        market_dir=market_dir,
        market_manifest=market_manifest,
        market_profile_adapter=market_profile_adapter,
        span={"start": start, "end": end},
    )


def source_date_anomaly_rule(market: dict[str, Any]) -> str | None:
    """Return a pinned, source-observed anomaly group; never alter the source date."""
    date = market["market_date"]
    if date is None:
        return None
    if (
        market["market_season"] == 2006
        and market["Tournament"] == "BNP Paribas"
        and date == dt.date(2005, 11, 5)
    ):
        return "2006_bnp_paribas_isolated_prior_year_cell"
    if (
        market["market_season"] == 2013
        and market["Tournament"] in {"China Open", "Rakuten Japan Open Tennis Championships"}
        and dt.date(2012, 10, 1) <= date <= dt.date(2012, 10, 7)
    ):
        return "2013_china_japan_prior_year_event_block"
    return None


def normalized(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return "".join(character for character in folded.casefold() if character.isalnum())


def name_words(value: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.findall(r"[A-Za-z0-9]+", folded.casefold())


def td_signature(value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(.+?)\s+((?:[A-Za-z]\.)+)", value.strip())
    if not match:
        return None
    surname = normalized(match.group(1))
    initials = "".join(re.findall(r"[A-Za-z]", match.group(2))).casefold()
    return (surname, initials) if surname and initials else None


def source_signatures(value: str) -> set[tuple[str, str]]:
    words = name_words(value)
    result = set()
    for split in range(1, len(words)):
        surname = "".join(words[split:])
        initials = "".join(word[0] for word in words[:split])
        if surname and initials:
            result.add((surname, initials))
    return result


def canonical_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def canonical_event_number(value: str) -> str:
    value = value.strip()
    try:
        number = float(value)
        if math.isfinite(number) and number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return value.casefold()


def parse_date(value: Any, kind: str, datemode: int | None) -> dt.date | None:
    parsed = profile_annual.date_value(value, kind, datemode)
    return parsed.date() if parsed is not None else None


def read_market_workbook(path: Path, year: int) -> tuple[list[str], list[dict[str, Any]]]:
    if path.suffix.casefold() == ".xlsx":
        workbook = profile_annual.openpyxl.load_workbook(path, read_only=True, data_only=False)
        sheet = workbook.worksheets[0]
        physical = []
        for excel_row in sheet.iter_rows():
            values = [cell.value for cell in excel_row]
            if not any(not profile_annual.blank(value) for value in values):
                continue
            if any(cell.data_type == "f" for cell in excel_row):
                raise ChainError(f"unqualified formula in {path} row {excel_row[0].row}")
            kinds = ["xlsx_date" if cell.is_date else str(cell.data_type) for cell in excel_row]
            physical.append((excel_row[0].row, values, kinds, None))
        workbook.close()
    elif path.suffix.casefold() == ".xls":
        xlrd = profile_annual.xlrd
        workbook = xlrd.open_workbook(path, on_demand=True)
        sheet = workbook.sheet_by_index(0)
        kind_names = {
            xlrd.XL_CELL_EMPTY: "empty",
            xlrd.XL_CELL_TEXT: "text",
            xlrd.XL_CELL_NUMBER: "number",
            xlrd.XL_CELL_DATE: "xls_date",
            xlrd.XL_CELL_BOOLEAN: "boolean",
            xlrd.XL_CELL_ERROR: "error",
            xlrd.XL_CELL_BLANK: "blank",
        }
        physical = []
        for row_index in range(sheet.nrows):
            cells = sheet.row(row_index)
            values = [cell.value for cell in cells]
            if not any(not profile_annual.blank(value) for value in values):
                continue
            kinds = [kind_names.get(cell.ctype, f"ctype_{cell.ctype}") for cell in cells]
            physical.append((row_index + 1, values, kinds, workbook.datemode))
        workbook.release_resources()
    else:
        raise ChainError(f"unsupported market workbook: {path}")
    if not physical:
        raise ChainError(f"empty workbook: {path}")
    headers = [canonical_cell(value) for value in physical[0][1]]
    while headers and not headers[-1]:
        headers.pop()
    if len(headers) != len(set(headers)):
        raise ChainError(f"duplicate workbook header: {path}")
    index = {name: position for position, name in enumerate(headers)}
    required = {
        "ATP",
        "Location",
        "Tournament",
        "Date",
        "Court",
        "Surface",
        "Round",
        "Best of",
        "Winner",
        "Loser",
        "Comment",
        "B365W",
        "B365L",
    }
    if not required.issubset(index):
        raise ChainError(
            f"missing required market columns in {path}: {sorted(required - index.keys())}"
        )
    rows = []
    for source_row, values, kinds, datemode in physical[1:]:
        values = values[: len(headers)] + [None] * max(0, len(headers) - len(values))
        kinds = kinds[: len(headers)] + ["empty"] * max(0, len(headers) - len(kinds))
        record = {name: canonical_cell(values[position]) for name, position in index.items()}
        record.update(
            market_season=year,
            market_source_path=relative_to_root(path),
            market_source_row=source_row,
            market_date=parse_date(values[index["Date"]], kinds[index["Date"]], datemode),
        )
        rows.append(record)
    return headers, rows


def round_agrees(archive: dict[str, str], market_round: str) -> bool:
    archive_round = archive["round"]
    if archive_round in FIXED_ROUNDS:
        return market_round == FIXED_ROUNDS[archive_round]
    if not re.fullmatch(r"R\d+", archive_round) or not archive["draw_size"].isdigit():
        return False
    draw_size = int(archive["draw_size"])
    current = int(archive_round[1:])
    top = 1 << (draw_size - 1).bit_length()
    index = (top // current).bit_length()
    return market_round == {1: "1st Round", 2: "2nd Round", 3: "3rd Round", 4: "4th Round"}.get(
        index
    )


def archive_event_number(row: dict[str, str]) -> str:
    suffix = row["tourney_id"].split("-", 1)[-1]
    return canonical_event_number(suffix) if suffix.isdigit() else suffix.casefold()


def event_evidence(
    archive: dict[str, str], market: dict[str, Any], pinned_event: str | None
) -> tuple[str, bool]:
    if pinned_event is not None and archive["tourney_id"] == pinned_event:
        return "pinned_ch01_event", True
    if archive_event_number(archive) == canonical_event_number(market["ATP"]):
        return "event_code_exact", True
    if normalized(archive["tourney_name"]) == normalized(market["Tournament"]):
        return "event_name_exact_normalized", True
    archive_name = normalized(archive["tourney_name"])
    market_name = normalized(market["Tournament"])
    if len(archive_name) >= 5 and (archive_name in market_name or market_name in archive_name):
        return "event_name_containment", False
    return "event_unmapped", False


def market_sets(row: dict[str, Any]) -> list[tuple[int, int]] | None:
    result = []
    for index in range(1, 6):
        left = row.get(f"W{index}", "")
        right = row.get(f"L{index}", "")
        if left == "" and right == "":
            continue
        try:
            left_number = float(left)
            right_number = float(right)
        except ValueError:
            return None
        if not left_number.is_integer() or not right_number.is_integer():
            return None
        result.append((int(left_number), int(right_number)))
    return result


def archive_sets(score: str) -> list[tuple[int, int]]:
    return [tuple(map(int, pair)) for pair in re.findall(r"(\d+)-(\d+)(?:\(\d+\))?", score)]


def decimal_pair_quality(winner: str, loser: str, present: bool) -> str:
    if not present:
        return "fields_absent"
    if winner == "" and loser == "":
        return "both_missing"
    if (winner == "") != (loser == ""):
        return "one_sided_missing"
    try:
        values = [float(winner), float(loser)]
    except ValueError:
        return "nonnumeric"
    if not all(math.isfinite(value) for value in values):
        return "nonfinite"
    return "valid_decimal_gt_1" if all(value > 1 for value in values) else "numeric_not_gt_1"


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def load_inputs(
    settings: JoinSettings,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], dict[str, Any]]:
    source_panel = settings.source_panel
    source_quality = settings.source_quality
    quality = json.loads(source_quality.read_text())
    expected_panel_hash = quality["output_sha256"]["source_panel.csv"]
    if sha256(source_panel) != expected_panel_hash:
        raise ChainError("archive source panel hash mismatch")
    with source_panel.open(encoding="utf-8", newline="") as handle:
        archive_rows = list(csv.DictReader(handle))
    if len(archive_rows) != quality["panel_rows"]:
        raise ChainError("archive source panel row count mismatch")
    if len({row["source_key"] for row in archive_rows}) != len(archive_rows):
        raise ChainError("archive source keys are not unique")

    manifest = json.loads(settings.market_manifest.read_text())
    retained = {int(row["year"]): row for row in manifest["records"] if row.get("retained_path")}
    market_rows = []
    market_headers = {}
    market_files = {}
    for year in sorted(retained):
        record = retained[year]
        path = settings.market_dir / record["retained_path"]
        if sha256(path) != record["retained_sha256"]:
            raise ChainError(f"market source hash mismatch: {year}")
        headers, rows = read_market_workbook(path, year)
        market_headers[str(year)] = headers
        market_files[str(year)] = {
            "path": relative_to_root(path),
            "sha256": record["retained_sha256"],
            "capture_timestamp": record.get("capture_timestamp", ""),
            "acquisition_route": record.get("acquisition_route", ""),
        }
        for row in rows:
            row["market_source_sha256"] = record["retained_sha256"]
            row["capture_timestamp"] = record.get("capture_timestamp", "")
        market_rows.extend(rows)

    recovered = resolve_under_root(RECOVERED_2018, label="recovered_2018")
    recovered_receipt_path = resolve_under_root(RECOVERED_2018_RECEIPT, label="recovered_2018")
    if not recovered.exists() or not recovered_receipt_path.exists():
        raise ChainError("pinned recovered 2018 workbook or receipt is missing")
    recovered_receipt = json.loads(recovered_receipt_path.read_text())
    if (
        sha256(recovered) != RECOVERED_2018_SHA256
        or recovered_receipt.get("sha256") != RECOVERED_2018_SHA256
    ):
        raise ChainError("recovered 2018 workbook hash mismatch")
    headers, rows = read_market_workbook(recovered, 2018)
    market_headers["2018"] = headers
    market_files["2018"] = {
        "path": relative_to_root(recovered),
        "sha256": RECOVERED_2018_SHA256,
        "receipt_path": relative_to_root(recovered_receipt_path),
        "receipt_sha256": sha256(recovered_receipt_path),
        "capture_timestamp": recovered_receipt.get("received_at_utc", ""),
        "acquisition_route": "pinned_third_party_git_copy",
        "source_class": recovered_receipt.get("source_class", ""),
        "original_capture_timestamp": "unknown",
    }
    for row in rows:
        row["market_source_sha256"] = RECOVERED_2018_SHA256
        row["capture_timestamp"] = recovered_receipt.get("received_at_utc", "")
    market_rows.extend(rows)
    market_rows.sort(
        key=lambda row: (row["market_season"], row["market_source_path"], row["market_source_row"])
    )
    metadata = {
        "archive_source_panel": {
            "path": relative_to_root(source_panel),
            "sha256": expected_panel_hash,
        },
        "archive_quality_report": {
            "path": relative_to_root(source_quality),
            "sha256": sha256(source_quality),
        },
        "market_manifest": {
            "path": relative_to_root(settings.market_manifest),
            "sha256": sha256(settings.market_manifest),
        },
        "market_profile_adapter": {
            "path": relative_to_root(settings.market_profile_adapter),
            "sha256": sha256(settings.market_profile_adapter),
        },
        "market_files": market_files,
        "market_headers": market_headers,
    }
    return archive_rows, market_rows, metadata


def build_alias_indexes(
    archive_rows: list[dict[str, str]],
) -> tuple[dict[int, dict[tuple[str, str], set[int]]], dict[int, dict[str, set[int]]]]:
    signatures: dict[int, dict[tuple[str, str], set[int]]] = defaultdict(lambda: defaultdict(set))
    exact_names: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for row in archive_rows:
        season = int(row["season"])
        for side in ("a", "b"):
            if row[f"{side}_identity_metadata_status"] == "quarantined_wrong_source_identity":
                continue
            player_id = int(row[f"{side}_entity_id"])
            source_name = row[f"{side}_source_name"]
            exact_names[season][normalized(source_name)].add(player_id)
            for signature in source_signatures(source_name):
                signatures[season][signature].add(player_id)
    return signatures, exact_names


def resolve_alias(
    season: int,
    td_name: str,
    pinned_players: dict[tuple[int, str], int],
    signatures: dict[int, dict[tuple[str, str], set[int]]],
    exact_names: dict[int, dict[str, set[int]]],
) -> dict[str, Any]:
    pinned = pinned_players.get((season, td_name))
    if pinned is not None:
        return {"ids": {pinned}, "basis": "pinned_ch01_alias", "signature": ""}
    exact = exact_names[season].get(normalized(td_name), set())
    if exact:
        return {
            "ids": set(exact),
            "basis": "source_name_exact_unique"
            if len(exact) == 1
            else "source_name_exact_ambiguous",
            "signature": normalized(td_name),
        }
    signature = td_signature(td_name)
    if signature is None:
        return {"ids": set(), "basis": "unparsed_name", "signature": ""}
    candidates = signatures[season].get(signature, set())
    return {
        "ids": set(candidates),
        "basis": "initial_surname_unique"
        if len(candidates) == 1
        else "initial_surname_ambiguous"
        if candidates
        else "initial_surname_unmatched",
        "signature": "/".join(signature),
    }


def candidate_record(
    archive: dict[str, str], market: dict[str, Any], evidence: str, strong_event: bool
) -> dict[str, Any]:
    anchor = dt.date.fromisoformat(archive["tourney_anchor_date"])
    market_date = market["market_date"]
    delta = (market_date - anchor).days if market_date is not None else None
    return {
        "archive": archive,
        "event_evidence": evidence,
        "event_strong": strong_event,
        "round_agreement": round_agrees(archive, market["Round"]),
        "date_delta_days": delta,
        "date_window_agreement": delta is not None and NORMAL_DATE_MIN <= delta <= NORMAL_DATE_MAX,
    }


def classify_market_row(
    market: dict[str, Any],
    archive_pair_index: dict[tuple[int, tuple[int, int]], list[dict[str, str]]],
    winner_alias: dict[str, Any],
    loser_alias: dict[str, Any],
    pinned_event_id: str | None,
) -> dict[str, Any]:
    pair_rows: dict[str, dict[str, str]] = {}
    for winner_id, loser_id in product(winner_alias["ids"], loser_alias["ids"]):
        if winner_id == loser_id:
            continue
        pair = tuple(sorted((winner_id, loser_id)))
        for row in archive_pair_index.get((market["market_season"], pair), []):
            pair_rows[row["source_key"]] = row
    candidates = []
    for row in pair_rows.values():
        evidence, strong = event_evidence(row, market, pinned_event_id)
        candidates.append(candidate_record(row, market, evidence, strong))
    strong = [
        row
        for row in candidates
        if row["event_strong"] and row["round_agreement"] and row["date_window_agreement"]
    ]
    weak = [row for row in candidates if row["round_agreement"] and row["date_window_agreement"]]
    date_only = [
        row
        for row in candidates
        if row["event_strong"] and row["round_agreement"] and not row["date_window_agreement"]
    ]
    selected = None
    if len(strong) == 1:
        selected = strong[0]
        both_pinned = winner_alias["basis"] == loser_alias["basis"] == "pinned_ch01_alias"
        both_unique = len(winner_alias["ids"]) == len(loser_alias["ids"]) == 1
        if both_pinned and selected["event_evidence"] == "pinned_ch01_event":
            classification = "candidate_q1_pinned_ch01"
        elif both_unique:
            classification = "candidate_q2_unique_alias_event"
        else:
            classification = "candidate_q3_context_disambiguated"
        pool = strong
    elif len(strong) > 1:
        classification = "ambiguous_multiple_strong"
        pool = strong
    elif len(weak) == 1:
        selected = weak[0]
        classification = "candidate_q4_unique_pair_round_date_event_unmapped"
        pool = weak
    elif len(weak) > 1:
        classification = "ambiguous_multiple_weak"
        pool = weak
    elif len(date_only) == 1:
        selected = date_only[0]
        classification = "date_correction_candidate"
        pool = date_only
    elif len(date_only) > 1:
        classification = "ambiguous_multiple_date_corrections"
        pool = date_only
    elif not winner_alias["ids"] or not loser_alias["ids"]:
        classification = "unmatched_player_alias"
        pool = []
    elif not candidates:
        classification = "unmatched_pair"
        pool = []
    else:
        classification = "unmatched_event_round_or_date"
        pool = candidates
    return {
        "market": market,
        "winner_alias": winner_alias,
        "loser_alias": loser_alias,
        "classification": classification,
        "selected": selected,
        "candidate_pool": pool,
        "all_candidates": candidates,
    }


def validate_selected(result: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    market = result["market"]
    selected = result["selected"]
    if selected is None:
        raise ChainError("validate_selected called without a selected candidate")
    archive = selected["archive"]
    a = int(archive["a_entity_id"])
    b = int(archive["b_entity_id"])
    # outcome-history read: the panel's orientation validates a candidate; nothing is scored.
    archive_winner = a if archive["a_won"] == "true" else b
    archive_loser = b if archive["a_won"] == "true" else a
    winner_ids = result["winner_alias"]["ids"]
    loser_ids = result["loser_alias"]["ids"]
    if archive_winner in winner_ids and archive_loser in loser_ids:
        winner_agreement = "agree"
    elif archive_loser in winner_ids and archive_winner in loser_ids:
        winner_agreement = "disagree"
    else:
        winner_agreement = "ambiguous_alias_sets"
    market_score = market_sets(market)
    source_score = archive_sets(archive["score"])
    score_agreement = (
        "unparsed_market_score"
        if market_score is None
        else "agree"
        if winner_agreement == "agree" and market_score == source_score
        else "disagree"
        if winner_agreement == "agree"
        else "not_comparable_winner_orientation"
    )
    surface_agreement = "agree" if market["Surface"] == archive["surface"] else "disagree"
    best_of_agreement = "agree" if market["Best of"] == archive["best_of"] else "disagree"
    mapped_status = STATUS_MAP.get(market["Comment"])
    status_agreement = (
        "unmapped_market_status"
        if mapped_status is None
        else "agree"
        if mapped_status == archive["status"]
        else "disagree"
    )
    validation = {
        "winner_agreement": winner_agreement,
        "score_agreement": score_agreement,
        "surface_agreement": surface_agreement,
        "best_of_agreement": best_of_agreement,
        "status_agreement": status_agreement,
    }
    conflicts = []
    for field, status in validation.items():
        if status == "agree":
            continue
        conflicts.append(
            {
                "market_season": market["market_season"],
                "market_source_path": market["market_source_path"],
                "market_source_row": market["market_source_row"],
                "archive_source_key": archive["source_key"],
                "quality_tier": result["classification"],
                "field": field.removesuffix("_agreement"),
                "status": status,
                "market_value": {
                    "winner": market["Winner"],
                    "score": json.dumps(market_score),
                    "surface": market["Surface"],
                    "best_of": market["Best of"],
                    "status": market["Comment"],
                }[field.removesuffix("_agreement")],
                "archive_value": {
                    "winner": str(archive_winner),
                    "score": archive["score"],
                    "surface": archive["surface"],
                    "best_of": archive["best_of"],
                    "status": archive["status"],
                }[field.removesuffix("_agreement")],
            }
        )
    return validation, conflicts


def flattened_candidate(
    result: dict[str, Any], validation: dict[str, Any] | None = None
) -> dict[str, Any]:
    market = result["market"]
    selected = result["selected"]
    archive = selected["archive"] if selected is not None else None
    out = {
        "market_season": market["market_season"],
        "market_source_path": market["market_source_path"],
        "market_source_sha256": market["market_source_sha256"],
        "market_source_row": market["market_source_row"],
        "market_capture_timestamp": market["capture_timestamp"],
        "market_match_date": market["market_date"].isoformat() if market["market_date"] else "",
        "market_event_number": market["ATP"],
        "market_location": market["Location"],
        "market_tournament": market["Tournament"],
        "market_round": market["Round"],
        "market_comment": market["Comment"],
        "market_court": market["Court"],
        "market_surface": market["Surface"],
        "market_best_of": market["Best of"],
        "market_winner_name": market["Winner"],
        "market_loser_name": market["Loser"],
        "winner_alias_basis": result["winner_alias"]["basis"],
        "winner_alias_candidates": ";".join(map(str, sorted(result["winner_alias"]["ids"]))),
        "loser_alias_basis": result["loser_alias"]["basis"],
        "loser_alias_candidates": ";".join(map(str, sorted(result["loser_alias"]["ids"]))),
        "PSW": market.get("PSW", ""),
        "PSL": market.get("PSL", ""),
        "PS_pair_quality": decimal_pair_quality(
            market.get("PSW", ""), market.get("PSL", ""), "PSW" in market and "PSL" in market
        ),
        "B365W": market.get("B365W", ""),
        "B365L": market.get("B365L", ""),
        "B365_pair_quality": decimal_pair_quality(
            market.get("B365W", ""), market.get("B365L", ""), True
        ),
        "classification": result["classification"],
        "candidate_count": len(result["candidate_pool"]),
        "candidate_source_keys": ";".join(
            sorted(item["archive"]["source_key"] for item in result["candidate_pool"])
        ),
    }
    if archive is not None:
        out.update(
            archive_source_key=archive["source_key"],
            archive_source_member=archive["source_member"],
            archive_source_file_sha256=archive["source_file_sha256"],
            archive_source_line_number=archive["source_line_number"],
            archive_tourney_id=archive["tourney_id"],
            archive_tourney_name=archive["tourney_name"],
            archive_competition_type=archive["competition_type"],
            archive_population_basis=archive["population_basis"],
            archive_tourney_anchor_date=archive["tourney_anchor_date"],
            archive_date_basis=archive["date_basis"],
            match_date_minus_anchor_days=selected["date_delta_days"],
            event_evidence=selected["event_evidence"],
            round_agreement=str(selected["round_agreement"]).lower(),
            date_window_agreement=str(selected["date_window_agreement"]).lower(),
            archive_round=archive["round"],
            archive_surface=archive["surface"],
            archive_best_of=archive["best_of"],
            archive_status=archive["status"],
            archive_played=archive["played"],
            archive_completed=archive["completed"],
            archive_retired=archive["retired"],
            archive_walkover=archive["walkover"],
            archive_defaulted=archive["defaulted"],
            archive_abandoned=archive["abandoned"],
            player_a=archive["a_entity_id"],
            player_b=archive["b_entity_id"],
            archive_a_source_id=archive["a_source_id"],
            archive_a_source_name=archive["a_source_name"],
            archive_a_identity_correction=archive["a_identity_correction"],
            archive_a_identity_metadata_status=archive["a_identity_metadata_status"],
            archive_b_source_id=archive["b_source_id"],
            archive_b_source_name=archive["b_source_name"],
            archive_b_identity_correction=archive["b_identity_correction"],
            archive_b_identity_metadata_status=archive["b_identity_metadata_status"],
            a_won=archive["a_won"],
            archive_score=archive["score"],
        )
    if validation:
        out.update(validation)
    return out


def build_date_correction_candidates(
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int]]:
    """Describe source-date corrections as candidates, without changing join acceptance."""
    grouped: dict[tuple[str, int, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        market = result["market"]
        rule = source_date_anomaly_rule(market)
        if rule is not None:
            key = (
                rule,
                market["market_season"],
                canonical_event_number(market["ATP"]),
                market["Tournament"],
                market["Location"],
            )
            grouped[key].append(result)

    output: list[dict[str, Any]] = []
    anomaly_result_ids: set[int] = set()
    for group_key, group in sorted(grouped.items()):
        rule, season, _, tournament, _ = group_key
        round_candidates = {
            id(result): [
                candidate
                for candidate in result["all_candidates"]
                if candidate["round_agreement"] and not candidate["date_window_agreement"]
            ]
            for result in group
        }
        event_counts = Counter(
            candidate["archive"]["tourney_id"]
            for result in group
            for candidate in round_candidates[id(result)]
        )
        dominant_event = ""
        dominant_support = 0
        if len(group) >= 10 and event_counts:
            ranking = event_counts.most_common()
            top_event, top_count = ranking[0]
            tied = len(ranking) > 1 and ranking[1][1] == top_count
            if not tied and top_count / len(group) >= 0.8:
                dominant_event = top_event
                dominant_support = top_count

        for result in group:
            anomaly_result_ids.add(id(result))
            market = result["market"]
            candidates = round_candidates[id(result)]
            cohort_candidates = [
                candidate
                for candidate in candidates
                if candidate["archive"]["tourney_id"] == dominant_event
            ]
            if dominant_event and cohort_candidates:
                candidates_to_emit = cohort_candidates
                candidate_basis = "event_block_dominant_tourney_plus_pair_round"
            elif len(candidates) == 1:
                candidates_to_emit = candidates
                candidate_basis = "unique_pair_round_outside_date_window"
            else:
                candidates_to_emit = candidates or [None]
                candidate_basis = (
                    "ambiguous_pair_round_candidates"
                    if candidates
                    else "no_resolved_pair_round_candidate"
                )

            proposed_date = None
            if market["market_date"] is not None:
                try:
                    proposed_date = market["market_date"].replace(year=season)
                except ValueError:
                    proposed_date = None
            for rank, candidate in enumerate(candidates_to_emit, start=1):
                copy = dict(result)
                copy["classification"] = "source_date_anomaly_candidate"
                copy["selected"] = candidate
                copy["candidate_pool"] = [item for item in candidates if item is not None]
                validation = validate_selected(copy)[0] if candidate is not None else None
                row = flattened_candidate(copy, validation)
                candidate_window_start = ""
                candidate_window_end = ""
                proposed_delta = ""
                proposed_in_window = ""
                if candidate is not None:
                    anchor = dt.date.fromisoformat(candidate["archive"]["tourney_anchor_date"])
                    candidate_window_start = (
                        anchor + dt.timedelta(days=NORMAL_DATE_MIN)
                    ).isoformat()
                    candidate_window_end = (anchor + dt.timedelta(days=NORMAL_DATE_MAX)).isoformat()
                    if proposed_date is not None:
                        proposed_delta = (proposed_date - anchor).days
                        proposed_in_window = str(
                            NORMAL_DATE_MIN <= proposed_delta <= NORMAL_DATE_MAX
                        ).lower()
                row.update(
                    source_date_anomaly_rule=rule,
                    source_date_anomaly_group_rows=len(group),
                    market_event_group=tournament,
                    dominant_archive_event_candidate=dominant_event,
                    dominant_event_candidate_support=dominant_support,
                    dominant_event_candidate_share=round(dominant_support / len(group), 8)
                    if dominant_event
                    else "",
                    correction_candidate_basis=candidate_basis,
                    correction_candidate_rank=rank,
                    correction_candidate_records=len(candidates_to_emit),
                    candidate_window_start=candidate_window_start,
                    candidate_window_end=candidate_window_end,
                    proposed_year_relabel_date=proposed_date.isoformat() if proposed_date else "",
                    proposed_date_minus_anchor_days=proposed_delta,
                    proposed_date_in_candidate_window=proposed_in_window,
                    correction_status="evidence_candidate_only_source_date_unchanged",
                )
                output.append(row)
    return output, anomaly_result_ids


def build(output_dir: Path, settings: JoinSettings) -> dict[str, Any]:
    # An *empty* pre-created directory is allowed: the chain driver creates the stage
    # directory before launching the stage. A nonempty one still fails closed.
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_rows, market_rows, inputs = load_inputs(settings)
    ch01_players = resolve_under_root(CH01_PLAYERS, label="ch01_players")
    ch01_events = resolve_under_root(CH01_EVENTS, label="ch01_events")
    ch01_lineage = {
        year: resolve_under_root(path, label="ch01_lineage") for year, path in CH01_LINEAGE.items()
    }
    pinned_player_rows = json.loads(ch01_players.read_text())
    pinned_players = {
        (int(row["season"]), row["td_name"]): int(row["canonical_player_id"])
        for row in pinned_player_rows
    }
    if len(pinned_players) != len(pinned_player_rows):
        raise ChainError("duplicate CH01 player aliases")
    pinned_event_rows = json.loads(ch01_events.read_text())
    pinned_events = {
        (
            int(row["season"]),
            canonical_event_number(row["td_event_number"]),
            row["td_tournament"],
            row["td_location"],
        ): row["archive_tourney_id"]
        for row in pinned_event_rows
    }
    if len(pinned_events) != len(pinned_event_rows):
        raise ChainError("duplicate CH01 event mapping")
    inputs["ch01_player_aliases"] = {
        "path": relative_to_root(ch01_players),
        "sha256": sha256(ch01_players),
    }
    inputs["ch01_event_crosswalk"] = {
        "path": relative_to_root(ch01_events),
        "sha256": sha256(ch01_events),
    }
    inputs["ch01_lineage"] = {
        str(year): {"path": relative_to_root(path), "sha256": sha256(path)}
        for year, path in ch01_lineage.items()
    }

    signatures, exact_names = build_alias_indexes(archive_rows)
    archive_pair_index: dict[tuple[int, tuple[int, int]], list[dict[str, str]]] = defaultdict(list)
    for row in archive_rows:
        pair = tuple(sorted((int(row["a_entity_id"]), int(row["b_entity_id"]))))
        archive_pair_index[(int(row["season"]), pair)].append(row)

    alias_records: dict[tuple[int, str], dict[str, Any]] = {}
    results = []
    for market in market_rows:
        season = market["market_season"]
        winner_alias = resolve_alias(
            season, market["Winner"], pinned_players, signatures, exact_names
        )
        loser_alias = resolve_alias(
            season, market["Loser"], pinned_players, signatures, exact_names
        )
        for name, alias in ((market["Winner"], winner_alias), (market["Loser"], loser_alias)):
            key = (season, name)
            alias_records[key] = {
                "season": season,
                "td_name": name,
                "basis": alias["basis"],
                "signature": alias["signature"],
                "candidate_count": len(alias["ids"]),
                "candidate_entity_ids": ";".join(map(str, sorted(alias["ids"]))),
            }
        pinned_event = pinned_events.get(
            (
                season,
                canonical_event_number(market["ATP"]),
                market["Tournament"],
                market["Location"],
            )
        )
        results.append(
            classify_market_row(market, archive_pair_index, winner_alias, loser_alias, pinned_event)
        )

    accepted_prefix = "candidate_q"
    reuse: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        if result["classification"].startswith(accepted_prefix) and result["selected"] is not None:
            reuse[result["selected"]["archive"]["source_key"]].append(result)
    for _source_key, repeated in reuse.items():
        if len(repeated) > 1:
            for result in repeated:
                result["classification"] = "ambiguous_archive_row_reused"
                result["candidate_pool"] = [result["selected"]]
                result["selected"] = None

    common = []
    conflicts = []
    candidate_rows = []
    ambiguous_rows = []
    unmatched_rows = []
    matched_archive_keys = set()
    market_event_dates: dict[tuple[int, str, str, str], list[dt.date]] = defaultdict(list)
    for market in market_rows:
        if market["market_date"] is not None:
            market_event_dates[
                (
                    market["market_season"],
                    canonical_event_number(market["ATP"]),
                    market["Tournament"],
                    market["Location"],
                )
            ].append(market["market_date"])

    correction_rows, pinned_anomaly_result_ids = build_date_correction_candidates(results)

    for result in results:
        candidate_rows.append(flattened_candidate(result))
        classification = result["classification"]
        if classification.startswith(accepted_prefix):
            validation, row_conflicts = validate_selected(result)
            row = flattened_candidate(result, validation)
            common.append(row)
            conflicts.extend(row_conflicts)
            matched_archive_keys.add(result["selected"]["archive"]["source_key"])
        elif (
            classification == "date_correction_candidate"
            and id(result) not in pinned_anomaly_result_ids
        ):
            selected = result["selected"]
            if selected is None:
                raise ChainError("date correction candidate without a selected row")
            archive = selected["archive"]
            market = result["market"]
            anchor = dt.date.fromisoformat(archive["tourney_anchor_date"])
            peer_dates = market_event_dates[
                (
                    market["market_season"],
                    canonical_event_number(market["ATP"]),
                    market["Tournament"],
                    market["Location"],
                )
            ]
            correction_rows.append(
                {
                    **flattened_candidate(result),
                    "candidate_window_start": (
                        anchor + dt.timedelta(days=NORMAL_DATE_MIN)
                    ).isoformat(),
                    "candidate_window_end": (
                        anchor + dt.timedelta(days=NORMAL_DATE_MAX)
                    ).isoformat(),
                    "same_market_event_observed_date_min": min(peer_dates).isoformat()
                    if peer_dates
                    else "",
                    "same_market_event_observed_date_max": max(peer_dates).isoformat()
                    if peer_dates
                    else "",
                    "correction_status": "evidence_candidate_only_no_exact_date_assigned",
                }
            )
        elif classification.startswith("ambiguous"):
            if result["candidate_pool"]:
                for candidate in result["candidate_pool"]:
                    copy = dict(result)
                    copy["selected"] = candidate
                    ambiguous_rows.append(flattened_candidate(copy))
            else:
                ambiguous_rows.append(flattened_candidate(result))
        else:
            unmatched_rows.append(flattened_candidate(result))

    unmatched_archive = []
    for row in archive_rows:
        if row["source_key"] in matched_archive_keys:
            continue
        unmatched_archive.append(
            {
                "season": row["season"],
                "archive_source_key": row["source_key"],
                "archive_source_member": row["source_member"],
                "archive_source_line_number": row["source_line_number"],
                "tourney_id": row["tourney_id"],
                "tourney_name": row["tourney_name"],
                "competition_type": row["competition_type"],
                "tourney_anchor_date": row["tourney_anchor_date"],
                "round": row["round"],
                "surface": row["surface"],
                "best_of": row["best_of"],
                "status": row["status"],
                "played": row["played"],
                "player_a": row["a_entity_id"],
                "player_b": row["b_entity_id"],
                "reason": "no_unique_q1_q4_market_candidate",
            }
        )

    common_fields = list(common[0]) if common else list(candidate_rows[0])
    candidate_fields = list(candidate_rows[0])
    correction_fields: list[str] = []
    for row in correction_rows:
        for field in row:
            if field not in correction_fields:
                correction_fields.append(field)
    if not correction_fields:
        correction_fields = candidate_fields + [
            "candidate_window_start",
            "candidate_window_end",
            "correction_status",
        ]
    write_csv(output_dir / "common_panel_candidates.csv", common, common_fields)
    write_csv(output_dir / "market_row_candidates.csv", candidate_rows, candidate_fields)
    write_csv(output_dir / "ambiguous_candidates.csv", ambiguous_rows, candidate_fields)
    write_csv(output_dir / "unmatched_market_rows.csv", unmatched_rows, candidate_fields)
    write_csv(
        output_dir / "unmatched_archive_rows.csv", unmatched_archive, list(unmatched_archive[0])
    )
    write_csv(output_dir / "date_correction_candidates.csv", correction_rows, correction_fields)
    write_csv(
        output_dir / "conflict_locators.csv",
        conflicts,
        [
            "market_season",
            "market_source_path",
            "market_source_row",
            "archive_source_key",
            "quality_tier",
            "field",
            "status",
            "market_value",
            "archive_value",
        ],
    )
    alias_rows = sorted(alias_records.values(), key=lambda row: (row["season"], row["td_name"]))
    write_csv(output_dir / "alias_candidates.csv", alias_rows, list(alias_rows[0]))

    by_year = []
    all_years = range(settings.span["start"], settings.span["end"] + 1)
    for year in all_years:
        source = [row for row in archive_rows if int(row["season"]) == year]
        market = [row for row in results if row["market"]["market_season"] == year]
        accepted = [row for row in market if row["classification"].startswith(accepted_prefix)]
        common_year = [row for row in common if int(row["market_season"]) == year]
        counts = Counter(row["classification"] for row in market)
        by_year.append(
            {
                "season": year,
                "market_acquisition_status": "pinned_third_party_copy_original_capture_time_unknown"
                if year == 2018
                else "retained_original_acquisition",
                "market_rows": len(market),
                "archive_scope_rows": len(source),
                "unique_q1_q4_candidates": len(accepted),
                "q1_q4_coverage_of_market": round(len(accepted) / len(market), 8) if market else "",
                "q1_q4_coverage_of_archive": round(len(accepted) / len(source), 8)
                if source
                else "",
                "q1_pinned": counts["candidate_q1_pinned_ch01"],
                "q2_unique_alias_event": counts["candidate_q2_unique_alias_event"],
                "q3_context_disambiguated": counts["candidate_q3_context_disambiguated"],
                "q4_event_unmapped": counts["candidate_q4_unique_pair_round_date_event_unmapped"],
                "date_correction_candidates": sum(
                    source_date_anomaly_rule(row["market"]) is not None
                    or row["classification"] == "date_correction_candidate"
                    for row in market
                ),
                "ambiguous": sum(
                    value for key, value in counts.items() if key.startswith("ambiguous")
                ),
                "unmatched": sum(
                    value for key, value in counts.items() if key.startswith("unmatched")
                ),
                "winner_conflicts": sum(row["winner_agreement"] != "agree" for row in common_year),
                "score_conflicts_or_unparsed": sum(
                    row["score_agreement"] != "agree" for row in common_year
                ),
                "surface_conflicts": sum(
                    row["surface_agreement"] != "agree" for row in common_year
                ),
                "best_of_conflicts": sum(
                    row["best_of_agreement"] != "agree" for row in common_year
                ),
                "status_conflicts_or_unmapped": sum(
                    row["status_agreement"] != "agree" for row in common_year
                ),
                "ps_valid_pairs": sum(
                    row["PS_pair_quality"] == "valid_decimal_gt_1" for row in common_year
                ),
                "b365_valid_pairs": sum(
                    row["B365_pair_quality"] == "valid_decimal_gt_1" for row in common_year
                ),
            }
        )
    write_csv(output_dir / "coverage_by_year.csv", by_year, list(by_year[0]))

    ours = {
        (int(row["market_season"]), int(row["market_source_row"])): row["archive_source_key"]
        for row in common
    }
    archive_key_set = {row["source_key"] for row in archive_rows}
    ch01_report = {}
    for year, path in ch01_lineage.items():
        with path.open(encoding="utf-8", newline="") as handle:
            known = [row for row in csv.DictReader(handle) if row["match_id"] in archive_key_set]
        exact = 0
        missing = []
        disagreements = []
        for row in known:
            key = (year, int(row["td_source_row"]))
            observed = ours.get(key)
            if observed is None:
                missing.append(
                    {
                        "td_source_row": int(row["td_source_row"]),
                        "expected_match_id": row["match_id"],
                    }
                )
            elif observed == row["match_id"]:
                exact += 1
            else:
                disagreements.append(
                    {
                        "td_source_row": int(row["td_source_row"]),
                        "expected_match_id": row["match_id"],
                        "observed_match_id": observed,
                    }
                )
        ch01_report[str(year)] = {
            "known_lineage_rows_in_new_archive_scope": len(known),
            "exact_join_matches": exact,
            "missing_candidate_rows": len(missing),
            "disagreements": disagreements,
            "missing_examples": missing[:20],
        }
        if exact != len(known) or missing or disagreements:
            raise ChainError(f"join candidates disagree with pinned CH01 lineage for {year}")
    (output_dir / "ch01_validation.json").write_text(
        json.dumps(ch01_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    output_names = [
        "common_panel_candidates.csv",
        "market_row_candidates.csv",
        "ambiguous_candidates.csv",
        "unmatched_market_rows.csv",
        "unmatched_archive_rows.csv",
        "date_correction_candidates.csv",
        "conflict_locators.csv",
        "alias_candidates.csv",
        "coverage_by_year.csv",
        "ch01_validation.json",
    ]
    original_adapter = resolve_under_root(ORIGINAL_ADAPTER, label="original_adapter")
    tests_path = resolve_under_root(TESTS_PATH, label="tests")
    report = {
        "scope": "Dated market/archive join candidates only; no final population, price cutoff, model fit, or identity correction.",
        "date_window_days": [NORMAL_DATE_MIN, NORMAL_DATE_MAX],
        "quality_tiers": {
            "candidate_q1_pinned_ch01": "CH01-pinned player aliases and event crosswalk; unique pair/event/round/date candidate",
            "candidate_q2_unique_alias_event": "unique mechanical source-name aliases plus strong event, round and date evidence",
            "candidate_q3_context_disambiguated": "ambiguous individual alias narrowed by unordered pair plus strong event, round and date evidence",
            "candidate_q4_unique_pair_round_date_event_unmapped": "unique unordered pair/round/date candidate without strong event mapping; review before use",
            "date_correction_candidate": "unique pair/event/round candidate outside date window; evidence candidate only, no corrected date assigned",
            "source_date_anomaly_candidate": "pinned 2006/2013 source-date defect; year-relabel date and archive event window emitted only as correction evidence",
        },
        "inputs": inputs,
        "implementation": {
            # The code that ran is this package module; the archive's parent adapter and
            # the covering test file stay declared bindings, resolved and hashed here.
            "adapter": code_receipt(__name__),
            "tests": {"path": relative_to_root(tests_path), "sha256": sha256(tests_path)},
            "original_adapter": {
                "path": relative_to_root(original_adapter),
                "sha256": sha256(original_adapter),
            },
        },
        "source_date_anomaly_rules": {
            "2006_bnp_paribas_isolated_prior_year_cell": "season 2006, BNP Paribas, source date 2005-11-05",
            "2013_china_japan_prior_year_event_block": "season 2013, China Open or Rakuten Japan Open, source dates 2012-10-01 through 2012-10-07",
            "proposed_transform": "replace only the source-date year with the explicit source season, retain month/day, and emit as an unapplied candidate",
        },
        "counts": {
            "archive_scope_rows": len(archive_rows),
            "market_rows": len(market_rows),
            "common_panel_candidates": len(common),
            "ambiguous_market_rows": sum(
                row["classification"].startswith("ambiguous") for row in results
            ),
            "unmatched_market_rows": sum(
                row["classification"].startswith("unmatched") for row in results
            ),
            "date_correction_candidates": len(correction_rows),
            "source_date_anomaly_market_rows": len(pinned_anomaly_result_ids),
            "unmatched_archive_rows": len(unmatched_archive),
            "validation_conflict_locators": len(conflicts),
        },
        "ch01_validation": ch01_report,
        "outputs": {
            name: {
                "bytes": (output_dir / name).stat().st_size,
                "sha256": sha256(output_dir / name),
            }
            for name in output_names
        },
        "limitations": [
            "Tennis-Data dates have no time or timezone; quote fields are later annual revisions labeled latest_preplay_reported_time_unknown.",
            "Archive tourney_anchor_date is an event anchor, not a match date.",
            "Winner, score, surface, format and status are validation fields and never select a match candidate.",
            "Name-pattern candidates outside CH01 are mechanical proposals, not identity corrections.",
            "The 2018 workbook is a pinned third-party Git copy attributed to Tennis-Data; its original capture time is unknown.",
            "The 2006 and 2013 proposed year-relabel dates are candidates supported by archive anchor windows and pair/round evidence; source dates remain unchanged.",
        ],
    }
    (output_dir / "audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def validate(output_dir: Path, settings: JoinSettings) -> None:
    report = json.loads((output_dir / "audit.json").read_text())
    for name, record in report["outputs"].items():
        path = output_dir / name
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ChainError(f"output drift: {path}")
    for name, record in report["inputs"]["market_files"].items():
        path = resolve_under_root(record["path"], label=f"market file {name}")
        if sha256(path) != record["sha256"]:
            raise ChainError(f"market input drift: {name}")
        if record.get("receipt_path"):
            receipt = resolve_under_root(record["receipt_path"], label=f"market receipt {name}")
            if sha256(receipt) != record["receipt_sha256"]:
                raise ChainError(f"market receipt drift: {name}")
    panel = resolve_under_root(
        report["inputs"]["archive_source_panel"]["path"], label="archive_source_panel"
    )
    if sha256(panel) != report["inputs"]["archive_source_panel"]["sha256"]:
        raise ChainError("archive panel drift")
    for name in (
        "archive_quality_report",
        "market_manifest",
        "market_profile_adapter",
        "ch01_player_aliases",
        "ch01_event_crosswalk",
    ):
        record = report["inputs"][name]
        if sha256(resolve_under_root(record["path"], label=name)) != record["sha256"]:
            raise ChainError(f"input drift: {name}")
    for year, record in report["inputs"]["ch01_lineage"].items():
        if sha256(resolve_under_root(record["path"], label="ch01_lineage")) != record["sha256"]:
            raise ChainError(f"CH01 lineage drift: {year}")
    for name in ("tests", "original_adapter"):
        record = report["implementation"][name]
        if sha256(resolve_under_root(record["path"], label=name)) != record["sha256"]:
            raise ChainError(f"implementation drift: {name}")
    receipt = code_receipt(__name__)
    if receipt["sha256"] != report["implementation"]["adapter"]["sha256"]:
        raise ChainError("implementation drift: adapter")
    _ = settings
    print("MULTI01 join inputs and outputs validated")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["build", "validate"])
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--config", type=Path, help="JSON with an optional `join` object and `year_plan`"
    )
    args = parser.parse_args(argv)
    document = read_config(args.config) if args.config is not None else None
    settings = configure(document)
    output_dir = resolve_under_root(args.output_dir, label="output_dir")
    if args.mode == "build":
        print(json.dumps(build(output_dir, settings), indent=2, sort_keys=True))
    else:
        validate(output_dir, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
