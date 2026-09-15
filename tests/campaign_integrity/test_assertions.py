"""Planted defects through the same public assertions used by the synthetic harness."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from tennislab.chain.labels import LabelHistory, LabelHistoryError
from tennislab.integrity.campaign import (
    CampaignIntegrityError,
    assert_fit_frame,
    assert_forecasts,
    assert_learned_horizon,
    assert_raw_member,
    assert_source_uses,
    assert_swap,
    null_score,
)
from tennislab.models import numerical as num
from tests.campaign_integrity.primitives import mirror_participants, reconstruct, simulate


@pytest.fixture
def fit_input():
    records = [
        {"season": "2016", "match_id": f"m{i}", "sports": str(i / 9), "context": "1"}
        for i in range(20)
    ]
    frame = num.FeatureTable.from_rows(records, tuple(records[0]))
    labels = num.LabelTable.from_values({key: i % 2 for i, key in enumerate(frame.keys)})
    model = {
        "family": "hist_gradient_boosting",
        "signed_numeric_columns": ["sports"],
        "context_columns": ["context"],
    }
    args = dict(
        approved_signed=["sports"],
        approved_context=["context"],
        reference=frame,
        expected_keys=frame.keys,
        metadata={
            k: {"match_date": "2016-01-08", "eligible_through_date": "2016-01-06"}
            for k in frame.keys
        },
        fit_start="2012-01-01",
        fit_through="2016-12-30",
        prediction_year=2017,
    )
    return model, frame, labels, args


def test_actual_clean_fit_frame(fit_input):
    model, frame, labels, args = fit_input
    result = assert_fit_frame(model, frame, labels, **args)
    assert result["rows"] == 20 and result["columns"] == ["sports", "context"]
    assert len(result["matrix_sha256"]) == 64


@pytest.mark.parametrize(
    "defect",
    [
        "current_copy",
        "next_copy",
        "price",
        "swapped_values",
        "late_fit",
        "late_feature",
        "order",
        "drop_label",
    ],
)
def test_fit_assertion_rejects_actual_planted_input(fit_input, defect):
    model, frame, labels, args = copy.deepcopy(fit_input)
    records = [dict(r) for r in frame.rows]
    if defect in ("current_copy", "next_copy"):
        y = labels.align_exact(frame.keys)
        values = y if defect == "current_copy" else np.roll(y, -1)
        for row, value in zip(records, values, strict=True):
            row["sports"] = str(2 * value - 1)
        frame = num.FeatureTable.from_rows(records, frame.header)
    elif defect == "price":
        for row in records:
            row["PS_decimal_a"] = "1.8"
        frame = num.FeatureTable.from_rows(records, (*frame.header, "PS_decimal_a"))
        model["signed_numeric_columns"] = ["PS_decimal_a"]
    elif defect == "swapped_values":
        for row in records:
            row["sports"] = str(-float(row["sports"]))
        frame = num.FeatureTable.from_rows(records, frame.header)
    elif defect == "late_fit":
        args["fit_through"] = "2017-02-01"
    elif defect == "late_feature":
        args["metadata"][frame.keys[0]]["eligible_through_date"] = "2016-01-07"
    elif defect == "order":
        # Bypass the normal canonical constructor to plant a real malformed frame.
        frame = num.FeatureTable(
            frame.header, tuple(reversed(frame.rows)), frame.source_path, frame.source_sha256
        )
    elif defect == "drop_label":
        labels = num.LabelTable.from_values(
            {k: v for k, v in labels.values.items() if k != frame.keys[0]}
        )
    with pytest.raises((CampaignIntegrityError, num.NumericalError)):
        assert_fit_frame(model, frame, labels, **args)


@pytest.mark.parametrize("defect", ["same_target", "next_outcome", "price_source"])
def test_observed_source_use_rejects_prohibited_edges(defect):
    row = {
        "target_match_id": "target",
        "source_match_id": "past",
        "source_kind": "sports_history",
        "source_date": "2016-01-06",
        "eligible_through_date": "2016-01-06",
    }
    assert_source_uses([row])  # Inclusive same-cutoff history is admitted.
    if defect == "same_target":
        row["source_match_id"] = "target"
    elif defect == "next_outcome":
        row.update(source_match_id="next_player_match", source_date="2016-01-09")
    else:
        row["source_kind"] = "market_price"
    with pytest.raises(CampaignIntegrityError):
        assert_source_uses([row])


def member_receipt():
    keys = (("2017", "m1"), ("2017", "m2"))
    receipt = {
        "member_id": "hgb7",
        "prediction_year": 2017,
        "procedure": "predeclared_raw_candidate",
        "selection_years": [],
        "calibration_years": [],
        "horizons": {
            s: "2016-12-30" for s in ("base_fit", "preprocessing", "state_policy", "offset")
        },
        "prediction_keys_sha256": num.key_hash(keys),
        **{
            n: "ab" * 32
            for n in ("features_sha256", "training_keys_sha256", "preprocessing_sha256")
        },
    }
    return keys, receipt


@pytest.mark.parametrize(
    "defect",
    ["selected", "same_year_slope", "late_offset", "late_preprocessing", "omitted_member_keys"],
)
def test_stack_rejects_same_fold_member_and_horizon_contamination(defect):
    keys, receipt = member_receipt()
    assert_raw_member(receipt, raw_year=2017, member_id="hgb7", expected_keys=keys)
    if defect == "selected":
        receipt["procedure"] = "selected_calibrated"
    elif defect == "same_year_slope":
        receipt["calibration_years"] = [2017]
    elif defect == "late_offset":
        receipt["horizons"]["offset"] = "2017-01-01"
    elif defect == "late_preprocessing":
        receipt["horizons"]["preprocessing"] = "2018-01-01"
    else:
        receipt["prediction_keys_sha256"] = num.key_hash(keys[:1])
    with pytest.raises(CampaignIntegrityError):
        assert_raw_member(receipt, raw_year=2017, member_id="hgb7", expected_keys=keys)


def test_admitted_history_accessor_rejects_deliberately_late_read_before_open(tmp_path):
    # Reuse the B2 production control, not another permissive substitute reader.
    with pytest.raises(LabelHistoryError, match="does not precede"):
        LabelHistory(
            tmp_path / "not_opened.csv",
            "ab" * 32,
            purpose="training_fit",
            year_ceiling=2017,
            fold_outer_year=2017,
        )


def test_non_tier_raw_member_does_not_invent_an_offset():
    keys, receipt = member_receipt()
    receipt.update(feature_bundle="full", offset_applicability="not_applicable_non_tier")
    receipt["horizons"]["offset"] = None
    assert_raw_member(receipt, raw_year=2017, member_id="hgb7", expected_keys=keys)
    receipt["feature_bundle"] = "full_tier"
    with pytest.raises(CampaignIntegrityError):
        assert_raw_member(receipt, raw_year=2017, member_id="hgb7", expected_keys=keys)


def test_score_inventory_rejects_two_keys_for_one_realized_match():
    keys = (("2018", "row1"), ("2018", "row2"))
    with pytest.raises(CampaignIntegrityError, match="canonical realized match"):
        assert_forecasts(
            keys, [0.5, 0.5], expected_keys=keys, canonical_ids=["source:one", "source:one"]
        )


def test_numerical_orientation_defect_is_rejected():
    assert_swap([0.2, 0.8], [0.8, 0.2])
    with pytest.raises(CampaignIntegrityError):
        assert_swap([0.2, 0.8], [0.2, 0.8])


def test_annual_offset_rejects_horizon_after_earliest_training_row():
    assert_learned_horizon("2010-12-31", "2011-01-01", stage="offset")
    with pytest.raises(CampaignIntegrityError):
        assert_learned_horizon("2014-12-31", "2011-01-01", stage="offset")


def test_likelihood_arithmetic_and_current_copy_power():
    result = null_score([0.8, 0.6], [1, 0])
    assert result["log_likelihood_ratio"] == pytest.approx(math.log(1.6) + math.log(0.8))
    assert result["alarm_log_threshold"] == math.log(4800)
    assert null_score([0.5] * 1000, [0, 1] * 500)["alarm"] is False
    # Deliberately contaminated predictions: not a clean fitted-null result.
    assert null_score([0.999999, 0.000001] * 50, [1, 0] * 50)["alarm"] is True
    # Honest bad forecasts need not lie in a narrow band around log(2).
    bad = null_score([0.99] * 100, [1, 0] * 50)
    assert bad["log_loss"] > 2 and bad["alarm"] is False


def test_independent_point_reconstruction_and_corruption_controls():
    # Fixed tiny verification worlds, not additional statistical null repetitions.
    rng = np.random.default_rng(991)
    for best_of, final in ((3, 7), (5, 10)):
        match = simulate(rng, best_of, final)
        reconstruct(match)
        mirrored = mirror_participants(match)
        assert mirrored["winner"] == 1 - match["winner"]
        assert mirrored["counts"] == list(reversed(match["counts"]))
        assert mirror_participants(mirrored) == match
        for defect in ("score", "winner", "counts", "service", "truncation"):
            changed = copy.deepcopy(match)
            if defect == "score":
                changed["score"] = "6-0 6-0"
            elif defect == "winner":
                changed["winner"] ^= 1
            elif defect == "counts":
                changed["counts"][0]["SvGms"] += 1
            elif defect == "service":
                changed["trace"][0][0]["server"] ^= 1
            else:
                changed["trace"][-1][-1]["points"] = changed["trace"][-1][-1]["points"][:-1]
            with pytest.raises(ValueError):
                reconstruct(changed)
