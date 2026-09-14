"""Synthetic full-entrypoint check of ``sr02_runner``; never reads the tennis panel.

Archive ``references/SR02_models/test_runner.py``. The archive copied the three SR02
files into a temporary ``references/SR02_models`` and hash-bound them; the port runs the
package module with the temporary root as the declared workspace, and the code entries of
``market_execution.files`` are declared provenance, so they are listed but not hashed.
"""

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_file(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class RunnerTests(unittest.TestCase):
    def test_synthetic_release_and_corrupted_prediction_rejected(self):
        with tempfile.TemporaryDirectory(prefix="sr02-synthetic-") as directory:
            root = Path(directory)
            rng = np.random.default_rng(92310)
            panel, points, old = [], [], []
            for year in range(2011, 2025):
                for i in range(12):
                    q = float(rng.uniform(0.2, 0.8))
                    p = float(np.clip(q + rng.normal(0, 0.1), 0.15, 0.85))
                    metadata = dict(
                        match_id=f"{year}-fixture/{i}",
                        source_key=f"{year}-fixture/{i}",
                        source_season=str(year),
                        match_date=f"{year}-06-{i + 1:02}",
                        tourney_id=f"{year}-fixture",
                        surface="Hard",
                        best_of="3",
                        player_a="1",
                        player_b="2",
                    )
                    panel.append(
                        {
                            **metadata,
                            "a_won": str(bool(rng.binomial(1, q))).lower(),
                            "PS_valid": "true",
                            "PS_decimal_a": 1 / (q * 1.04),
                            "PS_decimal_b": 1 / ((1 - q) * 1.04),
                            "completed": "true",
                            "source_field_agreement": "true",
                            "identity_tier": "primary",
                            "status": "completed",
                        }
                    )
                    points.append(
                        {
                            **metadata,
                            "rule_status": "provided",
                            "dynamic_match_probability_a": p,
                            "unadjusted_match_probability_a": 0.5 * q + 0.5 * p,
                            "simple_unadjusted_match_probability_a": 0.5 + 0.5 * (p - 0.5),
                        }
                    )
                    if year >= 2012:
                        old.append(
                            {
                                "season": year,
                                "match_id": metadata["match_id"],
                                "reported_match_date": metadata["match_date"],
                                "pinnacle_raw_normalized": q,
                                "pinnacle_calibration_logistic": q,
                            }
                        )
            csv_file(root / "panel.csv", panel)
            csv_file(root / "legacy.csv", old)
            point_dir = root / "point_run"
            point_dir.mkdir()
            csv_file(point_dir / "selected_matches.csv", points)
            code = [
                {"path": f"references/SR02_models/{name}.py", "sha256": "declared"}
                for name in ("market", "protocol", "runner")
            ]
            config = {
                "proposal_status": "frozen_for_real_execution",
                "input": {"panel_path": "panel.csv", "panel_sha256": sha(root / "panel.csv")},
                "market_execution": {
                    "penalties": [None, 1.0, 0.1, 0.01, 0.001],
                    "files": [
                        *code,
                        {"path": "legacy.csv", "sha256": sha(root / "legacy.csv")},
                    ],
                    "legacy_market_predictions": {
                        "path": "legacy.csv",
                        "sha256": sha(root / "legacy.csv"),
                    },
                },
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config))
            point_manifest = {
                "status": "complete",
                "config_sha256": sha(config_path),
                "panel_sha256": sha(root / "panel.csv"),
                "selected_matches_sha256": sha(point_dir / "selected_matches.csv"),
                "selected_matches_rows": len(points),
            }
            (point_dir / "run_manifest.json").write_text(json.dumps(point_manifest))
            command = [
                sys.executable,
                "-m",
                "tennislab.dynamics.sr02_runner",
                "config.json",
                "point_run",
            ]
            env = {
                **os.environ,
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "TENNISLAB_WORKSPACE": str(root),
            }
            completed = subprocess.run(
                [*command, "output"], capture_output=True, text=True, env=env, cwd=root
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            manifest = json.loads((root / "output" / "run_manifest.json").read_text())
            self.assertEqual(manifest["predictions"], 96)
            self.assertEqual(manifest["selections"], 16)
            self.assertEqual(manifest["code"]["declared_binding"], code)
            self.assertEqual(manifest["code"]["runner"]["module"], "tennislab.dynamics.sr02_runner")
            comparisons = json.loads((root / "output" / "comparisons.json").read_text())
            self.assertIn(
                "market_2017_2024/primary/dynamic_augmented_minus_market_calibrated", comparisons
            )
            self.assertIn(
                "market_2017_2024/primary/dynamic_augmented_minus_legacy_pinnacle_calibration",
                comparisons,
            )
            with (point_dir / "selected_matches.csv").open("a") as handle:
                handle.write("\nCORRUPTED")
            rejected = subprocess.run(
                [*command, "bad_output"], capture_output=True, text=True, env=env, cwd=root
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Completed point stage does not match", rejected.stderr)
            self.assertFalse((root / "bad_output").exists())


if __name__ == "__main__":
    unittest.main()
