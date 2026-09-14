from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
from pathlib import Path

import pytest

from tennislab.benchmark.core import BenchmarkError, TargetMatch
from tennislab.benchmark.workflow import COMPARATORS, _fit_calibration, barrier, forecast, report
from tests.test_benchmark_workflow import synthetic_workspace


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
    path = root / "inputs/atp/incumbent/2019.csv"
    _rewrite_csv(path, lambda rows: rows[0].__setitem__("p_a_wins", "0.00000001"))
    prediction_path = forecast(config, "extreme") / "forecast" / "predictions.csv"
    with prediction_path.open(newline="", encoding="utf-8") as handle:
        row = next(row for row in csv.DictReader(handle) if row["match_id"] == "ATP-2019-1")
    assert row["raw_incumbent"] == "0.00000001"
    assert row["calibrated_incumbent"] == "0.00000001"


def test_g3_final_unavailable_outcome_is_never_parsed(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    root, config = synthetic_workspace
    path = root / "inputs/atp/panel.csv"
    _rewrite_csv(
        path,
        lambda rows: next(row for row in rows if row["match_id"] == "ATP-2020-1").__setitem__(
            "a_won", "UNAVAILABLE_AFTER_FINAL_CUTOFF"
        ),
    )
    attempt = forecast(config, "unavailable")
    receipt = json.loads((attempt / "forecast/access_receipt.json").read_text())
    assert "ATP-2020-1" not in receipt["tours"]["ATP"]["parsed_outcome_match_ids"]


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


def test_g7_report_is_complete_and_brier_is_not_inference(
    synthetic_workspace: tuple[Path, Path],
) -> None:
    _, config = synthetic_workspace
    forecast(config, "complete_report")
    barrier(config, "complete_report")
    destination = report(config, "complete_report")
    payload = json.loads((destination / "benchmark_report.json").read_text())
    atp = payload["tours"]["ATP"]
    assert {"annual", "equal_year", "match_weighted", "contrasts"} <= set(
        atp["cohorts"]["primary"]["scores"]
    )
    assert {
        "normalized_pinnacle_raw",
        "normalized_pinnacle_calibrated_past",
    } <= set(atp["cohorts"]["priced"]["scores"]["equal_year"])
    assert atp["fixed_prediction_sensitivities"]["leave_one_year_out"]
    assert payload["inference_scope"]["brier_inference"] is False
    assert all("brier" not in name for name in atp["inference"]["primary"]["8"]["intervals"])
