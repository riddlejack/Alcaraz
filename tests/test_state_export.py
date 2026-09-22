"""Tests for the bounded native latent-state pair export."""

from __future__ import annotations

import copy
import datetime as dt
import math

import pytest

from tennislab.dynamics.dynamic import (
    DynamicConfig,
    HistoryObservation,
    PrequentialServeReturn,
    ServiceLine,
    TargetMatch,
)
from tennislab.features.state_export import (
    STATE_GEOMETRY_FEATURES,
    StateExportError,
    export_pair_geometry,
    export_selected_geometry,
    pair_geometry,
)

CONFIG = DynamicConfig(
    global_initial_mean_logit=0.5,
    global_initial_sd=0.12,
    surface_mean_initial_sd=0.08,
    tournament_initial_sd=0.06,
    serve_initial_sd=0.2,
    return_initial_sd=0.2,
    surface_initial_sd=0.08,
    serve_process_sd_per_60_days=0.04,
    return_process_sd_per_60_days=0.04,
    surface_process_sd_per_60_days=0.0,
)
HASH_A = "a" * 64
HASH_B = "b" * 64


def observation(
    match_id: str,
    match_date: str,
    *,
    a_won: int,
    b_won: int,
    points: int = 60,
) -> HistoryObservation:
    return HistoryObservation(
        match_id=match_id,
        match_date=dt.date.fromisoformat(match_date),
        tourney_id="2020-TEST",
        surface="Hard",
        player_a=1,
        player_b=2,
        service_a=ServiceLine(a_won, points),
        service_b=ServiceLine(b_won, points),
        history_eligible=True,
        exclusion_reason="",
    )


def target(match_date: str = "2020-01-10") -> TargetMatch:
    return TargetMatch(
        match_id="target",
        match_date=dt.date.fromisoformat(match_date),
        tourney_id="2020-TEST",
        surface="Hard",
        best_of=3,
        player_a=1,
        player_b=2,
    )


def engine(items: list[HistoryObservation]) -> PrequentialServeReturn:
    return PrequentialServeReturn(
        items,
        CONFIG,
        lag_days=2,
        baseline_half_life_days=180.0,
        baseline_prior_units=50.0,
        baseline_surface_prior_units=50.0,
    )


class GateRemovedReplay(PrequentialServeReturn):
    """Planted negative control: admit D-1 history and misdeclare the cutoff."""

    def _advance(self, target_date: dt.date) -> dt.date:
        self.latest_target_date = target_date
        self.baseline.advance(target_date)
        while (
            self.cursor < len(self.observations)
            and self.observations[self.cursor].match_date <= target_date
        ):
            source_date = self.observations[self.cursor].match_date
            end = self.cursor + 1
            while end < len(self.observations) and self.observations[end].match_date == source_date:
                end += 1
            batch = self.observations[self.cursor : end]
            self.dynamic.apply_batch(batch)
            for item in batch:
                self.baseline.add_observation(item)
            self.cursor = end
        return target_date


def leaky_engine(items: list[HistoryObservation]) -> GateRemovedReplay:
    return GateRemovedReplay(
        items,
        CONFIG,
        lag_days=2,
        baseline_half_life_days=180.0,
        baseline_prior_units=50.0,
        baseline_surface_prior_units=50.0,
    )


def test_native_export_reconstructs_filter_calculation_and_incumbent() -> None:
    fitted = engine(
        [
            observation("m1", "2020-01-01", a_won=49, b_won=35),
            observation("m2", "2020-01-05", a_won=44, b_won=40),
        ]
    )
    match = target()
    native = fitted.forecast(match)
    unchanged = copy.deepcopy(native)
    exported = export_pair_geometry(native, state_ancestry="main")

    point_a = fitted.dynamic.point_prediction(1, 2, "Hard", "2020-TEST", match.match_date)
    point_b = fitted.dynamic.point_prediction(2, 1, "Hard", "2020-TEST", match.match_date)
    covariance = fitted.dynamic.point_logit_covariance(
        1, 2, 2, 1, "Hard", "2020-TEST", match.match_date
    )
    eta_a = float(point_a["logit"])
    eta_b = float(point_b["logit"])
    var_a = float(point_a["latent_variance_diagonal"])
    var_b = float(point_b["latent_variance_diagonal"])
    assert exported["serve_logit_diff"] == pytest.approx(eta_a - eta_b)
    assert exported["serve_logit_variance_asymmetry"] == pytest.approx(var_a - var_b)
    assert exported["serve_logit_sum"] == pytest.approx(eta_a + eta_b)
    assert exported["serve_logit_variance_diff"] == pytest.approx(var_a + var_b - 2 * covariance)
    assert exported["serve_logit_variance_sum"] == pytest.approx(var_a + var_b + 2 * covariance)

    reconstructed_eta_a = (
        float(exported["serve_logit_sum"]) + float(exported["serve_logit_diff"])
    ) / 2.0
    reconstructed_eta_b = (
        float(exported["serve_logit_sum"]) - float(exported["serve_logit_diff"])
    ) / 2.0
    assert 1.0 / (1.0 + math.exp(-reconstructed_eta_a)) == pytest.approx(
        native["dynamic_p_a_serve"]
    )
    assert 1.0 / (1.0 + math.exp(-reconstructed_eta_b)) == pytest.approx(
        native["dynamic_p_b_serve"]
    )
    assert native == unchanged
    assert exported["eligible_through_date"] == "2020-01-08"
    assert exported["latest_state_source_date"] == "2020-01-05"


def test_fixed_swap_semantics_and_feature_order() -> None:
    original = pair_geometry(0.7, 0.6, 0.10, 0.04, 0.02)
    swapped = pair_geometry(0.6, 0.7, 0.04, 0.10, 0.02)
    assert tuple(original) == (*STATE_GEOMETRY_FEATURES, "state_geometry_missing")
    assert swapped["serve_logit_diff"] == pytest.approx(-float(original["serve_logit_diff"]))
    assert swapped["serve_logit_variance_asymmetry"] == pytest.approx(
        -float(original["serve_logit_variance_asymmetry"])
    )
    for field in (
        "serve_logit_sum",
        "serve_logit_variance_diff",
        "serve_logit_variance_sum",
    ):
        assert swapped[field] == pytest.approx(original[field])


def test_future_mutation_invariance_and_planted_gate_removal_control() -> None:
    fixed = observation("eligible", "2020-01-08", a_won=48, b_won=34)
    future_low = observation("d-minus-one", "2020-01-09", a_won=5, b_won=55)
    future_high = observation("d-minus-one", "2020-01-09", a_won=55, b_won=5)

    protected_low = export_pair_geometry(
        engine([fixed, future_low]).forecast(target()), state_ancestry="main"
    )
    protected_high = export_pair_geometry(
        engine([fixed, future_high]).forecast(target()), state_ancestry="main"
    )
    assert protected_low == protected_high

    leaked_low = export_pair_geometry(
        leaky_engine([fixed, future_low]).forecast(target()), state_ancestry="main"
    )
    leaked_high = export_pair_geometry(
        leaky_engine([fixed, future_high]).forecast(target()), state_ancestry="main"
    )
    assert leaked_low["serve_logit_diff"] != pytest.approx(leaked_high["serve_logit_diff"])


def test_missing_is_distinct_from_zero_and_unseen_prior_is_available() -> None:
    missing = pair_geometry(0.6, 0.6, "", "", "")
    assert missing["state_geometry_missing"] == 1
    assert all(missing[field] is None for field in STATE_GEOMETRY_FEATURES)

    measured_zero = pair_geometry(0.6, 0.6, 0.0, 0.0, 0.0)
    assert measured_zero["state_geometry_missing"] == 0
    assert measured_zero["serve_logit_variance_diff"] == 0.0
    assert measured_zero["serve_logit_variance_sum"] == 0.0

    unseen = export_pair_geometry(engine([]).forecast(target()), state_ancestry="main")
    assert unseen["state_geometry_missing"] == 0
    assert unseen["latest_state_source_date"] is None


def test_covariance_finiteness_psd_and_chronology_fail_closed() -> None:
    with pytest.raises(StateExportError, match="positive semidefinite"):
        pair_geometry(0.6, 0.6, 0.01, 0.01, 0.02)
    with pytest.raises(StateExportError, match="positive semidefinite"):
        pair_geometry(0.6, 0.6, 1e-10, 4e-10, 2.1e-10)
    with pytest.raises(StateExportError, match="finite"):
        pair_geometry(0.6, 0.6, 0.01, 0.01, math.inf)
    with pytest.raises(StateExportError, match="finite"):
        pair_geometry(math.nan, 0.6, "", "", "")

    native = engine([]).forecast(target())
    native["latest_dynamic_source_date"] = "2020-01-09"
    with pytest.raises(StateExportError, match="exceeds eligible_through_date"):
        export_pair_geometry(native, state_ancestry="main")


def test_label_barrier_and_ancestry_fail_closed() -> None:
    native = engine([]).forecast(target())
    native["a_won"] = True
    with pytest.raises(StateExportError, match="outcome label"):
        export_pair_geometry(native, state_ancestry="main")
    native.pop("a_won")
    with pytest.raises(StateExportError, match="state_ancestry"):
        export_pair_geometry(native, state_ancestry="other")  # type: ignore[arg-type]


def test_saved_selected_row_adapter_binds_cutoff_hashes_and_unknown_latest_source() -> None:
    row = {
        "match_date": "2011-01-02",
        "dynamic_p_a_serve": "0.65599642800187963",
        "dynamic_p_b_serve": "0.67345774424462856",
        "dynamic_a_logit_variance": "0.0064514382215697403",
        "dynamic_b_logit_variance": "0.0064963319962874954",
        "dynamic_a_b_logit_covariance": "0.00058287601537409736",
    }
    exported = export_selected_geometry(
        row,
        state_ancestry="tier",
        source_sha256=HASH_A,
        replay_config_sha256=HASH_B,
    )
    direct = pair_geometry(
        row["dynamic_p_a_serve"],
        row["dynamic_p_b_serve"],
        row["dynamic_a_logit_variance"],
        row["dynamic_b_logit_variance"],
        row["dynamic_a_b_logit_covariance"],
    )
    assert {key: exported[key] for key in direct} == direct
    assert exported["eligible_through_date"] == "2010-12-31"
    assert exported["cutoff_convention"] == "match_date_minus_2_calendar_days_retrospective"
    assert exported["latest_state_source_date"] is None
    assert exported["state_ancestry"] == "tier"
    assert exported["source_sha256"] == HASH_A
    assert exported["replay_config_sha256"] == HASH_B


def test_saved_selected_row_missing_state_emits_no_partial_geometry() -> None:
    exported = export_selected_geometry(
        {
            "match_date": "2011-01-02",
            "dynamic_p_a_serve": "0.65",
            "dynamic_p_b_serve": "0.63",
            "dynamic_a_logit_variance": "",
            "dynamic_b_logit_variance": "",
            "dynamic_a_b_logit_covariance": "",
        },
        state_ancestry="main",
        source_sha256=HASH_A,
        replay_config_sha256=HASH_B,
    )
    assert exported["state_geometry_missing"] == 1
    assert all(exported[field] is None for field in STATE_GEOMETRY_FEATURES)
