"""Small shared helpers for the ported Lane C2 gates (``tests/test_gate_t*.py``).

Stdlib plus numpy only. Hashing goes through ``tennislab.chain.common`` so the gates
re-derive the same digests the chain records. Nothing here reads the archive.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import canonical_hash, sha256

__all__ = [
    "PLACEHOLDERS",
    "EMPTY_OBJECT_SHA256",
    "EMPTY_STRING_SHA256",
    "aligned_primary",
    "canonical_hash",
    "chain_document",
    "finite",
    "must_reject",
    "read_csv",
    "read_json",
    "sha256",
    "write_csv",
    "write_json",
]

EMPTY_STRING_SHA256 = hashlib.sha256(b"").hexdigest()
EMPTY_OBJECT_SHA256 = hashlib.sha256(b"{}").hexdigest()
EMPTY_ARRAY_SHA256 = hashlib.sha256(b"[]").hexdigest()
PLACEHOLDERS = frozenset(
    {EMPTY_STRING_SHA256, EMPTY_OBJECT_SHA256, EMPTY_ARRAY_SHA256, "0" * 64, ""}
)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(header))
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> Any:
    path = Path(path)
    assert path.is_file(), f"missing required receipt: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def chain_document(run: Mapping[str, Any]) -> dict[str, Any]:
    """The chain configuration the session fixture ran (``chain`` and ``year_plan``)."""
    return read_json(Path(run["config"]))


def finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def aligned_primary(row: Mapping[str, str]) -> bool:
    """The reporter's primary cohort predicate on a feature or label row."""
    year = row["calendar_year"]
    return (
        row["identity_tier"] == "primary"
        and row["primary_target"] == "1"
        and row["source_season"] == year
        and row["match_date"][:4] == year
    )


def must_reject(call: Callable[[], Any], contains: str) -> str:
    """The planted defect must fail the positive check with an assertion naming it.

    Any other exception is an error in the gate, never a detection.
    """
    try:
        call()
    except AssertionError as error:
        message = str(error)
        assert contains in message, f"wrong rejection: {message!r} lacks {contains!r}"
        return message
    raise AssertionError(f"planted defect escaped the positive check (expected {contains!r})")
