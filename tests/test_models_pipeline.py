"""The runner's column contract, chronology, calibration and settings contracts.

Ported from the archive's JOINT04 ``test_runner.py`` and the runner cases of TIER01's
``test_tier01.py``; the tier_block cross-checks wait for that module.
"""

import datetime as dt
import math
from collections.abc import Iterator

import numpy as np
import pytest

from tennislab.chain.common import ChainError
from tennislab.models import pipeline as runner


@pytest.fixture(autouse=True)
def _restore_module_state() -> Iterator[None]:
    yield
    # Cohort before bundles: the no-dynamic cohort refuses the default four blocks.
    runner.configure_identity()
    runner.configure_years(runner.DEFAULT_YEAR_PLAN)
    runner.configure_cohort()
    runner.configure_bundles()


def contract() -> runner.FeatureContract:
    binary = tuple(
        f"context_{name}"
        for name in ("clay", "grass", "carpet", "best_of_5", "indoor", "indoor_unknown")
    )
    signed = tuple(f"base_{index}" for index in range(22))
    linear = tuple((*signed, *(f"linear_{index}" for index in range(140))))
    return runner.FeatureContract(
        base_linear=linear,
        base_signed=signed,
        binary_context=binary,
        hgb_base_context=(*binary, "ranking_global_age_days", "ranking_global_stale"),
        trait_interactions=tuple(
            f"{trait}_x_{context}" for trait in runner.TRAIT_SIGNED for context in binary
        ),
    )


def base_and_sidecar() -> tuple[dict[str, str], dict[str, str]]:
    base = {
        "match_id": "m1",
        "calendar_year": "2019",
        "source_season": "2019",
        "match_date": "2019-05-10",
        "eligible_through_date": "2019-05-08",
        "tourney_id": "2019-X",
        "surface": "Clay",
        "best_of": "3",
        "player_a": "10",
        "player_b": "20",
        "primary_target": "1",
        "identity_tier": "primary",
        "context_clay": "1",
        "context_grass": "0",
        "context_carpet": "0",
        "context_best_of_5": "0",
        "context_indoor": "0",
        "context_indoor_unknown": "0",
    }
    sidecar = dict(base)
    sidecar.update(
        {
            "age_years_at_target_a": "35",
            "age_missing_a": "0",
            "height_cm_a": "190",
            "height_missing_a": "0",
            "hand_a": "L",
            "hand_missing_a": "0",
            "age_years_at_target_b": "25",
            "age_missing_b": "0",
            "height_cm_b": "180",
            "height_missing_b": "0",
            "hand_b": "R",
            "hand_missing_b": "0",
            "dynamic_match_probability_a": "0.8",
        }
    )
    return base, sidecar


def swapped(base: dict[str, str], sidecar: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    other_base = dict(base)
    other_base["player_a"], other_base["player_b"] = base["player_b"], base["player_a"]
    other_sidecar = dict(sidecar)
    other_sidecar["player_a"], other_sidecar["player_b"] = (
        sidecar["player_b"],
        sidecar["player_a"],
    )
    for field in (
        "age_years_at_target",
        "age_missing",
        "height_cm",
        "height_missing",
        "hand",
        "hand_missing",
    ):
        other_sidecar[f"{field}_a"], other_sidecar[f"{field}_b"] = (
            sidecar[f"{field}_b"],
            sidecar[f"{field}_a"],
        )
    other_sidecar["dynamic_match_probability_a"] = repr(
        1.0 - float(sidecar["dynamic_match_probability_a"])
    )
    return other_base, other_sidecar


def aligned(year: str, date: str, **overrides: str) -> dict[str, str]:
    row = {
        "calendar_year": year,
        "source_season": year,
        "match_date": date,
        "primary_target": "1",
        "identity_tier": "primary",
        "sr02_selected_match_present": "1",
        "dynamic_match_probability_a": "0.6",
    }
    row.update(overrides)
    return row


# ------------------------------------------------------------------ chronology


def test_training_windows_retain_2011_and_end_december_30() -> None:
    assert runner.training_window(2014) == (dt.date(2011, 1, 1), dt.date(2013, 12, 30))
    assert runner.training_window(2015) == (dt.date(2011, 1, 1), dt.date(2014, 12, 30))
    assert runner.training_window(2019) == (dt.date(2014, 1, 1), dt.date(2018, 12, 30))
    assert runner.validation_years(2017) == (2014, 2015, 2016)


def test_source_year_alignment_not_sr02_warmup_flag() -> None:
    metadata = {
        ("2011", "keep"): aligned("2011", "2011-01-03"),
        ("2011", "drop"): aligned("2011", "2011-12-31", source_season="2012"),
        ("2012", "keep2"): aligned("2012", "2012-02-01"),
        ("2013", "keep3"): aligned("2013", "2013-12-30"),
        ("2013", "late"): aligned("2013", "2013-12-31"),
    }
    keys = runner.training_keys(metadata, 2014)
    assert ("2011", "keep") in keys
    assert ("2011", "drop") not in keys
    assert ("2013", "keep3") in keys
    assert ("2013", "late") not in keys


def test_primary_and_provisional_targets_are_disjoint() -> None:
    metadata = {
        ("2019", "p"): aligned("2019", "2019-05-01"),
        ("2019", "x"): aligned(
            "2019",
            "2019-05-02",
            primary_target="0",
            identity_tier="provisional",
            dynamic_match_probability_a="0.55",
        ),
    }
    primary = runner.target_keys(metadata, 2019)
    provisional = runner.provisional_target_keys(metadata, 2019)
    assert primary == (("2019", "p"),)
    assert provisional == (("2019", "x"),)
    assert runner.all_prediction_keys(metadata, 2019) == (("2019", "p"), ("2019", "x"))


def test_the_no_dynamic_cohort_admits_rows_without_a_dynamic_probability() -> None:
    row = aligned("2019", "2019-05-01", sr02_selected_match_present="0")
    row["dynamic_match_probability_a"] = ""
    assert runner.is_aligned_primary(row) is False
    runner.configure_bundles(["base", "traits"], ["ridge", "hgb"])
    runner.configure_cohort("aligned_primary_no_dynamic")
    assert runner.is_aligned_primary(row) is True
    with pytest.raises(ChainError):
        runner.configure_bundles(["base", "full"], ["hgb"])


# ------------------------------------------------------------------ features


def test_swap_negates_signed_and_preserves_symmetric_contexts() -> None:
    base, sidecar = base_and_sidecar()
    first = runner.transformed_additions(base, sidecar, contract())
    second = runner.transformed_additions(*swapped(base, sidecar), contract())
    for field in (*runner.TRAIT_SIGNED, *contract().trait_interactions, *runner.DYNAMIC_SIGNED):
        assert math.isclose(float(first[field]), -float(second[field]), abs_tol=1e-13), field
    for field in runner.TRAIT_HGB_CONTEXT:
        assert math.isclose(float(first[field]), float(second[field]), abs_tol=1e-13), field


def test_one_sided_and_two_sided_missingness() -> None:
    base, sidecar = base_and_sidecar()
    sidecar.update(
        {"height_missing_a": "1", "height_cm_a": "", "hand_missing_b": "1", "hand_b": "U"}
    )
    values = runner.transformed_additions(base, sidecar, contract())
    assert float(values["trait_height_10cm_diff"]) == 0.0
    assert float(values["trait_height_missing_diff"]) == 1.0
    assert float(values["trait_hand_missing_diff"]) == -1.0
    assert float(values["trait_height_missing_sum"]) == 1.0
    assert float(values["trait_hand_missing_sum"]) == 1.0
    other = dict(sidecar)
    other.update({"height_missing_b": "1", "height_cm_b": "", "hand_missing_a": "1", "hand_a": "?"})
    both = runner.transformed_additions(base, other, contract())
    assert float(both["trait_height_missing_diff"]) == 0.0
    assert float(both["trait_height_missing_sum"]) == 2.0
    assert float(both["trait_hand_missing_diff"]) == 0.0
    assert float(both["trait_hand_missing_sum"]) == 2.0


def test_column_contract_and_capacity_menu() -> None:
    c = contract()
    ridge_traits, ridge_context = c.model_columns("ridge", "traits")
    assert len(ridge_traits) == 162 + 49
    assert ridge_context == ()
    hgb_traits, hgb_context = c.model_columns("hgb", "traits")
    assert len(hgb_traits) == 29
    assert len(hgb_context) == 13
    larger = runner.numerical_config(c, "hgb", "full", "hgb_leaf15_depth4")
    assert larger["estimator_params"]["max_leaf_nodes"] == 15
    assert larger["estimator_params"]["max_depth"] == 4


def test_dictionary_lists_reject_outcomes_ids_and_market_fields() -> None:
    c = contract()
    dictionary = {
        "linear_sports_model_features": list(c.base_linear),
        "signed_base_model_features": list(c.base_signed),
        "binary_context_columns": list(c.binary_context),
        "identifier_and_split_columns": ["match_id"],
        "label_file_columns": ["a_won", "status"],
        "contemporaneous_pinnacle_fields": ["ps_probability_a", "ps_logit_a", "ps_missing"],
        "lagged_market_elo_features": [
            "lagged_market_elo_overall_logit",
            "lagged_market_elo_surface_logit",
        ],
    }
    for forbidden in ("a_won", "match_id", "ps_probability_a", "lagged_market_elo_overall_logit"):
        changed = dict(dictionary)
        fields = list(dictionary["linear_sports_model_features"])
        fields[-1] = forbidden
        changed["linear_sports_model_features"] = fields
        with pytest.raises(ChainError):
            runner.FeatureContract.from_dictionary(changed)


def test_join_rejects_exact_metadata_drift() -> None:
    base, sidecar = base_and_sidecar()
    sidecar["best_of"] = "5"
    with pytest.raises(ChainError, match="best_of mismatch"):
        runner.transformed_additions(base, sidecar, contract())


def test_ridge_rms_is_fit_local() -> None:
    c = contract()
    header = ("season", "match_id", *c.base_linear)
    rows = []
    values = (-2.0, -1.0, 0.5, 1.0, 2.0, 3.0)
    for index, value in enumerate(values):
        row = {"season": "2013", "match_id": f"m{index}"}
        row.update({column: repr(value * (j + 1)) for j, column in enumerate(c.base_linear)})
        rows.append(row)
    train = runner.NUM.FeatureTable.from_rows(rows, header)
    labels = runner.NUM.LabelTable.from_values(
        {key: int(index % 2 == 0) for index, key in enumerate(train.keys)}
    )
    fit = runner.NUM.fit_procedure(
        runner.numerical_config(c, "ridge", "base", "ridge_c1"), train, labels
    )
    assert fit.status == "complete"
    assert fit.fitted is not None and fit.fitted.rms_scale is not None
    expected = np.sqrt(np.mean(np.square(train.matrix(c.base_linear)), axis=0))
    np.testing.assert_allclose(fit.fitted.rms_scale, expected, rtol=0.0, atol=0.0)
    before = fit.fitted.rms_scale.copy()
    target_row = {"season": "2014", "match_id": "target"}
    target_row.update({column: repr(1e8 * (j + 1)) for j, column in enumerate(c.base_linear)})
    fit.fitted.predict(runner.NUM.FeatureTable.from_rows([target_row], header))
    np.testing.assert_array_equal(fit.fitted.rms_scale, before)


# ------------------------------------------------------------------ tier bundles


def test_tier_columns_are_not_forbidden_and_every_provenance_column_is() -> None:
    model = (*runner.TIER_SIGNED, *runner.TIER_DYNAMIC_SIGNED, *runner.TIER_NOQUAL_DYNAMIC_SIGNED)
    assert sorted(runner.FORBIDDEN_MODEL_COLUMNS.intersection(model)) == []
    provenance = {*runner.TIER_PROVENANCE_ONLY_COLUMNS, *runner.TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS}
    assert sorted(provenance - runner.FORBIDDEN_MODEL_COLUMNS) == []


def test_tier_bundles_append_and_remove_nothing() -> None:
    c = contract()
    runner.configure_bundles(["base", "full", "base_tier", "full_tier"], ["hgb"])
    for stem in ("base", "full"):
        plain = c.model_columns("hgb", stem)
        tiered = c.model_columns("hgb", f"{stem}_tier")
        assert tiered[0][: len(plain[0])] == plain[0]
        assert tiered[1] == plain[1]
        expected = runner.TIER_SIGNED + (runner.TIER_DYNAMIC_SIGNED if stem == "full" else ())
        assert tiered[0][len(plain[0]) :] == expected
    signed, _ = c.model_columns("hgb", "full_tier")
    assert "dynamic_match_logit" in signed and "tier_dynamic_match_logit" in signed


def test_the_ablation_bundle_swaps_only_the_dynamic_logit() -> None:
    assert runner.split_block("full_tier_noqual") == ("full", "tier_noqual")
    assert runner.split_block("full_tier") == ("full", "tier")
    assert runner.split_block("full") == ("full", "")
    c = contract()
    runner.configure_bundles(
        ["base", "full", "base_tier", "full_tier", "full_tier_noqual"], ["hgb"]
    )
    tiered, context = c.model_columns("hgb", "full_tier")
    ablated, ablated_context = c.model_columns("hgb", "full_tier_noqual")
    assert context == ablated_context
    assert len(tiered) == len(ablated)
    assert [name for name in tiered if name != "tier_dynamic_match_logit"] == [
        name for name in ablated if name != "tier_noqual_dynamic_match_logit"
    ]
    assert "tier_noqual_dynamic_match_logit" in ablated
    assert "tier_dynamic_match_logit" not in ablated
    assert runner.settings_document()["tier_columns"] == list(runner.TIER_COLUMNS) + list(
        runner.TIER_NOQUAL_COLUMNS
    )


def test_joint04_bundles_alone_add_no_tier_column() -> None:
    runner.configure_bundles(["base", "traits", "dynamic", "full"], ["ridge", "hgb"])
    assert runner.tier_enabled() is False
    assert runner.settings_document()["tier_columns"] == []
    assert len(contract().all_columns) == len(set(contract().all_columns))


def test_ridge_and_unknown_blocks_are_refused() -> None:
    with pytest.raises(ChainError):
        runner.configure_bundles(["full_tier"], ["ridge", "hgb"])
    with pytest.raises(ChainError):
        runner.configure_bundles(["full_nonsense"], ["hgb"])
    with pytest.raises(ChainError):
        runner.configure_bundles(["base", "base"], ["hgb"])


# ------------------------------------------------------------------ the two settings contracts


def test_the_tier_contract_freezes_tier_columns_and_no_tour() -> None:
    runner.configure_identity(None, None)
    runner.configure_bundles(["base", "full", "base_tier", "full_tier"], ["hgb"])
    settings = runner.settings_document()
    assert runner.EXPERIMENT_ID == "TIER01"
    assert "tier_columns" in settings
    assert "tour" not in settings and "cohort" not in settings


def test_the_tour_contract_freezes_tour_and_cohort_and_refuses_tier_bundles() -> None:
    runner.configure_identity("WTA02", "wta")
    settings = runner.settings_document()
    assert (runner.EXPERIMENT_ID, runner.TOUR) == ("WTA02", "WTA")
    assert settings["tour"] == "WTA" and settings["cohort"] == "aligned_primary"
    assert "tier_columns" not in settings
    with pytest.raises(ChainError):
        runner.configure_bundles(["base", "full", "full_tier"], ["hgb"])
    with pytest.raises(ChainError):
        runner.configure_identity("X", "ITF")
    with pytest.raises(ChainError):
        runner.configure_identity("bad id", None)


# ------------------------------------------------------------------ calibration


def test_equal_year_weighting_and_finite_nonnegative_slope() -> None:
    probabilities = {2014: [0.7, 0.4], 2015: [0.65] * 20, 2016: [0.3, 0.8, 0.55]}
    labels = {2014: [1, 0], 2015: [1] * 15 + [0] * 5, 2016: [0, 1, 0]}
    result = runner.fit_nonnegative_slope(probabilities, labels, (2014, 2015, 2016))
    assert result["status"] == "complete"
    assert result["slope"] >= 0.0
    expected = sum(result["annual"][str(year)]["mean_log_loss"] for year in (2014, 2015, 2016)) / 3
    assert math.isclose(result["equal_year_mean_log_loss"], expected, abs_tol=1e-14)


def test_zero_slope_boundary_is_valid() -> None:
    probabilities = {2014: [0.9, 0.1], 2015: [0.8, 0.2], 2016: [0.7, 0.3]}
    labels = {year: [0, 1] for year in probabilities}
    result = runner.fit_nonnegative_slope(probabilities, labels, (2014, 2015, 2016))
    assert result["status"] == "complete"
    assert result["slope"] == 0.0
    assert math.isclose(result["equal_year_mean_log_loss"], math.log(2), abs_tol=1e-14)


def test_perfect_separation_fails_instead_of_using_arbitrary_slope_cap() -> None:
    probabilities = {year: [0.2, 0.8] for year in (2014, 2015, 2016)}
    labels = {year: [0, 1] for year in (2014, 2015, 2016)}
    result = runner.fit_nonnegative_slope(probabilities, labels, (2014, 2015, 2016))
    assert result["status"] == "failed"
    assert "no finite nonnegative bracket" in result["error"]["message"]


def test_candidate_selection_ties_to_simpler_and_reports_gap() -> None:
    trials = {
        "simple": {"status": "complete", "slope": 0.8, "equal_year_mean_log_loss": 0.6 + 5e-13},
        "complex": {"status": "complete", "slope": 0.9, "equal_year_mean_log_loss": 0.6},
    }
    selected = runner.select_calibrated_candidate(trials, ("simple", "complex"))
    assert selected["selected_candidate_id"] == "simple"
    assert math.isclose(selected["runner_up_gap"], 5e-13, abs_tol=1e-15)
    assert (
        selected["score_semantics"]
        == "past_in_sample_nuisance_calibration_plus_complexity_selection"
    )


def test_one_failed_candidate_invalidates_complete_menu() -> None:
    trials = {
        "simple": {"status": "complete", "slope": 0.8, "equal_year_mean_log_loss": 0.6},
        "complex": {"status": "failed", "error": {"type": "Synthetic", "message": "failed"}},
    }
    selected = runner.select_calibrated_candidate(trials, ("simple", "complex"))
    assert selected["status"] == "unavailable_incomplete_candidate_menu"
    assert selected["selected_candidate_id"] is None
    assert selected["unavailable"][0]["candidate_id"] == "complex"


def test_logit_and_score_clips_are_separate_at_probability_boundaries() -> None:
    base, sidecar = base_and_sidecar()
    sidecar["dynamic_match_probability_a"] = "1e-30"
    values = runner.transformed_additions(base, sidecar, contract())
    expected_logit = math.log(runner.LOGIT_CLIP / (1.0 - runner.LOGIT_CLIP))
    assert math.isclose(float(values["dynamic_match_logit"]), expected_logit, abs_tol=1e-14)
    x, y, weights, clipped = runner.weighted_calibration_arrays(
        {2014: [1e-30], 2015: [0.5], 2016: [1.0 - 1e-30]},
        {2014: [0], 2015: [1], 2016: [1]},
        (2014, 2015, 2016),
    )
    assert clipped == 2
    assert math.isclose(float(x[0]), expected_logit, abs_tol=1e-14)
    assert runner.SCORE_CLIP == 1e-15
    assert math.isclose(float(np.sum(weights)), 1.0, abs_tol=1e-14)
    assert y.tolist() == [0.0, 1.0, 1.0]


def test_apply_slope_preserves_complement() -> None:
    p = runner.apply_slope([0.2, 0.8], 1.7)
    assert math.isclose(float(p[0] + p[1]), 1.0, abs_tol=1e-14)


def test_market_missingness_disagreement_fails_closed() -> None:
    metadata = aligned("2019", "2019-05-01", ps_missing="0", ps_probability_a="")
    with pytest.raises(ChainError, match="conflicts"):
        runner.is_valid_market(metadata)


# ------------------------------------------------------------------ declared code bindings


def test_a_binding_naming_the_package_module_must_match_it() -> None:
    receipts = runner.code_receipts()
    archive = {
        "runner_path": "references/TIER01_models/runner.py",
        "runner_sha256": "2fa405f7c0220655cf74b6826a4d4bbce240717dbafce379939e6d9bfb655260",
        "numerical_path": "references/MULTI01_models/numerical.py",
        "numerical_sha256": "e3c1db5d7785b8b204f4024853cd2459b4a23829c0ce6a719119aa5f8fc1a367",
    }
    assert runner.declared_code_binding(archive) == archive
    package = {
        "runner_path": "tennislab.models.pipeline",
        "runner_sha256": receipts["runner"]["sha256"],
        "numerical_path": "tennislab.models.numerical",
        "numerical_sha256": receipts["numerical"]["sha256"],
    }
    assert runner.declared_code_binding(package) == package
    with pytest.raises(ChainError):
        runner.declared_code_binding({**package, "runner_sha256": "0" * 64})
    with pytest.raises(ChainError):
        runner.declared_code_binding({**archive, "numerical_sha256": "PENDING"})
