"""Label-free dynamic serve/return representation and tennis scoring engine.

Ported verbatim from the archive's ``references/SR02_models/dynamic.py`` (the revision
``experiments/SR02-C1.json`` binds by hash). The state update is a deterministic diagonal
Laplace filter for aggregate binomial service-point observations. It is an approximation
to, not a replacement for, the joint posterior in Ingram (2019).

What changed in the port: validation errors are :class:`DynamicsError`, a
:class:`tennislab.chain.common.ChainError` (still a ``ValueError``); nothing in the
arithmetic, the iteration order or the solver's acceptance rules.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

import numpy as np

from tennislab.chain.common import ChainError


class DynamicsError(ChainError):
    """Invalid history row, target, rule or filter state; fails closed."""


SURFACES = ("Hard", "Clay", "Grass", "Carpet")
COUNT_SUFFIXES = ("svpt", "1stIn", "1stWon", "2ndWon", "df", "ace", "bpSaved", "bpFaced")
SOURCE_ROW_FIELDS = (
    "match_id",
    "match_date",
    "tourney_id",
    "surface",
    "player_a",
    "player_b",
    "a_entity_id",
    "b_entity_id",
    "identity_tier",
    "status",
    "played",
    "walkover",
    "abandoned",
    "count_block_status",
    "started_evidence",
    *(f"{side}_{suffix}" for side in ("a", "b") for suffix in COUNT_SUFFIXES),
)


def expit(value: float) -> float:
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def logit_probability(value: float) -> float:
    if not 0.0 <= value <= 1.0 or not math.isfinite(value):
        raise DynamicsError("probability must be finite and lie in [0,1]")
    clipped = min(max(value, 1e-12), 1.0 - 1e-12)
    return math.log(clipped / (1.0 - clipped))


def canonical_date(value: str, field: str) -> dt.date:
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise DynamicsError(f"invalid {field}: {value!r}") from exc
    if result.isoformat() != value:
        raise DynamicsError(f"noncanonical {field}: {value!r}")
    return result


def positive_int(value: str, field: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise DynamicsError(f"invalid {field}: {value!r}") from exc
    if result <= 0 or str(result) != value:
        raise DynamicsError(f"{field} must be a canonical positive integer")
    return result


def nonnegative_int(value: str, field: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise DynamicsError(f"invalid {field}: {value!r}") from exc
    if result < 0 or str(result) != value:
        raise DynamicsError(f"{field} must be a canonical nonnegative integer")
    return result


@dataclass(frozen=True)
class ServiceLine:
    points_won: int
    points_played: int

    def __post_init__(self) -> None:
        if self.points_played <= 0:
            raise DynamicsError("service points must be positive")
        if not 0 <= self.points_won <= self.points_played:
            raise DynamicsError("service points won must lie in [0, service points]")


@dataclass(frozen=True)
class HistoryObservation:
    match_id: str
    match_date: dt.date
    tourney_id: str
    surface: str
    player_a: int
    player_b: int
    service_a: ServiceLine | None
    service_b: ServiceLine | None
    history_eligible: bool
    exclusion_reason: str

    def __post_init__(self) -> None:
        if not self.match_id or not self.tourney_id:
            raise DynamicsError("match_id and tourney_id are required")
        if self.surface not in SURFACES:
            raise DynamicsError(f"unsupported surface: {self.surface!r}")
        if self.player_a <= 0 or self.player_a >= self.player_b:
            raise DynamicsError("history rows require neutral player_a < player_b")
        if self.history_eligible and self.service_a is None and self.service_b is None:
            raise DynamicsError("eligible history requires at least one usable service contest")


def _service_line(row: Mapping[str, str], side: str) -> ServiceLine:
    serve_points = nonnegative_int(row[f"{side}_svpt"], f"{side}_svpt")
    first_in = nonnegative_int(row[f"{side}_1stIn"], f"{side}_1stIn")
    first_won = nonnegative_int(row[f"{side}_1stWon"], f"{side}_1stWon")
    second_won = nonnegative_int(row[f"{side}_2ndWon"], f"{side}_2ndWon")
    double_faults = nonnegative_int(row[f"{side}_df"], f"{side}_df")
    aces = nonnegative_int(row[f"{side}_ace"], f"{side}_ace")
    bp_saved = nonnegative_int(row[f"{side}_bpSaved"], f"{side}_bpSaved")
    bp_faced = nonnegative_int(row[f"{side}_bpFaced"], f"{side}_bpFaced")
    second_points = serve_points - first_in
    won = first_won + second_won
    if first_in > serve_points:
        raise DynamicsError("first serves in exceed serve points")
    if first_won > first_in:
        raise DynamicsError("first-serve wins exceed first serves in")
    if second_won > second_points:
        raise DynamicsError("second-serve wins exceed second-serve points")
    if double_faults > second_points or second_won + double_faults > second_points:
        raise DynamicsError("second-serve wins plus double faults exceed second-serve points")
    if won > serve_points or aces > won:
        raise DynamicsError("service wins/aces exceed their denominators")
    if bp_saved > bp_faced:
        raise DynamicsError("break points saved exceed break points faced")
    return ServiceLine(won, serve_points)


def observation_from_source_row(
    row: Mapping[str, str], *, history_statuses: Sequence[str] = ("completed", "retired", "default")
) -> HistoryObservation:
    """Extract only the allowlisted historical fields; `a_won` is never read."""
    player_a = positive_int(row["player_a"], "player_a")
    player_b = positive_int(row["player_b"], "player_b")
    if row["a_entity_id"] != row["player_a"] or row["b_entity_id"] != row["player_b"]:
        raise DynamicsError("entity and neutral player IDs disagree")
    if row["identity_tier"] not in {"primary", "provisional"}:
        raise DynamicsError("unsupported identity tier")
    if row["status"] not in {"completed", "retired", "default"}:
        raise DynamicsError("unsupported status")
    if (
        row["played"] not in {"true", "false"}
        or row["walkover"] not in {"true", "false"}
        or row["abandoned"] not in {"true", "false"}
    ):
        raise DynamicsError("played/walkover/abandoned must be literal booleans")
    if row["count_block_status"] not in {"usable", "missing_all"}:
        raise DynamicsError("unsupported corrected count block status")
    service_a = service_b = None
    count_notes: list[str] = []
    if row["count_block_status"] == "usable":
        for side in ("a", "b"):
            try:
                line = _service_line(row, side)
            except ValueError as exc:
                count_notes.append(f"{side}_counts_invalid:{exc}")
            else:
                if side == "a":
                    service_a = line
                else:
                    service_b = line
    reasons: list[str] = []
    if row["identity_tier"] != "primary":
        reasons.append("nonprimary_identity")
    if row["status"] not in set(history_statuses):
        reasons.append(f"status_{row['status']}_excluded")
    if row["status"] == "default" and not row.get("started_evidence", ""):
        reasons.append("default_missing_commencement_evidence")
    if row["played"] != "true" or row["walkover"] != "false" or row["abandoned"] != "false":
        reasons.append("not_ordinary_started_row")
    if service_a is None and service_b is None:
        reasons.append("counts_missing_all")
    return HistoryObservation(
        match_id=row["match_id"],
        match_date=canonical_date(row["match_date"], "match_date"),
        tourney_id=row["tourney_id"],
        surface=row["surface"],
        player_a=player_a,
        player_b=player_b,
        service_a=service_a,
        service_b=service_b,
        history_eligible=not reasons,
        exclusion_reason=";".join((*reasons, *count_notes)),
    )


@dataclass(frozen=True)
class SetRule:
    tiebreak_at_games: int | None
    tiebreak_points: int | None

    def __post_init__(self) -> None:
        if self.tiebreak_at_games is None:
            if self.tiebreak_points is not None:
                raise DynamicsError("advantage set cannot specify tiebreak points")
        elif self.tiebreak_at_games < 6 or self.tiebreak_points not in {7, 10}:
            raise DynamicsError("tiebreak set requires games>=6 and 7 or 10 points")


@dataclass(frozen=True)
class MatchRule:
    sets_to_win: int
    regular_set: SetRule
    deciding_set: SetRule

    def __post_init__(self) -> None:
        if self.sets_to_win not in {2, 3}:
            raise DynamicsError("sets_to_win must be 2 or 3")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> MatchRule:
        expected = {"sets_to_win", "regular_set", "deciding_set"}
        if set(value) != expected:
            raise DynamicsError(f"match-rule fields differ: {sorted(set(value) ^ expected)}")

        def set_rule(item: Mapping[str, Any]) -> SetRule:
            if set(item) != {"mode", "tiebreak_at_games", "tiebreak_points"}:
                raise DynamicsError("set-rule fields differ")
            mode = item["mode"]
            if mode not in {"tiebreak", "advantage"}:
                raise DynamicsError("set mode must be tiebreak or advantage")
            if mode == "advantage" and (
                item["tiebreak_at_games"] is not None or item["tiebreak_points"] is not None
            ):
                raise DynamicsError("advantage set must use null tiebreak fields")
            return SetRule(item["tiebreak_at_games"], item["tiebreak_points"])

        return cls(
            int(value["sets_to_win"]),
            set_rule(value["regular_set"]),
            set_rule(value["deciding_set"]),
        )


@dataclass(frozen=True)
class TargetMatch:
    match_id: str
    match_date: dt.date
    tourney_id: str
    surface: str
    best_of: int
    player_a: int
    player_b: int
    rule: MatchRule | None = None

    def __post_init__(self) -> None:
        if (
            not self.match_id
            or not self.tourney_id
            or self.player_a <= 0
            or self.player_a >= self.player_b
        ):
            raise DynamicsError(
                "target match requires match/tournament IDs and neutral player_a < player_b"
            )
        if self.surface not in SURFACES or self.best_of not in {3, 5}:
            raise DynamicsError("unsupported target surface or best_of")
        if self.rule is not None and self.best_of != self.rule.sets_to_win * 2 - 1:
            raise DynamicsError("best_of and match rule disagree")


@dataclass
class GaussianState:
    mean: float
    variance: float
    last_date: dt.date
    point_observations: int = 0


@dataclass(frozen=True)
class DynamicConfig:
    global_initial_mean_logit: float
    global_initial_sd: float
    surface_mean_initial_sd: float
    tournament_initial_sd: float
    serve_initial_sd: float
    return_initial_sd: float
    surface_initial_sd: float
    serve_process_sd_per_60_days: float
    return_process_sd_per_60_days: float
    surface_process_sd_per_60_days: float
    solver_gradient_tolerance: float = 1e-6
    solver_newton_decrement_tolerance: float = 1e-7
    solver_max_iterations: int = 50

    def __post_init__(self) -> None:
        values = (
            self.global_initial_mean_logit,
            self.global_initial_sd,
            self.surface_mean_initial_sd,
            self.tournament_initial_sd,
            self.serve_initial_sd,
            self.return_initial_sd,
            self.surface_initial_sd,
            self.serve_process_sd_per_60_days,
            self.return_process_sd_per_60_days,
            self.surface_process_sd_per_60_days,
            self.solver_gradient_tolerance,
            self.solver_newton_decrement_tolerance,
        )
        if not all(math.isfinite(value) for value in values):
            raise DynamicsError("dynamic parameters must be finite")
        if min(values[1:-2]) < 0.0 or min(values[1:7]) <= 0.0:
            raise DynamicsError("initial SDs must be positive and process SDs nonnegative")
        if (
            self.solver_gradient_tolerance <= 0.0
            or self.solver_newton_decrement_tolerance <= 0.0
            or self.solver_max_iterations <= 0
        ):
            raise DynamicsError("solver controls must be positive")


class DynamicServeReturnFilter:
    """Diagonal assumed-density filter with source-date frozen batches."""

    def __init__(self, config: DynamicConfig):
        self.config = config
        self.states: dict[tuple[str, int, str], GaussianState] = {}
        self.latest_source_date: dt.date | None = None
        self.matches_used = 0
        self.points_used = 0
        self.last_solver_iterations = 0
        self.last_solver_max_gradient = 0.0
        self.last_solver_newton_decrement = 0.0
        self.last_solver_acceptance = ""

    def _parameters(self, key: tuple[str, int, str]) -> tuple[float, float]:
        kind = key[0]
        if kind == "global":
            return self.config.global_initial_sd**2, 0.0
        if kind == "surface_mean":
            return self.config.surface_mean_initial_sd**2, 0.0
        if kind == "tournament":
            return self.config.tournament_initial_sd**2, 0.0
        if kind == "serve":
            return (
                self.config.serve_initial_sd**2,
                self.config.serve_process_sd_per_60_days**2 / 60.0,
            )
        if kind == "return":
            return (
                self.config.return_initial_sd**2,
                self.config.return_process_sd_per_60_days**2 / 60.0,
            )
        if kind == "surface":
            return (
                self.config.surface_initial_sd**2,
                self.config.surface_process_sd_per_60_days**2 / 60.0,
            )
        raise DynamicsError(f"unknown state kind: {kind}")

    def _prior(self, key: tuple[str, int, str], date: dt.date) -> GaussianState:
        current = self.states.get(key)
        initial_variance, process_per_day = self._parameters(key)
        if current is None:
            initial_mean = self.config.global_initial_mean_logit if key[0] == "global" else 0.0
            return GaussianState(initial_mean, initial_variance, date, 0)
        days = (date - current.last_date).days
        if days < 0:
            raise DynamicsError("dynamic state cannot move backward")
        return GaussianState(
            current.mean,
            current.variance + process_per_day * days,
            date,
            current.point_observations,
        )

    @staticmethod
    def _terms(
        server: int, returner: int, surface: str, tourney_id: str
    ) -> tuple[tuple[tuple[str, int, str], float], ...]:
        return (
            (("global", 0, ""), 1.0),
            (("surface_mean", 0, surface), 1.0),
            (("tournament", 0, tourney_id), 1.0),
            (("serve", server, ""), 1.0),
            (("return", returner, ""), -1.0),
            (("surface", server, surface), 1.0),
            (("surface", returner, surface), -1.0),
        )

    def apply_batch(self, observations: Iterable[HistoryObservation]) -> None:
        batch = sorted(observations, key=lambda item: item.match_id)
        if not batch:
            return
        date = batch[0].match_date
        if any(item.match_date != date for item in batch):
            raise DynamicsError("dynamic update batch must have one source date")
        if self.latest_source_date is not None and date <= self.latest_source_date:
            raise DynamicsError("source-date batches must be strictly increasing")
        used = [item for item in batch if item.history_eligible]
        if not used:
            return
        contests = [
            (item, item.player_a, item.player_b, item.service_a)
            for item in used
            if item.service_a is not None
        ] + [
            (item, item.player_b, item.player_a, item.service_b)
            for item in used
            if item.service_b is not None
        ]
        active = {
            key
            for item, server, returner, _ in contests
            for key, _ in self._terms(server, returner, item.surface, item.tourney_id)
        }
        keys = sorted(active)
        key_index = {key: index for index, key in enumerate(keys)}
        priors = {key: self._prior(key, date) for key in keys}
        prior_mean = np.asarray([priors[key].mean for key in keys], dtype=np.float64)
        prior_precision = np.asarray([1.0 / priors[key].variance for key in keys], dtype=np.float64)
        point_counts: dict[tuple[str, int, str], int] = defaultdict(int)
        design_rows: list[np.ndarray] = []
        wins: list[float] = []
        attempts: list[float] = []
        for item, server, returner, line in contests:
            terms = self._terms(server, returner, item.surface, item.tourney_id)
            design = np.zeros(len(keys), dtype=np.float64)
            for key, sign in terms:
                design[key_index[key]] = sign
                point_counts[key] += line.points_played
            design_rows.append(design)
            wins.append(float(line.points_won))
            attempts.append(float(line.points_played))
            self.points_used += line.points_played

        design_matrix = np.vstack(design_rows)
        y = np.asarray(wins, dtype=np.float64)
        n = np.asarray(attempts, dtype=np.float64)

        def objective_gradient_hessian(values: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
            eta = design_matrix @ values
            probability = np.empty_like(eta)
            positive = eta >= 0.0
            probability[positive] = 1.0 / (1.0 + np.exp(-eta[positive]))
            exponent = np.exp(eta[~positive])
            probability[~positive] = exponent / (1.0 + exponent)
            difference = values - prior_mean
            objective = float(
                0.5 * np.dot(prior_precision * difference, difference)
                + np.sum(n * np.logaddexp(0.0, eta) - y * eta)
            )
            gradient = prior_precision * difference + design_matrix.T @ (n * probability - y)
            curvature = n * probability * (1.0 - probability)
            hessian = np.diag(prior_precision) + design_matrix.T @ (
                curvature[:, None] * design_matrix
            )
            return objective, gradient, hessian

        values = prior_mean.copy()
        converged = False
        iterations = 0
        # The loop variable is read after the loop (the last iteration count is a receipt).
        for iterations in range(1, self.config.solver_max_iterations + 1):  # noqa: B007
            objective, gradient, hessian = objective_gradient_hessian(values)
            max_gradient = float(np.max(np.abs(gradient)))
            if max_gradient <= self.config.solver_gradient_tolerance:
                converged = True
                acceptance = "maximum_gradient"
                break
            step = np.linalg.solve(hessian, gradient)
            directional = float(np.dot(gradient, step))
            eta = design_matrix @ values
            probability = np.asarray([expit(float(value)) for value in eta])
            scale = 1.0
            while scale >= 2.0**-30:
                candidate = values - scale * step
                # Compare the change directly: subtracting two large absolute
                # losses loses the final Newton improvement to roundoff.
                delta = candidate - values
                eta_delta = design_matrix @ delta
                small = np.abs(eta_delta) <= 0.5
                curvature_remainder = np.empty_like(eta_delta)
                curvature_remainder[small] = (
                    np.log1p(probability[small] * np.expm1(eta_delta[small]))
                    - probability[small] * eta_delta[small]
                )
                curvature_remainder[~small] = (
                    np.logaddexp(0.0, eta[~small] + eta_delta[~small])
                    - np.logaddexp(0.0, eta[~small])
                    - probability[~small] * eta_delta[~small]
                )
                objective_change = float(
                    np.dot(gradient, delta)
                    + 0.5 * np.dot(prior_precision * delta, delta)
                    + np.dot(n, curvature_remainder)
                )
                if objective_change <= -1e-4 * scale * directional:
                    values = candidate
                    break
                scale *= 0.5
            else:
                newton_decrement = math.sqrt(max(directional, 0.0))
                if newton_decrement <= self.config.solver_newton_decrement_tolerance:
                    converged = True
                    acceptance = "newton_decrement"
                    break
                raise DynamicsError(
                    f"joint batch MAP line search failed: max_gradient={max_gradient:.6g}, "
                    f"newton_decrement_squared={directional:.6g}"
                )
        if not converged:
            _, gradient, hessian = objective_gradient_hessian(values)
            max_gradient = float(np.max(np.abs(gradient)))
            final_step = np.linalg.solve(hessian, gradient)
            newton_decrement = math.sqrt(max(float(np.dot(gradient, final_step)), 0.0))
            if max_gradient <= self.config.solver_gradient_tolerance:
                converged = True
                acceptance = "maximum_gradient"
            elif newton_decrement <= self.config.solver_newton_decrement_tolerance:
                converged = True
                acceptance = "newton_decrement"
        if not converged:
            raise DynamicsError(
                f"joint batch MAP did not converge: iterations={iterations}, max_gradient={max_gradient:.6g}"
            )
        _, gradient, hessian = objective_gradient_hessian(values)
        covariance = np.linalg.inv(hessian)
        if not np.all(np.isfinite(covariance)):
            raise DynamicsError("joint batch Laplace covariance is nonfinite")
        self.last_solver_iterations = iterations
        self.last_solver_max_gradient = float(np.max(np.abs(gradient)))
        final_step = np.linalg.solve(hessian, gradient)
        self.last_solver_newton_decrement = math.sqrt(max(float(np.dot(gradient, final_step)), 0.0))
        self.last_solver_acceptance = acceptance
        for index, key in enumerate(keys):
            prior = priors[key]
            posterior_mean = float(values[index])
            posterior_variance = float(covariance[index, index])
            if not (
                math.isfinite(posterior_mean)
                and math.isfinite(posterior_variance)
                and posterior_variance > 0.0
            ):
                raise DynamicsError("dynamic update produced invalid state")
            self.states[key] = GaussianState(
                posterior_mean,
                posterior_variance,
                date,
                prior.point_observations + point_counts[key],
            )
        self.matches_used += len(used)
        self.latest_source_date = date

    def point_prediction(
        self, server: int, returner: int, surface: str, tourney_id: str, date: dt.date
    ) -> dict[str, float | int]:
        terms = self._terms(server, returner, surface, tourney_id)
        priors = [(self._prior(key, date), sign) for key, sign in terms]
        eta = sum(sign * state.mean for state, sign in priors)
        variance = sum(state.variance for state, _ in priors)
        return {
            "probability": expit(eta),
            "logit": eta,
            "latent_variance_diagonal": variance,
            "server_unseen": int(("serve", server, "") not in self.states),
            "returner_unseen": int(("return", returner, "") not in self.states),
            "server_surface_unseen": int(("surface", server, surface) not in self.states),
            "returner_surface_unseen": int(("surface", returner, surface) not in self.states),
            "surface_mean_unseen": int(("surface_mean", 0, surface) not in self.states),
            "tournament_unseen": int(("tournament", 0, tourney_id) not in self.states),
        }

    def population_summary(
        self, surface: str, tourney_id: str, date: dt.date
    ) -> dict[str, float | int]:
        output: dict[str, float | int] = {}
        for label, key in (
            ("global", ("global", 0, "")),
            ("surface_mean", ("surface_mean", 0, surface)),
            ("tournament", ("tournament", 0, tourney_id)),
        ):
            state = self._prior(key, date)
            output[f"{label}_mean"] = state.mean
            output[f"{label}_variance"] = state.variance
            output[f"{label}_unseen"] = int(key not in self.states)
        return output

    def point_logit_covariance(
        self,
        first_server: int,
        first_returner: int,
        second_server: int,
        second_returner: int,
        surface: str,
        tourney_id: str,
        date: dt.date,
    ) -> float:
        """Propagate the retained diagonal state through two serve logits.

        This keeps covariance induced by shared population, tournament, and
        player-surface terms.  Cross-state posterior covariance was discarded
        by the assumed-density projection and cannot be recovered here.
        """
        first = dict(self._terms(first_server, first_returner, surface, tourney_id))
        second = dict(self._terms(second_server, second_returner, surface, tourney_id))
        return sum(
            first[key] * second[key] * self._prior(key, date).variance
            for key in first.keys() & second.keys()
        )

    def state_summary(self, player: int, surface: str, date: dt.date) -> dict[str, float | int]:
        result: dict[str, float | int] = {}
        for label, key in (
            ("serve", ("serve", player, "")),
            ("return", ("return", player, "")),
            ("surface", ("surface", player, surface)),
        ):
            state = self._prior(key, date)
            result[f"{label}_mean"] = state.mean
            result[f"{label}_variance"] = state.variance
            result[f"{label}_unseen"] = int(key not in self.states)
            result[f"{label}_point_observations"] = state.point_observations
        return result


@dataclass
class Tally:
    successes: float = 0.0
    attempts: float = 0.0


class UnadjustedRateBaseline:
    """Decayed marginal player rates; estimation ignores opponent strength."""

    def __init__(
        self,
        half_life_days: float,
        prior_units: float,
        surface_prior_units: float,
        base_serve: float,
    ):
        if (
            half_life_days <= 0.0
            or prior_units <= 0.0
            or surface_prior_units <= 0.0
            or not 0.0 < base_serve < 1.0
        ):
            raise DynamicsError("invalid unadjusted baseline parameters")
        self.half_life_days = half_life_days
        self.prior_units = prior_units
        self.surface_prior_units = surface_prior_units
        self.base = {"serve": base_serve, "return": 1.0 - base_serve}
        self.overall: dict[tuple[str, int], Tally] = {}
        self.surface: dict[tuple[str, int, str], Tally] = {}
        self.population_overall: dict[str, Tally] = {"serve": Tally(), "return": Tally()}
        self.population_surface: dict[tuple[str, str], Tally] = {}
        self.current_target_date: dt.date | None = None
        self.latest_source_date: dt.date | None = None

    def advance(self, target_date: dt.date) -> None:
        if self.current_target_date is None:
            self.current_target_date = target_date
            return
        days = (target_date - self.current_target_date).days
        if days < 0:
            raise DynamicsError("target dates must be nondecreasing")
        factor = 2.0 ** (-days / self.half_life_days)
        if days:
            for tally in (
                *self.overall.values(),
                *self.surface.values(),
                *self.population_overall.values(),
                *self.population_surface.values(),
            ):
                tally.successes *= factor
                tally.attempts *= factor
        self.current_target_date = target_date

    def _add(
        self, role: str, player: int, surface: str, successes: int, attempts: int, weight: float
    ) -> None:
        overall = self.overall.setdefault((role, player), Tally())
        specific = self.surface.setdefault((role, player, surface), Tally())
        overall.successes += successes * weight
        overall.attempts += attempts * weight
        specific.successes += successes * weight
        specific.attempts += attempts * weight
        population = self.population_overall[role]
        population_specific = self.population_surface.setdefault((role, surface), Tally())
        population.successes += successes * weight
        population.attempts += attempts * weight
        population_specific.successes += successes * weight
        population_specific.attempts += attempts * weight

    def add_observation(self, item: HistoryObservation) -> None:
        if not item.history_eligible:
            return
        if self.current_target_date is None:
            raise DynamicsError("advance baseline before adding history")
        age = (self.current_target_date - item.match_date).days
        if age < 0:
            raise DynamicsError("future baseline observation")
        weight = 2.0 ** (-age / self.half_life_days)
        if item.service_a is not None:
            self._add(
                "serve",
                item.player_a,
                item.surface,
                item.service_a.points_won,
                item.service_a.points_played,
                weight,
            )
            self._add(
                "return",
                item.player_b,
                item.surface,
                item.service_a.points_played - item.service_a.points_won,
                item.service_a.points_played,
                weight,
            )
        if item.service_b is not None:
            self._add(
                "serve",
                item.player_b,
                item.surface,
                item.service_b.points_won,
                item.service_b.points_played,
                weight,
            )
            self._add(
                "return",
                item.player_a,
                item.surface,
                item.service_b.points_played - item.service_b.points_won,
                item.service_b.points_played,
                weight,
            )
        self.latest_source_date = (
            item.match_date
            if self.latest_source_date is None
            else max(self.latest_source_date, item.match_date)
        )

    def rate(self, role: str, player: int, surface: str) -> dict[str, float]:
        overall = self.overall.get((role, player), Tally())
        population = self.population_overall[role]
        population_rate = (
            population.successes / population.attempts
            if population.attempts > 0.0
            else self.base[role]
        )
        overall_rate = (overall.successes + self.prior_units * population_rate) / (
            overall.attempts + self.prior_units
        )
        specific = self.surface.get((role, player, surface), Tally())
        population_specific = self.population_surface.get((role, surface), Tally())
        population_surface_rate = (
            population_specific.successes / population_specific.attempts
            if population_specific.attempts > 0.0
            else population_rate
        )
        surface_prior = expit(
            logit_probability(overall_rate)
            + logit_probability(population_surface_rate)
            - logit_probability(population_rate)
        )
        surface_rate = (specific.successes + self.surface_prior_units * surface_prior) / (
            specific.attempts + self.surface_prior_units
        )
        return {
            "surface_rate": surface_rate,
            "overall_rate": overall_rate,
            "surface_prior": surface_prior,
            "population_overall_rate": population_rate,
            "population_surface_rate": population_surface_rate,
            "overall_denominator": overall.attempts,
            "surface_denominator": specific.attempts,
        }

    def point_prediction(self, server: int, returner: int, surface: str) -> dict[str, float]:
        serve = self.rate("serve", server, surface)
        return_win = self.rate("return", returner, surface)
        population_server_probability = 0.5 * (
            serve["population_surface_rate"] + 1.0 - return_win["population_surface_rate"]
        )
        probability = expit(
            logit_probability(population_server_probability)
            + logit_probability(serve["surface_rate"])
            - logit_probability(serve["population_surface_rate"])
            + logit_probability(1.0 - return_win["surface_rate"])
            - logit_probability(1.0 - return_win["population_surface_rate"])
        )
        simple_probability_mean = 0.5 * serve["surface_rate"] + 0.5 * (
            1.0 - return_win["surface_rate"]
        )
        return {
            "probability": probability,
            "simple_probability_mean": simple_probability_mean,
            "server_overall_rate": serve["overall_rate"],
            "server_surface_rate": serve["surface_rate"],
            "server_surface_prior": serve["surface_prior"],
            "returner_overall_rate": return_win["overall_rate"],
            "returner_surface_rate": return_win["surface_rate"],
            "returner_surface_prior": return_win["surface_prior"],
            "population_surface_serve_rate": serve["population_surface_rate"],
            "population_surface_return_rate": return_win["population_surface_rate"],
            "server_overall_denominator": serve["overall_denominator"],
            "server_surface_denominator": serve["surface_denominator"],
            "returner_overall_denominator": return_win["overall_denominator"],
            "returner_surface_denominator": return_win["surface_denominator"],
        }


def game_win_probability(point_probability: float) -> float:
    if not 0.0 < point_probability < 1.0:
        raise DynamicsError("point probability must be strictly inside (0,1)")
    q = 1.0 - point_probability
    before_deuce = point_probability**4 * (1.0 + 4.0 * q + 10.0 * q * q)
    reach_deuce = 20.0 * point_probability**3 * q**3
    from_deuce = (
        point_probability * point_probability / (point_probability * point_probability + q * q)
    )
    return before_deuce + reach_deuce * from_deuce


def _tiebreak_server(first_server: int, points_played: int) -> int:
    phase = points_played % 4
    return first_server if phase in {0, 3} else 1 - first_server


def tiebreak_win_probability(
    p_a_serve: float, p_b_serve: float, first_server: int, points_to_win: int
) -> float:
    if first_server not in {0, 1} or points_to_win not in {7, 10}:
        raise DynamicsError("invalid tiebreak rule")

    def a_point(points_played: int) -> float:
        return p_a_serve if _tiebreak_server(first_server, points_played) == 0 else 1.0 - p_b_serve

    states = [(difference, phase) for difference in (-1, 0, 1) for phase in range(4)]
    index = {state: number for number, state in enumerate(states)}
    matrix = np.eye(len(states), dtype=np.float64)
    target = np.zeros(len(states), dtype=np.float64)
    for state, row in index.items():
        difference, phase = state
        probability = a_point(phase)
        for next_difference, weight in (
            (difference + 1, probability),
            (difference - 1, 1.0 - probability),
        ):
            if next_difference >= 2:
                target[row] += weight
            elif next_difference <= -2:
                continue
            else:
                matrix[row, index[(next_difference, (phase + 1) % 4)]] -= weight
    tail = np.linalg.solve(matrix, target)

    @cache
    def before_tail(a: int, b: int) -> float:
        if (a >= points_to_win or b >= points_to_win) and abs(a - b) >= 2:
            return float(a > b)
        if min(a, b) >= points_to_win - 1:
            return float(tail[index[(a - b, (a + b) % 4)]])
        probability = a_point(a + b)
        return probability * before_tail(a + 1, b) + (1.0 - probability) * before_tail(a, b + 1)

    return before_tail(0, 0)


def set_transitions(
    p_a_serve: float, p_b_serve: float, first_server: int, rule: SetRule
) -> dict[tuple[int, int], float]:
    game = (game_win_probability(p_a_serve), 1.0 - game_win_probability(p_b_serve))

    def merge(
        destination: dict[tuple[int, int], float],
        source: Mapping[tuple[int, int], float],
        weight: float,
    ) -> None:
        for key, value in source.items():
            destination[key] = destination.get(key, 0.0) + weight * value

    @cache
    def visit(
        a_games: int, b_games: int, next_server: int
    ) -> tuple[tuple[tuple[int, int], float], ...]:
        if rule.tiebreak_at_games is not None and a_games == b_games == rule.tiebreak_at_games:
            probability = tiebreak_win_probability(
                p_a_serve, p_b_serve, next_server, int(rule.tiebreak_points)
            )
            return (((1, 1 - next_server), probability), ((0, 1 - next_server), 1.0 - probability))
        if a_games >= 6 and a_games - b_games >= 2:
            return (((1, next_server), 1.0),)
        if b_games >= 6 and b_games - a_games >= 2:
            return (((0, next_server), 1.0),)
        if rule.tiebreak_at_games is None and a_games == b_games == 6:
            first = game[next_server]
            second = game[1 - next_server]
            win_two = first * second
            lose_two = (1.0 - first) * (1.0 - second)
            probability = win_two / (win_two + lose_two)
            return (((1, next_server), probability), ((0, next_server), 1.0 - probability))
        probability = game[next_server]
        output: dict[tuple[int, int], float] = {}
        merge(output, dict(visit(a_games + 1, b_games, 1 - next_server)), probability)
        merge(output, dict(visit(a_games, b_games + 1, 1 - next_server)), 1.0 - probability)
        return tuple(sorted(output.items()))

    return dict(visit(0, 0, first_server))


def match_win_probability(p_a_serve: float, p_b_serve: float, rule: MatchRule) -> float:
    if not 0.0 < p_a_serve < 1.0 or not 0.0 < p_b_serve < 1.0:
        raise DynamicsError("serve probabilities must be strictly inside (0,1)")

    @cache
    def visit(a_sets: int, b_sets: int, next_server: int) -> float:
        if a_sets == rule.sets_to_win:
            return 1.0
        if b_sets == rule.sets_to_win:
            return 0.0
        deciding = a_sets == b_sets == rule.sets_to_win - 1
        set_rule = rule.deciding_set if deciding else rule.regular_set
        probability = 0.0
        for (a_won, following_server), weight in set_transitions(
            p_a_serve, p_b_serve, next_server, set_rule
        ).items():
            probability += weight * visit(a_sets + a_won, b_sets + 1 - a_won, following_server)
        return probability

    return 0.5 * visit(0, 0, 0) + 0.5 * visit(0, 0, 1)


class PrequentialServeReturn:
    def __init__(
        self,
        observations: Iterable[HistoryObservation],
        dynamic_config: DynamicConfig,
        *,
        lag_days: int,
        baseline_half_life_days: float,
        baseline_prior_units: float,
        baseline_surface_prior_units: float,
    ):
        if lag_days < 0:
            raise DynamicsError("lag_days must be nonnegative")
        self.lag_days = lag_days
        self.observations = sorted(observations, key=lambda item: (item.match_date, item.match_id))
        keys = [item.match_id for item in self.observations]
        if len(keys) != len(set(keys)):
            raise DynamicsError("duplicate history match_id")
        self.dynamic = DynamicServeReturnFilter(dynamic_config)
        self.baseline = UnadjustedRateBaseline(
            baseline_half_life_days,
            baseline_prior_units,
            baseline_surface_prior_units,
            expit(dynamic_config.global_initial_mean_logit),
        )
        self.cursor = 0
        self.latest_target_date: dt.date | None = None

    def _advance(self, target_date: dt.date) -> dt.date:
        if self.latest_target_date is not None and target_date < self.latest_target_date:
            raise DynamicsError("targets must be forecast in nondecreasing date order")
        self.latest_target_date = target_date
        cutoff = target_date - dt.timedelta(days=self.lag_days)
        self.baseline.advance(target_date)
        while (
            self.cursor < len(self.observations)
            and self.observations[self.cursor].match_date <= cutoff
        ):
            source_date = self.observations[self.cursor].match_date
            end = self.cursor + 1
            while end < len(self.observations) and self.observations[end].match_date == source_date:
                end += 1
            batch = self.observations[self.cursor : end]
            self.dynamic.apply_batch(batch)
            for item in batch:
                self.baseline.add_observation(item)
            self.cursor = end
        return cutoff

    def forecast(self, target: TargetMatch) -> dict[str, Any]:
        cutoff = self._advance(target.match_date)
        dynamic_a = self.dynamic.point_prediction(
            target.player_a, target.player_b, target.surface, target.tourney_id, target.match_date
        )
        dynamic_b = self.dynamic.point_prediction(
            target.player_b, target.player_a, target.surface, target.tourney_id, target.match_date
        )
        dynamic_logit_covariance = self.dynamic.point_logit_covariance(
            target.player_a,
            target.player_b,
            target.player_b,
            target.player_a,
            target.surface,
            target.tourney_id,
            target.match_date,
        )
        baseline_a = self.baseline.point_prediction(
            target.player_a, target.player_b, target.surface
        )
        baseline_b = self.baseline.point_prediction(
            target.player_b, target.player_a, target.surface
        )
        state_a = self.dynamic.state_summary(target.player_a, target.surface, target.match_date)
        state_b = self.dynamic.state_summary(target.player_b, target.surface, target.match_date)
        population = self.dynamic.population_summary(
            target.surface, target.tourney_id, target.match_date
        )
        result: dict[str, Any] = {
            "match_id": target.match_id,
            "match_date": target.match_date.isoformat(),
            "tourney_id": target.tourney_id,
            "eligible_through_date": cutoff.isoformat(),
            "surface": target.surface,
            "best_of": target.best_of,
            "player_a": target.player_a,
            "player_b": target.player_b,
            "dynamic_p_a_serve": dynamic_a["probability"],
            "dynamic_p_b_serve": dynamic_b["probability"],
            "dynamic_a_serve_latent_variance": dynamic_a["latent_variance_diagonal"],
            "dynamic_b_serve_latent_variance": dynamic_b["latent_variance_diagonal"],
            "dynamic_a_b_serve_logit_covariance_diagonal_projection": dynamic_logit_covariance,
            "unadjusted_p_a_serve": baseline_a["probability"],
            "unadjusted_p_b_serve": baseline_b["probability"],
            "simple_unadjusted_p_a_serve": baseline_a["simple_probability_mean"],
            "simple_unadjusted_p_b_serve": baseline_b["simple_probability_mean"],
            "dynamic_state_a": state_a,
            "dynamic_state_b": state_b,
            "dynamic_population_state": population,
            "unadjusted_a_audit": baseline_a,
            "unadjusted_b_audit": baseline_b,
            "latest_dynamic_source_date": self.dynamic.latest_source_date.isoformat()
            if self.dynamic.latest_source_date
            else "",
            "latest_unadjusted_source_date": self.baseline.latest_source_date.isoformat()
            if self.baseline.latest_source_date
            else "",
            "match_rule_status": "provided" if target.rule is not None else "missing_explicit_rule",
            "dynamic_match_probability_a": None,
            "unadjusted_match_probability_a": None,
            "simple_unadjusted_match_probability_a": None,
        }
        if target.rule is not None:
            result["dynamic_match_probability_a"] = match_win_probability(
                float(dynamic_a["probability"]), float(dynamic_b["probability"]), target.rule
            )
            result["unadjusted_match_probability_a"] = match_win_probability(
                float(baseline_a["probability"]), float(baseline_b["probability"]), target.rule
            )
            result["simple_unadjusted_match_probability_a"] = match_win_probability(
                float(baseline_a["simple_probability_mean"]),
                float(baseline_b["simple_probability_mean"]),
                target.rule,
            )
        for field in ("latest_dynamic_source_date", "latest_unadjusted_source_date"):
            if result[field] and canonical_date(result[field], field) > cutoff:
                raise DynamicsError(f"{field} exceeds target cutoff")
        return result
