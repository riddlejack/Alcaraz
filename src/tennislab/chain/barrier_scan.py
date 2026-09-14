"""The barrier's content scan: no metric-shaped artifact before the report stage.

Lane C2's T8b detector, made part of the chain (decision RB14). Every file a pre-barrier
stage wrote is inspected by *content*, never by file name: CSV headers (plain and gzip),
JSON objects and JSONL lines, recursively. A column or key that names a proper score,
an outcome rate or a paired score delta is a finding, whichever stage wrote it and
whichever year it scores. The barrier stage refuses to freeze a run tree with findings;
``verify`` repeats the scan.

What the scan does not see: formats other than CSV/JSON/JSONL (recorded as
``uninspected``), and a score hidden under a key the pattern does not name. The negative
controls in ``tests/test_barrier_gate.py`` plant a JSON metric, a nested CSV metric, a
JSONL metric and a gzip CSV metric and require a finding for each.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

METRIC = re.compile(
    r"(?:^|_)(?:log_?loss|brier(?:_score)?|auc|accuracy|ece|mse|rmse|mean_outcome"
    r"|observed_rate|outcome_rate|win_rate)(?:$|_)",
    re.I,
)
INSPECTED_SUFFIXES = (".csv", ".csv.gz", ".json", ".jsonl")
# Files whose only role is to describe the scan itself or the stage command.
SKIPPED_NAMES = frozenset({"stage_manifest.json", "access_log.jsonl"})


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def metric_paths(value: Any, prefix: str = "$") -> Iterator[str]:
    """Every JSON path at which a metric-shaped numeric leaf sits."""
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{prefix}.{key}"
            if METRIC.search(str(key)) and _is_number(child):
                yield here
            if key in ("metric", "metric_name") and isinstance(child, str) and METRIC.search(child):
                if any(_is_number(value.get(k)) for k in ("value", "score", "estimate")):
                    yield here
            if (
                key in ("delta", "equal_year_delta", "match_weighted_delta")
                and _is_number(child)
                and ("annual" in prefix or "treatment" in value or "control" in value)
            ):
                yield here
            if (
                key in ("score", "loss")
                and _is_number(child)
                and any(k in value for k in ("year", "outer_year", "model", "metric"))
            ):
                yield here
            yield from metric_paths(child, here)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from metric_paths(child, f"{prefix}[{index}]")


def _csv_header(payload: bytes) -> list[str]:
    text = payload.decode("utf-8", errors="replace")
    return next(csv.reader(io.StringIO(text, newline="")), [])


def scan_file(path: Path) -> list[str]:
    """Metric locations inside one file; an empty list means none were found."""
    name = path.name.lower()
    if name.endswith(".csv.gz"):
        with gzip.open(path, "rb") as handle:
            header = _csv_header(handle.readline())
        return _csv_hits(header)
    if name.endswith(".csv"):
        with path.open("rb") as handle:
            header = _csv_header(handle.readline())
        return _csv_hits(header)
    if name.endswith(".json"):
        return list(metric_paths(json.loads(path.read_text(encoding="utf-8"))))
    if name.endswith(".jsonl"):
        hits: list[str] = []
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if line.strip():
                    hits.extend(f"line:{number}:{h}" for h in metric_paths(json.loads(line)))
        return hits
    return []


def _csv_hits(header: list[str]) -> list[str]:
    hits = [f"header:{column}" for column in header if METRIC.search(column)]
    if {"metric", "value"} <= set(header):
        hits.append("header:metric/value long form")
    return hits


def inspectable(path: Path) -> bool:
    return path.name.lower().endswith(INSPECTED_SUFFIXES)


def scan_tree(run_root: Path, stages: list[str]) -> dict[str, Any]:
    """Scan the named stage directories under ``run_root``.

    Returns ``findings`` (one entry per file with metric locations), ``scanned`` (every
    inspected file) and ``uninspected`` (files of other formats, listed so the coverage
    limit is explicit).
    """
    findings: list[dict[str, Any]] = []
    scanned: list[str] = []
    uninspected: list[str] = []
    for stage in stages:
        directory = run_root / stage
        if not directory.is_dir():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            relative = path.relative_to(run_root).as_posix()
            if (
                path.parent == directory and path.name in SKIPPED_NAMES
            ) or "__pycache__" in relative:
                continue
            if not inspectable(path):
                uninspected.append(relative)
                continue
            scanned.append(relative)
            hits = scan_file(path)
            if hits:
                findings.append({"artifact": relative, "stage": stage, "metric_locations": hits})
    return {"findings": findings, "scanned": scanned, "uninspected": uninspected}
