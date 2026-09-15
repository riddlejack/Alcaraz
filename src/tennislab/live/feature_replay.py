"""Exact, outcome-free live feature replay for the accepted trained rungs.

The live history binding is an accepted corrected panel augmented with availability
bounds.  ``model_event_date`` preserves the panel's reported-date chronology while the
completion/publication/receipt fields decide whether the row is knowable at issue time.
The prospective fixture is never assigned a result, status, score, price or serve count.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    canonical_hash,
    code_receipt,
    relative_to_root,
    require_hash,
    resolve_under_root,
)
from tennislab.chronology.ranking_lookup import RankingLookup
from tennislab.dynamics import dynamic, path_runner
from tennislab.features import base, sidecar
from tennislab.live.common import LiveConfig, LiveError, parse_utc
from tennislab.models import pipeline, release
from tennislab.ratings import elo, tier_elo


class ReplayUnavailable(LiveError):
    """A declared, exact replay input is not bound yet."""


MODEL_EVENT_DATE = "model_event_date"
BOUND_FIELDS = (
    "date_basis",
    "completion_upper_bound",
    "completion_basis",
    "publication_upper_bound_utc",
    "receipt_time_utc",
    "overlap_unresolved",
)
PANEL_TRAIT_FIELDS = {
    "a_height_cm",
    "b_height_cm",
    "a_hand",
    "b_hand",
    "source_key",
    "source_member",
    "source_line_number",
    "source_row_number",
}
PANEL_FIELDS = frozenset(
    {"tour", *base.REQUIRED_PANEL_FIELDS, *PANEL_TRAIT_FIELDS, MODEL_EVENT_DATE, *BOUND_FIELDS}
)
HISTORY_STATUSES = frozenset({"completed", "retired"})
FORBIDDEN_FIXTURE_FIELDS = frozenset(
    {
        "a_won",
        "winner",
        "loser",
        "winner_id",
        "loser_id",
        "winner_name",
        "loser_name",
        "winner_side",
        "score",
        "result",
        "sets",
        "status",
        "outcome",
        "minutes",
    }
)
FORBIDDEN_FIXTURE_PREFIXES = (
    "a_1st",
    "b_1st",
    "a_2nd",
    "b_2nd",
    "a_svpt",
    "b_svpt",
    "a_ace",
    "b_ace",
    "a_df",
    "b_df",
    "a_bp",
    "b_bp",
)

# These are the saved SR02 choices used by the accepted ATP and WTA full bundles.  A
# post-2024 target inherits the saved choice; no candidate is rescored or selected here.
DYNAMIC_BASE = {
    "global_initial_mean_logit": 0.5,
    "surface_process_sd_per_60_days": 0.0,
    "solver_gradient_tolerance": 1e-6,
    "solver_max_iterations": 50,
    "solver_newton_decrement_tolerance": 1e-7,
}
DYNAMIC_CANDIDATE = {
    "candidate_id": "q020_g040_tight",
    "global_initial_sd": 0.08,
    "role_initial_sd": 0.15,
    "role_process_sd_per_60_days": 0.02,
    "shared_surface_initial_sd": 0.04,
    "surface_mean_initial_sd": 0.05,
    "tournament_initial_sd": 0.04,
}
CONTROL_CANDIDATE = {
    "candidate_id": "h365_o250_s250",
    "half_life_days": 365.0,
    "overall_prior_units": 250.0,
    "surface_prior_units": 250.0,
}
SELECTION_RECEIPT_SHA256 = "7740d54723b33ec2c65d09a61e0d43381631e7814498a130e501d2d5b3b8d87c"
PRIMARY_DYNAMIC_CONFIG_SHA256 = "36dce886e5f09f5c3f7a8b4449baf03da49905f0ea7b45a5c6116a0cc5116182"
SELECTION_MAP_SHA256 = "a85e713815d55921ac4b0ca2808644c2dd2b3f59601d0ebca8b1072124d54525"


@dataclass(frozen=True)
class QualifiedPanel:
    rows: tuple[dict[str, str], ...]
    records: tuple[base.Record, ...]
    sha256: str
    path: Path
    withheld: dict[str, int]


@dataclass(frozen=True)
class NeutralEloTarget:
    """The target view consumed by ``ratings.elo.replay``; it has no outcome."""

    date: dt.date
    surface: str
    best_of: int
    player_a: elo.PlayerKey
    player_b: elo.PlayerKey
    a_won: None = None


def _binding_pending(value: object) -> bool:
    return value in (None, "", "PENDING")


def _input_review_binding(
    config: LiveConfig, tour: str, *, issue_time: dt.datetime | None = None
) -> dict[str, Any]:
    entry = config.document.get("feature_replay", {}).get("input_review_receipt")
    if not isinstance(entry, dict) or _binding_pending(entry.get("path")):
        raise ReplayUnavailable("feature_replay.input_review_receipt is PENDING")
    if (
        _binding_pending(entry.get("sha256"))
        or _binding_pending(entry.get("checked_utc"))
        or _binding_pending(entry.get("input_manifest_path"))
    ):
        raise ReplayUnavailable("feature_replay.input_review_receipt is incomplete")
    path = resolve_under_root(str(entry["path"]), label="D101 input review receipt")
    digest = require_hash(path, str(entry["sha256"]), label="D101 input review receipt")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS":
        raise LiveError("D101 input review receipt is not PASS")
    if receipt.get("checked_utc") != entry["checked_utc"]:
        raise LiveError("D101 input review timestamp differs from its binding")
    if receipt.get("manifest_sha256") != entry.get("input_manifest_sha256"):
        raise LiveError("D101 input manifest hash differs from its review receipt")
    manifest_path = resolve_under_root(
        str(entry["input_manifest_path"]), label="D101 input manifest"
    )
    manifest_sha = require_hash(
        manifest_path, str(entry["input_manifest_sha256"]), label="D101 input manifest"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviewed_history = manifest.get("history_candidates", {}).get(tour, {})
    history_binding = config.section("history").get(tour, {})
    if history_binding.get("sha256") != reviewed_history.get("sha256"):
        raise LiveError(f"{tour} history binding differs from the reviewed D101 manifest")
    route = config.document.get("feature_replay", {}).get(tour, {})
    direct_ranking = route.get("ranking_source")
    reviewed_ranking = manifest.get("rankings", {}).get(tour, {})
    if (
        isinstance(direct_ranking, dict)
        and not _binding_pending(direct_ranking.get("path"))
        and direct_ranking.get("sha256") != reviewed_ranking.get("sha256")
    ):
        raise LiveError(f"{tour} ranking binding differs from the reviewed D101 manifest")
    identity = config.section("identity")
    if (
        not _binding_pending(identity.get("players_csv"))
        and not _binding_pending(identity.get("players_sha256"))
        and identity.get("players_sha256") != manifest.get("players_candidate", {}).get("sha256")
    ):
        raise LiveError("BIO player binding differs from the reviewed D101 manifest")
    if tour == "ATP":
        reviewed_tier = manifest.get("atp_lower_tier_inputs", {})
        for name in ("tier_results", "tier_source_rows"):
            bound = route.get(name)
            if (
                isinstance(bound, dict)
                and not _binding_pending(bound.get("path"))
                and bound.get("sha256") != reviewed_tier.get(name, {}).get("sha256")
            ):
                raise LiveError(f"ATP {name} binding differs from the reviewed D101 manifest")
    checked = parse_utc(str(entry["checked_utc"]), label="D101 input review")
    if issue_time is not None and checked > issue_time:
        raise ReplayUnavailable("D101 replay inputs were reviewed after forecast issue time")
    return {
        "path": relative_to_root(path, label="D101 input review receipt"),
        "sha256": digest,
        "checked_utc": entry["checked_utc"],
        "input_manifest_path": relative_to_root(manifest_path, label="D101 input manifest"),
        "input_manifest_sha256": manifest_sha,
    }


def _history_entry(config: LiveConfig, tour: str) -> tuple[Path, str, dict[str, Any]]:
    entry = config.section("history").get(tour)
    if not isinstance(entry, dict) or _binding_pending(entry.get("results_csv")):
        raise ReplayUnavailable(f"history binding for {tour} is PENDING")
    path = resolve_under_root(str(entry["results_csv"]), label=f"{tour} model panel")
    if not path.is_file():
        raise ReplayUnavailable(f"{tour} model panel not found: {path}")
    digest = entry.get("sha256")
    if _binding_pending(digest):
        raise ReplayUnavailable(f"history binding for {tour} has no sha256")
    observed = require_hash(path, str(digest), label=f"{tour} model panel")
    bases = entry.get("admissible_completion_bases")
    if not isinstance(bases, list) or not bases:
        raise ReplayUnavailable(f"history binding for {tour} has no completion-basis allowlist")
    return path, observed, entry


def _qualified(
    row: Mapping[str, str],
    *,
    admitted_bases: set[str],
    cutoff: dt.date,
    issue_time: dt.datetime,
    index: int,
    label: str,
) -> str | None:
    unresolved = row["overlap_unresolved"].strip().lower()
    if unresolved not in {"true", "false"}:
        raise LiveError(f"{label} row {index} has invalid overlap_unresolved {unresolved!r}")
    completion_text = row["completion_upper_bound"].strip()
    if unresolved == "true" or not completion_text:
        return "overlap_unresolved"
    if row["completion_basis"].strip() not in admitted_bases:
        return "completion_basis_not_admissible"
    try:
        completion = dt.date.fromisoformat(completion_text)
    except ValueError as error:
        raise LiveError(f"{label} row {index} has invalid completion_upper_bound") from error
    modeled_text = (
        row.get(MODEL_EVENT_DATE, "").strip()
        or row.get("match_date", "").strip()
        or row.get("date", "").strip()
    )
    if modeled_text:
        try:
            modeled_event = dt.date.fromisoformat(modeled_text)
        except ValueError as error:
            raise LiveError(f"{label} row {index} has invalid modeled event date") from error
        if modeled_event > completion:
            raise LiveError(
                f"{label} row {index} has modeled event date after completion upper bound"
            )
    if completion > cutoff:
        return "after_cutoff"
    if parse_utc(row["publication_upper_bound_utc"], label=f"{label} publication") > issue_time:
        return "published_after_issue"
    if parse_utc(row["receipt_time_utc"], label=f"{label} receipt") > issue_time:
        return "received_after_issue"
    return None


def qualified_panel(
    config: LiveConfig,
    tour: str,
    *,
    cutoff: dt.date,
    issue_time: dt.datetime,
) -> QualifiedPanel:
    """Load the hash-bound accepted panel without replacing its modeled event date."""

    path, digest, entry = _history_entry(config, tour)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or ())
        missing = sorted(PANEL_FIELDS - header)
        if missing:
            raise ReplayUnavailable(f"{tour} model panel lacks exact replay columns {missing}")
        input_rows = [dict(row) for row in reader]
    admitted = {str(value) for value in entry["admissible_completion_bases"]}
    rows: list[dict[str, str]] = []
    records: list[base.Record] = []
    withheld: Counter[str] = Counter()
    seen: set[str] = set()
    for index, row in enumerate(input_rows, 2):
        if row.get("tour", "").strip().upper() != tour:
            withheld["other_tour"] += 1
            continue
        reason = _qualified(
            row,
            admitted_bases=admitted,
            cutoff=cutoff,
            issue_time=issue_time,
            index=index,
            label=f"{tour} model panel",
        )
        if reason:
            withheld[reason] += 1
            continue
        event_date = row[MODEL_EVENT_DATE].strip()
        try:
            parsed_event_date = dt.date.fromisoformat(event_date)
        except ValueError as error:
            raise LiveError(
                f"{tour} model panel row {index} has invalid model_event_date"
            ) from error
        if event_date != row["match_date"].strip():
            raise LiveError(
                f"{tour} model panel row {index} changes accepted chronology: "
                f"model_event_date {event_date!r} != match_date {row['match_date']!r}"
            )
        if parsed_event_date > cutoff:
            withheld["model_event_after_cutoff"] += 1
            continue
        if row["match_id"] in seen:
            raise LiveError(f"{tour} model panel has duplicate match_id {row['match_id']!r}")
        seen.add(row["match_id"])
        if row["status"] not in HISTORY_STATUSES:
            withheld["not_model_history_status"] += 1
            continue
        parsed, rejected = base.parse_record(row, 1900, max(2100, parsed_event_date.year))
        if rejected:
            withheld[f"panel_rejection:{rejected}"] += 1
            continue
        if parsed is None:
            raise LiveError(f"{tour} model panel row {index} parsed to no record")
        rows.append(row)
        records.append(parsed)
    if not records:
        raise ReplayUnavailable(f"{tour} model panel has no eligible replay records")
    return QualifiedPanel(tuple(rows), tuple(records), digest, path, dict(sorted(withheld.items())))


def _fixture_record(fixture: Mapping[str, Any]) -> base.Record:
    forbidden = sorted(
        key
        for key, value in fixture.items()
        if value not in (None, "")
        and (key in FORBIDDEN_FIXTURE_FIELDS or key.startswith(FORBIDDEN_FIXTURE_PREFIXES))
    )
    if forbidden:
        raise LiveError(f"trained feature replay fixture carries outcome/stat fields {forbidden}")
    date = dt.date.fromisoformat(str(fixture["scheduled_start_local_date"]))
    player_a = int(fixture["player_a_id"])
    player_b = int(fixture["player_b_id"])
    if player_a >= player_b:
        raise LiveError("trained feature replay requires neutral player_a < player_b")
    return base.Record(
        match_id=str(fixture["fixture_id"]),
        match_date=date,
        calendar_year=date.year,
        source_season=date.year,
        tourney_id=str(fixture["event_id"]),
        tourney_name=str(fixture["event_name"]),
        tourney_level=str(fixture["level"]),
        competition_type="individual_tour",
        round=str(fixture["round"]),
        surface=str(fixture["surface"]),
        best_of=int(fixture["best_of"]),
        court_recorded="",
        player_a=player_a,
        player_b=player_b,
        a_won=None,
        identity_tier="primary",
        status="prospective",
        date_basis="sourced_scheduled_start_local_date",
        archive_date_basis="prospective_fixture_no_result",
        source_field_agreement=True,
        counts_a=None,
        counts_b=None,
        ps_probability_a=None,
    )


def _ranking_lookup(
    config: LiveConfig,
    version: Mapping[str, Any],
    tour: str,
    *,
    issue_time: dt.datetime,
) -> RankingLookup:
    route = config.document.get("feature_replay", {}).get(tour, {})
    source = route.get("ranking_source")
    index = route.get("ranking_index")
    if (
        isinstance(source, dict)
        and isinstance(index, dict)
        and not _binding_pending(source.get("path"))
    ):
        if (
            _binding_pending(source.get("sha256"))
            or _binding_pending(index.get("path"))
            or _binding_pending(index.get("sha256"))
        ):
            raise ReplayUnavailable(f"{tour} direct ranking binding is incomplete")
        available = source.get("available_upper_bound_utc")
        if _binding_pending(available):
            raise ReplayUnavailable(f"{tour} direct ranking binding has no availability bound")
        if parse_utc(str(available), label=f"{tour} ranking availability") > issue_time:
            raise ReplayUnavailable(f"{tour} ranking source was not available by issue time")
        source_path = resolve_under_root(str(source["path"]), label=f"{tour} ranking source")
        index_path = resolve_under_root(str(index["path"]), label=f"{tour} ranking index")
        require_hash(index_path, str(index["sha256"]), label=f"{tour} ranking index")
        return RankingLookup.from_gzip(
            source_path,
            edition_index_path=index_path,
            expected_source_sha256=str(source["sha256"]),
        )

    receipts = {
        f"{source}/{binding['attempt_id']}": binding["finished_utc"]
        for source, binding in version["manifest"]["acquisition_receipts"].items()
    }
    rows: list[dict[str, str]] = []
    for index, row in enumerate(version["rankings"], 2):
        if row["tour"] != tour:
            continue
        received = receipts.get(row["receipt_id"])
        if received is None or parse_utc(received, label="ranking receipt") > issue_time:
            continue
        rows.append(
            {
                "effective_date": row["ranking_date"],
                "rank": row["rank"],
                "player_id": row["player_id"],
                "ranking_points": row["points"],
                "source_member": f"live:{version['manifest']['version_id']}:rankings.csv",
                "source_physical_line": str(index),
            }
        )
    if not rows:
        raise ReplayUnavailable(f"snapshot has no receipt-qualified {tour} ranking edition")
    return RankingLookup.from_rows(rows)


def _base_feature(
    panel: QualifiedPanel,
    target: base.Record,
    ranking_lookup: RankingLookup,
) -> dict[str, Any]:
    """Advance the exact chain state, omitting unused historical target-row emission."""

    parameters = base.FIXED_PARAMETERS
    sources = sorted(
        (record for record in panel.records if record.identity_tier == base.PRIMARY_TIER),
        key=base.Record.order_key,
    )
    sports_elo = base.EloHistory(
        float(parameters["elo_initial_rating"]),
        float(parameters["elo_k"]),
        float(parameters["elo_scale"]),
    )
    market_elo = base.EloHistory(
        float(parameters["elo_initial_rating"]),
        float(parameters["elo_k"]),
        float(parameters["elo_scale"]),
    )
    counts = base.CountHistory(
        float(parameters["count_half_life_days"]),
        float(parameters["count_prior_denominator_units"]),
        float(parameters["initial_serve_rate"]),
        float(parameters["initial_return_rate"]),
    )
    workload = base.WorkloadHistory()
    lag = int(parameters["lag_calendar_days"])
    cutoff = target.match_date - dt.timedelta(days=lag)
    # CountHistory applies decay on every historical target date, and adds a newly
    # eligible source with a weight relative to that date.  Visit the native panel
    # dates in exactly the same order as ``base.stream_rows`` even though only the
    # prospective row is emitted.  Availability dates never enter this timeline.
    target_dates = sorted({record.match_date for record in panel.records} | {target.match_date})
    cursor = 0
    for target_date in target_dates:
        if target_date > target.match_date:
            break
        counts.advance(target_date)
        date_cutoff = target_date - dt.timedelta(days=lag)
        while cursor < len(sources) and sources[cursor].match_date <= date_cutoff:
            source_date = sources[cursor].match_date
            end = cursor + 1
            while end < len(sources) and sources[end].match_date == source_date:
                end += 1
            batch = sources[cursor:end]
            sports_elo.apply_batch(batch, pseudo_outcome=False)
            market_elo.apply_batch(batch, pseudo_outcome=True)
            for record in batch:
                counts.add_match(record, target_date)
                workload.add_match(record)
            cursor = end
    rank_a, rank_b = ranking_lookup.lookup_many(
        [(target.match_date, target.player_a), (target.match_date, target.player_b)]
    )
    return base.build_feature_row(
        target,
        cutoff,
        sports_elo,
        counts,
        workload,
        market_elo,
        rank_a,
        rank_b,
        tuple(int(value) for value in parameters["workload_windows_days"]),
        int(parameters["rest_days_cap"]),
    )


def _target_panel_row(target: base.Record) -> dict[str, str]:
    row = {field: "" for field in PANEL_FIELDS}
    row.update(
        {
            "match_id": target.match_id,
            "match_date": target.match_date.isoformat(),
            MODEL_EVENT_DATE: target.match_date.isoformat(),
            "source_season": str(target.source_season),
            "tourney_id": target.tourney_id,
            "tourney_name": target.tourney_name,
            "tourney_level": target.tourney_level,
            "competition_type": target.competition_type,
            "round": target.round,
            "surface": target.surface,
            "best_of": str(target.best_of),
            "player_a": str(target.player_a),
            "player_b": str(target.player_b),
            "a_entity_id": str(target.player_a),
            "b_entity_id": str(target.player_b),
            "identity_tier": "primary",
            "source_key": target.match_id,
            "source_member": "prospective_fixture",
            "source_line_number": "1",
            "source_row_number": "1",
            "date_basis": target.date_basis,
            "archive_date_basis": target.archive_date_basis,
            "source_field_agreement": "true",
        }
    )
    return row


def _normalized_event(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().replace(".", " ").replace("-", " ").split())


def _mapped_match_rule(
    config: LiveConfig,
    panel: QualifiedPanel,
    fixture: Mapping[str, Any],
    *,
    tour: str,
) -> tuple[dynamic.MatchRule, dict[str, Any]] | None:
    binding = config.document.get("feature_replay", {}).get(tour, {}).get("rule_mapping")
    if not isinstance(binding, dict) or _binding_pending(binding.get("path")):
        return None
    if _binding_pending(binding.get("sha256")):
        raise ReplayUnavailable(f"{tour} rule mapping binding is incomplete")
    path = resolve_under_root(str(binding["path"]), label=f"{tour} rule mapping")
    digest = require_hash(path, str(binding["sha256"]), label=f"{tour} rule mapping")
    panel_by_source = {row["source_key"]: row for row in panel.rows}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "source_key",
            "tourney_id",
            "round",
            "best_of",
            "rule_group",
            "rule_basis",
            "match_rule",
        }
        missing = sorted(required - set(reader.fieldnames or ()))
        if missing:
            raise ReplayUnavailable(f"{tour} rule mapping lacks columns {missing}")
        joined = [(dict(row), panel_by_source.get(row["source_key"])) for row in reader]
    event_id = str(fixture["event_id"])
    exact = [(row, meta) for row, meta in joined if row["tourney_id"] == event_id and meta]
    matched_by = "event_id"
    candidates = exact
    if not candidates:
        event_name = _normalized_event(fixture["event_name"])
        candidates = [
            (row, meta)
            for row, meta in joined
            if meta and _normalized_event(meta["tourney_name"]) == event_name
        ]
        matched_by = "event_name"
    best_of = str(fixture["best_of"])
    candidates = [(row, meta) for row, meta in candidates if row["best_of"] == best_of]
    exact_round = [(row, meta) for row, meta in candidates if row["round"] == fixture["round"]]
    if exact_round:
        candidates = exact_round
        matched_by += "+round"
    rules = {(row["match_rule"], row["rule_group"], row["rule_basis"]) for row, _ in candidates}
    if not rules:
        return None
    if len(rules) != 1:
        raise ReplayUnavailable(
            f"{tour} accepted rule mapping is ambiguous for fixture {fixture['fixture_id']}"
        )
    rule_text, group, basis = next(iter(rules))
    try:
        rule = dynamic.MatchRule.from_mapping(json.loads(rule_text))
    except (TypeError, ValueError, dynamic.DynamicsError) as error:
        raise LiveError(f"{tour} accepted rule mapping is invalid: {error}") from error
    return rule, {
        "resolution": "accepted_rule_mapping",
        "matched_by": matched_by,
        "rule_group": group,
        "rule_basis": basis,
        "path": relative_to_root(path, label=f"{tour} rule mapping"),
        "sha256": digest,
    }


def _match_rule(
    config: LiveConfig,
    panel: QualifiedPanel,
    fixture: Mapping[str, Any],
    *,
    tour: str,
) -> tuple[dynamic.MatchRule, dict[str, Any]]:
    mapped = _mapped_match_rule(config, panel, fixture, tour=tour)
    value = fixture.get("match_rule")
    source = str(fixture.get("match_rule_source", "")).strip()
    if mapped is not None:
        rule, lineage = mapped
        if 2 * rule.sets_to_win - 1 != int(fixture["best_of"]):
            raise LiveError("accepted rule mapping sets_to_win disagrees with best_of")
        if isinstance(value, dict):
            try:
                explicit = dynamic.MatchRule.from_mapping(value)
            except (TypeError, ValueError, dynamic.DynamicsError) as error:
                raise LiveError(f"fixture match_rule is invalid: {error}") from error
            if explicit != rule:
                raise LiveError("fixture match_rule conflicts with the accepted rule mapping")
        return rule, lineage
    if not isinstance(value, dict) or not source:
        raise ReplayUnavailable(
            "full feature replay needs an accepted rule-map match or explicit sourced match_rule"
        )
    try:
        rule = dynamic.MatchRule.from_mapping(value)
    except (TypeError, ValueError, dynamic.DynamicsError) as error:
        raise LiveError(f"fixture match_rule is invalid: {error}") from error
    expected_best_of = 2 * rule.sets_to_win - 1
    if expected_best_of != int(fixture["best_of"]):
        raise LiveError("fixture match_rule sets_to_win disagrees with best_of")
    return rule, {"resolution": "explicit_sourced_fixture_field", "source": source}


def _observations(
    rows: Iterable[Mapping[str, str]], *, tour: str
) -> list[dynamic.HistoryObservation]:
    observations = []
    for row in rows:
        adapted = dict(row)
        if adapted["count_block_status"] != "usable":
            adapted["count_block_status"] = "missing_all"
        if tour == "WTA" and int(adapted["match_date"][:4]) < 2016:
            adapted["count_block_status"] = "missing_all"
        observations.append(
            dynamic.observation_from_source_row(
                adapted, history_statuses=("completed", "retired", "default")
            )
        )
    return observations


def _dynamic_binding(config: LiveConfig, tour: str, target_year: int) -> dict[str, Any]:
    """Verify the shared SR02 contract and each tour's accepted carry-forward receipt."""

    replay = config.document.get("feature_replay", {})
    contract = replay.get("dynamic_contract")
    if not isinstance(contract, dict):
        raise ReplayUnavailable("feature_replay.dynamic_contract is PENDING")
    files: dict[str, tuple[Path, str]] = {}
    for name, expected in (
        ("primary_config", PRIMARY_DYNAMIC_CONFIG_SHA256),
        ("saved_selections", SELECTION_RECEIPT_SHA256),
    ):
        entry = contract.get(name)
        if not isinstance(entry, dict) or _binding_pending(entry.get("path")):
            raise ReplayUnavailable(f"feature_replay.dynamic_contract.{name} is PENDING")
        if entry.get("sha256") != expected:
            raise LiveError(f"feature_replay.dynamic_contract.{name} has the wrong accepted hash")
        path = resolve_under_root(str(entry["path"]), label=f"dynamic {name}")
        files[name] = (path, require_hash(path, expected, label=f"dynamic {name}"))

    source = json.loads(files["primary_config"][0].read_text(encoding="utf-8"))
    observed_base = {name: source["dynamic_filter"][name] for name in DYNAMIC_BASE}
    dynamic_candidates = source["hyperparameter_selection_proposal"]["candidate_menu"]
    observed_dynamic = next(
        (
            row
            for row in dynamic_candidates
            if row["candidate_id"] == DYNAMIC_CANDIDATE["candidate_id"]
        ),
        None,
    )
    control_candidates = source["unadjusted_baseline"]["selection_proposal"]["candidate_menu"]
    observed_control = next(
        (
            row
            for row in control_candidates
            if row["candidate_id"] == CONTROL_CANDIDATE["candidate_id"]
        ),
        None,
    )
    if observed_dynamic is not None:
        observed_dynamic = {name: observed_dynamic[name] for name in DYNAMIC_CANDIDATE}
    if observed_control is not None:
        observed_control = {name: observed_control[name] for name in CONTROL_CANDIDATE}
    if observed_base != DYNAMIC_BASE or observed_dynamic != DYNAMIC_CANDIDATE:
        raise LiveError("accepted dynamic configuration differs from the live replay constants")
    if observed_control != CONTROL_CANDIDATE:
        raise LiveError("accepted control configuration differs from the live replay constants")

    with files["saved_selections"][0].open(newline="", encoding="utf-8") as handle:
        saved = [dict(row) for row in csv.DictReader(handle)]
    expected_ids = {
        "dynamic": DYNAMIC_CANDIDATE["candidate_id"],
        "control": CONTROL_CANDIDATE["candidate_id"],
    }
    saved_2024 = {
        row["candidate_family"]: row["selected_candidate_id"]
        for row in saved
        if row["selection_year"] == "2024"
    }
    if saved_2024 != expected_ids:
        raise LiveError("accepted 2024 SR02 saved selections differ from the replay candidates")

    selection_entry = replay.get(tour, {}).get("selection_map")
    if not isinstance(selection_entry, dict) or _binding_pending(selection_entry.get("path")):
        raise ReplayUnavailable(f"feature_replay.{tour}.selection_map is PENDING")
    if selection_entry.get("sha256") != SELECTION_MAP_SHA256:
        raise LiveError(f"feature_replay.{tour}.selection_map has the wrong accepted hash")
    selection_path = resolve_under_root(str(selection_entry["path"]), label=f"{tour} selection map")
    selection_sha = require_hash(
        selection_path, SELECTION_MAP_SHA256, label=f"{tour} selection map"
    )
    with selection_path.open(newline="", encoding="utf-8") as handle:
        mapped = [dict(row) for row in csv.DictReader(handle)]
    target_selection = {
        row["candidate_family"]: row for row in mapped if row["selection_year"] == str(target_year)
    }
    if {key: row["selected_candidate_id"] for key, row in target_selection.items()} != expected_ids:
        raise ReplayUnavailable(
            f"{tour} selection map has no accepted candidates for {target_year}"
        )
    if target_year > 2024 and any(
        row["source"] != "carried_forward" or row["inherited_from_selection_year"] != "2024"
        for row in target_selection.values()
    ):
        raise LiveError(f"{tour} post-2024 selection map is not the accepted 2024 carry-forward")
    return {
        "primary_config": {
            "path": relative_to_root(files["primary_config"][0], label="dynamic primary config"),
            "sha256": files["primary_config"][1],
        },
        "saved_selections": {
            "path": relative_to_root(
                files["saved_selections"][0], label="dynamic saved selections"
            ),
            "sha256": files["saved_selections"][1],
        },
        "selection_map": {
            "path": relative_to_root(selection_path, label=f"{tour} selection map"),
            "sha256": selection_sha,
            "selection_year": target_year,
            "selected": expected_ids,
            "source": "carried_forward_from_2024" if target_year > 2024 else "saved",
        },
        "operation": "fixed_hyperparameter_state_assimilation_no_fit_no_selection",
    }


def _dynamic_row(
    panel_rows: Sequence[Mapping[str, str]],
    target: base.Record,
    rule: dynamic.MatchRule,
    *,
    tour: str,
    extra_observations: Sequence[dynamic.HistoryObservation] = (),
) -> tuple[dict[str, str], dict[str, Any]]:
    target_match = dynamic.TargetMatch(
        target.match_id,
        target.match_date,
        target.tourney_id,
        target.surface,
        target.best_of,
        target.player_a,
        target.player_b,
        rule,
    )
    path_target = path_runner.PathTarget(target_match, target.source_season, target.match_id)
    observations = [*_observations(panel_rows, tour=tour), *extra_observations]
    solver: dict[str, Any] = {}
    dynamic_rows = path_runner.dynamic_point_path(
        observations,
        [path_target],
        path_runner._dynamic_config(DYNAMIC_BASE, DYNAMIC_CANDIDATE),
        DYNAMIC_CANDIDATE["candidate_id"],
        lag_days=2,
        solver_summary=solver,
    )
    initial_serve = 1.0 / (1.0 + math.exp(-DYNAMIC_BASE["global_initial_mean_logit"]))
    control_rows = path_runner.control_point_path(
        observations,
        [path_target],
        CONTROL_CANDIDATE["candidate_id"],
        half_life_days=CONTROL_CANDIDATE["half_life_days"],
        overall_prior_units=CONTROL_CANDIDATE["overall_prior_units"],
        surface_prior_units=CONTROL_CANDIDATE["surface_prior_units"],
        initial_serve_probability=initial_serve,
        lag_days=2,
    )
    selections = [
        {
            "selection_year": target.match_date.year,
            "selected_candidate_id": DYNAMIC_CANDIDATE["candidate_id"],
        }
    ]
    controls = [
        {
            "selection_year": target.match_date.year,
            "selected_candidate_id": CONTROL_CANDIDATE["candidate_id"],
        }
    ]
    selected_dynamic = path_runner.selected_match_predictions(
        "dynamic", {DYNAMIC_CANDIDATE["candidate_id"]: dynamic_rows}, selections, [path_target]
    )
    selected_control = path_runner.selected_match_predictions(
        "control", {CONTROL_CANDIDATE["candidate_id"]: control_rows}, controls, [path_target]
    )
    merged = path_runner.merge_selected_matches(selected_dynamic, selected_control)[0]
    serialized = {key: path_runner._serialize(value) for key, value in merged.items()}
    return serialized, solver


def _bio_rows(config: LiveConfig, tour: str) -> tuple[list[dict[str, str]], str, Path]:
    entry = config.section("identity")
    path_value = entry.get("players_csv")
    digest = entry.get("players_sha256")
    if _binding_pending(path_value) or _binding_pending(digest):
        raise ReplayUnavailable("full feature replay needs a hash-bound identity.players_csv")
    path = resolve_under_root(str(path_value), label="bio player table")
    if not path.is_file():
        raise ReplayUnavailable(f"bio player table not found: {path}")
    observed = require_hash(path, str(digest), label="bio player table")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or ())
        missing = sorted({"tour", "player_id", "dob"} - header)
        if missing:
            raise ReplayUnavailable(f"bio player table lacks columns {missing}")
        rows = [
            {"player_id": row["player_id"], "dob": row["dob"]}
            for row in reader
            if row["tour"].strip().upper() == tour
        ]
    if not rows:
        raise ReplayUnavailable(f"bio player table has no {tour} rows")
    return rows, observed, path


def _sidecar_row(
    config: LiveConfig,
    panel: QualifiedPanel,
    target: base.Record,
    feature: Mapping[str, Any],
    selected: Mapping[str, str],
    *,
    tour: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    players, players_sha, players_path = _bio_rows(config, tour)
    target_panel = _target_panel_row(target)
    outputs, _, _, summary = sidecar.build_sidecar_rows(
        [{field: str(feature[field]) for field in sidecar.BASE_KEYS}],
        [*panel.rows, target_panel],
        players,
        [selected],
        relative_to_root(players_path, label="bio player table"),
    )
    # The accepted pipeline consumes the sidecar as CSV text.  Preserve that public
    # interface here rather than handing its parsers Python ints from the in-memory
    # builder result.
    serialized = {key: "" if value is None else str(value) for key, value in outputs[0].items()}
    return serialized, {"players_sha256": players_sha, "summary": summary}


def _read_bound_gzip(
    config: LiveConfig,
    *,
    name: str,
    cutoff: dt.date,
    issue_time: dt.datetime,
    required: set[str],
) -> tuple[list[dict[str, str]], str, Path, dict[str, int]]:
    route = config.document.get("feature_replay", {}).get("ATP", {})
    binding = route.get(name)
    if not isinstance(binding, dict) or _binding_pending(binding.get("path")):
        raise ReplayUnavailable(f"ATP full-tier replay binding {name} is PENDING")
    path = resolve_under_root(str(binding["path"]), label=name)
    digest = binding.get("sha256")
    if _binding_pending(digest):
        raise ReplayUnavailable(f"ATP full-tier replay binding {name} has no sha256")
    observed = require_hash(path, str(digest), label=name)
    admitted = set(binding.get("admissible_completion_bases") or ())
    if not admitted:
        raise ReplayUnavailable(f"ATP full-tier replay binding {name} has no basis allowlist")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or ())
        missing = sorted(required - header)
        if missing:
            raise ReplayUnavailable(f"{name} lacks exact replay columns {missing}")
        source = [dict(row) for row in reader]
    row_bound = {MODEL_EVENT_DATE, *BOUND_FIELDS}.issubset(header)
    if not row_bound:
        file_bound_fields = {
            "completion_upper_bound",
            "completion_basis",
            "publication_upper_bound_utc",
            "receipt_time_utc",
        }
        absent = sorted(
            field for field in file_bound_fields if _binding_pending(binding.get(field))
        )
        if absent:
            raise ReplayUnavailable(f"{name} lacks row bounds and binding fields {absent}")
    rows: list[dict[str, str]] = []
    withheld: Counter[str] = Counter()
    for index, row in enumerate(source, 2):
        date_field = "match_date" if "match_date" in row else "date"
        if not row_bound:
            row.update(
                {
                    MODEL_EVENT_DATE: row[date_field],
                    "date_basis": str(binding.get("date_basis", "accepted_stream_date_proxy")),
                    "completion_upper_bound": str(binding["completion_upper_bound"]),
                    "completion_basis": str(binding["completion_basis"]),
                    "publication_upper_bound_utc": str(binding["publication_upper_bound_utc"]),
                    "receipt_time_utc": str(binding["receipt_time_utc"]),
                    "overlap_unresolved": "false",
                }
            )
        reason = _qualified(
            row,
            admitted_bases=admitted,
            cutoff=cutoff,
            issue_time=issue_time,
            index=index,
            label=name,
        )
        if reason:
            withheld[reason] += 1
            continue
        if row[MODEL_EVENT_DATE] != row[date_field]:
            raise LiveError(f"{name} row {index} changes accepted modeled-event chronology")
        rows.append(row)
    if not rows:
        raise ReplayUnavailable(f"{name} has no eligible rows")
    return rows, observed, path, dict(sorted(withheld.items()))


def _record_result(record: base.Record, index: int) -> elo.Result:
    if record.a_won is None:
        raise LiveError(f"tier state history row {record.match_id} has no outcome")
    a = elo.player_key(str(record.player_a), "")
    b = elo.player_key(str(record.player_b), "")
    winner, loser = (a, b) if record.a_won else (b, a)
    return elo.Result(
        record.match_date,
        "ATP",
        record.tourney_name,
        record.tourney_level,
        record.round,
        record.surface,
        record.best_of,
        winner,
        loser,
        "",
        "",
        tier_elo.TOUR_SOURCE,
        index,
    )


def _tier_offset(config: LiveConfig) -> tuple[float, dict[str, Any]]:
    route = config.document.get("feature_replay", {}).get("ATP", {})
    entry = route.get("tier_offset_contract")
    if not isinstance(entry, dict) or _binding_pending(entry.get("path")):
        raise ReplayUnavailable("ATP tier offset contract is PENDING")
    path = resolve_under_root(str(entry["path"]), label="ATP tier offset contract")
    digest = require_hash(path, str(entry.get("sha256")), label="ATP tier offset contract")
    source = json.loads(path.read_text(encoding="utf-8"))
    checkpoint_year = int(entry["checkpoint_target_year"])
    chain = source.get("chain", {})
    if chain.get("tier_offset_mode") != "per_training_window":
        raise LiveError("ATP tier offset source does not declare per-training-window mode")
    try:
        frozen = float(chain["tier_initial_rating_offset_by_year"][str(checkpoint_year)])
    except (KeyError, TypeError, ValueError) as error:
        raise LiveError("ATP tier offset source lacks its checkpoint value") from error
    configured = float(route["tier_initial_rating_offset_2024"])
    if checkpoint_year != 2024 or configured != frozen:
        raise LiveError("ATP live tier offset differs from the accepted 2024 checkpoint")
    return configured, {
        "path": relative_to_root(path, label="ATP tier offset contract"),
        "sha256": digest,
        "checkpoint_target_year": checkpoint_year,
        "offset_mode": "per_training_window",
        "value": configured,
    }


def _tier_block(
    config: LiveConfig,
    panel: QualifiedPanel,
    target: base.Record,
    rule: dynamic.MatchRule,
    base_dynamic_probability: str,
    *,
    issue_time: dt.datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cutoff = target.match_date - dt.timedelta(days=2)
    results_rows, results_sha, results_path, results_withheld = _read_bound_gzip(
        config,
        name="tier_results",
        cutoff=cutoff,
        issue_time=issue_time,
        required=set(elo.RESULT_COLUMNS) | {"match_id", "season", "is_final"},
    )
    count_rows, counts_sha, counts_path, counts_withheld = _read_bound_gzip(
        config,
        name="tier_source_rows",
        cutoff=cutoff,
        issue_time=issue_time,
        required=set(dynamic.SOURCE_ROW_FIELDS),
    )
    # The accepted tier Elo candidate starts its lower-tier state in 2005.  The
    # experience block independently retains the longer 1991+ result history.
    lower_results = elo.parse_results(
        [
            row
            for row in results_rows
            if int(row["season"]) >= int(tier_elo.DEFAULT_PARAMETERS["elo_start_year"])
        ]
    )
    tour_results = [_record_result(record, index) for index, record in enumerate(panel.records)]
    sources = sorted([*tour_results, *lower_results], key=elo.Result.order_key)
    offset, offset_binding = _tier_offset(config)
    engine = tier_elo.make_engine(tier_elo.DECLARED_MULTIPLIERS, offset)
    neutral_target = NeutralEloTarget(
        target.match_date,
        target.surface,
        target.best_of,
        elo.player_key(str(target.player_a), ""),
        elo.player_key(str(target.player_b), ""),
    )
    prediction = next(elo.replay([neutral_target], lag_days=2, sources=sources, engine=engine))
    experience_rows = sorted(results_rows, key=lambda row: (row["date"], row["match_id"]))
    experience = tier_elo.Experience(experience_rows)
    experience.advance_to(cutoff)
    block: dict[str, Any] = {
        "tier_elo_overall_logit": repr(float(prediction.elo_overall_logit)),
        "tier_elo_surface_logit": repr(float(prediction.elo_surface_logit)),
    }
    for suffix, player in (("a", target.player_a), ("b", target.player_b)):
        raw_matches = experience.matches[player]
        raw_titles = experience.titles[player]
        key = elo.player_key(str(player), "")
        block["tier_prior_matches_diff" if suffix == "a" else "_discard_matches_b"] = raw_matches
        block["tier_prior_titles_diff" if suffix == "a" else "_discard_titles_b"] = raw_titles
        block[f"tier_first_tier_{suffix}"] = engine.debut_tier.get(key, "")
        block[f"tier_initial_offset_applied_{suffix}"] = int(
            engine.debut_tier.get(key, "tour") != "tour"
        )
    block["tier_prior_matches_diff"] = repr(
        float(
            min(int(block.pop("tier_prior_matches_diff")), 300)
            - min(int(block.pop("_discard_matches_b")), 300)
        )
    )
    block["tier_prior_titles_diff"] = repr(
        float(
            min(int(block.pop("tier_prior_titles_diff")), 20)
            - min(int(block.pop("_discard_titles_b")), 20)
        )
    )
    extra = dynamic_replay_tier_observations(
        count_rows, panel_match_ids={row["match_id"] for row in panel.rows}
    )
    selected, solver = _dynamic_row(panel.rows, target, rule, tour="ATP", extra_observations=extra)
    block["tier_dynamic_match_probability_a"] = selected["dynamic_match_probability_a"]
    state = {
        "tier_results": {
            "path": relative_to_root(results_path, label="tier_results"),
            "sha256": results_sha,
            "withheld": results_withheld,
            "state_through": max(row["date"] for row in results_rows),
        },
        "tier_source_rows": {
            "path": relative_to_root(counts_path, label="tier_source_rows"),
            "sha256": counts_sha,
            "withheld": counts_withheld,
            "state_through": max(row["match_date"] for row in count_rows),
        },
        "tier_initial_rating_offset": offset,
        "tier_offset_binding": offset_binding,
        "dynamic_solver": solver,
        "base_dynamic_probability": base_dynamic_probability,
    }
    return block, state


def dynamic_replay_tier_observations(
    rows: Sequence[Mapping[str, str]], *, panel_match_ids: set[str]
) -> list[dynamic.HistoryObservation]:
    observations: list[dynamic.HistoryObservation] = []
    for row in rows:
        if row["match_id"] in panel_match_ids:
            raise LiveError(f"lower-tier count row collides with panel match_id {row['match_id']}")
        observations.append(
            dynamic.observation_from_source_row(
                row, history_statuses=("completed", "retired", "default")
            )
        )
    return observations


def _state_hashes(feature: Mapping[str, Any], selected: Mapping[str, Any] | None) -> dict[str, str]:
    groups = {
        "elo": [name for name in feature if name.startswith("elo_")],
        "serve_return": [
            name
            for name in feature
            if name.startswith(("serve_", "return_", "log_serve_", "count_"))
        ],
        "workload": [
            name
            for name in feature
            if name.startswith(("matches_", "log_points_", "points_missing_", "rest_"))
        ],
        "ranking": [name for name in feature if name.startswith(("rank_", "ranking_"))],
    }
    hashes = {
        name: canonical_hash({key: feature[key] for key in sorted(keys)})
        for name, keys in groups.items()
    }
    if selected is not None:
        hashes["dynamic"] = canonical_hash(dict(sorted(selected.items())))
    tier_keys = [name for name in feature if name.startswith("tier_")]
    if tier_keys:
        hashes["tier"] = canonical_hash({key: feature[key] for key in sorted(tier_keys)})
    return hashes


def predict(
    config: LiveConfig,
    rung: str,
    fixture: Mapping[str, Any],
    version: Mapping[str, Any],
    *,
    issue_time: dt.datetime,
    model_bundle: str | Path,
) -> dict[str, Any]:
    """Replay one exact estimator row and apply the pinned accepted checkpoint."""

    tour = str(fixture["tour"])
    cutoff = dt.date.fromisoformat(str(fixture["information_cutoff"]))
    target = _fixture_record(fixture)
    input_review = _input_review_binding(config, tour, issue_time=issue_time)
    record = config.section("rungs").get(rung)
    if not isinstance(record, dict):
        raise LiveError(f"rung {rung!r} is not declared")
    expected_tour = "ATP" if rung.startswith("atp_") else "WTA"
    if tour != expected_tour:
        raise LiveError(f"rung {rung} cannot forecast a {tour} fixture")
    route = record.get("feature_route", {})
    declared_fixture_year = int(route["fixture_year"])
    if target.calendar_year != declared_fixture_year:
        raise ReplayUnavailable(
            f"{rung} route is declared for fixture year {declared_fixture_year}, "
            f"not {target.calendar_year}"
        )
    lag_days = config.lag_days()
    if lag_days != int(base.FIXED_PARAMETERS["lag_calendar_days"]):
        raise LiveError("live cutoff lag differs from the accepted feature replay lag")
    expected_cutoff = target.match_date - dt.timedelta(days=lag_days)
    if cutoff != expected_cutoff:
        raise LiveError(
            f"fixture information cutoff {cutoff} differs from the declared D-{lag_days} "
            f"cutoff {expected_cutoff}"
        )
    panel = qualified_panel(config, tour, cutoff=cutoff, issue_time=issue_time)
    feature = _base_feature(
        panel,
        target,
        _ranking_lookup(config, version, tour, issue_time=issue_time),
    )
    selected: dict[str, str] | None = None
    rule_state: dict[str, Any] | None = None
    sidecar_state: dict[str, Any] | None = None
    tier_state: dict[str, Any] | None = None
    dynamic_binding: dict[str, Any] | None = None
    if rung in {"atp_p1", "atp_full_tier", "wta_full"}:
        dynamic_binding = _dynamic_binding(config, tour, target.calendar_year)
        rule, rule_state = _match_rule(config, panel, fixture, tour=tour)
        selected, solver = _dynamic_row(panel.rows, target, rule, tour=tour)
        sidecar_row, sidecar_state = _sidecar_row(
            config, panel, target, feature, selected, tour=tour
        )
        if rung == "atp_full_tier":
            tier_values, tier_state = _tier_block(
                config,
                panel,
                target,
                rule,
                selected["dynamic_match_probability_a"],
                issue_time=issue_time,
            )
            sidecar_row.update(tier_values)
            pipeline.configure_bundles(["base", "full", "full_tier"], ["hgb"])
        else:
            pipeline.configure_bundles(["base", "full"], ["hgb"])
        contract = pipeline.FeatureContract.from_dictionary(base.column_dictionary())
        feature.update(pipeline.transformed_additions(feature, sidecar_row, contract))

    checkpoint_year = int(route["checkpoint_target_year"])
    bundle = Path(model_bundle).expanduser().resolve()
    checkpoint = release.load_checkpoint(bundle, tour=tour, rung=rung, year=checkpoint_year)
    columns = list(checkpoint.metadata["estimator_feature_names"])
    missing = [column for column in columns if column not in feature]
    if missing:
        raise LiveError(f"{rung} exact replay row lacks checkpoint columns {missing}")
    values = {column: feature[column] for column in columns}
    probabilities = release.predict_feature_row(
        checkpoint,
        values,
        season=str(target.calendar_year),
        match_id=target.match_id,
    )
    p_a = probabilities["calibrated_probability_a"]
    return {
        "rung": rung,
        "status": "issued",
        "model_id": checkpoint.metadata["model_id"],
        "p_a": p_a,
        "p_b": 1.0 - p_a,
        "raw_probability_a": probabilities["raw_probability_a"],
        "checkpoint_target_year": checkpoint_year,
        "fixture_year": target.calendar_year,
        "fit_cutoff": checkpoint.metadata["fit_cutoff"],
        "selection_cutoff_inclusive": checkpoint.metadata["selection_cutoff_inclusive"],
        "model_sha256": checkpoint.metadata["model_sha256"],
        "source_fit_manifest_sha256": checkpoint.metadata["source_fit_manifest_sha256"],
        "information_cutoff": cutoff.isoformat(),
        "feature_count": len(columns),
        "feature_order_sha256": canonical_hash(columns),
        "feature_row_sha256": canonical_hash(values),
        "state_hashes": _state_hashes(feature, selected),
        "fixture_outcome_fields_read": [],
        "fixture_stats_read": [],
        "lineage": {
            "history_path": relative_to_root(panel.path, label="model panel"),
            "history_sha256": panel.sha256,
            "history_rows_used": len(panel.records),
            "history_withheld": panel.withheld,
            "history_event_date_field": MODEL_EVENT_DATE,
            "history_availability_fields": list(BOUND_FIELDS[1:]),
            "input_review_receipt": input_review,
            "ranking_snapshot_date": feature["ranking_snapshot_date"],
            "ranking_global_age_days": feature["ranking_global_age_days"],
            "ranking_global_stale": feature["ranking_global_stale"],
            "live_version": version["manifest"]["version_id"],
            "live_version_content_sha256": version["manifest"]["content_sha256"],
            "incremental_version_results_consumed": 0,
            "incremental_version_results_policy": (
                "trained replay consumes the reviewed bound panel; version results are not "
                "duplicated into that state"
            ),
            "dynamic_binding": dynamic_binding,
            "match_rule": rule_state,
            "dynamic_solver": solver if selected else None,
            "sidecar": sidecar_state,
            "tier": tier_state,
        },
        "code": {
            "route": code_receipt(__name__),
            "base_features": code_receipt(base.__name__),
            "dynamic": code_receipt(dynamic.__name__) if selected else None,
            "model_release": code_receipt(release.__name__),
        },
        "config": {"live_config_sha256": config.sha256},
    }


def binding_status(config: LiveConfig, rung: str) -> dict[str, Any]:
    """Read-only binding preflight used by D2 readiness; it never executes a replay."""

    tour = "ATP" if rung.startswith("atp_") else "WTA"
    missing: list[str] = []
    route = config.document.get("feature_replay", {}).get(tour, {})
    try:
        _input_review_binding(config, tour)
    except (ReplayUnavailable, LiveError, OSError, ValueError) as error:
        missing.append(str(error))
    if config.lag_days() != int(base.FIXED_PARAMETERS["lag_calendar_days"]):
        missing.append("live cutoff lag differs from the accepted feature replay lag")
    try:
        path, _, _ = _history_entry(config, tour)
        with path.open(newline="", encoding="utf-8") as handle:
            header = set(csv.DictReader(handle).fieldnames or ())
        absent = sorted(PANEL_FIELDS - header)
        if absent:
            missing.append(f"model panel columns {absent}")
    except (ReplayUnavailable, LiveError, OSError) as error:
        missing.append(str(error))
    if rung in {"atp_p1", "atp_full_tier", "wta_full"}:
        try:
            target_year = int(config.section("rungs")[rung]["feature_route"]["fixture_year"])
            _dynamic_binding(config, tour, target_year)
        except (KeyError, ReplayUnavailable, LiveError, OSError, ValueError) as error:
            missing.append(str(error))
        try:
            _bio_rows(config, tour)
        except (ReplayUnavailable, LiveError, OSError) as error:
            missing.append(str(error))
    if rung == "atp_full_tier":
        try:
            _tier_offset(config)
        except (ReplayUnavailable, LiveError, OSError, ValueError) as error:
            missing.append(str(error))
        for name in ("tier_results", "tier_source_rows"):
            entry = route.get(name)
            if (
                not isinstance(entry, dict)
                or _binding_pending(entry.get("path"))
                or _binding_pending(entry.get("sha256"))
            ):
                missing.append(f"feature_replay.ATP.{name}")
            else:
                try:
                    path = resolve_under_root(str(entry["path"]), label=name)
                    require_hash(path, str(entry["sha256"]), label=name)
                except (LiveError, OSError, ValueError) as error:
                    missing.append(str(error))
    ranking_source = route.get("ranking_source")
    ranking_index = route.get("ranking_index")
    direct_ranking = isinstance(ranking_source, dict) and not _binding_pending(
        ranking_source.get("path")
    )
    ranking_status = "snapshot_fallback"
    if direct_ranking:
        ranking_status = "direct_bound"
        for name, entry in (("ranking_source", ranking_source), ("ranking_index", ranking_index)):
            if (
                not isinstance(entry, dict)
                or _binding_pending(entry.get("path"))
                or _binding_pending(entry.get("sha256"))
            ):
                missing.append(f"feature_replay.{tour}.{name}")
                continue
            try:
                path = resolve_under_root(str(entry["path"]), label=f"{tour} {name}")
                require_hash(path, str(entry["sha256"]), label=f"{tour} {name}")
            except (LiveError, OSError, ValueError) as error:
                missing.append(str(error))
        if _binding_pending(ranking_source.get("available_upper_bound_utc")):
            missing.append(f"feature_replay.{tour}.ranking_source.available_upper_bound_utc")
    rule_mapping = route.get("rule_mapping")
    rule_status = (
        "accepted_map_bound"
        if isinstance(rule_mapping, dict) and not _binding_pending(rule_mapping.get("path"))
        else "explicit_sourced_fixture_fallback"
    )
    return {
        "status": "ready" if not missing else "pending",
        "missing": missing,
        "event_date_field": MODEL_EVENT_DATE,
        "availability_fields": list(BOUND_FIELDS[1:]),
        "ranking_route": ranking_status,
        "match_rule_route": rule_status,
    }
