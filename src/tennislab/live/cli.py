"""``tennislab update | fixture | forecast | ledger | settle`` — the live commands.

Every command is explicit and user-invoked; none schedules, polls or probes liveness.
``--replay <dir>`` rehearses acquisition against retained or synthetic responses through
the same code path as ``--network``; the default is replay-only, so nothing reaches the
network unless asked.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import ChainError, atomic_json, resolve_under_root, sha256
from tennislab.live import fixtures as fx
from tennislab.live import readiness, sources, versions
from tennislab.live import settle as st
from tennislab.live.common import (
    LiveConfig,
    LiveError,
    iso_utc,
    read_json,
    safe_output_id,
    utc_now,
)
from tennislab.live.identity import IdentityTable
from tennislab.live.ledger import Ledger, OfflineProofAdapter
from tennislab.live.receipts import advance_latest, begin_attempt, write_receipt
from tennislab.live.transport import ReplayTransport, Transport, UrllibTransport


def _identity(config: LiveConfig) -> IdentityTable:
    section = config.section("identity")
    players = resolve_under_root(section["players_csv"], label="players_csv")
    aliases = (
        resolve_under_root(section["aliases_csv"], label="aliases_csv")
        if section.get("aliases_csv")
        else None
    )
    if not players.is_file():
        raise LiveError(f"player master not found: {players}")
    return IdentityTable(players, aliases)


def _transport(config: LiveConfig, args: argparse.Namespace) -> Transport:
    if args.network and args.replay:
        raise LiveError("choose --replay <dir> or --network, not both")
    if args.network:
        source = config.source("wikipedia_results")
        return UrllibTransport(
            user_agent=str(source["user_agent"]),
            min_interval_seconds=float(source["min_interval_seconds"]),
            allowed_hosts={"api.wikimedia.org"},
        )
    if not args.replay:
        raise LiveError(
            "acquisition needs --replay <dir> (rehearsal) or --network (explicit live use)"
        )
    return ReplayTransport(
        resolve_under_root(args.replay, label="replay dir"), fail_after=args.fail_after
    )


# --- update ---------------------------------------------------------------------------------


def cmd_update(args: argparse.Namespace) -> int:
    config = LiveConfig(args.config)
    attempts: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    completeness: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    serve_rows = None
    ranking_rows = None
    if args.events:
        events = sources.read_events(resolve_under_root(args.events, label="events"))
        transport = _transport(config, args)
        attempt = begin_attempt(
            config, "wikipedia_results", purpose="results refresh", transport_name=transport.name
        )
        try:
            captures = sources.acquire_wikipedia(config, attempt, transport, events)
        except Exception as error:  # an interruption is a recorded outcome, never a silent one
            attempt.finish("interrupted", note=f"{type(error).__name__}: {error}")
            write_receipt(attempt)
            print(
                json.dumps(
                    {
                        "status": "interrupted",
                        "attempt_id": attempt.attempt_id,
                        "error": str(error),
                    },
                    sort_keys=True,
                )
            )
            return 1
        probe = sources.structural_probe(captures)
        atomic_json(attempt.directory / "structural_probe.json", probe)
        if args.probe_only:
            attempt.finish("complete", note="structural probe only; no parse, no version")
            write_receipt(attempt)
            print(
                json.dumps(
                    {"status": "probe", "attempt_id": attempt.attempt_id, "probe": probe},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        failed = [c["event"]["event_id"] for c in captures if "source" not in c]
        if failed:
            attempt.finish("failed", note=f"no usable body for events {failed}")
            write_receipt(attempt)
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "attempt_id": attempt.attempt_id,
                        "events_without_body": failed,
                    },
                    sort_keys=True,
                )
            )
            return 1
        attempt.finish("complete")
        write_receipt(attempt)
        advance_latest(config, "wikipedia_results", attempt)
        attempts["wikipedia_results"] = attempt.attempt_id
        receipt_id = f"wikipedia_results/{attempt.attempt_id}"
        results, quarantine, completeness = versions.normalize_captures(
            captures, _identity(config), receipt_id=receipt_id
        )
    else:
        latest = versions.latest_version(config)
        if latest is None:
            raise LiveError("no events file and no earlier version: nothing to update")
        previous = versions.load_version(latest)
        results, events = previous["results"], previous["events"]
        with (latest / "quarantine" / "rows.csv").open(newline="", encoding="utf-8") as handle:
            import csv

            quarantine = [dict(r) for r in csv.DictReader(handle)]
        completeness = read_json(latest / "completeness.json")
        attempts.update(previous["manifest"]["attempts"])
    if args.serve_feed:
        attempt = begin_attempt(
            config, "tennisabstract_serve", purpose="serve-state ingestion", transport_name="local"
        )
        feed_rows = sources.ingest_serve_feed(
            config, attempt, resolve_under_root(args.serve_feed, label="serve feed")
        )
        attempt.finish("complete")
        write_receipt(attempt)
        advance_latest(config, "tennisabstract_serve", attempt)
        attempts["tennisabstract_serve"] = attempt.attempt_id
        serve_rows = versions.attach_serve_windows(
            feed_rows, events, receipt_id=f"tennisabstract_serve/{attempt.attempt_id}"
        )
    if args.rankings:
        attempt = begin_attempt(
            config, "rankings_feed", purpose="rankings ingestion", transport_name="local"
        )
        ranking_rows = []
        for item in args.rankings:
            tour, _, path = item.partition("=")
            if tour.upper() not in {"ATP", "WTA"} or not path:
                raise LiveError(f"--rankings expects TOUR=PATH, got {item!r}")
            ranking_rows.extend(
                sources.ingest_rankings(
                    config, attempt, resolve_under_root(path, label="rankings"), tour=tour.upper()
                )
            )
        attempt.finish("complete")
        write_receipt(attempt)
        advance_latest(config, "rankings_feed", attempt)
        attempts["rankings_feed"] = attempt.attempt_id
        for row in ranking_rows:
            row["source_id"] = "rankings_feed"
            row["receipt_id"] = f"rankings_feed/{attempt.attempt_id}"
    directory = versions.write_version(
        config,
        results=results,
        serve=serve_rows,
        rankings=ranking_rows,
        quarantine=quarantine,
        completeness=completeness,
        attempts=attempts,
        events=events,
        note=args.note or "",
    )
    manifest = read_json(directory / "manifest.json")
    print(
        json.dumps(
            {
                "status": "ok",
                "version_id": manifest["version_id"],
                "no_change": manifest["no_change"],
                "counts": manifest["counts"],
                "diff": read_json(directory / "diff.json")["counts"],
                "serve_frontier_observed": manifest["serve_frontier_observed"],
                "carried_forward": manifest["carried_forward"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


# --- fixture and forecast ---------------------------------------------------------------------


def _batch_dir(config: LiveConfig, batch_id: str) -> Path:
    return config.sub("fixtures", safe_output_id(batch_id, label="batch id"))


FIXTURE_QUALIFICATION_FIELDS = (
    "fixture_id",
    "fixture_status",
    "exclusion_reasons",
    "tour",
    "event_id",
    "event_name",
    "level",
    "round",
    "surface",
    "best_of",
    "best_of_source",
    "scheduled_start_utc",
    "scheduled_start_local_date",
    "scheduled_start_source",
    "scheduled_start_timezone",
    "start_uncertainty_hours",
    "player_a_id",
    "player_b_id",
    "information_cutoff",
    "cutoff_rule",
    "version_id",
    "version_manifest_sha256",
    "live_config_sha256",
    "design_sha256",
    "repair_design_sha256",
    "repair2_design_sha256",
    "repair3_design_sha256",
)


def _verified_batch(
    config: LiveConfig, ledger: Ledger, batch_id: str
) -> tuple[Path, list[dict[str, Any]]]:
    ledger.verify()
    directory = _batch_dir(config, batch_id)
    fixture_path = directory / "fixtures.jsonl"
    manifest_path = directory / "manifest.json"
    if not fixture_path.is_file() or not manifest_path.is_file():
        raise LiveError(f"batch {batch_id} has no complete fixture binding")
    manifest = read_json(manifest_path)
    if manifest.get("batch_id") != batch_id:
        raise LiveError(f"batch {batch_id}: manifest batch id mismatch")
    if sha256(fixture_path) != manifest.get("fixtures_sha256"):
        raise LiveError(f"batch {batch_id}: fixtures bytes hash mismatch")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(fixture_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise LiveError(f"batch {batch_id}: blank fixture line {number}")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise LiveError(f"batch {batch_id}: fixture line {number} is not JSON") from error
        if record.get("batch_id") != batch_id or record.get("version_id") not in manifest.get(
            "version_ids", []
        ):
            raise LiveError(f"batch {batch_id}: fixture line {number} binding mismatch")
        if record.get("fixture_status") == "qualified":
            expected = fx.fixture_identity(
                record["tour"],
                record["event_id"],
                record["round"],
                record["player_a_id"],
                record["player_b_id"],
                record["scheduled_start_local_date"],
            )
            if expected != record.get("fixture_id"):
                raise LiveError(f"batch {batch_id}: fixture identity mismatch on line {number}")
            qualifications = [
                item for item in ledger.by_subject(expected) if item["kind"] == "fixture_qualified"
            ]
            if not qualifications:
                raise LiveError(f"batch {batch_id}: fixture has no ledger qualification")
            bound = qualifications[-1]["payload"]
            if any(bound.get(field) != record.get(field) for field in FIXTURE_QUALIFICATION_FIELDS):
                raise LiveError(
                    f"batch {batch_id}: qualification payload mismatch for fixture {expected[:12]}"
                )
        records.append(record)
    if len(records) != manifest.get("fixture_count"):
        raise LiveError(f"batch {batch_id}: fixture count does not match manifest")
    return directory, records


def cmd_fixture(args: argparse.Namespace) -> int:
    config = LiveConfig(args.config)
    latest = versions.latest_version(config)
    if latest is None:
        raise LiveError("no version exists; run `tennislab update` first")
    version = versions.load_version(latest)
    version_manifest_sha256 = sha256(latest / "manifest.json")
    events = {e["event_id"]: e for e in version["events"]}
    rows = fx.read_fixture_input(resolve_under_root(args.input, label="fixture input"))
    records = fx.construct(config, rows, _identity(config), events)
    directory = _batch_dir(config, args.batch_id)
    if directory.exists():
        raise LiveError(f"batch {args.batch_id} already exists; batches are immutable")
    ledger = Ledger(config)
    ledger.verify()
    directory.mkdir(parents=True)
    written = []
    batch_records = []
    for record in records:
        payload = fx.public_fixture({k: v for k, v in record.items() if k != "identity"})
        payload["version_id"] = version["manifest"]["version_id"]
        payload["version_manifest_sha256"] = version_manifest_sha256
        payload["batch_id"] = args.batch_id
        payload["live_config_sha256"] = config.sha256
        payload["design_sha256"] = config.design_hash()
        payload["repair_design_sha256"] = config.repair_design_hash()
        payload["repair2_design_sha256"] = config.repair2_design_hash()
        payload["repair3_design_sha256"] = config.repair3_design_hash()
        if record["fixture_status"] == "qualified":
            subject = record["fixture_id"]
            history = ledger.by_subject(subject)
            if not history:
                ledger.append("fixture_proposed", subject, payload)
                ledger.append("fixture_qualified", subject, payload)
            else:
                qualifications = [item for item in history if item["kind"] == "fixture_qualified"]
                if not qualifications:
                    raise LiveError(f"known fixture {subject[:12]} has no qualification record")
                original = qualifications[-1]["payload"]
                payload["version_id"] = original["version_id"]
                payload["version_manifest_sha256"] = original.get("version_manifest_sha256")
                if any(
                    original.get(field) != payload.get(field)
                    for field in FIXTURE_QUALIFICATION_FIELDS
                ):
                    raise LiveError(
                        f"known fixture {subject[:12]} does not match its original qualification"
                    )
            written.append(
                {
                    "fixture_ref": record["fixture_ref"],
                    "fixture_id": subject,
                    "status": "qualified",
                    "already_known": bool(history),
                }
            )
        else:
            subject = f"excluded:{args.batch_id}:{record['fixture_ref']}"
            ledger.append("fixture_proposed", subject, payload)
            ledger.append("fixture_excluded", subject, payload)
            written.append(
                {
                    "fixture_ref": record["fixture_ref"],
                    "fixture_id": None,
                    "status": "excluded",
                    "reasons": record["exclusion_reasons"],
                }
            )
        batch_records.append(payload)
    fixture_path = directory / "fixtures.jsonl"
    with fixture_path.open("w", encoding="utf-8") as handle:
        for record in batch_records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    atomic_json(
        directory / "manifest.json",
        {
            "batch_id": args.batch_id,
            "written_utc": iso_utc(utc_now()),
            "constructed_from_version": version["manifest"]["version_id"],
            "version_ids": sorted({record["version_id"] for record in batch_records}),
            "version_manifests": {
                record["version_id"]: record["version_manifest_sha256"] for record in batch_records
            },
            "fixture_count": len(batch_records),
            "fixtures_sha256": sha256(fixture_path),
            "fixtures": written,
            "live_config_sha256": config.sha256,
            "design_sha256": config.design_hash(),
            "repair_design_sha256": config.repair_design_hash(),
            "repair2_design_sha256": config.repair2_design_hash(),
            "repair3_design_sha256": config.repair3_design_hash(),
        },
    )
    print(json.dumps({"batch_id": args.batch_id, "fixtures": written}, indent=2, sort_keys=True))
    return 0


def cmd_forecast(args: argparse.Namespace) -> int:
    config = LiveConfig(args.config)
    ledger = Ledger(config)
    directory, fixtures = _verified_batch(config, ledger, args.batch_id)
    forecast_path = config.sub(
        "fixtures", safe_output_id(args.batch_id, label="batch id"), "forecasts.jsonl"
    )
    if forecast_path.exists():
        raise LiveError(f"batch {args.batch_id} already has forecasts; issue a new batch instead")
    proofs = OfflineProofAdapter(config)
    issue_time = utc_now()
    issued: list[dict[str, Any]] = []
    loaded_versions: dict[tuple[str, str], dict[str, Any]] = {}
    for fixture in fixtures:
        if fixture["fixture_status"] != "qualified":
            continue
        if fixture["scheduled_start_utc"] and iso_utc(issue_time) >= fixture["scheduled_start_utc"]:
            issued.append(
                {
                    "fixture_id": fixture["fixture_id"],
                    "rung": None,
                    "status": "refused_late",
                    "note": "scheduled start is not after the issue time",
                }
            )
            continue
        version_id = safe_output_id(str(fixture["version_id"]), label="version id")
        manifest_digest = str(fixture.get("version_manifest_sha256", ""))
        version_key = (version_id, manifest_digest)
        if version_key not in loaded_versions:
            loaded_versions[version_key] = versions.load_version(
                config.sub("versions", version_id),
                expected_manifest_sha256=manifest_digest,
            )
        version = loaded_versions[version_key]
        receipts = fx.receipt_times(version)
        for forecast in fx.forecast_all(
            config, fixture, version, issue_time=issue_time, receipts=receipts
        ):
            payload = {
                **forecast,
                "fixture_ref": fixture["fixture_ref"],
                "batch_id": args.batch_id,
                "issued_at_utc": iso_utc(issue_time),
                "scheduled_start_utc": fixture["scheduled_start_utc"],
            }
            kind = "forecast_issued" if forecast["status"] == "issued" else "forecast_unavailable"
            record = ledger.append(kind, fixture["fixture_id"], payload, recorded_at=issue_time)
            entry = {
                "fixture_id": fixture["fixture_id"],
                "rung": forecast["rung"],
                "status": forecast["status"],
                "record_sha256": record["record_sha256"],
            }
            if kind == "forecast_issued":
                entry["p_a"] = forecast["p_a"]
                request = proofs.request(record["record_sha256"])
                ledger.append(
                    "proof_requested",
                    fixture["fixture_id"],
                    {
                        "forecast_record_sha256": record["record_sha256"],
                        "digest": record["record_sha256"],
                        "adapter": proofs.name,
                        "request_file": request.name,
                        "scope": config.section("proof")["scope"],
                    },
                )
            issued.append(entry)
    try:
        with forecast_path.open("x", encoding="utf-8") as handle:
            for entry in issued:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except FileExistsError as error:
        raise LiveError(f"batch {args.batch_id} forecast output already exists") from error
    print(
        json.dumps(
            {"batch_id": args.batch_id, "issued_at_utc": iso_utc(issue_time), "forecasts": issued},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


# --- ledger ------------------------------------------------------------------------------------


def cmd_ledger(args: argparse.Namespace) -> int:
    config = LiveConfig(args.config)
    ledger = Ledger(config)
    if args.ledger_command == "verify":
        print(json.dumps(ledger.verify(), sort_keys=True))
        return 0
    if args.ledger_command == "show":
        subjects = ledger.subjects()
        view = {s: [r["kind"] for r in rs] for s, rs in subjects.items()}
        if args.fixture:
            view = {s: k for s, k in view.items() if s.startswith(args.fixture)}
        print(json.dumps(view, indent=2, sort_keys=True))
        return 0
    subject = _resolve_subject(ledger, args.fixture)
    if args.ledger_command == "start-verified":
        record = ledger.append(
            "start_verified",
            subject,
            st.verify_start_payload(args.actual_start, args.source, args.evidence),
        )
    elif args.ledger_command == "proof-verify":
        forecast = _forecast_record(ledger, subject, args.forecast_record)
        adapter = OfflineProofAdapter(config)
        verification = adapter.verify(
            forecast["record_sha256"], resolve_under_root(args.attestation, label="attestation")
        )
        kind = "proof_verified" if verification["ok"] else "proof_failed"
        record = ledger.append(
            kind, subject, {"forecast_record_sha256": forecast["record_sha256"], **verification}
        )
    elif args.ledger_command == "proof-fail":
        forecast = _forecast_record(ledger, subject, args.forecast_record)
        record = ledger.append(
            "proof_failed",
            subject,
            {
                "forecast_record_sha256": forecast["record_sha256"],
                "ok": False,
                "reason": args.reason or "declared failed",
            },
        )
    else:
        raise LiveError(f"unknown ledger command {args.ledger_command}")
    print(
        json.dumps(
            {
                "seq": record["seq"],
                "kind": record["kind"],
                "record_sha256": record["record_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


def _resolve_subject(ledger: Ledger, prefix: str | None) -> str:
    if not prefix:
        raise LiveError("--fixture <id or unique prefix> is required")
    matches = sorted(s for s in ledger.subjects() if s.startswith(prefix))
    if len(matches) != 1:
        raise LiveError(f"fixture prefix {prefix!r} matches {len(matches)} subjects")
    return matches[0]


def _forecast_record(ledger: Ledger, subject: str, prefix: str | None) -> dict[str, Any]:
    forecasts = [r for r in ledger.by_subject(subject) if r["kind"] == "forecast_issued"]
    if prefix:
        forecasts = [r for r in forecasts if r["record_sha256"].startswith(prefix)]
    if len(forecasts) != 1:
        raise LiveError(
            f"{len(forecasts)} forecast records match; pass --forecast-record <hash prefix>"
        )
    return forecasts[0]


# --- settle ------------------------------------------------------------------------------------


def _trusted_version_manifest_binding(config: LiveConfig, ledger: Ledger, version_id: str) -> str:
    """Reconcile chain-bound qualifications with the matching current pointer."""
    ledger.verify()
    qualification_digests = {
        str(record["payload"].get("version_manifest_sha256", ""))
        for record in ledger.records()
        if record["kind"] == "fixture_qualified"
        and record["payload"].get("version_id") == version_id
        and record["payload"].get("version_manifest_sha256")
    }
    if len(qualification_digests) > 1:
        raise LiveError(f"version {version_id}: conflicting trusted qualification digests")

    pointer_digest = None
    pointer = config.sub("versions", "latest.json")
    if pointer.is_file():
        record = read_json(pointer)
        pointed_id = safe_output_id(str(record.get("version_id", "")), label="latest version id")
        if pointed_id == version_id:
            pointer_digest = str(record.get("manifest_sha256", ""))

    if qualification_digests:
        qualification_digest = qualification_digests.pop()
        if pointer_digest is not None and pointer_digest != qualification_digest:
            raise LiveError(
                f"version {version_id}: latest pointer conflicts with trusted qualification digest"
            )
        return qualification_digest
    if pointer_digest is not None:
        return pointer_digest
    raise LiveError(f"version {version_id}: no prior trusted manifest digest")


def cmd_settle(args: argparse.Namespace) -> int:
    config = LiveConfig(args.config)
    ledger = Ledger(config)
    if args.settle_command == "results":
        explicit = args.version not in (None, "latest")
        version_id = safe_output_id(args.version, label="version id") if explicit else None
        target = (
            config.sub("versions", version_id)
            if explicit and version_id is not None
            else versions.latest_version(config)
        )
        if target is None or not target.is_dir():
            raise LiveError("no such version")
        resolved_version_id = version_id if explicit and version_id is not None else target.name
        expected_manifest = _trusted_version_manifest_binding(config, ledger, resolved_version_id)
        print(
            json.dumps(
                st.record_results(
                    config,
                    ledger,
                    versions.load_version(target, expected_manifest_sha256=expected_manifest),
                ),
                sort_keys=True,
            )
        )
        return 0
    if args.settle_command == "score":
        directory = st.score(config, ledger, settlement_id=args.settlement_id)
        print(
            json.dumps(read_json(directory / "manifest.json")["summary"], indent=2, sort_keys=True)
        )
        return 0
    if args.settle_command == "report":
        print(json.dumps(st.report(config, ledger, args.settlement_id), indent=2, sort_keys=True))
        return 0
    raise LiveError(f"unknown settle command {args.settle_command}")


def cmd_readiness(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            readiness.assess(args.config, model_bundle=args.model_bundle),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


# --- parser ------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tennislab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    update = sub.add_parser("update", help="versioned, user-invoked results/serve/rankings refresh")
    update.add_argument("--config", required=True)
    update.add_argument("--events", help="JSON list of declared events to refresh from Wikipedia")
    update.add_argument("--replay", help="directory of retained or synthetic responses (rehearsal)")
    update.add_argument(
        "--network", action="store_true", help="explicit live requests to api.wikimedia.org"
    )
    update.add_argument("--fail-after", type=int, default=None, help=argparse.SUPPRESS)
    update.add_argument(
        "--probe-only",
        action="store_true",
        help="structural probe: headers, templates, counts; no parse",
    )
    update.add_argument("--serve-feed", help="directory of parsed TAPLAYER01-layout CSV files")
    update.add_argument(
        "--rankings", nargs="*", metavar="TOUR=PATH", help="Sackmann-layout ranking files"
    )
    update.add_argument("--note", default="")
    update.set_defaults(func=cmd_update)

    fixture = sub.add_parser("fixture", help="construct outcome-free prospective fixtures")
    fixture.add_argument("--config", required=True)
    fixture.add_argument("--input", required=True, help="pending fixtures CSV")
    fixture.add_argument("--batch-id", required=True)
    fixture.set_defaults(func=cmd_fixture)

    forecast = sub.add_parser(
        "forecast", help="issue forecasts for a fixture batch into the ledger"
    )
    forecast.add_argument("--config", required=True)
    forecast.add_argument("--batch-id", required=True)
    forecast.set_defaults(func=cmd_forecast)

    ledger = sub.add_parser("ledger", help="verify or extend the prospective ledger")
    ledger.add_argument(
        "ledger_command", choices=["verify", "show", "start-verified", "proof-verify", "proof-fail"]
    )
    ledger.add_argument("--config", required=True)
    ledger.add_argument("--fixture", help="fixture id or unique prefix")
    ledger.add_argument(
        "--actual-start", help="independently established actual start (ISO, with offset)"
    )
    ledger.add_argument("--source", default="")
    ledger.add_argument("--evidence", default="")
    ledger.add_argument("--forecast-record", help="record hash prefix of the forecast")
    ledger.add_argument("--attestation", help="attestation JSON obtained outside this code")
    ledger.add_argument("--reason", default="")
    ledger.set_defaults(func=cmd_ledger)

    settle = sub.add_parser("settle", help="results, barrier-checked scores and the report")
    settle.add_argument("settle_command", choices=["results", "score", "report"])
    settle.add_argument("--config", required=True)
    settle.add_argument("--version", default="latest")
    settle.add_argument("--settlement-id", default=None)
    settle.set_defaults(func=cmd_settle)

    ready = sub.add_parser(
        "readiness", help="read-only D2 history, snapshot, rung and ledger readiness report"
    )
    ready.add_argument("--config", required=True)
    ready.add_argument(
        "--model-bundle",
        help="unpacked accepted incumbent release to verify; read-only and never persisted",
    )
    ready.set_defaults(func=cmd_readiness)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ChainError as error:
        print(f"tennislab {args.command}: {error}", file=sys.stderr)
        return 2
