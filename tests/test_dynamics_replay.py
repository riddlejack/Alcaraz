"""Stage-level checks of ``tennislab.dynamics.replay``'s pure helpers on synthetic rows.

The archive had no unit tests for ``sr02_replay.py``; its equivalence is established by
``tools/equivalence.py`` (see ``docs/equivalence/notes/sr02_replay.md``). These tests pin
the configuration switches the port merged from the TIER01 and WTA02 copies.
"""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tennislab.chain.common import ChainError
from tennislab.dynamics import replay
from tennislab.dynamics.dynamic import SOURCE_ROW_FIELDS
from tests.test_dynamics_dynamic import source_row
from tests.test_dynamics_path_runner import path_target

RULE = json.dumps(
    {
        "sets_to_win": 2,
        "regular_set": {"mode": "tiebreak", "tiebreak_at_games": 6, "tiebreak_points": 7},
        "deciding_set": {"mode": "tiebreak", "tiebreak_at_games": 6, "tiebreak_points": 10},
    }
)


def panel_row(match_id: str, date: str, a: int, b: int, **overrides: str) -> dict[str, str]:
    row = source_row(match_id, date, a, b)
    row.update(
        {
            "source_season": date[:4],
            "source_key": match_id,
            "round": "R32",
            "best_of": "3",
            "tourney_id": f"{date[:4]}-T",
        }
    )
    row.update(overrides)
    return row


def write_panel(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(
        dict.fromkeys((*SOURCE_ROW_FIELDS, "source_season", "source_key", "round", "best_of"))
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_rules(path: Path, rows: list[dict[str, str]], *, drop: set[str] = frozenset()) -> None:
    fields = [
        "match_id",
        "source_key",
        "source_season",
        "tourney_id",
        "round",
        "best_of",
        "match_rule",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            record = {field: row[field] for field in fields[:-1]}
            record["match_rule"] = "" if row["match_id"] in drop else RULE
            writer.writerow(record)


class SelectionMapTests(unittest.TestCase):
    def test_years_after_the_last_saved_selection_inherit_it(self) -> None:
        saved = [
            {
                "candidate_family": "dynamic",
                "selection_year": "2023",
                "selected_candidate_id": "d1",
            },
            {
                "candidate_family": "dynamic",
                "selection_year": "2024",
                "selected_candidate_id": "d2",
            },
            {
                "candidate_family": "control",
                "selection_year": "2024",
                "selected_candidate_id": "c1",
            },
        ]
        resolved, records = replay.selection_map(saved, (2024, 2025, 2026))
        self.assertEqual(resolved[("dynamic", 2026)], "d2")
        self.assertEqual(resolved[("control", 2025)], "c1")
        carried = [row for row in records if row["source"] == "carried_forward"]
        self.assertEqual(len(carried), 4)
        self.assertTrue(all(row["inherited_from_selection_year"] == "2024" for row in carried))
        with self.assertRaisesRegex(ChainError, "refusing to invent"):
            replay.selection_map(saved, (2022,))


class LoadSourceTests(unittest.TestCase):
    def test_relabelling_and_count_history_floor_suppress_updates_not_targets(self) -> None:
        rows = [
            panel_row("2015-T/1", "2015-06-01", 1, 2),
            panel_row("2016-T/1", "2016-06-01", 1, 2, count_block_status="quarantined_invalid"),
            panel_row("2016-T/2", "2016-06-02", 1, 3, count_block_status="partial_missing"),
            panel_row("2016-T/3", "2016-06-03", 2, 3),
        ]
        for row in rows[1:3]:
            for key in list(row):
                if key.startswith(("a_", "b_")) and key not in {
                    "a_entity_id",
                    "b_entity_id",
                    "a_won",
                    "a_rank",
                    "b_rank",
                }:
                    row[key] = ""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_panel(root / "panel.csv", rows)
            write_rules(root / "rules.csv", rows, drop={"2016-T/3"})
            observations, targets, summary = replay.load_source(
                root / "panel.csv",
                root / "rules.csv",
                history_statuses=("completed", "retired", "default"),
                source_year_min=2015,
                source_year_max=2016,
                relabelled_statuses=("quarantined_invalid", "partial_missing"),
                count_history_from_year=2016,
            )
        self.assertEqual(len(observations), 4)
        self.assertEqual(len(targets), 4)
        self.assertEqual(
            [item.history_eligible for item in observations], [False, False, False, True]
        )
        self.assertEqual(summary["quarantined_invalid_count_block_match_ids"], ["2016-T/1"])
        self.assertEqual(
            summary["count_blocks_relabelled_to_missing_all"],
            {"partial_missing": 1, "quarantined_invalid": 1},
        )
        self.assertEqual(summary["pre_floor_count_blocks_suppressed_by_year"], {2015: 1})
        self.assertEqual(summary["targets_without_a_rule_examples"], ["2016-T/3"])
        self.assertIsNone(targets[3].match.rule)

    def test_source_span_is_enforced(self) -> None:
        rows = [panel_row("2016-T/1", "2016-06-01", 1, 2)]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_panel(root / "panel.csv", rows)
            write_rules(root / "rules.csv", rows)
            with self.assertRaisesRegex(ChainError, "outside the configured span"):
                replay.load_source(
                    root / "panel.csv",
                    root / "rules.csv",
                    history_statuses=("completed",),
                    source_year_min=2017,
                    source_year_max=2018,
                )


class ProvenanceTests(unittest.TestCase):
    def test_same_event_membership_respects_the_availability_lag(self) -> None:
        from tennislab.dynamics.dynamic import observation_from_source_row

        target = path_target(observation_from_source_row(panel_row("2016-T/9", "2016-06-10", 1, 2)))
        feed = [
            {
                "tourney_id": "2016-T",
                "match_id": "q1",
                "match_date": "2016-06-08",
                "count_block_status": "usable",
            },
            {
                "tourney_id": "2016-T",
                "match_id": "q2",
                "match_date": "2016-06-09",
                "count_block_status": "usable",
            },
            {
                "tourney_id": "2016-T",
                "match_id": "q3",
                "match_date": "2016-06-07",
                "count_block_status": "missing_all",
            },
        ]
        membership = replay.same_event_membership(feed, [target], lag_days=2)
        self.assertEqual(len(membership), 1)
        self.assertEqual(membership[0]["same_event_qualifying_rows"], 1)
        self.assertEqual(membership[0]["latest_qualifying_date"], "2016-06-08")

    def test_dispersion_flags_a_constant_year(self) -> None:
        merged = [
            {
                "match_date": "2015-01-01",
                "dynamic_match_probability_a": 0.5,
                "dynamic_a_serve_unseen": 1,
            },
            {
                "match_date": "2015-02-01",
                "dynamic_match_probability_a": 0.5,
                "dynamic_a_serve_unseen": 1,
            },
            {
                "match_date": "2016-01-01",
                "dynamic_match_probability_a": 0.4,
                "dynamic_a_serve_unseen": 0,
            },
            {
                "match_date": "2016-02-01",
                "dynamic_match_probability_a": 0.6,
                "dynamic_a_serve_unseen": 0,
            },
        ]
        dispersion = replay.dynamic_dispersion_by_year(merged)
        self.assertFalse(dispersion["2015"]["informative"])
        self.assertEqual(dispersion["2015"]["rows_with_an_unseen_serve_state"], 2)
        self.assertTrue(dispersion["2016"]["informative"])
        self.assertAlmostEqual(dispersion["2016"]["dynamic_probability_sd"], 0.1)

    def test_reporting_revision_follows_tour(self) -> None:
        self.assertEqual(replay.reporting_revision({}), "TIER01")
        self.assertEqual(replay.reporting_revision({"tour": "wta"}), "WTA02")
        with self.assertRaises(ChainError):
            replay.reporting_revision({"tour": "ITF"})


if __name__ == "__main__":
    unittest.main()
