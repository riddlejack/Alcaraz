"""Shared helpers for the live package: config, ids, clocks, atomic writes.

Wall clocks are read in exactly one place (:func:`utc_now`) so tests can pin them, and
they appear only in receipts, manifests and ledger records, never in normalized data.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    read_config,
    resolve_under_root,
    sha256,
)

CONFIG_SCHEMA = "live-config-1"
STAMP = "%Y%m%dT%H%M%SZ"


class LiveError(ChainError):
    """A fail-closed error in the live package."""


_clock: Callable[[], dt.datetime] | None = None


def set_clock(clock: Callable[[], dt.datetime] | None) -> None:
    """Pin the wall clock (tests) or restore the system clock (``None``)."""
    global _clock
    _clock = clock


def utc_now() -> dt.datetime:
    value = _clock() if _clock else dt.datetime.now(dt.UTC)
    if value.tzinfo is None:
        raise LiveError("clock returned a naive datetime")
    return value.astimezone(dt.UTC)


def iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def parse_utc(text: str, *, label: str) -> dt.datetime:
    """An ISO 8601 instant with an explicit offset; naive values are refused."""
    raw = (text or "").strip()
    if not raw:
        raise LiveError(f"{label}: empty timestamp")
    value = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise LiveError(f"{label}: timestamp {raw!r} has no timezone offset")
    return value.astimezone(dt.UTC)


def parse_date(text: str, *, label: str) -> dt.date:
    raw = (text or "").strip()
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as error:
        raise LiveError(f"{label}: not an ISO date: {raw!r}") from error


def stamp_id(moment: dt.datetime, digest: str) -> str:
    return f"{moment.astimezone(dt.UTC).strftime(STAMP)}-{digest[:8]}"


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return slug[:120] or "x"


class LiveConfig:
    """The manifest-bound live configuration, resolved under the workspace."""

    def __init__(self, path: Path | str) -> None:
        self.path = resolve_under_root(path, label="live config")
        self.document = read_config(self.path)
        if self.document.get("schema_version") != CONFIG_SCHEMA:
            raise LiveError(
                f"live config schema must be {CONFIG_SCHEMA}: {self.document.get('schema_version')!r}"
            )
        self.sha256 = sha256(self.path)
        self.root = resolve_under_root(self.document["workspace_dir"], label="live workspace")

    def section(self, name: str) -> dict[str, Any]:
        value = self.document.get(name)
        if not isinstance(value, dict):
            raise LiveError(f"live config has no {name} object")
        return value

    def source(self, source_id: str) -> dict[str, Any]:
        sources = self.section("sources")
        if source_id not in sources:
            raise LiveError(f"source {source_id!r} is not declared in the live config")
        return dict(sources[source_id])

    def require_source_status(self, source_id: str, *allowed: str) -> dict[str, Any]:
        record = self.source(source_id)
        status = record.get("status")
        if status not in allowed:
            reason = record.get("refuse_reason", "no qualification record for this use")
            raise LiveError(
                f"source {source_id!r} has status {status!r}; this command needs one of "
                f"{sorted(allowed)}: {reason}"
            )
        return record

    def lag_days(self) -> int:
        return int(self.section("cutoff")["lag_calendar_days"])

    def sub(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def design_hash(self) -> str | None:
        design = self.document.get("design")
        if not design:
            return None
        path = resolve_under_root(design, label="design")
        return sha256(path) if path.is_file() else None


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LiveError(f"missing file: {path}") from error
    except json.JSONDecodeError as error:
        raise LiveError(f"not valid JSON: {path}: {error}") from error


def replace_pointer(path: Path, value: Mapping[str, Any]) -> None:
    """Advance a ``latest`` pointer atomically (validate before calling)."""
    atomic_json(path, dict(value))


def relative_in(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
