"""Prospective fixtures: outcome-free rows, the information cutoff, freshness and rungs.

A fixture is the neutral pair ``(player_a, player_b)`` in a declared event and round with a
sourced scheduled start. The constructor refuses any input carrying an outcome-like column,
applies the frozen exclusion rule for unknown identity, surface, format or start, and
records for every fixture which source versions, rows and constants a forecast may use.

The ``elo`` rung replays the bound history table plus eligible live rows. Trained rungs
use :mod:`tennislab.live.feature_replay` only when their exact model bundle and state
bindings are supplied; no weaker substitute runs under a rung's name.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tennislab.chain.common import (
    canonical_hash,
    code_receipt,
    require_hash,
    resolve_under_root,
    sha256,
)
from tennislab.live.common import LiveConfig, LiveError, iso_utc, parse_utc
from tennislab.live.identity import IdentityTable
from tennislab.ratings import elo
from tennislab.ratings.elo import SURFACES, PlayerKey, Result, player_key

FIXTURE_INPUT = (
    "fixture_ref",
    "tour",
    "event_id",
    "round",
    "player_x_id",
    "player_x_name",
    "player_y_id",
    "player_y_name",
    "surface",
    "best_of",
    "best_of_source",
    "scheduled_start",
    "scheduled_start_source",
    "scheduled_start_timezone",
    "start_uncertainty_hours",
)
OUTCOME_LIKE = {
    "winner",
    "loser",
    "winner_id",
    "loser_id",
    "winner_name",
    "loser_name",
    "score",
    "a_won",
    "result",
    "sets",
    "status",
    "outcome",
    "minutes",
}
OUTCOME_PREFIXES = ("w_", "l_", "p_", "o_", "a_1st", "b_1st", "a_svpt", "b_svpt")
PLAYED = {"completed", "retired"}
BOUND_HISTORY_FIELDS = (
    "date_basis",
    "completion_upper_bound",
    "completion_basis",
    "publication_upper_bound_utc",
    "receipt_time_utc",
    "status",
    "overlap_unresolved",
)


def _refuse_outcome_columns(header: list[str]) -> None:
    bad = [c for c in header if c in OUTCOME_LIKE or c.startswith(OUTCOME_PREFIXES)]
    if bad:
        raise LiveError(
            f"fixture input carries outcome-like columns {bad}; a prospective fixture has no outcome"
        )


def read_fixture_input(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        _refuse_outcome_columns(header)
        missing = [c for c in FIXTURE_INPUT if c not in header]
        if missing:
            raise LiveError(f"fixture input lacks columns {missing}")
        rows = [dict(row) for row in reader]
    if not rows:
        raise LiveError("fixture input has no rows")
    return rows


def _key(pid: str) -> PlayerKey:
    return player_key(pid, "")


def fixture_identity(
    tour: str, event_id: str, round_code: str, a: str, b: str, start_date: str
) -> str:
    return hashlib.sha256(
        "|".join([tour, event_id, round_code, a, b, start_date]).encode()
    ).hexdigest()


def construct(
    config: LiveConfig,
    rows: list[dict[str, str]],
    identity: IdentityTable,
    events: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the frozen exclusion rule and neutral orientation; no forecast here."""
    rules = config.section("exclusion")
    out: list[dict[str, Any]] = []
    for row in rows:
        reasons: list[str] = []
        tour = row["tour"].strip().upper()
        if tour not in {"ATP", "WTA"}:
            reasons.append("unknown_tour")
        event = events.get(row["event_id"].strip())
        if event is None:
            reasons.append("unknown_event")
        res_x = identity.resolve(row["player_x_name"], tour=tour, declared_id=row["player_x_id"])
        res_y = identity.resolve(row["player_y_name"], tour=tour, declared_id=row["player_y_id"])
        if res_x.status != "resolved" or res_y.status != "resolved":
            reasons.append("unknown_identity")
        elif res_x.player_id == res_y.player_id:
            reasons.append("same_player_both_sides")
        surface = row["surface"].strip()
        if surface not in SURFACES:
            reasons.append("unknown_surface")
        best_of = row["best_of"].strip()
        if best_of not in {"3", "5"} or not row["best_of_source"].strip():
            reasons.append("unknown_format")
        match_rule: dict[str, Any] | None = None
        match_rule_text = row.get("match_rule", "").strip()
        match_rule_source = row.get("match_rule_source", "").strip()
        if match_rule_text or match_rule_source:
            if not match_rule_text or not match_rule_source:
                reasons.append("incomplete_match_rule_binding")
            else:
                try:
                    parsed_rule = json.loads(match_rule_text)
                    if not isinstance(parsed_rule, dict):
                        raise ValueError("match_rule must be a JSON object")
                    from tennislab.dynamics.dynamic import MatchRule

                    rule = MatchRule.from_mapping(parsed_rule)
                    if best_of in {"3", "5"} and 2 * rule.sets_to_win - 1 != int(best_of):
                        raise ValueError("match_rule sets_to_win disagrees with best_of")
                    match_rule = parsed_rule
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    reasons.append(f"invalid_match_rule:{error}")
        start_utc = None
        try:
            start_utc = parse_utc(row["scheduled_start"], label="scheduled_start")
        except LiveError:
            reasons.append("start_unparseable")
        timezone_name = row["scheduled_start_timezone"].strip()
        timezone = None
        if not row["scheduled_start_source"].strip() or not timezone_name:
            reasons.append("start_without_source_or_timezone")
        elif start_utc is not None:
            try:
                timezone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError, ValueError:
                reasons.append("start_timezone_invalid")
        try:
            uncertainty = float(row["start_uncertainty_hours"] or "nan")
        except ValueError:
            uncertainty = float("nan")
        if uncertainty != uncertainty or uncertainty > float(rules["start_uncertainty_hours_max"]):
            reasons.append("start_uncertainty_missing_or_too_large")
        record: dict[str, Any] = {
            "fixture_ref": row["fixture_ref"],
            "tour": tour,
            "event_id": row["event_id"].strip(),
            "round": row["round"].strip(),
            "surface": surface,
            "best_of": int(best_of) if best_of in {"3", "5"} else None,
            "best_of_source": row["best_of_source"].strip(),
            "match_rule": match_rule,
            "match_rule_source": match_rule_source,
            "scheduled_start_utc": iso_utc(start_utc) if start_utc else None,
            "scheduled_start_local_date": None,
            "scheduled_start_source": row["scheduled_start_source"].strip(),
            "scheduled_start_timezone": timezone_name,
            "start_uncertainty_hours": uncertainty if uncertainty == uncertainty else None,
            "identity": {"x": res_x.__dict__, "y": res_y.__dict__},
        }
        if start_utc and timezone is not None:
            record["scheduled_start_local_date"] = start_utc.astimezone(timezone).date().isoformat()
        if reasons:
            record.update(
                {"fixture_status": "excluded", "exclusion_reasons": reasons, "fixture_id": None}
            )
            out.append(record)
            continue
        kx, ky = _key(res_x.player_id), _key(res_y.player_id)
        swapped = ky < kx
        a_id, b_id = (
            (res_y.player_id, res_x.player_id) if swapped else (res_x.player_id, res_y.player_id)
        )
        a_name, b_name = (
            (row["player_y_name"], row["player_x_name"])
            if swapped
            else (row["player_x_name"], row["player_y_name"])
        )
        cutoff = dt.date.fromisoformat(record["scheduled_start_local_date"]) - dt.timedelta(
            days=config.lag_days()
        )
        record.update(
            {
                "fixture_status": "qualified",
                "exclusion_reasons": [],
                "player_a_id": a_id,
                "player_b_id": b_id,
                "player_a_name": a_name.strip(),
                "player_b_name": b_name.strip(),
                "input_orientation_swapped": swapped,
                "event_name": event["name"] if event else "",
                "level": event.get("level", "") if event else "",
                "information_cutoff": cutoff.isoformat(),
                "cutoff_rule": f"scheduled local date minus {config.lag_days()} calendar days; bound <= cutoff inclusive",
                "fixture_id": fixture_identity(
                    tour,
                    record["event_id"],
                    record["round"],
                    a_id,
                    b_id,
                    record["scheduled_start_local_date"],
                ),
            }
        )
        out.append(record)
    return out


# --- eligibility and freshness ----------------------------------------------------------------


def receipt_times(version: Mapping[str, Any]) -> dict[str, str]:
    """Receipt times from hash-verified version-manifest bindings, not mutable files."""
    out: dict[str, str] = {}
    for source_id, binding in version["manifest"]["acquisition_receipts"].items():
        attempt_id = binding["attempt_id"]
        out[f"{source_id}/{attempt_id}"] = binding["finished_utc"]
    return out


def eligible_results(
    rows: list[dict[str, str]],
    *,
    tour: str,
    cutoff: dt.date,
    issue_time: dt.datetime,
    receipts: Mapping[str, str],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Rows a forecast may use, and the counts of what was withheld and why (RB13)."""
    chosen: list[dict[str, str]] = []
    withheld = {
        "overlap_unresolved": 0,
        "after_cutoff": 0,
        "not_played": 0,
        "published_after_issue": 0,
        "received_after_issue": 0,
        "other_tour": 0,
    }
    for row in rows:
        if row["tour"] != tour:
            withheld["other_tour"] += 1
            continue
        if row["overlap_unresolved"].lower() == "true" or not row["completion_upper_bound"]:
            withheld["overlap_unresolved"] += 1
            continue
        if row["status"] not in PLAYED or row["winner_side"] not in {"a", "b"}:
            withheld["not_played"] += 1
            continue
        if dt.date.fromisoformat(row["completion_upper_bound"]) > cutoff:
            withheld["after_cutoff"] += 1
            continue
        if parse_utc(row["publication_upper_bound_utc"], label="publication") > issue_time:
            withheld["published_after_issue"] += 1
            continue
        received = receipts.get(row["receipt_id"])
        if received is None or parse_utc(received, label="receipt") > issue_time:
            withheld["received_after_issue"] += 1
            continue
        chosen.append(row)
    return chosen, withheld


def serve_freshness(
    serve: list[dict[str, str]], *, tour: str, player_id: str, cutoff: dt.date, start: dt.date
) -> dict[str, Any]:
    usable = []
    withheld = 0
    for row in serve:
        if row["tour"] != tour or row["player_id"] != player_id:
            continue
        if row["overlap_unresolved"].lower() == "true" or not row["completion_upper_bound"]:
            withheld += 1
            continue
        bound = dt.date.fromisoformat(row["completion_upper_bound"])
        if bound <= cutoff:
            usable.append((bound, row))
    if not usable:
        return {
            "status": "missing",
            "last_usable_bound": None,
            "basis": None,
            "fields_present": [],
            "fields_missing": [],
            "state_as_of": None,
            "state_date_basis": None,
            "staleness_days": None,
            "staleness_basis": None,
            "availability_age_days": None,
            "withheld_overlap_unresolved": withheld,
            "source_id": None,
            "receipt_id": None,
        }
    bound, row = max(usable, key=lambda item: (item[0], item[1]["match_id"]))
    present = row["fields_present"].split()
    modeled_text = row.get("model_event_date", "").strip()
    if modeled_text:
        modeled_event = dt.date.fromisoformat(modeled_text)
        if modeled_event > bound:
            raise LiveError("serve model_event_date exceeds its completion upper bound")
        staleness_basis = "model_event_date"
    else:
        modeled_event = bound
        staleness_basis = "legacy_completion_upper_bound"
    return {
        "status": "usable" if row["serve_block_valid"].lower() == "true" else "present_invalid",
        "last_usable_bound": bound.isoformat(),
        "basis": f"{row['date_basis']} anchor {row['event_anchor']} with {row['completion_basis']} {row['completion_upper_bound']}",
        "fields_present": present,
        "fields_missing": row["fields_missing"].split(),
        "state_as_of": modeled_event.isoformat(),
        "state_date_basis": row["date_basis"],
        "staleness_days": (start - modeled_event).days,
        "staleness_basis": staleness_basis,
        "availability_age_days": (start - bound).days,
        "withheld_overlap_unresolved": withheld,
        "source_id": row["source_id"],
        "receipt_id": row["receipt_id"],
    }


def ranking_freshness(
    rankings: list[dict[str, str]], *, tour: str, player_id: str, cutoff: dt.date, start: dt.date
) -> dict[str, Any]:
    usable = [
        r
        for r in rankings
        if r["tour"] == tour
        and r["player_id"] == player_id
        and dt.date.fromisoformat(r["ranking_date"]) <= cutoff
    ]
    if not usable:
        return {
            "status": "missing",
            "rank": None,
            "points": None,
            "as_of": None,
            "publication_basis": None,
            "staleness_days": None,
        }
    row = max(usable, key=lambda r: r["ranking_date"])
    as_of = dt.date.fromisoformat(row["ranking_date"])
    return {
        "status": "last_known",
        "rank": row["rank"],
        "points": row["points"],
        "as_of": as_of.isoformat(),
        "publication_basis": row["publication_basis"],
        "staleness_days": (start - as_of).days,
    }


# --- rungs -------------------------------------------------------------------------------------


def history_binding(config: LiveConfig, tour: str) -> tuple[Path, str, dict[str, Any]]:
    section = config.section("history")
    entry = section.get(tour)
    if not isinstance(entry, dict) or entry.get("results_csv") in (None, "", "PENDING"):
        raise LiveError(f"history binding for {tour} is PENDING in the live config")
    path = resolve_under_root(entry["results_csv"], label=f"{tour} history")
    if not path.is_file():
        raise LiveError(f"{tour} history table not found: {path}")
    expected = entry.get("sha256")
    if expected in (None, "", "PENDING"):
        raise LiveError(f"history binding for {tour} has no sha256")
    bases = entry.get("admissible_completion_bases")
    if not isinstance(bases, list) or not bases or any(not isinstance(v, str) for v in bases):
        raise LiveError(f"history binding for {tour} has no admissible completion bases")
    return path, require_hash(path, str(expected), label=f"{tour} history"), entry


def eligible_history(
    config: LiveConfig,
    tour: str,
    *,
    cutoff: dt.date,
    issue_time: dt.datetime,
) -> tuple[list[Result], str, dict[str, int], Path]:
    """Read hash-bound history and apply the same temporal eligibility gates as live rows."""
    path, digest, binding = history_binding(config, tour)
    binding_available = binding.get("available_upper_bound_utc")
    if binding_available not in (None, ""):
        if binding_available == "PENDING":
            raise LiveError(f"history binding for {tour} has PENDING availability")
        if (
            parse_utc(str(binding_available), label=f"{tour} history binding availability")
            > issue_time
        ):
            raise LiveError(f"{tour} history binding was not available by issue time")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        required = [*elo.RESULT_COLUMNS, *BOUND_HISTORY_FIELDS]
        missing = [field for field in required if field not in header]
        if missing:
            raise LiveError(f"{tour} bound history lacks columns {missing}")
        rows = [dict(row) for row in reader]
    admitted = set(binding["admissible_completion_bases"])
    chosen: list[dict[str, str]] = []
    withheld = {
        "overlap_unresolved": 0,
        "completion_basis_not_admissible": 0,
        "after_cutoff": 0,
        "model_event_after_cutoff": 0,
        "not_played": 0,
        "published_after_issue": 0,
        "received_after_issue": 0,
        "other_tour": 0,
    }
    for index, row in enumerate(rows):
        row_tour = row["tour"].strip().upper()
        if row_tour != tour:
            withheld["other_tour"] += 1
            continue
        unresolved = row["overlap_unresolved"].strip().lower()
        if unresolved not in {"true", "false"}:
            raise LiveError(
                f"{tour} bound history row {index} has invalid overlap_unresolved {unresolved!r}"
            )
        if unresolved == "true" or not row["completion_upper_bound"].strip():
            withheld["overlap_unresolved"] += 1
            continue
        if not row["date_basis"].strip():
            raise LiveError(f"{tour} bound history row {index} has no date_basis")
        if row["completion_basis"].strip() not in admitted:
            withheld["completion_basis_not_admissible"] += 1
            continue
        if row["status"].strip().lower() not in PLAYED:
            withheld["not_played"] += 1
            continue
        try:
            completion = dt.date.fromisoformat(row["completion_upper_bound"].strip())
        except ValueError as error:
            raise LiveError(
                f"{tour} bound history row {index} has invalid completion_upper_bound"
            ) from error
        modeled_event_text = row.get("model_event_date", "").strip() or row.get("date", "").strip()
        if not modeled_event_text:
            raise LiveError(f"{tour} bound history row {index} has no modeled event date")
        try:
            modeled_event = dt.date.fromisoformat(modeled_event_text)
        except ValueError as error:
            raise LiveError(
                f"{tour} bound history row {index} has invalid modeled event date"
            ) from error
        if modeled_event > completion:
            raise LiveError(
                f"{tour} bound history row {index} has modeled event date after "
                "completion upper bound"
            )
        if completion > cutoff:
            withheld["after_cutoff"] += 1
            continue
        if modeled_event > cutoff:
            withheld["model_event_after_cutoff"] += 1
            continue
        if (
            parse_utc(row["publication_upper_bound_utc"], label=f"{tour} history publication")
            > issue_time
        ):
            withheld["published_after_issue"] += 1
            continue
        if parse_utc(row["receipt_time_utc"], label=f"{tour} history receipt") > issue_time:
            withheld["received_after_issue"] += 1
            continue
        # Receipt/publication/completion bounds decide eligibility.  The accepted
        # event-date proxy independently orders model state and rest intervals.
        chosen.append({**row, "date": modeled_event.isoformat()})
    try:
        results = elo.parse_results(chosen)
    except ValueError as error:
        raise LiveError(f"{tour} bound history is invalid: {error}") from error
    return results, digest, withheld, path


def live_result(row: Mapping[str, str], version_id: str, index: int) -> Result:
    a, b = _key(row["player_a_id"]), _key(row["player_b_id"])
    winner, loser = (a, b) if row["winner_side"] == "a" else (b, a)
    w_name, l_name = (
        (row["player_a_name"], row["player_b_name"])
        if row["winner_side"] == "a"
        else (row["player_b_name"], row["player_a_name"])
    )
    return Result(
        date=dt.date.fromisoformat(row["completion_upper_bound"]),
        tour=row["tour"],
        tournament=row["event_name"],
        level=row["level"],
        round=row["round"],
        surface=row["surface"],
        best_of=None,
        winner=winner,
        loser=loser,
        winner_name=w_name,
        loser_name=l_name,
        source=f"live:{version_id}:{row['source_revision']}",
        row_index=index,
    )


def elo_forecast(
    config: LiveConfig,
    fixture: Mapping[str, Any],
    version: Mapping[str, Any],
    *,
    issue_time: dt.datetime,
    receipts: Mapping[str, str],
) -> dict[str, Any]:
    tour = fixture["tour"]
    cutoff = dt.date.fromisoformat(fixture["information_cutoff"])
    start = dt.date.fromisoformat(fixture["scheduled_start_local_date"])
    history, history_sha, history_withheld, history_path = eligible_history(
        config, tour, cutoff=cutoff, issue_time=issue_time
    )
    live_rows, withheld = eligible_results(
        version["results"], tour=tour, cutoff=cutoff, issue_time=issue_time, receipts=receipts
    )
    if (
        live_rows
        and live_rows[0]["surface"]
        and any(r["surface"] not in SURFACES for r in live_rows)
    ):
        raise LiveError("a live results row has an unsupported surface")
    sources = history + [
        live_result(r, version["manifest"]["version_id"], 10_000_000 + i)
        for i, r in enumerate(live_rows)
        if r["surface"] in SURFACES
    ]
    sources.sort(key=Result.order_key)
    engine = elo.state_as_of(sources, cutoff)
    if engine.latest_source_date is not None and engine.latest_source_date > cutoff:
        raise LiveError(f"state date {engine.latest_source_date} exceeds cutoff {cutoff}")
    a, b = _key(fixture["player_a_id"]), _key(fixture["player_b_id"])
    priced = engine.prospective(a, b, fixture["surface"], fixture["best_of"], date=start)
    a_serve = serve_freshness(
        version["serve"], tour=tour, player_id=fixture["player_a_id"], cutoff=cutoff, start=start
    )
    b_serve = serve_freshness(
        version["serve"], tour=tour, player_id=fixture["player_b_id"], cutoff=cutoff, start=start
    )
    a_rank = ranking_freshness(
        version["rankings"], tour=tour, player_id=fixture["player_a_id"], cutoff=cutoff, start=start
    )
    b_rank = ranking_freshness(
        version["rankings"], tour=tour, player_id=fixture["player_b_id"], cutoff=cutoff, start=start
    )
    frontier_declared = config.document.get("serve_frontier_declared", {}).get(tour)
    frontier_observed = version["manifest"].get("serve_frontier_observed", {}).get(tour)
    return {
        "rung": "elo",
        "status": "issued",
        "model_id": elo.MODEL_ID,
        "p_a": priced["p_x"],
        "p_b": priced["p_y"],
        "p_overall_a": priced["p_overall_x"],
        "p_surface_a": priced["p_surface_x"],
        "cold_start_overall": priced["cold_start_overall"],
        "cold_start_surface": priced["cold_start_surface"],
        "best_of_used_by_model": False,
        "state_through": priced["state_through"],
        "state_sha256": engine.state_hash(),
        "information_cutoff": cutoff.isoformat(),
        "lineage": {
            "history": {
                "path": str(history_path.relative_to(resolve_under_root(".", label="workspace"))),
                "sha256": history_sha,
                "rows_used": len(history),
                "withheld": history_withheld,
                "receipt_semantics": "receipt_time_utc proves local custody only; publication_upper_bound_utc is the separate retrospective availability evidence",
            },
            "live_version": version["manifest"]["version_id"],
            "live_version_content_sha256": version["manifest"]["content_sha256"],
            "live_rows_used": len(live_rows),
            "live_rows_sha256": canonical_hash([r["row_id"] for r in live_rows]),
            "live_rows_max_bound": max(
                (r["completion_upper_bound"] for r in live_rows), default=None
            ),
            "withheld": withheld,
        },
        "freshness": {
            "results": {
                "source_id": "wikipedia_results",
                "version": version["manifest"]["version_id"],
                "completion_basis": "declared_event_end",
                "max_source_revision_used": max(
                    (r["source_revision"] for r in live_rows), default=None
                ),
            },
            "serve_a": a_serve,
            "serve_b": b_serve,
            "ranking_a": a_rank,
            "ranking_b": b_rank,
            "serve_frontier": {
                "declared_retained": frontier_declared,
                "observed_feed": frontier_observed,
            },
            "price": {
                "provenance": "none",
                "note": "no price source bound; benchmark coverage only",
            },
            "note": "serve and ranking freshness come from their own feeds; a results-only update never advances them",
        },
        "learned_constants": {
            "elo_k": elo.ELO_K,
            "elo_scale": elo.ELO_SCALE,
            "initial_rating": elo.INITIAL_RATING,
            "pooling": [elo.POOLED_OVERALL_WEIGHT, elo.POOLED_SURFACE_WEIGHT],
            "horizon": "none: fixed constants, no fit",
        },
        "code": {
            "module": code_receipt("tennislab.ratings.elo"),
            "constructor": code_receipt("tennislab.live.fixtures"),
        },
        "config": {
            "live_config_sha256": config.sha256,
            "design_sha256": config.design_hash(),
            "repair_design_sha256": config.repair_design_hash(),
            "rung_config_sha256": _rung_config_hash(config, "elo"),
        },
    }


def _rung_config_hash(config: LiveConfig, rung: str) -> str | None:
    entry = config.section("rungs").get(rung, {})
    path = entry.get("config")
    if not path:
        return None
    resolved = resolve_under_root(path, label=f"rung {rung} config")
    return sha256(resolved) if resolved.is_file() else None


def unavailable(
    config: LiveConfig,
    rung: str,
    fixture: Mapping[str, Any],
    *,
    reason: str | None = None,
    missing_bindings: list[str] | None = None,
) -> dict[str, Any]:
    entry = config.section("rungs").get(rung)
    if entry is None:
        raise LiveError(f"rung {rung!r} is not declared")
    return {
        "rung": rung,
        "status": "unavailable",
        "reason": reason or entry.get("reason", "no binding"),
        "information_cutoff": fixture["information_cutoff"],
        "missing_bindings": missing_bindings
        or ["accepted model bundle", "qualified model-panel history", "exact feature state"],
        "config": {
            "live_config_sha256": config.sha256,
            "design_sha256": config.design_hash(),
            "repair_design_sha256": config.repair_design_hash(),
        },
    }


def rungs_for(config: LiveConfig, tour: str) -> list[str]:
    declared = config.section("rungs")
    order = (
        ["elo", "atp_p0", "atp_p1", "atp_full_tier"]
        if tour == "ATP"
        else ["elo", "wta_base", "wta_full"]
    )
    return [r for r in order if r in declared]


def forecast_all(
    config: LiveConfig,
    fixture: Mapping[str, Any],
    version: Mapping[str, Any],
    *,
    issue_time: dt.datetime,
    receipts: Mapping[str, str],
    model_bundle: str | Path | None = None,
) -> list[dict[str, Any]]:
    out = []
    for rung in rungs_for(config, fixture["tour"]):
        entry = config.section("rungs")[rung]
        if rung == "elo" and entry.get("status") == "available":
            out.append(
                elo_forecast(config, fixture, version, issue_time=issue_time, receipts=receipts)
            )
        elif entry.get("feature_route", {}).get("status") == "implemented" and model_bundle:
            from tennislab.live import feature_replay

            try:
                out.append(
                    feature_replay.predict(
                        config,
                        rung,
                        fixture,
                        version,
                        issue_time=issue_time,
                        model_bundle=model_bundle,
                    )
                )
            except feature_replay.ReplayUnavailable as error:
                out.append(
                    unavailable(
                        config,
                        rung,
                        fixture,
                        reason=str(error),
                        missing_bindings=[str(error)],
                    )
                )
        else:
            out.append(unavailable(config, rung, fixture))
    return out


def public_fixture(record: Mapping[str, Any]) -> dict[str, Any]:
    """The fixture as written to the batch and the ledger: no outcome field can exist."""
    payload = dict(record)
    for key in list(payload):
        if key in OUTCOME_LIKE:
            raise LiveError(f"fixture payload carries outcome-like field {key!r}")
    return payload
