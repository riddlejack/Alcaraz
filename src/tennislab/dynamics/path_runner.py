"""Thin chronological point-path and past-only selection harness for SR02.

Ported from the archive's ``references/SR02_models/path_runner.py`` (the revision
``experiments/SR02-C1.json`` binds by hash). The real-data CLI refuses the unfrozen
candidate configuration; public functions are exercised with synthetic fixtures in
``tests/test_dynamics_path_runner.py``.

What changed in the port: the repository root computed from the source file is gone and
every configured path resolves through the declared workspace (``resolve_under_root``);
the hashing and JSON helpers come from ``tennislab.chain.common``; errors are
:class:`DynamicsError`. The candidate checkpoint CSV keeps its own writer because it
uses ``\n`` line ends where the chain's ``atomic_csv`` uses ``\r\n``. Arithmetic,
iteration order and serialization are as in the archive.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    atomic_json,
    canonical_hash,
    relative_to_root,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
)
from tennislab.dynamics.dynamic import (
    SOURCE_ROW_FIELDS,
    DynamicConfig,
    DynamicsError,
    DynamicServeReturnFilter,
    HistoryObservation,
    MatchRule,
    TargetMatch,
    UnadjustedRateBaseline,
    match_win_probability,
    observation_from_source_row,
)

canonical_json_hash = canonical_hash
LOSS_FIELDS = (
    "candidate_family",
    "candidate_id",
    "match_id",
    "match_date",
    "source_season",
    "service_points",
    "negative_log_likelihood",
    "contests_used",
)
TRIAL_FIELDS = (
    "candidate_family",
    "selection_year",
    "candidate_id",
    "selection_start",
    "selection_cutoff",
    "calendar_year_point_counts",
    "mean_equal_year_point_log_loss",
    "status",
)
SELECTION_FIELDS = (
    "candidate_family",
    "selection_year",
    "selected_candidate_id",
    "selection_start",
    "selection_cutoff",
    "selection_reason",
)
SELECTED_MATCH_FIELDS = (
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
    "selected_dynamic_id",
    "selected_unadjusted_id",
    "dynamic_p_a_serve",
    "dynamic_p_b_serve",
    "unadjusted_p_a_serve",
    "unadjusted_p_b_serve",
    "dynamic_match_probability_a",
    "unadjusted_match_probability_a",
    "simple_unadjusted_match_probability_a",
    "dynamic_a_logit_variance",
    "dynamic_b_logit_variance",
    "dynamic_a_b_logit_covariance",
    "dynamic_a_serve_unseen",
    "dynamic_a_return_unseen",
    "dynamic_a_surface_unseen",
    "dynamic_b_serve_unseen",
    "dynamic_b_return_unseen",
    "dynamic_b_surface_unseen",
    "dynamic_a_serve_point_observations",
    "dynamic_a_return_point_observations",
    "dynamic_a_surface_point_observations",
    "dynamic_b_serve_point_observations",
    "dynamic_b_return_point_observations",
    "dynamic_b_surface_point_observations",
)


PATH_FIELDS = (
    "match_id",
    "match_date",
    "source_season",
    "source_key",
    "tourney_id",
    "surface",
    "best_of",
    "player_a",
    "player_b",
    "candidate_family",
    "candidate_id",
    "p_a_serve",
    "p_b_serve",
    "simple_p_a_serve",
    "simple_p_b_serve",
    "a_logit_variance",
    "b_logit_variance",
    "a_b_logit_covariance",
    "a_serve_unseen",
    "a_return_unseen",
    "a_surface_unseen",
    "b_serve_unseen",
    "b_return_unseen",
    "b_surface_unseen",
    "a_serve_point_observations",
    "a_return_point_observations",
    "a_surface_point_observations",
    "b_serve_point_observations",
    "b_return_point_observations",
    "b_surface_point_observations",
    "surface_mean_unseen",
    "tournament_unseen",
    "a_server_overall_denominator",
    "a_server_surface_denominator",
    "b_returner_overall_denominator",
    "b_returner_surface_denominator",
    "b_server_overall_denominator",
    "b_server_surface_denominator",
    "a_returner_overall_denominator",
    "a_returner_surface_denominator",
    "latest_source_date",
)


@dataclass(frozen=True)
class PathTarget:
    match: TargetMatch
    source_season: int
    source_key: str

    def __post_init__(self) -> None:
        if self.source_season <= 0 or not self.source_key:
            raise DynamicsError("path target requires source season/key audit metadata")


def _sorted_inputs(
    observations: Iterable[HistoryObservation], targets: Iterable[PathTarget]
) -> tuple[list[HistoryObservation], list[PathTarget]]:
    history = sorted(observations, key=lambda row: (row.match_date, row.match_id))
    target_rows = sorted(targets, key=lambda row: (row.match.match_date, row.match.match_id))
    if len({row.match_id for row in history}) != len(history):
        raise DynamicsError("duplicate history match_id")
    if len({row.match.match_id for row in target_rows}) != len(target_rows):
        raise DynamicsError("duplicate target match_id")
    return history, target_rows


def _advance_dynamic(
    model: DynamicServeReturnFilter,
    history: Sequence[HistoryObservation],
    cursor: int,
    cutoff: dt.date,
    solver_summary: dict[str, Any] | None = None,
) -> int:
    while cursor < len(history) and history[cursor].match_date <= cutoff:
        source_date = history[cursor].match_date
        end = cursor + 1
        while end < len(history) and history[end].match_date == source_date:
            end += 1
        batch = history[cursor:end]
        eligible = [item for item in batch if item.history_eligible]
        try:
            model.apply_batch(batch)
        except Exception as error:
            if solver_summary is not None:
                solver_summary.update(
                    {
                        "status": "failed",
                        "failure_source_date": source_date.isoformat(),
                        "failure_error_type": type(error).__name__,
                        "failure_error": str(error),
                    }
                )
            raise
        if eligible and solver_summary is not None:
            acceptance = model.last_solver_acceptance
            if acceptance not in {"maximum_gradient", "newton_decrement"}:
                raise DynamicsError("dynamic batch has no registered solver acceptance")
            counts = solver_summary["acceptance_counts"]
            counts[acceptance] = int(counts[acceptance]) + 1
            solver_summary["batch_count"] = int(solver_summary["batch_count"]) + 1
            solver_summary["eligible_rows"] = int(solver_summary["eligible_rows"]) + len(eligible)
            solver_summary["service_contests"] = int(solver_summary["service_contests"]) + sum(
                int(item.service_a is not None) + int(item.service_b is not None)
                for item in eligible
            )
            solver_summary["service_points"] = int(solver_summary["service_points"]) + sum(
                (item.service_a.points_played if item.service_a is not None else 0)
                + (item.service_b.points_played if item.service_b is not None else 0)
                for item in eligible
            )
            solver_summary["maximum_iterations"] = max(
                int(solver_summary["maximum_iterations"]), model.last_solver_iterations
            )
            solver_summary["maximum_absolute_gradient"] = max(
                float(solver_summary["maximum_absolute_gradient"]), model.last_solver_max_gradient
            )
            solver_summary["maximum_newton_decrement"] = max(
                float(solver_summary["maximum_newton_decrement"]),
                model.last_solver_newton_decrement,
            )
        cursor = end
    return cursor


def dynamic_point_path(
    observations: Iterable[HistoryObservation],
    targets: Iterable[PathTarget],
    config: DynamicConfig,
    candidate_id: str,
    *,
    lag_days: int = 2,
    solver_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not candidate_id or lag_days < 0:
        raise DynamicsError("candidate ID is required and lag must be nonnegative")
    history, target_rows = _sorted_inputs(observations, targets)
    model = DynamicServeReturnFilter(config)
    if solver_summary is not None:
        solver_summary.clear()
        solver_summary.update(
            {
                "status": "in_progress",
                "candidate_family": "dynamic",
                "candidate_id": candidate_id,
                "batch_count": 0,
                "eligible_rows": 0,
                "service_contests": 0,
                "service_points": 0,
                "acceptance_counts": {"maximum_gradient": 0, "newton_decrement": 0},
                "maximum_iterations": 0,
                "maximum_absolute_gradient": 0.0,
                "maximum_newton_decrement": 0.0,
                "failure_source_date": "",
                "failure_error_type": "",
                "failure_error": "",
            }
        )
    cursor = 0
    output: list[dict[str, Any]] = []
    for record in target_rows:
        target = record.match
        cutoff = target.match_date - dt.timedelta(days=lag_days)
        cursor = _advance_dynamic(model, history, cursor, cutoff, solver_summary)
        a = model.point_prediction(
            target.player_a, target.player_b, target.surface, target.tourney_id, target.match_date
        )
        b = model.point_prediction(
            target.player_b, target.player_a, target.surface, target.tourney_id, target.match_date
        )
        covariance = model.point_logit_covariance(
            target.player_a,
            target.player_b,
            target.player_b,
            target.player_a,
            target.surface,
            target.tourney_id,
            target.match_date,
        )
        latest = model.latest_source_date
        if latest is not None and latest > cutoff:
            raise DynamicsError("dynamic source date exceeds target cutoff")
        row = _path_row(
            record,
            "dynamic",
            candidate_id,
            float(a["probability"]),
            float(b["probability"]),
            None,
            None,
            float(a["latent_variance_diagonal"]),
            float(b["latent_variance_diagonal"]),
            covariance,
            latest,
        )
        state_a = model.state_summary(target.player_a, target.surface, target.match_date)
        state_b = model.state_summary(target.player_b, target.surface, target.match_date)
        population = model.population_summary(target.surface, target.tourney_id, target.match_date)
        for side, state in (("a", state_a), ("b", state_b)):
            for role in ("serve", "return", "surface"):
                row[f"{side}_{role}_unseen"] = state[f"{role}_unseen"]
                row[f"{side}_{role}_point_observations"] = state[f"{role}_point_observations"]
        row["surface_mean_unseen"] = population["surface_mean_unseen"]
        row["tournament_unseen"] = population["tournament_unseen"]
        output.append(row)
    if solver_summary is not None:
        solver_summary["status"] = "complete"
    return output


def control_point_path(
    observations: Iterable[HistoryObservation],
    targets: Iterable[PathTarget],
    candidate_id: str,
    *,
    half_life_days: float,
    overall_prior_units: float,
    surface_prior_units: float,
    initial_serve_probability: float,
    lag_days: int = 2,
) -> list[dict[str, Any]]:
    if not candidate_id or lag_days < 0:
        raise DynamicsError("candidate ID is required and lag must be nonnegative")
    history, target_rows = _sorted_inputs(observations, targets)
    model = UnadjustedRateBaseline(
        half_life_days, overall_prior_units, surface_prior_units, initial_serve_probability
    )
    cursor = 0
    output: list[dict[str, Any]] = []
    for record in target_rows:
        target = record.match
        cutoff = target.match_date - dt.timedelta(days=lag_days)
        model.advance(target.match_date)
        while cursor < len(history) and history[cursor].match_date <= cutoff:
            model.add_observation(history[cursor])
            cursor += 1
        a = model.point_prediction(target.player_a, target.player_b, target.surface)
        b = model.point_prediction(target.player_b, target.player_a, target.surface)
        latest = model.latest_source_date
        if latest is not None and latest > cutoff:
            raise DynamicsError("control source date exceeds target cutoff")
        row = _path_row(
            record,
            "control",
            candidate_id,
            float(a["probability"]),
            float(b["probability"]),
            float(a["simple_probability_mean"]),
            float(b["simple_probability_mean"]),
            None,
            None,
            None,
            latest,
        )
        row.update(
            {
                "a_server_overall_denominator": a["server_overall_denominator"],
                "a_server_surface_denominator": a["server_surface_denominator"],
                "b_returner_overall_denominator": a["returner_overall_denominator"],
                "b_returner_surface_denominator": a["returner_surface_denominator"],
                "b_server_overall_denominator": b["server_overall_denominator"],
                "b_server_surface_denominator": b["server_surface_denominator"],
                "a_returner_overall_denominator": b["returner_overall_denominator"],
                "a_returner_surface_denominator": b["returner_surface_denominator"],
            }
        )
        output.append(row)
    return output


def _path_row(
    record: PathTarget,
    family: str,
    candidate_id: str,
    p_a: float,
    p_b: float,
    simple_a: float | None,
    simple_b: float | None,
    variance_a: float | None,
    variance_b: float | None,
    covariance: float | None,
    latest: dt.date | None,
) -> dict[str, Any]:
    for value in (p_a, p_b, simple_a, simple_b):
        if value is not None and (not math.isfinite(value) or not 0.0 < value < 1.0):
            raise DynamicsError("candidate point probability is invalid")
    target = record.match
    return {
        "match_id": target.match_id,
        "match_date": target.match_date.isoformat(),
        "source_season": record.source_season,
        "source_key": record.source_key,
        "tourney_id": target.tourney_id,
        "surface": target.surface,
        "best_of": target.best_of,
        "player_a": target.player_a,
        "player_b": target.player_b,
        "candidate_family": family,
        "candidate_id": candidate_id,
        "p_a_serve": p_a,
        "p_b_serve": p_b,
        "simple_p_a_serve": simple_a,
        "simple_p_b_serve": simple_b,
        "a_logit_variance": variance_a,
        "b_logit_variance": variance_b,
        "a_b_logit_covariance": covariance,
        "latest_source_date": latest.isoformat() if latest is not None else "",
    }


def point_loss_rows(
    path_rows: Iterable[Mapping[str, Any]],
    observations: Mapping[str, HistoryObservation],
) -> list[dict[str, Any]]:
    output = []
    for path in path_rows:
        item = observations[path["match_id"]]
        if not item.history_eligible:
            continue
        loss = 0.0
        points = 0
        contests = 0
        for line, field in ((item.service_a, "p_a_serve"), (item.service_b, "p_b_serve")):
            if line is None:
                continue
            probability = float(path[field])
            loss -= line.points_won * math.log(probability)
            loss -= (line.points_played - line.points_won) * math.log1p(-probability)
            points += line.points_played
            contests += 1
        if points <= 0:
            raise DynamicsError("eligible history row has no point-loss contest")
        output.append(
            {
                "candidate_family": path["candidate_family"],
                "candidate_id": path["candidate_id"],
                "match_id": item.match_id,
                "match_date": item.match_date.isoformat(),
                "source_season": path["source_season"],
                "service_points": points,
                "negative_log_likelihood": loss,
                "contests_used": contests,
            }
        )
    return output


def select_family(
    losses_by_candidate: Mapping[str, Sequence[Mapping[str, Any]]],
    tie_ranks: Mapping[str, tuple[Any, ...]],
    *,
    selection_years: Iterable[int],
    fallback_candidate_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if set(losses_by_candidate) != set(tie_ranks):
        raise DynamicsError("candidate loss/tie-rank membership differs")
    if fallback_candidate_id not in losses_by_candidate:
        raise DynamicsError("fallback candidate missing")
    reference_membership: dict[str, tuple[str, int, int, int]] | None = None
    for candidate_id, rows in losses_by_candidate.items():
        membership: dict[str, tuple[str, int, int, int]] = {}
        for row in rows:
            match_id = str(row["match_id"])
            if match_id in membership:
                raise DynamicsError(f"duplicate candidate loss key: {candidate_id}/{match_id}")
            membership[match_id] = (
                str(row["match_date"]),
                int(row["source_season"]),
                int(row["service_points"]),
                int(row["contests_used"]),
            )
        if reference_membership is None:
            reference_membership = membership
        elif membership != reference_membership:
            raise DynamicsError("candidate loss key or denominator membership differs")
    trials: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    for year in selection_years:
        start = dt.date(year - 3, 1, 1)
        cutoff = dt.date(year, 1, 1) - dt.timedelta(days=2)
        scored: list[tuple[float, tuple[Any, ...], str]] = []
        incomplete = False
        for candidate_id, rows in losses_by_candidate.items():
            totals = {value: [0.0, 0] for value in range(year - 3, year)}
            for row in rows:
                date = dt.date.fromisoformat(str(row["match_date"]))
                if start <= date <= cutoff:
                    bucket = totals[date.year]
                    bucket[0] += float(row["negative_log_likelihood"])
                    bucket[1] += int(row["service_points"])
            year_losses = [
                totals[value][0] / totals[value][1] for value in totals if totals[value][1] > 0
            ]
            complete = len(year_losses) == 3
            score = sum(year_losses) / 3.0 if complete else None
            trials.append(
                {
                    "selection_year": year,
                    "candidate_id": candidate_id,
                    "selection_start": start.isoformat(),
                    "selection_cutoff": cutoff.isoformat(),
                    "calendar_year_point_counts": json.dumps(
                        {key: value[1] for key, value in totals.items()}, sort_keys=True
                    ),
                    "mean_equal_year_point_log_loss": score,
                    "status": "eligible" if complete else "inadequate_validation_coverage",
                }
            )
            if complete:
                if not math.isfinite(float(score)):
                    raise DynamicsError("nonfinite candidate selection score")
                scored.append((float(score), tie_ranks[candidate_id], candidate_id))
            else:
                incomplete = True
        if incomplete:
            selected = fallback_candidate_id
            reason = "inadequate_validation_coverage"
        else:
            best_score = min(value[0] for value in scored)
            tied = [value for value in scored if value[0] <= best_score + 1e-10]
            selected = min(tied, key=lambda value: (value[1], value[2]))[2]
            reason = "minimum_equal_year_point_log_loss"
        selections.append(
            {
                "selection_year": year,
                "selected_candidate_id": selected,
                "selection_start": start.isoformat(),
                "selection_cutoff": cutoff.isoformat(),
                "selection_reason": reason,
            }
        )
    return selections, trials


def selected_match_predictions(
    family: str,
    candidate_paths: Mapping[str, Sequence[Mapping[str, Any]]],
    selections: Sequence[Mapping[str, Any]],
    targets: Iterable[PathTarget],
) -> list[dict[str, Any]]:
    selected = {int(row["selection_year"]): str(row["selected_candidate_id"]) for row in selections}
    rows_by_candidate = {
        candidate: {str(row["match_id"]): row for row in rows}
        for candidate, rows in candidate_paths.items()
    }
    output = []
    for record in sorted(targets, key=lambda row: (row.match.match_date, row.match.match_id)):
        target = record.match
        year = target.match_date.year
        if year not in selected:
            continue
        candidate_id = selected[year]
        row = rows_by_candidate[candidate_id][target.match_id]
        if target.rule is None:
            primary_match = simple_match = None
        else:
            primary_match = match_win_probability(
                float(row["p_a_serve"]), float(row["p_b_serve"]), target.rule
            )
            simple_match = None
            if row.get("simple_p_a_serve") not in (None, "") and row.get(
                "simple_p_b_serve"
            ) not in (None, ""):
                simple_match = match_win_probability(
                    float(row["simple_p_a_serve"]), float(row["simple_p_b_serve"]), target.rule
                )
        output.append(
            {
                "match_id": target.match_id,
                "match_date": target.match_date.isoformat(),
                "source_season": record.source_season,
                "source_key": record.source_key,
                "tourney_id": target.tourney_id,
                "surface": target.surface,
                "best_of": target.best_of,
                "player_a": target.player_a,
                "player_b": target.player_b,
                "candidate_family": family,
                "selected_candidate_id": candidate_id,
                "p_a_serve": row["p_a_serve"],
                "p_b_serve": row["p_b_serve"],
                "match_probability_a": primary_match,
                "simple_match_probability_a": simple_match,
                "a_logit_variance": row.get("a_logit_variance"),
                "b_logit_variance": row.get("b_logit_variance"),
                "a_b_logit_covariance": row.get("a_b_logit_covariance"),
                "a_serve_unseen": row.get("a_serve_unseen"),
                "a_return_unseen": row.get("a_return_unseen"),
                "a_surface_unseen": row.get("a_surface_unseen"),
                "b_serve_unseen": row.get("b_serve_unseen"),
                "b_return_unseen": row.get("b_return_unseen"),
                "b_surface_unseen": row.get("b_surface_unseen"),
                "a_serve_point_observations": row.get("a_serve_point_observations"),
                "a_return_point_observations": row.get("a_return_point_observations"),
                "a_surface_point_observations": row.get("a_surface_point_observations"),
                "b_serve_point_observations": row.get("b_serve_point_observations"),
                "b_return_point_observations": row.get("b_return_point_observations"),
                "b_surface_point_observations": row.get("b_surface_point_observations"),
                "annual_target_eligible": int(record.source_season == year and year >= 2012),
                "rule_status": "provided" if target.rule is not None else "missing",
            }
        )
    return output


def merge_selected_matches(
    dynamic_rows: Sequence[Mapping[str, Any]],
    control_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    dynamic = {str(row["match_id"]): row for row in dynamic_rows}
    control = {str(row["match_id"]): row for row in control_rows}
    if (
        len(dynamic) != len(dynamic_rows)
        or len(control) != len(control_rows)
        or set(dynamic) != set(control)
    ):
        raise DynamicsError("selected dynamic/control match membership differs")
    metadata = (
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
    )
    output = []
    for match_id in sorted(dynamic, key=lambda key: (str(dynamic[key]["match_date"]), key)):
        left, right = dynamic[match_id], control[match_id]
        if any(str(left[field]) != str(right[field]) for field in metadata):
            raise DynamicsError(f"selected match metadata differs: {match_id}")
        row = {field: left[field] for field in ("match_id", *metadata)}
        row.update(
            {
                "selected_dynamic_id": left["selected_candidate_id"],
                "selected_unadjusted_id": right["selected_candidate_id"],
                "dynamic_p_a_serve": left["p_a_serve"],
                "dynamic_p_b_serve": left["p_b_serve"],
                "unadjusted_p_a_serve": right["p_a_serve"],
                "unadjusted_p_b_serve": right["p_b_serve"],
                "dynamic_match_probability_a": left["match_probability_a"],
                "unadjusted_match_probability_a": right["match_probability_a"],
                "simple_unadjusted_match_probability_a": right["simple_match_probability_a"],
            }
        )
        for field in (
            "a_logit_variance",
            "b_logit_variance",
            "a_b_logit_covariance",
            "a_serve_unseen",
            "a_return_unseen",
            "a_surface_unseen",
            "b_serve_unseen",
            "b_return_unseen",
            "b_surface_unseen",
            "a_serve_point_observations",
            "a_return_point_observations",
            "a_surface_point_observations",
            "b_serve_point_observations",
            "b_return_point_observations",
            "b_surface_point_observations",
        ):
            row[f"dynamic_{field}"] = left[field]
        output.append(row)
    if any("a_won" in row or "PS_decimal_a" in row for row in output):
        raise DynamicsError("label or market field entered selected prediction file")
    return output


def _serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DynamicsError("cannot serialize nonfinite float")
        return format(value, ".17g")
    return str(value)


def _atomic_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(
            destination, fieldnames=fields, extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _serialize(row.get(field)) for field in fields})
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)


def checkpoint_candidate_path(
    directory: Path,
    binding: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    solver_summary: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, str]], str]:
    loaded = load_candidate_checkpoint(directory, binding)
    if loaded is not None:
        return loaded, "reused"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "point_forecasts.csv"
    manifest_path = directory / "checkpoint.json"
    summary_path = directory / "solver_summary.json"
    normalized_binding = json.loads(json.dumps(binding, sort_keys=True))
    binding_hash = canonical_json_hash(normalized_binding)
    if binding.get("candidate_family") == "dynamic":
        if solver_summary is None or solver_summary.get("status") != "complete":
            raise DynamicsError("dynamic checkpoint requires a complete solver summary")
    _atomic_csv(path, PATH_FIELDS, rows)
    if binding.get("candidate_family") == "dynamic":
        atomic_json(summary_path, solver_summary)
    manifest = {
        "binding": normalized_binding,
        "binding_sha256": binding_hash,
        "point_forecasts_sha256": sha256(path),
        "rows": len(rows),
        "status": "complete",
    }
    if binding.get("candidate_family") == "dynamic":
        manifest["solver_summary_sha256"] = sha256(summary_path)
    temporary = manifest_path.with_suffix(f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as destination:
        json.dump(manifest, destination, indent=2, sort_keys=True)
        destination.write("\n")
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, manifest_path)
    return [dict(row) for row in rows], "written"


def load_candidate_checkpoint(
    directory: Path,
    binding: Mapping[str, Any],
) -> list[dict[str, str]] | None:
    """Return a valid completed path without constructing its model again."""
    path = directory / "point_forecasts.csv"
    manifest_path = directory / "checkpoint.json"
    summary_path = directory / "solver_summary.json"
    failure_path = directory / "failure.json"
    if failure_path.exists():
        raise DynamicsError("candidate has a preserved fatal failure receipt; use a new attempt")
    if not path.exists() and not manifest_path.exists() and not summary_path.exists():
        return None
    if not path.exists() or not manifest_path.exists():
        raise DynamicsError("incomplete candidate checkpoint")
    normalized_binding = json.loads(json.dumps(binding, sort_keys=True))
    binding_hash = canonical_json_hash(normalized_binding)
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest.get("binding_sha256") != binding_hash
        or manifest.get("binding") != normalized_binding
    ):
        raise DynamicsError("candidate checkpoint binding mismatch")
    if sha256(path) != manifest.get("point_forecasts_sha256"):
        raise DynamicsError("candidate checkpoint file hash mismatch")
    with path.open(newline="", encoding="utf-8") as source:
        loaded = list(csv.DictReader(source))
    if len(loaded) != manifest.get("rows"):
        raise DynamicsError("candidate checkpoint row count mismatch")
    if binding.get("candidate_family") == "dynamic":
        if not summary_path.exists():
            raise DynamicsError("incomplete dynamic solver diagnostic checkpoint")
        if sha256(summary_path) != manifest.get("solver_summary_sha256"):
            raise DynamicsError("dynamic solver summary hash mismatch")
        summary = json.loads(summary_path.read_text())
        if (
            summary.get("status") != "complete"
            or summary.get("candidate_id") != binding["candidate"]["candidate_id"]
        ):
            raise DynamicsError("dynamic solver summary identity or status differs")
    elif summary_path.exists():
        raise DynamicsError("unexpected control solver summary")
    return loaded


def _require_frozen(config: Mapping[str, Any], config_path: Path) -> None:
    if config.get("proposal_status") != "frozen_for_real_execution":
        raise DynamicsError("configuration is not frozen for real execution")
    binding = config.get("execution_binding")
    required = {
        "design_path",
        "design_sha256",
        "runner_path",
        "runner_sha256",
        "dynamic_path",
        "dynamic_sha256",
        "column_dictionary_path",
        "column_dictionary_sha256",
    }
    if not isinstance(binding, dict) or set(binding) != required:
        raise DynamicsError("execution_binding fields differ")
    for prefix in ("design", "runner", "dynamic", "column_dictionary"):
        path = resolve_under_root(binding[f"{prefix}_path"], label=f"{prefix} binding")
        if sha256(path) != binding[f"{prefix}_sha256"]:
            raise DynamicsError(f"{prefix} execution hash mismatch")


def _validate_config_contract(config: Mapping[str, Any]) -> None:
    years = config.get("selection_years")
    if not isinstance(years, list) or not years or years != sorted(set(years)):
        raise DynamicsError("selection_years must be a nonempty increasing unique list")
    for name, proposal in (
        ("dynamic", config["hyperparameter_selection_proposal"]),
        ("control", config["unadjusted_baseline"]["selection_proposal"]),
    ):
        menu = proposal.get("candidate_menu")
        if not isinstance(menu, list) or not menu:
            raise DynamicsError(f"{name} candidate menu is empty")
        candidate_ids = [str(item["candidate_id"]) for item in menu]
        if any(not value for value in candidate_ids) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise DynamicsError(f"{name} candidate IDs are blank or duplicated")
        if proposal.get("fallback_candidate_id") not in candidate_ids:
            raise DynamicsError(f"{name} fallback candidate is outside its menu")


def _load_source(config: Mapping[str, Any]) -> tuple[list[HistoryObservation], list[PathTarget]]:
    panel = resolve_under_root(config["input"]["panel_path"], label="panel")
    rules_path = resolve_under_root(
        config["match_conversion"]["rule_mapping_path"], label="rule_mapping"
    )
    if sha256(panel) != config["input"]["panel_sha256"]:
        raise DynamicsError("source panel hash mismatch")
    if sha256(rules_path) != config["match_conversion"]["rule_mapping_sha256"]:
        raise DynamicsError("rule mapping hash mismatch")
    rules: dict[str, tuple[dict[str, str], MatchRule]] = {}
    with rules_path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            key = row["source_key"]
            if key in rules or key != row["match_id"]:
                raise DynamicsError("duplicate or inconsistent rule key")
            rules[key] = (row, MatchRule.from_mapping(json.loads(row["match_rule"])))

    additional = ("source_season", "source_key", "round", "best_of")
    selected_fields = tuple(dict.fromkeys((*SOURCE_ROW_FIELDS, *additional)))
    history_statuses = tuple(config["chronology"]["history_statuses"])
    observations: list[HistoryObservation] = []
    targets: list[PathTarget] = []
    with panel.open(newline="", encoding="utf-8") as source:
        reader = csv.reader(source)
        header = next(reader)
        if len(header) != len(set(header)) or set(selected_fields) - set(header):
            raise DynamicsError("source panel header differs")
        indices = {field: header.index(field) for field in selected_fields}
        for line_number, values in enumerate(reader, 2):
            if len(values) != len(header):
                raise DynamicsError(f"source row width differs at line {line_number}")
            row = {field: values[index] for field, index in indices.items()}
            observation = observation_from_source_row(row, history_statuses=history_statuses)
            source_season = int(row["source_season"])
            if not 2005 <= source_season <= 2024 or observation.match_date.year > 2024:
                raise DynamicsError("source lies outside the frozen historical boundary")
            rule_row, rule = rules[row["source_key"]]
            for field in (
                "match_id",
                "source_key",
                "source_season",
                "tourney_id",
                "round",
                "best_of",
            ):
                if str(rule_row[field]) != str(row[field]):
                    raise DynamicsError(
                        f"rule/source metadata differs at line {line_number}: {field}"
                    )
            target = TargetMatch(
                observation.match_id,
                observation.match_date,
                observation.tourney_id,
                observation.surface,
                int(row["best_of"]),
                observation.player_a,
                observation.player_b,
                rule,
            )
            observations.append(observation)
            targets.append(PathTarget(target, source_season, row["source_key"]))
    if len(observations) != config["input"]["panel_rows"] or len(rules) != len(observations):
        raise DynamicsError("source/rule row count differs")
    return observations, targets


def _dynamic_config(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> DynamicConfig:
    return DynamicConfig(
        global_initial_mean_logit=float(base["global_initial_mean_logit"]),
        global_initial_sd=float(candidate["global_initial_sd"]),
        surface_mean_initial_sd=float(candidate["surface_mean_initial_sd"]),
        tournament_initial_sd=float(candidate["tournament_initial_sd"]),
        serve_initial_sd=float(candidate["role_initial_sd"]),
        return_initial_sd=float(candidate["role_initial_sd"]),
        surface_initial_sd=float(candidate["shared_surface_initial_sd"]),
        serve_process_sd_per_60_days=float(candidate["role_process_sd_per_60_days"]),
        return_process_sd_per_60_days=float(candidate["role_process_sd_per_60_days"]),
        surface_process_sd_per_60_days=float(base["surface_process_sd_per_60_days"]),
        solver_gradient_tolerance=float(base["solver_gradient_tolerance"]),
        solver_newton_decrement_tolerance=float(base["solver_newton_decrement_tolerance"]),
        solver_max_iterations=int(base["solver_max_iterations"]),
    )


def _bind_output_directory(output: Path, binding: Mapping[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "run_binding.json"
    normalized = json.loads(json.dumps(binding, sort_keys=True))
    if path.exists():
        if json.loads(path.read_text()) != normalized:
            raise DynamicsError("output run binding mismatch")
    else:
        existing = [item for item in output.iterdir() if item.name != path.name]
        if existing:
            raise DynamicsError("unbound nonempty output directory")
        atomic_json(path, normalized)


def _validate_completed_manifest(
    output: Path,
    manifest: Mapping[str, Any],
    run_binding: Mapping[str, Any],
) -> None:
    if manifest.get("status") != "complete" or manifest.get("run_binding") != run_binding:
        raise DynamicsError("completed run manifest binding or status differs")
    expected = {
        "config_sha256": run_binding["config_sha256"],
        "panel_sha256": run_binding["input_panel_sha256"],
        "rule_mapping_sha256": run_binding["rule_mapping_sha256"],
    }
    if any(manifest.get(field) != value for field, value in expected.items()):
        raise DynamicsError("completed run manifest source hash differs")
    entries = manifest.get("outputs")
    if not isinstance(entries, list):
        raise DynamicsError("completed run output inventory is missing")
    inventory = {str(item["path"]): item for item in entries}
    actual = {
        str(path.relative_to(output))
        for path in output.rglob("*")
        if path.is_file() and path.name != "run_manifest.json"
    }
    if set(inventory) != actual:
        raise DynamicsError("completed run output inventory membership differs")
    for relative, item in inventory.items():
        path = output / relative
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise DynamicsError("completed output hash or byte count differs")
    selected_path = output / "selected_matches.csv"
    if manifest.get("selected_matches_sha256") != sha256(selected_path):
        raise DynamicsError("completed selected match hash differs")
    with selected_path.open(newline="", encoding="utf-8") as source:
        selected_rows = sum(1 for _ in csv.DictReader(source))
    if manifest.get("selected_matches_rows") != selected_rows:
        raise DynamicsError("completed selected match row count differs")


def run(config_path: Path, output: Path) -> dict[str, Any]:
    config_path = resolve_under_root(config_path, label="config")
    output = resolve_output_under_root(output, label="output")
    config = json.loads(config_path.read_text())
    _require_frozen(config, config_path)
    _validate_config_contract(config)
    config_hash = sha256(config_path)
    run_binding = {
        "experiment_id": config["experiment_id"],
        "config_path": relative_to_root(config_path, label="config"),
        "config_sha256": config_hash,
        "input_panel_sha256": config["input"]["panel_sha256"],
        "rule_mapping_sha256": config["match_conversion"]["rule_mapping_sha256"],
        "execution_binding": config["execution_binding"],
    }
    _bind_output_directory(output, run_binding)
    complete_manifest = output / "run_manifest.json"
    if complete_manifest.exists():
        manifest = json.loads(complete_manifest.read_text())
        _validate_completed_manifest(output, manifest, run_binding)
        return manifest

    observations, targets = _load_source(config)
    observation_map = {item.match_id: item for item in observations}
    lag_days = int(config["chronology"]["availability_lag_calendar_days"])
    candidate_root = output / "candidate_paths"
    dynamic_paths: dict[str, list[Mapping[str, Any]]] = {}
    control_paths: dict[str, list[Mapping[str, Any]]] = {}
    dynamic_losses: dict[str, list[dict[str, Any]]] = {}
    control_losses: dict[str, list[dict[str, Any]]] = {}
    checkpoint_status: list[dict[str, str]] = []

    dynamic_base = config["dynamic_filter"]
    for candidate in config["hyperparameter_selection_proposal"]["candidate_menu"]:
        candidate_id = candidate["candidate_id"]
        binding = {**run_binding, "candidate_family": "dynamic", "candidate": candidate}
        directory = candidate_root / "dynamic" / candidate_id
        saved = load_candidate_checkpoint(directory, binding)
        if saved is None:
            solver_summary: dict[str, Any] = {}
            try:
                rows = dynamic_point_path(
                    observations,
                    targets,
                    _dynamic_config(dynamic_base, candidate),
                    candidate_id,
                    lag_days=lag_days,
                    solver_summary=solver_summary,
                )
            except Exception as error:
                directory.mkdir(parents=True, exist_ok=True)
                atomic_json(
                    directory / "failure.json",
                    {
                        "status": "fatal",
                        "candidate_family": "dynamic",
                        "candidate_id": candidate_id,
                        "source_date": solver_summary.get("failure_source_date", ""),
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "binding": binding,
                        "binding_sha256": canonical_json_hash(binding),
                    },
                )
                raise
            saved, status = checkpoint_candidate_path(
                directory, binding, rows, solver_summary=solver_summary
            )
        else:
            status = "reused"
        dynamic_paths[candidate_id] = saved
        losses = point_loss_rows(saved, observation_map)
        dynamic_losses[candidate_id] = losses
        _atomic_csv(
            candidate_root / "dynamic" / candidate_id / "point_losses.csv", LOSS_FIELDS, losses
        )
        checkpoint_status.append(
            {
                "candidate_family": "dynamic",
                "candidate_id": candidate_id,
                "status": status,
                "solver_summary_sha256": sha256(directory / "solver_summary.json"),
            }
        )

    initial_serve_probability = 1.0 / (
        1.0 + math.exp(-float(dynamic_base["global_initial_mean_logit"]))
    )
    for candidate in config["unadjusted_baseline"]["selection_proposal"]["candidate_menu"]:
        candidate_id = candidate["candidate_id"]
        binding = {**run_binding, "candidate_family": "control", "candidate": candidate}
        directory = candidate_root / "control" / candidate_id
        saved = load_candidate_checkpoint(directory, binding)
        if saved is None:
            rows = control_point_path(
                observations,
                targets,
                candidate_id,
                half_life_days=float(candidate["half_life_days"]),
                overall_prior_units=float(candidate["overall_prior_units"]),
                surface_prior_units=float(candidate["surface_prior_units"]),
                initial_serve_probability=initial_serve_probability,
                lag_days=lag_days,
            )
            saved, status = checkpoint_candidate_path(directory, binding, rows)
        else:
            status = "reused"
        control_paths[candidate_id] = saved
        losses = point_loss_rows(saved, observation_map)
        control_losses[candidate_id] = losses
        _atomic_csv(
            candidate_root / "control" / candidate_id / "point_losses.csv", LOSS_FIELDS, losses
        )
        checkpoint_status.append(
            {"candidate_family": "control", "candidate_id": candidate_id, "status": status}
        )

    selection_years = config["selection_years"]
    dynamic_definitions = {
        row["candidate_id"]: (
            float(row["role_process_sd_per_60_days"]),
            float(row["shared_surface_initial_sd"]),
            0 if row["prior_bundle"] == "tight" else 1,
            row["candidate_id"],
        )
        for row in config["hyperparameter_selection_proposal"]["candidate_menu"]
    }
    control_definitions = {
        row["candidate_id"]: (
            -float(row["half_life_days"]),
            -float(row["overall_prior_units"]),
            -float(row["surface_prior_units"]),
            row["candidate_id"],
        )
        for row in config["unadjusted_baseline"]["selection_proposal"]["candidate_menu"]
    }
    dynamic_selection, dynamic_trials = select_family(
        dynamic_losses,
        dynamic_definitions,
        selection_years=selection_years,
        fallback_candidate_id=config["hyperparameter_selection_proposal"]["fallback_candidate_id"],
    )
    control_selection, control_trials = select_family(
        control_losses,
        control_definitions,
        selection_years=selection_years,
        fallback_candidate_id=config["unadjusted_baseline"]["selection_proposal"][
            "fallback_candidate_id"
        ],
    )
    for row in dynamic_selection:
        row["candidate_family"] = "dynamic"
    for row in control_selection:
        row["candidate_family"] = "control"
    for row in dynamic_trials:
        row["candidate_family"] = "dynamic"
    for row in control_trials:
        row["candidate_family"] = "control"
    _atomic_csv(output / "selection_trials.csv", TRIAL_FIELDS, [*dynamic_trials, *control_trials])
    _atomic_csv(
        output / "selections.csv", SELECTION_FIELDS, [*dynamic_selection, *control_selection]
    )

    selected_dynamic = selected_match_predictions(
        "dynamic", dynamic_paths, dynamic_selection, targets
    )
    selected_control = selected_match_predictions(
        "control", control_paths, control_selection, targets
    )
    selected = merge_selected_matches(selected_dynamic, selected_control)
    _atomic_csv(output / "selected_matches.csv", SELECTED_MATCH_FIELDS, selected)
    atomic_json(output / "checkpoint_status.json", checkpoint_status)

    outputs = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in {"run_manifest.json"}:
            outputs.append(
                {
                    "path": str(path.relative_to(output)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest = {
        "status": "complete",
        "artifact_kind": "point_paths_and_selected_label_free_match_predictions_no_outcome_scores",
        "config_sha256": config_hash,
        "panel_sha256": config["input"]["panel_sha256"],
        "rule_mapping_sha256": config["match_conversion"]["rule_mapping_sha256"],
        "selected_matches_sha256": sha256(output / "selected_matches.csv"),
        "selected_matches_rows": len(selected),
        "run_binding": run_binding,
        "source_rows": len(observations),
        "candidate_checkpoints": checkpoint_status,
        "outputs": outputs,
    }
    atomic_json(complete_manifest, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SR02 candidate point paths and selection")
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    manifest = run(args.config, args.output)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "selected_matches_rows": manifest["selected_matches_rows"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
