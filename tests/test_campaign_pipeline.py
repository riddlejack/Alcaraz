"""Executable E01-E08 contracts for the repaired Lane E campaign graph."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from tennislab.campaign.artifacts import CampaignArtifactError, load_inputs
from tennislab.campaign.barrier import CampaignBarrierError, hash_tree, run_barrier
from tennislab.campaign.contracts import campaign_settings, load_campaign_config
from tennislab.campaign.forecast import read_forecasts, run_forecast
from tennislab.campaign.members import (
    fit_raw_numerical_member,
    member_specs,
    numerical_member_config,
)
from tennislab.campaign.report import CampaignReportError, run_report
from tennislab.campaign.runner import main as campaign_main
from tennislab.campaign.runner import verify_run
from tennislab.campaign.stages import inventory_sha256
from tennislab.campaign.synthetic import prepare_rehearsal
from tennislab.chain.common import canonical_hash_nonempty, sha256
from tennislab.config import reset_workspace_cache
from tennislab.models import numerical as num
from tennislab.models import pipeline

REPOSITORY_ROOT = Path.cwd()


@pytest.fixture(autouse=True)
def _restore_pipeline() -> Iterator[None]:
    yield
    pipeline.configure_identity()
    pipeline.configure_years(pipeline.DEFAULT_YEAR_PLAN)
    pipeline.configure_cohort()
    pipeline.configure_bundles()
    reset_workspace_cache()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _contract() -> pipeline.FeatureContract:
    contexts = tuple(
        f"context_{value}"
        for value in ("clay", "grass", "carpet", "best_of_5", "indoor", "indoor_unknown")
    )
    signed = tuple(f"base_{index}" for index in range(22))
    linear = tuple((*signed, *(f"linear_{index}" for index in range(140))))
    return pipeline.FeatureContract(
        base_linear=linear,
        base_signed=signed,
        binary_context=contexts,
        hgb_base_context=(*contexts, "ranking_global_age_days", "ranking_global_stale"),
        trait_interactions=tuple(
            f"{trait}_x_{context}" for trait in pipeline.TRAIT_SIGNED for context in contexts
        ),
    )


def _rehearsal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, tour: str = "ATP"
) -> tuple[Path, Path]:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    design = tmp_path / "design.md"
    design.write_text("# Synthetic campaign contract\n", encoding="utf-8")
    config_path = prepare_rehearsal(Path("work/rehearsal"), Path("design.md"), tour=tour)
    return config_path, tmp_path / "work/rehearsal/run"


def _run_forecast_barrier_report(config_path: Path, output: Path) -> None:
    config = load_campaign_config(config_path)
    run_forecast(config, output)
    run_barrier(config, output)
    run_report(config, output)


def test_frozen_member_menu_and_settings_are_unchanged() -> None:
    specs = {spec.member_id: spec for spec in member_specs("ATP")}
    first = numerical_member_config(_contract(), specs["rf_leaf50"])
    second = numerical_member_config(_contract(), specs["rf_leaf100"])
    assert first["estimator_params"] == pipeline.RF_PARAMS
    assert second["estimator_params"] == {**pipeline.RF_PARAMS, "min_samples_leaf": 100}
    assert first["signed_numeric_columns"][-5:] == [
        *pipeline.TIER_SIGNED,
        *pipeline.TIER_DYNAMIC_SIGNED,
    ]
    assert not pipeline.FORBIDDEN_MODEL_COLUMNS.intersection(
        (*first["signed_numeric_columns"], *first["context_columns"])
    )
    assert pipeline.LEARNERS == pipeline.DEFAULT_LEARNERS
    with pytest.raises(pipeline.PipelineError):
        pipeline.configure_bundles(["full"], ["random_forest"])
    wta = member_specs("WTA")
    assert len(wta) == len({spec.member_id for spec in wta}) == 8
    assert [spec.feature_bundle for spec in wta if spec.learner == "ridge"] == ["full"] * 3
    assert [spec.feature_bundle for spec in wta if spec.learner == "hgb"] == ["full"] * 2
    contaminated = _contract()
    contaminated = pipeline.FeatureContract(
        base_linear=contaminated.base_linear,
        base_signed=(*contaminated.base_signed[:-1], "lagged_market_signal"),
        binary_context=contaminated.binary_context,
        hgb_base_context=contaminated.hgb_base_context,
        trait_interactions=contaminated.trait_interactions,
    )
    with pytest.raises(ValueError, match="market-derived"):
        numerical_member_config(contaminated, specs["rf_leaf50"])


@pytest.mark.parametrize(
    ("tour", "target_rows", "priced_rows"),
    (("ATP", 18_972, 18_882), ("WTA", 12_900, 12_785)),
)
def test_checked_in_settings_remain_exact(tour: str, target_rows: int, priced_rows: int) -> None:
    path = REPOSITORY_ROOT / "configs/campaign" / f"e_v1_{tour.lower()}.settings.json"
    document = _read(path)
    assert document["settings"] == campaign_settings(tour)
    assert document["expected_population"] == {
        "target_rows": target_rows,
        "priced_rows": priced_rows,
    }
    assert document["status"] == "settings_complete_inputs_not_yet_bound"


def test_member_helper_uses_plan_hash_and_actual_training_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    state_path = tmp_path / "state.json"
    state_path.write_text('{"synthetic": true}\n', encoding="utf-8")
    contract = pipeline.FeatureContract(
        base_linear=("sports_x",),
        base_signed=("sports_x",),
        binary_context=(),
        hgb_base_context=(),
        trait_interactions=(),
    )
    spec = next(spec for spec in member_specs("ATP") if spec.member_id == "ridge_c001")
    columns = tuple(numerical_member_config(contract, spec)["numeric_columns"])
    header = ("season", "match_id", *columns)
    training = num.FeatureTable.from_rows(
        [
            {
                "season": str(year),
                "match_id": f"t{index}",
                **{column: str(index - 2) for column in columns},
            }
            for index, year in enumerate(range(2012, 2017))
        ],
        header,
    )
    dates = {key: f"{key[0]}-06-10" for key in training.keys}
    training_membership_path = tmp_path / "training_membership.csv"
    with training_membership_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("season", "match_id", "match_date"))
        writer.writeheader()
        writer.writerows(
            {
                "season": key[0],
                "match_id": key[1],
                "match_date": dates[key],
            }
            for key in training.keys
        )
    labels = num.LabelTable.from_values({key: index % 2 for index, key in enumerate(training.keys)})
    prediction = num.FeatureTable.from_rows(
        [
            {"season": "2017", "match_id": match_id, **{column: value for column in columns}}
            for match_id, value in (("p0", "-0.5"), ("p1", "0.5"))
        ],
        header,
    )
    prediction_feature_path = tmp_path / "prediction_features.csv"
    with prediction_feature_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(prediction.rows)
    matrix = training.matrix(columns).astype("<f8", order="C")
    fit_frame = {
        "rows": len(training.keys),
        "columns": list(columns),
        "matrix_sha256": hashlib.sha256(str(matrix.shape).encode() + matrix.tobytes()).hexdigest(),
        "labels_sha256": labels.source_sha256,
        "training_keys_sha256": num.key_hash(training.keys),
        "fit_start": "2012-01-01",
        "fit_through": "2016-12-30",
        "prediction_year": 2017,
        "classes": [0, 1],
    }
    state = [{"path": "state.json", "sha256": sha256(state_path), "horizon_end": "2016-12-30"}]
    kwargs = {
        "spec": spec,
        "contract": contract,
        "training_features": training,
        "training_labels": labels,
        "prediction_features": prediction,
        "tour": "ATP",
        "custody_scope": "synthetic_rehearsal",
        "fit_cutoff": "2016-12-30",
        "producer_plan_sha256": "1" * 64,
        "training_dates": dates,
        "training_membership_receipt": {
            "path": "training_membership.csv",
            "sha256": sha256(training_membership_path),
            "rows": len(training.keys),
            "membership_sha256": num.key_hash(training.keys),
        },
        "prediction_feature_receipt": {
            "path": "prediction_features.csv",
            "sha256": sha256(prediction_feature_path),
            "rows": len(prediction.keys),
            "membership_sha256": num.key_hash(prediction.keys),
        },
        "state_receipts": state,
        "offset_receipts": [],
        "fit_frame_receipt": fit_frame,
        "output_dir": tmp_path / "fit",
    }
    first = fit_raw_numerical_member(**kwargs)
    second = fit_raw_numerical_member(**kwargs)
    assert first["status"] == second["status"] == "complete"
    assert first["fit_cache_reused"] is False and second["fit_cache_reused"] is True
    assert first["fit_identity"]["producer_plan_sha256"] == "1" * 64
    assert "campaign_config_sha256" not in first["fit_identity"]
    assert first["schema"] == "campaign_raw_member_completion/v1"
    assert first["origin"] == "new_plan_fit"
    assert first["training_membership"]["rows"] == len(training.keys)
    assert first["offset_applicability"] == "not_applicable_non_tier"
    assert first["offset_receipts"] == []
    assert first["horizons"]["offset"] is None
    assert first["transformed_fit_evidence"]["sha256"]
    transformed = _read(tmp_path / first["transformed_fit_evidence"]["path"])
    assert transformed["basis"] == "captured_at_actual_estimator_fit_call"
    assert transformed["estimator_fit_inputs"]["matrix"]["shape"] == [
        len(training.keys),
        len(columns),
    ]
    assert transformed["estimator_fit_inputs"]["labels"]["shape"] == [len(training.keys)]
    assert first["prediction_closure"]["method"] == "predict_bound_model"
    assert (
        first["prediction_closure"]["recomputed_prediction_sha256"] == first["prediction"]["sha256"]
    )
    with pytest.raises(ValueError, match="fit_start"):
        fit_raw_numerical_member(
            **{
                **kwargs,
                "fit_frame_receipt": {**fit_frame, "fit_start": "2099-01-01"},
                "output_dir": tmp_path / "bad-start",
            }
        )
    with pytest.raises(ValueError, match="date/season drift|outside base window"):
        fit_raw_numerical_member(
            **{
                **kwargs,
                "training_dates": {key: "2000-01-01" for key in training.keys},
                "output_dir": tmp_path / "bad-dates",
            }
        )
    with pytest.raises(ValueError, match="must not invent offset"):
        fit_raw_numerical_member(
            **{**kwargs, "offset_receipts": state, "output_dir": tmp_path / "bad-offset"}
        )
    altered_prediction = num.FeatureTable.from_rows(
        [
            {
                **row,
                columns[0]: str(float(row[columns[0]]) + 1.0),
            }
            for row in prediction.rows
        ],
        header,
    )
    with pytest.raises(ValueError, match="differ from prebound artifact"):
        fit_raw_numerical_member(
            **{
                **kwargs,
                "prediction_features": altered_prediction,
                "output_dir": tmp_path / "bad-prediction-features",
            }
        )


@pytest.mark.parametrize(("tour", "rows", "priced"), (("ATP", 64, 56), ("WTA", 48, 42)))
def test_public_typed_graph_recomputes_and_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tour: str,
    rows: int,
    priced: int,
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch, tour=tour)
    config = load_campaign_config(config_path)
    assert config.producer_completion["producer_plan_sha256"] == config.producer_plan_sha256
    assert "config_sha256" not in config.producer_plan
    assert "campaign_config_sha256" not in json.dumps(config.producer_plan)
    assert "campaign_config_sha256" not in json.dumps(config.producer_completion)
    _run_forecast_barrier_report(config_path, output)
    result = verify_run(config, output)
    assert result["status"] == "PASS"
    assert result["report_artifacts_verified"] == 12
    summary = _read(output / "report/summary.json")
    assert summary["population"]["paired_rows"] == rows
    assert (
        summary["population"]["annual_equal_year_degrees_of_freedom"]
        == len(config.target_years) - 1
    )
    assert summary["priced_descriptive"]["priced_rows"] == priced
    assert set(summary["full_sports_probability_clip_counts"]) == {"S0", "S1", "S2", "S3"}
    sensitivities = _read(output / "report/sensitivities.json")
    assert set(sensitivities["leave_one_year_out"]) == {str(year) for year in config.target_years}
    assert sensitivities["leave_2020_out"]["S3_minus_S0"]["years"] == [
        year for year in config.target_years if year != 2020
    ]
    assert "market-source-conditioned" in (output / "report/report.md").read_text()
    first_year = config.target_years[0]
    saved = read_forecasts(output / "forecast/forecasts" / f"{first_year}.csv", first_year)
    assert [float(row["S0"]) for row in saved] == list(
        load_inputs(config).incumbent[first_year].probabilities.values()
    )
    if tour == "WTA":
        assert summary["primary"]["edition_bootstrap_95_percentile"]["WTA_interval_label"]


def test_empty_and_partial_stage_manifests_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    config = load_campaign_config(config_path)
    (output / "forecast").mkdir(parents=True)
    _write(
        output / "forecast/forecast_manifest.json",
        {"schema": "campaign_forecast_completion/v1", "status": "complete", "artifacts": []},
    )
    with pytest.raises(CampaignBarrierError):
        run_barrier(config, output)


@pytest.mark.parametrize(
    "inventory_name", ("expected_forecast_inventory", "expected_report_inventory")
)
def test_consumer_cannot_shrink_mandatory_stage_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inventory_name: str,
) -> None:
    config_path, _ = _rehearsal(tmp_path, monkeypatch)
    document = _read(config_path)
    document[inventory_name] = [
        record for record in document[inventory_name] if record["logical_key"]["role"] == "exposure"
    ]
    _write(config_path, document)
    with pytest.raises(ValueError, match="inventory differs from fixed"):
        load_campaign_config(config_path)


def test_numbered_failure_receipts_preserve_first_failure_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    args = [
        "barrier",
        "--config",
        str(config_path.relative_to(tmp_path)),
        "--output",
        str(output.relative_to(tmp_path)),
    ]
    assert campaign_main(args) == 1
    first = output / "failures/barrier_001.json"
    first_bytes = first.read_bytes()
    assert campaign_main(args) == 1
    assert first.read_bytes() == first_bytes
    assert (output / "failures/barrier_002.json").is_file()


def test_verify_rejects_an_incomplete_report_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    config = load_campaign_config(config_path)
    run_forecast(config, output)
    run_barrier(config, output)
    (output / "report").mkdir()
    with pytest.raises(CampaignReportError, match="without a typed completion"):
        verify_run(config, output)


def test_dec31_raw_prediction_remains_but_is_excluded_from_fold_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    (tmp_path / "design.md").write_text("# Synthetic campaign contract\n", encoding="utf-8")
    config_path = prepare_rehearsal(Path("work/rehearsal"), Path("design.md"), dec31_year=2016)
    config = load_campaign_config(config_path)
    inputs = load_inputs(config)
    assert len(inputs.cohort_keys[2016]) == 8
    assert len(inputs.selection_keys[2017][2016]) == 7
    assert ("2016", "2016-m07") in inputs.cohort_keys[2016]
    assert ("2016", "2016-m07") not in inputs.selection_keys[2017][2016]
    manifest = run_forecast(config, tmp_path / "work/rehearsal/run")
    decision = _read(tmp_path / "work/rehearsal/run/forecast/decisions/2017.json")
    assert manifest["status"] == "complete"
    assert decision["selection_rows"] == 23


def test_forecast_rewrite_cannot_rebind_only_local_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    config = load_campaign_config(config_path)
    run_forecast(config, output)
    path = output / "forecast/forecasts/2017.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["S3"] = "0.999"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = output / "forecast/forecast_manifest.json"
    manifest = _read(manifest_path)
    for record in manifest["artifacts"]:
        if record["path"] == "forecast/forecasts/2017.csv":
            record["sha256"] = sha256(path)
    manifest["inventory_sha256"] = inventory_sha256(manifest["artifacts"])
    _write(manifest_path, manifest)
    with pytest.raises(CampaignBarrierError, match="attempt anchor"):
        run_barrier(config, output)


def test_report_recomputation_rejects_even_a_coherently_rebound_local_forecast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    config = load_campaign_config(config_path)
    run_forecast(config, output)
    run_barrier(config, output)
    forecast_path = output / "forecast/forecasts/2017.csv"
    with forecast_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["S3"] = "0.999"
    with forecast_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    forecast_manifest_path = output / "forecast/forecast_manifest.json"
    forecast_manifest = _read(forecast_manifest_path)
    for record in forecast_manifest["artifacts"]:
        if record["path"] == "forecast/forecasts/2017.csv":
            record["sha256"] = sha256(forecast_path)
    forecast_manifest["inventory_sha256"] = inventory_sha256(forecast_manifest["artifacts"])
    _write(forecast_manifest_path, forecast_manifest)
    anchor_path = output / "attempts/forecast_001.json"
    anchor = _read(anchor_path)
    anchor["forecast_completion"]["sha256"] = sha256(forecast_manifest_path)
    _write(anchor_path, anchor)
    barrier_path = output / "barrier/barrier_manifest.json"
    barrier = _read(barrier_path)
    barrier["forecast_completion"]["sha256"] = sha256(forecast_manifest_path)
    barrier["forecast_attempt_anchor"]["sha256"] = sha256(anchor_path)
    tree = hash_tree(output / "forecast", output)
    barrier["forecast_tree"] = tree
    barrier["forecast_tree_sha256"] = canonical_hash_nonempty(tree, label="forecast tree")
    _write(barrier_path, barrier)
    with pytest.raises(CampaignReportError, match="saved S3 probability"):
        run_report(config, output)


def test_quote_parse_is_deferred_until_after_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    (tmp_path / "design.md").write_text("# Synthetic campaign contract\n", encoding="utf-8")
    config_path = prepare_rehearsal(Path("work/rehearsal"), Path("design.md"), malformed_quote=True)
    output = tmp_path / "work/rehearsal/run"
    config = load_campaign_config(config_path)
    run_forecast(config, output)
    run_barrier(config, output)
    with pytest.raises(CampaignArtifactError, match="invalid raw quote"):
        run_report(config, output)


def test_quote_source_provenance_is_checked_postbarrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    config = load_campaign_config(config_path)
    run_forecast(config, output)
    run_barrier(config, output)
    source = config.raw_quotes_path.parent / "synthetic_provenance.json"
    source.write_text('{"status":"changed"}\n', encoding="utf-8")
    with pytest.raises(CampaignArtifactError, match="invalid raw quote/provenance"):
        run_report(config, output)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("failed", "status must be complete"),
        ("same_year", "same-year decision"),
        ("settings", "resolved_estimator_params drift"),
    ),
)
def test_actual_producer_status_ancestry_and_settings_are_reconciled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    config_path, _ = _rehearsal(tmp_path, monkeypatch)
    config_doc = _read(config_path)
    input_path = tmp_path / config_doc["input_manifest"]["path"]
    input_doc = _read(input_path)
    raw = next(
        item
        for item in input_doc["raw_members"]
        if item["year"] == 2014 and item["member_id"] == "hgb_leaf07_depth3"
    )
    record_path = tmp_path / raw["producer_record"]["path"]
    producer = _read(record_path)
    if mutation == "failed":
        producer["status"] = "failed"
    elif mutation == "same_year":
        producer["same_year_selection_or_slope_used"] = True
    else:
        producer["resolved_estimator_params"] = {"arbitrary": True}
    _write(record_path, producer)
    raw["producer_record"]["sha256"] = sha256(record_path)
    completion_path = tmp_path / config_doc["producer_completion"]["path"]
    completion = _read(completion_path)
    for artifact in completion["artifacts"]:
        if artifact["path"] == raw["producer_record"]["path"]:
            artifact["sha256"] = sha256(record_path)
    completion["inventory_sha256"] = inventory_sha256(completion["artifacts"])
    _write(completion_path, completion)
    input_doc["producer_completion_sha256"] = sha256(completion_path)
    _write(input_path, input_doc)
    config_doc["input_manifest"]["sha256"] = sha256(input_path)
    config_doc["producer_completion"]["sha256"] = sha256(completion_path)
    _write(config_path, config_doc)
    with pytest.raises(CampaignArtifactError, match=message):
        load_inputs(load_campaign_config(config_path))


def test_numeric_objective_in_bound_upstream_producer_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    config_doc = _read(config_path)
    input_path = tmp_path / config_doc["input_manifest"]["path"]
    input_doc = _read(input_path)
    raw = input_doc["raw_members"][0]
    record_path = tmp_path / raw["producer_record"]["path"]
    producer = _read(record_path)
    producer["fit"] = {"objective": 0.5}
    _write(record_path, producer)
    raw["producer_record"]["sha256"] = sha256(record_path)
    completion_path = tmp_path / config_doc["producer_completion"]["path"]
    completion = _read(completion_path)
    for artifact in completion["artifacts"]:
        if artifact["path"] == raw["producer_record"]["path"]:
            artifact["sha256"] = sha256(record_path)
    completion["inventory_sha256"] = inventory_sha256(completion["artifacts"])
    _write(completion_path, completion)
    input_doc["producer_completion_sha256"] = sha256(completion_path)
    _write(input_path, input_doc)
    config_doc["input_manifest"]["sha256"] = sha256(input_path)
    config_doc["producer_completion"]["sha256"] = sha256(completion_path)
    _write(config_path, config_doc)
    config = load_campaign_config(config_path)
    run_forecast(config, output)
    with pytest.raises(CampaignBarrierError, match="performance-shaped content"):
        run_barrier(config, output)


def test_report_completion_requires_exact_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    _run_forecast_barrier_report(config_path, output)
    config = load_campaign_config(config_path)
    report_path = output / "report/report_manifest.json"
    report = _read(report_path)
    report["artifacts"] = []
    report["inventory_sha256"] = "1" * 64
    _write(report_path, report)
    with pytest.raises(ValueError, match="inventory"):
        verify_run(config, output)


def test_coherently_rehashed_report_value_is_rederived_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, output = _rehearsal(tmp_path, monkeypatch)
    _run_forecast_barrier_report(config_path, output)
    config = load_campaign_config(config_path)
    summary_path = output / "report/summary.json"
    summary = _read(summary_path)
    summary["primary"]["equal_year_mean_log_loss_delta"] = 99.0
    _write(summary_path, summary)
    manifest_path = output / "report/report_manifest.json"
    manifest = _read(manifest_path)
    for artifact in manifest["artifacts"]:
        if artifact["path"] == "report/summary.json":
            artifact["sha256"] = sha256(summary_path)
    manifest["inventory_sha256"] = inventory_sha256(manifest["artifacts"])
    _write(manifest_path, manifest)
    with pytest.raises(CampaignReportError, match="semantic drift"):
        verify_run(config, output)
