"""The frozen year plan: the only place a calendar year is declared for a chain.

Ported verbatim from the archive's ``runner.YearPlan`` so that every stage reads the
same object and none carries a year literal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class YearPlanError(ValueError):
    """A year plan that is missing a field, unsorted, or internally inconsistent."""


YEAR_PLAN_FIELDS = (
    "panel_end_year",
    "feature_end_year",
    "target_years",
    "calibration_years_back",
    "history_floor_year",
    "training_window_years",
)


@dataclass(frozen=True)
class YearPlan:
    panel_end_year: int
    feature_end_year: int
    target_years: tuple[int, ...]
    calibration_years_back: int
    history_floor_year: int
    training_window_years: int

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> YearPlan:
        if not isinstance(mapping, Mapping):
            raise YearPlanError("year_plan must be an object")
        if set(mapping) != set(YEAR_PLAN_FIELDS):
            raise YearPlanError(f"year_plan keys must be exactly {sorted(YEAR_PLAN_FIELDS)}")
        targets = mapping["target_years"]
        if not isinstance(targets, list | tuple) or not targets:
            raise YearPlanError("year_plan target_years must be a nonempty list")
        if any(not isinstance(year, int) or isinstance(year, bool) for year in targets):
            raise YearPlanError("year_plan target_years must be integers")
        if list(targets) != sorted(set(targets)):
            raise YearPlanError("year_plan target_years must be sorted and unique")
        scalars = {}
        for name in (
            "panel_end_year",
            "feature_end_year",
            "calibration_years_back",
            "history_floor_year",
            "training_window_years",
        ):
            value = mapping[name]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise YearPlanError(f"year_plan {name} must be a positive integer")
            scalars[name] = value
        plan = cls(target_years=tuple(int(year) for year in targets), **scalars)
        if plan.calibration_years_back < 1:
            raise YearPlanError("year_plan calibration_years_back must be at least 1")
        if plan.feature_end_year > plan.panel_end_year:
            raise YearPlanError("feature_end_year cannot exceed panel_end_year")
        if max(plan.target_years) > plan.feature_end_year:
            raise YearPlanError("target years must lie inside the feature table")
        if min(plan.raw_years) < plan.history_floor_year:
            raise YearPlanError(
                "calibration reaches before the configured history floor: "
                f"{min(plan.raw_years)} < {plan.history_floor_year}"
            )
        return plan

    @property
    def raw_years(self) -> tuple[int, ...]:
        """Every year needing saved raw forecasts: targets plus their calibration years."""
        needed: set[int] = set()
        for year in self.target_years:
            needed.add(year)
            needed.update(year - offset for offset in range(1, self.calibration_years_back + 1))
        return tuple(sorted(needed))

    def as_document(self) -> dict[str, Any]:
        return {
            "panel_end_year": self.panel_end_year,
            "feature_end_year": self.feature_end_year,
            "target_years": list(self.target_years),
            "calibration_years_back": self.calibration_years_back,
            "history_floor_year": self.history_floor_year,
            "training_window_years": self.training_window_years,
        }
