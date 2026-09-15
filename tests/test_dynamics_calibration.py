"""Archive ``references/SR03_calibration/test_calibration.py``, importing from the package.

Adaptations: the fit-failure tests expect :class:`CalibrationError` (a ``ChainError``)
where the archive raised ``RuntimeError``; the corrupted-binding test builds a synthetic
workspace instead of relying on the archive's own files; a stage-level test covers the
``score_years_max`` switch of ``calibrate``.
"""

import copy
import hashlib
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tennislab.chain.common import canonical_hash
from tennislab.config import reset_workspace_cache
from tennislab.dynamics import calibrate, calibration
from tennislab.dynamics.calibration import CalibrationError, CalibrationWindow

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EDGES = [i / 10 for i in range(11)]


def synthetic_rows():
    rows = []
    outcomes = {}
    probabilities = (0.24, 0.34, 0.44, 0.56, 0.66, 0.76)
    for year in range(2011, 2016):
        dates = [f"{year}-03-{index + 1:02d}" for index in range(4)] + [
            f"{year}-12-30",
            f"{year}-12-31",
        ]
        for index, (date, probability) in enumerate(zip(dates, probabilities, strict=True)):
            match_id = f"{year}-S/{index}"
            tier = "provisional" if year >= 2014 and index == 5 else "primary"
            row = {
                "match_id": match_id,
                "match_date": date,
                "date": calibration.parse_date(date),
                "source_season": str(year),
                "source_key": match_id,
                "tourney_id": f"{year}-S{index // 2}",
                "surface": "Hard" if index % 2 else "Clay",
                "best_of": "3",
                "player_a": str(1000 + index),
                "player_b": str(2000 + index),
                "identity_tier": tier,
                "played": True,
                "completed": index != 0,
                "source_agreement": index != 1,
                "annual_target_eligible": year >= 2012,
                "raw_dynamic": probability,
                "raw_unadjusted": 0.5 + 0.8 * (probability - 0.5),
                "raw_simple_unadjusted": 0.5 + 0.6 * (probability - 0.5),
                "pinnacle_raw_normalized": 0.5 + 0.9 * (probability - 0.5),
            }
            rows.append(row)
            outcomes[match_id] = int(index >= 3 if year % 2 else index >= 2)
    return rows, outcomes


class ProtocolTests(unittest.TestCase):
    def test_campaign_run_redacts_both_prebarrier_fit_write_sinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")
            config = {
                "experiment_id": "E-SYNTHETIC",
                "calibration": {
                    "outer_years": [2017],
                    "fit_disclosure_policy": calibrate.CAMPAIGN_FIT_DISCLOSURE_POLICY,
                },
                "source": {
                    "point_manifest_sha256": "1" * 64,
                    "selected_matches_sha256": "2" * 64,
                    "panel_sha256": "3" * 64,
                    "design_sha256": "4" * 64,
                },
            }
            fit_records = [
                {
                    "outer_year": 2017,
                    "family": family,
                    "training_max_date": "2016-12-30",
                    "status": "complete",
                    "fit": {
                        "market_slope": 1.0,
                        "residual_coefficient": 0.0,
                        "penalty": None,
                        "n": 12,
                        "objective": 0.6 + index / 100,
                    },
                }
                for index, (family, _) in enumerate(calibration.FAMILIES)
            ]

            def fake_fit_and_predict(*args, event_sink=None, **kwargs):
                for record in fit_records:
                    event_sink(record)
                return [], fit_records, []

            def fake_write_csv(path, rows, fields):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(",".join(fields) + "\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {"TENNISLAB_WORKSPACE": str(root)}):
                reset_workspace_cache()
                try:
                    with (
                        mock.patch.object(
                            calibrate,
                            "_load",
                            return_value=(
                                config,
                                calibration.SR03_WINDOW,
                                {"selected_matches_rows": 0, "declared_binding": {}},
                            ),
                        ),
                        mock.patch.object(
                            calibration,
                            "load_dataset",
                            return_value=types.SimpleNamespace(rows=[], refused_without_rule=[]),
                        ) as load_dataset,
                        mock.patch.object(
                            calibration, "panel_outcomes_for_fold", return_value=object()
                        ),
                        mock.patch.object(
                            calibration, "fit_and_predict", side_effect=fake_fit_and_predict
                        ),
                        mock.patch.object(calibrate, "write_csv", side_effect=fake_write_csv),
                        mock.patch.object(
                            calibrate,
                            "_source_hashes",
                            return_value={
                                "point_manifest_sha256": "1" * 64,
                                "selected_matches_sha256": "2" * 64,
                                "panel_sha256": "3" * 64,
                                "rule_mapping_sha256": "5" * 64,
                            },
                        ),
                        mock.patch.object(
                            calibrate,
                            "code_receipt",
                            return_value={"module": "synthetic", "sha256": "6" * 64},
                        ),
                    ):
                        calibrate.run(config_path, root / "out")
                        load_dataset.assert_called_once_with(
                            config,
                            window=calibration.SR03_WINDOW,
                            labels=True,
                            exclude_without_rule=True,
                            prices=False,
                        )
                finally:
                    reset_workspace_cache()
            fits = json.loads((root / "out/fits.json").read_text(encoding="utf-8"))
            events = [
                json.loads(line)
                for line in (root / "out/fit_events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            for sink_records in (fits, events):
                self.assertEqual(len(sink_records), len(calibration.FAMILIES))
                self.assertTrue(all("objective" not in record["fit"] for record in sink_records))
                self.assertTrue(
                    all("full_fit_record_commitment_sha256" in record for record in sink_records)
                )

    def test_campaign_fit_disclosure_commits_without_prebarrier_objective(self):
        original = {
            "outer_year": 2017,
            "family": "dynamic",
            "training_max_date": "2016-12-30",
            "status": "complete",
            "fit": {
                "market_slope": 0.9,
                "residual_coefficient": 0.0,
                "penalty": None,
                "n": 12,
                "objective": 0.6123,
                "projected_gradient": 1e-9,
                "iterations": 4,
                "status": "complete",
            },
        }
        serialized = calibrate.prebarrier_fit_record(
            original, policy=calibrate.CAMPAIGN_FIT_DISCLOSURE_POLICY
        )
        self.assertNotIn("objective", serialized["fit"])
        self.assertEqual(serialized["fit"]["market_slope"], 0.9)
        self.assertEqual(serialized["training_max_date"], "2016-12-30")
        self.assertEqual(serialized["full_fit_record_commitment_sha256"], canonical_hash(original))
        self.assertIn("objective", original["fit"])
        disclosed = calibrate.disclose_postbarrier_fit_objectives([serialized], [original])
        self.assertEqual(disclosed[0]["objective"], 0.6123)
        self.assertTrue(disclosed[0]["commitment_verified"])

    def test_campaign_evaluate_refuses_without_completed_barrier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")
            config = {
                "calibration": {"fit_disclosure_policy": calibrate.CAMPAIGN_FIT_DISCLOSURE_POLICY}
            }
            with mock.patch.dict(os.environ, {"TENNISLAB_WORKSPACE": str(root)}):
                reset_workspace_cache()
                try:
                    with mock.patch.object(
                        calibrate,
                        "_load",
                        return_value=(config, calibration.SR03_WINDOW, {}),
                    ):
                        with self.assertRaisesRegex(ValueError, "requires --barrier-completion"):
                            calibrate.evaluate(config_path, root / "calibration", root / "output")
                finally:
                    reset_workspace_cache()

    def test_campaign_evaluate_reconciles_both_disclosure_sinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = {
                "outer_year": 2017,
                "family": "dynamic",
                "fit": {"market_slope": 1.0},
                "fit_objective_disclosure": "deferred_to_post_barrier",
                "full_fit_record_commitment_sha256": "1" * 64,
            }
            (root / "fits.json").write_text(json.dumps([record]) + "\n", encoding="utf-8")
            (root / "fit_events.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            manifest = {
                "fits": 1,
                "artifacts": {
                    "fits.json": hashlib.sha256((root / "fits.json").read_bytes()).hexdigest(),
                    "fit_events.jsonl": hashlib.sha256(
                        (root / "fit_events.jsonl").read_bytes()
                    ).hexdigest(),
                },
            }
            self.assertEqual(calibrate._campaign_disclosure_sinks(root, manifest), [record])
            changed = {**record, "full_fit_record_commitment_sha256": "2" * 64}
            (root / "fit_events.jsonl").write_text(json.dumps(changed) + "\n", encoding="utf-8")
            manifest["artifacts"]["fit_events.jsonl"] = hashlib.sha256(
                (root / "fit_events.jsonl").read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(ValueError, "sink commitments differ"):
                calibrate._campaign_disclosure_sinks(root, manifest)

    def test_campaign_fit_disclosure_rejects_recomputed_drift(self):
        original = {
            "outer_year": 2017,
            "family": "dynamic",
            "status": "complete",
            "fit": {"objective": 0.6},
        }
        serialized = calibrate.prebarrier_fit_record(
            original, policy=calibrate.CAMPAIGN_FIT_DISCLOSURE_POLICY
        )
        mutated = copy.deepcopy(original)
        mutated["fit"]["objective"] = 0.61
        with self.assertRaisesRegex(ValueError, "differs from its prebarrier commitment"):
            calibrate.disclose_postbarrier_fit_objectives([serialized], [mutated])

    def test_legacy_fit_disclosure_is_exact_and_invalid_policy_fails(self):
        record = {"status": "complete", "fit": {"objective": 0.5}}
        self.assertEqual(
            calibrate.prebarrier_fit_record(record, policy=calibrate.LEGACY_FIT_DISCLOSURE_POLICY),
            record,
        )
        self.assertEqual(
            calibrate.fit_disclosure_policy({"calibration": {}}),
            calibrate.LEGACY_FIT_DISCLOSURE_POLICY,
        )
        with self.assertRaisesRegex(ValueError, "unsupported calibration"):
            calibrate.fit_disclosure_policy(
                {"calibration": {"fit_disclosure_policy": "write_then_delete"}}
            )

    def test_candidate_config_cannot_run(self):
        config = json.loads((FIXTURES / "sr03_config.candidate.json").read_text())
        with self.assertRaisesRegex(ValueError, "frozen configuration"):
            calibration.validate_config(config, require_frozen=True)

    def test_three_year_cutoff_excludes_preceding_december_31(self):
        rows, outcomes = synthetic_rows()
        selected = calibration.training_rows(rows, 2014)
        self.assertEqual({row["date"].year for row in selected}, {2011, 2012, 2013})
        self.assertEqual(selected[-1]["match_date"], "2013-12-30")
        self.assertNotIn("2013-S/5", {row["match_id"] for row in selected})

    def test_future_labels_cannot_change_earlier_fit_or_prediction(self):
        rows, outcomes = synthetic_rows()
        first_predictions, first_fits, _ = calibration.fit_and_predict(
            rows, calibration.fold_outcomes_from_mapping(outcomes), [2014, 2015]
        )
        mutated = dict(outcomes)
        for row in rows:
            if row["date"].year >= 2014:
                mutated[row["match_id"]] = 1 - mutated[row["match_id"]]
        second_predictions, second_fits, _ = calibration.fit_and_predict(
            rows, calibration.fold_outcomes_from_mapping(mutated), [2014, 2015]
        )
        first_2014 = [row for row in first_predictions if row["calibration_year"] == 2014]
        second_2014 = [row for row in second_predictions if row["calibration_year"] == 2014]
        self.assertEqual(first_2014, second_2014)
        self.assertEqual(
            [row for row in first_fits if row["outer_year"] == 2014],
            [row for row in second_fits if row["outer_year"] == 2014],
        )
        self.assertNotEqual(
            [row for row in first_fits if row["outer_year"] == 2015],
            [row for row in second_fits if row["outer_year"] == 2015],
        )
        self.assertTrue(
            all("a_won" not in row and "completed" not in row for row in first_predictions)
        )

    def test_orientation_swap_complements_forecasts_and_preserves_slopes(self):
        rows, outcomes = synthetic_rows()
        predictions, fits, _ = calibration.fit_and_predict(
            rows, calibration.fold_outcomes_from_mapping(outcomes), [2014]
        )
        swapped = copy.deepcopy(rows)
        swapped_outcomes = {}
        for row in swapped:
            row["player_a"], row["player_b"] = row["player_b"], row["player_a"]
            for family, _ in calibration.FAMILIES:
                row[f"raw_{family}"] = 1 - row[f"raw_{family}"]
            row["pinnacle_raw_normalized"] = 1 - row["pinnacle_raw_normalized"]
            swapped_outcomes[row["match_id"]] = 1 - outcomes[row["match_id"]]
        swapped_predictions, swapped_fits, _ = calibration.fit_and_predict(
            swapped, calibration.fold_outcomes_from_mapping(swapped_outcomes), [2014]
        )
        for left, right in zip(fits, swapped_fits, strict=True):
            self.assertAlmostEqual(
                left["fit"]["market_slope"], right["fit"]["market_slope"], places=10
            )
        by_id = {row["match_id"]: row for row in swapped_predictions}
        for row in predictions:
            other = by_id[row["match_id"]]
            for family, _ in calibration.FAMILIES:
                self.assertAlmostEqual(
                    row[f"calibrated_{family}"] + other[f"calibrated_{family}"], 1.0, places=12
                )

    def test_fit_contract_is_one_nonnegative_unpenalized_slope(self):
        rows, outcomes = synthetic_rows()
        _, fits, membership = calibration.fit_and_predict(
            rows, calibration.fold_outcomes_from_mapping(outcomes), [2014]
        )
        self.assertEqual(len(fits), 3)
        self.assertEqual(len(membership), len(calibration.training_rows(rows, 2014)))
        for record in fits:
            fit = record["fit"]
            self.assertIsNone(fit["penalty"])
            self.assertEqual(fit["residual_coefficient"], 0.0)
            self.assertGreaterEqual(fit["market_slope"], 0.0)
            self.assertEqual(record["training_max_date"], "2013-12-30")

    def test_constant_half_probability_uses_unit_slope_convention(self):
        rows, outcomes = synthetic_rows()
        for row in rows:
            for family, _ in calibration.FAMILIES:
                row[f"raw_{family}"] = 0.5
        predictions, fits, _ = calibration.fit_and_predict(
            rows, calibration.fold_outcomes_from_mapping(outcomes), [2014]
        )
        self.assertTrue(all(record["fit"]["market_slope"] == 1.0 for record in fits))
        self.assertTrue(
            all(
                prediction[f"calibrated_{family}"] == 0.5
                for prediction in predictions
                for family, _ in calibration.FAMILIES
            )
        )

    def test_window_from_year_plan_reproduces_sr03_for_the_2024_plan(self):
        plan = {
            "panel_end_year": 2024,
            "feature_end_year": 2024,
            "target_years": list(range(2017, 2025)),
            "calibration_years_back": 3,
            "history_floor_year": 2011,
            "training_window_years": 5,
        }
        self.assertEqual(
            CalibrationWindow.from_config({"year_plan": plan}), calibration.SR03_WINDOW
        )
        self.assertEqual(CalibrationWindow.from_config({}), calibration.SR03_WINDOW)
        with self.assertRaises(CalibrationError):
            CalibrationWindow(
                outer_years=(2010,),
                training_calendar_years=3,
                date_year_min=2011,
                date_year_max=2024,
                source_season_min=2000,
                source_season_max=2024,
                annual_eligible_floor_year=2012,
            )


class EvaluationTests(unittest.TestCase):
    def test_all_models_use_paired_cohorts_and_fixed_bins(self):
        rows, outcomes = synthetic_rows()
        predictions, _, _ = calibration.fit_and_predict(
            rows, calibration.fold_outcomes_from_mapping(outcomes), [2014]
        )
        metrics, bins, comparisons, counts = calibration.evaluate(
            rows, outcomes, predictions, edges=EDGES, bootstrap_seed=71101, bootstrap_repetitions=20
        )
        groups = {}
        for row in metrics:
            groups.setdefault((row["scope"], row["cohort"], row["year"]), []).append(row)
        for (scope, _, _), items in groups.items():
            expected_models = 7 if scope == "priced_primary_2014_2024" else 6
            self.assertEqual(len(items), expected_models)
            self.assertEqual(len({item["n"] for item in items}), 1)
        self.assertEqual(len(bins), 60)
        self.assertEqual(
            sum(item["n"] for item in bins if item["model"] == "calibrated_dynamic"), 5
        )
        self.assertEqual(len(comparisons), 4)
        self.assertEqual(counts["prediction_rows"], len(predictions))
        self.assertEqual(counts["primary_missing_pinnacle_rows"], 0)
        primary = comparisons["sports_2014_2024/primary/calibrated_dynamic_minus_raw_dynamic"]
        self.assertEqual(primary["n"], 5)
        self.assertEqual(primary["bootstrap_repetitions"], 20)

    def test_target_outcome_mutation_changes_scores_not_predictions(self):
        rows, outcomes = synthetic_rows()
        predictions, _, _ = calibration.fit_and_predict(
            rows, calibration.fold_outcomes_from_mapping(outcomes), [2014]
        )
        frozen_predictions = copy.deepcopy(predictions)
        first, _, _, _ = calibration.evaluate(
            rows, outcomes, predictions, edges=EDGES, bootstrap_seed=1, bootstrap_repetitions=10
        )
        mutated = dict(outcomes)
        for prediction in predictions:
            mutated[prediction["match_id"]] = 1 - mutated[prediction["match_id"]]
        second, _, _, _ = calibration.evaluate(
            rows, mutated, predictions, edges=EDGES, bootstrap_seed=1, bootstrap_repetitions=10
        )
        self.assertEqual(predictions, frozen_predictions)
        self.assertNotEqual(first, second)

    def test_the_calibration_stage_scores_nothing_and_defers_every_outer_year(self):
        # RB14: the stage writes fits and predictions only; the receipt names the outer
        # years the post-barrier component stage will score and keeps the historical
        # switch value for a frozen config that still carries one.
        boundary = calibrate.scoring_boundary(
            {"calibration": {"score_years_max": 2014}}, [2015, 2014]
        )
        self.assertEqual(boundary["outer_years_scored"], [])
        self.assertEqual(boundary["outer_years_deferred_to_sr03_component_stage"], [2014, 2015])
        self.assertEqual(boundary["historical_score_years_max"], 2014)
        self.assertIsNone(
            calibrate.scoring_boundary({"calibration": {}}, [2014])["historical_score_years_max"]
        )

    def test_unresolved_outcomes_are_predicted_but_not_scored(self):
        rows, outcomes = synthetic_rows()
        predictions, _, _ = calibration.fit_and_predict(
            rows, calibration.fold_outcomes_from_mapping(outcomes), [2014]
        )
        partial = {k: v for k, v in outcomes.items() if not k.startswith("2014-S/0")}
        metrics, _, _, counts = calibration.evaluate(
            rows, partial, predictions, edges=EDGES, bootstrap_seed=1, bootstrap_repetitions=10
        )
        self.assertEqual(counts["unresolved_outcome_rows"], 1)
        self.assertEqual(counts["resolved_outcome_rows"], len(predictions) - 1)
        with self.assertRaisesRegex(CalibrationError, "no prediction has a resolved outcome"):
            calibration.evaluate(
                rows, {}, predictions, edges=EDGES, bootstrap_seed=1, bootstrap_repetitions=10
            )

    def test_fold_accessor_refuses_a_row_beyond_its_horizon(self):
        rows, outcomes = synthetic_rows()
        lookup = calibration.fold_outcomes_from_mapping(outcomes)
        training = calibration.training_rows(rows, 2014)
        self.assertEqual(
            set(lookup(training, 2014, calibration.training_cutoff(2014))),
            {row["match_id"] for row in training},
        )
        late = [row for row in rows if row["date"].year == 2014][:1]
        with self.assertRaisesRegex(CalibrationError, "beyond the fold horizon"):
            lookup(training + late, 2014, calibration.training_cutoff(2014))


class FailureTests(unittest.TestCase):
    def test_optimizer_failure_is_preserved_before_raise(self):
        class BrokenAdapter:
            @staticmethod
            def fit(*args, **kwargs):
                raise ValueError("synthetic optimizer failure")

        rows, outcomes = synthetic_rows()
        events = []
        with self.assertRaisesRegex(CalibrationError, "2014/dynamic"):
            calibration.fit_and_predict(
                rows,
                calibration.fold_outcomes_from_mapping(outcomes),
                [2014],
                adapter=BrokenAdapter,
                event_sink=events.append,
            )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "failed")
        self.assertEqual(events[0]["outer_year"], 2014)
        self.assertEqual(events[0]["family"], "dynamic")
        self.assertIn("synthetic optimizer failure", events[0]["error"])

    @staticmethod
    def synthetic_workspace(root: Path, config: dict) -> None:
        """Materialise the config's data sources under ``root`` and bind their hashes."""
        source = config["source"]
        contents = {
            source["design_path"]: b"design\n",
            source["primary_config_path"]: json.dumps(
                {"proposal_status": "frozen_for_real_execution", "input": {"panel_sha256": "x"}}
            ).encode(),
            source["selected_matches_path"]: b"match_id\n",
            source["panel_path"]: b"match_id\n",
            source["rule_mapping_path"]: b"source_key\n",
        }
        for relative, payload in contents.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        digest = {k: hashlib.sha256(v).hexdigest() for k, v in contents.items()}
        manifest = {
            "status": "complete",
            "config_sha256": digest[source["primary_config_path"]],
            "panel_sha256": digest[source["panel_path"]],
            "rule_mapping_sha256": digest[source["rule_mapping_path"]],
            "selected_matches_sha256": digest[source["selected_matches_path"]],
            "selected_matches_rows": source["selected_matches_rows"],
        }
        manifest_path = root / source["point_manifest_path"]
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest))
        digest[source["point_manifest_path"]] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        for record in config["bindings"]["files"]:
            if record.get("path") in digest:
                record["sha256"] = digest[record["path"]]
        for name in (
            "design",
            "primary_config",
            "point_manifest",
            "selected_matches",
            "panel",
            "rule_mapping",
        ):
            source[f"{name}_sha256"] = digest[source[f"{name}_path"]]
        source["panel_binding_authority"] = "point_run_manifest"
        config["tour"] = "WTA"

    def test_corrupted_source_binding_fails_preflight(self):
        config = json.loads((FIXTURES / "sr03_config.candidate.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.synthetic_workspace(root, config)
            with mock.patch.dict(os.environ, {"TENNISLAB_WORKSPACE": str(root)}):
                reset_workspace_cache()
                try:
                    bound = calibration.validate_bindings(config)
                    self.assertEqual(
                        bound["declared_binding"]["implementation"],
                        "references/SR03_calibration/calibration.py",
                    )
                    self.assertEqual(len(bound["declared_binding"]["files"]), 3)
                    corrupted = copy.deepcopy(config)
                    corrupted["source"]["design_sha256"] = "0" * 64
                    with self.assertRaisesRegex(ValueError, "source hash differs"):
                        calibration.validate_bindings(corrupted)
                    missing_code = copy.deepcopy(config)
                    missing_code["bindings"]["files"] = [
                        record
                        for record in missing_code["bindings"]["files"]
                        if not record["path"].endswith("runner.py")
                    ]
                    with self.assertRaisesRegex(ValueError, "required code boundary"):
                        calibration.validate_bindings(missing_code)
                finally:
                    reset_workspace_cache()

    def test_chain_driver_binding_shape_records_package_receipts(self):
        config = json.loads((FIXTURES / "sr03_config.candidate.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.synthetic_workspace(root, config)
            receipts = [
                {
                    "module": "tennislab.dynamics.calibrate",
                    "sha256": "a" * 64,
                    "package_version": "0.1.0",
                },
                {
                    "module": "tennislab.dynamics.market",
                    "sha256": "b" * 64,
                    "package_version": "0.1.0",
                },
            ]
            config["bindings"] = {
                "implementation": "tennislab.dynamics.calibrate",
                "files": [
                    record
                    for record in config["bindings"]["files"]
                    if not record["path"].endswith(".py")
                ]
                + receipts,
            }
            with mock.patch.dict(os.environ, {"TENNISLAB_WORKSPACE": str(root)}):
                reset_workspace_cache()
                try:
                    bound = calibration.validate_bindings(config)
                    self.assertEqual(
                        bound["declared_binding"],
                        {"implementation": "tennislab.dynamics.calibrate", "files": receipts},
                    )
                    no_code = copy.deepcopy(config)
                    no_code["bindings"]["files"] = no_code["bindings"]["files"][:-2]
                    with self.assertRaisesRegex(ValueError, "no code receipt"):
                        calibration.validate_bindings(no_code)
                finally:
                    reset_workspace_cache()

    def test_nonconforming_fit_result_is_rejected(self):
        class Product:
            def record(self):
                return {"penalty": None, "residual_coefficient": 0.1, "market_slope": 1.0, "n": 15}

        class BadAdapter:
            @staticmethod
            def fit(*args, **kwargs):
                return Product()

        rows, outcomes = synthetic_rows()
        events = []
        with self.assertRaisesRegex(CalibrationError, "nonconforming"):
            calibration.fit_and_predict(
                rows,
                calibration.fold_outcomes_from_mapping(outcomes),
                [2014],
                adapter=BadAdapter,
                event_sink=events.append,
            )
        self.assertEqual(events[0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
