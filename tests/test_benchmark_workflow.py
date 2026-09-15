from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from tennislab.benchmark.core import BenchmarkError
from tennislab.benchmark.workflow import barrier, forecast, report
from tennislab.config import reset_workspace_cache


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fixture_workspace(root: Path) -> Path:
    feature_fields = [
        "match_id",
        "calendar_year",
        "source_season",
        "match_date",
        "eligible_through_date",
        "tourney_id",
        "tourney_level",
        "player_a",
        "player_b",
        "surface",
        "rank_a",
        "rank_b",
        "primary_target",
        "identity_tier",
    ]
    panel_fields = [
        "match_id",
        "match_date",
        "player_a",
        "player_b",
        "a_rank",
        "b_rank",
        "surface",
        "tourney_level",
        "tourney_anchor_date",
        "a_won",
        "score",
        "played",
        "retired",
        "walkover",
        "PS_valid",
        "PS_decimal_a",
        "PS_decimal_b",
    ]
    tours: dict[str, object] = {}
    for tour_index, tour in enumerate(("ATP", "WTA"), 1):
        features: list[dict[str, object]] = []
        panel: list[dict[str, object]] = []
        labels: list[dict[str, object]] = []
        for year in range(2011, 2021):
            match_id = f"SYNTHETIC-{tour}-{year}-1"
            a_won = (year + tour_index) % 2
            player_a = year * 10 + tour_index * 2
            player_b = player_a + 1
            features.append(
                {
                    "match_id": match_id,
                    "calendar_year": year,
                    "source_season": year,
                    "match_date": f"{year}-07-10",
                    "eligible_through_date": f"{year}-07-08",
                    "tourney_id": f"{year}-SYN",
                    "tourney_level": "G" if year % 4 == 0 else "A",
                    "player_a": player_a,
                    "player_b": player_b,
                    "surface": "Hard" if year % 2 else "Clay",
                    "rank_a": 10,
                    "rank_b": 10,
                    "primary_target": 1,
                    "identity_tier": "primary",
                }
            )
            panel.append(
                {
                    "match_id": match_id,
                    "match_date": f"{year}-07-10",
                    "player_a": player_a,
                    "player_b": player_b,
                    "a_rank": 10,
                    "b_rank": 10,
                    "surface": "Hard" if year % 2 else "Clay",
                    "tourney_level": "G" if year % 4 == 0 else "A",
                    "tourney_anchor_date": f"{year}0708",
                    "a_won": a_won,
                    "score": "6-4 3-6 6-2" if a_won else "7-5 6-4",
                    "played": "true",
                    "retired": "false",
                    "walkover": "false",
                    "PS_valid": "false" if year == 2020 else "true",
                    "PS_decimal_a": 1.8,
                    "PS_decimal_b": 2.1,
                }
            )
            labels.append({"match_id": match_id, "a_won": a_won})
        base = root / "fixtures" / "synthetic" / "basic" / tour.lower()
        write_csv(base / "features.csv", feature_fields, features)
        write_csv(base / "panel.csv", panel_fields, panel)
        write_csv(base / "labels.csv", ["match_id", "a_won"], labels)
        for year in (2019, 2020):
            write_csv(
                base / "incumbent" / f"{year}.csv",
                ["season", "match_id", "p_a_wins"],
                [{"season": year, "match_id": f"SYNTHETIC-{tour}-{year}-1", "p_a_wins": 0.6}],
            )
        tours[tour] = {
            "target_years": [2019, 2020],
            "major_level_codes": ["G"],
            "inputs": {
                "features": {"path": f"fixtures/synthetic/basic/{tour.lower()}/features.csv"},
                "history_panel": {"path": f"fixtures/synthetic/basic/{tour.lower()}/panel.csv"},
                "labels": {"path": f"fixtures/synthetic/basic/{tour.lower()}/labels.csv"},
                "prices": {"path": f"fixtures/synthetic/basic/{tour.lower()}/panel.csv"},
                "incumbent_pattern": f"fixtures/synthetic/basic/{tour.lower()}/incumbent/{{year}}.csv",
            },
        }
    constants = {
        "elo_initial": 1500.0,
        "elo_scale": 400.0,
        "k32": 32.0,
        "decaying_k_numerator": 250.0,
        "decaying_k_offset": 5.0,
        "decaying_k_exponent": 0.4,
        "kovalchik_major_multiplier": 1.1,
        "fivethirtyeight_overall_weight": 0.71,
        "fivethirtyeight_surface_weight": 0.29,
        "calibration_years": 3,
        "parameter_history_years": 5,
        "logit_clip": 1e-6,
        "scoring_clip": 1e-15,
    }
    procedures = [
        "incumbent",
        "k32_pooled",
        "rank_logistic",
        "kovalchik_overall_major",
        "fivethirtyeight_surface",
        "welo",
    ]
    fixture_root = root / "fixtures/synthetic/basic"
    files = {}
    for path in sorted(
        item
        for item in fixture_root.rglob("*")
        if item.is_file() and item.name != "fixture_manifest.json"
    ):
        with path.open(newline="", encoding="utf-8") as handle:
            rows = max(sum(1 for _ in csv.reader(handle)) - 1, 0)
        files[path.relative_to(fixture_root).as_posix()] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": rows,
        }
    fixture_manifest = fixture_root / "fixture_manifest.json"
    fixture_manifest.write_text(
        json.dumps({"schema_version": 1, "fixture_id": "basic", "files": files}, indent=2) + "\n",
        encoding="utf-8",
    )
    document = {
        "schema_version": 2,
        "benchmark_id": "G-L",
        "proposal_status": "synthetic_rehearsal",
        "anchor_basis": "tourney_anchor_date_event_anchor_proxy",
        "procedures": procedures,
        "constants": constants,
        "fixed_contract": {"procedures": procedures, "constants": constants},
        "calibration": {
            "implementation": "tennislab.models.pipeline.fit_nonnegative_slope",
            "application": "tennislab.models.pipeline.apply_slope",
            "year_weighting": "equal_total_weight_per_calendar_year",
            "intercept": False,
            "slope_lower_bound": 0.0,
        },
        "market_references": {
            "book": "PS",
            "valid_column": "PS_valid",
            "decimal_a_column": "PS_decimal_a",
            "decimal_b_column": "PS_decimal_b",
            "normalized_id": "normalized_pinnacle_raw",
            "past_calibrated_id": "normalized_pinnacle_calibrated_past",
            "quote_timing": "unknown_later_information_reference",
        },
        "inference": {
            "replicates": 50,
            "maximum_draws": 500,
            "seed_base": 20260914,
            "tour_offsets": {"ATP": 1000, "WTA": 2000},
            "stream_unit": "tour_cohort_mean_block_weeks",
            "rng": "numpy.PCG64",
            "primary_mean_block_weeks": 8,
            "sensitivity_mean_block_weeks": [4, 13],
            "simultaneous_level": 0.95,
            "degenerate_se_tolerance": 1e-15,
            "multiplicity_scope": "per_tour_five_calibrated_log_loss_incumbent_contrasts",
            "brier_inference": False,
            "fixed_prediction_sensitivities": ["leave_one_year_out", "leave_2020_out"],
            "deferred": ["unordered_player_dyad", "player_cluster", "fitting_uncertainty"],
        },
        "synthetic_policy": {
            "required_root": "fixtures/synthetic",
            "required_match_id_prefix": "SYNTHETIC-",
            "maximum_rows_per_input": 1000,
            "manifest_name": "fixture_manifest.json",
            "symlinks_allowed": False,
            "allowed_tours": ["ATP", "WTA"],
        },
        "fixture_manifest": {
            "path": "fixtures/synthetic/basic/fixture_manifest.json",
            "sha256": hashlib.sha256(fixture_manifest.read_bytes()).hexdigest(),
        },
        "tours": tours,
        "output_root": "runs/G-L",
    }
    config = root / "config.json"
    config.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return config


def refresh_fixture_manifest(root: Path, config: Path) -> None:
    fixture_root = root / "fixtures/synthetic/basic"
    manifest_path = fixture_root / "fixture_manifest.json"
    files = {}
    for path in sorted(
        item for item in fixture_root.rglob("*") if item.is_file() and item != manifest_path
    ):
        with path.open(newline="", encoding="utf-8") as handle:
            rows = max(sum(1 for _ in csv.reader(handle)) - 1, 0)
        files[path.relative_to(fixture_root).as_posix()] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": rows,
        }
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "fixture_id": "basic", "files": files}, indent=2) + "\n",
        encoding="utf-8",
    )
    document = json.loads(config.read_text())
    document["fixture_manifest"]["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    config.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def synthetic_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    config = fixture_workspace(tmp_path)
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    return tmp_path, config


def test_full_synthetic_rehearsal(synthetic_workspace: tuple[Path, Path]) -> None:
    root, config = synthetic_workspace
    attempt = forecast(config, "attempt_001")
    assert len((attempt / "forecast" / "predictions.csv").read_text().splitlines()) == 5
    barrier(config, "attempt_001")
    destination = report(config, "attempt_001")
    payload = json.loads((destination / "benchmark_report.json").read_text())
    assert payload["tours"]["ATP"]["primary_rows"] == 2
    assert payload["tours"]["ATP"]["priced_rows"] == 1
    assert payload["admission_failures"]["ingram"]
    assert (root / "runs/G-L/attempt_001/barrier/commitment.json").is_file()


def test_real_execution_status_is_fail_closed(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    root, config = synthetic_workspace
    document = json.loads(config.read_text())
    document["proposal_status"] = "implementation_rehearsal_only"
    config.write_text(json.dumps(document) + "\n")
    with pytest.raises(BenchmarkError, match="not frozen_for_real_execution"):
        forecast(config, "forbidden")
    assert not (root / "runs/G-L/forbidden").exists()


def test_future_outcome_and_price_values_do_not_change_forecast(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    root, config = synthetic_workspace
    first = forecast(config, "first") / "forecast" / "predictions.csv"
    before = first.read_bytes()
    panel = root / "fixtures/synthetic/basic/atp/panel.csv"
    fields, rows = None, None
    with panel.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields, rows = list(reader.fieldnames or ()), list(reader)
    for row in rows:
        if row["match_id"] == "SYNTHETIC-ATP-2020-1":
            row["a_won"] = "0" if row["a_won"] == "1" else "1"
            row["PS_decimal_a"] = "99"
            row["PS_valid"] = "true"
    write_csv(panel, fields, rows)
    refresh_fixture_manifest(root, config)
    second = forecast(config, "second") / "forecast" / "predictions.csv"
    assert second.read_bytes() == before


def test_duplicate_rejected_and_failure_retained(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    root, config = synthetic_workspace
    features = root / "fixtures/synthetic/basic/atp/features.csv"
    with features.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields, rows = list(reader.fieldnames or ()), list(reader)
    rows.append(dict(rows[-1]))
    write_csv(features, fields, rows)
    refresh_fixture_manifest(root, config)
    with pytest.raises(BenchmarkError, match="duplicate feature match_id"):
        forecast(config, "duplicate")
    failure = root / "runs/G-L/duplicate/failure.json"
    assert failure.is_file()


@pytest.mark.parametrize("payload", ['{"log_loss": 0.5}\n', '{"a_won": 1}\n', '{"price": 1.8}\n'])
def test_barrier_rejects_planted_metric_or_sensitive_value(
    synthetic_workspace: tuple[Path, Path], payload: str
) -> None:
    root, config = synthetic_workspace
    attempt = forecast(config, "leak")
    (attempt / "forecast" / "planted.json").write_text(payload)
    with pytest.raises(BenchmarkError, match="barrier rejected"):
        barrier(config, "leak")
    assert not (root / "runs/G-L/leak/barrier").exists()
    assert (root / "runs/G-L/leak/barrier_failure.json").is_file()


def test_full_source_side_swap_is_invariant(synthetic_workspace: tuple[Path, Path]) -> None:
    root, config = synthetic_workspace
    before = (forecast(config, "before_swap") / "forecast" / "predictions.csv").read_bytes()
    features = root / "fixtures/synthetic/basic/atp/features.csv"
    with features.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        feature_fields, feature_rows = list(reader.fieldnames or ()), list(reader)
    for row in feature_rows:
        row["player_a"], row["player_b"] = row["player_b"], row["player_a"]
        row["rank_a"], row["rank_b"] = row["rank_b"], row["rank_a"]
    write_csv(features, feature_fields, feature_rows)
    panel = root / "fixtures/synthetic/basic/atp/panel.csv"
    with panel.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        panel_fields, panel_rows = list(reader.fieldnames or ()), list(reader)
    for row in panel_rows:
        row["player_a"], row["player_b"] = row["player_b"], row["player_a"]
        row["a_rank"], row["b_rank"] = row["b_rank"], row["a_rank"]
        row["a_won"] = "0" if row["a_won"] == "1" else "1"
    write_csv(panel, panel_fields, panel_rows)
    refresh_fixture_manifest(root, config)
    after = (forecast(config, "after_swap") / "forecast" / "predictions.csv").read_bytes()
    assert after == before


def test_post_barrier_mutation_blocks_report(synthetic_workspace: tuple[Path, Path]) -> None:
    _, config = synthetic_workspace
    attempt = forecast(config, "mutated")
    barrier(config, "mutated")
    path = attempt / "forecast" / "predictions.csv"
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="forecast bytes changed"):
        report(config, "mutated")
    assert (attempt / "report_failure.json").is_file()
