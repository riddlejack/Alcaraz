"""Results, the barrier and settlement: the only writer of a score.

``record_results`` turns a version's rows into provisional, final or corrected result
records for the fixtures the ledger knows. ``score`` verifies the chain, then for each
issued forecast checks the barrier (issued before an independently verified start,
proof attested before that start, result final) and writes proper scores for completed
matches only; everything else stays visible in the coverage table with its reason and is
never counted as confirmed prospective evidence. ``report`` refuses before any settlement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tennislab.chain.common import atomic_csv, atomic_json, canonical_hash
from tennislab.evaluation.scores import individual_scores
from tennislab.live.common import (
    LiveConfig,
    LiveError,
    iso_utc,
    parse_utc,
    read_json,
    safe_output_id,
    stamp_id,
    utc_now,
)
from tennislab.live.ledger import Ledger

SCORE_COLUMNS = (
    "settlement_id",
    "fixture_id",
    "rung",
    "p_a",
    "y_a",
    "log_loss",
    "brier",
    "issued_at_utc",
    "actual_start_utc",
    "proof_attested_utc",
    "result_record_sha256",
    "result_status",
)
COVERAGE_COLUMNS = ("settlement_id", "fixture_id", "rung", "cohort", "reason")
EXCLUDED_STATUSES = {"retired": "retired", "walkover": "walkover", "default": "default"}


def _latest(records: list[dict[str, Any]], *kinds: str) -> dict[str, Any] | None:
    chosen = [r for r in records if r["kind"] in kinds]
    return chosen[-1] if chosen else None


def record_results(config: LiveConfig, ledger: Ledger, version: dict[str, Any]) -> dict[str, int]:
    """Provisional on first sight; final when a second distinct source revision agrees;
    corrected when a later capture disagrees with a final result."""
    rows = {
        (r["tour"], r["event_id"], r["round"], r["player_a_id"], r["player_b_id"]): r
        for r in version["results"]
    }
    counts = {"provisional": 0, "final": 0, "corrected": 0, "pending": 0, "no_row": 0}
    for subject, records in ledger.subjects().items():
        qualified = _latest(records, "fixture_qualified")
        if qualified is None:
            continue
        fixture = qualified["payload"]
        row = rows.get(
            (
                fixture["tour"],
                fixture["event_id"],
                fixture["round"],
                fixture["player_a_id"],
                fixture["player_b_id"],
            )
        )
        if row is None:
            counts["no_row"] += 1
            continue
        if row["status"] == "pending" or row["winner_side"] not in {"a", "b"}:
            counts["pending"] += 1
            continue
        content = {
            "winner_side": row["winner_side"],
            "score": row["score"],
            "status": row["status"],
        }
        payload = {
            **content,
            "source_id": row["source_id"],
            "source_revision": row["source_revision"],
            "receipt_id": row["receipt_id"],
            "version_id": version["manifest"]["version_id"],
            "completion_upper_bound": row["completion_upper_bound"],
            "publication_upper_bound_utc": row["publication_upper_bound_utc"],
        }
        final = _latest(records, "result_final", "result_corrected")
        if final is not None:
            if all(final["payload"][k] == v for k, v in content.items()):
                continue  # agrees with the settled result; nothing to append
            if final["payload"]["source_revision"] == row["source_revision"]:
                continue
            ledger.append(
                "result_corrected", subject, {**payload, "supersedes": final["record_sha256"]}
            )
            counts["corrected"] += 1
            continue
        provisionals = [r for r in records if r["kind"] == "result_provisional"]
        agreeing = [
            p for p in provisionals if all(p["payload"][k] == v for k, v in content.items())
        ]
        distinct_revisions = {p["payload"]["source_revision"] for p in agreeing}
        if agreeing and row["source_revision"] not in distinct_revisions:
            ledger.append(
                "result_final",
                subject,
                {
                    **payload,
                    "confirmed_by": sorted(distinct_revisions | {row["source_revision"]}),
                    "finality_rule": config.section("settlement")["finality_rule"],
                },
            )
            counts["final"] += 1
            continue
        if any(
            p["payload"]["source_revision"] == row["source_revision"]
            and all(p["payload"][k] == v for k, v in content.items())
            for p in provisionals
        ):
            continue  # same capture already recorded
        ledger.append("result_provisional", subject, payload)
        counts["provisional"] += 1
    return counts


def barrier(
    records: list[dict[str, Any]], forecast: dict[str, Any]
) -> tuple[bool, str, dict[str, Any]]:
    """Whether this forecast may be scored, the reason if not, and the evidence used."""
    issued_at = parse_utc(forecast["recorded_at_utc"], label="issued_at")
    start = _latest(records, "start_verified")
    if start is None:
        return False, "unconfirmed:start_not_verified", {}
    actual_start = parse_utc(start["payload"]["actual_start_utc"], label="actual_start")
    if issued_at >= actual_start:
        return False, "unconfirmed:issued_after_start", {}
    proofs = [
        r
        for r in records
        if r["kind"] in {"proof_verified", "proof_failed"}
        and r["payload"].get("forecast_record_sha256") == forecast["record_sha256"]
    ]
    proof = proofs[-1] if proofs else None
    if proof is None:
        return False, "unconfirmed:proof_pending", {}
    if proof["kind"] == "proof_failed":
        return False, "unconfirmed:proof_failed", {}
    attested = parse_utc(proof["payload"]["attested_time_utc"], label="attested")
    if attested >= actual_start:
        return False, "unconfirmed:proof_late", {}
    result = _latest(records, "result_final", "result_corrected")
    if result is None:
        return False, "pending:result_not_final", {}
    return (
        True,
        "",
        {
            "actual_start_utc": iso_utc(actual_start),
            "proof_attested_utc": iso_utc(attested),
            "result": result,
        },
    )


def score(config: LiveConfig, ledger: Ledger, *, settlement_id: str | None = None) -> Path:
    ledger.verify()
    clip = float(config.section("settlement")["log_loss_clip"])
    now = utc_now()
    settlement_id = safe_output_id(
        settlement_id or stamp_id(now, canonical_hash({"settle": iso_utc(now)})),
        label="settlement id",
    )
    directory = config.sub("settlement", settlement_id)
    if directory.exists():
        raise LiveError(f"settlement {settlement_id} already exists")
    scores: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for subject, records in ledger.subjects().items():
        for forecast in [r for r in records if r["kind"] == "forecast_issued"]:
            rung = forecast["payload"]["rung"]
            ok, reason, evidence = barrier(records, forecast)
            if not ok:
                coverage.append(
                    {
                        "settlement_id": settlement_id,
                        "fixture_id": subject,
                        "rung": rung,
                        "cohort": reason.split(":")[0],
                        "reason": reason,
                    }
                )
                continue
            result = evidence["result"]
            status = result["payload"]["status"]
            if status in EXCLUDED_STATUSES:
                coverage.append(
                    {
                        "settlement_id": settlement_id,
                        "fixture_id": subject,
                        "rung": rung,
                        "cohort": "excluded",
                        "reason": f"estimand:{EXCLUDED_STATUSES[status]}",
                    }
                )
                continue
            if status != "completed":
                coverage.append(
                    {
                        "settlement_id": settlement_id,
                        "fixture_id": subject,
                        "rung": rung,
                        "cohort": "excluded",
                        "reason": f"status:{status}",
                    }
                )
                continue
            already = [
                r
                for r in records
                if r["kind"] == "score_reported"
                and r["payload"].get("result_record_sha256") == result["record_sha256"]
                and r["payload"].get("rung") == rung
            ]
            y_a = 1 if result["payload"]["winner_side"] == "a" else 0
            losses, brier, _ = individual_scores([forecast["payload"]["p_a"]], [y_a], clip)
            row = {
                "settlement_id": settlement_id,
                "fixture_id": subject,
                "rung": rung,
                "p_a": forecast["payload"]["p_a"],
                "y_a": y_a,
                "log_loss": float(losses[0]),
                "brier": float(brier[0]),
                "issued_at_utc": forecast["recorded_at_utc"],
                "actual_start_utc": evidence["actual_start_utc"],
                "proof_attested_utc": evidence["proof_attested_utc"],
                "result_record_sha256": result["record_sha256"],
                "result_status": status,
            }
            scores.append(row)
            coverage.append(
                {
                    "settlement_id": settlement_id,
                    "fixture_id": subject,
                    "rung": rung,
                    "cohort": "confirmed_scored",
                    "reason": "" if not already else "rescored:same_result_record",
                }
            )
            if not already:
                superseded = [
                    r
                    for r in records
                    if r["kind"] == "score_reported" and r["payload"].get("rung") == rung
                ]
                payload = {k: v for k, v in row.items() if k != "settlement_id"}
                payload["settlement_id"] = settlement_id
                payload["forecast_record_sha256"] = forecast["record_sha256"]
                if superseded:
                    payload["supersedes_score"] = superseded[-1]["record_sha256"]
                ledger.append("score_reported", subject, payload)
    directory.mkdir(parents=True)
    files = {
        "scores.csv": atomic_csv(directory / "scores.csv", SCORE_COLUMNS, scores),
        "coverage.csv": atomic_csv(directory / "coverage.csv", COVERAGE_COLUMNS, coverage),
    }
    summary = summarize(scores, coverage)
    atomic_json(
        directory / "manifest.json",
        {
            "schema_version": "live-settlement-1",
            "settlement_id": settlement_id,
            "written_utc": iso_utc(now),
            "ledger_head": ledger.verify()["head_sha256"],
            "files": files,
            "summary": summary,
            "estimand": config.section("settlement")["estimand"],
            "barrier": "chain verified; issued before verified actual start; proof attested before start; result final",
        },
    )
    return directory


def summarize(scores: list[dict[str, Any]], coverage: list[dict[str, Any]]) -> dict[str, Any]:
    by_rung: dict[str, dict[str, Any]] = {}
    for row in scores:
        entry = by_rung.setdefault(row["rung"], {"n": 0, "log_loss_sum": 0.0, "brier_sum": 0.0})
        entry["n"] += 1
        entry["log_loss_sum"] += float(row["log_loss"])
        entry["brier_sum"] += float(row["brier"])
    out = {
        rung: {
            "n": e["n"],
            "mean_log_loss": e["log_loss_sum"] / e["n"],
            "mean_brier": e["brier_sum"] / e["n"],
        }
        for rung, e in by_rung.items()
    }
    cohorts: dict[str, int] = {}
    for row in coverage:
        key = f"{row['cohort']}:{row['reason']}" if row["reason"] else row["cohort"]
        cohorts[key] = cohorts.get(key, 0) + 1
    return {
        "scored_by_rung": out,
        "coverage": cohorts,
        "caveat": "point estimates over the confirmed cohort only; no interval is claimed on fewer than the pre-registered count",
    }


def report(config: LiveConfig, ledger: Ledger, settlement_id: str | None = None) -> dict[str, Any]:
    ledger.verify()
    root = config.sub("settlement")
    candidates = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if settlement_id:
        settlement_id = safe_output_id(settlement_id, label="settlement id")
        candidates = [p for p in candidates if p.name == settlement_id]
    if not candidates:
        raise LiveError(
            "report refused: no settlement exists; run `tennislab settle score` after the barrier (verified start, verified proof, final result)"
        )
    manifest = read_json(candidates[-1] / "manifest.json")
    if manifest.get("ledger_head") != ledger.verify()["head_sha256"]:
        manifest["note"] = (
            "ledger has grown since this settlement; re-run settle score for a current view"
        )
    return manifest


def verify_start_payload(actual_start: str, source: str, evidence: str) -> dict[str, Any]:
    if not source.strip() or not evidence.strip():
        raise LiveError("start verification needs an independent source and an evidence reference")
    return {
        "actual_start_utc": iso_utc(parse_utc(actual_start, label="actual_start")),
        "source": source.strip(),
        "evidence": evidence.strip(),
        "basis": "independently established actual start; not the scheduled start",
    }
