"""The four steps of ``tennislab current``, each driven by one JSON configuration.

``table``  builds the all-tier table (``table.csv.gz``, its numeric view ``table.npz``,
           ``columns.json`` and ``summary.json``) from the archive and the previous
           version's panel and tier stream.
``tune``   scores the serve/return filter's settings on early seasons (``tuning.json``).
``fit``    fits the all-tier model's raw forecasts, selects each window's candidate and
           slope, and writes the windows' calibrated forecasts (``members/``).
``pool``   writes the all-tier forecasts and the current Alcaraz per season
           (``alltier/<year>.csv`` and ``current/<year>.csv``).

Every path is resolved under the workspace; every input is hashed into the step's
``summary.json`` and a pinned hash is enforced.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.alltier import kalman, model, pool, source, table
from tennislab.chain.common import (
    ChainError,
    atomic_json,
    code_receipt,
    relative_to_root,
    require_hash,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
    sha256_bytes,
)

WORKERS_ENVIRONMENT_VARIABLE = "TENNISLAB_ALLTIER_WORKERS"
CODE_MODULES = (
    "tennislab.alltier.source",
    "tennislab.alltier.table",
    "tennislab.alltier.kalman",
    "tennislab.alltier.pointmodel",
    "tennislab.alltier.model",
    "tennislab.alltier.pool",
    "tennislab.alltier.stages",
)


def section_of(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = config.get(name)
    if not isinstance(section, dict):
        raise ChainError(f"configuration has no {name} object")
    return section


def code() -> dict[str, dict[str, str]]:
    return {name: code_receipt(name) for name in CODE_MODULES}


def fresh_output(section: Mapping[str, Any], marker: str) -> Path:
    output_dir = resolve_output_under_root(section["output_dir"], label="output_dir")
    if (output_dir / marker).exists():
        raise ChainError(f"refusing to overwrite {output_dir / marker}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def pinned_input(entry: Mapping[str, Any], label: str) -> tuple[Path, dict[str, str]]:
    path = resolve_under_root(entry["path"], label=label)
    digest = require_hash(path, entry.get("sha256"), label=label)
    return path, {"path": relative_to_root(path), "sha256": digest}


def workers(section: Mapping[str, Any]) -> int:
    text = os.environ.get(WORKERS_ENVIRONMENT_VARIABLE, str(section.get("workers", 1)))
    count = int(text)
    if count < 1:
        raise ChainError(f"{WORKERS_ENVIRONMENT_VARIABLE} must be positive: {count}")
    return count


# ------------------------------------------------------------------ table


def run_table(config: Mapping[str, Any]) -> dict[str, Any]:
    section = section_of(config, "table")
    started = time.monotonic()
    output_dir = fresh_output(section, "table.csv.gz")
    max_year = int(section["max_year"])
    rows = source.load_rows(section, max_year)
    loaded = time.monotonic()
    filter_section = section.get("serve_return_filter")
    settings = kalman.KalmanSettings.from_mapping(filter_section) if filter_section else None
    built = table.build(rows, settings)
    computed = time.monotonic()
    text = table.csv_text(built)
    table.write_csv_gz(output_dir / "table.csv.gz", text)
    np.savez_compressed(output_dir / "table.npz", **table.matrix_arrays(text, built.groups))
    columns = {
        **built.groups,
        "parameters": {**table.PARAMETERS, "serve_return_filter": filter_section},
    }
    tiers, counts = np.unique(built.columns["tier"], return_counts=True)
    summary = {
        **rows.manifest,
        "rows": len(built),
        "rows_by_tier": {str(t): int(c) for t, c in zip(tiers, counts, strict=True)},
        "columns": len(built.columns),
        "max_season": int(built.columns["season"].max()),
        "outputs": {
            "table.csv.gz": sha256(output_dir / "table.csv.gz"),
            "table.csv (decompressed)": sha256_bytes(text.encode("utf-8")),
            "table.npz": sha256(output_dir / "table.npz"),
            "columns.json": atomic_json(output_dir / "columns.json", columns),
        },
        "code": code(),
        "seconds": {
            "load": round(loaded - started, 1),
            "compute": round(computed - loaded, 1),
            "total": round(time.monotonic() - started, 1),
        },
    }
    atomic_json(output_dir / "summary.json", summary)
    return summary


# ------------------------------------------------------------------ tuning


def filter_rows(rows: source.SourceRows) -> dict[str, list[Any]]:
    """The observed rows in table order, as the filter's arguments."""
    rows = rows.subset(table.table_order(rows))
    status = np.array([table.parse_score(s)[0] for s in rows["score"]])
    ok, w_sv, w_sp, l_sv, l_sp = table.serve_counts(rows, status)
    kept = rows.subset(ok)
    return {
        "day": kept["day"].tolist(),
        "player_a": kept["player_a"].tolist(),
        "player_b": kept["player_b"].tolist(),
        "winner": kept["winner_id"].tolist(),
        "loser": kept["loser_id"].tolist(),
        "tiers": list(kept["tier"]),
        "surfaces": list(kept["surface"]),
        "observed": [True] * int(ok.sum()),
        "winner_serve_points": w_sv[ok].tolist(),
        "winner_serve_won": w_sp[ok].tolist(),
        "loser_serve_points": l_sv[ok].tolist(),
        "loser_serve_won": l_sp[ok].tolist(),
    }


def run_tuning(config: Mapping[str, Any]) -> dict[str, Any]:
    section = section_of(config, "tuning")
    started = time.monotonic()
    output_dir = fresh_output(section, "tuning.json")
    max_year = int(section["max_year"])
    first, last = section["score_window"]
    if dt.date.fromisoformat(last).year > max_year:
        raise ChainError("the score window ends after the last season loaded")
    rows = source.load_rows(section, max_year)
    window = (source.iso_day(first), source.iso_day(last))
    record = kalman.tune(filter_rows(rows), section["protocol"], window)
    document = {
        "max_year": max_year,
        "score_window": [first, last],
        "score": "sum over rows of the Binomial log-likelihood (no binomial coefficient) of "
        "both sides' serve points, p = sigmoid(eta) from the two-day state",
        **record,
        "inputs": {k: rows.manifest[k] for k in ("custody", "members", "previous_run")},
        "max_season_loaded": int(rows["season"].max()),
        "code": code(),
        "seconds": round(time.monotonic() - started, 1),
    }
    atomic_json(output_dir / "tuning.json", document)
    return document


# ------------------------------------------------------------------ fit


def previous_run(section: Mapping[str, Any]) -> model.PreviousRun:
    entry = section["previous_run"]
    root = resolve_under_root(entry["root"], label="previous_run")
    if not root.is_dir():
        raise ChainError(f"previous run root is not a directory: {root}")
    return model.PreviousRun(root, str(entry.get("learner", "hgb")), str(entry["bundle"]))


def member_path(output_dir: Path, year: int, window: int) -> Path:
    return output_dir / "members" / str(year) / f"window{window:02d}.csv"


def run_fit(config: Mapping[str, Any]) -> dict[str, Any]:
    section = section_of(config, "alltier")
    started = time.monotonic()
    output_dir = resolve_output_under_root(section["output_dir"], label="output_dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = model.ModelSettings.from_mapping(section)
    previous = previous_run(section)
    table_path, table_record = pinned_input(section["table"], "table")
    target_years = [int(y) for y in section["target_years"]]
    raw_years = settings.raw_years(target_years)
    # Raw files already written are reused, so they must come from the same table, targets
    # and settings.
    fingerprint = {
        "table_sha256": table_record["sha256"],
        "previous_run": relative_to_root(previous.root),
        "bundle": [previous.learner, previous.bundle],
        "windows": list(settings.windows),
        "training_tiers": list(settings.training_tiers),
        "candidates": settings.candidates,
    }
    fingerprint_path = output_dir / "fit_settings.json"
    if fingerprint_path.is_file():
        if json.loads(fingerprint_path.read_text(encoding="utf-8")) != fingerprint:
            raise ChainError(f"{output_dir} holds raw fits of other settings or another table")
    else:
        atomic_json(fingerprint_path, fingerprint)
    raw_files = model.run_raw_fits(
        table_path, previous, settings, raw_years, output_dir, workers(section)
    )
    fitted = time.monotonic()
    picks: dict[str, dict[str, Any]] = {}
    members: dict[str, str] = {}
    for window in settings.windows:
        raw = {
            candidate: {
                year: model.read_forecasts(
                    model.raw_path(output_dir, year, window, candidate), previous.targets(year)
                )
                for year in raw_years
            }
            for candidate in settings.candidates
        }
        for outer in target_years:
            decision = model.select_window(raw, previous, outer, settings)
            picks.setdefault(str(outer), {})[f"window{window:02d}"] = decision
            values = model.apply_slope(raw[decision["candidate"]][outer], decision["slope"])
            path = member_path(output_dir, outer, window)
            members[path.relative_to(output_dir).as_posix()] = model.write_forecasts(
                path, previous.targets(outer), values
            )
    summary = {
        "target_years": target_years,
        "raw_years": raw_years,
        "windows": list(settings.windows),
        "training_tiers": list(settings.training_tiers),
        "candidates": settings.candidates,
        "picks": picks,
        "inputs": {
            "table": table_record,
            "previous_run": {
                "root": relative_to_root(previous.root),
                "files": dict(sorted(previous.read.items())),
            },
        },
        "outputs": {"raw": raw_files, "members": members},
        "code": code(),
        "seconds": {
            "fits": round(fitted - started, 1),
            "total": round(time.monotonic() - started, 1),
        },
    }
    atomic_json(output_dir / "picks.json", picks)
    atomic_json(output_dir / "summary.json", summary)
    return summary


# ------------------------------------------------------------------ pool


def run_pool(config: Mapping[str, Any]) -> dict[str, Any]:
    section = section_of(config, "pool")
    output_dir = fresh_output(section, "summary.json")
    previous = previous_run(section)
    members_dir = resolve_under_root(section["alltier_dir"], label="alltier_dir")
    fit_summary_path = members_dir / "summary.json"
    fit_summary = json.loads(fit_summary_path.read_text(encoding="utf-8"))
    windows = [int(w) for w in fit_summary["windows"]]
    weights = {k: float(v) for k, v in section["weights"].items()}
    outputs: dict[str, str] = {}
    missing: dict[str, int] = {}
    for year in [int(y) for y in section["target_years"]]:
        keys = previous.targets(year)
        member_files = [member_path(members_dir, year, w) for w in windows]
        for path in member_files:
            expected = fit_summary["outputs"]["members"].get(
                path.relative_to(members_dir).as_posix()
            )
            require_hash(path, expected, label="member forecast")
        alltier, current, absent = pool.combine(
            [model.read_forecasts(path, keys) for path in member_files],
            previous.forecasts(year),
            weights,
            float(section["max_missing_share"]),
            label=str(year),
        )
        missing[str(year)] = absent
        for name, values in (("alltier", alltier), ("current", current)):
            path = output_dir / name / f"{year}.csv"
            outputs[f"{name}/{year}.csv"] = model.write_forecasts(path, keys, values)
    summary = {
        "weights": weights,
        "windows": windows,
        "targets_without_alltier_row": missing,
        "inputs": {
            "alltier_summary": {
                "path": relative_to_root(fit_summary_path),
                "sha256": sha256(fit_summary_path),
            },
            "previous_run": {
                "root": relative_to_root(previous.root),
                "files": dict(sorted(previous.read.items())),
            },
        },
        "outputs": outputs,
        "code": code(),
    }
    atomic_json(output_dir / "summary.json", summary)
    return summary


STEPS = {"table": run_table, "tune": run_tuning, "fit": run_fit, "pool": run_pool}
