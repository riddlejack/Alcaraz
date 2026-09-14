"""Strict, case-insensitive readers used by the Lane G content boundary."""

from __future__ import annotations

import csv
import gzip
import io
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.benchmark.core import BenchmarkError

SUPPORTED_SUFFIXES = (".csv", ".csv.gz", ".json", ".jsonl")


def format_name(path: Path) -> str:
    name = path.name.lower()
    for suffix in SUPPORTED_SUFFIXES:
        if name.endswith(suffix):
            return suffix
    raise BenchmarkError(f"unsupported artifact format: {path}")


def _text_handle(path: Path):
    return (
        gzip.open(path, "rt", newline="", encoding="utf-8")
        if format_name(path) == ".csv.gz"
        else path.open("r", newline="", encoding="utf-8")
    )


def csv_header(path: Path) -> tuple[str, ...]:
    if format_name(path) not in {".csv", ".csv.gz"}:
        raise BenchmarkError(f"expected CSV input: {path}")
    with _text_handle(path) as handle:
        header = tuple(next(csv.reader(handle), ()))
    if not header or len(header) != len(set(header)):
        raise BenchmarkError(f"invalid CSV header: {path}")
    return header


def selected_csv_rows(
    path: Path,
    columns: Sequence[str],
    *,
    gate: Callable[[Mapping[str, str]], bool] | None = None,
) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Read only named column indexes; a gate may reject before callers parse values."""
    if format_name(path) not in {".csv", ".csv.gz"}:
        raise BenchmarkError(f"expected CSV input: {path}")
    requested = tuple(columns)
    if not requested or len(requested) != len(set(requested)):
        raise BenchmarkError("selected CSV columns must be unique and nonempty")
    with _text_handle(path) as handle:
        reader = csv.reader(handle)
        header = tuple(next(reader, ()))
        if not header or len(header) != len(set(header)):
            raise BenchmarkError(f"invalid CSV header: {path}")
        missing = [name for name in requested if name not in header]
        if missing:
            raise BenchmarkError(f"missing CSV columns in {path}: {missing}")
        indexes = tuple(header.index(name) for name in requested)
        rows: list[dict[str, str]] = []
        for number, source in enumerate(reader, 2):
            if len(source) != len(header):
                raise BenchmarkError(f"CSV row width mismatch: {path}:{number}")
            projected = {
                name: source[index] for name, index in zip(requested, indexes, strict=True)
            }
            if gate is None or gate(projected):
                rows.append(projected)
    return header, rows


def gated_selected_csv_rows(
    path: Path,
    gate_columns: Sequence[str],
    admitted_columns: Sequence[str],
    gate: Callable[[Mapping[str, str]], bool],
) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Project gate fields first and never index protected fields on rejected rows."""
    requested = tuple(dict.fromkeys((*gate_columns, *admitted_columns)))
    if format_name(path) not in {".csv", ".csv.gz"}:
        raise BenchmarkError(f"expected CSV input: {path}")
    with _text_handle(path) as handle:
        reader = csv.reader(handle)
        header = tuple(next(reader, ()))
        if not header or len(header) != len(set(header)):
            raise BenchmarkError(f"invalid CSV header: {path}")
        missing = [name for name in requested if name not in header]
        if missing:
            raise BenchmarkError(f"missing CSV columns in {path}: {missing}")
        gate_indexes = tuple(header.index(name) for name in gate_columns)
        admitted_indexes = tuple(header.index(name) for name in admitted_columns)
        rows: list[dict[str, str]] = []
        for number, source in enumerate(reader, 2):
            if len(source) != len(header):
                raise BenchmarkError(f"CSV row width mismatch: {path}:{number}")
            gate_row = {
                name: source[index] for name, index in zip(gate_columns, gate_indexes, strict=True)
            }
            if not gate(gate_row):
                continue
            admitted = dict(gate_row)
            admitted.update(
                {
                    name: source[index]
                    for name, index in zip(admitted_columns, admitted_indexes, strict=True)
                }
            )
            rows.append(admitted)
    return header, rows


def data_row_count(path: Path) -> int:
    kind = format_name(path)
    if kind in {".csv", ".csv.gz"}:
        with _text_handle(path) as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return sum(1 for _ in reader)
    if kind == ".jsonl":
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    value = json.loads(path.read_text(encoding="utf-8"))
    return len(value) if isinstance(value, list) else 1


def json_values(path: Path) -> Iterator[tuple[str, Any]]:
    kind = format_name(path)
    if kind == ".json":
        yield "$", json.loads(path.read_text(encoding="utf-8"))
        return
    if kind == ".jsonl":
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                yield f"line:{number}", json.loads(line)
        return
    raise BenchmarkError(f"expected JSON/JSONL input: {path}")


def csv_header_from_bytes(payload: bytes, *, compressed: bool) -> tuple[str, ...]:
    if compressed:
        payload = gzip.decompress(payload)
    return tuple(next(csv.reader(io.StringIO(payload.decode("utf-8"), newline="")), ()))
