"""Acquisition attempts: one immutable directory and receipt per attempt.

``data/live/sources/<source_id>/attempts/<attempt_id>/`` holds ``receipt.json`` and the
retained bytes under ``raw/``. A retry gets a new directory; nothing is ever rewritten.
``latest.json`` names the last attempt whose receipt says ``complete`` and whose retained
files still hash-verify; an interrupted attempt keeps its receipt (``interrupted``) and
can never be named by the pointer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tennislab.chain.common import atomic_json, sha256
from tennislab.live.common import (
    LiveConfig,
    LiveError,
    iso_utc,
    read_json,
    relative_in,
    replace_pointer,
    stamp_id,
    utc_now,
)
from tennislab.live.transport import Response

RECEIPT_SCHEMA = "live-receipt-1"


@dataclass
class Attempt:
    source_id: str
    directory: Path
    attempt_id: str
    receipt: dict[str, Any]
    requests: list[dict[str, Any]] = field(default_factory=list)

    @property
    def raw_dir(self) -> Path:
        return self.directory / "raw"

    def retain(
        self, response: Response, *, name: str, qualification: dict[str, Any]
    ) -> dict[str, Any]:
        """Record one request; keep the body only on a 2xx status."""
        record: dict[str, Any] = {
            "requested_url": response.url,
            "status": response.status,
            "error_class": response.error_class,
            "headers": response.headers,
            "bytes": len(response.body),
            "sha256": response.sha256 if response.body else None,
            "request_started_utc": response.requested_at_utc,
            "response_received_utc": response.received_at_utc,
            "retained_path": None,
            "qualification": qualification,
        }
        for key in ("last-modified", "etag", "age", "cache-control", "x-cache"):
            if key in response.headers:
                record.setdefault("source_headers", {})[key] = response.headers[key]
        if response.status is not None and 200 <= response.status < 300 and response.body:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            target = self.raw_dir / name
            if target.exists():
                raise LiveError(f"retained file already exists in this attempt: {target}")
            target.write_bytes(response.body)
            record["retained_path"] = relative_in(self.directory, target)
        self.requests.append(record)
        return record

    def finish(self, status: str, *, note: str = "", extra: dict[str, Any] | None = None) -> Path:
        if status not in {"complete", "interrupted", "failed"}:
            raise LiveError(f"unknown attempt status {status!r}")
        self.receipt.update(
            {
                "status": status,
                "finished_utc": iso_utc(utc_now()),
                "requests": self.requests,
                "note": note,
                **(extra or {}),
            }
        )
        return Path(self.directory / "receipt.json")


def begin_attempt(
    config: LiveConfig, source_id: str, *, purpose: str, transport_name: str
) -> Attempt:
    started = utc_now()
    seed = hashlib.sha256(f"{source_id}|{purpose}|{iso_utc(started)}".encode()).hexdigest()
    attempt_id = stamp_id(started, seed)
    directory = config.sub("sources", source_id, "attempts", attempt_id)
    if directory.exists():
        raise LiveError(f"attempt directory already exists: {directory}")
    directory.mkdir(parents=True)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "source_id": source_id,
        "attempt_id": attempt_id,
        "purpose": purpose,
        "transport": transport_name,
        "started_utc": iso_utc(started),
        "status": "running",
        "live_config_sha256": config.sha256,
    }
    atomic_json(directory / "receipt.json", receipt)
    return Attempt(source_id, directory, attempt_id, receipt)


def write_receipt(attempt: Attempt) -> str:
    """Persist the finished receipt (the only rewrite of ``receipt.json``: running → final)."""
    if attempt.receipt.get("status") == "running":
        raise LiveError("finish the attempt before writing its receipt")
    return atomic_json(attempt.directory / "receipt.json", attempt.receipt)


def retained_hashes(attempt_dir: Path) -> dict[str, str]:
    raw = attempt_dir / "raw"
    if not raw.is_dir():
        return {}
    return {relative_in(attempt_dir, p): sha256(p) for p in sorted(raw.rglob("*")) if p.is_file()}


def validate_attempt(attempt_dir: Path) -> dict[str, Any]:
    """A complete receipt whose retained files still hash-verify; otherwise refuse."""
    receipt = read_json(attempt_dir / "receipt.json")
    if receipt.get("status") != "complete":
        raise LiveError(f"attempt {attempt_dir.name} is {receipt.get('status')!r}, not complete")
    observed = retained_hashes(attempt_dir)
    for request in receipt.get("requests", []):
        path = request.get("retained_path")
        if path is None:
            continue
        if observed.get(path) != request.get("sha256"):
            raise LiveError(f"retained file {path} in {attempt_dir.name} does not hash-verify")
    return receipt


def advance_latest(config: LiveConfig, source_id: str, attempt: Attempt) -> Path:
    receipt = validate_attempt(attempt.directory)
    pointer = config.sub("sources", source_id, "latest.json")
    replace_pointer(
        pointer,
        {
            "attempt_id": attempt.attempt_id,
            "receipt_sha256": sha256(attempt.directory / "receipt.json"),
            "finished_utc": receipt["finished_utc"],
        },
    )
    return pointer
