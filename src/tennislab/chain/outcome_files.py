"""Classify a file a stage opened by *content*: does it carry match outcomes?

Used by the chain driver on the access log (:mod:`tennislab.chain.access`) to derive a
stage's observed outcome access. A tabular file is outcome-bearing when its header names
a column that reveals who won; a container (tarball, zip) is outcome-bearing because the
source archives inside are result files; JSON is inspected for the same keys. Nothing
here depends on a file's name or on which module opened it.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path
from typing import Any

from tennislab.chain.labels import OUTCOME_COLUMNS as _LABEL_OUTCOME_COLUMNS

OUTCOME_COLUMNS = frozenset({*_LABEL_OUTCOME_COLUMNS, "winner", "loser"})
CONTAINER_SUFFIXES = (".tar.gz", ".tgz", ".tar", ".zip")
# Innermost ``tennislab`` functions that read bytes to hash or count them, never parse.
HASH_ONLY_OPENERS = frozenset(
    {
        "tennislab.chain.common:sha256",
        "tennislab.chain.common:require_hash",
        "tennislab.chain.runner:bound_hash",
        "tennislab.chain.runner:_stage_manifest_hash",
        "tennislab.chain.runner:csv_data_rows",
        "tennislab.chain.runner:hash_tree",
    }
)


def _outcome_columns(header: list[str]) -> list[str]:
    return sorted({column for column in header if column.strip().lower() in OUTCOME_COLUMNS})


# JSON keys that name an outcome unambiguously; ``score`` is a match score in a table
# but a proper score in a JSON record, so it is a tabular marker only.
OUTCOME_JSON_KEYS = OUTCOME_COLUMNS - {"score", "winner", "loser"}


def _json_keys(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in OUTCOME_JSON_KEYS:
                found.add(str(key))
            _json_keys(child, found)
    elif isinstance(value, list):
        for child in value:
            _json_keys(child, found)


def _workbook_header(path: Path) -> list[str]:
    name = path.name.lower()
    if name.endswith(".xlsx"):
        import openpyxl

        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            header: list[str] = []
            for sheet in book.worksheets:
                for row in sheet.iter_rows(min_row=1, max_row=1, values_only=True):
                    header.extend(str(cell) for cell in row if cell is not None)
            return header
        finally:
            book.close()
    if name.endswith(".xls"):
        import xlrd

        book = xlrd.open_workbook(path, on_demand=True)
        header = []
        for sheet in book.sheets():
            if sheet.nrows:
                header.extend(str(cell.value) for cell in sheet.row(0))
        return header
    return []


def classify(path: Path) -> dict[str, Any]:
    """``{"content": kind, "outcome_columns": [...]}`` for one opened file.

    ``kind`` is ``outcome_columns`` (a tabular or JSON file naming an outcome column),
    ``container`` (an archive), ``clean`` (inspected, no outcome column) or
    ``uninspected`` (a format the classifier does not read).
    """
    name = path.name.lower()
    try:
        if name.endswith(CONTAINER_SUFFIXES):
            return {"content": "container", "outcome_columns": []}
        if name.endswith(".csv.gz"):
            with gzip.open(path, "rb") as handle:
                line = handle.readline().decode("utf-8", errors="replace")
            columns = _outcome_columns(next(csv.reader(io.StringIO(line, newline="")), []))
        elif name.endswith(".csv"):
            with path.open("rb") as handle:
                line = handle.readline().decode("utf-8", errors="replace")
            columns = _outcome_columns(next(csv.reader(io.StringIO(line, newline="")), []))
        elif name.endswith((".xlsx", ".xls")):
            columns = _outcome_columns(_workbook_header(path))
        elif name.endswith(".json"):
            found: set[str] = set()
            _json_keys(json.loads(path.read_text(encoding="utf-8")), found)
            columns = sorted(found)
        elif name.endswith(".jsonl"):
            found = set()
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        _json_keys(json.loads(line), found)
            columns = sorted(found)
        else:
            return {"content": "uninspected", "outcome_columns": []}
    except (OSError, ValueError, ImportError) as error:
        return {"content": "uninspected", "outcome_columns": [], "error": str(error)}
    if columns:
        return {"content": "outcome_columns", "outcome_columns": columns}
    return {"content": "clean", "outcome_columns": []}


def access_kind(opener: str) -> str:
    """``hash_only`` when the innermost tennislab frame only hashes or counts bytes."""
    return "hash_only" if opener in HASH_ONLY_OPENERS else "parsed"
