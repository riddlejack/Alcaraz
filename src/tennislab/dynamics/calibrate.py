"""Stage ``sr03_calibration``: year-parameterised SR03 slope calibration of a point run,
and the post-barrier stage ``sr03_component`` that scores what it predicted.

Ported from the archive's ``references/TIER01_models/sr03_calibrate.py`` (base) with the
``references/WTA02_models/sr03_calibrate.py`` additions merged: the ``tour`` switch in
the panel-binding authority. The calibration core lives in
:mod:`tennislab.dynamics.calibration`; this module reads the config, derives the
:class:`~tennislab.dynamics.calibration.CalibrationWindow` from ``year_plan``, validates
the bindings, runs the fits and writes the stage directory.

Decision RB14 (Lane B2): the calibration stage is **forecast-only**. It writes fits,
slope receipts, training membership and ``predictions.csv`` for every outer year and
scores nothing; ``scoring_boundary.json`` says so and records the historical
``calibration.score_years_max`` value where a frozen config still carries one. The
component metrics the archive wrote here before the barrier (``metrics.csv``,
``reliability.csv``, ``comparisons.json``, ``cohort_counts.json``) are computed by
``calibrate evaluate`` in stage ``sr03_component`` after the report, from the persisted
predictions, with identical arithmetic.

Outcome reads. The fits read training outcomes through
:func:`calibration.panel_outcomes_for_fold` (one ``PanelOutcomeHistory`` per outer year,
ceiling = outer year − 1, cutoff = 30 December); ``evaluate`` reads the scored outcomes
through the same accessor with purpose ``component_scoring`` and no ceiling.

    python -m tennislab.dynamics.calibrate run <sr03 config> <stage dir>
    python -m tennislab.dynamics.calibrate evaluate <sr03 config> <calibration stage dir> <stage dir> [--barrier-completion <path>]
    python -m tennislab.dynamics.calibrate preflight <sr03 config>
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    canonical_hash,
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

COMPONENT_FILES = ("metrics.csv", "reliability.csv", "comparisons.json", "cohort_counts.json")
LEGACY_FIT_DISCLOSURE_POLICY = "legacy_full_fit_record"
CAMPAIGN_FIT_DISCLOSURE_POLICY = "campaign_commit_objective_defer_value"
FIT_DISCLOSURE_POLICIES = frozenset({LEGACY_FIT_DISCLOSURE_POLICY, CAMPAIGN_FIT_DISCLOSURE_POLICY})
FIT_OBJECTIVES_FILE = "fit_objectives.json"


def fit_disclosure_policy(config: Mapping[str, Any]) -> str:
    """Return the explicit SR03 fit-record disclosure policy.

    Historical configurations carry no policy and retain the exact legacy record.  The
    campaign policy is opt-in because it changes only what is serialized around the
    frozen fit, never the fit or its predictions.
    """
    section = config.get("calibration")
    if not isinstance(section, Mapping):
        raise ChainError("calibration configuration must be an object")
    policy = section.get("fit_disclosure_policy", LEGACY_FIT_DISCLOSURE_POLICY)
    if policy not in FIT_DISCLOSURE_POLICIES:
        raise ChainError(f"unsupported calibration.fit_disclosure_policy: {policy!r}")
    return str(policy)


def prebarrier_fit_record(record: Mapping[str, Any], *, policy: str) -> dict[str, Any]:
    """Apply a disclosure policy before a fit record reaches either write sink."""
    if policy == LEGACY_FIT_DISCLOSURE_POLICY:
        return copy.deepcopy(dict(record))
    if policy != CAMPAIGN_FIT_DISCLOSURE_POLICY:
        raise ChainError(f"unsupported fit disclosure policy: {policy!r}")
    serialized = copy.deepcopy(dict(record))
    fit = serialized.get("fit")
    if not isinstance(fit, dict) or "objective" not in fit:
        # Failure records contain no fit and must remain visible verbatim.
        if serialized.get("status") == "failed" and fit is None:
            return serialized
        raise ChainError("completed campaign fit record lacks fit.objective")
    objective = fit["objective"]
    if isinstance(objective, bool) or not isinstance(objective, (int, float)):
        raise ChainError("completed campaign fit objective is not numeric")
    if not math.isfinite(float(objective)):
        raise ChainError("completed campaign fit objective is not finite")
    commitment = canonical_hash(serialized)
    del fit["objective"]
    serialized["full_fit_record_commitment_sha256"] = commitment
    serialized["fit_objective_disclosure"] = "deferred_to_post_barrier"
    return serialized


def disclose_postbarrier_fit_objectives(
    prebarrier_records: Sequence[Mapping[str, Any]],
    recomputed_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Verify prebarrier commitments and disclose recomputed objective values."""
    by_key = {
        (int(record["outer_year"]), str(record["family"])): record for record in recomputed_records
    }
    if len(by_key) != len(recomputed_records):
        raise ChainError("recomputed SR03 fits contain duplicate year/family keys")
    disclosed: list[dict[str, Any]] = []
    for prebarrier in prebarrier_records:
        key = (int(prebarrier["outer_year"]), str(prebarrier["family"]))
        recomputed = by_key.pop(key, None)
        if recomputed is None:
            raise ChainError(f"prebarrier SR03 fit has no recomputed counterpart: {key}")
        if prebarrier.get("fit_objective_disclosure") != "deferred_to_post_barrier":
            raise ChainError(f"prebarrier SR03 fit lacks the campaign disclosure marker: {key}")
        fit = prebarrier.get("fit")
        if not isinstance(fit, Mapping) or "objective" in fit:
            raise ChainError(f"prebarrier SR03 fit exposed an objective value: {key}")
        commitment = prebarrier.get("full_fit_record_commitment_sha256")
        observed = canonical_hash(recomputed)
        if commitment != observed:
            raise ChainError(f"recomputed SR03 fit differs from its prebarrier commitment: {key}")
        recomputed_fit = recomputed.get("fit")
        if not isinstance(recomputed_fit, Mapping) or "objective" not in recomputed_fit:
            raise ChainError(f"recomputed SR03 fit lacks its objective: {key}")
        disclosed.append(
            {
                "outer_year": key[0],
                "family": key[1],
                "objective": recomputed_fit["objective"],
                "full_fit_record_commitment_sha256": commitment,
                "commitment_verified": True,
                "basis": "recomputed_after_report_barrier_from_hash_bound_inputs",
            }
        )
    if by_key:
        raise ChainError(f"unexpected recomputed SR03 fits: {sorted(by_key)}")
    return disclosed


def scoring_boundary(config: dict[str, Any], outer_years: list[int]) -> dict[str, Any]:
    """The receipt that nothing was scored here and every outer year is deferred."""
    section = config["calibration"]
    return {
        "outer_years_scored": [],
        "outer_years_deferred_to_sr03_component_stage": sorted(int(y) for y in outer_years),
        "historical_score_years_max": section.get("score_years_max"),
        "basis": "RB14: the calibration stage emits fits and predictions only; component "
        "metrics are computed after the report barrier by `calibrate evaluate`",
    }


def _load(config_path: Path) -> tuple[dict[str, Any], CalibrationWindow, dict[str, Any]]:
    config = read_config(config_path)
    fit_disclosure_policy(config)
    window = CalibrationWindow.from_config(config)
    calibration.validate_config(config, require_frozen=True, window=window)
    manifest = calibration.validate_bindings(config, window=window)
    return config, window, manifest


def _refuse_nonempty(output: Path) -> None:
    # An empty pre-created directory is allowed (the chain driver creates the stage
    # directory first); a nonempty one is refused.
    if output.exists() and any(output.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)


def _source_hashes(config: dict[str, Any]) -> dict[str, str]:
    source = config["source"]
    return {
        "point_manifest_sha256": sha256(
            resolve_under_root(source["point_manifest_path"], label="point_manifest")
        ),
        "selected_matches_sha256": sha256(
            resolve_under_root(source["selected_matches_path"], label="selected_matches")
        ),
        "panel_sha256": sha256(resolve_under_root(source["panel_path"], label="panel")),
        "rule_mapping_sha256": sha256(
            resolve_under_root(source["rule_mapping_path"], label="rule_mapping")
        ),
    }


def run(config_path: Path, output: Path) -> dict[str, Any]:
    config_path = resolve_under_root(config_path, label="config")
    output = resolve_output_under_root(output, label="output")
    config, window, manifest = _load(config_path)
    disclosure_policy = fit_disclosure_policy(config)
    _refuse_nonempty(output)
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
        serialized = prebarrier_fit_record(event, policy=disclosure_policy)
        with (output / "fit_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(serialized, sort_keys=True, allow_nan=False) + "\n")

    try:
        dataset = calibration.load_dataset(
            config,
            window=window,
            labels=True,
            exclude_without_rule=True,
            prices=disclosure_policy != CAMPAIGN_FIT_DISCLOSURE_POLICY,
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
        outer_years = [int(year) for year in config["calibration"]["outer_years"]]
        predictions, fits, memberships = calibration.fit_and_predict(
            dataset.rows,
            calibration.panel_outcomes_for_fold(dataset),
            outer_years,
            window=window,
            event_sink=event_sink,
        )
        expected_fits = len(outer_years) * len(FAMILIES)
        if len(fits) != expected_fits:
            raise ChainError(f"scheduled fit count differs: {len(fits)} != {expected_fits}")
        serialized_fits = [
            prebarrier_fit_record(record, policy=disclosure_policy) for record in fits
        ]
        write_csv(output / "training_membership.csv", memberships, TRAINING_FIELDS)
        write_json(output / "fits.json", serialized_fits)
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
        boundary = scoring_boundary(config, outer_years)
        if disclosure_policy == CAMPAIGN_FIT_DISCLOSURE_POLICY:
            boundary["fit_disclosure"] = {
                "policy": disclosure_policy,
                "objective_values_written_prebarrier": False,
                "commitment": "canonical_sha256_of_each_complete_unredacted_fit_record",
                "disclosure_stage": "sr03_component_after_report_barrier",
                "raw_decimal_quotes_parsed_prebarrier": False,
                "prediction_price_values_written_prebarrier": False,
            }
        write_json(output / "scoring_boundary.json", boundary)
    except Exception as exc:
        write_json(output / "failure.json", {**start, "status": "failed", "error": str(exc)})
        raise

    files = sorted(path for path in output.iterdir() if path.is_file())
    document = {
        "status": "complete",
        "experiment_id": config["experiment_id"],
        "config_sha256": sha256(config_path),
        **_source_hashes(config),
        "source_point_rows": manifest["selected_matches_rows"],
        "fits": len(fits),
        "predictions": len(predictions),
        "scored": 0,
        "code": {
            "calibrate": code_receipt(__name__),
            "calibration": code_receipt(calibration.__name__),
            "market": code_receipt(market.__name__),
            "sr02_runner": code_receipt(sr02_runner.__name__),
            "declared_binding": manifest["declared_binding"],
        },
        "artifacts": {path.name: sha256(path) for path in files},
    }
    if disclosure_policy == CAMPAIGN_FIT_DISCLOSURE_POLICY:
        document["fit_disclosure"] = {
            "policy": disclosure_policy,
            "objective_values_written_prebarrier": False,
            "committed_fit_records": len(fits),
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


def _verify_campaign_barrier(
    config_path: Path, calibration_dir: Path, barrier_completion: Path | None
) -> dict[str, Any]:
    if barrier_completion is None:
        raise ChainError("campaign-policy evaluate requires --barrier-completion")
    barrier_path = resolve_under_root(barrier_completion, label="campaign barrier completion")
    if barrier_path.name != "barrier_manifest.json" or barrier_path.parent.name != "barrier":
        raise ChainError("campaign-policy evaluate received an invalid barrier path")
    from tennislab.campaign.barrier import verify_barrier
    from tennislab.campaign.contracts import load_campaign_config

    barrier_document = read_config(barrier_path)
    if (
        barrier_document.get("schema") != "campaign_barrier_completion/v1"
        or barrier_document.get("status") != "complete"
    ):
        raise ChainError("campaign-policy evaluate requires a completed campaign barrier")
    consumer_path = resolve_under_root(
        barrier_document.get("config_path", ""), label="campaign consumer config"
    )
    if barrier_document.get("config_sha256") != sha256(consumer_path):
        raise ChainError("campaign barrier/consumer config binding drift")
    campaign = load_campaign_config(consumer_path)
    output_root = barrier_path.parent.parent
    if output_root != campaign.output_prefix and campaign.output_prefix not in output_root.parents:
        raise ChainError("campaign barrier is outside its declared output")
    verified = verify_barrier(campaign, output_root)
    native = campaign.producer_plan.get("native_sr03", {})
    native_config = resolve_under_root(
        native.get("config", {}).get("path", ""), label="native config"
    )
    if native_config != config_path or native.get("config", {}).get("sha256") != sha256(
        config_path
    ):
        raise ChainError("campaign producer plan binds a different native SR03 config")
    if (
        resolve_under_root(native.get("fits_path", ""), label="native fits")
        != calibration_dir / "fits.json"
    ):
        raise ChainError("campaign producer plan binds a different native fits sink")
    if (
        resolve_under_root(native.get("events_path", ""), label="native events")
        != calibration_dir / "fit_events.jsonl"
    ):
        raise ChainError("campaign producer plan binds a different native event sink")
    return verified


def _campaign_disclosure_sinks(
    calibration_dir: Path, run_manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    fits_path = calibration_dir / "fits.json"
    events_path = calibration_dir / "fit_events.jsonl"
    if run_manifest.get("artifacts", {}).get("fits.json") != sha256(fits_path):
        raise ChainError("persisted SR03 fits differ from the calibration manifest")
    if run_manifest.get("artifacts", {}).get("fit_events.jsonl") != sha256(events_path):
        raise ChainError("persisted SR03 events differ from the calibration manifest")
    try:
        fits = json.loads(fits_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as error:
        raise ChainError(f"cannot read prebarrier SR03 disclosure sinks: {error}") from error
    if not isinstance(fits, list) or any(not isinstance(item, dict) for item in [*fits, *events]):
        raise ChainError("prebarrier SR03 disclosure sinks have invalid records")
    if (
        not isinstance(run_manifest.get("fits"), int)
        or len(fits) != run_manifest["fits"]
        or len(events) != run_manifest["fits"]
    ):
        raise ChainError("prebarrier SR03 sink inventory differs from the calibration manifest")

    def commitments(records: Sequence[Mapping[str, Any]], sink: str) -> dict[tuple[int, str], str]:
        output: dict[tuple[int, str], str] = {}
        for record in records:
            key = (int(record["outer_year"]), str(record["family"]))
            fit = record.get("fit")
            if not isinstance(fit, Mapping) or "objective" in fit:
                raise ChainError(f"prebarrier SR03 {sink} exposed or omitted fit objective")
            if record.get("fit_objective_disclosure") != "deferred_to_post_barrier":
                raise ChainError(f"prebarrier SR03 {sink} lacks disclosure marker")
            commitment = record.get("full_fit_record_commitment_sha256")
            if not isinstance(commitment, str) or len(commitment) != 64:
                raise ChainError(f"prebarrier SR03 {sink} lacks full-record commitment")
            if key in output:
                raise ChainError(f"duplicate prebarrier SR03 {sink} key: {key}")
            output[key] = commitment
        return output

    if commitments(fits, "fits") != commitments(events, "events"):
        raise ChainError("prebarrier SR03 sink commitments differ")
    return fits


def evaluate(
    config_path: Path,
    calibration_dir: Path,
    output: Path,
    *,
    barrier_completion: Path | None = None,
) -> dict[str, Any]:
    """Stage ``sr03_component``: score the persisted predictions, after the barrier.

    The predictions are bound by the calibration stage's ``run_manifest.json``; the
    dataset is reloaded from the same panel and selected matches (hash-checked by the
    config bindings); the arithmetic is :func:`calibration.evaluate` unchanged.
    """
    config_path = resolve_under_root(config_path, label="config")
    calibration_dir = resolve_under_root(calibration_dir, label="calibration_dir")
    output = resolve_output_under_root(output, label="output")
    config, window, manifest = _load(config_path)
    disclosure_policy = fit_disclosure_policy(config)
    campaign_barrier: dict[str, Any] | None = None
    if disclosure_policy == CAMPAIGN_FIT_DISCLOSURE_POLICY:
        campaign_barrier = _verify_campaign_barrier(
            config_path, calibration_dir, barrier_completion
        )
    run_manifest = read_config(calibration_dir / "run_manifest.json")
    if run_manifest.get("status") != "complete":
        raise ChainError("calibration stage did not complete")
    if run_manifest.get("config_sha256") != sha256(config_path):
        raise ChainError("calibration stage ran with a different config")
    predictions_path = calibration_dir / "predictions.csv"
    predictions_sha256 = sha256(predictions_path)
    if run_manifest["artifacts"].get("predictions.csv") != predictions_sha256:
        raise ChainError("persisted predictions differ from the calibration manifest")
    _refuse_nonempty(output)

    dataset = calibration.load_dataset(
        config, window=window, labels=True, exclude_without_rule=True
    )
    predictions = [
        {**row, "calibration_year": int(row["calibration_year"])}
        for row in read_csv(predictions_path)
    ]
    postbarrier_prices = (
        {str(item["match_id"]): item["pinnacle_raw_normalized"] for item in dataset.rows}
        if disclosure_policy == CAMPAIGN_FIT_DISCLOSURE_POLICY
        else None
    )
    for row in predictions:
        for field in (
            *(f"raw_{f}" for f, _ in FAMILIES),
            *(f"calibrated_{f}" for f, _ in FAMILIES),
        ):
            row[field] = float(row[field])
        if postbarrier_prices is not None:
            row["pinnacle_raw_normalized"] = postbarrier_prices[str(row["match_id"])]
        else:
            row["pinnacle_raw_normalized"] = (
                None
                if row["pinnacle_raw_normalized"] == ""
                else float(row["pinnacle_raw_normalized"])
            )
    known = {row["match_id"] for row in dataset.rows if row.get("outcome_known")}
    resolved_ids = [str(row["match_id"]) for row in predictions if str(row["match_id"]) in known]
    from tennislab.chain.labels import PanelOutcomeHistory

    history = PanelOutcomeHistory(
        dataset.panel_path, dataset.panel_sha256, purpose="component_scoring"
    )
    outcomes = history.selected(resolved_ids)  # outcome read after the barrier
    metrics, bins, comparisons, counts = calibration.evaluate(
        dataset.rows,
        outcomes,
        predictions,
        edges=config["calibration"]["reliability_bin_edges"],
        bootstrap_seed=config["comparisons"]["bootstrap_seed"],
        bootstrap_repetitions=config["comparisons"]["bootstrap_repetitions"],
    )
    component_files = list(COMPONENT_FILES)
    fit_disclosure: dict[str, Any] | None = None
    if disclosure_policy == CAMPAIGN_FIT_DISCLOSURE_POLICY:
        if run_manifest.get("fit_disclosure", {}).get("policy") != disclosure_policy:
            raise ChainError("calibration manifest has a different fit disclosure policy")
        prebarrier_fits = _campaign_disclosure_sinks(calibration_dir, run_manifest)
        outer_years = [int(year) for year in config["calibration"]["outer_years"]]
        _, recomputed_fits, _ = calibration.fit_and_predict(
            dataset.rows,
            calibration.panel_outcomes_for_fold(dataset),
            outer_years,
            window=window,
        )
        disclosed = disclose_postbarrier_fit_objectives(prebarrier_fits, recomputed_fits)
        write_json(output / FIT_OBJECTIVES_FILE, disclosed)
        component_files.append(FIT_OBJECTIVES_FILE)
        fit_disclosure = {
            "policy": disclosure_policy,
            "postbarrier_objectives_disclosed": len(disclosed),
            "all_prebarrier_commitments_verified": True,
            "both_prebarrier_sinks_reconciled": True,
            "barrier_completion_sha256": sha256(
                resolve_under_root(barrier_completion, label="campaign barrier completion")
            ),
            "forecast_tree_sha256": campaign_barrier["forecast_tree_sha256"],
        }
    write_csv(output / "metrics.csv", metrics, METRIC_FIELDS)
    write_csv(output / "reliability.csv", bins, RELIABILITY_FIELDS)
    write_json(output / "comparisons.json", comparisons)
    write_json(output / "cohort_counts.json", counts)
    document = {
        "status": "complete",
        "experiment_id": config["experiment_id"],
        "config_sha256": sha256(config_path),
        **_source_hashes(config),
        "calibration_run_manifest_sha256": sha256(calibration_dir / "run_manifest.json"),
        "predictions_sha256": predictions_sha256,
        "prediction_rows": len(predictions),
        "scored_rows": counts["resolved_outcome_rows"],
        "unresolved_rows": counts["unresolved_outcome_rows"],
        "outcome_read": history.reads[-1],
        "code": {
            "calibrate": code_receipt(__name__),
            "calibration": code_receipt(calibration.__name__),
            "market": code_receipt(market.__name__),
            "sr02_runner": code_receipt(sr02_runner.__name__),
            "declared_binding": manifest["declared_binding"],
        },
        "artifacts": {name: sha256(output / name) for name in component_files},
    }
    if fit_disclosure is not None:
        document["fit_disclosure"] = fit_disclosure
    write_json(output / "component_manifest.json", document)
    print(
        json.dumps(
            {
                "status": "complete",
                "scored_rows": counts["resolved_outcome_rows"],
                "unresolved_rows": counts["unresolved_outcome_rows"],
                "output": relative_to_root(output, label="output"),
            }
        )
    )
    return document


def preflight(config_path: Path) -> dict[str, object]:
    config_path = resolve_under_root(config_path, label="config")
    config = read_config(config_path)
    disclosure_policy = fit_disclosure_policy(config)
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
    document: dict[str, object] = {
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
    if disclosure_policy == CAMPAIGN_FIT_DISCLOSURE_POLICY:
        document["fit_disclosure_policy"] = disclosure_policy
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("config", type=Path)
    run_parser.add_argument("output", type=Path)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("config", type=Path)
    evaluate_parser.add_argument("calibration_dir", type=Path)
    evaluate_parser.add_argument("output", type=Path)
    evaluate_parser.add_argument("--barrier-completion", type=Path)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("config", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.config, args.output)
    elif args.command == "evaluate":
        evaluate(
            args.config,
            args.calibration_dir,
            args.output,
            barrier_completion=args.barrier_completion,
        )
    else:
        print(json.dumps(preflight(args.config), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
