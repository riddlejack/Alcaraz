"""Archive ``references/SR02_models/test_path_runner.py``, importing from the package.

The archive mocked ``path_runner.REPO_ROOT``; here the two end-to-end tests point the
declared workspace (``TENNISLAB_WORKSPACE``) at a temporary root instead.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from tennislab.config import reset_workspace_cache
from tennislab.dynamics import path_runner
from tennislab.dynamics.dynamic import TargetMatch
from tennislab.dynamics.path_runner import (
    PathTarget,
    checkpoint_candidate_path,
    control_point_path,
    dynamic_point_path,
    load_candidate_checkpoint,
    merge_selected_matches,
    point_loss_rows,
    run,
    select_family,
    selected_match_predictions,
)
from tests.test_dynamics_dynamic import CONFIG, STANDARD_BO3, observation

CANDIDATE_CONFIG = Path(__file__).parent / "fixtures" / "sr02_config.candidate.json"


@contextlib.contextmanager
def workspace(root: Path) -> Iterator[Path]:
    with mock.patch.dict(os.environ, {"TENNISLAB_WORKSPACE": str(root)}):
        reset_workspace_cache()
        try:
            yield root
        finally:
            reset_workspace_cache()


def path_target(item, source_season: int | None = None) -> PathTarget:
    return PathTarget(
        TargetMatch(
            item.match_id,
            item.match_date,
            item.tourney_id,
            item.surface,
            3,
            item.player_a,
            item.player_b,
            STANDARD_BO3,
        ),
        item.match_date.year if source_season is None else source_season,
        item.match_id,
    )


def loss_row(candidate: str, date: str, mean_loss: float, points: int = 100) -> dict[str, object]:
    return {
        "candidate_id": candidate,
        "match_id": f"match-{date}",
        "match_date": date,
        "source_season": int(date[:4]),
        "service_points": points,
        "negative_log_likelihood": mean_loss * points,
        "contests_used": 2,
    }


class PathTests(unittest.TestCase):
    def test_future_count_mutation_leaves_earlier_path_and_selection_unchanged(self) -> None:
        history = [
            observation(f"m{year}", f"{year}-06-01", 1, 2, a_won_points=40 + year % 5)
            for year in range(2008, 2013)
        ]
        changed = list(history)
        changed[-1] = observation("m2012", "2012-06-01", 1, 2, a_won_points=1)
        targets = [path_target(item) for item in history]
        first = dynamic_point_path(history, targets, CONFIG, "candidate")
        second = dynamic_point_path(changed, targets, CONFIG, "candidate")
        self.assertEqual(
            [row for row in first if row["match_date"] < "2012-01-01"],
            [row for row in second if row["match_date"] < "2012-01-01"],
        )
        first_losses = point_loss_rows(first, {item.match_id: item for item in history})
        second_losses = point_loss_rows(second, {item.match_id: item for item in changed})
        first_selection, _ = select_family(
            {"candidate": first_losses},
            {"candidate": (0,)},
            selection_years=[2011],
            fallback_candidate_id="candidate",
        )
        second_selection, _ = select_family(
            {"candidate": second_losses},
            {"candidate": (0,)},
            selection_years=[2011],
            fallback_candidate_id="candidate",
        )
        self.assertEqual(first_selection, second_selection)

    def test_dynamic_and_control_paths_are_label_free_and_share_keys(self) -> None:
        history = [observation("m1", "2010-01-01", 1, 2, a_won_points=48)]
        targets = [path_target(history[0])]
        dynamic = dynamic_point_path(history, targets, CONFIG, "d")
        control = control_point_path(
            history,
            targets,
            "c",
            half_life_days=180.0,
            overall_prior_units=50.0,
            surface_prior_units=50.0,
            initial_serve_probability=0.62,
        )
        self.assertEqual(dynamic[0]["match_id"], control[0]["match_id"])
        self.assertNotIn("a_won", dynamic[0])
        self.assertNotIn("a_won", control[0])
        self.assertEqual(dynamic[0]["latest_source_date"], "")
        self.assertEqual(control[0]["latest_source_date"], "")

    def test_point_loss_uses_unequal_service_denominators(self) -> None:
        item = observation(
            "m1",
            "2010-01-01",
            1,
            2,
            a_won_points=15,
            a_points=20,
            b_won_points=130,
            b_points=200,
        )
        rows = dynamic_point_path([item], [path_target(item)], CONFIG, "d")
        losses = point_loss_rows(rows, {item.match_id: item})
        self.assertEqual(losses[0]["service_points"], 220)
        self.assertEqual(losses[0]["contests_used"], 2)

    def test_dynamic_path_retains_solver_acceptance_summary(self) -> None:
        source = observation("source", "2010-01-01", 1, 2, a_won_points=48)
        target = observation("target", "2010-01-03", 1, 2, a_won_points=45)
        summary: dict[str, object] = {}
        dynamic_point_path(
            [source], [path_target(target)], CONFIG, "candidate", solver_summary=summary
        )
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["batch_count"], 1)
        self.assertEqual(sum(summary["acceptance_counts"].values()), 1)
        self.assertGreaterEqual(summary["maximum_iterations"], 1)
        self.assertGreaterEqual(summary["maximum_absolute_gradient"], 0.0)
        self.assertGreaterEqual(summary["maximum_newton_decrement"], 0.0)


class SelectionTests(unittest.TestCase):
    def test_december_31_is_excluded_from_immediately_prior_year(self) -> None:
        base_dates = ("2008-06-01", "2009-06-01", "2010-06-01")
        losses = {
            "stable": [loss_row("stable", date, 0.5) for date in base_dates]
            + [loss_row("stable", "2010-12-31", 2.0)],
            "dec31_only": [loss_row("dec31_only", date, 0.6) for date in base_dates]
            + [loss_row("dec31_only", "2010-12-31", 0.0)],
        }
        selected, trials = select_family(
            losses,
            {"stable": (0,), "dec31_only": (1,)},
            selection_years=[2011],
            fallback_candidate_id="stable",
        )
        self.assertEqual(selected[0]["selection_cutoff"], "2010-12-30")
        self.assertEqual(selected[0]["selected_candidate_id"], "stable")
        for row in trials:
            self.assertEqual(
                row["calendar_year_point_counts"], '{"2008": 100, "2009": 100, "2010": 100}'
            )

    def test_exact_tie_uses_declared_rank(self) -> None:
        rows = [
            loss_row("unused", date, 0.5) for date in ("2008-01-01", "2009-01-01", "2010-01-01")
        ]
        losses = {
            candidate: [dict(row, candidate_id=candidate) for row in rows]
            for candidate in ("a", "b")
        }
        selected, _ = select_family(
            losses, {"a": (1,), "b": (0,)}, selection_years=[2011], fallback_candidate_id="a"
        )
        self.assertEqual(selected[0]["selected_candidate_id"], "b")

    def test_inadequate_year_uses_only_declared_fallback(self) -> None:
        rows = [loss_row("fallback", date, 0.5) for date in ("2008-01-01", "2010-01-01")]
        losses = {
            "fallback": rows,
            "other": [dict(row, candidate_id="other") for row in rows],
        }
        selected, _ = select_family(
            losses,
            {"fallback": (0,), "other": (1,)},
            selection_years=[2011],
            fallback_candidate_id="fallback",
        )
        self.assertEqual(selected[0]["selected_candidate_id"], "fallback")
        self.assertEqual(selected[0]["selection_reason"], "inadequate_validation_coverage")

    def test_candidate_specific_missing_loss_fails_closed(self) -> None:
        dates = ("2008-01-01", "2009-01-01", "2010-01-01")
        complete = [loss_row("complete", date, 0.5) for date in dates]
        incomplete = [loss_row("incomplete", date, 0.5) for date in dates[:-1]]
        with self.assertRaisesRegex(ValueError, "membership differs"):
            select_family(
                {"complete": complete, "incomplete": incomplete},
                {"complete": (0,), "incomplete": (1,)},
                selection_years=[2011],
                fallback_candidate_id="complete",
            )


class OutputTests(unittest.TestCase):
    def test_selected_stage_interface_and_source_year_flag(self) -> None:
        item = observation("m2011", "2011-06-01", 1, 2, a_won_points=45)
        targets = [path_target(item, source_season=2010)]
        dynamic_paths = {"d": dynamic_point_path([item], targets, CONFIG, "d")}
        control_paths = {
            "c": control_point_path(
                [item],
                targets,
                "c",
                half_life_days=180.0,
                overall_prior_units=50.0,
                surface_prior_units=50.0,
                initial_serve_probability=0.62,
            )
        }
        selection_d = [{"selection_year": 2011, "selected_candidate_id": "d"}]
        selection_c = [{"selection_year": 2011, "selected_candidate_id": "c"}]
        dynamic = selected_match_predictions("dynamic", dynamic_paths, selection_d, targets)
        control = selected_match_predictions("control", control_paths, selection_c, targets)
        merged = merge_selected_matches(dynamic, control)
        self.assertEqual(merged[0]["annual_target_eligible"], 0)
        self.assertEqual(merged[0]["selected_dynamic_id"], "d")
        self.assertEqual(merged[0]["selected_unadjusted_id"], "c")
        self.assertNotIn("a_won", merged[0])
        self.assertFalse(any("PS_" in field for field in merged[0]))

    def test_checkpoint_reuse_requires_exact_binding_and_file_hash(self) -> None:
        item = observation("m1", "2010-01-01", 1, 2)
        rows = dynamic_point_path([item], [path_target(item)], CONFIG, "d")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "candidate"
            _, first = checkpoint_candidate_path(
                directory, {"input_sha256": "a", "candidate_id": "d"}, rows
            )
            directly_loaded = load_candidate_checkpoint(
                directory, {"input_sha256": "a", "candidate_id": "d"}
            )
            loaded, second = checkpoint_candidate_path(
                directory, {"input_sha256": "a", "candidate_id": "d"}, rows
            )
            self.assertEqual((first, second), ("written", "reused"))
            self.assertEqual(directly_loaded, loaded)
            self.assertEqual(len(loaded), 1)
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                checkpoint_candidate_path(
                    directory, {"input_sha256": "b", "candidate_id": "d"}, rows
                )
            path = directory / "point_forecasts.csv"
            path.write_text(path.read_text() + "tamper\n")
            with self.assertRaisesRegex(ValueError, "file hash mismatch"):
                checkpoint_candidate_path(
                    directory, {"input_sha256": "a", "candidate_id": "d"}, rows
                )

    def test_dynamic_checkpoint_binds_solver_summary_hash(self) -> None:
        source = observation("source", "2010-01-01", 1, 2)
        target = observation("target", "2010-01-03", 1, 2)
        summary: dict[str, object] = {}
        rows = dynamic_point_path(
            [source], [path_target(target)], CONFIG, "d", solver_summary=summary
        )
        binding = {"candidate_family": "dynamic", "candidate": {"candidate_id": "d"}}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "candidate"
            checkpoint_candidate_path(directory, binding, rows, solver_summary=summary)
            summary_path = directory / "solver_summary.json"
            value = json.loads(summary_path.read_text())
            value["batch_count"] += 1
            summary_path.write_text(json.dumps(value) + "\n")
            with self.assertRaisesRegex(ValueError, "summary hash mismatch"):
                load_candidate_checkpoint(directory, binding)

    def test_candidate_config_refuses_real_execution_before_any_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, workspace(Path(temporary)) as root:
            config = root / "config.candidate.json"
            config.write_bytes(CANDIDATE_CONFIG.read_bytes())
            output = root / "output"
            with self.assertRaisesRegex(ValueError, "not frozen"):
                run(config, output)
            self.assertFalse(output.exists())

    def test_full_synthetic_runner_emits_bound_stage_manifest_and_resumes(self) -> None:
        first = observation("m2011a", "2011-06-01", 1, 2, a_won_points=45)
        second = observation("m2011b", "2011-06-03", 1, 2, a_won_points=46)
        items = [first, second]
        targets = [path_target(item) for item in items]
        with tempfile.TemporaryDirectory() as temporary, workspace(Path(temporary)) as root:
            config = json.loads(CANDIDATE_CONFIG.read_text())
            dynamic_candidate = config["hyperparameter_selection_proposal"]["candidate_menu"][0]
            control_candidate = config["unadjusted_baseline"]["selection_proposal"][
                "candidate_menu"
            ][0]
            config["proposal_status"] = "frozen_for_real_execution"
            config["execution_binding"] = {"synthetic": True}
            config["selection_years"] = [2011]
            config["hyperparameter_selection_proposal"]["candidate_menu"] = [dynamic_candidate]
            config["hyperparameter_selection_proposal"]["fallback_candidate_id"] = (
                dynamic_candidate["candidate_id"]
            )
            config["unadjusted_baseline"]["selection_proposal"]["candidate_menu"] = [
                control_candidate
            ]
            config["unadjusted_baseline"]["selection_proposal"]["fallback_candidate_id"] = (
                control_candidate["candidate_id"]
            )
            config["input"]["panel_sha256"] = "synthetic-panel"
            config["match_conversion"]["rule_mapping_sha256"] = "synthetic-rules"
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config, sort_keys=True) + "\n")
            output = root / "output"
            with (
                mock.patch.object(path_runner, "_require_frozen"),
                mock.patch.object(path_runner, "_load_source", return_value=(items, targets)),
            ):
                manifest = run(config_path, output)
                resumed = run(config_path, output)
            self.assertEqual(manifest, resumed)
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["panel_sha256"], "synthetic-panel")
            self.assertEqual(manifest["rule_mapping_sha256"], "synthetic-rules")
            self.assertEqual(manifest["selected_matches_rows"], 2)
            self.assertEqual(manifest["run_binding"]["config_path"], "config.json")
            self.assertEqual(
                manifest["selected_matches_sha256"],
                path_runner.sha256(output / "selected_matches.csv"),
            )
            header = (output / "selected_matches.csv").read_text().splitlines()[0]
            self.assertNotIn("a_won", header)
            self.assertNotIn("PS_", header)
            summary = json.loads(
                next(
                    (output / "candidate_paths" / "dynamic").glob("*/solver_summary.json")
                ).read_text()
            )
            self.assertEqual(summary["status"], "complete")
            self.assertGreaterEqual(summary["batch_count"], 1)

    def test_fatal_dynamic_batch_writes_bound_source_date_receipt(self) -> None:
        first = observation("m2011a", "2011-06-01", 1, 2)
        second = observation("m2011b", "2011-06-03", 1, 2)
        items = [first, second]
        targets = [path_target(item) for item in items]
        with tempfile.TemporaryDirectory() as temporary, workspace(Path(temporary)) as root:
            config = json.loads(CANDIDATE_CONFIG.read_text())
            dynamic_candidate = config["hyperparameter_selection_proposal"]["candidate_menu"][0]
            config["proposal_status"] = "frozen_for_real_execution"
            config["execution_binding"] = {"synthetic": True}
            config["hyperparameter_selection_proposal"]["candidate_menu"] = [dynamic_candidate]
            config["hyperparameter_selection_proposal"]["fallback_candidate_id"] = (
                dynamic_candidate["candidate_id"]
            )
            config["input"]["panel_sha256"] = "synthetic-panel"
            config["match_conversion"]["rule_mapping_sha256"] = "synthetic-rules"
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config, sort_keys=True) + "\n")
            output = root / "output"
            with (
                mock.patch.object(path_runner, "_require_frozen"),
                mock.patch.object(path_runner, "_load_source", return_value=(items, targets)),
                mock.patch.object(
                    path_runner.DynamicServeReturnFilter,
                    "apply_batch",
                    side_effect=RuntimeError("synthetic solver failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic solver failure"):
                    run(config_path, output)
            receipt_path = next((output / "candidate_paths" / "dynamic").glob("*/failure.json"))
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "fatal")
            self.assertEqual(receipt["source_date"], "2011-06-01")
            self.assertEqual(receipt["candidate_id"], dynamic_candidate["candidate_id"])
            self.assertEqual(
                receipt["binding_sha256"], path_runner.canonical_json_hash(receipt["binding"])
            )


class DateSanity(unittest.TestCase):
    def test_path_target_requires_audit_metadata(self) -> None:
        item = observation("m1", "2010-01-01", 1, 2)
        with self.assertRaisesRegex(ValueError, "audit metadata"):
            PathTarget(path_target(item).match, 0, item.match_id)
        self.assertEqual(path_target(item).match.match_date, dt.date(2010, 1, 1))


if __name__ == "__main__":
    unittest.main()
