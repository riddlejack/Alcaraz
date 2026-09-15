"""Post-barrier fixed comparison, equal-year arithmetic, and edition bootstrap."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.campaign.artifacts import (
    CampaignInputs,
    QuoteArtifact,
    load_inputs,
    load_quotes,
    read_target_labels,
)
from tennislab.campaign.barrier import verify_barrier
from tennislab.campaign.contracts import CampaignConfig, config_receipt
from tennislab.campaign.forecast import compute_fold, read_decision, read_forecasts
from tennislab.campaign.stages import (
    REPORT_COMPLETION_SCHEMA,
    inventory_contract_map,
    inventory_sha256,
    read_object,
    report_inventory_contract,
    require_completion,
    typed_artifact,
    validate_typed_inventory,
)
from tennislab.chain.common import (
    atomic_csv,
    atomic_json,
    canonical_hash_nonempty,
    serialize_cell,
    sha256,
)
from tennislab.evaluation.scores import individual_scores, reliability_bins
from tennislab.models.numerical import key_hash

MODELS = ("S0", "S1", "S2", "S3")
PRICED_MODELS = (*MODELS, "result_elo", "normalized_pinnacle")
CONTRASTS = {
    "S3_minus_S0": ("S3", "S0"),
    "S1_minus_S0": ("S1", "S0"),
    "S2_minus_S0": ("S2", "S0"),
    "S3_minus_S2": ("S3", "S2"),
}
SCORE_CLIP = 1e-15


class CampaignReportError(ValueError):
    """A post-barrier cohort, score, commitment, or report contract failed."""


def _year_detail(
    year: int,
    rows: Sequence[Mapping[str, str]],
    inputs: CampaignInputs,
    quotes: QuoteArtifact,
    labels: Mapping[tuple[str, str], int],
) -> dict[str, Any]:
    keys = tuple((row["season"], row["match_id"]) for row in rows)
    if keys != inputs.cohort_keys[year]:
        raise CampaignReportError(f"forecast/cohort membership drift in {year}")
    outcomes = np.asarray([labels[key] for key in keys], dtype=np.int8)
    model_scores: dict[str, Any] = {}
    for model in MODELS:
        probabilities = np.asarray([float(row[model]) for row in rows], dtype=np.float64)
        losses, brier, clip_count = individual_scores(probabilities, outcomes, SCORE_CLIP)
        model_scores[model] = {
            "probabilities": probabilities,
            "losses": losses,
            "brier": brier,
            "probability_clip_count": clip_count,
        }
    priced_indices = np.asarray(
        [index for index, key in enumerate(keys) if key in set(inputs.priced_keys[year])],
        dtype=np.int64,
    )
    if not len(priced_indices):
        raise CampaignReportError(f"year {year} has no frozen priced subset")
    priced_scores: dict[str, Any] = {}
    priced_outcomes = outcomes[priced_indices]
    priced_probabilities = {
        **{model: model_scores[model]["probabilities"][priced_indices] for model in MODELS},
        "result_elo": np.asarray(
            [inputs.raw_members[(year, "result_elo")].probabilities[key] for key in keys],
            dtype=np.float64,
        )[priced_indices],
        "normalized_pinnacle": np.asarray(
            [quotes.probabilities[keys[int(index)]] for index in priced_indices],
            dtype=np.float64,
        ),
    }
    for model, probabilities in priced_probabilities.items():
        losses, brier, clip_count = individual_scores(probabilities, priced_outcomes, SCORE_CLIP)
        priced_scores[model] = {
            "probabilities": probabilities,
            "losses": losses,
            "brier": brier,
            "probability_clip_count": clip_count,
        }
    deltas = {
        name: model_scores[treatment]["losses"] - model_scores[control]["losses"]
        for name, (treatment, control) in CONTRASTS.items()
    }
    brier_deltas = {
        name: model_scores[treatment]["brier"] - model_scores[control]["brier"]
        for name, (treatment, control) in CONTRASTS.items()
    }
    editions: dict[str, list[int]] = {}
    for index, (key, row) in enumerate(zip(keys, rows, strict=True)):
        tourney_id = inputs.metadata[key]["tourney_id"]
        if row["tourney_id"] != tourney_id or not tourney_id:
            raise CampaignReportError(f"edition identity drift at {key}")
        editions.setdefault(tourney_id, []).append(index)
    return {
        "year": year,
        "keys": keys,
        "membership_sha256": key_hash(keys),
        "outcomes": outcomes,
        "model_scores": model_scores,
        "deltas": deltas,
        "brier_deltas": brier_deltas,
        "editions": {name: editions[name] for name in sorted(editions)},
        "priced_indices": priced_indices,
        "priced_outcomes": priced_outcomes,
        "priced_scores": priced_scores,
    }


def _bootstrap(
    details: Sequence[Mapping[str, Any]], *, replicates: int, seed: int
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    rng = np.random.default_rng(seed)
    matrix = np.zeros((replicates, len(details)), dtype=np.float64)
    inventory: list[dict[str, Any]] = []
    for column, detail in enumerate(details):
        names = tuple(detail["editions"])
        if not names:
            raise CampaignReportError(f"year {detail['year']} has no edition blocks")
        block_sums = np.asarray(
            [
                [
                    float(np.sum(detail["deltas"]["S3_minus_S0"][detail["editions"][name]])),
                    len(detail["editions"][name]),
                ]
                for name in names
            ],
            dtype=np.float64,
        )
        draws = rng.integers(0, len(names), size=(replicates, len(names)))
        sampled = block_sums[draws].sum(axis=1)
        matrix[:, column] = sampled[:, 0] / sampled[:, 1]
        inventory.append(
            {
                "season": detail["year"],
                "paired_rows": len(detail["keys"]),
                "tournament_editions": len(names),
                "membership_sha256": detail["membership_sha256"],
            }
        )
    return matrix.mean(axis=1), inventory


def _criterion_receipts(
    config: CampaignConfig, inputs: CampaignInputs, output_root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipts: dict[str, Any] = {}
    recomputation: dict[str, Any] = {}
    for year in config.target_years:
        recomputed_rows, recomputed, private = compute_fold(config, inputs, year)
        saved_rows = read_forecasts(output_root / "forecast" / "forecasts" / f"{year}.csv", year)
        saved = read_decision(output_root / "forecast" / "decisions" / f"{year}.json")
        if saved != recomputed:
            raise CampaignReportError(f"complete decision recomputation drift in {year}")
        if len(saved_rows) != len(recomputed_rows):
            raise CampaignReportError(f"forecast row-count recomputation drift in {year}")
        for index, (observed, expected) in enumerate(zip(saved_rows, recomputed_rows, strict=True)):
            for field in ("season", "match_id", "tourney_id"):
                if observed[field] != expected[field]:
                    raise CampaignReportError(
                        f"forecast identity recomputation drift in {year} row {index}"
                    )
            for model in MODELS:
                try:
                    value = float(observed[model])
                except ValueError as error:
                    raise CampaignReportError(
                        f"invalid saved {model} probability in {year} row {index}"
                    ) from error
                if value != expected[model]:
                    raise CampaignReportError(
                        f"saved {model} probability differs from recomputation in {year} row {index}"
                    )
        s2_hash = canonical_hash_nonempty(private["s2"], label="S2 criterion")
        s3_hash = canonical_hash_nonempty(private["s3"], label="S3 criterion")
        if saved["S2"]["criterion_commitment_sha256"] != s2_hash:
            raise CampaignReportError(f"S2 criterion commitment drift in {year}")
        if saved["S3"]["criterion_commitment_sha256"] != s3_hash:
            raise CampaignReportError(f"S3 criterion commitment drift in {year}")
        if recomputed["target_membership_sha256"] != saved["target_membership_sha256"]:
            raise CampaignReportError(f"decision membership drift in {year}")
        receipts[str(year)] = {
            "S2": private["s2"],
            "S3": private["s3"],
            "commitments_verified": True,
        }
        recomputation[str(year)] = {
            "rows": len(recomputed_rows),
            "target_membership_sha256": recomputed["target_membership_sha256"],
            "decision_sha256": sha256(output_root / "forecast" / "decisions" / f"{year}.json"),
            "forecast_sha256": sha256(output_root / "forecast" / "forecasts" / f"{year}.csv"),
            "all_S0_S1_S2_S3_probabilities_equal": True,
            "complete_decision_equal": True,
        }
    return receipts, recomputation


def _calibration_rows(details: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in MODELS:
        pairs = [
            (float(probability), int(outcome))
            for detail in details
            for probability, outcome in zip(
                detail["model_scores"][model]["probabilities"], detail["outcomes"], strict=True
            )
        ]
        for record in reliability_bins(pairs, [index / 10 for index in range(11)]):
            rows.append({"scope": "full_sports", "model": model, **record})
    for model in PRICED_MODELS:
        pairs = [
            (float(probability), int(outcome))
            for detail in details
            for probability, outcome in zip(
                detail["priced_scores"][model]["probabilities"],
                detail["priced_outcomes"],
                strict=True,
            )
        ]
        for record in reliability_bins(pairs, [index / 10 for index in range(11)]):
            rows.append({"scope": "priced_subset", "model": model, **record})
    return rows


def _priced_summary(
    details: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    annual: list[dict[str, Any]] = []
    for detail in details:
        for model in PRICED_MODELS:
            scores = detail["priced_scores"][model]
            annual.append(
                {
                    "season": detail["year"],
                    "model": model,
                    "priced_rows": len(detail["priced_indices"]),
                    "full_sports_rows": len(detail["keys"]),
                    "mean_log_loss": float(np.mean(scores["losses"])),
                    "mean_brier": float(np.mean(scores["brier"])),
                    "probability_clip_count": scores["probability_clip_count"],
                }
            )
    models: dict[str, Any] = {}
    for model in PRICED_MODELS:
        model_annual = [row for row in annual if row["model"] == model]
        losses = np.concatenate([detail["priced_scores"][model]["losses"] for detail in details])
        brier = np.concatenate([detail["priced_scores"][model]["brier"] for detail in details])
        models[model] = {
            "equal_year_mean_log_loss": float(
                np.mean([row["mean_log_loss"] for row in model_annual])
            ),
            "match_weighted_log_loss": float(np.mean(losses)),
            "equal_year_mean_brier": float(np.mean([row["mean_brier"] for row in model_annual])),
            "match_weighted_brier": float(np.mean(brier)),
        }
    return annual, {
        "scope": "frozen_priced_subset_descriptive_only",
        "priced_rows": int(sum(len(detail["priced_indices"]) for detail in details)),
        "full_sports_rows": int(sum(len(detail["keys"]) for detail in details)),
        "per_year": [
            {
                "season": detail["year"],
                "priced_rows": len(detail["priced_indices"]),
                "full_sports_rows": len(detail["keys"]),
            }
            for detail in details
        ],
        "models": models,
        "affects_primary_membership_or_nomination": False,
    }


def _score_only_sensitivities(details: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def summarize(selected: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {
            contrast: {
                "years": [int(detail["year"]) for detail in selected],
                "equal_year_mean_log_loss_delta": float(
                    np.mean([float(np.mean(detail["deltas"][contrast])) for detail in selected])
                ),
                "years_negative": int(
                    sum(float(np.mean(detail["deltas"][contrast])) < 0.0 for detail in selected)
                ),
            }
            for contrast in CONTRASTS
        }

    return {
        "schema": "campaign_sensitivities/v1",
        "models_refit": False,
        "decisions_refit": False,
        "score_only": True,
        "leave_one_year_out": {
            str(detail["year"]): summarize(
                [item for item in details if item["year"] != detail["year"]]
            )
            for detail in details
        },
        "leave_2020_out": summarize([item for item in details if item["year"] != 2020]),
    }


def _clip_counts(details: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "campaign_clip_counts/v1",
        "score_probability_clip": SCORE_CLIP,
        "full_sports": {
            model: {
                "per_year": {
                    str(detail["year"]): int(
                        detail["model_scores"][model]["probability_clip_count"]
                    )
                    for detail in details
                },
                "total": int(
                    sum(
                        detail["model_scores"][model]["probability_clip_count"]
                        for detail in details
                    )
                ),
            }
            for model in MODELS
        },
        "priced_subset": {
            model: {
                "per_year": {
                    str(detail["year"]): int(
                        detail["priced_scores"][model]["probability_clip_count"]
                    )
                    for detail in details
                },
                "total": int(
                    sum(
                        detail["priced_scores"][model]["probability_clip_count"]
                        for detail in details
                    )
                ),
            }
            for model in PRICED_MODELS
        },
    }


def _attempt_inventory(config: CampaignConfig, output_root: Path) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for directory in (output_root / "attempts", output_root / "failures"):
        if not directory.exists():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            if path.is_symlink():
                raise CampaignReportError(f"attempt inventory contains a symlink: {path}")
            attempts.append(
                {
                    "path": path.relative_to(output_root).as_posix(),
                    "sha256": sha256(path),
                }
            )
    return {
        "schema": "campaign_attempt_inventory/v1",
        "attempt_id": config.document["attempt_id"],
        "producer_plan_sha256": config.producer_plan_sha256,
        "records": attempts,
        "failed_attempts_preserved": sum(
            record["path"].startswith("failures/") for record in attempts
        ),
    }


def _expected_report_inventory(
    config: CampaignConfig,
) -> dict[str, tuple[str, Mapping[str, Any], str]]:
    return inventory_contract_map(report_inventory_contract(), label="report inventory")


def _report_materials(
    config: CampaignConfig, inputs: CampaignInputs, output_root: Path
) -> dict[str, Any]:
    criteria, recomputation = _criterion_receipts(config, inputs, output_root)
    labels = read_target_labels(inputs)
    quotes = load_quotes(config, inputs)
    details = [
        _year_detail(
            year,
            read_forecasts(output_root / "forecast" / "forecasts" / f"{year}.csv", year),
            inputs,
            quotes,
            labels,
        )
        for year in config.target_years
    ]
    priced_rows, priced_summary = _priced_summary(details)
    annual_rows: list[dict[str, Any]] = []
    for detail in details:
        for contrast in CONTRASTS:
            annual_rows.append(
                {
                    "season": detail["year"],
                    "contrast": contrast,
                    "paired_rows": len(detail["keys"]),
                    "membership_sha256": detail["membership_sha256"],
                    "mean_log_loss_delta": float(np.mean(detail["deltas"][contrast])),
                    "mean_brier_delta": float(np.mean(detail["brier_deltas"][contrast])),
                }
            )
    summaries: dict[str, Any] = {}
    for contrast in CONTRASTS:
        annual = [row for row in annual_rows if row["contrast"] == contrast]
        all_values = np.concatenate([detail["deltas"][contrast] for detail in details])
        all_brier = np.concatenate([detail["brier_deltas"][contrast] for detail in details])
        summaries[contrast] = {
            "paired_rows": int(sum(row["paired_rows"] for row in annual)),
            "equal_year_mean_log_loss_delta": float(
                np.mean([row["mean_log_loss_delta"] for row in annual])
            ),
            "match_weighted_log_loss_delta": float(np.mean(all_values)),
            "equal_year_mean_brier_delta": float(
                np.mean([row["mean_brier_delta"] for row in annual])
            ),
            "match_weighted_brier_delta": float(np.mean(all_brier)),
            "years_negative": int(sum(row["mean_log_loss_delta"] < 0.0 for row in annual)),
        }
    bootstrap_values, bootstrap_inventory = _bootstrap(
        details,
        replicates=config.document["settings"]["report"]["bootstrap"]["replicates"],
        seed=config.document["settings"]["report"]["bootstrap"]["seed"],
    )
    lower, upper = (
        float(np.quantile(bootstrap_values, 0.025, method="linear")),
        float(np.quantile(bootstrap_values, 0.975, method="linear")),
    )
    primary = summaries["S3_minus_S0"]
    nomination = config.document["settings"]["report"]["nomination"]
    population_complete = len(config.target_years) == nomination["required_years"]
    recommendation_eligible = bool(
        population_complete
        and primary["equal_year_mean_log_loss_delta"] <= nomination["maximum_equal_year_delta"]
        and primary["years_negative"] >= nomination["minimum_negative_years"]
        and upper < 0.0
    )
    summary = {
        "schema_version": 1,
        "campaign_id": config.document["campaign_id"],
        "tour": config.tour,
        "population": {
            "years": list(config.target_years),
            "paired_rows": sum(len(detail["keys"]) for detail in details),
            "per_year": bootstrap_inventory,
            "annual_equal_year_degrees_of_freedom": len(config.target_years) - 1,
        },
        "primary": {
            "contrast": "S3_minus_S0",
            **primary,
            "edition_bootstrap_95_percentile": {
                "lower": lower,
                "upper": upper,
                "replicates": len(bootstrap_values),
                "seed": config.document["settings"]["report"]["bootstrap"]["seed"],
                "quantile_method": "linear",
                "models_refit": False,
                "stack_coefficients_refit": False,
                "conditional_limit": "saved forecasts; fitting and selection uncertainty excluded",
                "WTA_interval_label": (
                    "new WTA campaign edition interval; not the original WTA01 interval"
                    if config.tour == "WTA"
                    else None
                ),
            },
        },
        "secondary": {name: summaries[name] for name in CONTRASTS if name != "S3_minus_S0"},
        "priced_descriptive": priced_summary,
        "full_sports_probability_clip_counts": {
            model: int(
                sum(detail["model_scores"][model]["probability_clip_count"] for detail in details)
            )
            for model in MODELS
        },
        "nomination_screen": {
            "applicable_to_complete_reviewed_population": population_complete,
            "eligible_for_documented_later_manual_prospective_design": recommendation_eligible,
            "candidate": "S3_only",
            "automatic_promotion": False,
            "prospective_evidence_established": False,
        },
        "limitations": [
            "exposed historical development populations, not a new held-out window",
            "conditional bootstrap excludes model fitting and selection uncertainty",
            "annual signs are correlated robustness evidence, not independent replications",
            "passing arithmetic and integrity checks does not establish scientific validity",
            "primary population is historically market-source-conditioned",
            "quote clocks are unequal or unresolved; market comparisons are descriptive only",
            "raw decimal quotes were validated and normalized only after the barrier",
        ],
    }
    report_lines = [
        f"# {config.document['campaign_id']} — {config.tour}",
        "",
        "Primary: S3 minus unchanged S0 on the exact paired sports population.",
        "",
        f"- Equal-year log-loss delta: {primary['equal_year_mean_log_loss_delta']:.4f}",
        f"- 95% edition-bootstrap interval: [{lower:.4f}, {upper:.4f}]",
        f"- Negative annual deltas: {primary['years_negative']}/{len(config.target_years)}",
        "- Automatic promotion: no",
        "",
        "Secondary arms remain visible in summary.json: S1−S0, S2−S0, and S3−S2.",
        "Passing this reporter does not establish prospective evidence or scientific validity.",
        "The historical sports population is market-source-conditioned.",
        "Quote clocks are unequal or unresolved; quoted-market comparisons are descriptive.",
    ]
    exposure = {
        "stage": "report",
        "barrier_verified_before_target_read": True,
        "quotes_read_and_normalized_post_barrier": True,
        "raw_quotes_sha256": quotes.binding.sha256,
        "target_outcomes_read_and_scored": True,
        "target_rows": sum(len(detail["keys"]) for detail in details),
        "target_membership_sha256": key_hash(
            tuple(key for detail in details for key in detail["keys"])
        ),
        "historical_population_is_already_exposed": True,
        "prospective_evidence_created": False,
    }
    return {
        "annual_rows": annual_rows,
        "bootstrap_rows": [
            {"replicate": index, "primary_log_loss_delta": float(value)}
            for index, value in enumerate(bootstrap_values)
        ],
        "calibration_rows": _calibration_rows(details),
        "priced_rows": priced_rows,
        "criteria": criteria,
        "summary": summary,
        "report_text": "\n".join(report_lines) + "\n",
        "exposure": exposure,
        "recomputation": {"schema": "campaign_recomputation/v1", "years": recomputation},
        "sensitivities": _score_only_sensitivities(details),
        "clip_counts": _clip_counts(details),
        "attempt_inventory": _attempt_inventory(config, output_root),
    }


def _verify_csv_semantics(
    path: Path, fields: Sequence[str], expected_rows: Sequence[Mapping[str, Any]]
) -> None:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            observed = list(reader)
    except OSError as error:
        raise CampaignReportError(f"cannot read report CSV {path}: {error}") from error
    expected = [
        {field: serialize_cell(row.get(field)) for field in fields} for row in expected_rows
    ]
    if header != tuple(fields) or observed != expected:
        raise CampaignReportError(f"report CSV semantic drift: {path.name}")


def run_report(config: CampaignConfig, output_root: Path) -> dict[str, Any]:
    barrier = verify_barrier(config, output_root)
    stage = output_root / "report"
    if stage.exists():
        raise CampaignReportError(f"report stage already exists: {stage}")
    inputs = load_inputs(config)
    criteria, recomputation = _criterion_receipts(config, inputs, output_root)
    labels = read_target_labels(inputs)
    quotes = load_quotes(config, inputs)
    details = [
        _year_detail(
            year,
            read_forecasts(output_root / "forecast" / "forecasts" / f"{year}.csv", year),
            inputs,
            quotes,
            labels,
        )
        for year in config.target_years
    ]
    priced_rows, priced_summary = _priced_summary(details)
    annual_rows: list[dict[str, Any]] = []
    for detail in details:
        for contrast in CONTRASTS:
            annual_rows.append(
                {
                    "season": detail["year"],
                    "contrast": contrast,
                    "paired_rows": len(detail["keys"]),
                    "membership_sha256": detail["membership_sha256"],
                    "mean_log_loss_delta": float(np.mean(detail["deltas"][contrast])),
                    "mean_brier_delta": float(np.mean(detail["brier_deltas"][contrast])),
                }
            )
    summaries: dict[str, Any] = {}
    for contrast in CONTRASTS:
        annual = [row for row in annual_rows if row["contrast"] == contrast]
        all_values = np.concatenate([detail["deltas"][contrast] for detail in details])
        all_brier = np.concatenate([detail["brier_deltas"][contrast] for detail in details])
        summaries[contrast] = {
            "paired_rows": int(sum(row["paired_rows"] for row in annual)),
            "equal_year_mean_log_loss_delta": float(
                np.mean([row["mean_log_loss_delta"] for row in annual])
            ),
            "match_weighted_log_loss_delta": float(np.mean(all_values)),
            "equal_year_mean_brier_delta": float(
                np.mean([row["mean_brier_delta"] for row in annual])
            ),
            "match_weighted_brier_delta": float(np.mean(all_brier)),
            "years_negative": int(sum(row["mean_log_loss_delta"] < 0.0 for row in annual)),
        }
    bootstrap_values, bootstrap_inventory = _bootstrap(
        details,
        replicates=config.document["settings"]["report"]["bootstrap"]["replicates"],
        seed=config.document["settings"]["report"]["bootstrap"]["seed"],
    )
    lower, upper = (
        float(np.quantile(bootstrap_values, 0.025, method="linear")),
        float(np.quantile(bootstrap_values, 0.975, method="linear")),
    )
    primary = summaries["S3_minus_S0"]
    nomination = config.document["settings"]["report"]["nomination"]
    population_complete = len(config.target_years) == nomination["required_years"]
    recommendation_eligible = bool(
        population_complete
        and primary["equal_year_mean_log_loss_delta"] <= nomination["maximum_equal_year_delta"]
        and primary["years_negative"] >= nomination["minimum_negative_years"]
        and upper < 0.0
    )
    summary = {
        "schema_version": 1,
        "campaign_id": config.document["campaign_id"],
        "tour": config.tour,
        "population": {
            "years": list(config.target_years),
            "paired_rows": sum(len(detail["keys"]) for detail in details),
            "per_year": bootstrap_inventory,
            "annual_equal_year_degrees_of_freedom": len(config.target_years) - 1,
        },
        "primary": {
            "contrast": "S3_minus_S0",
            **primary,
            "edition_bootstrap_95_percentile": {
                "lower": lower,
                "upper": upper,
                "replicates": len(bootstrap_values),
                "seed": config.document["settings"]["report"]["bootstrap"]["seed"],
                "quantile_method": "linear",
                "models_refit": False,
                "stack_coefficients_refit": False,
                "conditional_limit": "saved forecasts; fitting and selection uncertainty excluded",
                "WTA_interval_label": (
                    "new WTA campaign edition interval; not the original WTA01 interval"
                    if config.tour == "WTA"
                    else None
                ),
            },
        },
        "secondary": {name: summaries[name] for name in CONTRASTS if name != "S3_minus_S0"},
        "priced_descriptive": priced_summary,
        "full_sports_probability_clip_counts": {
            model: int(
                sum(detail["model_scores"][model]["probability_clip_count"] for detail in details)
            )
            for model in MODELS
        },
        "nomination_screen": {
            "applicable_to_complete_reviewed_population": population_complete,
            "eligible_for_documented_later_manual_prospective_design": recommendation_eligible,
            "candidate": "S3_only",
            "automatic_promotion": False,
            "prospective_evidence_established": False,
        },
        "limitations": [
            "exposed historical development populations, not a new held-out window",
            "conditional bootstrap excludes model fitting and selection uncertainty",
            "annual signs are correlated robustness evidence, not independent replications",
            "passing arithmetic and integrity checks does not establish scientific validity",
            "primary population is historically market-source-conditioned",
            "quote clocks are unequal or unresolved; market comparisons are descriptive only",
            "raw decimal quotes were validated and normalized only after the barrier",
        ],
    }
    stage.mkdir(parents=True)
    artifacts = []
    annual_path = stage / "annual.csv"
    atomic_csv(
        annual_path,
        (
            "season",
            "contrast",
            "paired_rows",
            "membership_sha256",
            "mean_log_loss_delta",
            "mean_brier_delta",
        ),
        annual_rows,
    )
    artifacts.append(
        typed_artifact(
            annual_path,
            schema="campaign_annual_scores/v1",
            logical_key={"role": "annual_scores"},
            root=output_root,
        )
    )
    bootstrap_path = stage / "bootstrap.csv"
    atomic_csv(
        bootstrap_path,
        ("replicate", "primary_log_loss_delta"),
        [
            {"replicate": index, "primary_log_loss_delta": float(value)}
            for index, value in enumerate(bootstrap_values)
        ],
    )
    artifacts.append(
        typed_artifact(
            bootstrap_path,
            schema="campaign_bootstrap/v1",
            logical_key={"role": "bootstrap"},
            root=output_root,
        )
    )
    calibration_path = stage / "calibration.csv"
    atomic_csv(
        calibration_path,
        ("scope", "model", "bin", "lower", "upper", "n", "mean_prediction", "outcome_rate"),
        _calibration_rows(details),
    )
    artifacts.append(
        typed_artifact(
            calibration_path,
            schema="campaign_calibration/v1",
            logical_key={"role": "calibration"},
            root=output_root,
        )
    )
    priced_path = stage / "priced.csv"
    atomic_csv(
        priced_path,
        (
            "season",
            "model",
            "priced_rows",
            "full_sports_rows",
            "mean_log_loss",
            "mean_brier",
            "probability_clip_count",
        ),
        priced_rows,
    )
    artifacts.append(
        typed_artifact(
            priced_path,
            schema="campaign_priced_scores/v1",
            logical_key={"role": "priced_scores"},
            root=output_root,
        )
    )
    criteria_path = stage / "fit_criteria.json"
    atomic_json(criteria_path, criteria)
    artifacts.append(
        typed_artifact(
            criteria_path,
            schema="campaign_fit_criteria/v1",
            logical_key={"role": "fit_criteria"},
            root=output_root,
        )
    )
    summary_path = stage / "summary.json"
    atomic_json(summary_path, summary)
    artifacts.append(
        typed_artifact(
            summary_path,
            schema="campaign_summary/v1",
            logical_key={"role": "summary"},
            root=output_root,
        )
    )
    report_lines = [
        f"# {config.document['campaign_id']} — {config.tour}",
        "",
        "Primary: S3 minus unchanged S0 on the exact paired sports population.",
        "",
        f"- Equal-year log-loss delta: {primary['equal_year_mean_log_loss_delta']:.4f}",
        f"- 95% edition-bootstrap interval: [{lower:.4f}, {upper:.4f}]",
        f"- Negative annual deltas: {primary['years_negative']}/{len(config.target_years)}",
        "- Automatic promotion: no",
        "",
        "Secondary arms remain visible in summary.json: S1−S0, S2−S0, and S3−S2.",
        "Passing this reporter does not establish prospective evidence or scientific validity.",
        "The historical sports population is market-source-conditioned.",
        "Quote clocks are unequal or unresolved; quoted-market comparisons are descriptive.",
    ]
    report_path = stage / "report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    artifacts.append(
        typed_artifact(
            report_path,
            schema="campaign_short_report/v1",
            logical_key={"role": "short_report"},
            root=output_root,
        )
    )
    exposure_path = stage / "exposure.json"
    atomic_json(
        exposure_path,
        {
            "stage": "report",
            "barrier_verified_before_target_read": True,
            "quotes_read_and_normalized_post_barrier": True,
            "raw_quotes_sha256": quotes.binding.sha256,
            "target_outcomes_read_and_scored": True,
            "target_rows": sum(len(detail["keys"]) for detail in details),
            "target_membership_sha256": key_hash(
                tuple(key for detail in details for key in detail["keys"])
            ),
            "historical_population_is_already_exposed": True,
            "prospective_evidence_created": False,
        },
    )
    artifacts.append(
        typed_artifact(
            exposure_path,
            schema="campaign_report_exposure/v1",
            logical_key={"role": "exposure"},
            root=output_root,
        )
    )
    extra_documents = (
        (
            "recomputation.json",
            {"schema": "campaign_recomputation/v1", "years": recomputation},
            "campaign_recomputation/v1",
            "recomputation",
        ),
        (
            "sensitivities.json",
            _score_only_sensitivities(details),
            "campaign_sensitivities/v1",
            "sensitivities",
        ),
        (
            "clip_counts.json",
            _clip_counts(details),
            "campaign_clip_counts/v1",
            "clip_counts",
        ),
        (
            "attempt_inventory.json",
            _attempt_inventory(config, output_root),
            "campaign_attempt_inventory/v1",
            "attempts",
        ),
    )
    for name, document, schema, role in extra_documents:
        path = stage / name
        atomic_json(path, document)
        artifacts.append(
            typed_artifact(path, schema=schema, logical_key={"role": role}, root=output_root)
        )
    observed_inventory = [
        {
            "path": item["path"],
            "schema": item["schema"],
            "logical_key": item["logical_key"],
            "media_type": item["media_type"],
        }
        for item in artifacts
    ]
    if observed_inventory != report_inventory_contract():
        raise CampaignReportError("report inventory differs from fixed stage-role contract")
    manifest = {
        "schema": REPORT_COMPLETION_SCHEMA,
        "status": "complete",
        "stage": "report",
        **config_receipt(config),
        "barrier_manifest_sha256": sha256(output_root / "barrier" / "barrier_manifest.json"),
        "forecast_tree_sha256": barrier["forecast_tree_sha256"],
        "artifacts": artifacts,
        "inventory_sha256": inventory_sha256(artifacts),
        "attempt_id": config.document["attempt_id"],
        "target_outcomes_read_and_scored_post_barrier": True,
        "primary_contrast": "S3_minus_S0",
        "automatic_promotion": False,
    }
    manifest_path = stage / "report_manifest.json"
    atomic_json(manifest_path, manifest)
    manifest["report_manifest_sha256"] = sha256(manifest_path)
    return manifest


def verify_report(config: CampaignConfig, output_root: Path) -> dict[str, Any] | None:
    stage = output_root / "report"
    path = stage / "report_manifest.json"
    if not path.exists():
        if stage.exists():
            raise CampaignReportError("report stage exists without a typed completion")
        return None
    barrier = verify_barrier(config, output_root)
    document = read_object(path, label="report completion")
    require_completion(document, schema=REPORT_COMPLETION_SCHEMA, stage="report")
    if document.get("config_sha256") != config.sha256:
        raise CampaignReportError("report completion/config binding drift")
    if document.get("barrier_manifest_sha256") != sha256(
        output_root / "barrier" / "barrier_manifest.json"
    ):
        raise CampaignReportError("report completion/barrier binding drift")
    if document.get("forecast_tree_sha256") != barrier["forecast_tree_sha256"]:
        raise CampaignReportError("report completion/forecast tree binding drift")
    if document.get("attempt_id") != config.document["attempt_id"]:
        raise CampaignReportError("report completion attempt drift")
    for field, expected in config_receipt(config).items():
        if document.get(field) != expected:
            raise CampaignReportError(f"report completion {field} binding drift")
    if (
        document.get("target_outcomes_read_and_scored_post_barrier") is not True
        or document.get("primary_contrast") != "S3_minus_S0"
        or document.get("automatic_promotion") is not False
    ):
        raise CampaignReportError("report completion semantic status drift")
    try:
        records = validate_typed_inventory(
            document.get("artifacts"),
            root=output_root,
            inventory_root=output_root / "report",
            expected=_expected_report_inventory(config),
            label="report completion",
            ignored_paths=("report/report_manifest.json",),
        )
    except ValueError as error:
        raise CampaignReportError(str(error)) from error
    if document.get("inventory_sha256") != inventory_sha256(records):
        raise CampaignReportError("report completion inventory commitment drift")
    inputs = load_inputs(config)
    materials = _report_materials(config, inputs, output_root)
    csv_contracts = (
        (
            "annual.csv",
            (
                "season",
                "contrast",
                "paired_rows",
                "membership_sha256",
                "mean_log_loss_delta",
                "mean_brier_delta",
            ),
            "annual_rows",
        ),
        (
            "bootstrap.csv",
            ("replicate", "primary_log_loss_delta"),
            "bootstrap_rows",
        ),
        (
            "calibration.csv",
            (
                "scope",
                "model",
                "bin",
                "lower",
                "upper",
                "n",
                "mean_prediction",
                "outcome_rate",
            ),
            "calibration_rows",
        ),
        (
            "priced.csv",
            (
                "season",
                "model",
                "priced_rows",
                "full_sports_rows",
                "mean_log_loss",
                "mean_brier",
                "probability_clip_count",
            ),
            "priced_rows",
        ),
    )
    for name, fields, material in csv_contracts:
        _verify_csv_semantics(
            output_root / "report" / name,
            fields,
            materials[material],
        )
    json_contracts = {
        "fit_criteria.json": "criteria",
        "summary.json": "summary",
        "exposure.json": "exposure",
        "recomputation.json": "recomputation",
        "sensitivities.json": "sensitivities",
        "clip_counts.json": "clip_counts",
        "attempt_inventory.json": "attempt_inventory",
    }
    for name, material in json_contracts.items():
        if (
            read_object(output_root / "report" / name, label=f"report {name}")
            != materials[material]
        ):
            raise CampaignReportError(f"report JSON semantic drift: {name}")
    if (output_root / "report" / "report.md").read_text(encoding="utf-8") != materials[
        "report_text"
    ]:
        raise CampaignReportError("report markdown semantic drift")
    return document
