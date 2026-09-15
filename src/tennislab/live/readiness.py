"""Deterministic, read-only D2 readiness assessment.

This module does not acquire data, advance a pointer, fit a model, or issue a forecast.
It verifies the bindings that already exist and names the remaining data/model work.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from tennislab.chain.common import relative_to_root, require_hash
from tennislab.live import feature_replay, versions
from tennislab.live.common import LiveConfig, LiveError, parse_utc
from tennislab.live.fixtures import BOUND_HISTORY_FIELDS, PLAYED, history_binding
from tennislab.live.ledger import Ledger
from tennislab.models import release
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
            identity_date = row.get("model_event_date", "").strip() or row.get("date", "").strip()
            if not identity_date:
                raise LiveError(f"{tour} bound history row {index} has no modeled event date")
            try:
                modeled_event = dt.date.fromisoformat(identity_date)
            except ValueError as error:
                raise LiveError(
                    f"{tour} bound history row {index} has invalid modeled event date"
                ) from error
            if modeled_event > dt.date.fromisoformat(completion):
                raise LiveError(
                    f"{tour} bound history row {index} has modeled event date after "
                    "completion upper bound"
                )
            identity = (
                identity_date,
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
            candidates.append({**row, "date": identity_date})
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


def _snapshot(config: LiveConfig, history: dict[str, dict[str, Any]]) -> dict[str, Any]:
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
        incremental_results_rows = len(loaded["results"])
        if incremental_results_rows == 0:
            result_coverage = sorted(
                tour for tour, record in history.items() if record.get("status") == "ready"
            )
            results_mode = "bound_history_no_live_delta"
        else:
            result_coverage = tours["results"]
            results_mode = "incremental_version_results"
        coverage_tours = {**tours, "results": result_coverage}
        missing = {
            name: sorted({"ATP", "WTA"} - set(present)) for name, present in coverage_tours.items()
        }
        blockers = [
            f"{name} lacks {', '.join(absent)}" for name, absent in missing.items() if absent
        ]
        return {
            "status": "ready" if not blockers else "partial",
            "version_id": directory.name,
            "content_sha256": loaded["manifest"]["content_sha256"],
            "counts": loaded["manifest"]["counts"],
            "tours": tours,
            "coverage_tours": coverage_tours,
            "results_mode": results_mode,
            "incremental_results_rows": incremental_results_rows,
            "blockers": blockers,
            "serve_frontier_observed": loaded["manifest"].get("serve_frontier_observed", {}),
            "serve_frontier_observed_basis": "completion_upper_bound; not the modeled event date",
            "serve_model_event_frontier": {
                tour: max(
                    (
                        row["model_event_date"]
                        for row in loaded["serve"]
                        if row.get("tour") == tour and row.get("model_event_date")
                    ),
                    default=None,
                )
                for tour in ("ATP", "WTA")
            },
            "ranking_frontier_observed": loaded["manifest"].get("ranking_frontier_observed", {}),
        }
    except (LiveError, OSError, ValueError) as error:
        return {"status": "invalid", "reason": str(error)}


def _probe_values(columns: list[str]) -> dict[str, float]:
    """A deterministic asymmetric row containing no identity, label or outcome fields."""
    values: dict[str, float] = {}
    for index, column in enumerate(columns):
        if any(token in column for token in ("missing", "unseen", "stale")):
            value = 0.0
        elif column.startswith("context_"):
            value = 1.0 if column == "context_clay" else 0.0
        else:
            value = (1.0 if index % 2 == 0 else -1.0) * (index + 1) / 100.0
        values[column] = value
    return values


def _model_release(config: LiveConfig, bundle_path: str | Path | None) -> dict[str, Any]:
    expected = config.section("model_release")
    bindings = {name: record for name, record in config.section("rungs").items() if name != "elo"}
    declared = {
        "release_id": expected.get("release_id"),
        "archive_sha256": expected.get("archive_sha256"),
        "manifest_sha256": expected.get("manifest_sha256"),
        "runner": expected.get("runner"),
    }
    if bundle_path is None:
        return {
            "status": "pending",
            "binding": declared,
            "reason": "accepted bundle not supplied; pass --model-bundle to verify its bytes and interfaces",
        }
    try:
        root = Path(bundle_path).expanduser().resolve()
        manifest_path = root / "MANIFEST.json"
        observed_manifest_sha = release.sha256_file(manifest_path)
        if observed_manifest_sha != expected.get("manifest_sha256"):
            raise LiveError(
                "model release manifest SHA-256 mismatch: "
                f"expected {expected.get('manifest_sha256')}, observed {observed_manifest_sha}"
            )
        manifest = release.verify_bundle(root)
        if manifest.get("schema_version") != expected.get("manifest_schema_version"):
            raise LiveError("model release manifest schema differs from the live binding")
        if manifest.get("release_id") != expected.get("release_id"):
            raise LiveError("model release identity differs from the live binding")
        if expected.get("runner") != "tennislab.models.release.predict_feature_row":
            raise LiveError("model release runner is not the accepted prepared-row interface")

        probes: dict[str, dict[str, Any]] = {}
        for rung, record in sorted(bindings.items()):
            artifact = record.get("artifact_manifest")
            if not isinstance(artifact, dict):
                raise LiveError(f"rung {rung} has no artifact_manifest object")
            if artifact.get("release_id") != manifest.get("release_id"):
                raise LiveError(f"rung {rung} release identity differs")
            if artifact.get("rung") != rung:
                raise LiveError(f"rung {rung} artifact key differs")
            tour = str(artifact.get("tour", "")).upper()
            expected_years = artifact.get("target_years")
            if not isinstance(expected_years, list) or not expected_years:
                raise LiveError(f"rung {rung} has no target-year inventory")
            matches = [
                item
                for item in manifest["models"]
                if item.get("tour") == tour and item.get("rung") == rung
            ]
            observed_years = sorted(item.get("target_year") for item in matches)
            if observed_years != expected_years or len(matches) != len(expected_years):
                raise LiveError(
                    f"rung {rung} year inventory differs: expected {expected_years}, "
                    f"observed {observed_years}"
                )
            if record.get("runner") != expected.get("runner"):
                raise LiveError(f"rung {rung} runner differs from the release binding")

            probe_year = int(expected_years[-1])
            checkpoint = release.load_checkpoint(root, tour=tour, rung=rung, year=probe_year)
            columns = list(checkpoint.metadata["estimator_feature_names"])
            forbidden = {
                "winner",
                "loser",
                "score",
                "a_won",
                "result",
                "winner_side",
                "outcome",
            }
            if forbidden & set(columns):
                raise LiveError(f"rung {rung} estimator schema contains outcome fields")
            values = _probe_values(columns)
            prediction = release.predict_feature_row(
                checkpoint,
                values,
                season=str(probe_year),
                match_id=f"d2-readiness-{rung}-{probe_year}",
            )
            if not all(
                math.isfinite(value) and 0.0 <= value <= 1.0 for value in prediction.values()
            ):
                raise LiveError(f"rung {rung} probe emitted an invalid probability")
            probe_sha = hashlib.sha256(
                json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            probes[rung] = {
                "tour": tour,
                "target_years": expected_years,
                "probed_year": probe_year,
                "feature_count": len(columns),
                "outcome_fields_read": [],
                "feature_row_sha256": probe_sha,
                **prediction,
            }
        return {
            "status": "verified",
            "binding": declared,
            "bundle_path": str(root),
            "payload_files_verified": len(manifest["files"]),
            "models_verified": len(manifest["models"]),
            "interface_probes": probes,
        }
    except (LiveError, release.ReleaseBundleError, OSError, ValueError, TypeError) as error:
        return {"status": "invalid", "binding": declared, "reason": str(error)}


def assess(config_path: str | Path, *, model_bundle: str | Path | None = None) -> dict[str, Any]:
    """Return a stable readiness report; absence is reported, never promoted to success."""
    config = LiveConfig(config_path)
    history = {tour: _history(config, tour) for tour in ("ATP", "WTA")}
    snapshot = _snapshot(config, history)
    model_release = _model_release(config, model_bundle)
    rungs: dict[str, dict[str, Any]] = {}
    for rung, record in config.section("rungs").items():
        tour = "ATP" if rung.startswith("atp_") else "WTA" if rung.startswith("wta_") else None
        configured = record.get("status") in {"available", "route_implemented"}
        if rung == "elo":
            snapshot_tours = snapshot.get("coverage_tours", snapshot.get("tours", {}))
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
            artifact = record.get("artifact_manifest", {})
            artifact_verified = model_release["status"] == "verified" and rung in model_release.get(
                "interface_probes", {}
            )
            feature_route = record.get("feature_route", {})
            feature_ready = isinstance(feature_route, dict) and feature_route.get("status") in {
                "ready",
                "implemented",
            }
            route_inputs = feature_replay.binding_status(config, rung)
            snapshot_tours = snapshot.get("coverage_tours", snapshot.get("tours", {}))
            snapshot_ready = bool(snapshot_tours) and all(
                tour in snapshot_tours.get(table, ())
                for table in ("results", "serve_state", "rankings")
            )
            ready = (
                configured
                and artifact_verified
                and feature_ready
                and route_inputs["status"] == "ready"
                and snapshot_ready
            )
            rungs[rung] = {
                "status": "ready" if ready else "pending",
                "tour": tour,
                "artifact_status": "verified" if artifact_verified else "pending",
                "target_years": artifact.get("target_years", []),
                "feature_route_status": feature_route.get("status", "pending")
                if isinstance(feature_route, dict)
                else "invalid",
                "feature_input_status": route_inputs,
                "snapshot_tour_status": "ready" if snapshot_ready else "pending",
                "checkpoint_target_year": feature_route.get("checkpoint_target_year")
                if isinstance(feature_route, dict)
                else None,
                "fixture_year": feature_route.get("fixture_year")
                if isinstance(feature_route, dict)
                else None,
                "reason": None
                if ready
                else record.get("reason", "artifact, snapshot or exact feature input is not ready"),
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
    if model_release["status"] != "verified":
        blockers.append(f"model release: {model_release.get('reason', model_release['status'])}")
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
        "model_release": model_release,
        "rungs": rungs,
        "ledger": ledger_status,
        "settlement": {
            "status": "implemented",
            "barrier": "verified issue/proof before independently verified start; final result",
            "estimand": config.section("settlement")["estimand"],
        },
        "blockers": blockers,
    }
