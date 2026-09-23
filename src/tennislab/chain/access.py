"""Runtime record of the files a stage process opens for reading.

Decision RB14: a stage's outcome access is *derived from what it actually opened*, not
from a flag in the stage table. When the chain driver launches a stage it sets
``TENNISLAB_ACCESS_LOG`` to a file inside the stage directory; importing ``tennislab``
in that process then installs an audit hook (:func:`sys.addaudithook`) on the ``open``
event, which fires for ``open``, ``io.open``, ``gzip.open``, ``tarfile``, ``zipfile``,
``Path.read_*`` and every other reader built on them. Each read-open of a file inside the
workspace is recorded with the innermost ``tennislab`` frame that caused it, so the driver
can tell a hash-only read (``chain.common.sha256``) from a parse.

The outcome-history accessors (:mod:`tennislab.chain.labels`) append their receipts to
the same log through :func:`record_receipt`, so the driver can check every returned
horizon against the fold that consumed it.

The log is written once, at interpreter exit, as JSON lines: one ``open`` line per
distinct ``(path, opener)`` with a count, and one ``receipt`` line per accessor read.
Without the environment variable nothing is installed and nothing is written.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
from collections import Counter
from typing import Any

LOG_ENVIRONMENT_VARIABLE = "TENNISLAB_ACCESS_LOG"
SCHEMA_VERSION = 2
_state: dict[str, Any] = {"installed": False, "log": None, "root": None}
_opens: Counter[tuple[str, str, str]] = Counter()
_receipts: list[dict[str, Any]] = []


def _opener() -> str:
    """``module:function`` of the innermost ``tennislab`` frame, or ``''``."""
    frame = sys._getframe(2)
    while frame is not None:
        module = frame.f_globals.get("__name__", "")
        if module == "__main__":
            # A stage runs as ``python -m tennislab.<module>``: name it by its spec.
            spec = frame.f_globals.get("__spec__")
            module = getattr(spec, "name", "") or ""
        if module.startswith("tennislab.") and module != __name__:
            return f"{module}:{frame.f_code.co_name}"
        frame = frame.f_back
    return ""


def _relative(path: Any) -> str | None:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, str):
        return None
    root = _state["root"]
    absolute = os.path.normpath(os.path.abspath(path))
    if absolute == root or not absolute.startswith(root + os.sep):
        return None
    return os.path.relpath(absolute, root).replace(os.sep, "/")


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if event != "open":
        return
    try:
        path, mode, flags = args
        if mode is None:
            if int(flags or 0) & os.O_ACCMODE == os.O_WRONLY:
                return
            mode = "r+" if int(flags or 0) & os.O_ACCMODE == os.O_RDWR else "r"
        if "r" not in str(mode) and "+" not in str(mode):
            return
        relative = _relative(path)
        if relative is None:
            return
        _opens[(relative, str(mode), _opener())] += 1
    except Exception:  # an audit hook must never raise into the traced program
        return


def record_receipt(receipt: dict[str, Any]) -> None:
    """Append an accessor receipt to this process's log (no-op when not installed)."""
    if _state["installed"]:
        _receipts.append(dict(receipt))


def detach() -> None:
    """In a worker process a stage starts: keep recording, never write the log file.

    The stage's own process absorbs the worker's records (:func:`drain` in the worker,
    :func:`absorb` in the stage), so the one log still covers every file the stage's
    processes opened, and a worker's exit cannot overwrite it.
    """
    _state["log"] = None


def drain() -> dict[str, Any]:
    """This process's records since the last drain, as data; the counters are emptied."""
    records = {
        "opens": [
            [path, mode, opener, count] for (path, mode, opener), count in sorted(_opens.items())
        ],
        "receipts": [dict(receipt) for receipt in _receipts],
    }
    _opens.clear()
    _receipts.clear()
    return records


def absorb(records: dict[str, Any]) -> None:
    """Add a worker's drained records to this process's log."""
    for path, mode, opener, count in records["opens"]:
        _opens[(str(path), str(mode), str(opener))] += int(count)
    _receipts.extend(dict(receipt) for receipt in records["receipts"])


def _flush() -> None:
    log = _state["log"]
    if not log:
        return
    lines = [
        json.dumps(
            {"kind": "open", "path": path, "mode": mode, "opener": opener, "count": count},
            sort_keys=True,
        )
        for (path, mode, opener), count in sorted(_opens.items())
    ]
    lines += [json.dumps({"kind": "receipt", **receipt}, sort_keys=True) for receipt in _receipts]
    lines.append(
        json.dumps(
            {
                "kind": "complete",
                "schema": SCHEMA_VERSION,
                "opens": len(_opens),
                "receipts": len(_receipts),
            }
        )
    )
    with open(log, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def install() -> bool:
    """Install the hook when ``TENNISLAB_ACCESS_LOG`` names a log file."""
    log = os.environ.get(LOG_ENVIRONMENT_VARIABLE)
    if not log or _state["installed"]:
        return False
    workspace = os.environ.get("TENNISLAB_WORKSPACE") or os.getcwd()
    _state.update(
        {"installed": True, "log": log, "root": os.path.normpath(os.path.abspath(workspace))}
    )
    sys.addaudithook(_hook)
    atexit.register(_flush)
    return True


def read_log(path: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(opens, receipts)`` from a complete log; missing/incomplete evidence fails."""
    opens: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        entries = [json.loads(line) for line in handle if line.strip()]
    if not entries or entries[-1].get("kind") != "complete":
        raise ValueError("missing completed audit log (schema 2 required)")
    completion = entries.pop()
    for entry in entries:
        kind = entry.pop("kind", None)
        if kind not in {"open", "receipt"}:
            raise ValueError("invalid audit record kind")
        (opens if kind == "open" else receipts).append(entry)
    if completion != {
        "kind": "complete",
        "schema": SCHEMA_VERSION,
        "opens": len(opens),
        "receipts": len(receipts),
    }:
        raise ValueError("inconsistent audit completion record")
    return opens, receipts
