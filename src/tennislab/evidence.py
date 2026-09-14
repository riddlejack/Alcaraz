"""Host-portable evidence records.

Equivalence records (``docs/equivalence/**.json``) and the ladder (``docs/ladder.json``)
embed diff excerpts and run roots that name the host: the research archive's root, this
repository's root and the interpreter's ``site-packages`` directory. Those strings are
machine evidence, not dependencies, but a tracked file must not carry a host path.

The tracked file under ``docs/`` is therefore a *representation*: the same bytes with
only the host-specific prefixes replaced by semantic placeholders. The original is kept
byte for byte in the ignored ``local/evidence/<same relative path>`` and listed in
``local/evidence/index.json`` (path, sha256, the concrete prefix behind each
placeholder). ``docs/equivalence/LOCAL_EVIDENCE.md`` is the tracked index of the
migrated originals.

The prefixes are derived at run time from ``TENNISLAB_ARCHIVE``, the repository root and
``sys.prefix``/``sysconfig``; nothing here names a host.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import sysconfig
from pathlib import Path

ARCHIVE_ROOT = "<ARCHIVE_ROOT>"
PRODUCT_ROOT = "<PRODUCT_ROOT>"
SITE_PACKAGES = "<SITE_PACKAGES>"
LOCAL_EVIDENCE = Path("local") / "evidence"
INDEX_NAME = "index.json"

Placeholders = tuple[tuple[str, str], ...]


def host_placeholders(*, repo_root: Path, archive_root: Path | None) -> Placeholders:
    """``(prefix, placeholder)`` pairs, longest prefix first.

    ``<SITE_PACKAGES>`` covers this interpreter's ``purelib`` and, when an archive root is
    given, the archive's own environment at the same relative location under a venv of
    the same name (the archive's stages ran from ``<ARCHIVE_ROOT>/.venv``; that layout is
    derived from ``sys.prefix``, not written down).
    """
    purelib = Path(sysconfig.get_paths()["purelib"])
    pairs: list[tuple[str, str]] = [
        (os.fspath(purelib), SITE_PACKAGES),
        (os.fspath(repo_root), PRODUCT_ROOT),
    ]
    if archive_root is not None:
        prefix = Path(sys.prefix)
        try:
            inside_prefix = purelib.relative_to(prefix)
        except ValueError:
            inside_prefix = None
        if inside_prefix is not None:
            pairs.append((os.fspath(archive_root / prefix.name / inside_prefix), SITE_PACKAGES))
        pairs.append((os.fspath(archive_root), ARCHIVE_ROOT))
    return tuple(sorted(pairs, key=lambda pair: -len(pair[0])))


def portable_text(text: str, placeholders: Placeholders) -> str:
    """``text`` with every host prefix replaced by its placeholder; nothing else changes."""
    for prefix, placeholder in placeholders:
        text = text.replace(prefix, placeholder)
    return text


def write_evidence(
    repo_root: Path, relative: str | Path, text: str, placeholders: Placeholders
) -> dict[str, str]:
    """Write ``text`` as the original under ``local/evidence/<relative>``, record it in
    the local index and write the placeholder representation to ``<repo_root>/<relative>``.

    Returns ``{"path": relative, "sha256": <digest of the original>}``.
    """
    relative_posix = Path(relative).as_posix()
    payload = text.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    store = repo_root / LOCAL_EVIDENCE
    original = store / relative_posix
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(payload)
    _update_index(store / INDEX_NAME, relative_posix, digest, placeholders)
    tracked = repo_root / relative_posix
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_bytes(portable_text(text, placeholders).encode("utf-8"))
    return {"path": relative_posix, "sha256": digest}


def _update_index(
    index_path: Path, relative_posix: str, digest: str, placeholders: Placeholders
) -> None:
    index: dict = {"records": {}, "placeholders": {}}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index.setdefault("records", {})
        index.setdefault("placeholders", {})
    index["records"][relative_posix] = {"sha256": digest}
    for prefix, placeholder in placeholders:
        seen = set(index["placeholders"].get(placeholder, []))
        seen.add(prefix)
        index["placeholders"][placeholder] = sorted(seen)
    index["records"] = dict(sorted(index["records"].items()))
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
