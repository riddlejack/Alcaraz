"""Stage ``sr03_calibration``: year-parameterised SR03 slope calibration of a point run.

Ported from the archive's ``references/TIER01_models/sr03_calibrate.py`` (base) with the
``references/WTA02_models/sr03_calibrate.py`` additions merged: the ``tour`` switch in
the panel-binding authority and the ``calibration.score_years_max`` scoring ceiling.
The calibration core lives in :mod:`tennislab.dynamics.calibration`; this module reads
the config, derives the :class:`~tennislab.dynamics.calibration.CalibrationWindow` from
``year_plan``, validates the bindings, runs the fits and writes the stage directory.

Configuration switches (both default to the TIER01 behaviour):

* ``calibration.score_years_max`` -- when the key is *declared* (even as ``null``) the
  stage writes ``scoring_boundary.json`` and scores only calibration years at or below
  the ceiling (WTA02 rule 6: no component metric on a target year before the report
  stage); fits and predictions for every outer year are still persisted. When the key
  is absent every outer year is scored and no boundary receipt is written, as SR03 and
  CONFIRM2026 did.
* ``tour`` -- ``point_run_manifest`` panel-binding authority is accepted for another
  tour's panel as well as for an extended ATP panel.

Outcome reads. This stage loads the panel's ``a_won`` for every played selected match
(``calibration.load_dataset``), fits on training years (history) and then, in
``calibration.evaluate``, scores ``metrics.csv``, ``reliability.csv``,
``comparisons.json`` and ``cohort_counts.json`` on the outer years -- the target years
included unless ``score_years_max`` excludes them. This is the archive's B1 exposure;
the reads are marked ``# outcome-history read`` in the core for the integration pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    code_receipt,
    read_config,
    relative_to_root,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
)
from tennislab.dynamics import calibration, market, sr02_runner
from tennislab.dynamics.calibration import (
    FAMILIES,
    METRIC_FIELDS,
    PREDICTION_FIELDS,
    RELIABILITY_FIELDS,
    TRAINING_FIELDS,
    CalibrationWindow,
    read_csv,
    write_csv,
    write_json,
)


def scoring_selection(
    config: dict[str, Any], predictions: list[dict[str, object]]
) -> tuple[list[dict[str, object]], dict[str, Any] | None]:
    """The predictions to score and, when a ceiling is declared, the boundary receipt."""
    section = config["calibration"]
    if "score_years_max" not in section:
        return predictions, None
    score_years_max = section["score_years_max"]
    scored = predictions
    suppressed: list[int] = []
    if score_years_max is not None:
        scored = [
            item for item in predictions if int(item["calibration_year"]) <= int(score_years_max)
        ]
        suppressed = sorted(
            {
                int(item["calibration_year"])
                for item in predictions
                if int(item["calibration_year"]) > int(score_years_max)
            }
        )
    boundary = {
        "score_years_max": score_years_max,
        "outer_years_scored": sorted({int(item["calibration_year"]) for item in scored}),
        "outer_years_suppressed_until_report_stage": suppressed,
        "predictions_persisted_for_suppressed_years": sum(
            1 for item in predictions if int(item["calibration_year"]) in set(suppressed)
        ),
        "basis": "WTA02 declared rule 6: no component metric on a target year before the report stage",
    }
    return scored, boundary


def run(config_path: Path, output: Path) -> dict[str, Any]:
    config_path = resolve_under_root(config_path, label="config")
    output = resolve_output_under_root(output, label="output")
    config = read_config(config_path)
    window = CalibrationWindow.from_config(config)
    calibration.validate_config(config, require_frozen=True, window=window)
    manifest = calibration.validate_bindings(config, window=window)
    # An empty pre-created directory is allowed (the chain driver creates the stage
    # directory first); a nonempty one is refused.
    if output.exists() and any(output.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    start = {
        "experiment_id": config["experiment_id"],
        "config_path": relative_to_root(config_path, label="config"),
        "config_sha256": sha256(config_path),
        "point_manifest_sha256": config["source"]["point_manifest_sha256"],
        "selected_matches_sha256": config["source"]["selected_matches_sha256"],
        "panel_sha256": config["source"]["panel_sha256"],
        "design_sha256": config["source"]["design_sha256"],
    }
    write_json(output / "start.json", start)

    def event_sink(event: dict[str, object]) -> None:
        with (output / "fit_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")

    try:
        dataset = calibration.load_dataset(
            config, window=window, labels=True, exclude_without_rule=True
        )
        if dataset.refused_without_rule:
            print(
                json.dumps(
                    {
                        "rows_excluded_rule_status_not_provided": len(dataset.refused_without_rule),
                        "examples": sorted(dataset.refused_without_rule)[:10],
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
        predictions, fits, memberships = calibration.fit_and_predict(
            dataset.rows,
            dataset.outcomes,
            config["calibration"]["outer_years"],
            window=window,
            event_sink=event_sink,
        )
        expected_fits = len(config["calibration"]["outer_years"]) * len(FAMILIES)
        if len(fits) != expected_fits:
            raise ChainError(f"scheduled fit count differs: {len(fits)} != {expected_fits}")
        write_csv(output / "training_membership.csv", memberships, TRAINING_FIELDS)
        write_json(output / "fits.json", fits)
        write_csv(output / "predictions.csv", predictions, PREDICTION_FIELDS)
        write_json(
            output / "predictions_boundary.json",
            {
                "status": "year_ahead_predictions_persisted_before_outer_scoring",
                "predictions_sha256": sha256(output / "predictions.csv"),
                "prediction_rows": len(predictions),
                "target_outcome_fields_in_prediction_artifact": [],
                "limit": "Input bytes contain exposed outcomes; chronology and separate label access enforce the developmental information boundary, not holdout custody.",
            },
        )
        scored, boundary = scoring_selection(config, predictions)
        if boundary is not None:
            write_json(output / "scoring_boundary.json", boundary)
        if scored:
            metrics, bins, comparisons, counts = calibration.evaluate(
                dataset.rows,
                dataset.outcomes,
                scored,
                edges=config["calibration"]["reliability_bin_edges"],
                bootstrap_seed=config["comparisons"]["bootstrap_seed"],
                bootstrap_repetitions=config["comparisons"]["bootstrap_repetitions"],
            )
        else:
            metrics, bins, comparisons, counts = (
                [],
                [],
                {},
                {"prediction_rows": 0, "scoring_suppressed": True},
            )
        write_csv(output / "metrics.csv", metrics, METRIC_FIELDS)
        write_csv(output / "reliability.csv", bins, RELIABILITY_FIELDS)
        write_json(output / "comparisons.json", comparisons)
        write_json(output / "cohort_counts.json", counts)
    except Exception as exc:
        write_json(output / "failure.json", {**start, "status": "failed", "error": str(exc)})
        raise

    files = sorted(path for path in output.iterdir() if path.is_file())
    document = {
        "status": "complete",
        "experiment_id": config["experiment_id"],
        "config_sha256": sha256(config_path),
        "point_manifest_sha256": sha256(
            resolve_under_root(config["source"]["point_manifest_path"], label="point_manifest")
        ),
        "selected_matches_sha256": sha256(
            resolve_under_root(config["source"]["selected_matches_path"], label="selected_matches")
        ),
        "panel_sha256": sha256(resolve_under_root(config["source"]["panel_path"], label="panel")),
        "rule_mapping_sha256": sha256(
            resolve_under_root(config["source"]["rule_mapping_path"], label="rule_mapping")
        ),
        "source_point_rows": manifest["selected_matches_rows"],
        "fits": len(fits),
        "predictions": len(predictions),
        "code": {
            "calibrate": code_receipt(__name__),
            "calibration": code_receipt(calibration.__name__),
            "market": code_receipt(market.__name__),
            "sr02_runner": code_receipt(sr02_runner.__name__),
            "declared_binding": manifest["declared_binding"],
        },
        "artifacts": {path.name: sha256(path) for path in files},
    }
    write_json(output / "run_manifest.json", document)
    print(
        json.dumps(
            {
                "status": "complete",
                "fits": len(fits),
                "predictions": len(predictions),
                "output": relative_to_root(output, label="output"),
            }
        )
    )
    return document


def preflight(config_path: Path) -> dict[str, object]:
    config_path = resolve_under_root(config_path, label="config")
    config = read_config(config_path)
    window = CalibrationWindow.from_config(config)
    manifest = calibration.validate_bindings(config, window=window)
    selected = read_csv(
        resolve_under_root(config["source"]["selected_matches_path"], label="selected_matches")
    )
    required = {
        "match_id",
        "match_date",
        "source_season",
        "source_key",
        "tourney_id",
        "surface",
        "best_of",
        "player_a",
        "player_b",
        "annual_target_eligible",
        "rule_status",
        *(field for _, field in FAMILIES),
    }
    if not selected or not required <= set(selected[0]):
        raise ChainError("selected match schema lacks required prediction inputs")
    return {
        "status": "PASS",
        "scope": "hash_schema_and_point_manifest_binding_only_no_fit_or_score",
        "config_sha256": sha256(config_path),
        "point_manifest_sha256": sha256(
            resolve_under_root(config["source"]["point_manifest_path"], label="point_manifest")
        ),
        "selected_matches_sha256": sha256(
            resolve_under_root(config["source"]["selected_matches_path"], label="selected_matches")
        ),
        "selected_matches_rows": len(selected),
        "manifest_selected_matches_rows": manifest["selected_matches_rows"],
        "scheduled_fits": len(config["calibration"]["outer_years"]) * len(FAMILIES),
        "outer_years": config["calibration"]["outer_years"],
        "calibration_window": window.as_document(),
        "outcomes_accessed": False,
        "model_fit_executed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("config", type=Path)
    run_parser.add_argument("output", type=Path)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("config", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.config, args.output)
    else:
        print(json.dumps(preflight(args.config), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
