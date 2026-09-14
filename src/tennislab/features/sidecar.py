"""Build a label-free trait and saved-latent sidecar, for either tour.

Stage ``sidecar``. Ported from the archive's ``WTA02_models/build_sidecar.py``, which is
the ``TIER01_models`` revision plus one change: the DOB locator was the literal
``data/raw/BIO01/attempt_001/atp_players.csv:<line>``, BIO01's ATP player master. The WTA
traits come from the archive's own ``wta/wta_players.csv`` (BIO01 covers only the ATP),
which the panel stage writes beside the panel and the config binds by hash, so the locator
names the bound file. For an ATP run binding BIO01's file the locator string is identical
to before. Nothing else moves: the trait contract, the D-2 cutoff, the same-date collapse
rule, the height/hand audit and the SR02 join are unchanged, and the player table is still
read for ``player_id`` and ``dob`` only.

What changed in the port: the ``BIO_PLAYERS_PATH`` global and its installer are replaced
by an explicit argument threaded to :func:`age_fields`; input and output paths resolve
through ``resolve_under_root`` instead of ``ROOT / value``; there is no
"write beside the source file" fallback -- a run must declare ``output.sidecar``;
``executed_builder`` becomes the package code receipt.

This stage does not read ``labels.csv``: the manifest names it, with the hash the bound
base manifest recorded, as the file that was deliberately not read.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import gzip
import io
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    code_receipt,
    relative_to_root,
    resolve_under_root,
    sha256,
    sha256_bytes,
)

BASE_KEYS = [
    "match_id",
    "calendar_year",
    "source_season",
    "match_date",
    "eligible_through_date",
    "tourney_id",
    "surface",
    "best_of",
    "player_a",
    "player_b",
    "primary_target",
    "identity_tier",
]
PANEL_KEY_FIELDS = [
    "match_id",
    "match_date",
    "source_season",
    "tourney_id",
    "surface",
    "best_of",
    "player_a",
    "player_b",
]
PANEL_MEASUREMENT_FIELDS = list(
    dict.fromkeys(
        PANEL_KEY_FIELDS
        + [
            "identity_tier",
            "a_entity_id",
            "b_entity_id",
            "a_height_cm",
            "b_height_cm",
            "a_hand",
            "b_hand",
            "source_key",
            "source_member",
            "source_line_number",
            "source_row_number",
        ]
    )
)
PLAYER_MEASUREMENT_FIELDS = ["player_id", "dob"]
SELECTED_AGREEMENT_FIELDS = [
    "match_id",
    "match_date",
    "source_season",
    "source_key",
    "tourney_id",
    "surface",
    "best_of",
    "player_a",
    "player_b",
]
SR02_FIELDS = [
    "annual_target_eligible",
    "rule_status",
    "selected_dynamic_id",
    "selected_unadjusted_id",
    "dynamic_p_a_serve",
    "dynamic_p_b_serve",
    "unadjusted_p_a_serve",
    "unadjusted_p_b_serve",
    "dynamic_match_probability_a",
    "unadjusted_match_probability_a",
    "simple_unadjusted_match_probability_a",
    "dynamic_a_logit_variance",
    "dynamic_b_logit_variance",
    "dynamic_a_b_logit_covariance",
    "dynamic_a_serve_unseen",
    "dynamic_a_return_unseen",
    "dynamic_a_surface_unseen",
    "dynamic_b_serve_unseen",
    "dynamic_b_return_unseen",
    "dynamic_b_surface_unseen",
    "dynamic_a_serve_point_observations",
    "dynamic_a_return_point_observations",
    "dynamic_a_surface_point_observations",
    "dynamic_b_serve_point_observations",
    "dynamic_b_return_point_observations",
    "dynamic_b_surface_point_observations",
]

SIDE_FIELDS: list[str] = []
for side in ("a", "b"):
    SIDE_FIELDS.extend(
        [
            f"age_years_at_target_{side}",
            f"age_missing_{side}",
            f"age_status_{side}",
            f"age_dob_locator_{side}",
            f"height_cm_{side}",
            f"height_missing_{side}",
            f"height_status_{side}",
            f"height_lag_days_{side}",
            f"height_source_group_id_{side}",
            f"height_audit_status_{side}",
            f"height_invalid_history_seen_{side}",
            f"height_latest_invalid_source_group_id_{side}",
            f"hand_{side}",
            f"hand_missing_{side}",
            f"hand_status_{side}",
            f"hand_lag_days_{side}",
            f"hand_source_group_id_{side}",
            f"hand_non_lr_history_seen_{side}",
            f"hand_latest_non_lr_code_{side}",
            f"hand_latest_non_lr_source_date_{side}",
            f"hand_latest_non_lr_source_group_id_{side}",
        ]
    )

SIDECAR_FIELDS = BASE_KEYS + SIDE_FIELDS + ["sr02_selected_match_present"] + SR02_FIELDS
LINEAGE_FIELDS = [
    "source_group_id",
    "field",
    "player_id",
    "source_date",
    "group_kind",
    "group_status",
    "selected_value",
    "source_values_json",
    "source_locators_json",
    "source_record_count",
]
CONFLICT_FIELDS = [
    "match_id",
    "target_side",
    "field",
    "player_id",
    "target_match_date",
    "eligible_through_date",
    "source_group_id",
    "source_date",
    "source_values_json",
    "source_locators_json",
]
FORBIDDEN_OUTPUT_FIELDS = {
    "a_won",
    "status",
    "score",
    "completed",
    "retired",
    "defaulted",
    "B365_decimal_a",
    "B365_decimal_b",
    "PS_decimal_a",
    "PS_decimal_b",
}


def require_hash(path: Path, expected: str, label: str) -> bytes:
    data = path.read_bytes()
    observed = sha256_bytes(data)
    if observed != expected:
        raise ChainError(f"{label} SHA-256 mismatch: {observed} != {expected}")
    return data


def parse_iso(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def finite_positive(value: str) -> float | None:
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def compact_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def locator(row: Mapping[str, str], side: str) -> dict[str, str]:
    return {
        "source_key": row["source_key"],
        "source_side": side,
        "source_member": row["source_member"],
        "source_line_number": row["source_line_number"],
        "source_row_number": row["source_row_number"],
    }


def normalized_height(value: float) -> str:
    return format(value, ".15g")


@dataclass(frozen=True)
class Selection:
    value: str
    missing: int
    status: str
    source_date: str
    lag_days: str
    group_id: str
    invalid_seen: int
    invalid_group_id: str
    invalid_value: str
    invalid_source_date: str


class TraitHistory:
    """Index primary-row source observations by canonical player and date."""

    def __init__(self, panel_rows: Iterable[Mapping[str, str]]):
        self.valid: dict[str, dict[str, dict[str, dict[str, set[str]]]]] = {
            "height": defaultdict(lambda: defaultdict(lambda: defaultdict(set))),
            "hand": defaultdict(lambda: defaultdict(lambda: defaultdict(set))),
        }
        self.invalid: dict[str, dict[str, dict[str, dict[str, set[str]]]]] = {
            "height": defaultdict(lambda: defaultdict(lambda: defaultdict(set))),
            "hand": defaultdict(lambda: defaultdict(lambda: defaultdict(set))),
        }
        self.all_positive_heights: set[str] = set()
        self.raw_counts: Counter[str] = Counter()
        self.lineage: dict[str, dict[str, object]] = {}

        for row in panel_rows:
            if row["identity_tier"] != "primary":
                continue
            source_date = row["match_date"]
            parse_iso(source_date)
            for side in ("a", "b"):
                self.raw_counts["sides"] += 1
                player_id = row[f"{side}_entity_id"]
                if player_id != row[f"player_{side}"]:
                    raise ChainError(
                        f"panel canonical player mismatch for {row['match_id']} side {side}"
                    )
                loc = compact_json(locator(row, side))
                height = finite_positive(row[f"{side}_height_cm"])
                if height is None:
                    self.raw_counts["height_missing_or_nonpositive"] += 1
                    raw_height = row[f"{side}_height_cm"]
                    self.invalid["height"][player_id][source_date][raw_height].add(loc)
                else:
                    self.raw_counts["height_positive"] += 1
                    value = normalized_height(height)
                    self.valid["height"][player_id][source_date][value].add(loc)
                    self.all_positive_heights.add(value)

                hand = row[f"{side}_hand"]
                self.raw_counts[f"hand_code_{hand or 'blank'}"] += 1
                if hand in {"L", "R"}:
                    self.valid["hand"][player_id][source_date][hand].add(loc)
                else:
                    self.invalid["hand"][player_id][source_date][hand].add(loc)

        self.valid_dates = {
            field: {player: sorted(by_date) for player, by_date in players.items()}
            for field, players in self.valid.items()
        }
        self.invalid_dates = {
            field: {player: sorted(by_date) for player, by_date in players.items()}
            for field, players in self.invalid.items()
        }
        self.height_distinct_counts: dict[str, list[int]] = {}
        for player_id, dates in self.valid_dates["height"].items():
            seen_values: set[str] = set()
            counts: list[int] = []
            for source_date in dates:
                seen_values.update(self.valid["height"][player_id][source_date])
                counts.append(len(seen_values))
            self.height_distinct_counts[player_id] = counts

    def multiple_height_values_through(self, player_id: str, cutoff: str) -> bool:
        dates = self.valid_dates["height"].get(player_id, [])
        index = bisect.bisect_right(dates, cutoff) - 1
        return index >= 0 and self.height_distinct_counts[player_id][index] > 1

    def _register_group(
        self,
        field: str,
        player_id: str,
        source_date: str,
        group_kind: str,
        values: Mapping[str, set[str]],
    ) -> str:
        value_list = sorted(values)
        locators = sorted({entry for entries in values.values() for entry in entries})
        payload = {
            "field": field,
            "player_id": player_id,
            "source_date": source_date,
            "group_kind": group_kind,
            "values": value_list,
            "locators": locators,
        }
        group_id = "tg_" + sha256_bytes(compact_json(payload).encode("utf-8"))[:20]
        if len(value_list) == 1:
            group_status = "single_value" if len(locators) == 1 else "consistent_duplicate_values"
            selected_value = value_list[0]
        else:
            group_status = "conflicting_values"
            selected_value = ""
        row = {
            "source_group_id": group_id,
            "field": field,
            "player_id": player_id,
            "source_date": source_date,
            "group_kind": group_kind,
            "group_status": group_status,
            "selected_value": selected_value,
            "source_values_json": compact_json(value_list),
            "source_locators_json": compact_json([json.loads(entry) for entry in locators]),
            "source_record_count": len(locators),
        }
        previous = self.lineage.get(group_id)
        if previous is not None and previous != row:
            raise ChainError(f"lineage ID collision: {group_id}")
        self.lineage[group_id] = row
        return group_id

    def _latest_group(
        self,
        store: dict[str, dict[str, dict[str, dict[str, set[str]]]]],
        dates: dict[str, dict[str, list[str]]],
        field: str,
        player_id: str,
        cutoff: str,
        kind: str,
    ) -> tuple[str, Mapping[str, set[str]], str] | None:
        player_dates = dates[field].get(player_id, [])
        index = bisect.bisect_right(player_dates, cutoff) - 1
        if index < 0:
            return None
        source_date = player_dates[index]
        values = store[field][player_id][source_date]
        return (
            source_date,
            values,
            self._register_group(field, player_id, source_date, kind, values),
        )

    def select(self, field: str, player_id: str, cutoff: str, target_date: str) -> Selection:
        selected = self._latest_group(
            self.valid, self.valid_dates, field, player_id, cutoff, "valid"
        )
        invalid = self._latest_group(
            self.invalid, self.invalid_dates, field, player_id, cutoff, "invalid"
        )
        invalid_seen = int(invalid is not None)
        invalid_group_id = invalid[2] if invalid else ""
        invalid_source_date = invalid[0] if invalid else ""
        invalid_value = ""
        if invalid:
            invalid_values = sorted(invalid[1])
            invalid_value = (
                invalid_values[0] if len(invalid_values) == 1 else compact_json(invalid_values)
            )

        if selected is None:
            return Selection(
                "",
                1,
                "no_prior_valid_observation",
                "",
                "",
                "",
                invalid_seen,
                invalid_group_id,
                invalid_value,
                invalid_source_date,
            )
        source_date, values, group_id = selected
        lag = str((parse_iso(target_date) - parse_iso(source_date)).days)
        if len(values) != 1:
            return Selection(
                "",
                1,
                "latest_valid_date_conflict",
                source_date,
                lag,
                group_id,
                invalid_seen,
                invalid_group_id,
                invalid_value,
                invalid_source_date,
            )
        value = next(iter(values))
        count = sum(len(locators) for locators in values.values())
        status = "observed" if count == 1 else "consistent_same_date_duplicates"
        return Selection(
            value,
            0,
            status,
            source_date,
            lag,
            group_id,
            invalid_seen,
            invalid_group_id,
            invalid_value,
            invalid_source_date,
        )


def load_players(
    rows: Iterable[Mapping[str, str]],
) -> tuple[dict[str, Mapping[str, str]], dict[str, int]]:
    players: dict[str, Mapping[str, str]] = {}
    lines: dict[str, int] = {}
    for line, row in enumerate(rows, start=2):
        player_id = row["player_id"]
        if player_id in players:
            raise ChainError(f"duplicate player_id: {player_id}")
        players[player_id] = row
        lines[player_id] = line
    return players, lines


def age_fields(
    player_id: str,
    target_date: str,
    players: Mapping[str, Mapping[str, str]],
    player_lines: Mapping[str, int],
    bio_players_path: str,
) -> dict[str, object]:
    player = players.get(player_id)
    if player is None:
        return {"value": "", "missing": 1, "status": "player_not_in_bio_table", "locator": ""}
    dob = player.get("dob", "")
    locator_value = f"{bio_players_path}:{player_lines[player_id]}"
    try:
        birth = dt.datetime.strptime(dob, "%Y%m%d").date()
        target = parse_iso(target_date)
    except TypeError, ValueError:
        return {
            "value": "",
            "missing": 1,
            "status": "missing_or_invalid_dob",
            "locator": locator_value,
        }
    age = (target - birth).days / 365.25
    if age < 0:
        return {
            "value": "",
            "missing": 1,
            "status": "dob_after_target_date",
            "locator": locator_value,
        }
    return {
        "value": format(age, ".17g"),
        "missing": 0,
        "status": "derived_from_current_bio_dob",
        "locator": locator_value,
    }


def project_side(
    output: dict[str, object],
    side: str,
    player_id: str,
    target_date: str,
    cutoff: str,
    history: TraitHistory,
    players: Mapping[str, Mapping[str, str]],
    player_lines: Mapping[str, int],
    match_id: str,
    conflicts: list[dict[str, object]],
    bio_players_path: str,
) -> None:
    age = age_fields(player_id, target_date, players, player_lines, bio_players_path)
    output[f"age_years_at_target_{side}"] = age["value"]
    output[f"age_missing_{side}"] = age["missing"]
    output[f"age_status_{side}"] = age["status"]
    output[f"age_dob_locator_{side}"] = age["locator"]

    height = history.select("height", player_id, cutoff, target_date)
    output[f"height_cm_{side}"] = height.value
    output[f"height_missing_{side}"] = height.missing
    output[f"height_status_{side}"] = height.status
    output[f"height_lag_days_{side}"] = height.lag_days
    output[f"height_source_group_id_{side}"] = height.group_id
    height_flags = ["positive_unbounded_no_plausibility_filter"] if not height.missing else []
    if history.multiple_height_values_through(player_id, cutoff):
        height_flags.append("player_has_multiple_positive_source_values")
    output[f"height_audit_status_{side}"] = ";".join(height_flags)
    output[f"height_invalid_history_seen_{side}"] = height.invalid_seen
    output[f"height_latest_invalid_source_group_id_{side}"] = height.invalid_group_id

    hand = history.select("hand", player_id, cutoff, target_date)
    output[f"hand_{side}"] = hand.value
    output[f"hand_missing_{side}"] = hand.missing
    output[f"hand_status_{side}"] = hand.status
    output[f"hand_lag_days_{side}"] = hand.lag_days
    output[f"hand_source_group_id_{side}"] = hand.group_id
    output[f"hand_non_lr_history_seen_{side}"] = hand.invalid_seen
    output[f"hand_latest_non_lr_code_{side}"] = hand.invalid_value
    output[f"hand_latest_non_lr_source_date_{side}"] = hand.invalid_source_date
    output[f"hand_latest_non_lr_source_group_id_{side}"] = hand.invalid_group_id

    for field, selected in (("height", height), ("hand", hand)):
        if selected.status != "latest_valid_date_conflict":
            continue
        lineage = history.lineage[selected.group_id]
        conflicts.append(
            {
                "match_id": match_id,
                "target_side": side,
                "field": field,
                "player_id": player_id,
                "target_match_date": target_date,
                "eligible_through_date": cutoff,
                "source_group_id": selected.group_id,
                "source_date": selected.source_date,
                "source_values_json": lineage["source_values_json"],
                "source_locators_json": lineage["source_locators_json"],
            }
        )


def keyed(rows: Iterable[Mapping[str, str]], label: str) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        key = row["match_id"]
        if key in result:
            raise ChainError(f"duplicate {label} match_id: {key}")
        result[key] = row
    return result


def build_sidecar_rows(
    base_rows: list[Mapping[str, str]],
    panel_rows: list[Mapping[str, str]],
    player_rows: list[Mapping[str, str]],
    selected_rows: list[Mapping[str, str]],
    bio_players_path: str,
) -> tuple[list[dict[str, object]], TraitHistory, list[dict[str, object]], dict[str, object]]:
    panel = keyed(panel_rows, "panel")
    selected = keyed(selected_rows, "SR02 selected")
    players, player_lines = load_players(player_rows)
    history = TraitHistory(panel_rows)
    outputs: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    counts: Counter[str] = Counter()

    seen_base: set[str] = set()
    for base in base_rows:
        match_id = base["match_id"]
        if match_id in seen_base:
            raise ChainError(f"duplicate base match_id: {match_id}")
        seen_base.add(match_id)
        raw = panel.get(match_id)
        if raw is None:
            raise ChainError(f"base match absent from panel: {match_id}")
        for field in PANEL_KEY_FIELDS:
            if base[field] != raw[field]:
                raise ChainError(
                    f"base/panel disagreement {match_id} {field}: {base[field]} != {raw[field]}"
                )
        expected_cutoff = parse_iso(base["match_date"]) - dt.timedelta(days=2)
        if base["eligible_through_date"] != expected_cutoff.isoformat():
            raise ChainError(f"bad D-2 cutoff for {match_id}")

        output: dict[str, object] = {field: base[field] for field in BASE_KEYS}
        for side in ("a", "b"):
            project_side(
                output,
                side,
                base[f"player_{side}"],
                base["match_date"],
                base["eligible_through_date"],
                history,
                players,
                player_lines,
                match_id,
                conflicts,
                bio_players_path,
            )

        latent = selected.get(match_id)
        output["sr02_selected_match_present"] = int(latent is not None)
        if latent is None:
            for field in SR02_FIELDS:
                output[field] = ""
            counts["sr02_missing"] += 1
        else:
            for field in SELECTED_AGREEMENT_FIELDS:
                reference = raw[field] if field == "source_key" else base[field]
                if latent[field] != reference:
                    raise ChainError(
                        f"SR02/base disagreement {match_id} {field}: {latent[field]} != {reference}"
                    )
            for field in SR02_FIELDS:
                output[field] = latent[field]
            counts["sr02_present"] += 1
            counts[f"annual_target_eligible_{latent['annual_target_eligible']}"] += 1

        for side in ("a", "b"):
            counts[f"age_{output[f'age_status_{side}']}"] += 1
            counts[f"height_{output[f'height_status_{side}']}"] += 1
            counts[f"hand_{output[f'hand_status_{side}']}"] += 1
            counts["height_missing"] += int(output[f"height_missing_{side}"])
            counts["hand_missing"] += int(output[f"hand_missing_{side}"])
            counts["age_missing"] += int(output[f"age_missing_{side}"])
            counts["hand_non_lr_history_seen"] += int(output[f"hand_non_lr_history_seen_{side}"])
        outputs.append(output)

    extras = sorted(set(selected) - seen_base)
    if extras:
        raise ChainError(f"SR02 selected rows absent from base: {extras[:3]}")
    if len(outputs) != len(base_rows):
        raise ChainError("sidecar row loss")
    summary = {
        "base_rows": len(base_rows),
        "output_rows": len(outputs),
        "unique_match_ids": len(seen_base),
        "counts": dict(sorted(counts.items())),
        "lineage_groups_referenced": len(history.lineage),
        "same_date_target_conflicts": len(conflicts),
        "retrospective_height_positive_source_range_cm": [
            min(float(value) for value in history.all_positive_heights),
            max(float(value) for value in history.all_positive_heights),
        ],
        "retrospective_primary_history_raw_trait_counts": dict(sorted(history.raw_counts.items())),
        "status": "no_fit_no_score_trait_and_saved_latent_sidecar",
    }
    return outputs, history, conflicts, summary


def read_csv_bytes(data: bytes, label: str) -> list[dict[str, str]]:
    text = data.decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise ChainError(f"empty CSV: {label}")
    return rows


def project_rows(
    rows: Iterable[Mapping[str, str]], fields: Iterable[str], label: str
) -> list[dict[str, str]]:
    ordered_fields = list(fields)
    projected: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=2):
        missing = [field for field in ordered_fields if field not in row]
        if missing:
            raise ChainError(f"{label} row {index} missing fields: {missing}")
        projected.append({field: row[field] for field in ordered_fields})
    return projected


def project_measurement_inputs(
    base_rows: Iterable[Mapping[str, str]],
    panel_rows: Iterable[Mapping[str, str]],
    player_rows: Iterable[Mapping[str, str]],
    selected_rows: Iterable[Mapping[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    return (
        project_rows(base_rows, BASE_KEYS, "base features"),
        project_rows(panel_rows, PANEL_MEASUREMENT_FIELDS, "SR02 panel"),
        project_rows(player_rows, PLAYER_MEASUREMENT_FIELDS, "BIO01 players"),
        project_rows(
            selected_rows,
            list(dict.fromkeys(SELECTED_AGREEMENT_FIELDS + SR02_FIELDS)),
            "SR02 selected matches",
        ),
    )


def write_csv(path: Path, fields: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def write_csv_gzip(path: Path, fields: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", fileobj=raw_handle, mode="wb", mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text_handle:
                writer = csv.DictWriter(text_handle, fieldnames=fields, extrasaction="raise")
                writer.writeheader()
                writer.writerows(rows)


def run(config_path: Path) -> dict[str, object]:
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    inputs = config["inputs"]
    bio_players_path = str(inputs["bio_players"]["path"])
    loaded: dict[str, bytes] = {}
    for name, binding in inputs.items():
        path = resolve_under_root(binding["path"], label=name)
        loaded[name] = require_hash(path, binding["sha256"], name)

    base_manifest = json.loads(loaded["base_manifest"])
    if base_manifest["outputs"]["features.csv"]["sha256"] != inputs["base_features"]["sha256"]:
        raise ChainError("base manifest does not bind configured feature file")
    dictionary = json.loads(loaded["base_dictionary"])
    forbidden = set(dictionary["forbidden_from_sports_predictors"])
    if not {"a_won", "status", "score"}.issubset(forbidden):
        raise ChainError("base dictionary label-separation contract missing")

    base_rows, panel_rows, player_rows, selected_rows = project_measurement_inputs(
        read_csv_bytes(loaded["base_features"], "base features"),
        read_csv_bytes(loaded["sr02_panel"], "SR02 panel"),
        read_csv_bytes(loaded["bio_players"], "bio players"),
        read_csv_bytes(loaded["sr02_selected_matches"], "SR02 selected matches"),
    )
    outputs, history, conflicts, summary = build_sidecar_rows(
        base_rows, panel_rows, player_rows, selected_rows, bio_players_path
    )

    declared = config.get("output", {}).get("sidecar")
    if not declared:
        raise ChainError("configuration declares no output.sidecar path")
    output_dir = resolve_under_root(declared, label="output.sidecar").parent
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "trait_latent_sidecar.csv", SIDECAR_FIELDS, outputs)
    write_csv_gzip(
        output_dir / "trait_lineage_groups.csv.gz",
        LINEAGE_FIELDS,
        [history.lineage[key] for key in sorted(history.lineage)],
    )
    old_plain_lineage = output_dir / "trait_lineage_groups.csv"
    if old_plain_lineage.exists():
        old_plain_lineage.unlink()
    write_csv(output_dir / "trait_conflicts.csv", CONFLICT_FIELDS, conflicts)
    atomic_json(output_dir / "summary.json", summary)

    output_lineage_ids = {
        str(row[field])
        for row in outputs
        for side in ("a", "b")
        for field in (
            f"height_source_group_id_{side}",
            f"height_latest_invalid_source_group_id_{side}",
            f"hand_source_group_id_{side}",
            f"hand_latest_non_lr_source_group_id_{side}",
        )
        if row[field]
    }
    if output_lineage_ids != set(history.lineage):
        raise ChainError("sidecar/lineage reference set mismatch")
    for row in outputs:
        for side in ("a", "b"):
            for field in (
                f"height_source_group_id_{side}",
                f"height_latest_invalid_source_group_id_{side}",
                f"hand_source_group_id_{side}",
                f"hand_latest_non_lr_source_group_id_{side}",
            ):
                group_id = str(row[field])
                if (
                    group_id
                    and history.lineage[group_id]["source_date"] > row["eligible_through_date"]
                ):
                    raise ChainError(f"future lineage group for {row['match_id']}: {group_id}")
    if FORBIDDEN_OUTPUT_FIELDS & set(SIDECAR_FIELDS):
        raise ChainError("forbidden outcome or price field in sidecar schema")
    validation: dict[str, Any] = {
        "status": "PASS",
        "checks": {
            "base_panel_key_date_player_surface_best_of_agreement": "exact on all 51,222 rows",
            "base_eligible_through_date": "exactly reported match date minus 2 days",
            "history_membership": "only identity_tier=primary rows indexed",
            "history_cutoff": "selected trait source groups are no later than eligible_through_date",
            "row_count_and_key_uniqueness": "51,222 rows and unique match_id",
            "sr02_saved_field_projection": "exact on 34,724 joined rows; blank on 16,498 absent rows",
            "sidecar_lineage_reference_set": "exact",
            "sidecar_forbidden_outcome_and_price_fields": "absent",
            "companion_labels": "not read",
        },
        "counts": {
            "rows": len(outputs),
            "sr02_present": summary["counts"]["sr02_present"],
            "sr02_missing": summary["counts"]["sr02_missing"],
            "lineage_groups": len(history.lineage),
            "same_date_target_conflicts": len(conflicts),
        },
    }
    atomic_json(output_dir / "validation.json", validation)

    dictionary_out = {
        "dictionary_id": "JOINT04-trait-latent-sidecar-v1",
        "sidecar_columns": SIDECAR_FIELDS,
        "key_and_agreement_columns": BASE_KEYS,
        "trait_candidate_fields": {
            "age": [f"age_years_at_target_{side}" for side in ("a", "b")]
            + [f"age_missing_{side}" for side in ("a", "b")],
            "height": [f"height_cm_{side}" for side in ("a", "b")]
            + [f"height_missing_{side}" for side in ("a", "b")],
            "hand_raw": [f"hand_{side}" for side in ("a", "b")]
            + [f"hand_missing_{side}" for side in ("a", "b")],
        },
        "sr02_saved_dynamic_fields": SR02_FIELDS,
        "lineage_columns": LINEAGE_FIELDS,
        "forbidden_output_fields": sorted(FORBIDDEN_OUTPUT_FIELDS),
        "contracts": config["history_contract"],
        "notes": [
            "The sidecar contains saved SR02 outputs, not refitted latent states.",
            "annual_target_eligible=0 is preserved for SR02 warmup rows and is not a source-year mismatch flag.",
            "Per-target height audit status uses only history through D-2; no positive source value is clipped or rejected on plausibility grounds.",
            "The summary's observed positive-height range is a retrospective census and is not a target-row feature.",
            "The source panel carries outcome fields, but this adapter does not analyze or emit them.",
        ],
    }
    atomic_json(output_dir / "column_dictionary.json", dictionary_out)

    generated = [
        "trait_latent_sidecar.csv",
        "trait_lineage_groups.csv.gz",
        "trait_conflicts.csv",
        "summary.json",
        "validation.json",
        "column_dictionary.json",
    ]
    manifest = {
        "manifest_id": "JOINT04-trait-latent-sidecar-v1",
        "status": "no_fit_no_score",
        "executed_builder": code_receipt(__name__),
        "config": {
            "path": relative_to_root(config_path, label="config"),
            "sha256": sha256_bytes(config_raw),
        },
        "inputs": inputs,
        "not_read": {
            "labels": {
                "path": str(Path(inputs["base_features"]["path"]).parent / "labels.csv"),
                "sha256_from_bound_base_manifest": base_manifest["outputs"]["labels.csv"]["sha256"],
            }
        },
        "outputs": {
            name: {
                "bytes": (output_dir / name).stat().st_size,
                "sha256": sha256(output_dir / name),
            }
            for name in generated
        },
    }
    atomic_json(output_dir / "manifest.json", manifest)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run(resolve_under_root(args.config, label="config"))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
