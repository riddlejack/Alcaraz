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


# ------------------------------------------------------------------ ARMS01: the entry/level block

ENTRY_BUNDLES = ["base", "full", "base_tier", "full_tier", "full_tier_noqual", "full_tier_entry"]
ENTRY_BLOCK = {
    "entry_q_diff": "1",
    "entry_ll_diff": "0",
    "entry_wc_diff": "-1",
    "entry_pr_diff": "0",
    "entry_any_qualifier": "1",
    "level_context_g": "0",
    "level_context_m": "1",
    "level_context_a": "0",
    "level_context_f": "0",
}


def entry_contract() -> runner.FeatureContract:
    c = contract()
    return runner.FeatureContract(
        c.base_linear,
        c.base_signed,
        c.binary_context,
        c.hgb_base_context,
        c.trait_interactions,
        runner.ENTRY_LEVEL_COLUMNS,
    )


def with_tier(sidecar: dict[str, str]) -> dict[str, str]:
    tiered = dict(sidecar)
    tiered.update(
        {
            "tier_elo_overall_logit": "0.3",
            "tier_elo_surface_logit": "0.1",
            "tier_prior_matches_diff": "4",
            "tier_prior_titles_diff": "1",
            "tier_dynamic_match_probability_a": "0.7",
            "tier_noqual_dynamic_match_probability_a": "0.65",
        }
    )
    return tiered


def swapped_tier(sidecar: dict[str, str]) -> dict[str, str]:
    other = dict(sidecar)
    for column in runner.TIER_SIGNED:
        other[column] = repr(-float(sidecar[column]))
    for column in (
        "tier_dynamic_match_probability_a",
        "tier_noqual_dynamic_match_probability_a",
    ):
        other[column] = repr(1.0 - float(sidecar[column]))
    return other


def test_the_entry_block_columns_agree_with_the_features_stage() -> None:
    from tennislab.features import base as features

    assert runner.ENTRY_LEVEL_SIGNED == features.ENTRY_LEVEL_SIGNED
    assert runner.ENTRY_LEVEL_CONTEXT == features.ENTRY_LEVEL_CONTEXT
    assert runner.ENTRY_LEVEL_COLUMNS == features.ENTRY_LEVEL_COLUMNS
    assert runner.ENTRY_RAW_COLUMNS == features.ENTRY_RAW_AUDIT_COLUMNS
    assert runner.split_block("full_tier_entry") == ("full", "tier_entry")
    assert runner.split_block("base_tier_entry") == ("base", "tier_entry")


def test_the_entry_block_negates_signed_and_keeps_context_under_swap() -> None:
    runner.configure_bundles(ENTRY_BUNDLES, ["hgb"])
    base, sidecar = base_and_sidecar()
    base.update(ENTRY_BLOCK)
    sidecar = with_tier(sidecar)
    first = runner.transformed_additions(base, sidecar, entry_contract())
    other_base, other_sidecar = swapped(base, sidecar)
    for column in runner.ENTRY_LEVEL_SIGNED:
        other_base[column] = str(-int(base[column]))
    second = runner.transformed_additions(other_base, swapped_tier(other_sidecar), entry_contract())
    for field in (*runner.ENTRY_LEVEL_SIGNED, *runner.TIER_SIGNED, *runner.TIER_DYNAMIC_SIGNED):
        assert float(first[field]) == -float(second[field]), field
    for field in runner.ENTRY_LEVEL_CONTEXT:
        assert float(first[field]) == float(second[field]), field
    assert float(first["entry_q_diff"]) == 1.0 and float(first["entry_wc_diff"]) == -1.0
    assert float(first["entry_any_qualifier"]) == 1.0 and float(first["level_context_m"]) == 1.0
    # A blank, a raw code or an out-of-range cell fails closed rather than becoming a zero.
    for column, bad in (("entry_q_diff", ""), ("entry_q_diff", "Q"), ("entry_q_diff", "2")):
        broken = dict(base)
        broken[column] = bad
        with pytest.raises(ChainError, match="must be -1/0/1"):
            runner.transformed_additions(broken, sidecar, entry_contract())
    broken = dict(base)
    broken["level_context_g"] = "-1"
    with pytest.raises(ChainError):
        runner.transformed_additions(broken, sidecar, entry_contract())


def test_the_entry_bundle_appends_the_block_after_full_tier_and_removes_nothing() -> None:
    c = entry_contract()
    runner.configure_bundles(ENTRY_BUNDLES, ["hgb"])
    tier_signed, tier_context = c.model_columns("hgb", "full_tier")
    entry_signed, entry_context = c.model_columns("hgb", "full_tier_entry")
    assert entry_signed == (*tier_signed, *runner.ENTRY_LEVEL_SIGNED)
    assert entry_context == (*tier_context, *runner.ENTRY_LEVEL_CONTEXT)
    assert "tier_dynamic_match_logit" in entry_signed and "dynamic_match_logit" in entry_signed
    base_signed, base_context = c.campaign_model_columns("hgb", "base_tier_entry")
    assert base_signed[-4:] == runner.ENTRY_LEVEL_SIGNED and base_context[-5:] == entry_context[-5:]
    assert "tier_dynamic_match_logit" not in base_signed
    assert c.all_columns[-9:] == runner.ENTRY_LEVEL_COLUMNS
    assert len(c.all_columns) == len(set(c.all_columns))
    # The block reaches no bundle that did not ask for it.
    for block in ("base", "full", "base_tier", "full_tier", "full_tier_noqual"):
        signed, context = c.model_columns("hgb", block)
        assert not set(runner.ENTRY_LEVEL_COLUMNS) & {*signed, *context}, block


def test_with_the_variant_off_every_column_order_is_todays() -> None:
    runner.configure_bundles(
        ["base", "full", "base_tier", "full_tier", "full_tier_noqual"], ["hgb"]
    )
    assert runner.entry_enabled() is False
    plain = contract()
    declared = entry_contract()
    for c in (plain, declared):
        assert not set(runner.ENTRY_LEVEL_COLUMNS) & set(c.all_columns)
        assert c.all_columns == plain.all_columns
        for block in ("base", "full", "base_tier", "full_tier", "full_tier_noqual"):
            assert c.model_columns("hgb", block) == plain.model_columns("hgb", block)
    assert "entry_level_columns" not in runner.settings_document()
    runner.configure_bundles(["base", "traits", "dynamic", "full"], ["ridge", "hgb"])
    assert "entry_level_columns" not in runner.settings_document()


def test_the_settings_document_records_the_block_only_with_an_entry_bundle() -> None:
    runner.configure_bundles(["full_tier", "full_tier_entry"], ["hgb"])
    settings = runner.settings_document()
    assert settings["entry_level_columns"] == list(runner.ENTRY_LEVEL_COLUMNS)
    assert settings["tier_columns"] == list(runner.TIER_COLUMNS)
    assert settings["blocks"] == ["full_tier", "full_tier_entry"]
    with pytest.raises(ChainError):
        runner.configure_bundles(["full_tier_entry"], ["ridge", "hgb"])
    # The tour contract cannot record an entry bundle, exactly as it cannot a tier one.
    runner.configure_bundles(["base", "full"], ["hgb"])
    runner.configure_identity("WTA02", "WTA")
    with pytest.raises(ChainError):
        runner.configure_bundles(["base", "full", "full_tier_entry"], ["hgb"])


def test_an_entry_bundle_without_the_features_block_is_refused() -> None:
    runner.configure_bundles(["full_tier", "full_tier_entry"], ["hgb"])
    with pytest.raises(ChainError, match="entry_level_block"):
        contract().model_columns("hgb", "full_tier_entry")
    with pytest.raises(ChainError, match="entry_level_block"):
        runner.ordered_model_columns(contract())


def entry_dictionary(**overrides: object) -> dict[str, object]:
    c = contract()
    document: dict[str, object] = {
        "linear_sports_model_features": list(c.base_linear),
        "signed_base_model_features": list(c.base_signed),
        "binary_context_columns": list(c.binary_context),
        "identifier_and_split_columns": ["match_id", "tourney_level", "round"],
        "label_file_columns": ["a_won", "status"],
        "contemporaneous_pinnacle_fields": ["ps_probability_a", "ps_logit_a", "ps_missing"],
        "lagged_market_elo_features": [
            "lagged_market_elo_overall_logit",
            "lagged_market_elo_surface_logit",
        ],
        "entry_level_columns": list(runner.ENTRY_LEVEL_COLUMNS),
        "entry_level_signed_columns": list(runner.ENTRY_LEVEL_SIGNED),
        "entry_level_context_columns": list(runner.ENTRY_LEVEL_CONTEXT),
    }
    document.update(overrides)
    return document


def test_raw_draw_time_columns_stay_forbidden_and_a_dictionary_listing_them_is_refused() -> None:
    for raw in ("tourney_level", "round", "a_entry", "b_entry", "a_seed", "b_seed", "draw_size"):
        assert raw in runner.FORBIDDEN_MODEL_COLUMNS, raw
    assert not set(runner.ENTRY_LEVEL_COLUMNS) & runner.FORBIDDEN_MODEL_COLUMNS
    c = runner.FeatureContract.from_dictionary(entry_dictionary())
    assert c.entry_level == runner.ENTRY_LEVEL_COLUMNS
    assert runner.FeatureContract.from_dictionary(contract_dictionary()).entry_level == ()
    # The raw code, the raw level or the round listed as a model column is refused.
    for raw in ("a_entry", "tourney_level", "round"):
        columns = [*runner.ENTRY_LEVEL_COLUMNS[:-1], raw]
        with pytest.raises(ChainError):
            runner.FeatureContract.from_dictionary(entry_dictionary(entry_level_columns=columns))
    # The block must be the runner's, to the column and to the signed/context split.
    with pytest.raises(ChainError, match="differ from the runner"):
        runner.FeatureContract.from_dictionary(
            entry_dictionary(entry_level_columns=list(reversed(runner.ENTRY_LEVEL_COLUMNS)))
        )
    with pytest.raises(ChainError, match="split"):
        runner.FeatureContract.from_dictionary(
            entry_dictionary(entry_level_signed_columns=list(runner.ENTRY_LEVEL_COLUMNS))
        )
    # And the assembled column set is checked against the forbidden set as a whole.
    runner.configure_bundles(["full_tier", "full_tier_entry"], ["hgb"])
    assert not runner.FORBIDDEN_MODEL_COLUMNS & set(entry_contract().all_columns)


def contract_dictionary() -> dict[str, object]:
    document = entry_dictionary()
    for key in ("entry_level_columns", "entry_level_signed_columns", "entry_level_context_columns"):
        del document[key]
    return document


def test_an_hgb_fit_on_the_entry_bundle_is_exactly_swap_symmetric() -> None:
    """The numerical adapter negates the signed list and keeps the context list on both
    the training augmentation and the prediction symmetrisation; with the entry/level
    block in those lists a player swap complements the emitted probability exactly."""
    from tennislab.models import numerical as num

    runner.configure_bundles(["full_tier", "full_tier_entry"], ["hgb"])
    c = entry_contract()
    signed, context = c.model_columns("hgb", "full_tier_entry")
    config = runner.numerical_config(c, "hgb", "full_tier_entry", "hgb_leaf07_depth3")
    assert config["signed_numeric_columns"][-4:] == list(runner.ENTRY_LEVEL_SIGNED)
    assert config["context_columns"][-5:] == list(runner.ENTRY_LEVEL_CONTEXT)
    rng = np.random.default_rng(20260922)
    header = ("season", "match_id", *signed, *context)

    def rows(count: int, season: str) -> list[dict[str, str]]:
        table = []
        for index in range(count):
            row = {"season": season, "match_id": f"{season}-{index}"}
            for column in signed:
                if column in runner.ENTRY_LEVEL_SIGNED:
                    row[column] = repr(float(rng.integers(-1, 2)))
                else:
                    row[column] = repr(float(rng.normal()))
            for column in context:
                row[column] = repr(float(rng.integers(0, 2)))
            table.append(row)
        return table

    train_rows = rows(600, "2015")
    train = num.FeatureTable.from_rows(train_rows, header)
    strength = np.asarray(
        [float(row["entry_q_diff"]) + float(row[signed[0]]) for row in train.rows]
    )
    labels = num.LabelTable.from_values(
        {
            key: int(rng.random() < 1 / (1 + np.exp(-value)))
            for key, value in zip(train.keys, strength, strict=True)
        }
    )
    attempt = num.fit_procedure(config, train, labels)
    assert attempt.status == "complete" and attempt.fitted is not None, attempt.error
    test_rows = rows(200, "2016")
    swapped_rows = []
    for row in test_rows:
        other = dict(row)
        for column in signed:
            other[column] = repr(-float(row[column]))
        swapped_rows.append(other)
    original = attempt.fitted.predict(num.FeatureTable.from_rows(test_rows, header))
    mirrored = attempt.fitted.predict(num.FeatureTable.from_rows(swapped_rows, header))
    assert np.max(np.abs(original.probabilities + mirrored.probabilities - 1.0)) <= 1e-12
    assert np.std(original.probabilities) > 0.0


def test_the_ll_sensitivity_dictionary_gives_the_identical_feature_contract() -> None:
    """ARMS01 Arm 1-LLx changes values, not columns: the pipeline reads the same contract."""
    from tennislab.features import base as features

    arm1 = runner.FeatureContract.from_dictionary(features.column_dictionary(True))
    llx = runner.FeatureContract.from_dictionary(features.column_dictionary(True, True))
    assert llx == arm1
    assert llx.entry_level == runner.ENTRY_LEVEL_COLUMNS


def test_the_registered_any_qualifier_dictionary_gives_the_identical_feature_contract() -> None:
    """ARMS01 attempt 002 changes one column's values, not the columns the pipeline reads."""
    from tennislab.features import base as features

    attempt1 = runner.FeatureContract.from_dictionary(features.column_dictionary(True))
    attempt2 = runner.FeatureContract.from_dictionary(
        features.column_dictionary(True, any_qualifier_counts_ll=False)
    )
    assert attempt2 == attempt1
