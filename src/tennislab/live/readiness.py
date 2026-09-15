"""Deterministic, read-only D2 readiness assessment.

This module does not acquire data, advance a pointer, fit a model, or issue a forecast.
It verifies the bindings that already exist and names the remaining data/model work.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Any

from tennislab.chain.common import relative_to_root, require_hash
from tennislab.live import versions
from tennislab.live.common import LiveConfig, LiveError, parse_utc
from tennislab.live.fixtures import BOUND_HISTORY_FIELDS, PLAYED, history_binding
from tennislab.live.ledger import Ledger
from tennislab.ratings import elo


def _history(config: LiveConfig, tour: str) -> dict[str, Any]:
    try:
        path, digest, binding = history_binding(config, tour)
        require_hash(path, digest, label=f"{tour} history")
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = list(reader.fieldnames or [])
            required = [*elo.RESULT_COLUMNS, *BOUND_HISTORY_FIELDS]
            missing = [field for field in required if field not in header]
            if missing:
                raise LiveError(f"{tour} bound history lacks columns {missing}")
            rows = [dict(row) for row in reader]
        admitted = set(binding["admissible_completion_bases"])
        target_rows: list[dict[str, str]] = []
        candidates: list[dict[str, str]] = []
        withheld: Counter[str] = Counter()
        seen: set[tuple[str, ...]] = set()
        for index, row in enumerate(rows):
            row_tour = row["tour"].strip().upper()
            if row_tour != tour:
                continue
            target_rows.append(row)
            unresolved = row["overlap_unresolved"].strip().lower()
            if unresolved not in {"true", "false"}:
                raise LiveError(
                    f"{tour} bound history row {index} has invalid overlap_unresolved "
                    f"{unresolved!r}"
                )
            completion = row["completion_upper_bound"].strip()
            if completion:
                try:
                    dt.date.fromisoformat(completion)
                except ValueError as error:
                    raise LiveError(
                        f"{tour} bound history row {index} has invalid completion_upper_bound"
                    ) from error
            parse_utc(
                row["publication_upper_bound_utc"],
                label=f"{tour} history row {index} publication",
            )
            parse_utc(row["receipt_time_utc"], label=f"{tour} history row {index} receipt")
            if not row["date_basis"].strip():
                raise LiveError(f"{tour} bound history row {index} has no date_basis")
            if unresolved == "true" or not completion:
                withheld["overlap_unresolved"] += 1
                continue
            if row["completion_basis"].strip() not in admitted:
                withheld["completion_basis_not_admissible"] += 1
                continue
            if row["status"].strip().lower() not in PLAYED:
                withheld["not_played"] += 1
                continue
            identity = (
                completion,
                row["tournament"].strip(),
                row["round"].strip(),
                min(
                    row["winner_id"].strip() or row["winner_name"].strip().casefold(),
                    row["loser_id"].strip() or row["loser_name"].strip().casefold(),
                ),
                max(
                    row["winner_id"].strip() or row["winner_name"].strip().casefold(),
                    row["loser_id"].strip() or row["loser_name"].strip().casefold(),
                ),
            )
            if identity in seen:
                withheld["duplicate_identity"] += 1
                continue
            seen.add(identity)
            candidates.append({**row, "date": completion})
        elo.parse_results(candidates)
        return {
            "status": "ready",
            "path": relative_to_root(path, label=f"{tour} history"),
            "sha256": digest,
            "rows_in_file": len(rows),
            "tour_rows": len(target_rows),
            "eligible_candidate_rows": len(candidates),
            "withheld": dict(sorted(withheld.items())),
            "admissible_completion_bases": sorted(admitted),
        }
    except (LiveError, OSError, ValueError) as error:
        text = str(error)
        status = "pending" if "PENDING" in text or "not found" in text else "invalid"
        return {"status": status, "reason": text}


def _snapshot(config: LiveConfig) -> dict[str, Any]:
    try:
        directory = versions.latest_version(config)
        if directory is None:
            return {"status": "pending", "reason": "no versioned live snapshot exists"}
        loaded = versions.load_version(directory)
        tours = {
            name: sorted({str(row.get("tour", "")).upper() for row in rows if row.get("tour")})
            for name, rows in (
                ("results", loaded["results"]),
                ("serve_state", loaded["serve"]),
                ("rankings", loaded["rankings"]),
            )
        }
        missing = {name: sorted({"ATP", "WTA"} - set(present)) for name, present in tours.items()}
        blockers = [
            f"{name} lacks {', '.join(absent)}" for name, absent in missing.items() if absent
        ]
        return {
            "status": "ready" if not blockers else "partial",
            "version_id": directory.name,
            "content_sha256": loaded["manifest"]["content_sha256"],
            "counts": loaded["manifest"]["counts"],
            "tours": tours,
            "blockers": blockers,
            "serve_frontier_observed": loaded["manifest"].get("serve_frontier_observed", {}),
            "ranking_frontier_observed": loaded["manifest"].get("ranking_frontier_observed", {}),
        }
    except (LiveError, OSError, ValueError) as error:
        return {"status": "invalid", "reason": str(error)}


def assess(config_path: str | Path) -> dict[str, Any]:
    """Return a stable readiness report; absence is reported, never promoted to success."""
    config = LiveConfig(config_path)
    history = {tour: _history(config, tour) for tour in ("ATP", "WTA")}
    snapshot = _snapshot(config)
    rungs: dict[str, dict[str, Any]] = {}
    for rung, record in config.section("rungs").items():
        tour = "ATP" if rung.startswith("atp_") else "WTA" if rung.startswith("wta_") else None
        configured = record.get("status") == "available"
        if rung == "elo":
            snapshot_tours = snapshot.get("tours", {})
            ready_tours = [
                tour
                for tour, item in history.items()
                if item["status"] == "ready"
                and all(tour in snapshot_tours.get(table, []) for table in snapshot_tours)
                and bool(snapshot_tours)
            ]
            ready = configured and bool(ready_tours)
            rungs[rung] = {
                "status": "ready" if ready else "pending",
                "ready_tours": ready_tours,
                "reason": None if ready else "needs a bound history and verified snapshot",
            }
        else:
            ready = (
                configured and bool(record.get("runner")) and bool(record.get("artifact_manifest"))
            )
            rungs[rung] = {
                "status": "ready" if ready else "pending",
                "tour": tour,
                "reason": None
                if ready
                else record.get("reason", "runner or artifact manifest is not bound"),
            }
    try:
        ledger = Ledger(config).verify()
        ledger_status = {"status": "ready", **ledger}
    except (LiveError, OSError, ValueError) as error:
        ledger_status = {"status": "invalid", "reason": str(error)}
    blockers = []
    for tour, item in history.items():
        if item["status"] != "ready":
            blockers.append(f"{tour} history: {item.get('reason', item['status'])}")
    if snapshot["status"] != "ready":
        blockers.append(
            f"snapshot: {snapshot.get('reason', '; '.join(snapshot.get('blockers', [])))}"
        )
    for rung, item in rungs.items():
        if item["status"] != "ready":
            blockers.append(f"rung {rung}: {item['reason']}")
    if ledger_status["status"] != "ready":
        blockers.append(f"ledger: {ledger_status['reason']}")
    return {
        "schema_version": "d2-readiness-1",
        "status": "ready" if not blockers else "pending",
        "config_sha256": config.sha256,
        "history": history,
        "snapshot": snapshot,
        "rungs": rungs,
        "ledger": ledger_status,
        "settlement": {
            "status": "implemented",
            "barrier": "verified issue/proof before independently verified start; final result",
            "estimand": config.section("settlement")["estimand"],
        },
        "blockers": blockers,
    }
