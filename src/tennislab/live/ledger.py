"""The append-only, hash-chained prospective ledger and its transition rules.

One canonical JSON record per line. Every record carries the hash of its own content and
the hash of the previous record; the first record chains to a declared genesis digest.
``verify`` recomputes every hash, checks sequence contiguity and replays the transition
table (design §6), naming the first offending record. Nothing here ever rewrites a byte
that was written; corrections are later records that name what they supersede.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tennislab.chain.common import canonical_hash, require_nonempty_digest
from tennislab.live.common import LiveConfig, LiveError, iso_utc, parse_utc, utc_now

SCHEMA = "ledger-1"
LEDGER_FILE = "ledger.jsonl"
CHAIN_FIELDS = ("previous_record_sha256", "record_sha256")

KINDS = (
    "fixture_proposed",
    "fixture_qualified",
    "fixture_excluded",
    "forecast_issued",
    "forecast_unavailable",
    "proof_requested",
    "proof_verified",
    "proof_failed",
    "start_verified",
    "result_provisional",
    "result_final",
    "result_corrected",
    "score_reported",
)
# kind -> kinds that must already exist for the subject (any one of them)
REQUIRES: dict[str, tuple[str, ...]] = {
    "fixture_proposed": (),
    "fixture_qualified": ("fixture_proposed",),
    "fixture_excluded": ("fixture_proposed",),
    "forecast_issued": ("fixture_qualified",),
    "forecast_unavailable": ("fixture_qualified",),
    "proof_requested": ("forecast_issued",),
    "proof_verified": ("proof_requested",),
    "proof_failed": ("proof_requested",),
    "start_verified": ("fixture_qualified",),
    "result_provisional": ("fixture_qualified",),
    "result_final": ("result_provisional",),
    "result_corrected": ("result_final",),
    "score_reported": ("result_final", "result_corrected"),
}
FORBIDS: dict[str, tuple[str, ...]] = {
    "fixture_qualified": ("fixture_qualified", "fixture_excluded"),
    "fixture_excluded": ("fixture_qualified", "fixture_excluded"),
    "forecast_issued": ("fixture_excluded",),
    "forecast_unavailable": ("fixture_excluded",),
    "result_final": ("result_final",),
}


def genesis_digest(config: LiveConfig) -> str:
    text = str(config.section("ledger").get("genesis_text", ""))
    if not text:
        raise LiveError("ledger genesis_text is empty")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_digest(kind: str, subject_id: str, payload: Mapping[str, Any]) -> str:
    return canonical_hash({"kind": kind, "subject_id": subject_id, "payload": payload})


def record_digest(record: Mapping[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    return canonical_hash(body)


class Ledger:
    def __init__(self, config: LiveConfig) -> None:
        self.config = config
        self.path = config.sub("ledger", LEDGER_FILE)
        self.genesis = genesis_digest(config)

    # --- reading -----------------------------------------------------------------------
    def records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                raise LiveError(f"ledger line {number} is blank")
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise LiveError(f"ledger line {number} is not JSON: {error}") from error
        return out

    def verify(self) -> dict[str, Any]:
        """Recompute every digest, check chaining, sequence and transitions."""
        records = self.records()
        previous = self.genesis
        states: dict[str, list[str]] = {}
        for index, record in enumerate(records, 1):
            where = f"ledger record {index}"
            for field in (
                "schema_version",
                "seq",
                "kind",
                "subject_id",
                "recorded_at_utc",
                "payload",
                "content_sha256",
                *CHAIN_FIELDS,
            ):
                if field not in record:
                    raise LiveError(f"{where}: missing field {field!r}")
            if record["schema_version"] != SCHEMA:
                raise LiveError(f"{where}: schema {record['schema_version']!r} is not {SCHEMA}")
            if record["seq"] != index:
                raise LiveError(f"{where}: seq {record['seq']} is not {index}")
            for field in ("content_sha256", *CHAIN_FIELDS):
                require_nonempty_digest(record[field], label=f"{where}.{field}")
            if record["previous_record_sha256"] != previous:
                raise LiveError(
                    f"{where} ({record['kind']}, {record['subject_id'][:12]}): does not chain to its predecessor"
                )
            if record["content_sha256"] != content_digest(
                record["kind"], record["subject_id"], record["payload"]
            ):
                raise LiveError(
                    f"{where} ({record['kind']}): content digest does not match the payload"
                )
            if record["record_sha256"] != record_digest(record):
                raise LiveError(f"{where} ({record['kind']}): record digest does not match")
            self._check_transition(record, states.setdefault(record["subject_id"], []), where)
            states[record["subject_id"]].append(record["kind"])
            previous = record["record_sha256"]
        return {
            "ok": True,
            "records": len(records),
            "head_sha256": previous,
            "subjects": len(states),
        }

    def _check_transition(self, record: Mapping[str, Any], history: list[str], where: str) -> None:
        kind = record["kind"]
        if kind not in KINDS:
            raise LiveError(f"{where}: unknown kind {kind!r}")
        needed = REQUIRES[kind]
        if needed and not any(k in history for k in needed):
            raise LiveError(f"{where}: {kind} requires one of {list(needed)} for its subject")
        forbidden = FORBIDS.get(kind, ())
        if any(k in history for k in forbidden):
            raise LiveError(
                f"{where}: {kind} is not allowed after {[k for k in forbidden if k in history]}"
            )

    def by_subject(self, subject_id: str) -> list[dict[str, Any]]:
        return [r for r in self.records() if r["subject_id"] == subject_id]

    def subjects(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for record in self.records():
            out.setdefault(record["subject_id"], []).append(record)
        return out

    # --- writing -----------------------------------------------------------------------
    def append(
        self,
        kind: str,
        subject_id: str,
        payload: Mapping[str, Any],
        *,
        recorded_at: dt.datetime | None = None,
    ) -> dict[str, Any]:
        """Verify the whole chain, check the transition and idempotency, then append."""
        head = self.verify()
        history = [r for r in self.records() if r["subject_id"] == subject_id]
        kinds = [r["kind"] for r in history]
        digest = content_digest(kind, subject_id, payload)
        probe = {"kind": kind, "subject_id": subject_id}
        self._check_transition(probe, kinds, "new record")
        for earlier in history:
            if earlier["content_sha256"] == digest:
                raise LiveError(
                    f"duplicate record refused: identical {kind} already recorded for {subject_id[:12]} at seq {earlier['seq']}"
                )
        if kind in {"forecast_issued", "forecast_unavailable"}:
            rung = payload.get("rung")
            for earlier in history:
                if (
                    earlier["kind"] in {"forecast_issued", "forecast_unavailable"}
                    and earlier["payload"].get("rung") == rung
                ):
                    if payload.get("supersedes") != earlier["record_sha256"]:
                        raise LiveError(
                            f"duplicate issuance refused: rung {rung!r} already has a {earlier['kind']} record "
                            f"(seq {earlier['seq']}) for {subject_id[:12]}; a replacement must name it in 'supersedes'"
                        )
        record = {
            "schema_version": SCHEMA,
            "seq": head["records"] + 1,
            "kind": kind,
            "subject_id": subject_id,
            "recorded_at_utc": iso_utc(recorded_at or utc_now()),
            "payload": dict(payload),
            "content_sha256": digest,
            "previous_record_sha256": head["head_sha256"],
        }
        record["record_sha256"] = record_digest(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record


# --- proof adapter (offline, hash-only) ----------------------------------------------------


class OfflineProofAdapter:
    """Write a hash-only request file; verify an attestation obtained outside this code.

    Scope (D30): the digest is the ledger record hash; no data bytes are ever included.
    A live OpenTimestamps adapter is a separate step and is not implemented here.
    """

    name = "offline"

    def __init__(self, config: LiveConfig) -> None:
        self.directory = config.sub("proofs")

    def request(self, digest: str) -> Path:
        require_nonempty_digest(digest, label="proof digest")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{digest}.request.json"
        if path.exists():
            raise LiveError(f"proof already requested for {digest[:12]}")
        path.write_text(
            json.dumps(
                {
                    "digest": digest,
                    "requested_utc": iso_utc(utc_now()),
                    "adapter": self.name,
                    "payload": "hash-only",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def verify(self, digest: str, attestation_path: Path) -> dict[str, Any]:
        """The attestation is ``{digest, attested_time_utc, method, evidence}``; it must
        name the same digest, and the time must parse with an offset."""
        require_nonempty_digest(digest, label="proof digest")
        try:
            attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return {"ok": False, "reason": f"attestation unreadable: {error}"}
        if attestation.get("digest") != digest:
            return {"ok": False, "reason": "attestation names a different digest"}
        try:
            attested = parse_utc(
                str(attestation.get("attested_time_utc", "")), label="attested_time_utc"
            )
        except LiveError as error:
            return {"ok": False, "reason": str(error)}
        return {
            "ok": True,
            "attested_time_utc": iso_utc(attested),
            "method": str(attestation.get("method", "")),
            "evidence": str(attestation.get("evidence", "")),
            "attestation_sha256": hashlib.sha256(attestation_path.read_bytes()).hexdigest(),
        }
