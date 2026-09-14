from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
from pathlib import Path

import pytest

from tennislab.benchmark import workflow
from tennislab.benchmark.core import BenchmarkError, TargetMatch
from tennislab.benchmark.statistics import ScoredRow, simultaneous_intervals
from tennislab.benchmark.workflow import COMPARATORS, _fit_calibration, barrier, forecast, report
from tennislab.config import reset_workspace_cache
from tests.test_benchmark_workflow import fixture_workspace, refresh_fixture_manifest


@pytest.fixture
def synthetic_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    config = fixture_workspace(tmp_path)
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    return tmp_path, config


def _target(match_id: str, year: int) -> TargetMatch:
    return TargetMatch(
        match_id=match_id,
        tour="ATP",
        match_date=dt.date(year, 7, 10),
        eligible_through_date=dt.date(year, 7, 8),
        tournament_week=f"{year}-W28",
        player_a="1",
        player_b="2",
        surface="Hard",
        level="A",
        rank_a=10,
        rank_b=20,
    )


def _calibration_plant(probability: float, outcomes_by_year: dict[int, list[int]]):
    targets: list[TargetMatch] = []
    outcomes: dict[str, int] = {}
    raw = {procedure: {} for procedure in COMPARATORS}
    for year, labels in outcomes_by_year.items():
        for index, outcome in enumerate(labels):
            match_id = f"SYNTHETIC-{year}-{index}"
            targets.append(_target(match_id, year))
            outcomes[match_id] = outcome
            for procedure in COMPARATORS:
                raw[procedure][match_id] = probability
    products, _ = _fit_calibration(raw, targets, outcomes, [2019], 3)
    return products


def test_g1_calibration_is_equal_year_and_has_exact_zero_boundary() -> None:
    unequal = _calibration_plant(0.8, {2016: [1] * 100, 2017: [0], 2018: [0]})
    zero_logits = _calibration_plant(0.5, {2016: [1], 2017: [0], 2018: [1]})
    for procedure in COMPARATORS:
        assert unequal[(2019, procedure)]["slope"] == 0.0
        assert zero_logits[(2019, procedure)]["slope"] == 0.0


def _rewrite_csv(path: Path, mutate) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        rows = [dict(row) for row in reader]
    mutate(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_g2_incumbent_extreme_token_is_preserved(synthetic_workspace: tuple[Path, Path]) -> None:
    root, config = synthetic_workspace
    path = root / "fixtures/synthetic/basic/atp/incumbent/2019.csv"
    _rewrite_csv(path, lambda rows: rows[0].__setitem__("p_a_wins", "0.00000001"))
    refresh_fixture_manifest(root, config)
    prediction_path = forecast(config, "extreme") / "forecast" / "predictions.csv"
    with prediction_path.open(newline="", encoding="utf-8") as handle:
        row = next(
            row for row in csv.DictReader(handle) if row["match_id"] == "SYNTHETIC-ATP-2019-1"
        )
    assert row["raw_incumbent"] == "0.00000001"
    assert row["calibrated_incumbent"] == "0.00000001"


def test_g3_final_unavailable_outcome_is_never_parsed(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    root, config = synthetic_workspace
    path = root / "fixtures/synthetic/basic/atp/panel.csv"
    _rewrite_csv(
        path,
        lambda rows: next(
            row for row in rows if row["match_id"] == "SYNTHETIC-ATP-2020-1"
        ).__setitem__("a_won", "UNAVAILABLE_AFTER_FINAL_CUTOFF"),
    )
    refresh_fixture_manifest(root, config)
    attempt = forecast(config, "unavailable")
    receipt = json.loads((attempt / "forecast/access_receipt.json").read_text())
    assert "SYNTHETIC-ATP-2020-1" not in receipt["tours"]["ATP"]["parsed_outcome_match_ids"]


def test_g4_prediction_mutation_before_barrier_rejects(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    _, config = synthetic_workspace
    attempt = forecast(config, "prediction_mutation")
    path = attempt / "forecast/predictions.csv"
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="manifest|artifact|changed"):
        barrier(config, "prediction_mutation")


def test_g4_empty_or_failed_forecast_never_commits(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    _, config = synthetic_workspace
    attempt = forecast(config, "empty")
    for path in (attempt / "forecast").iterdir():
        if path.name != "stage_manifest.json":
            path.unlink()
    with pytest.raises(BenchmarkError, match="missing|allowlist|manifest|artifact"):
        barrier(config, "empty")


def test_g4_config_and_effective_code_mutations_reject(
    synthetic_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = synthetic_workspace
    forecast(config, "config_mutation")
    document = json.loads(config.read_text())
    document["inference"]["replicates"] += 1
    config.write_text(json.dumps(document) + "\n", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="config changed|config changed after forecast"):
        barrier(config, "config_mutation")

    config = fixture_workspace(root)
    forecast(config, "code_mutation")
    barrier(config, "code_mutation")
    original = workflow._execution_binding

    def changed_binding():
        binding = original()
        binding["runtime"] = {"python_implementation": "comment_only_mutation_plant"}
        return binding

    monkeypatch.setattr(workflow, "_execution_binding", changed_binding)
    with pytest.raises(BenchmarkError, match="code or dependencies changed"):
        report(config, "code_mutation")
    assert (root / "runs/G-L/code_mutation/report_failure.json").is_file()


def test_g5_sensitive_gzip_and_stage_manifest_plants_reject(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    _, config = synthetic_workspace
    attempt = forecast(config, "gzip_plant")
    with gzip.open(attempt / "forecast/planted.CSV.GZ", "wt", newline="", encoding="utf-8") as h:
        writer = csv.DictWriter(h, fieldnames=["match_id", "a_won"])
        writer.writeheader()
        writer.writerow({"match_id": "SYNTHETIC-X", "a_won": 1})
    with pytest.raises(BenchmarkError, match="sensitive|allowlist|artifact"):
        barrier(config, "gzip_plant")

    attempt = forecast(config, "manifest_plant")
    manifest_path = attempt / "forecast/stage_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["a_won"] = 1
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="schema|sensitive|manifest"):
        barrier(config, "manifest_plant")


def test_g6_fixed_constant_drift_rejects(synthetic_workspace: tuple[Path, Path]) -> None:
    root, config = synthetic_workspace
    document = json.loads(config.read_text())
    document.setdefault("fixed_contract", {}).setdefault("constants", {})["elo_initial"] = 1499
    config.write_text(json.dumps(document) + "\n", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="constant|contract"):
        forecast(config, "constant_drift")
    assert not (root / "runs/G-L/constant_drift/forecast").exists()

    config = fixture_workspace(root)
    document = json.loads(config.read_text())
    document["procedures"] = document["procedures"][:-1]
    config.write_text(json.dumps(document) + "\n", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="procedure contract drift"):
        forecast(config, "procedure_drift")


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("surface", "Grass", "surface or level mismatch"),
        ("match_date", "2019-07-11", "match date mismatch"),
        ("player_b", "999999", "canonical pair mismatch"),
    ],
)
def test_g6_cross_artifact_identity_drift_rejects(
    synthetic_workspace: tuple[Path, Path], column: str, value: str, message: str
) -> None:
    root, config = synthetic_workspace
    feature_path = root / "fixtures/synthetic/basic/atp/features.csv"
    _rewrite_csv(feature_path, lambda rows: rows[-2].__setitem__(column, value))
    refresh_fixture_manifest(root, config)
    with pytest.raises(BenchmarkError, match=message):
        forecast(config, f"drift_{column}")


def test_g6_missing_anchor_and_arbitrary_synthetic_relabel_reject(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    root, config = synthetic_workspace
    panel_path = root / "fixtures/synthetic/basic/atp/panel.csv"
    _rewrite_csv(panel_path, lambda rows: rows[-1].__setitem__("tourney_anchor_date", ""))
    refresh_fixture_manifest(root, config)
    with pytest.raises(BenchmarkError, match="missing tournament anchor"):
        forecast(config, "missing_anchor")

    config = fixture_workspace(root)
    source = root / "fixtures/synthetic/basic/atp/features.csv"
    outside = root / "outside.csv"
    outside.write_bytes(source.read_bytes())
    document = json.loads(config.read_text())
    document["tours"]["ATP"]["inputs"]["features"]["path"] = "outside.csv"
    config.write_text(json.dumps(document) + "\n", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="arbitrary synthetic relabeling"):
        forecast(config, "arbitrary_relabel")


def test_g6_fit_and_fallback_receipts_have_declared_grain(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    _, config = synthetic_workspace
    forecast_root = forecast(config, "receipt_grain") / "forecast"
    fits = json.loads((forecast_root / "fit_receipts.json").read_text())
    assert fits
    assert all(
        {
            "tour",
            "procedure",
            "outer_year",
            "selection_years",
            "annual_membership",
            "selection_rows",
            "selection_membership_sha256",
            "status",
        }
        <= set(row)
        for row in fits
    )
    with (forecast_root / "fallback_counts.csv").open(newline="", encoding="utf-8") as handle:
        fallback_rows = list(csv.DictReader(handle))
    keys = [
        (row["tour"], row["calendar_year"], row["service"], row["scope"], row["reason"])
        for row in fallback_rows
    ]
    assert len(keys) == len(set(keys))
    assert any(row["count"] == "0" for row in fallback_rows)
    assert {"rank_logistic", "k32_pooled", "welo"} <= {row["service"] for row in fallback_rows}


@pytest.mark.parametrize(
    "override",
    [
        {"replicates": 1},
        {"replicates": 3, "maximum_draws": 2},
        {"mean_block": 0},
        {"level": 1.0},
        {"degenerate_tolerance": -1.0},
    ],
)
def test_g7_malformed_statistics_controls_reject(override: dict[str, object]) -> None:
    rows = [
        ScoredRow(2019, "2019-W01", {"incumbent": 0.5, "comparison": 0.6}),
        ScoredRow(2020, "2020-W01", {"incumbent": 0.4, "comparison": 0.7}),
    ]
    kwargs: dict[str, object] = {
        "replicates": 3,
        "maximum_draws": 3,
        "seed": 7,
        "mean_block": 1,
        "level": 0.95,
        "degenerate_tolerance": 0.0,
    }
    kwargs.update(override)
    with pytest.raises(BenchmarkError):
        simultaneous_intervals(rows, {"delta": ("incumbent", "comparison")}, **kwargs)


def test_g7_report_is_complete_and_brier_is_not_inference(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    _, config = synthetic_workspace
    forecast(config, "complete_report")
    barrier(config, "complete_report")
    destination = report(config, "complete_report")
    payload = json.loads((destination / "benchmark_report.json").read_text())
    atp = payload["tours"]["ATP"]
    for variant in ("raw", "calibrated"):
        assert {"annual", "equal_year", "match_weighted", "contrasts"} <= set(
            atp["cohorts"]["primary"]["scores"][variant]
        )
    assert {
        "normalized_pinnacle_raw",
        "normalized_pinnacle_calibrated_past",
    } <= set(atp["cohorts"]["priced"]["scores"]["calibrated"]["equal_year"])
    assert atp["fixed_prediction_sensitivities"]["leave_one_year_out"]
    assert payload["inference_scope"]["brier_inference"] is False
    assert all("brier" not in name for name in atp["inference"]["primary"]["8"]["intervals"])
    assert atp["inference"]["primary"]["8"]["seed"] == 20260914 + 1000 + 8
    assert atp["inference"]["priced"]["8"]["seed"] == 20260914 + 1000 + 8
    assert atp["inference"]["primary"]["8"]["generator_reset_for_stream"] is True
