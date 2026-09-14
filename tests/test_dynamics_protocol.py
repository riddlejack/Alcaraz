"""Archive ``references/SR02_models/test_protocol.py``, importing from the package."""

import copy
import unittest
from unittest import mock

import numpy as np
from scipy.special import expit

from tennislab.dynamics.protocol import Store, prior_rows, run


class Guarded(dict):
    def __getitem__(self, key):
        if key == "a_won":
            raise RuntimeError("Future or excluded outcome was accessed")
        return super().__getitem__(key)


def synthetic():
    rng = np.random.default_rng(13092)
    rows = []
    for year in range(2011, 2018):
        for i in range(60):
            z, r = rng.normal(), rng.normal(scale=0.5)
            rows.append(
                {
                    "match_id": f"{year}-fixture/{i}",
                    "match_date": f"{year}-06-{i % 28 + 1:02}",
                    "source_season": year,
                    "identity_tier": "primary",
                    "PS_valid": True,
                    "q": float(expit(z)),
                    "dynamic_match_probability_a": float(expit(z + r)),
                    "unadjusted_match_probability_a": float(expit(z + r / 2)),
                    "a_won": int(rng.binomial(1, expit(z + r / 2))),
                }
            )
    return rows


class ProtocolTests(unittest.TestCase):
    def test_all_target_outcomes_are_unread_for_fitting_and_selection(self):
        rows = synthetic()
        guarded = [Guarded(r) if r["source_season"] == 2017 else r for r in rows]
        ordinary = run(rows, [2017])
        result = run(guarded, [2017])
        self.assertEqual(result, ordinary)
        self.assertEqual(len(result["predictions"]), 60)

    def test_selection_cutoff_excludes_dec31_and_mismatched_year(self):
        rows = synthetic()
        extra = copy.deepcopy(rows[-1])
        extra.update(match_id="2016-last/1", match_date="2016-12-31", source_season=2016)
        mismatch = copy.deepcopy(extra)
        mismatch.update(match_id="2017-year/1", source_season=2017, match_date="2016-12-30")
        expanded = rows + [Guarded(extra), Guarded(mismatch)]
        self.assertEqual(run(expanded, [2017]), run(rows, [2017]))
        kept = prior_rows(expanded, 2017)
        self.assertTrue(
            all("last" not in r["match_id"] and "year" not in r["match_id"] for r in kept)
        )

    def test_provisional_targets_never_update_fit_or_selection(self):
        rows = synthetic()
        extra = copy.deepcopy(rows[0])
        extra.update(match_id="provisional-history", identity_tier="provisional")
        self.assertEqual(run(rows + [Guarded(extra)], [2017]), run(rows, [2017]))

    def test_zero_residual_selection_is_exact_market_every_year(self):
        rows = synthetic()
        for row in rows:
            row["dynamic_match_probability_a"] = row["q"]
            row["unadjusted_match_probability_a"] = row["q"]
        result = run(rows, [2017])
        self.assertTrue(all(s["penalty"] is None for s in result["selections"]))
        self.assertTrue(
            all(
                p["dynamic_augmented"] == p["unadjusted_augmented"] == p["market_calibrated"]
                for p in result["predictions"]
            )
        )

    def test_invalid_metadata_is_not_treated_as_truthy(self):
        rows = synthetic()
        rows[0]["PS_valid"] = "false"
        with self.assertRaises(ValueError):
            Store(rows)

    def test_failed_fit_emits_bound_attempt_record_and_stops(self):
        events = []
        store = Store(synthetic(), record_sink=events.append)
        with mock.patch(
            "tennislab.dynamics.protocol.market.fit",
            side_effect=ValueError("synthetic numerical failure"),
        ):
            with self.assertRaisesRegex(ValueError, "year=2014"):
                store.get(2014, "dynamic", 0.01)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "failed")
        self.assertEqual(events[0]["penalty"], 0.01)
        self.assertEqual(len(events[0]["training_keys_sha256"]), 64)
        self.assertFalse(store.fits)


if __name__ == "__main__":
    unittest.main()
