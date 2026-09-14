"""Shared configuration, hashing and atomic-write helpers for every chain stage.

Ported from the archive's ``chain_common.py``. What changed: the repository root is the
declared workspace (``tennislab.config``) instead of a path computed from the source
file's location; modules are imported by name instead of by path at a pinned hash; the
code receipt a stage writes into its manifest names the package module and its file
hash instead of a repository-relative path.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab import __version__
from tennislab.config import WorkspaceError, workspace

PENDING = "PENDING"


class ChainError(ValueError):
    """Fail-closed configuration, path, span or provenance error."""


def read_config(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ChainError(f"configuration not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ChainError(f"configuration is not valid JSON: {path}: {error}") from error
    if not isinstance(document, dict):
        raise ChainError(f"configuration must be a JSON object: {path}")
    return document


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


EMPTY_DIGESTS = frozenset(
    {
        sha256_bytes(b""),
        canonical_hash({}),
        canonical_hash([]),
        canonical_hash(""),
        canonical_hash(None),
    }
)


def require_nonempty_digest(value: Any, *, label: str) -> str:
    """A manifest field must carry a real sha256, never a placeholder or the hash of nothing."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ChainError(f"{label}: not a sha256 hex digest: {value!r}")
    if value in EMPTY_DIGESTS:
        raise ChainError(f"{label}: digest of empty content is not acceptable: {value}")
    return value


def canonical_hash_nonempty(value: Any, *, label: str) -> str:
    return require_nonempty_digest(canonical_hash(value), label=label)


def resolve_under_root(value: str | Path, *, label: str) -> Path:
    """Resolve a config path under the workspace and refuse anything outside it."""
    try:
        return workspace().path(value, label=label)
    except WorkspaceError as error:
        raise ChainError(str(error)) from error


def resolve_output_under_root(value: str | Path, *, label: str = "output") -> Path:
    """Resolve a write destination under the workspace: lexical containment plus the
    physical check that no linked input directory becomes an output target."""
    try:
        return workspace().output_path(value, label=label)
    except WorkspaceError as error:
        raise ChainError(str(error)) from error


def relative_to_root(value: str | Path, *, label: str = "path") -> str:
    """The workspace-relative form of a path, for manifests and receipts."""
    try:
        return workspace().relative(value, label=label)
    except WorkspaceError as error:
        raise ChainError(str(error)) from error


def require_hash(path: Path, expected: str | None, *, label: str) -> str:
    observed = sha256(path)
    if expected is not None and observed != expected:
        raise ChainError(f"{label} hash mismatch: {path}: {observed} != {expected}")
    return observed


def code_receipt(module_name: str) -> dict[str, str]:
    """The provenance of the code that ran: module name, its file hash, the package version.

    Pass ``__name__``; when the module runs as ``python -m`` that is ``__main__`` and the
    real name is recovered from its import spec.
    """
    if module_name == "__main__":
        spec = getattr(sys.modules["__main__"], "__spec__", None)
        if spec is None or not spec.name:
            raise ChainError("cannot name the running module; run it with python -m")
        module_name = spec.name
    module = importlib.import_module(module_name)
    source = getattr(module, "__file__", None)
    if not source:
        raise ChainError(f"module has no source file: {module_name}")
    return {"module": module_name, "sha256": sha256(source), "package_version": __version__}


def declared_binding(entry: Mapping[str, Any], *, label: str) -> dict[str, str]:
    """A config field that pins code: the archive's ``{path, sha256}`` (resolved under the
    workspace and hash-verified) or the package's ``{module}`` (a code receipt)."""
    if "module" in entry:
        return code_receipt(str(entry["module"]))
    path = resolve_under_root(entry["path"], label=label)
    digest = require_hash(path, entry.get("sha256"), label=label)
    return {"path": relative_to_root(path), "sha256": digest}


def read_csv_rows(path: Path | str) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        rows = [dict(row) for row in reader]
    if not header:
        raise ChainError(f"empty CSV header: {path}")
    if len(header) != len(set(header)):
        raise ChainError(f"duplicate CSV header column: {path}")
    return header, rows


def atomic_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: serialize_cell(row.get(field)) for field in fields})
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return sha256(path)


def atomic_json(path: Path, value: Any) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return sha256(path)


def serialize_cell(value: Any) -> str:
    """Match SR02's ``path_runner._serialize``: 17 significant digits, no NaN/inf."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ChainError("cannot serialize nonfinite float")
        return format(value, ".17g")
    return str(value)


def year_plan(document: Mapping[str, Any]) -> Any:
    """The frozen YearPlan the models package owns, built from a config document."""
    from tennislab.models.year_plan import YearPlan

    if "year_plan" not in document:
        raise ChainError("configuration has no year_plan object")
    return YearPlan.from_mapping(document["year_plan"])
