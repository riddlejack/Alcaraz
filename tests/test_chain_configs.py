"""The configuration builder: plan settings, the reporting freeze, and B5 refusals."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from tennislab.chain import configs
from tennislab.chain.common import ChainError, canonical_hash, sha256
from tennislab.chain.labels import LabelHistory
from tennislab.config import reset_workspace_cache
from tennislab.evaluation import report
from tennislab.models import pipeline as runner


@pytest.fixture(autouse=True)
def _restore_module_state() -> Iterator[None]:
    yield
    for module in (runner, report):
        module.configure_identity()
        module.configure_cohort()
        module.configure_bundles()
    runner.configure_years(runner.DEFAULT_YEAR_PLAN)
    report.configure_years(report.DEFAULT_YEAR_PLAN, report.DEFAULT_T_CRITICAL_95)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    yield tmp_path
    reset_workspace_cache()


PLAN = {
    "panel_end_year": 2024,
    "feature_end_year": 2024,
    "target_years": [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
    "calibration_years_back": 3,
    "history_floor_year": 2011,
    "training_window_years": 5,
}


def test_plan_settings_accept_tier01_bundles_and_wta02_blocks(tmp_path: Path) -> None:
    tier = tmp_path / "tier.json"
    tier.write_text(
        json.dumps({"bundles": ["base", "full_tier"], "learners": ["hgb"], "year_plan": PLAN})
    )
    assert configs.read_plan_settings(tier) == {
        "blocks": ["base", "full_tier"],
        "learners": ["hgb"],
    }
    wta = tmp_path / "wta.json"
    wta.write_text(
        json.dumps(
            {
                "blocks": ["base", "full"],
                "tour": "WTA",
                "experiment_id": "WTA02",
                "bootstrap_unit": "match",
                "year_plan": PLAN,
            }
        )
    )
    assert configs.read_plan_settings(wta) == {
        "blocks": ["base", "full"],
        "tour": "WTA",
        "experiment_id": "WTA02",
        "bootstrap_unit": "match",
    }
    both = tmp_path / "both.json"
    both.write_text(json.dumps({"blocks": ["base"], "bundles": ["base"], "year_plan": PLAN}))
    with pytest.raises(ChainError):
        configs.read_plan_settings(both)


def test_t_critical_matches_the_archived_values() -> None:
    assert configs.t_critical_95(7) == 2.364624251592784
    assert configs.t_critical_95(1) == 12.706204736174694
    assert configs.t_critical_95(0) is None


def _predictor_and_selection(
    workspace: Path, *, tour: str | None, raw_digest: str | None = None
) -> tuple[Path, Path]:
    runner.configure_years(PLAN)
    if tour is None:
        runner.configure_identity("TIER01", None)
        runner.configure_bundles(["base", "full", "base_tier", "full_tier"], ["hgb"])
    else:
        runner.configure_identity("WTA02", tour)
        runner.configure_bundles(["base", "traits", "dynamic", "full"], ["ridge", "hgb"])
    predictor = {
        "experiment_id": runner.EXPERIMENT_ID,
        "settings": runner.settings_document(),
        "design": {"path": "experiments/X.design.md", "sha256": "a" * 64},
        "inputs": {},
    }
    if tour is not None:
        predictor["reporting_settings"] = {
            "primary_contrast": "full_minus_base",
            "bootstrap_seed": 20260912,
            "bootstrap_unit": "match",
        }
    predictor_path = workspace / "config.json"
    predictor_path.write_text(json.dumps(predictor, indent=2, sort_keys=True) + "\n")
    selection = {
        "status": "complete",
        "outer_target_outcomes_scored": False,
        "config_sha256": sha256(predictor_path),
        "raw_complete_sha256": raw_digest or "b" * 64,
        "membership": {"selected_primary_rows": 100},
        "market_records": [{"target_rows": 40}, {"target_rows": 50}],
    }
    selection_path = workspace / "selection_complete.json"
    selection_path.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")
    return predictor_path, selection_path


def test_reporting_freeze_takes_the_contrast_and_seed_from_arguments(workspace: Path) -> None:
    predictor_path, selection_path = _predictor_and_selection(workspace, tour=None)
    document = configs.build_reporting(
        predictor_path,
        selection_path,
        primary_contrast="full_tier_minus_full",
        secondary_contrasts=["base_tier_minus_base"],
        bootstrap_seed=20260912,
        selected_primary_priced_rows=None,
        claim_limits=[],
    )
    settings = document["settings"]
    assert settings["primary_contrast"] == "full_tier_minus_full"
    assert settings["secondary_contrasts"] == ["base_tier_minus_base"]
    assert settings["bootstrap_seed"] == 20260912
    assert settings["t_critical_95"] == configs.t_critical_95(7)
    assert document["expected_membership"] == {
        "selected_primary_rows": 100,
        "selected_primary_priced_rows": 90,
    }
    assert document["code"]["reporter_path"] == "tennislab.evaluation.report"
    assert document["inputs"]["predictor_config"]["path"] == "config.json"


def test_reporting_freeze_inherits_the_tour_contracts_reporting_settings(workspace: Path) -> None:
    predictor_path, selection_path = _predictor_and_selection(workspace, tour="WTA")
    document = configs.build_reporting(
        predictor_path,
        selection_path,
        primary_contrast=None,
        secondary_contrasts=None,
        bootstrap_seed=None,
        selected_primary_priced_rows=None,
        claim_limits=[],
    )
    settings = document["settings"]
    assert document["experiment_id"] == "WTA02"
    assert settings["tour"] == "WTA"
    assert settings["bootstrap_unit"] == "match"
    assert settings["bootstrap_seed"] == 20260912
    assert settings["primary_contrast"] == "full_minus_base"
    assert settings["contrasts"][0] == "full_minus_base"
    assert "secondary_contrasts" not in settings


def test_b5_a_selection_ledger_with_an_empty_run_tree_digest_is_refused(workspace: Path) -> None:
    predictor_path, selection_path = _predictor_and_selection(
        workspace, tour=None, raw_digest=canonical_hash({})
    )
    with pytest.raises(ChainError, match="empty content"):
        configs.build_reporting(
            predictor_path,
            selection_path,
            primary_contrast="full_tier_minus_full",
            secondary_contrasts=None,
            bootstrap_seed=None,
            selected_primary_priced_rows=None,
            claim_limits=[],
        )


def test_a_selection_ledger_from_another_predictor_config_is_refused(workspace: Path) -> None:
    predictor_path, selection_path = _predictor_and_selection(workspace, tour=None)
    predictor_path.write_text(predictor_path.read_text() + "\n")
    with pytest.raises(ChainError, match="not produced from this predictor"):
        configs.build_reporting(
            predictor_path,
            selection_path,
            primary_contrast=None,
            secondary_contrasts=None,
            bootstrap_seed=None,
            selected_primary_priced_rows=None,
            claim_limits=[],
        )


def test_write_config_refuses_to_replace_and_stays_in_the_workspace(workspace: Path) -> None:
    output, digest = configs.write_config({"a": 1}, Path("out/config.json"))
    assert output == workspace / "out" / "config.json"
    assert digest == sha256(output)
    with pytest.raises(ChainError):
        configs.write_config({"a": 2}, Path("out/config.json"))
    with pytest.raises(ChainError):
        configs.write_config({"a": 2}, Path("../escape.json"))


# ------------------------------------------------------------------ the label accessor


LABEL_HEADER = "match_id,calendar_year,source_season,match_date,tourney_id,identity_tier,primary_target,a_won,status,source_field_agreement\n"


def _labels(tmp_path: Path) -> tuple[Path, dict]:
    rows = [
        ("m1", "2013", "2013-05-01", "1"),
        ("m2", "2014", "2014-05-01", "0"),
    ]
    text = LABEL_HEADER + "".join(
        f"{m},{y},{y},{d},{y}-T,primary,1,{a},completed,1\n" for m, y, d, a in rows
    )
    path = tmp_path / "labels.csv"
    path.write_text(text)
    metadata = {
        (y, m): {
            "calendar_year": y,
            "source_season": y,
            "match_date": d,
            "tourney_id": f"{y}-T",
            "identity_tier": "primary",
            "primary_target": "1",
            "source_field_agreement": "1",
        }
        for m, y, d, _ in rows
    }
    return path, metadata


def test_label_history_reads_only_declared_history(tmp_path: Path) -> None:
    path, metadata = _labels(tmp_path)
    history = LabelHistory(path, sha256(path), purpose="training_fit", year_ceiling=2013)
    table = history.selected([("2013", "m1")], metadata)
    assert table.values == {("2013", "m1"): 1}
    (receipt,) = history.reads
    assert receipt["purpose"] == "training_fit" and receipt["year_ceiling"] == 2013
    # The receipt separates what was physically parsed from what was returned (RB14).
    assert receipt["rows_parsed"] == 2 and receipt["rows_returned"] == 1
    assert receipt["max_season_returned"] == 2013
    with pytest.raises(ChainError, match="ceiling"):
        history.selected([("2013", "m1"), ("2014", "m2")], metadata)
    with pytest.raises(ChainError):
        LabelHistory(path, sha256(path), purpose="scoring")
    drifted = dict(metadata)
    drifted[("2013", "m1")] = {**metadata[("2013", "m1")], "tourney_id": "other"}
    with pytest.raises(ChainError, match="tourney_id mismatch"):
        history.selected([("2013", "m1")], drifted)
    with pytest.raises(ChainError, match="hash mismatch"):
        LabelHistory(path, "0" * 64, purpose="training_fit").selected([("2013", "m1")], metadata)
