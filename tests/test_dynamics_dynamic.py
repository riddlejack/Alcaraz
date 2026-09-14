"""Archive ``references/SR02_models/test_dynamic.py``, importing from the package."""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import math
import random
import unittest

import numpy as np
from scipy.optimize import minimize

from tennislab.dynamics.dynamic import (
    DynamicConfig,
    DynamicServeReturnFilter,
    HistoryObservation,
    MatchRule,
    PrequentialServeReturn,
    ServiceLine,
    SetRule,
    TargetMatch,
    UnadjustedRateBaseline,
    match_win_probability,
    observation_from_source_row,
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


def source_row(
    match_id: str,
    date: str,
    a: int,
    b: int,
    *,
    a_won_points: int = 42,
    a_points: int = 60,
    b_won_points: int = 38,
    b_points: int = 60,
    status: str = "completed",
    count_status: str = "usable",
    surface: str = "Hard",
) -> dict[str, str]:
    def counts(side: str, won: int, points: int) -> dict[str, str]:
        first_in = min(points, max(won, points // 2))
        first_won = min(won, first_in)
        second_won = won - first_won
        return {
            f"{side}_svpt": str(points),
            f"{side}_1stIn": str(first_in),
            f"{side}_1stWon": str(first_won),
            f"{side}_2ndWon": str(second_won),
            f"{side}_df": "0",
            f"{side}_ace": "0",
            f"{side}_bpSaved": "0",
            f"{side}_bpFaced": "0",
        }

    row = {
        "match_id": match_id,
        "match_date": date,
        "surface": surface,
        "tourney_id": "2020-TEST",
        "player_a": str(a),
        "player_b": str(b),
        "a_entity_id": str(a),
        "b_entity_id": str(b),
        "identity_tier": "primary",
        "status": status,
        "played": "true",
        "walkover": "false",
        "abandoned": "false",
        "count_block_status": count_status,
        "started_evidence": "official-draw.pdf" if status == "default" else "",
        # Deliberately present fields that are outside the history parser's label-free contract.
        "a_won": "true",
        "a_rank": "1",
        "b_rank": "999",
        "score": "6-0 6-0",
    }
    row.update(counts("a", a_won_points, a_points))
    row.update(counts("b", b_won_points, b_points))
    if count_status == "missing_all":
        for key in list(row):
            if key.startswith(("a_", "b_")) and key not in {
                "a_entity_id",
                "b_entity_id",
                "a_won",
                "a_rank",
                "b_rank",
            }:
                row[key] = ""
    return row


def observation(
    *args, statuses=("completed", "retired", "default"), **kwargs
) -> HistoryObservation:
    return observation_from_source_row(source_row(*args, **kwargs), history_statuses=statuses)


def engine(items: list[HistoryObservation]) -> PrequentialServeReturn:
    return PrequentialServeReturn(
        items,
        CONFIG,
        lag_days=2,
        baseline_half_life_days=180.0,
        baseline_prior_units=50.0,
        baseline_surface_prior_units=50.0,
    )


def target(date: str, a: int = 1, b: int = 2, rule: MatchRule | None = None) -> TargetMatch:
    return TargetMatch("target", dt.date.fromisoformat(date), "2020-TEST", "Hard", 3, a, b, rule)


STANDARD_BO3 = MatchRule(2, SetRule(6, 7), SetRule(6, 10))
STANDARD_BO5 = MatchRule(3, SetRule(6, 7), SetRule(6, 10))
ADVANTAGE_BO5 = MatchRule(3, SetRule(6, 7), SetRule(None, None))


class SourceBoundaryTests(unittest.TestCase):
    def test_outcome_rank_and_score_are_outside_history_signature(self) -> None:
        original = source_row("m1", "2020-01-01", 1, 2)
        perturbed = copy.deepcopy(original)
        perturbed.update(a_won="false", a_rank="999", b_rank="1", score="0-6 0-6")
        self.assertEqual(
            observation_from_source_row(original), observation_from_source_row(perturbed)
        )

    def test_missing_counts_are_retained_but_ineligible(self) -> None:
        item = observation("m1", "2020-01-01", 1, 2, count_status="missing_all")
        self.assertFalse(item.history_eligible)
        self.assertEqual(item.exclusion_reason, "counts_missing_all")
        self.assertIsNone(item.service_a)

    def test_invalid_side_is_retained_as_partial_without_imputation(self) -> None:
        row = source_row("m1", "2020-01-01", 1, 2)
        row.update(a_svpt="50", a_1stIn="30", a_1stWon="20", a_2ndWon="18", a_df="3")
        item = observation_from_source_row(row)
        self.assertTrue(item.history_eligible)
        self.assertIsNone(item.service_a)
        self.assertIsNotNone(item.service_b)
        self.assertIn(
            "a_counts_invalid:second-serve wins plus double faults", item.exclusion_reason
        )
        fitted = DynamicServeReturnFilter(CONFIG)
        fitted.apply_batch([item])
        invalid_side = fitted.point_prediction(1, 2, "Hard", "2020-TEST", dt.date(2020, 1, 2))
        valid_side = fitted.point_prediction(2, 1, "Hard", "2020-TEST", dt.date(2020, 1, 2))
        self.assertEqual(invalid_side["server_unseen"], 1)
        self.assertEqual(invalid_side["returner_unseen"], 1)
        self.assertEqual(valid_side["server_unseen"], 0)
        self.assertEqual(valid_side["returner_unseen"], 0)

    def test_started_history_primary_and_completed_sensitivity(self) -> None:
        retired = observation("r", "2020-01-01", 1, 2, status="retired")
        default = observation("d", "2020-01-02", 1, 2, status="default")
        completed_only = observation(
            "s", "2020-01-03", 1, 2, status="retired", statuses=("completed",)
        )
        self.assertTrue(retired.history_eligible)
        self.assertTrue(default.history_eligible)
        self.assertFalse(completed_only.history_eligible)
        no_evidence = source_row("x", "2020-01-04", 1, 2, status="default")
        no_evidence["started_evidence"] = ""
        self.assertFalse(observation_from_source_row(no_evidence).history_eligible)

    def test_target_type_has_only_prediction_allowlist(self) -> None:
        fields = {field.name for field in dataclasses.fields(TargetMatch)}
        self.assertEqual(
            fields,
            {
                "match_id",
                "match_date",
                "tourney_id",
                "surface",
                "best_of",
                "player_a",
                "player_b",
                "rule",
            },
        )
        with self.assertRaisesRegex(ValueError, "neutral"):
            TargetMatch("bad", dt.date(2020, 1, 1), "2020-TEST", "Hard", 3, 2, 1)


class ChronologyTests(unittest.TestCase):
    def test_two_day_boundary_and_future_mutation(self) -> None:
        base = [
            observation("eligible", "2020-01-08", 1, 2, a_won_points=48),
            observation("too_late", "2020-01-09", 1, 2, a_won_points=5),
            observation("future", "2020-01-12", 1, 2, a_won_points=60),
        ]
        changed = list(base)
        changed[1] = observation("too_late", "2020-01-09", 1, 2, a_won_points=60)
        changed[2] = observation("future", "2020-01-12", 1, 2, a_won_points=0)
        first = engine(base).forecast(target("2020-01-10"))
        second = engine(changed).forecast(target("2020-01-10"))
        self.assertEqual(first, second)
        self.assertEqual(first["eligible_through_date"], "2020-01-08")
        self.assertEqual(first["latest_dynamic_source_date"], "2020-01-08")

    def test_same_date_batch_and_input_order_are_deterministic(self) -> None:
        items = [
            observation("b", "2020-01-01", 1, 3, a_won_points=50),
            observation("a", "2020-01-01", 1, 2, a_won_points=45),
            observation("c", "2020-01-02", 2, 3, a_won_points=40),
        ]
        shuffled = list(items)
        random.Random(71101).shuffle(shuffled)
        self.assertEqual(
            engine(items).forecast(target("2020-01-04")),
            engine(shuffled).forecast(target("2020-01-04")),
        )

    def test_identity_relabeling_preserves_numeric_forecast(self) -> None:
        items = [
            observation("a", "2020-01-01", 1, 2, a_won_points=47, b_won_points=35),
            observation("b", "2020-01-02", 1, 3, a_won_points=44, b_won_points=37),
        ]
        relabeled = [
            dataclasses.replace(item, player_a=item.player_a + 100, player_b=item.player_b + 100)
            for item in items
        ]
        left = engine(items).forecast(target("2020-01-04", 1, 2))
        right = engine(relabeled).forecast(target("2020-01-04", 101, 102))
        for key in (
            "dynamic_p_a_serve",
            "dynamic_p_b_serve",
            "unadjusted_p_a_serve",
            "unadjusted_p_b_serve",
        ):
            self.assertEqual(left[key], right[key])


class EstimationTests(unittest.TestCase):
    def test_named_unadjusted_reference_uses_population_surface_prior(self) -> None:
        item = observation(
            "population",
            "2020-01-01",
            1,
            2,
            a_won_points=80,
            a_points=100,
            b_won_points=50,
            b_points=100,
        )
        forecast = engine([item]).forecast(target("2020-01-03", 3, 4))
        self.assertAlmostEqual(forecast["unadjusted_p_a_serve"], 0.65, places=14)
        self.assertEqual(forecast["unadjusted_a_audit"]["server_overall_denominator"], 0.0)
        self.assertEqual(forecast["unadjusted_a_audit"]["returner_overall_denominator"], 0.0)

    def test_unadjusted_surface_prior_retains_player_overall_ability(self) -> None:
        baseline = UnadjustedRateBaseline(180.0, 50.0, 50.0, 0.62)
        baseline.advance(dt.date(2020, 1, 5))
        baseline.add_observation(
            observation(
                "hard-player",
                "2020-01-01",
                1,
                2,
                a_won_points=90,
                a_points=100,
                b_won_points=60,
                b_points=100,
            )
        )
        baseline.add_observation(
            observation(
                "clay-population",
                "2020-01-02",
                3,
                4,
                a_won_points=60,
                a_points=100,
                b_won_points=60,
                b_points=100,
                surface="Clay",
            )
        )
        summary = baseline.rate("serve", 1, "Clay")
        self.assertGreater(summary["overall_rate"], summary["population_overall_rate"])
        self.assertGreater(summary["surface_prior"], summary["population_surface_rate"])
        self.assertEqual(summary["surface_denominator"], 0.0)

    def test_joint_batch_map_matches_independent_optimizer(self) -> None:
        items = [
            observation(
                "large",
                "2020-01-01",
                1,
                2,
                a_won_points=310,
                a_points=400,
                b_won_points=245,
                b_points=380,
            ),
            observation(
                "small",
                "2020-01-01",
                1,
                3,
                a_won_points=8,
                a_points=20,
                b_won_points=17,
                b_points=25,
            ),
        ]
        contests = []
        for item in items:
            assert item.service_a is not None and item.service_b is not None
            contests.extend(
                (
                    (item.player_a, item.player_b, item.service_a),
                    (item.player_b, item.player_a, item.service_b),
                )
            )

        def literal_terms(
            server: int, returner: int
        ) -> tuple[tuple[tuple[str, int, str], float], ...]:
            return (
                (("global", 0, ""), 1.0),
                (("surface_mean", 0, "Hard"), 1.0),
                (("tournament", 0, "2020-TEST"), 1.0),
                (("serve", server, ""), 1.0),
                (("return", returner, ""), -1.0),
                (("surface", server, "Hard"), 1.0),
                (("surface", returner, "Hard"), -1.0),
            )

        keys = sorted(
            {key for server, returner, _ in contests for key, _ in literal_terms(server, returner)}
        )
        index = {key: number for number, key in enumerate(keys)}
        matrix = np.zeros((len(contests), len(keys)))
        y = np.zeros(len(contests))
        n = np.zeros(len(contests))
        for row_number, (server, returner, line) in enumerate(contests):
            for key, sign in literal_terms(server, returner):
                matrix[row_number, index[key]] = sign
            y[row_number] = line.points_won
            n[row_number] = line.points_played
        means = np.asarray(
            [CONFIG.global_initial_mean_logit if key[0] == "global" else 0.0 for key in keys]
        )
        variance_by_kind = {
            "global": CONFIG.global_initial_sd**2,
            "surface_mean": CONFIG.surface_mean_initial_sd**2,
            "tournament": CONFIG.tournament_initial_sd**2,
            "serve": CONFIG.serve_initial_sd**2,
            "return": CONFIG.return_initial_sd**2,
            "surface": CONFIG.surface_initial_sd**2,
        }
        precision = np.asarray([1.0 / variance_by_kind[key[0]] for key in keys])

        def objective(values: np.ndarray) -> float:
            eta = matrix @ values
            difference = values - means
            return float(
                0.5 * np.dot(precision * difference, difference)
                + np.sum(n * np.logaddexp(0.0, eta) - y * eta)
            )

        def gradient(values: np.ndarray) -> np.ndarray:
            eta = matrix @ values
            probability = 1.0 / (1.0 + np.exp(-eta))
            return precision * (values - means) + matrix.T @ (n * probability - y)

        reference = minimize(
            objective,
            means,
            jac=gradient,
            method="L-BFGS-B",
            options={"ftol": 1e-15, "gtol": 1e-10, "maxiter": 2000, "maxls": 100},
        )
        self.assertTrue(reference.success, reference.message)
        fitted = DynamicServeReturnFilter(CONFIG)
        fitted.apply_batch(items)
        actual = np.asarray([fitted.states[key].mean for key in keys])
        self.assertLess(float(np.max(np.abs(actual - reference.x))), 2e-7)
        self.assertLess(fitted.last_solver_max_gradient, CONFIG.solver_gradient_tolerance)

    def test_unequal_point_counts_change_information_not_weight_equally(self) -> None:
        low = DynamicServeReturnFilter(CONFIG)
        high = DynamicServeReturnFilter(CONFIG)
        low.apply_batch(
            [
                observation(
                    "low",
                    "2020-01-01",
                    1,
                    2,
                    a_won_points=15,
                    a_points=20,
                    b_won_points=13,
                    b_points=20,
                )
            ]
        )
        high.apply_batch(
            [
                observation(
                    "high",
                    "2020-01-01",
                    1,
                    2,
                    a_won_points=150,
                    a_points=200,
                    b_won_points=130,
                    b_points=200,
                )
            ]
        )
        low_state = low.state_summary(1, "Hard", dt.date(2020, 1, 2))
        high_state = high.state_summary(1, "Hard", dt.date(2020, 1, 2))
        self.assertLess(high_state["serve_variance"], low_state["serve_variance"])
        self.assertGreater(abs(high_state["serve_mean"]), abs(low_state["serve_mean"]))
        self.assertEqual(high.points_used, 400)

    def test_synthetic_connected_schedule_recovers_separate_roles(self) -> None:
        true_serve = {1: 0.30, 2: 0.10, 3: -0.10, 4: -0.30}
        true_return = {1: 0.24, 2: 0.08, 3: -0.08, 4: -0.24}
        filt = DynamicServeReturnFilter(CONFIG)
        start = dt.date(2020, 1, 1)
        match_number = 0
        for block in range(20):
            items = []
            for a, b in ((1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4)):
                match_number += 1
                p_a = 1.0 / (1.0 + math.exp(-(0.5 + true_serve[a] - true_return[b])))
                p_b = 1.0 / (1.0 + math.exp(-(0.5 + true_serve[b] - true_return[a])))
                items.append(
                    HistoryObservation(
                        f"m{match_number:04d}",
                        start + dt.timedelta(days=block),
                        "2020-TEST",
                        "Hard",
                        a,
                        b,
                        ServiceLine(round(200 * p_a), 200),
                        ServiceLine(round(200 * p_b), 200),
                        True,
                        "",
                    )
                )
            filt.apply_batch(items)
        date = start + dt.timedelta(days=20)
        estimated_serve = [filt.state_summary(p, "Hard", date)["serve_mean"] for p in true_serve]
        estimated_return = [filt.state_summary(p, "Hard", date)["return_mean"] for p in true_return]
        self.assertGreater(
            float(np.corrcoef(list(true_serve.values()), estimated_serve)[0, 1]), 0.95
        )
        self.assertGreater(
            float(np.corrcoef(list(true_return.values()), estimated_return)[0, 1]), 0.95
        )

    def test_sparse_surface_state_is_shrunk_and_more_uncertain(self) -> None:
        sparse = DynamicServeReturnFilter(CONFIG)
        abundant = DynamicServeReturnFilter(CONFIG)
        sparse.apply_batch(
            [observation("s", "2020-01-01", 1, 2, a_won_points=19, a_points=20, surface="Clay")]
        )
        for day in range(10):
            abundant.apply_batch(
                [
                    observation(
                        f"a{day}",
                        f"2020-01-{day + 1:02d}",
                        1,
                        2,
                        a_won_points=95,
                        a_points=100,
                        surface="Clay",
                    )
                ]
            )
        sparse_state = sparse.state_summary(1, "Clay", dt.date(2020, 1, 11))
        abundant_state = abundant.state_summary(1, "Clay", dt.date(2020, 1, 11))
        raw_logit_gap = math.log(0.95 / 0.05) - CONFIG.global_initial_mean_logit
        self.assertLess(abs(sparse_state["surface_mean"]), abs(raw_logit_gap))
        self.assertGreater(sparse_state["surface_variance"], abundant_state["surface_variance"])
        self.assertGreater(sparse_state["surface_variance"], 0.0)

    def test_diagonal_projection_exposes_repeated_pair_overconfidence(self) -> None:
        static = dataclasses.replace(
            CONFIG,
            serve_process_sd_per_60_days=0.0,
            return_process_sd_per_60_days=0.0,
        )
        joint = DynamicServeReturnFilter(static)
        sequential = DynamicServeReturnFilter(static)
        all_at_once = []
        for number in range(12):
            item = observation(
                f"same{number:02d}",
                "2020-01-01",
                1,
                2,
                a_won_points=150,
                a_points=200,
                b_won_points=130,
                b_points=200,
            )
            all_at_once.append(item)
            sequential.apply_batch(
                [
                    dataclasses.replace(
                        item, match_date=dt.date(2020, 1, 1) + dt.timedelta(days=number)
                    )
                ]
            )
        joint.apply_batch(all_at_once)
        date = dt.date(2020, 1, 20)
        joint_variance = joint.state_summary(1, "Hard", date)["serve_variance"]
        sequential_variance = sequential.state_summary(1, "Hard", date)["serve_variance"]
        self.assertLess(sequential_variance, 0.2 * joint_variance)

    def test_process_noise_reduces_overshrinkage_after_abrupt_change(self) -> None:
        nearly_roles_only = dataclasses.replace(
            CONFIG,
            global_initial_sd=0.005,
            surface_mean_initial_sd=0.005,
            tournament_initial_sd=0.005,
            surface_initial_sd=0.005,
            serve_process_sd_per_60_days=0.0,
            return_process_sd_per_60_days=0.0,
        )
        adaptive = dataclasses.replace(
            nearly_roles_only,
            serve_process_sd_per_60_days=0.12,
            return_process_sd_per_60_days=0.12,
        )
        static_filter = DynamicServeReturnFilter(nearly_roles_only)
        adaptive_filter = DynamicServeReturnFilter(adaptive)
        old = [
            observation(
                "old",
                "2020-01-01",
                1,
                2,
                a_won_points=110,
                a_points=200,
                b_won_points=110,
                b_points=200,
            )
        ]
        new = [
            observation(
                "new",
                "2021-01-01",
                1,
                2,
                a_won_points=170,
                a_points=200,
                b_won_points=110,
                b_points=200,
            )
        ]
        for fitted in (static_filter, adaptive_filter):
            fitted.apply_batch(old)
            fitted.apply_batch(new)
        date = dt.date(2021, 1, 2)
        static_p = static_filter.point_prediction(1, 2, "Hard", "2020-TEST", date)["probability"]
        adaptive_p = adaptive_filter.point_prediction(1, 2, "Hard", "2020-TEST", date)[
            "probability"
        ]
        self.assertLess(abs(adaptive_p - 0.85), abs(static_p - 0.85))

    def test_two_logit_covariance_keeps_shared_diagonal_states(self) -> None:
        fitted = DynamicServeReturnFilter(CONFIG)
        date = dt.date(2020, 1, 1)
        covariance = fitted.point_logit_covariance(1, 2, 2, 1, "Hard", "2020-TEST", date)
        expected = (
            CONFIG.global_initial_sd**2
            + CONFIG.surface_mean_initial_sd**2
            + CONFIG.tournament_initial_sd**2
            - 2.0 * CONFIG.surface_initial_sd**2
        )
        self.assertAlmostEqual(covariance, expected, places=15)


class ScoringTests(unittest.TestCase):
    def test_equal_players_are_exactly_half_under_supported_rules(self) -> None:
        for rule in (
            STANDARD_BO3,
            STANDARD_BO5,
            ADVANTAGE_BO5,
            MatchRule(3, SetRule(6, 7), SetRule(12, 7)),
        ):
            self.assertAlmostEqual(match_win_probability(0.62, 0.62, rule), 0.5, places=14)

    def test_swap_complement_and_best_of_five_amplification(self) -> None:
        bo3 = match_win_probability(0.65, 0.60, STANDARD_BO3)
        bo5 = match_win_probability(0.65, 0.60, STANDARD_BO5)
        swapped = match_win_probability(0.60, 0.65, STANDARD_BO3)
        self.assertAlmostEqual(bo3 + swapped, 1.0, places=14)
        self.assertGreater(bo3, 0.5)
        self.assertGreater(bo5, bo3)

    def test_explicit_rule_controls_match_probability_emission(self) -> None:
        no_rule = engine([]).forecast(target("2020-01-01"))
        with_rule = engine([]).forecast(target("2020-01-01", rule=STANDARD_BO3))
        self.assertIsNone(no_rule["dynamic_match_probability_a"])
        self.assertEqual(no_rule["match_rule_status"], "missing_explicit_rule")
        self.assertAlmostEqual(with_rule["dynamic_match_probability_a"], 0.5, places=14)


if __name__ == "__main__":
    unittest.main()
