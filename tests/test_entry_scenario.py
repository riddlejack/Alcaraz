"""ARMS01 Arm 1 rehearsal: the entry/level block through the real chain driver.

``configs/chains/sample_atp_tier_entry.json`` is the committed tier sample with the
features stage's ``entry_level_block`` switched on and the bundles ``base``, ``full_tier``
and ``full_tier_entry``. The chain is regenerated into a temporary workspace and driven
from ``rule_mapping`` to ``report`` exactly as ``tennislab reproduce-small --scenario
tier_entry`` drives it. Two things are checked beyond "it runs": the block is appended
after every existing column and reaches only the entry bundle, and the bundles that do
not read it (``base``, ``full_tier``) reproduce the tier scenario's pinned pooled log
losses to the pin's tolerance, which is the Arm 0 reproduction check on synthetic data.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tennislab import reproduce
from tennislab.chain import runner
from tennislab.features import base as features
from tennislab.models import pipeline
from tests.test_tier_scenario import SAMPLE, committed_sample, generate, inside

CHAIN_CONFIG = Path("configs", "chains", "sample_atp_tier_entry.json")
RUN_ROOT = Path("work", "sample_atp_tier_entry", "run")
BLOCK = features.ENTRY_RAW_AUDIT_COLUMNS + features.ENTRY_LEVEL_COLUMNS


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


@pytest.fixture(scope="module")
def entry_chain(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[dict[str, Any]]:
    root = Path(request.config.rootpath)
    committed_sample(root)
    assert (root / CHAIN_CONFIG).is_file(), f"the entry chain config is absent: {CHAIN_CONFIG}"
    workspace = tmp_path_factory.mktemp("entry_scenario")
    # The generator re-pins the tier sample and its template; the entry config binds the
    # same sample files, so it is copied beside them unchanged.
    generate(root, workspace)
    (workspace / CHAIN_CONFIG).write_bytes((root / CHAIN_CONFIG).read_bytes())
    config = str(workspace / CHAIN_CONFIG)
    assert inside(workspace, ["write-configs", "--config", config]) == 0
    assert inside(workspace, ["dry-run", "--config", config]) == 0
    assert inside(workspace, ["run", "--include-report", "--config", config]) == 0
    yield {"workspace": workspace, "config": config, "root": root}


def test_the_entry_config_binds_the_tier_sample_and_declares_the_block(
    request: pytest.FixtureRequest,
) -> None:
    root = Path(request.config.rootpath)
    tier = read_json(root / "configs" / "chains" / "sample_atp_tier.json")["chain"]
    entry = read_json(root / CHAIN_CONFIG)["chain"]
    assert entry["inputs"] == tier["inputs"]
    assert entry["entry_level_block"] is True
    assert entry["bundles"] == ["base", "full_tier", "full_tier_entry"]
    assert entry["reporting_primary_contrast"] == "full_tier_entry_minus_full_tier"
    assert entry["tier_initial_rating_offset_by_year"] == tier["tier_initial_rating_offset_by_year"]
    assert reproduce.SCENARIOS["tier_entry"].expected.name == "expected_entry.json"


def test_every_stage_completes_and_the_features_stage_appends_the_block(
    entry_chain: dict[str, Any],
) -> None:
    run_root = entry_chain["workspace"] / RUN_ROOT
    stage_names = [
        stage.name for stage in runner.stages(read_json(Path(entry_chain["config"]))["chain"])
    ]
    for name in stage_names:
        if (run_root / name / "stage_manifest.json").is_file():
            assert read_json(run_root / name / "stage_manifest.json")["exit_status"] == 0, name
    header, rows = read_csv(run_root / "features" / "features.csv")
    assert tuple(header) == features.feature_header(entry_level=True)
    assert tuple(header[-len(BLOCK) :]) == BLOCK
    assert tuple(header[: -len(BLOCK)]) == features.feature_header()
    dictionary = read_json(run_root / "features" / "column_dictionary.json")
    assert dictionary["entry_level_columns"] == list(features.ENTRY_LEVEL_COLUMNS)
    assert dictionary["ordered_feature_file_columns"] == header
    # The sample draws Q and WC entries and G/M/A levels, so the block is not constant.
    assert any(row["entry_q_diff"] != "0" for row in rows)
    assert any(row["entry_wc_diff"] != "0" for row in rows)
    assert any(row["entry_any_qualifier"] == "1" for row in rows)
    assert {row["level_context_g"] for row in rows} == {"0", "1"}
    for row in rows:
        assert row["entry_q_diff"] in {"-1", "0", "1"}
        assert sum(int(row[column]) for column in features.LEVEL_CONTEXT) <= 1
    summary = read_json(run_root / "features" / "summary.json")["entry_level_block"]
    assert summary["flagged_entry_codes"] == ["Q", "LL", "WC", "PR"]
    assert set(summary["counts_by_season"]) and isinstance(
        summary["events_without_any_entry_code"], list
    )
    assert inside(entry_chain["workspace"], ["verify", "--config", entry_chain["config"]]) == 0


def test_the_block_reaches_only_the_entry_bundle(entry_chain: dict[str, Any]) -> None:
    workspace = entry_chain["workspace"]
    section = read_json(Path(entry_chain["config"]))["chain"]
    predictor = read_json(workspace / section["predictor_config"])
    columns = predictor["ordered_model_columns"]["hgb"]
    tier = columns["full_tier"]
    entry = columns["full_tier_entry"]
    assert entry["numeric_or_signed"] == [*tier["numeric_or_signed"], *pipeline.ENTRY_LEVEL_SIGNED]
    assert entry["symmetric_context"] == [*tier["symmetric_context"], *pipeline.ENTRY_LEVEL_CONTEXT]
    for block in ("base", "full_tier"):
        assert not set(pipeline.ENTRY_LEVEL_COLUMNS) & set(columns[block]["numeric_or_signed"])
        assert not set(pipeline.ENTRY_LEVEL_COLUMNS) & set(columns[block]["symmetric_context"])
    assert predictor["settings"]["entry_level_columns"] == list(pipeline.ENTRY_LEVEL_COLUMNS)
    assert predictor["settings"]["blocks"] == ["base", "full_tier", "full_tier_entry"]
    assert predictor["experiment_id"] == "TIER01"  # the emitted year plan names no id


def test_the_bundles_without_the_block_reproduce_the_tier_pin(entry_chain: dict[str, Any]) -> None:
    """Arm 0 on synthetic data: appending the block changes nothing for the bundles that do
    not read it, so `base` and `full_tier` match the tier scenario's pinned pooled values."""
    observed = reproduce.headline(entry_chain["workspace"], reproduce.SCENARIOS["tier_entry"])
    assert observed["primary_contrast"] == "full_tier_entry_minus_full_tier"
    tier_pin = read_json(entry_chain["root"] / SAMPLE / "expected.json")
    tolerance = float(tier_pin["tolerance"])
    for model in ("selected/hgb/base", "selected/hgb/full_tier", "market/calibrated_ps"):
        pinned = tier_pin["pooled_log_loss_match_weighted"][model]
        assert abs(observed["pooled_log_loss_match_weighted"][model] - pinned) <= tolerance, model
    entry_pin = read_json(entry_chain["root"] / SAMPLE / "expected_entry.json")
    assert reproduce.compare(observed, entry_pin) == []
    primary = read_json(entry_chain["workspace"] / RUN_ROOT / "report" / "primary.json")
    assert primary["effect_direction"] == "negative_favors_entry_level_block"
    assert primary["secondary_contrasts"] == {}


# ------------------------------------------------------------------ TUNE01: an enlarged menu

MENU = Path("configs", "menus", "tune01_hgb_menu.json")
TUNED_MENU = Path("configs", "menus", "tiny_tune_menu.json")


def tiny_menu(root: Path) -> bytes:
    """The TUNE01 menu cut to two grid candidates and a 40-iteration cap, so the synthetic
    chain exercises every bagged path in seconds."""
    document = read_json(root / MENU)
    document["grid_axes"] = {
        "max_leaf_nodes": [7],
        "min_samples_leaf": [80, 40],
        "l2_regularization": [10.0],
        "learning_rate": [0.1],
    }
    document["grid"] = [
        entry
        for entry in document["grid"]
        if entry["candidate_id"]
        in ("tune_lr100_leaf07_min080_reg10", "tune_lr100_leaf07_min040_reg10")
    ]
    document["counts"].update(grid=2, total_candidates_seen_by_selector=4)
    document["early_stopping"].update(max_iter_cap=40, patience=5)
    return (json.dumps(document, indent=1) + "\n").encode("utf-8")


@pytest.fixture(scope="module")
def tuned_chain(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[dict[str, Any]]:
    """The same scenario with an HGB menu bound to `full_tier_entry`, fitted by two worker
    processes, through the real chain driver from write-configs to report."""
    import hashlib
    import os

    root = Path(request.config.rootpath)
    workspace = tmp_path_factory.mktemp("tune_scenario")
    generate(root, workspace)
    menu = tiny_menu(root)
    (workspace / TUNED_MENU).parent.mkdir(parents=True, exist_ok=True)
    (workspace / TUNED_MENU).write_bytes(menu)
    document = read_json(root / CHAIN_CONFIG)
    document["chain"]["hgb_menus"] = {
        "full_tier_entry": {
            "path": TUNED_MENU.as_posix(),
            "sha256": hashlib.sha256(menu).hexdigest(),
        }
    }
    (workspace / CHAIN_CONFIG).parent.mkdir(parents=True, exist_ok=True)
    (workspace / CHAIN_CONFIG).write_text(json.dumps(document, indent=2), encoding="utf-8")
    config = str(workspace / CHAIN_CONFIG)
    previous = os.environ.get(pipeline.WORKERS_ENVIRONMENT_VARIABLE)
    os.environ[pipeline.WORKERS_ENVIRONMENT_VARIABLE] = "2"
    try:
        assert inside(workspace, ["write-configs", "--config", config]) == 0
        assert inside(workspace, ["dry-run", "--config", config]) == 0
        assert inside(workspace, ["run", "--include-report", "--config", config]) == 0
    finally:
        if previous is None:
            os.environ.pop(pipeline.WORKERS_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[pipeline.WORKERS_ENVIRONMENT_VARIABLE] = previous
    yield {"workspace": workspace, "config": config, "root": root}


def forecast_bytes(run_root: Path) -> dict[str, bytes]:
    pipeline_dir = run_root / "pipeline"
    return {
        path.relative_to(pipeline_dir).as_posix(): path.read_bytes()
        for folder in ("raw", "selected", "shared_base", "market")
        for path in sorted((pipeline_dir / folder).rglob("*.csv"))
    }


def test_a_bound_menu_leaves_every_default_forecast_and_the_anchors_byte_identical(
    entry_chain: dict[str, Any], tuned_chain: dict[str, Any]
) -> None:
    default = forecast_bytes(entry_chain["workspace"] / RUN_ROOT)
    tuned = forecast_bytes(tuned_chain["workspace"] / RUN_ROOT)
    grid = {name for name in tuned if "/tune_" in name}
    assert len(grid) == 2 * 5
    assert set(tuned) - grid == set(default)
    selection = read_json(
        tuned_chain["workspace"] / RUN_ROOT / "pipeline" / "selection_complete.json"
    )
    chosen = {
        record["outer_year"]: record["selected_candidate_id"]
        for record in selection["selection_records"]
        if record["block"] == "full_tier_entry"
    }
    for name, payload in default.items():
        selected_entry = name.startswith("selected/") and name.endswith("/full_tier_entry.csv")
        if selected_entry and chosen[int(name.split("/")[1])].startswith("tune_"):
            continue  # a year whose selector chose a grid candidate
        assert tuned[name] == payload, name


def test_the_tuned_records_carry_the_menu_the_stopped_counts_and_the_bag_seeds(
    tuned_chain: dict[str, Any],
) -> None:
    run_root = tuned_chain["workspace"] / RUN_ROOT
    section = read_json(Path(tuned_chain["config"]))["chain"]
    binding = section["hgb_menus"]["full_tier_entry"]
    predictor = read_json(tuned_chain["workspace"] / section["predictor_config"])
    assert predictor["settings"]["hgb_menus"] == {"full_tier_entry": binding}
    assert predictor["expected_membership"]["raw_fit_attempts"] == (2 + 2 + 4) * 5
    raw = read_json(run_root / "pipeline" / "raw_complete.json")
    assert raw["process_workers"] == 2 and raw["hgb_menus"] == {"full_tier_entry": binding}
    grid_attempts = [
        item for item in raw["raw_attempts"] if item["candidate_id"].startswith("tune_")
    ]
    assert len(grid_attempts) == 10
    for item in grid_attempts:
        tuning = item["tuning"]
        assert tuning["menu_sha256"] == binding["sha256"]
        assert tuning["refit_member_n_iter"] == [tuning["k_star"]] * 5
        assert 1 <= tuning["k_star"] <= 40 and tuning["curve_points"] == 40
        assert [entry["seed_sequence"] for entry in tuning["subsamples"]["refit"]] == [
            [71101, item["year"], 1, member] for member in range(5)
        ]
    for record in read_json(run_root / "pipeline" / "selection_complete.json")["selection_records"]:
        if record["block"] != "full_tier_entry":
            assert "hgb_menu" not in record
            continue
        assert record["hgb_menu"] == binding
        assert set(record["candidate_trials"]) == {
            "hgb_leaf07_depth3",
            "hgb_leaf15_depth4",
            "tune_lr100_leaf07_min080_reg10",
            "tune_lr100_leaf07_min040_reg10",
        }
        for candidate, trial in record["candidate_trials"].items():
            for source in trial["prediction_sources"].values():
                assert ("tuning" in source) == candidate.startswith("tune_")
                if "tuning" in source:
                    assert set(source["tuning"]) == {
                        "k_star", "k_stop", "stop_status", "curve_sha256", "bag_seeds",
                    }  # fmt: skip
        assert ("tuning" in record) == record["selected_candidate_id"].startswith("tune_")
    # The report publishes every candidate's past-year log losses after the barrier.
    trials = read_json(run_root / "report" / "selection_trials.json")
    assert "tune_lr100_leaf07_min040_reg10" in json.dumps(trials)
    assert inside(tuned_chain["workspace"], ["verify", "--config", tuned_chain["config"]]) == 0


def test_the_dry_run_refuses_a_year_plan_whose_menu_differs_from_the_chain(
    tuned_chain: dict[str, Any],
) -> None:
    workspace = tuned_chain["workspace"]
    document = read_json(Path(tuned_chain["config"]))
    plan_path = workspace / document["chain"]["configs"]["year_plan"]
    plan = read_json(plan_path)
    assert plan["hgb_menus"] == document["chain"]["hgb_menus"]
    plan["hgb_menus"]["full_tier_entry"]["sha256"] = "0" * 64
    other_plan = plan_path.with_name("year_plan.other_menu.json")
    other_plan.write_text(json.dumps(plan), encoding="utf-8")
    document["chain"]["configs"]["year_plan"] = other_plan.relative_to(workspace).as_posix()
    other_config = Path(tuned_chain["config"]).with_name("other_menu.json")
    other_config.write_text(json.dumps(document), encoding="utf-8")
    assert inside(workspace, ["dry-run", "--config", str(other_config)]) == 1


def test_the_selected_curves_are_published_after_the_barrier_and_match_their_hashes(
    tuned_chain: dict[str, Any],
) -> None:
    import os

    from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache

    workspace = tuned_chain["workspace"]
    section = read_json(Path(tuned_chain["config"]))["chain"]
    argv = [
        "curves",
        "--config",
        section["predictor_config"],
        "--output",
        (RUN_ROOT / "pipeline").as_posix(),
        "--publish",
        (RUN_ROOT.parent / "tune_curves").as_posix(),
    ]
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    cwd = Path.cwd()
    try:
        os.chdir(workspace)
        assert pipeline.main(argv) == 0
        assert pipeline.main(argv) == 1  # never replaces published curves
    finally:
        os.chdir(cwd)
        os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        reset_workspace_cache()
        pipeline.configure_identity()
        pipeline.configure_years(pipeline.DEFAULT_YEAR_PLAN)
        pipeline.configure_cohort()
        pipeline.configure_bundles()
    summary = read_json(workspace / RUN_ROOT.parent / "tune_curves" / "curves_complete.json")
    assert summary["status"] == "complete" and len(summary["published"]) == 3
    for item in summary["published"]:
        if item["status"] == "anchor_selected_no_curve":
            continue
        assert item["hash_matches"] and item["partition_matches"]
        assert item["decision"] == item["committed_decision"]
        curve = read_json(
            workspace
            / RUN_ROOT.parent
            / "tune_curves"
            / str(item["outer_year"])
            / "hgb"
            / "full_tier_entry.json"
        )["curve"]
        assert len(curve) == 40
