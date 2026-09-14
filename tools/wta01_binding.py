#!/usr/bin/env python3
"""Freeze and audit the repaired-product reconstruction of historical WTA01.

This tool never acquires data. ``freeze`` reads only the declared WTA01 bindings and
the retained historical oracle. ``audit`` independently checks the completed isolated
workspace, including forecast bytes, membership receipts and primary arithmetic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from itertools import zip_longest
from pathlib import Path
from typing import Any

from tennislab.evidence import host_placeholders, write_evidence
from tennislab.models.numerical import key_hash

ATTEMPT_ID = "WTA01-BINDING-002"
CONFIG_PATH = Path("configs/chains/wta01_2019_2024.json")
SOURCE_CHAIN = Path("experiments/runs/WTA01/attempt_001/primary/chain_wta01_primary_2019_2024.json")
SOURCE_RUN = Path("experiments/runs/WTA01/attempt_001/primary")
SOURCE_RUN_MANIFEST = Path("data/manifests/WTA01-run-001.json")
SECONDARY_FAILURE_RECORDS = (
    Path("experiments/runs/WTA01/attempt_001/STOP.md"),
    Path("experiments/runs/WTA01/attempt_001/STOP-secondary-2017.md"),
)
DESIGN_PATH = "experiments/WTA01.design.md"
DESIGN_COMMIT = "1f18978828293c745b93879ea7fae41c821b2900"
DESIGN_SHA256 = "0428751403cbd8b1d52ef65f83a1a630d0b61d94f446a3ea5e286354071950f0"
SOURCE_CHAIN_SHA256 = "e56713e7e3326db0803144e6eca7f3e444b5332953f07011490692c05f472f7a"
TARGET_YEARS = tuple(range(2019, 2025))
RAW_YEARS = tuple(range(2016, 2025))
EXPECTED_PRIMARY = {2019: 2337, 2020: 1019, 2021: 2363, 2022: 2324, 2023: 2453, 2024: 2404}
EXPECTED_PRICED = {2019: 2317, 2020: 1013, 2021: 2321, 2022: 2307, 2023: 2439, 2024: 2388}
FINAL_REPORT_FILES = (
    "primary.json",
    "pooled_metrics.csv",
    "annual_metrics.csv",
    "annual_contrasts.csv",
    "contrast_summary.csv",
    "bootstrap.csv",
    "reliability.csv",
    "report.md",
    "coverage.csv",
    "selection_diagnostics.csv",
)
ENTRYPOINT_MODULES = (
    "tennislab.chain.runner",
    "tennislab.panel.archive_panel",
    "tennislab.panel.wta_join",
    "tennislab.panel.prepare",
    "tennislab.panel.format_corrections",
    "tennislab.panel.wta_rules",
    "tennislab.dynamics.replay",
    "tennislab.dynamics.calibrate",
    "tennislab.panel.rankings",
    "tennislab.chronology.edition_index",
    "tennislab.features.base",
    "tennislab.features.sidecar",
    "tennislab.chain.configs",
    "tennislab.models.pipeline",
    "tennislab.evaluation.report",
)
CANONICAL_ARTIFACTS = {
    "source_panel": "run/archive_panel/source_panel.csv",
    "prepared_panel": "run/prepare_panel/panel.csv",
    "corrected_panel": "run/format_corrections/panel.csv",
    "rules": "run/rule_mapping/rules.csv",
    "sr02_history": "run/sr02_replay/selected_matches.csv",
    "sr03_forecasts": "run/sr03_calibration/predictions.csv",
    "sr03_fits": "run/sr03_calibration/fits.json",
    "sr03_training_membership": "run/sr03_calibration/training_membership.csv",
    "features": "run/features/features.csv",
    "labels": "run/features/labels.csv",
    "feature_dictionary": "run/features/column_dictionary.json",
    "sidecar": "run/sidecar/trait_latent_sidecar.csv",
    "predictor_config": "predictor_config/config.json",
}
FORECAST_GROUPS = {
    "raw": "raw/**/*.csv",
    "selected": "selected/**/*.csv",
    "shared_base": "shared_base/**/*.csv",
    "market": "market/**/*.csv",
}
EXPECTED_FORECAST_COUNTS = {"raw": 180, "selected": 48, "shared_base": 48, "market": 12}
STRUCTURAL_RECORD = Path("docs/equivalence/WTA01-binding_attempt_002/structural_binding.json")
AUDIT_RECORD = Path("docs/equivalence/WTA01-binding_attempt_002/historical_audit.json")


class BindingError(RuntimeError):
    """The historical binding or reconstruction differs from its frozen contract."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_tree(records: Mapping[str, Mapping[str, Any]]) -> str:
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(payload)


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def repository_root() -> Path:
    root = Path.cwd().resolve()
    if not (root / "pyproject.toml").is_file() or not (root / "src/tennislab").is_dir():
        raise BindingError("run this command from the tennis-lab repository root")
    return root


def archive_root(value: str | None) -> Path:
    candidate = value or os.environ.get("TENNISLAB_ARCHIVE")
    if not candidate:
        raise BindingError("pass --archive or set TENNISLAB_ARCHIVE")
    root = Path(candidate).resolve()
    if not (root / SOURCE_RUN).is_dir():
        raise BindingError(f"archive does not contain the retained WTA01 run: {root}")
    return root


def read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise BindingError(f"expected a JSON object: {path}")
    return document


def file_record(path: Path, relative: str) -> dict[str, Any]:
    if not path.is_file():
        raise BindingError(f"missing bound file: {path}")
    return {"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)}


def inventory(base: Path, files: Iterable[Path]) -> dict[str, Any]:
    records = {
        path.relative_to(base).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(files)
    }
    return {"count": len(records), "tree_sha256": canonical_tree(records), "files": records}


def git_blob(archive: Path, commit: str, relative: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", os.fspath(archive), "show", f"{commit}:{relative}"],
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _without_binding_metadata(document: Mapping[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(document))
    section = copied["chain"]
    for key in ("binding_attempt_id", "experiment_id", "frozen_source", "skip_stages"):
        section.pop(key, None)
    return copied


def verify_config_contract(repo: Path, archive: Path) -> dict[str, Any]:
    product = read_json(repo / CONFIG_PATH)
    source = read_json(archive / SOURCE_CHAIN)
    section = product.get("chain", {})
    plan = product.get("year_plan", {})
    checks = {
        "attempt_id": section.get("binding_attempt_id") == ATTEMPT_ID,
        "tour": section.get("tour") == "WTA",
        "experiment_id": section.get("experiment_id") == "WTA01",
        "target_years": tuple(plan.get("target_years", ())) == TARGET_YEARS,
        "panel_end_year": plan.get("panel_end_year") == 2024,
        "feature_end_year": plan.get("feature_end_year") == 2024,
        "history_floor_year": plan.get("history_floor_year") == 2011,
        "dynamic_count_floor": section.get("count_history_from_year") == 2016,
        "annual_eligible_floor": section.get("annual_eligible_floor_year") == 2016,
        "blocks": section.get("blocks") == ["base", "traits", "dynamic", "full"],
        "learners": section.get("learners") == ["ridge", "hgb"],
        "no_bridge": "bridge_seasons" not in section and "bridge_sources" not in section,
        "no_wta02_stage": section.get("skip_stages") == ["event_carry_forward"],
        "scientific_contract_equals_archive": _without_binding_metadata(product) == source,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BindingError(f"WTA01 config contract failed: {failed}")
    if sha256(archive / SOURCE_CHAIN) != SOURCE_CHAIN_SHA256:
        raise BindingError("archive historical chain hash drift")
    return checks


def primary_membership(run: Path) -> dict[int, tuple[tuple[str, str], ...]]:
    sidecar_path = run / "run/sidecar/trait_latent_sidecar.csv"
    features_path = run / "run/features/features.csv"
    with sidecar_path.open(newline="", encoding="utf-8") as handle:
        sidecar = {
            row["match_id"]: (
                row["sr02_selected_match_present"],
                row["dynamic_match_probability_a"],
            )
            for row in csv.DictReader(handle)
        }
    grouped: dict[int, list[tuple[str, str]]] = {year: [] for year in RAW_YEARS}
    with features_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            year = int(row["calendar_year"])
            if year not in grouped:
                continue
            dynamic = sidecar.get(row["match_id"], ("", ""))
            aligned = (
                row["primary_target"] == "1"
                and row["identity_tier"] == "primary"
                and row["source_season"] == row["calendar_year"]
                and row["match_date"][:4] == row["calendar_year"]
                and dynamic[0] == "1"
                and dynamic[1] != ""
            )
            if aligned:
                grouped[year].append((str(year), row["match_id"]))
    return {year: tuple(sorted(keys)) for year, keys in grouped.items()}


def csv_keys(path: Path) -> tuple[tuple[str, str], ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not {"season", "match_id"}.issubset(reader.fieldnames or ()):
            raise BindingError(f"forecast/key file has no season,match_id key: {path}")
        keys = tuple((row["season"], row["match_id"]) for row in reader)
    if len(keys) != len(set(keys)):
        raise BindingError(f"duplicate keys: {path}")
    return keys


def membership_record(run: Path) -> dict[str, Any]:
    primary = primary_membership(run)
    years: dict[str, Any] = {}
    for year in TARGET_YEARS:
        keys = primary[year]
        full = csv_keys(run / f"run/pipeline/selected/{year}/hgb/full.csv")
        base = csv_keys(run / f"run/pipeline/selected/{year}/hgb/base.csv")
        priced_all = csv_keys(run / f"run/pipeline/market/{year}/raw_ps.csv")
        priced = tuple(key for key in priced_all if key in set(keys))
        if not set(keys).issubset(full) or full != base:
            raise BindingError(f"full/base selected membership differs in {year}")
        if len(keys) != EXPECTED_PRIMARY[year] or len(priced) != EXPECTED_PRICED[year]:
            raise BindingError(f"WTA01 membership count differs in {year}")
        years[str(year)] = {
            "primary_rows": len(keys),
            "primary_membership_sha256": key_hash(keys),
            "priced_rows": len(priced),
            "priced_membership_sha256": key_hash(priced),
            "selected_prediction_rows_including_provisional": len(full),
            "selected_prediction_membership_sha256": key_hash(full),
        }
    return {
        "basis": "aligned_primary from features plus SR02 sidecar; price is a projection afterward",
        "years": years,
        "primary_rows": sum(item["primary_rows"] for item in years.values()),
        "priced_rows": sum(item["priced_rows"] for item in years.values()),
    }


def entrypoint_records(repo: Path) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for module in ENTRYPOINT_MODULES:
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            raise BindingError(f"cannot locate product module {module}")
        path = Path(spec.origin).resolve()
        try:
            relative = path.relative_to(repo).as_posix()
        except ValueError as error:
            raise BindingError(f"module {module} is not loaded from this product tree") from error
        records[module] = file_record(path, relative)
    return records


def structural_record(repo: Path, archive: Path) -> dict[str, Any]:
    checks = verify_config_contract(repo, archive)
    design = git_blob(archive, DESIGN_COMMIT, DESIGN_PATH)
    if sha256_bytes(design) != DESIGN_SHA256:
        raise BindingError("frozen design blob differs from the WTA01 run binding")
    config = read_json(repo / CONFIG_PATH)
    declared_inputs: dict[str, Any] = {}
    for name, binding in sorted(config["chain"]["inputs"].items()):
        path = binding.get("path")
        expected = binding.get("sha256")
        if not isinstance(path, str) or not isinstance(expected, str):
            raise BindingError(f"input {name} lacks a path/hash binding")
        if any(token in path.lower() for token in ("acquisition/ta", "data/raw/ta", "latest")):
            raise BindingError(f"forbidden live/latest binding in WTA01: {path}")
        payload = design if path == DESIGN_PATH else (archive / path).read_bytes()
        observed = sha256_bytes(payload)
        if observed != expected:
            raise BindingError(f"input hash mismatch for {name}: {observed} != {expected}")
        declared_inputs[name] = {"path": path, "bytes": len(payload), "sha256": observed}

    frozen = archive / SOURCE_RUN
    config_files = [archive / SOURCE_CHAIN, *sorted((frozen / "configs").glob("*.json"))]
    config_files += [
        frozen / "predictor_config/config.json",
        frozen / "reporting_config/reporting.json",
    ]
    configs = inventory(archive, config_files)
    pipeline = frozen / "run/pipeline"
    forecasts: dict[str, Any] = {}
    for name, pattern in FORECAST_GROUPS.items():
        item = inventory(pipeline, pipeline.glob(pattern))
        if item["count"] != EXPECTED_FORECAST_COUNTS[name]:
            raise BindingError(f"oracle {name} forecast count drift: {item['count']}")
        forecasts[name] = item
    training_keys = inventory(pipeline, pipeline.glob("fit_cache/*/training_keys.csv"))
    selections = inventory(pipeline, pipeline.glob("selection/**/*.json"))
    canonical = {
        name: file_record(frozen / relative, relative)
        for name, relative in CANONICAL_ARTIFACTS.items()
    }
    archive_status = git(archive, "status", "--short", "--untracked-files=no").splitlines()
    return {
        "attempt_id": ATTEMPT_ID,
        "status": "structurally_frozen_before_execution",
        "scope": "retrospective WTA01 2019-2024 product reconstruction; not E/G and not prospective evidence",
        "product": {
            "commit": git(repo, "rev-parse", "HEAD"),
            "config": file_record(repo / CONFIG_PATH, CONFIG_PATH.as_posix()),
            "lock": file_record(repo / "uv.lock", "uv.lock"),
            "entrypoints": entrypoint_records(repo),
            "package_sources_clean_against_head": not bool(
                git(repo, "status", "--short", "--untracked-files=no", "--", "src/tennislab")
            ),
        },
        "archive": {
            "commit": git(archive, "rev-parse", "HEAD"),
            "tracked_changes_outside_binding_preserved": archive_status,
            "source_chain": file_record(archive / SOURCE_CHAIN, SOURCE_CHAIN.as_posix()),
            "source_run_manifest": file_record(
                archive / SOURCE_RUN_MANIFEST, SOURCE_RUN_MANIFEST.as_posix()
            ),
            "frozen_design": {
                "path": DESIGN_PATH,
                "git_commit": DESIGN_COMMIT,
                "bytes": len(design),
                "sha256": DESIGN_SHA256,
                "current_amended_file_sha256": sha256(archive / DESIGN_PATH),
            },
        },
        "contract_checks": checks,
        "declared_inputs": declared_inputs,
        "frozen_configs": configs,
        "canonical_artifacts": canonical,
        "oracle_forecasts": forecasts,
        "oracle_training_keys": training_keys,
        "oracle_selection_records": selections,
        "oracle_membership": membership_record(frozen),
        "excluded": {
            "wta02_bridge_or_2025_2026_rows": True,
            "active_tennis_abstract_crawl": True,
            "latest_source_directories": True,
            "new_collection_or_source_ingestion": True,
        },
        "limitations": [
            "Historical WTA01 is exposed retrospective development, not prospective evidence.",
            "Most WTA scoring-rule eras were inferred from same-season outcome-bearing scores; only Wimbledon 2019-2021 has retained dated announcement custody.",
            "Raw 2016 has a wholly constant dynamic training window; early selected years inherit that limitation.",
            "The original two secondary attempts remain failed and withdrawn.",
            "Market prices have unknown clocks and the cohort is market-source-conditioned.",
        ],
    }


def _portable_write(repo: Path, archive: Path, relative: Path, record: Mapping[str, Any]) -> None:
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    write_evidence(repo, relative, text, host_placeholders(repo_root=repo, archive_root=archive))


def compare_group(expected: Path, observed: Path, pattern: str) -> dict[str, Any]:
    exp = {
        path.relative_to(expected).as_posix(): sha256(path)
        for path in sorted(expected.glob(pattern))
        if path.is_file()
    }
    obs = {
        path.relative_to(observed).as_posix(): sha256(path)
        for path in sorted(observed.glob(pattern))
        if path.is_file()
    }
    different = sorted(name for name in exp.keys() & obs.keys() if exp[name] != obs[name])
    return {
        "expected": len(exp),
        "observed": len(obs),
        "identical": len(exp.keys() & obs.keys()) - len(different),
        "different": different,
        "missing": sorted(exp.keys() - obs.keys()),
        "extra": sorted(obs.keys() - exp.keys()),
    }


def _record_fields_equal(
    expected: Mapping[str, Any], observed: Mapping[str, Any], fields: Sequence[str]
) -> bool:
    return all(expected.get(field) == observed.get(field) for field in fields)


def attempt_semantics(expected: Path, observed: Path) -> dict[str, Any]:
    fields = (
        "year",
        "learner",
        "block",
        "candidate_id",
        "status",
        "training_rows",
        "training_membership_sha256",
        "primary_target_rows",
        "primary_target_membership_sha256",
        "provisional_target_rows",
        "provisional_target_membership_sha256",
        "prediction_rows",
        "prediction_membership_sha256",
        "prediction_sha256",
        "outcome_labels_used_for_prediction",
    )
    mismatches: list[str] = []
    expected_files = sorted(expected.glob("attempts/**/*.json"))
    for path in expected_files:
        relative = path.relative_to(expected)
        counterpart = observed / relative
        if not counterpart.is_file() or not _record_fields_equal(
            read_json(path), read_json(counterpart), fields
        ):
            mismatches.append(relative.as_posix())
    return {
        "expected": len(expected_files),
        "matched": len(expected_files) - len(mismatches),
        "mismatches": mismatches,
    }


def training_key_semantics(expected: Path, observed: Path) -> dict[str, Any]:
    def collect(root: Path) -> dict[tuple[Any, ...], Path]:
        records: dict[tuple[Any, ...], Path] = {}
        for manifest_path in sorted(root.glob("fit_cache/*/fit_manifest.json")):
            document = read_json(manifest_path)
            identity = document["fit_identity"]
            key = (
                document["config_id"],
                identity["fit_cutoff"],
                identity["training_keys_sha256"],
                identity["training_rows"],
            )
            if key in records:
                raise BindingError(f"duplicate fit semantic key: {key}")
            records[key] = manifest_path.parent / document["training_keys_path"]
        return records

    exp = collect(expected)
    obs = collect(observed)
    missing = sorted(repr(key) for key in exp.keys() - obs.keys())
    extra = sorted(repr(key) for key in obs.keys() - exp.keys())
    different = sorted(
        repr(key) for key in exp.keys() & obs.keys() if sha256(exp[key]) != sha256(obs[key])
    )
    return {
        "expected": len(exp),
        "observed": len(obs),
        "identical": len(exp.keys() & obs.keys()) - len(different),
        "different": different,
        "missing": missing,
        "extra": extra,
    }


def selection_semantics(expected: Path, observed: Path) -> dict[str, Any]:
    fields = (
        "outer_year",
        "learner",
        "block",
        "status",
        "selection_years",
        "selection_rows",
        "selection_membership_sha256",
        "selection_cutoff_inclusive",
        "selected_candidate_id",
        "selected_slope",
        "outer_primary_rows",
        "outer_primary_membership_sha256",
        "outer_provisional_rows",
        "outer_provisional_membership_sha256",
        "selected_prediction_sha256",
        "selected_prediction_membership_sha256",
        "source_raw_prediction_sha256",
        "outer_labels_used",
    )
    mismatches: list[str] = []
    bad_key_receipts: list[str] = []
    expected_files = sorted(expected.glob("selection/**/*.json"))
    for path in expected_files:
        relative = path.relative_to(expected)
        counterpart = observed / relative
        if not counterpart.is_file():
            mismatches.append(relative.as_posix())
            continue
        source_doc, rebuilt = read_json(path), read_json(counterpart)
        if not _record_fields_equal(source_doc, rebuilt, fields):
            mismatches.append(relative.as_posix())
        key_path = rebuilt.get("selection_keys_path")
        if not isinstance(key_path, str):
            bad_key_receipts.append(relative.as_posix())
            continue
        keys = csv_keys(observed / key_path)
        if key_hash(keys) != source_doc["selection_membership_sha256"]:
            bad_key_receipts.append(relative.as_posix())
    return {
        "expected": len(expected_files),
        "matched": len(expected_files) - len(mismatches),
        "mismatches": mismatches,
        "selection_key_receipts_verified": len(expected_files) - len(bad_key_receipts),
        "bad_selection_key_receipts": bad_key_receipts,
    }


def market_selection_receipts(observed: Path) -> dict[str, Any]:
    receipt_path = observed / "run/report/selection_receipts.json"
    records = read_json(receipt_path).get("market_records")
    if not isinstance(records, list):
        raise BindingError("report selection receipts lack market_records")
    checked: list[dict[str, Any]] = []
    problems: list[str] = []
    pipeline = observed / "run/pipeline"
    for record in records:
        year = int(record["outer_year"])
        relative = record.get("selection_keys_path")
        if not isinstance(relative, str):
            problems.append(f"{year}: missing selection_keys_path")
            continue
        keys = csv_keys(pipeline / relative)
        checks = {
            "rows": len(keys) == record.get("selection_rows"),
            "membership": key_hash(keys) == record.get("selection_membership_sha256"),
            "selection_years": sorted({int(key[0]) for key in keys}) == list(range(year - 3, year)),
            "outer_labels_unused": record.get("outer_labels_used") is False,
        }
        problems.extend(f"{year}: {name}" for name, passed in checks.items() if not passed)
        checked.append(
            {
                "year": year,
                "path": relative,
                "rows": len(keys),
                "membership_sha256": key_hash(keys),
                "checks": checks,
            }
        )
    return {"expected": 6, "checked": checked, "problems": problems}


def generated_config_semantics(expected: Path, observed: Path) -> dict[str, Any]:
    source = read_json(expected)
    rebuilt = read_json(observed)
    changed_top_level = sorted(
        key for key in source.keys() | rebuilt.keys() if source.get(key) != rebuilt.get(key)
    )
    for document in (source, rebuilt):
        document.pop("code", None)
        document.pop("created_at_utc", None)
    return {
        "scientific_and_data_contract_equal": source == rebuilt,
        "changed_top_level_fields": changed_top_level,
    }


def join_market_semantics(expected: Path, observed: Path) -> dict[str, Any]:
    with (
        expected.open(newline="", encoding="utf-8") as source_handle,
        observed.open(newline="", encoding="utf-8") as rebuilt_handle,
    ):
        source_reader = csv.DictReader(source_handle)
        rebuilt_reader = csv.DictReader(rebuilt_handle)
        source_fields = source_reader.fieldnames or []
        rebuilt_fields = rebuilt_reader.fieldnames or []
        common = [field for field in source_fields if field in rebuilt_fields]
        differing_common_cells = 0
        rows = 0
        observed_seasons: set[int] = set()
        date_bases: set[str] = set()
        carried_rows = 0
        unequal_length = False
        for source_row, rebuilt_row in zip_longest(source_reader, rebuilt_reader):
            if source_row is None or rebuilt_row is None:
                unequal_length = True
                continue
            rows += 1
            differing_common_cells += sum(
                source_row[field] != rebuilt_row[field] for field in common
            )
            observed_seasons.add(int(rebuilt_row["season"]))
            date_bases.add(rebuilt_row["market_date_basis"])
            carried_rows += rebuilt_row["pairing_status"] == "accepted_carried_forward"
    added = sorted(set(rebuilt_fields) - set(source_fields))
    removed = sorted(set(source_fields) - set(rebuilt_fields))
    return {
        "rows": rows,
        "source_columns": len(source_fields),
        "rebuilt_columns": len(rebuilt_fields),
        "added_columns": added,
        "removed_columns": removed,
        "differing_common_cells": differing_common_cells,
        "unequal_length": unequal_length,
        "observed_season_min": min(observed_seasons),
        "observed_season_max": max(observed_seasons),
        "added_market_date_basis_values": sorted(date_bases),
        "accepted_carried_forward_rows": carried_rows,
        "historical_rows_semantically_equal": rows == 42905
        and not unequal_length
        and not removed
        and added == ["market_date_basis"]
        and differing_common_cells == 0
        and max(observed_seasons) == 2024
        and date_bases == {"tennis_data_reported_date"}
        and carried_rows == 0,
    }


def load_probabilities(path: Path) -> dict[tuple[str, str], float]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            (row["season"], row["match_id"]): float(row["p_a_wins"])
            for row in csv.DictReader(handle)
        }


def arithmetic_audit(run: Path) -> dict[str, Any]:
    primary = primary_membership(run)
    labels: dict[tuple[str, str], int] = {}
    with (run / "run/features/labels.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            labels[(row["calendar_year"], row["match_id"])] = int(row["a_won"])
    annual: dict[str, Any] = {}
    all_deltas: list[float] = []
    for year in TARGET_YEARS:
        keys = primary[year]
        full = load_probabilities(run / f"run/pipeline/selected/{year}/hgb/full.csv")
        base = load_probabilities(run / f"run/pipeline/selected/{year}/hgb/base.csv")
        deltas: list[float] = []
        for key in keys:
            y = labels[key]
            p_full = min(max(full[key], 1e-15), 1.0 - 1e-15)
            p_base = min(max(base[key], 1e-15), 1.0 - 1e-15)
            full_loss = -math.log(p_full if y else 1.0 - p_full)
            base_loss = -math.log(p_base if y else 1.0 - p_base)
            deltas.append(full_loss - base_loss)
        annual[str(year)] = {"n": len(deltas), "log_loss_delta": sum(deltas) / len(deltas)}
        all_deltas.extend(deltas)
    equal_year = sum(item["log_loss_delta"] for item in annual.values()) / len(annual)
    match_weighted = sum(all_deltas) / len(all_deltas)
    primary_report = read_json(run / "run/report/primary.json")
    expected_annual = primary_report["annual_deltas"]
    if not isinstance(expected_annual, dict):
        raise BindingError("primary report annual_deltas is not a year-to-delta mapping")
    tolerance = 2e-15
    matches = (
        abs(equal_year - primary_report["equal_year_log_loss_delta"]) <= tolerance
        and abs(match_weighted - primary_report["match_weighted_log_loss_delta"]) <= tolerance
        and all(
            abs(annual[year]["log_loss_delta"] - expected_annual[year]) <= tolerance
            for year in annual
        )
    )
    return {
        "basis": "independent row-wise log loss from rebuilt selected HGB full/base and labels, aligned-primary keys only",
        "annual": annual,
        "equal_year_log_loss_delta": equal_year,
        "match_weighted_log_loss_delta": match_weighted,
        "report_arithmetic_matches": matches,
        "tolerance": tolerance,
    }


def access_audit(run: Path, workspace: Path) -> dict[str, Any]:
    forbidden_tokens = ("/acquisition/ta", "/data/raw/ta", "wta02", "/latest")
    logs = sorted((run / "run").glob("*/access_log.jsonl"))
    offending: list[str] = []
    lines = 0
    for path in logs:
        for line in path.read_text(encoding="utf-8").splitlines():
            lines += 1
            lowered = line.lower()
            if any(token in lowered for token in forbidden_tokens):
                offending.append(f"{path.relative_to(workspace).as_posix()}:{lines}")
    return {
        "access_logs": len(logs),
        "records": lines,
        "forbidden_active_crawl_latest_or_wta02_references": offending,
    }


def historical_audit(repo: Path, archive: Path, workspace: Path) -> dict[str, Any]:
    expected = archive / SOURCE_RUN
    observed = workspace / "work/WTA01/run_001_primary"
    if not (observed / "run/report/primary.json").is_file():
        raise BindingError(f"completed WTA01 reconstruction not found: {observed}")
    expected_pipeline = expected / "run/pipeline"
    observed_pipeline = observed / "run/pipeline"
    forecasts = {
        name: compare_group(expected_pipeline, observed_pipeline, pattern)
        for name, pattern in FORECAST_GROUPS.items()
    }
    report = compare_group(expected / "run/report", observed / "run/report", "*")
    named_report = {
        name: {
            "expected_sha256": sha256(expected / "run/report" / name),
            "observed_sha256": sha256(observed / "run/report" / name),
            "identical": sha256(expected / "run/report" / name)
            == sha256(observed / "run/report" / name),
        }
        for name in FINAL_REPORT_FILES
    }
    canonical = {
        name: {
            "path": relative,
            "expected_sha256": sha256(expected / relative),
            "observed_sha256": sha256(observed / relative),
            "identical": sha256(expected / relative) == sha256(observed / relative),
            "required_byte_identity": name != "predictor_config",
        }
        for name, relative in CANONICAL_ARTIFACTS.items()
    }
    attempts = attempt_semantics(expected_pipeline, observed_pipeline)
    training = training_key_semantics(expected_pipeline, observed_pipeline)
    selections = selection_semantics(expected_pipeline, observed_pipeline)
    market_receipts = market_selection_receipts(observed)
    predictor_semantics = generated_config_semantics(
        expected / "predictor_config/config.json", observed / "predictor_config/config.json"
    )
    join_semantics = join_market_semantics(
        expected / "run/join/market_rows.csv", observed / "run/join/market_rows.csv"
    )
    membership = membership_record(observed)
    arithmetic = arithmetic_audit(observed)
    access = access_audit(observed, workspace)
    expected_receipt_extras = {f"market/{year}/selection_keys.csv" for year in TARGET_YEARS}
    forecast_ok = (
        sum(item["identical"] for item in forecasts.values()) == 288
        and all(not item["different"] and not item["missing"] for item in forecasts.values())
        and set(forecasts["market"]["extra"]) == expected_receipt_extras
        and all(not forecasts[name]["extra"] for name in ("raw", "selected", "shared_base"))
    )
    acceptance_checks = {
        "all_288_forecasts_byte_identical": forecast_ok,
        "ten_named_final_report_files_byte_identical": all(
            item["identical"] for item in named_report.values()
        ),
        "canonical_inputs_and_intermediates_byte_identical": all(
            item["identical"] for item in canonical.values() if item["required_byte_identity"]
        ),
        "all_180_attempt_semantics_match": attempts["expected"] == 180
        and attempts["matched"] == 180,
        "all_180_training_key_files_semantically_and_byte_match": training["expected"] == 180
        and training["observed"] == 180
        and training["identical"] == 180,
        "all_48_selection_records_and_key_receipts_match": selections["expected"] == 48
        and selections["matched"] == 48
        and selections["selection_key_receipts_verified"] == 48,
        "all_6_market_selection_key_receipts_match": market_receipts["expected"] == 6
        and len(market_receipts["checked"]) == 6
        and not market_receipts["problems"],
        "generated_predictor_scientific_and_data_contract_match": predictor_semantics[
            "scientific_and_data_contract_equal"
        ],
        "join_market_rows_semantically_match_without_bridge_rows": join_semantics[
            "historical_rows_semantically_equal"
        ],
        "target_and_priced_membership_exact": membership["primary_rows"] == 12900
        and membership["priced_rows"] == 12785,
        "primary_arithmetic_independently_recomputed": arithmetic["report_arithmetic_matches"],
        "active_crawl_latest_and_wta02_not_read": not access[
            "forbidden_active_crawl_latest_or_wta02_references"
        ],
    }
    return {
        "attempt_id": ATTEMPT_ID,
        "status": "historical_reconstruction_passed"
        if all(acceptance_checks.values())
        else "failed",
        "scope": "retrospective WTA01 product reconstruction only; this does not accept E/G or establish scientific validity",
        "product_commit_at_audit": git(repo, "rev-parse", "HEAD"),
        "archive_commit_at_audit": git(archive, "rev-parse", "HEAD"),
        "workspace": os.fspath(workspace),
        "acceptance_checks": acceptance_checks,
        "forecast_equivalence": forecasts,
        "report_tree_comparator": report,
        "named_report_equivalence": named_report,
        "canonical_artifact_equivalence": canonical,
        "attempt_semantics": attempts,
        "training_keys": training,
        "selection_records": selections,
        "market_selection_receipts": market_receipts,
        "generated_predictor_config_semantics": predictor_semantics,
        "join_market_rows_semantics": join_semantics,
        "membership": membership,
        "independent_arithmetic": arithmetic,
        "access_audit": access,
        "unmatched_artifacts": {
            "forecast_different": {
                name: item["different"] for name, item in forecasts.items() if item["different"]
            },
            "forecast_missing": {
                name: item["missing"] for name, item in forecasts.items() if item["missing"]
            },
            "forecast_extra": {
                name: item["extra"] for name, item in forecasts.items() if item["extra"]
            },
            "report_different": report["different"],
            "report_missing": report["missing"],
            "report_extra": report["extra"],
        },
        "semantic_exceptions": {
            "market_selection_key_receipts_added": sorted(expected_receipt_extras),
            "predictor_config": {
                "reason": "Repaired-product code receipts and post-barrier selection-score handling change generated provenance fields; scientific settings and all forecast bytes are audited separately.",
                "expected_sha256": canonical["predictor_config"]["expected_sha256"],
                "observed_sha256": canonical["predictor_config"]["observed_sha256"],
            },
            "join_manifest": {
                "reason": "The repaired join emits a generic WTA02-era manifest schema and an explicit market_date_basis column; all 42,905 historical common-column cells match, no season exceeds 2024, and no carried-forward row exists.",
                "rebuilt_id": read_json(observed / "run/join/join_manifest.json")["id"],
            },
            "sr03_component": {
                "reason": "The repaired runner adds a post-barrier SR03 component report that the retained WTA01 run did not contain.",
                "files": inventory(
                    observed / "run/sr03_component",
                    (observed / "run/sr03_component").glob("*"),
                ),
            },
        },
        "retained_original_secondary_failures": {
            path.as_posix(): file_record(archive / path, path.as_posix())
            for path in SECONDARY_FAILURE_RECORDS
        },
        "limitations": [
            "Passing bytes, membership and arithmetic establishes reconstruction only, not source truth, comprehensive leak freedom or scientific validity.",
            "The product intentionally moves pre-barrier SR03 and selection scores behind the barrier; those artifact-location differences are adjudicated separately by the chain comparator.",
            "Historical WTA01 remains exposed retrospective development with outcome-assisted rule-era provenance and a constant 2016 dynamic training window.",
            "The original failed secondary attempts remain failed and were not reopened.",
            "The market reference has unknown quote clocks and cannot support a market-efficiency, edge or value claim.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "audit"))
    parser.add_argument("--archive")
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args(argv)
    repo = repository_root()
    archive = archive_root(args.archive)
    if args.command == "freeze":
        record = structural_record(repo, archive)
        _portable_write(repo, archive, STRUCTURAL_RECORD, record)
    else:
        workspace = (
            args.workspace.resolve()
            if args.workspace
            else repo / "data/runs/equivalence/WTA01-binding_attempt_002/_chain"
        )
        record = historical_audit(repo, archive, workspace)
        _portable_write(repo, archive, AUDIT_RECORD, record)
    print(json.dumps({"attempt_id": ATTEMPT_ID, "status": record["status"]}, sort_keys=True))
    return 0 if record["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
