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
_WRITE_MODES = frozenset("wax+")
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
            if int(flags or 0) & (os.O_WRONLY | os.O_RDWR):
                return
            mode = "r"
        if _WRITE_MODES & set(str(mode)):
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
    if not lines:
        return
    with open(log, "a", encoding="utf-8") as handle:
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
    """``(opens, receipts)`` from a log file; both empty when it does not exist."""
    opens: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = json.loads(line)
                kind = entry.pop("kind", None)
                (opens if kind == "open" else receipts).append(entry)
    except FileNotFoundError:
        pass
    return opens, receipts
