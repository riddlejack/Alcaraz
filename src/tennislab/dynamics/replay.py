"""Advance the *saved* SR02 selected point paths through new matches. No reselection.

Stages ``sr02_replay``, ``sr02_tier_replay`` and ``sr02_tier_noqual_replay``. Base
revision: ``references/TIER01_models/sr02_replay.py`` (CONFIRM2026 revision 8 plus the
lower-tier feed and its same-event-qualifying ablation). Merged from
``references/WTA02_models/sr02_replay.py``: ``relabelled_count_block_statuses``,
``count_history_from_year`` and the per-year dynamic dispersion report. Every switch is
configuration under ``sr02_replay`` and defaults to the CONFIRM2026 behaviour.

What this does. ``path_runner`` runs all 24 candidate point paths, scores them on past
point losses, selects one per year and writes ``selected_matches.csv``. This program
does not rebuild the menu and computes no point loss: it reads the saved
``selections.csv``, takes the candidate id each year already selected, replays only
those two paths over the (possibly extended) stream, and lets a target year after the
last saved selection year inherit that year's candidate (``selection_carry_forward.csv``).
The filter, the unadjusted baseline, the rule conversion and the D-2 chronology are the
package modules :mod:`tennislab.dynamics.dynamic` and :mod:`tennislab.dynamics.path_runner`;
the frozen config's ``execution_binding`` (archive path and sha256 of the two files) is
read and recorded in the manifest as ``code.declared_binding`` (porting guide rule 2),
and the code that ran is recorded by ``code_receipt``.

Stale states. A match with no serve counts (``missing_all``, or any label listed in
``relabelled_count_block_statuses``, which defaults to ``quarantined_invalid`` only)
updates no state; the forecast is still emitted from the current states, and every row
carries ``dynamic_state_stale_days_a/b`` and their maximum. These are provenance, never
features (``PROVENANCE_ONLY_COLUMNS``). With ``count_history_from_year`` set, every
earlier row is replayed as a match without counts however complete its block, so the
states are initialised at that year (WTA02: the complete WTA serve block starts 2016).

Lower-tier feed (``tier_feed.enabled``). ``tier_stream``'s qualifying/Challenger rows are
appended to the **history observations** and to nothing else: never targets, never fit
rows, never rule rows. The file must carry exactly ``dynamic.SOURCE_ROW_FIELDS``, so no
outcome or price column can reach the filter. ``exclude_same_event_qualifying`` drops
feed rows whose ``tourney_id`` is a panel main draw's (a qualifying row admitted under a
main draw's own id updates the event's latent term, so it is not purely player-state
information); both replays declare the same-event membership read off the unfiltered
feed. The best-of-three rule a feed row *would* take is recorded in
``tier_feed_rule_basis.json`` and never consumed.

Reporting shape. The two archive revisions differ in the manifest ``id``, the manifest
keys they add (``tier_feed``/``tier_feed_rule_basis`` versus
``dynamic_dispersion_by_year``/``years_with_a_constant_dynamic_probability``), the
``limits`` text and the stdout summary. Top-level ``tour`` selects the revision's shape
(``ATP``, the default, is TIER01; ``WTA`` is WTA02) so each archive run reproduces byte
for byte; the numerical path honours every switch regardless of tour.

RESERVED WINDOW. This program reads the panel, which for a reserved season exists only
after the panel build has read those seasons' results; it is downstream of that exposure
event. It reads serve counts (pre-match information for *later* matches under the D-2
rule) and never reads ``a_won``: ``dynamic.SOURCE_ROW_FIELDS`` does not include it, and
``path_runner.merge_selected_matches`` raises if a label or price column reaches the
output.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import math
from collections import Counter
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
    sha256,
    year_plan,
)
from tennislab.dynamics import dynamic, path_runner

# Provenance columns this program adds. They describe how stale a state was, which is a
# property of data availability, not of the match, and they are correlated with coverage
# rather than with tennis. Treated as features they would leak the acquisition route.
PROVENANCE_ONLY_COLUMNS = (
    "dynamic_state_stale_days_a",
    "dynamic_state_stale_days_b",
    "dynamic_state_stale_days",
)

# Declared in `experiments/CONFIRM2026.design.md` (Procedures frozen, Control (P0)) on
# 2026-09-11: a match whose serve-count block is internally inconsistent
# (`quarantined_invalid`) is treated like a match without counts. The archive panel
# already blanks every primitive count on such a row, so the information content is
# identical to `missing_all`; only the label differs, and `observation_from_source_row`
# accepts just `usable` and `missing_all`. The mapping happens here, before the frozen
# loader sees the row. WTA02 generalises the list (`partial_missing`: a block missing the
# service-game count is a block this filter cannot use) and adds `count_history_from_year`.
QUARANTINED_COUNT_BLOCK_STATUS = "quarantined_invalid"
NO_UPDATE_COUNT_BLOCK_STATUS = "missing_all"
DEFAULT_RELABELLED_COUNT_BLOCK_STATUSES = (QUARANTINED_COUNT_BLOCK_STATUS,)

STALE_FIELDS = (
    "match_id",
    "match_date",
    "source_season",
    "tourney_id",
    "player_a",
    "player_b",
    "count_block_status",
    "status",
    "identity_tier",
    "history_eligible",
    "exclusion_reason",
    "dynamic_state_stale_days_a",
    "dynamic_state_stale_days_b",
    "dynamic_state_stale_days",
)
SELECTION_MAP_FIELDS = (
    "candidate_family",
    "selection_year",
    "selected_candidate_id",
    "source",
    "inherited_from_selection_year",
)
SAME_EVENT_FIELDS = (
    "match_id",
    "match_date",
    "tourney_id",
    "same_event_qualifying_rows",
    "earliest_qualifying_date",
    "latest_qualifying_date",
)
TIER_FEED_FIELDS_NOTE = (
    "the feed header must equal dynamic.SOURCE_ROW_FIELDS exactly, so no outcome, "
    "price or label column can reach the filter"
)
# The WTA02 revision's additions to the `source` summary; the TIER01 shape omits them.
WTA02_SOURCE_KEYS = (
    "relabelled_count_block_statuses",
    "count_blocks_relabelled_to_missing_all",
    "count_history_from_year",
    "pre_floor_count_blocks_suppressed_by_year",
    "pre_floor_count_blocks_suppressed_by_status",
)


def declared_engine_binding(primary: Mapping[str, Any]) -> dict[str, Any]:
    """The engine files the frozen SR02 config binds by path and hash, recorded not loaded."""
    binding = primary["execution_binding"]
    return {
        name: binding[name]
        for name in ("dynamic_path", "dynamic_sha256", "runner_path", "runner_sha256")
    }


def reporting_revision(document: Mapping[str, Any]) -> str:
    tour = str(document.get("tour", "ATP")).upper()
    if tour not in {"ATP", "WTA"}:
        raise ChainError(f"unsupported tour: {tour!r}")
    return "WTA02" if tour == "WTA" else "TIER01"


def load_source(
    panel_path: Path,
    rules_path: Path,
    *,
    history_statuses: Sequence[str],
    source_year_min: int,
    source_year_max: int,
    relabelled_statuses: Sequence[str] = DEFAULT_RELABELLED_COUNT_BLOCK_STATUSES,
    count_history_from_year: int | None = None,
) -> tuple[list[Any], list[Any], dict[str, Any]]:
    """Parameterized ``path_runner._load_source``.

    Differences from the original, and only these: the ``2005 <= source_season <= 2024``
    / ``match_date.year > 2024`` gate becomes the configured span; a count block whose
    label is in ``relabelled_statuses`` is relabelled ``missing_all`` before the frozen
    loader sees it (the design's declared no-update path) and the affected quarantined
    match ids are reported; with ``count_history_from_year`` every earlier row's block is
    suppressed the same way; a target with no rule row is allowed and reported instead
    of raising; the ``panel_rows`` count assertion moves into the caller.
    """
    rules: dict[str, tuple[dict[str, str], Any]] = {}
    _, rule_rows = read_csv_rows(rules_path)
    for row in rule_rows:
        key = row["source_key"]
        if key in rules or key != row["match_id"]:
            raise ChainError(f"duplicate or inconsistent rule key: {key}")
        if not row["match_rule"]:
            continue
        rules[key] = (row, dynamic.MatchRule.from_mapping(json.loads(row["match_rule"])))

    additional = ("source_season", "source_key", "round", "best_of")
    selected_fields = tuple(dict.fromkeys((*dynamic.SOURCE_ROW_FIELDS, *additional)))
    header, panel_rows = read_csv_rows(panel_path)
    missing = set(selected_fields) - set(header)
    if missing:
        raise ChainError(f"source panel header lacks {sorted(missing)}")
    observations: list[Any] = []
    targets: list[Any] = []
    without_rule: list[str] = []
    quarantined: list[str] = []
    relabelled_by_status: Counter[str] = Counter()
    pre_floor_by_year: Counter[int] = Counter()
    pre_floor_by_status: Counter[str] = Counter()
    relabelled = frozenset(relabelled_statuses)
    for line_number, full in enumerate(panel_rows, 2):
        row = {field: full[field] for field in selected_fields}
        original_status = row["count_block_status"]
        if original_status in relabelled:
            row["count_block_status"] = NO_UPDATE_COUNT_BLOCK_STATUS
            relabelled_by_status[original_status] += 1
            if original_status == QUARANTINED_COUNT_BLOCK_STATUS:
                quarantined.append(full["match_id"])
        if (
            count_history_from_year is not None
            and int(row["source_season"]) < count_history_from_year
            and row["count_block_status"] != NO_UPDATE_COUNT_BLOCK_STATUS
        ):
            pre_floor_by_year[int(row["source_season"])] += 1
            pre_floor_by_status[row["count_block_status"]] += 1
            row["count_block_status"] = NO_UPDATE_COUNT_BLOCK_STATUS
        observation = dynamic.observation_from_source_row(
            row, history_statuses=tuple(history_statuses)
        )
        source_season = int(row["source_season"])
        if not source_year_min <= source_season <= source_year_max:
            raise ChainError(
                f"source season {source_season} lies outside the configured span "
                f"{source_year_min}-{source_year_max} at line {line_number}"
            )
        if observation.match_date.year > source_year_max:
            raise ChainError(
                f"match date {observation.match_date} lies after the configured span end "
                f"{source_year_max} at line {line_number}"
            )
        entry = rules.get(row["source_key"])
        if entry is None:
            rule = None
            without_rule.append(row["source_key"])
        else:
            rule_row, rule = entry
            for field in (
                "match_id",
                "source_key",
                "source_season",
                "tourney_id",
                "round",
                "best_of",
            ):
                if str(rule_row[field]) != str(row[field]):
                    raise ChainError(f"rule/source metadata differs at line {line_number}: {field}")
        target = dynamic.TargetMatch(
            observation.match_id,
            observation.match_date,
            observation.tourney_id,
            observation.surface,
            int(row["best_of"]),
            observation.player_a,
            observation.player_b,
            rule,
        )
        observations.append(observation)
        targets.append(path_runner.PathTarget(target, source_season, row["source_key"]))
    summary = {
        "panel_rows": len(observations),
        "rule_rows_with_a_rule": len(rules),
        "targets_without_a_rule": len(without_rule),
        "targets_without_a_rule_examples": sorted(without_rule)[:20],
        "quarantined_invalid_count_blocks_mapped_to_missing_all": len(quarantined),
        "quarantined_invalid_count_block_match_ids": sorted(quarantined),
        "quarantined_invalid_mapping_basis": (
            "CONFIRM2026.design.md, Procedures frozen, Control (P0), declared "
            "2026-09-11 before any P0/P1 forecast"
        ),
        "relabelled_count_block_statuses": sorted(relabelled),
        "count_blocks_relabelled_to_missing_all": dict(sorted(relabelled_by_status.items())),
        "count_history_from_year": count_history_from_year,
        "pre_floor_count_blocks_suppressed_by_year": dict(sorted(pre_floor_by_year.items())),
        "pre_floor_count_blocks_suppressed_by_status": dict(sorted(pre_floor_by_status.items())),
    }
    return observations, targets, summary


def load_tier_feed(
    feed_path: Path,
    *,
    history_statuses: Sequence[str],
    source_year_min: int,
    source_year_max: int,
    panel_match_ids: set[str],
    panel_tourney_ids: frozenset[str] = frozenset(),
    exclude_tourney_ids: frozenset[str] = frozenset(),
) -> tuple[list[Any], dict[str, Any], list[dict[str, Any]]]:
    """Read ``tier_stream``'s lower-tier serve-count rows as history observations only.

    The file is gzip CSV in exactly ``dynamic.SOURCE_ROW_FIELDS``. Every row is checked
    against the configured season span, against the panel's own match ids (a collision
    would mean a lower-tier row could be mistaken for a target) and against the two count
    block labels the frozen loader accepts. Nothing here becomes a target.

    ``exclude_tourney_ids`` is the same-event ablation (archive review finding 8): passing
    the panel's tourney ids drops exactly the rows carried under a main draw's own id; the
    third return value is the same-event membership, read off the *unfiltered* file so
    both the full and the ablated replay can declare it.
    """
    with gzip.open(feed_path, "rb") as handle:
        text = handle.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = tuple(reader.fieldnames or ())
    if header != tuple(dynamic.SOURCE_ROW_FIELDS):
        raise ChainError(
            "lower-tier feed header is not dynamic.SOURCE_ROW_FIELDS: "
            f"{sorted(set(header) ^ set(dynamic.SOURCE_ROW_FIELDS))}"
        )
    observations: list[Any] = []
    counters: Counter[str] = Counter()
    seasons: Counter[int] = Counter()
    same_event: list[dict[str, Any]] = []
    for line_number, row in enumerate(reader, 2):
        counters["rows_read"] += 1
        if row["match_id"] in panel_match_ids:
            raise ChainError(
                f"lower-tier feed collides with a panel match id at line {line_number}"
            )
        if row["count_block_status"] not in {"usable", NO_UPDATE_COUNT_BLOCK_STATUS}:
            raise ChainError(
                f"lower-tier feed count block status {row['count_block_status']!r} at line "
                f"{line_number}"
            )
        observation = dynamic.observation_from_source_row(
            row, history_statuses=tuple(history_statuses)
        )
        year = observation.match_date.year
        if not source_year_min <= year <= source_year_max:
            raise ChainError(
                f"lower-tier feed row dated {observation.match_date} lies outside the "
                f"configured span {source_year_min}-{source_year_max} at line {line_number}"
            )
        if row["tourney_id"] in exclude_tourney_ids:
            counters["same_event_rows_excluded"] += 1
            counters[f"same_event_excluded_{row['count_block_status']}"] += 1
            same_event.append(
                {
                    "tourney_id": row["tourney_id"],
                    "match_id": row["match_id"],
                    "match_date": row["match_date"],
                    "count_block_status": row["count_block_status"],
                }
            )
            continue
        if row["tourney_id"] in panel_tourney_ids:
            counters["same_event_rows_admitted"] += 1
            same_event.append(
                {
                    "tourney_id": row["tourney_id"],
                    "match_id": row["match_id"],
                    "match_date": row["match_date"],
                    "count_block_status": row["count_block_status"],
                }
            )
        seasons[year] += 1
        counters[f"count_block_{row['count_block_status']}"] += 1
        counters["history_eligible" if observation.history_eligible else "history_ineligible"] += 1
        observations.append(observation)
    summary = {
        "feed_rows": counters["rows_read"],
        "feed_rows_by_year": dict(sorted(seasons.items())),
        "counters": dict(sorted(counters.items())),
        "service_points_available": sum(
            (item.service_a.points_played if item.service_a is not None else 0)
            + (item.service_b.points_played if item.service_b is not None else 0)
            for item in observations
            if item.history_eligible
        ),
        "targets_contributed": 0,
        "fit_rows_contributed": 0,
        "header_contract": TIER_FEED_FIELDS_NOTE,
        "same_event_qualifying": {
            "excluded": bool(exclude_tourney_ids),
            "rows_sharing_a_main_draw_tourney_id": len(same_event),
            "rows_excluded": counters["same_event_rows_excluded"],
            "rows_admitted": counters["same_event_rows_admitted"],
            "basis": "docs/reviews/astra_review_2026-09-12.md finding 8",
        },
    }
    return observations, summary, same_event


def tier_feed_rule_basis(rule_config_path: Path, feed_summary: Mapping[str, Any]) -> dict[str, Any]:
    """The declared best-of-three rule a lower-tier row would take, recorded not consumed."""
    rules = json.loads(rule_config_path.read_text(encoding="utf-8"))
    ordinary = rules["ordinary_atp"]
    if int(ordinary["best_of"]) != 3:
        raise ChainError("the frozen ordinary-ATP rule is not best-of-three")
    return {
        "carried_rule": {
            "best_of": ordinary["best_of"],
            "regular_set": rules["regular_set"],
            "deciding_set": ordinary["deciding_set"],
            "basis": ordinary["basis"],
        },
        "carried_to_seasons": sorted(feed_summary["feed_rows_by_year"]),
        "feed_rows_by_year": feed_summary["feed_rows_by_year"],
        "rule_config": {
            "path": relative_to_root(rule_config_path, label="tier_rule_config"),
            "sha256": sha256(rule_config_path),
        },
        "consumed_by_the_replay": False,
        "why_not_consumed": (
            "a history row supplies service points only: "
            "dynamic.observation_from_source_row reads no best_of and no rule, and "
            "path_runner.selected_match_predictions converts a serve probability to a "
            "match probability for TARGETS alone.  The rule is recorded so a later design "
            "that prices a lower-tier match does not have to invent one."
        ),
    }


def same_event_membership(
    same_event_rows: Sequence[Mapping[str, Any]], targets: Sequence[Any], lag_days: int
) -> list[dict[str, Any]]:
    """Targets whose event's latent term could have been updated by same-event qualifying."""
    available: dict[str, list[str]] = {}
    for row in same_event_rows:
        if row["count_block_status"] == "usable":
            available.setdefault(row["tourney_id"], []).append(row["match_date"])
    membership: list[dict[str, Any]] = []
    for record in sorted(targets, key=lambda item: (item.match.match_date, item.match.match_id)):
        target = record.match
        dates = available.get(target.tourney_id)
        if not dates:
            continue
        cutoff = (target.match_date - dt.timedelta(days=lag_days)).isoformat()
        eligible = [value for value in dates if value <= cutoff]
        if not eligible:
            continue
        membership.append(
            {
                "match_id": target.match_id,
                "match_date": target.match_date.isoformat(),
                "tourney_id": target.tourney_id,
                "same_event_qualifying_rows": len(eligible),
                "earliest_qualifying_date": min(eligible),
                "latest_qualifying_date": max(eligible),
            }
        )
    return membership


def dynamic_dispersion_by_year(merged: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per emitted year: how much the dynamic probability actually varies.

    Before the first season with serve counts the filter has nothing to update from, so
    every target of those years is priced off the same prior state and the feature is a
    constant: present, knowable at the cutoff and carrying no information. The replay
    measures it rather than leaving it to be noticed. Feature-availability provenance,
    never features.
    """
    by_year: dict[int, list[Mapping[str, Any]]] = {}
    for row in merged:
        by_year.setdefault(int(str(row["match_date"])[:4]), []).append(row)
    output: dict[str, Any] = {}
    for year, rows in sorted(by_year.items()):
        values = [
            float(row["dynamic_match_probability_a"])
            for row in rows
            if row.get("dynamic_match_probability_a") not in (None, "")
        ]
        distinct = len({format(value, ".17g") for value in values})
        mean = sum(values) / len(values) if values else None
        variance = (
            sum((value - mean) ** 2 for value in values) / len(values) if len(values) > 1 else 0.0
        )
        output[str(year)] = {
            "rows_emitted": len(rows),
            "rows_with_a_dynamic_probability": len(values),
            "distinct_dynamic_probabilities": distinct,
            "dynamic_probability_sd": math.sqrt(variance) if values else None,
            "informative": distinct > 1,
            "rows_with_an_unseen_serve_state": sum(
                1
                for row in rows
                if str(row.get("dynamic_a_serve_unseen")) == "1"
                or str(row.get("dynamic_b_serve_unseen")) == "1"
            ),
        }
    return output


def stale_days_by_target(
    observations: Sequence[Any], targets: Sequence[Any], lag_days: int
) -> dict[str, dict[str, Any]]:
    """Calendar days from each side's last *eligible* history row to the target date.

    Walks the same (match_date, match_id)-sorted history with the same D-2 cutoff the
    paths use, so a row this function counts is exactly a row the filter could have
    consumed. A player never yet seen in an eligible row gets a blank, not a zero.
    """
    history = sorted(observations, key=lambda row: (row.match_date, row.match_id))
    ordered = sorted(targets, key=lambda row: (row.match.match_date, row.match.match_id))
    last_seen: dict[int, dt.date] = {}
    cursor = 0
    result: dict[str, dict[str, Any]] = {}
    for record in ordered:
        target = record.match
        cutoff = target.match_date - dt.timedelta(days=lag_days)
        while cursor < len(history) and history[cursor].match_date <= cutoff:
            item = history[cursor]
            if item.history_eligible:
                last_seen[item.player_a] = item.match_date
                last_seen[item.player_b] = item.match_date
            cursor += 1
        values: dict[str, Any] = {}
        for side, player in (("a", target.player_a), ("b", target.player_b)):
            seen = last_seen.get(player)
            values[f"dynamic_state_stale_days_{side}"] = (
                None if seen is None else (target.match_date - seen).days
            )
        pair = [values["dynamic_state_stale_days_a"], values["dynamic_state_stale_days_b"]]
        present = [value for value in pair if value is not None]
        values["dynamic_state_stale_days"] = max(present) if len(present) == 2 else None
        result[target.match_id] = values
    return result


def selection_map(
    saved_rows: Sequence[Mapping[str, str]], years: Sequence[int]
) -> tuple[dict[tuple[str, int], str], list[dict[str, Any]]]:
    saved: dict[tuple[str, int], str] = {}
    for row in saved_rows:
        key = (row["candidate_family"], int(row["selection_year"]))
        if key in saved:
            raise ChainError(f"duplicate saved selection: {key}")
        saved[key] = row["selected_candidate_id"]
    families = sorted({family for family, _ in saved})
    if not families:
        raise ChainError("saved selections file is empty")
    records: list[dict[str, Any]] = []
    resolved: dict[tuple[str, int], str] = {}
    for family in families:
        saved_years = sorted(year for other, year in saved if other == family)
        latest = max(saved_years)
        for year in years:
            if (family, year) in saved:
                candidate = saved[(family, year)]
                source, inherited = "saved", ""
            elif year > latest:
                candidate = saved[(family, latest)]
                source, inherited = "carried_forward", str(latest)
            else:
                raise ChainError(
                    f"no saved selection for {family} {year} and it is not after the "
                    f"last saved year {latest}; refusing to invent one"
                )
            resolved[(family, year)] = candidate
            records.append(
                {
                    "candidate_family": family,
                    "selection_year": year,
                    "selected_candidate_id": candidate,
                    "source": source,
                    "inherited_from_selection_year": inherited,
                }
            )
    return resolved, records


def _candidate(
    menu: Sequence[Mapping[str, Any]], candidate_id: str, label: str
) -> Mapping[str, Any]:
    for item in menu:
        if str(item["candidate_id"]) == candidate_id:
            return item
    raise ChainError(f"{label} candidate {candidate_id!r} is not in the frozen menu")


def selected_predictions(
    family: str,
    candidate_paths: Mapping[str, Sequence[Mapping[str, Any]]],
    resolved: Mapping[tuple[str, int], str],
    targets: Sequence[Any],
    annual_floor: int,
) -> list[dict[str, Any]]:
    """Parameterized ``path_runner.selected_match_predictions``.

    The only change is the ``annual_target_eligible`` floor year, which the original
    hard-codes as ``year >= 2012``.
    """
    selected = {year: candidate for (other, year), candidate in resolved.items() if other == family}
    rows_by_candidate = {
        candidate: {str(row["match_id"]): row for row in rows}
        for candidate, rows in candidate_paths.items()
    }
    output: list[dict[str, Any]] = []
    for record in sorted(targets, key=lambda row: (row.match.match_date, row.match.match_id)):
        target = record.match
        year = target.match_date.year
        if year not in selected:
            continue
        candidate_id = selected[year]
        row = rows_by_candidate[candidate_id][target.match_id]
        if target.rule is None:
            primary_match = simple_match = None
        else:
            primary_match = dynamic.match_win_probability(
                float(row["p_a_serve"]), float(row["p_b_serve"]), target.rule
            )
            simple_match = None
            if row.get("simple_p_a_serve") not in (None, "") and row.get(
                "simple_p_b_serve"
            ) not in (
                None,
                "",
            ):
                simple_match = dynamic.match_win_probability(
                    float(row["simple_p_a_serve"]), float(row["simple_p_b_serve"]), target.rule
                )
        output.append(
            {
                "match_id": target.match_id,
                "match_date": target.match_date.isoformat(),
                "source_season": record.source_season,
                "source_key": record.source_key,
                "tourney_id": target.tourney_id,
                "surface": target.surface,
                "best_of": target.best_of,
                "player_a": target.player_a,
                "player_b": target.player_b,
                "candidate_family": family,
                "selected_candidate_id": candidate_id,
                "p_a_serve": row["p_a_serve"],
                "p_b_serve": row["p_b_serve"],
                "match_probability_a": primary_match,
                "simple_match_probability_a": simple_match,
                **{
                    name: row.get(name)
                    for name in (
                        "a_logit_variance",
                        "b_logit_variance",
                        "a_b_logit_covariance",
                        "a_serve_unseen",
                        "a_return_unseen",
                        "a_surface_unseen",
                        "b_serve_unseen",
                        "b_return_unseen",
                        "b_surface_unseen",
                        "a_serve_point_observations",
                        "a_return_point_observations",
                        "a_surface_point_observations",
                        "b_serve_point_observations",
                        "b_return_point_observations",
                        "b_surface_point_observations",
                    )
                },
                "annual_target_eligible": int(
                    record.source_season == year and year >= annual_floor
                ),
                "rule_status": "provided" if target.rule is not None else "missing",
            }
        )
    return output


def _limits(revision: str) -> list[str]:
    common = [
        "The selected path and its hyperparameters are the saved 2024 selection; a "
        "target year after 2024 inherits it. No candidate was rescored or reselected.",
        "A target with no match-format rule row gets rule_status=missing and a blank "
        "match probability; JOINT04's aligned-primary cohort then excludes it.",
        "dynamic_state_stale_days* are provenance. They are in "
        "runner.py FORBIDDEN_MODEL_COLUMNS and must never be fitted.",
        "A quarantined_invalid count block is replayed as missing_all: no state "
        "update, forecast still emitted. The affected match ids are in "
        "source.quarantined_invalid_count_block_match_ids.",
    ]
    if revision == "TIER01":
        return [
            *common,
            "TIER01: the lower-tier feed enters the history observations only. It "
            "contributes no target, no fit row and no rule row, and its file carries "
            "exactly dynamic.SOURCE_ROW_FIELDS, so no outcome or price column exists in "
            "it. Lower-tier rows carry an event-anchor date shifted by tier_stream's "
            "declared offset, not a match clock.",
        ]
    return [
        *common,
        "Any label in source.relabelled_count_block_statuses is replayed as "
        "missing_all on the same declared no-update path; a partial block is a block "
        "this filter cannot consume, never a block it consumes partially.",
        "With count_history_from_year set, every earlier row is replayed as a match "
        "without counts however complete its block is, so the states are initialised "
        "at that year. The suppressed rows are counted per year and per label.",
        "years_with_a_constant_dynamic_probability lists the emitted years whose "
        "dynamic feature takes one value on every row: present and knowable, carrying "
        "no information. Training on them is a declared degradation, not a defect.",
    ]


def replay(config_path: Path, *, save_paths: bool = False) -> dict[str, Any]:
    document = read_config(resolve_under_root(config_path, label="config"))
    plan = year_plan(document)
    revision = reporting_revision(document)
    section = document.get("sr02_replay")
    if not isinstance(section, dict):
        raise ChainError("configuration has no sr02_replay object")

    primary_path = resolve_under_root(section["primary_config"]["path"], label="primary_config")
    require_hash(primary_path, section["primary_config"].get("sha256"), label="primary_config")
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
    if primary.get("proposal_status") != "frozen_for_real_execution":
        raise ChainError("SR02 primary configuration is not frozen for real execution")
    engine_binding = declared_engine_binding(primary)

    panel_entry = section.get("panel") or primary["input"]
    rules_entry = section.get("rule_mapping") or {
        "path": primary["match_conversion"]["rule_mapping_path"],
        "sha256": primary["match_conversion"]["rule_mapping_sha256"],
    }
    panel_path = resolve_under_root(panel_entry["path"], label="panel")
    rules_path = resolve_under_root(rules_entry["path"], label="rule_mapping")
    hashes = {
        "primary_config": sha256(primary_path),
        "panel": require_hash(panel_path, panel_entry.get("sha256"), label="panel"),
        "rule_mapping": require_hash(rules_path, rules_entry.get("sha256"), label="rule_mapping"),
    }
    selections_entry = section["saved_selections"]
    selections_path = resolve_under_root(selections_entry["path"], label="saved_selections")
    hashes["saved_selections"] = require_hash(
        selections_path, selections_entry.get("sha256"), label="saved_selections"
    )
    _, saved_rows = read_csv_rows(selections_path)

    source_year_min = int(section.get("source_year_min", 2005))
    source_year_max = int(section.get("source_year_max", plan.panel_end_year))
    annual_floor = int(section.get("annual_eligible_floor_year", 2012))
    selection_year_min = int(section.get("selection_year_min", min(primary["selection_years"])))
    if source_year_max != plan.panel_end_year:
        raise ChainError(
            f"sr02_replay source_year_max {source_year_max} must equal the plan's "
            f"panel_end_year {plan.panel_end_year}"
        )
    selection_years = tuple(range(selection_year_min, source_year_max + 1))
    resolved, selection_records = selection_map(saved_rows, selection_years)

    lag_days = int(primary["chronology"]["availability_lag_calendar_days"])
    relabelled_statuses = tuple(
        section.get("relabelled_count_block_statuses", DEFAULT_RELABELLED_COUNT_BLOCK_STATUSES)
    )
    count_history_from_year = section.get("count_history_from_year")
    if count_history_from_year is not None:
        count_history_from_year = int(count_history_from_year)
    observations, targets, source_summary = load_source(
        panel_path,
        rules_path,
        history_statuses=primary["chronology"]["history_statuses"],
        source_year_min=source_year_min,
        source_year_max=source_year_max,
        relabelled_statuses=relabelled_statuses,
        count_history_from_year=count_history_from_year,
    )
    declared_rows = section.get("panel_rows", panel_entry.get("panel_rows"))
    if declared_rows is not None and int(declared_rows) != len(observations):
        raise ChainError(f"panel row count differs: {len(observations)} != {declared_rows}")

    # The lower-tier feed. Appended to the history observations after the panel row
    # count has been checked, so the declared panel contract still means the panel.
    tier_section = section.get("tier_feed") or {}
    tier_enabled = bool(tier_section.get("enabled", False))
    tier_summary: dict[str, Any] | None = None
    tier_rule_basis: dict[str, Any] | None = None
    same_event_rows: list[dict[str, Any]] = []
    if tier_enabled:
        feed_path = resolve_under_root(tier_section["path"], label="tier_feed")
        hashes["tier_feed"] = require_hash(
            feed_path, tier_section.get("sha256") or None, label="tier_feed"
        )
        feed_year_min = int(tier_section.get("source_year_min", 2010))
        feed_year_max = int(tier_section.get("source_year_max", plan.panel_end_year))
        if feed_year_max != plan.panel_end_year:
            raise ChainError(
                f"tier_feed source_year_max {feed_year_max} must equal the plan's "
                f"panel_end_year {plan.panel_end_year}"
            )
        panel_tourney_ids = frozenset(item.tourney_id for item in observations)
        exclude_same_event = bool(tier_section.get("exclude_same_event_qualifying", False))
        feed_observations, tier_summary, same_event_rows = load_tier_feed(
            feed_path,
            history_statuses=primary["chronology"]["history_statuses"],
            source_year_min=feed_year_min,
            source_year_max=feed_year_max,
            panel_match_ids={item.match_id for item in observations},
            panel_tourney_ids=panel_tourney_ids,
            exclude_tourney_ids=panel_tourney_ids if exclude_same_event else frozenset(),
        )
        tier_summary["source_year_span"] = [feed_year_min, feed_year_max]
        rule_entry = tier_section["rule_config"]
        rule_config_path = resolve_under_root(rule_entry["path"], label="tier_rule_config")
        hashes["tier_rule_config"] = require_hash(
            rule_config_path, rule_entry.get("sha256") or None, label="tier_rule_config"
        )
        tier_rule_basis = tier_feed_rule_basis(rule_config_path, tier_summary)
        observations = [*observations, *feed_observations]

    # `_advance_dynamic` stops at the last target's D-2 cutoff, so history rows dated
    # after it are never consumed. The verification below compares against exactly the
    # consumable set, not against every eligible row.
    last_cutoff = max(record.match.match_date for record in targets) - dt.timedelta(days=lag_days)
    eligible_points = sum(
        (item.service_a.points_played if item.service_a is not None else 0)
        + (item.service_b.points_played if item.service_b is not None else 0)
        for item in observations
        if item.history_eligible and item.match_date <= last_cutoff
    )
    stale_rows = [
        item for item in observations if item.service_a is None and item.service_b is None
    ]

    dynamic_base = primary["dynamic_filter"]
    dynamic_menu = primary["hyperparameter_selection_proposal"]["candidate_menu"]
    control_menu = primary["unadjusted_baseline"]["selection_proposal"]["candidate_menu"]
    dynamic_ids = sorted(
        {candidate for (family, _), candidate in resolved.items() if family == "dynamic"}
    )
    control_ids = sorted(
        {candidate for (family, _), candidate in resolved.items() if family == "control"}
    )

    dynamic_paths: dict[str, list[Mapping[str, Any]]] = {}
    solver_summaries: dict[str, dict[str, Any]] = {}
    for candidate_id in dynamic_ids:
        candidate = _candidate(dynamic_menu, candidate_id, "dynamic")
        summary: dict[str, Any] = {}
        dynamic_paths[candidate_id] = path_runner.dynamic_point_path(
            observations,
            targets,
            path_runner._dynamic_config(dynamic_base, candidate),
            candidate_id,
            lag_days=lag_days,
            solver_summary=summary,
        )
        solver_summaries[candidate_id] = summary

    initial_serve_probability = 1.0 / (
        1.0 + math.exp(-float(dynamic_base["global_initial_mean_logit"]))
    )
    control_paths: dict[str, list[Mapping[str, Any]]] = {}
    for candidate_id in control_ids:
        candidate = _candidate(control_menu, candidate_id, "control")
        control_paths[candidate_id] = path_runner.control_point_path(
            observations,
            targets,
            candidate_id,
            half_life_days=float(candidate["half_life_days"]),
            overall_prior_units=float(candidate["overall_prior_units"]),
            surface_prior_units=float(candidate["surface_prior_units"]),
            initial_serve_probability=initial_serve_probability,
            lag_days=lag_days,
        )

    for candidate_id, summary in solver_summaries.items():
        if summary.get("status") != "complete":
            raise ChainError(
                f"dynamic path {candidate_id} did not complete: {summary.get('status')}"
            )
        if int(summary["service_points"]) != eligible_points:
            raise ChainError(
                "state update consumed points from ineligible rows: "
                f"{summary['service_points']} != {eligible_points}"
            )

    selected_dynamic = selected_predictions(
        "dynamic", dynamic_paths, resolved, targets, annual_floor
    )
    selected_control = selected_predictions(
        "control", control_paths, resolved, targets, annual_floor
    )
    merged = path_runner.merge_selected_matches(selected_dynamic, selected_control)
    stale = stale_days_by_target(observations, targets, lag_days)
    for row in merged:
        row.update(stale[str(row["match_id"])])

    output_dir = resolve_under_root(section["output_dir"], label="output_dir")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = (*path_runner.SELECTED_MATCH_FIELDS, *PROVENANCE_ONLY_COLUMNS)
    outputs = {
        "selected_matches.csv": atomic_csv(output_dir / "selected_matches.csv", fields, merged),
        "selection_map.csv": atomic_csv(
            output_dir / "selection_map.csv", SELECTION_MAP_FIELDS, selection_records
        ),
        "selection_carry_forward.csv": atomic_csv(
            output_dir / "selection_carry_forward.csv",
            SELECTION_MAP_FIELDS,
            [row for row in selection_records if row["source"] == "carried_forward"],
        ),
        "stale_state_rows.csv": atomic_csv(
            output_dir / "stale_state_rows.csv",
            STALE_FIELDS,
            [
                {
                    "match_id": item.match_id,
                    "match_date": item.match_date.isoformat(),
                    "source_season": "",
                    "tourney_id": item.tourney_id,
                    "player_a": item.player_a,
                    "player_b": item.player_b,
                    "count_block_status": "missing_all",
                    "status": "",
                    "identity_tier": "",
                    "history_eligible": item.history_eligible,
                    "exclusion_reason": item.exclusion_reason,
                    **stale.get(item.match_id, {}),
                }
                for item in stale_rows
            ],
        ),
    }
    if tier_rule_basis is not None:
        outputs["tier_feed_rule_basis.json"] = atomic_json(
            output_dir / "tier_feed_rule_basis.json", tier_rule_basis
        )
    if tier_summary is not None:
        # Which targets could have had their event's latent term updated by qualifying
        # counts carried under the same tourney_id. Read off the unfiltered feed, so the
        # ablated replay declares the same membership it dropped.
        membership = same_event_membership(same_event_rows, targets, lag_days)
        outputs["same_event_qualifying_membership.csv"] = atomic_csv(
            output_dir / "same_event_qualifying_membership.csv", SAME_EVENT_FIELDS, membership
        )
        tier_summary["same_event_qualifying"]["targets_with_same_event_qualifying"] = len(
            membership
        )
    if save_paths:
        for family, paths in (("dynamic", dynamic_paths), ("control", control_paths)):
            for candidate_id, rows in paths.items():
                name = f"paths/{family}/{candidate_id}/point_path.csv"
                outputs[name] = atomic_csv(output_dir / name, path_runner.PATH_FIELDS, rows)

    emitted_years = Counter(int(str(row["match_date"])[:4]) for row in merged)
    stale_ids = {item.match_id for item in stale_rows}
    stale_emitted = sum(1 for row in merged if str(row["match_id"]) in stale_ids)
    manifest: dict[str, Any] = {
        "id": "TIER01-sr02-replay" if revision == "TIER01" else "CONFIRM2026-sr02-replay",
        "status": "complete",
        "artifact_kind": "saved_selected_point_paths_advanced_no_reselection_no_outcome_scores",
        # Same top-level field names as `path_runner`'s run manifest, so the calibration
        # stage can bind a replayed point run without a second manifest contract.
        "config_sha256": hashes["primary_config"],
        "panel_sha256": hashes["panel"],
        "rule_mapping_sha256": hashes["rule_mapping"],
        "selected_matches_sha256": outputs["selected_matches.csv"],
        "year_plan": plan.as_document(),
        "source_year_span": [source_year_min, source_year_max],
        "annual_eligible_floor_year": annual_floor,
        "selection_years": list(selection_years),
        "selected_candidate_ids": {"dynamic": dynamic_ids, "control": control_ids},
        "reselection_performed": False,
        "carried_forward_selections": sum(
            1 for row in selection_records if row["source"] == "carried_forward"
        ),
        "inputs": {
            name: {"path": relative_to_root(path, label=name), "sha256": hashes[name]}
            for name, path in (
                ("primary_config", primary_path),
                ("panel", panel_path),
                ("rule_mapping", rules_path),
                ("saved_selections", selections_path),
            )
        },
        "code": {
            "replay": code_receipt(__name__),
            "dynamic": code_receipt(dynamic.__name__),
            "path_runner": code_receipt(path_runner.__name__),
            "declared_binding": engine_binding,
        },
        "source": source_summary,
        "selected_matches_rows": len(merged),
        "selected_matches_rows_by_year": dict(sorted(emitted_years.items())),
        "stale_state": {
            "panel_rows_without_serve_counts": len(stale_rows),
            "emitted_targets_without_serve_counts": stale_emitted,
            "eligible_service_points_consumed": eligible_points,
            "state_update_skipped_for_both_players": True,
            "verification": "dynamic solver service_points equals the eligible-row point total",
            "provenance_only_columns": list(PROVENANCE_ONLY_COLUMNS),
        },
        "solver_summaries": solver_summaries,
        "outputs": outputs,
        "limits": _limits(revision),
    }
    if revision == "TIER01":
        manifest["source"] = {
            key: value for key, value in source_summary.items() if key not in WTA02_SOURCE_KEYS
        }
        manifest["tier_feed"] = {
            "enabled": tier_enabled,
            **({} if tier_summary is None else tier_summary),
        }
        manifest["tier_feed_rule_basis"] = tier_rule_basis
    else:
        dispersion = dynamic_dispersion_by_year(merged)
        manifest["dynamic_dispersion_by_year"] = dispersion
        manifest["years_with_a_constant_dynamic_probability"] = [
            year for year, record in dispersion.items() if not record["informative"]
        ]
    atomic_json(output_dir / "run_manifest.json", manifest)
    return manifest


def summary_line(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """The stdout summary, in the shape of the revision the manifest was written in."""
    summary = {
        "selected_matches_rows": manifest["selected_matches_rows"],
        "selected_candidate_ids": manifest["selected_candidate_ids"],
        "carried_forward_selections": manifest["carried_forward_selections"],
        "targets_without_a_rule": manifest["source"]["targets_without_a_rule"],
        "panel_rows_without_serve_counts": manifest["stale_state"][
            "panel_rows_without_serve_counts"
        ],
        "quarantined_invalid_count_blocks_mapped_to_missing_all": manifest["source"][
            "quarantined_invalid_count_blocks_mapped_to_missing_all"
        ],
    }
    if "tier_feed" in manifest:
        summary["tier_feed_enabled"] = manifest["tier_feed"]["enabled"]
        summary["tier_feed_rows"] = manifest["tier_feed"].get("feed_rows", 0)
        summary["tier_feed_service_points_available"] = manifest["tier_feed"].get(
            "service_points_available", 0
        )
    return summary


def dry_run(config_path: Path) -> dict[str, Any]:
    """Validate the config, hashes and paths without replaying anything."""
    document = read_config(resolve_under_root(config_path, label="config"))
    plan = year_plan(document)
    reporting_revision(document)
    section = document["sr02_replay"]
    primary_path = resolve_under_root(section["primary_config"]["path"], label="primary_config")
    require_hash(primary_path, section["primary_config"].get("sha256"), label="primary_config")
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
    declared_engine_binding(primary)
    for name in ("panel", "rule_mapping", "saved_selections"):
        entry = section.get(name)
        if entry is None:
            continue
        path = resolve_under_root(entry["path"], label=name)
        require_hash(path, entry.get("sha256"), label=name)
    feed = section.get("tier_feed") or {}
    if feed.get("enabled"):
        for label, entry in (("tier_feed", feed), ("tier_rule_config", feed["rule_config"])):
            path = resolve_under_root(entry["path"], label=label)
            require_hash(path, entry.get("sha256") or None, label=label)
    return {"status": "dry_run_ok", "year_plan": plan.as_document()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--save-paths", action="store_true", help="also write the two point paths")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate the config, hashes and paths only"
    )
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps(dry_run(args.config), sort_keys=True))
        return 0
    manifest = replay(args.config, save_paths=args.save_paths)
    print(json.dumps(summary_line(manifest), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
