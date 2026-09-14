"""Past-only slope calibration of frozen SR02 sports probabilities.

Ported from the archive's ``references/SR03_calibration/calibration.py`` with the
year-parameterisation of ``references/TIER01_models/sr03_calibrate.py`` folded in: every
calendar-year literal and fit-count gate is a field of :class:`CalibrationWindow`, whose
default :data:`SR03_WINDOW` is SR03's own frozen window, so a call without a window is
the SR03 program. The calibration rule is unchanged: one nonnegative logit slope per
sports family per outer year, no intercept, no penalty, no candidate selection, fitted on
the ``training_calendar_years`` calendar years strictly before the outer year and cut two
days before it starts.

What changed in the port: the repository root and the ``sys.path`` import of the SR02
modules are gone (``tennislab.dynamics.market`` and ``.sr02_runner`` are imported by
name); ``bindings.files`` is split into data bindings, verified by hash under the
workspace, and code bindings (``*.py``), which are recorded as declared provenance;
failures are :class:`CalibrationError`.

Outcome reads. ``load_dataset`` reads ``a_won`` from the panel for every played selected
match (``labels=True``). ``training_rows``/``fit_and_predict`` use those outcomes only on
calendar years strictly before the outer year (history). ``evaluate`` scores the outer
years themselves -- including target years when the caller passes them -- and is the
read the integration pass must move behind the report barrier. Every read is marked
``# outcome-history read``.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.chain.common import ChainError, resolve_under_root, sha256, year_plan
from tennislab.dynamics import market as sr02_market
from tennislab.dynamics import sr02_runner


class CalibrationError(ChainError):
    """Invalid calibration configuration, binding, dataset or fit; fails closed."""


FAMILIES = (
    ("dynamic", "dynamic_match_probability_a"),
    ("unadjusted", "unadjusted_match_probability_a"),
    ("simple_unadjusted", "simple_unadjusted_match_probability_a"),
)
MODEL_FIELDS = tuple(
    field for family, _ in FAMILIES for field in (f"raw_{family}", f"calibrated_{family}")
)
PREDICTION_FIELDS = (
    "match_id",
    "match_date",
    "source_season",
    "source_key",
    "tourney_id",
    "surface",
    "best_of",
    "player_a",
    "player_b",
    "identity_tier",
    "calibration_year",
    *MODEL_FIELDS,
    "pinnacle_raw_normalized",
)
TRAINING_FIELDS = (
    "outer_year",
    "training_calendar_year",
    "match_date",
    "match_id",
    "source_key",
    "player_a",
    "player_b",
)
METRIC_FIELDS = ("scope", "cohort", "year", "model", "n", "log_loss", "brier")
RELIABILITY_FIELDS = (
    "scope",
    "cohort",
    "model",
    "bin",
    "lower",
    "upper",
    "n",
    "mean_prediction",
    "outcome_rate",
)
METADATA_FIELDS = (
    "match_id",
    "match_date",
    "source_season",
    "source_key",
    "tourney_id",
    "surface",
    "best_of",
    "player_a",
    "player_b",
)


@dataclass(frozen=True)
class CalibrationWindow:
    """Every calendar-year bound the calibration reads, derived from one ``year_plan``.

    ``outer_years`` is the union over target years of {y - calibration_years_back .. y}:
    the target years themselves plus the years their slope is selected on. For target
    years 2017..2024 with ``calibration_years_back`` 3 that is 2014..2024, SR03's own
    list.
    """

    outer_years: tuple[int, ...]
    training_calendar_years: int
    date_year_min: int
    date_year_max: int
    source_season_min: int
    source_season_max: int
    annual_eligible_floor_year: int

    def __post_init__(self) -> None:
        if self.training_calendar_years < 1:
            raise CalibrationError("calibration_years_back must be at least 1")
        if min(self.outer_years) < self.date_year_min:
            raise CalibrationError("calibration reaches before the configured history floor")
        if max(self.outer_years) > self.date_year_max:
            raise CalibrationError("calibration reaches past the configured panel end year")

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> CalibrationWindow:
        """The window ``year_plan`` implies, or SR03's frozen window when there is none."""
        if config.get("year_plan") is None:
            return SR03_WINDOW
        try:
            plan = year_plan(config)
        except ValueError as error:
            raise CalibrationError(str(error)) from error
        return cls(
            outer_years=plan.raw_years,
            training_calendar_years=plan.calibration_years_back,
            date_year_min=plan.history_floor_year,
            date_year_max=plan.panel_end_year,
            source_season_min=int(config.get("source_season_min", 2000)),
            source_season_max=plan.panel_end_year,
            annual_eligible_floor_year=int(config.get("annual_eligible_floor_year", 2012)),
        )

    def as_document(self) -> dict[str, Any]:
        return {
            "outer_years": list(self.outer_years),
            "training_calendar_years": self.training_calendar_years,
            "date_year_min": self.date_year_min,
            "date_year_max": self.date_year_max,
            "source_season_min": self.source_season_min,
            "source_season_max": self.source_season_max,
            "annual_eligible_floor_year": self.annual_eligible_floor_year,
        }


SR03_WINDOW = CalibrationWindow(
    outer_years=tuple(range(2014, 2025)),
    training_calendar_years=3,
    date_year_min=2011,
    date_year_max=2024,
    source_season_min=2000,
    source_season_max=2024,
    annual_eligible_floor_year=2012,
)


def key_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = [[row["match_date"], row["match_id"]] for row in rows]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, object]], fields: tuple[str, ...]) -> None:
    if not rows:
        raise CalibrationError(f"refusing empty artifact: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_boolean(value: str) -> bool:
    if value not in ("true", "false"):
        raise CalibrationError(f"invalid literal boolean: {value!r}")
    return value == "true"


def parse_date(value: str) -> dt.date:
    try:
        date = dt.date.fromisoformat(value)
    except ValueError as error:
        raise CalibrationError(f"invalid date: {value!r}") from error
    if date.isoformat() != value:
        raise CalibrationError(f"noncanonical date: {value!r}")
    return date


def validate_config(
    config: Mapping[str, Any], *, require_frozen: bool, window: CalibrationWindow = SR03_WINDOW
) -> None:
    expected_status = "frozen_for_real_execution"
    if require_frozen and config.get("proposal_status") != expected_status:
        raise CalibrationError("real execution requires frozen configuration")
    calibration = config.get("calibration", {})
    expected_families = dict(FAMILIES)
    if calibration.get("families") != expected_families:
        raise CalibrationError("calibration family set differs")
    if calibration.get("outer_years") != list(window.outer_years):
        raise CalibrationError(
            f"outer years differ from the configured window {list(window.outer_years)}"
        )
    if (
        calibration.get("training_calendar_years") != window.training_calendar_years
        or calibration.get("availability_lag_days") != 2
    ):
        raise CalibrationError("training window or availability lag differs")
    if calibration.get("penalty") is not None or calibration.get("fit_intercept") is not False:
        raise CalibrationError("calibration must use no penalty and no intercept")
    if calibration.get("slope_constraint") != "nonnegative":
        raise CalibrationError("slope constraint differs")
    expected_edges = [i / 10 for i in range(11)]
    if calibration.get("reliability_bin_edges") != expected_edges:
        raise CalibrationError("reliability bins differ")
    if config.get("comparisons") != {"bootstrap_repetitions": 2000, "bootstrap_seed": 20260911}:
        raise CalibrationError("comparison settings differ")


def split_bindings(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate the code entries of a binding inventory from the data entries.

    Two inventory shapes are accepted. The archive shape lists every entry as
    ``{path, sha256}``; entries whose path ends in ``.py`` are code. The chain driver's
    shape lists the data sources as ``{path, sha256}`` and the package code as receipts
    ``{module, sha256, package_version}``. Code entries of either shape are declared
    provenance and are returned first; data entries are returned second.
    """
    code: list[dict[str, Any]] = []
    data: list[dict[str, Any]] = []
    for record in records:
        if "module" in record:
            code.append(dict(record))
        elif "path" in record and str(record["path"]).endswith(".py"):
            code.append(dict(record))
        elif "path" in record:
            data.append(dict(record))
        else:
            raise CalibrationError(f"binding entry names neither a path nor a module: {record}")
    return code, data


def validate_bindings(
    config: Mapping[str, Any], *, window: CalibrationWindow = SR03_WINDOW
) -> dict[str, Any]:
    """Check the declared source boundary and return the bound point-run manifest.

    The inventory must name exactly the design, the two SR02 market modules, the frozen
    point config, the point run manifest, its selected matches, the panel, the rule
    mapping and the implementation. Data entries are verified by hash under the
    workspace; the ``*.py`` entries are the archive's code provenance and are returned as
    ``declared_binding`` (porting guide rule 2), not checked against the package.
    """
    validate_config(config, require_frozen=False, window=window)
    bindings = config.get("bindings", {})
    records = bindings.get("files", [])
    if not records:
        raise CalibrationError("binding inventory is empty")
    declared_code, data_bindings = split_bindings(records)
    names = [record.get("path", record.get("module")) for record in records]
    if len(set(names)) != len(names):
        raise CalibrationError("binding inventory is duplicated")
    source = config["source"]
    required_data = {
        source["design_path"],
        source["primary_config_path"],
        source["point_manifest_path"],
        source["selected_matches_path"],
        source["panel_path"],
        source["rule_mapping_path"],
    }
    if {record["path"] for record in data_bindings} != required_data:
        raise CalibrationError("binding inventory differs from required source boundary")
    implementation = bindings.get("implementation_path", bindings.get("implementation"))
    if implementation is None:
        raise CalibrationError("binding inventory names no implementation")
    if "implementation_path" in bindings:
        # Archive shape: the two imported SR02 modules and the implementation itself.
        required_code = {
            "references/SR02_models/market.py",
            "references/SR02_models/runner.py",
            bindings["implementation_path"],
        }
        if {record.get("path") for record in declared_code} != required_code:
            raise CalibrationError("binding inventory differs from required code boundary")
    elif not declared_code:
        raise CalibrationError("binding inventory carries no code receipt")
    for record in data_bindings:
        path = resolve_under_root(record["path"], label="binding")
        if not path.is_file() or sha256(path) != record["sha256"]:
            raise CalibrationError(f"bound file differs: {record['path']}")

    primary_config_path = resolve_under_root(source["primary_config_path"], label="primary_config")
    point_manifest_path = resolve_under_root(source["point_manifest_path"], label="point_manifest")
    selected_path = resolve_under_root(source["selected_matches_path"], label="selected_matches")
    panel_path = resolve_under_root(source["panel_path"], label="panel")
    rule_path = resolve_under_root(source["rule_mapping_path"], label="rule_mapping")
    direct = {
        resolve_under_root(source["design_path"], label="design"): source["design_sha256"],
        primary_config_path: source["primary_config_sha256"],
        point_manifest_path: source["point_manifest_sha256"],
        selected_path: source["selected_matches_sha256"],
        panel_path: source["panel_sha256"],
        rule_path: source["rule_mapping_sha256"],
    }
    for path, expected in direct.items():
        if not path.is_file() or sha256(path) != expected:
            raise CalibrationError(f"source hash differs: {path}")
    manifest = json.loads(point_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise CalibrationError("primary point run is not complete")
    expected_manifest = {
        "config_sha256": source["primary_config_sha256"],
        "panel_sha256": source["panel_sha256"],
        "rule_mapping_sha256": source["rule_mapping_sha256"],
        "selected_matches_sha256": source["selected_matches_sha256"],
        "selected_matches_rows": source["selected_matches_rows"],
    }
    for field, expected in expected_manifest.items():
        if manifest.get(field) != expected:
            raise CalibrationError(f"primary point manifest differs: {field}")
    primary_config = json.loads(primary_config_path.read_text(encoding="utf-8"))
    if primary_config.get("proposal_status") != "frozen_for_real_execution":
        raise CalibrationError("primary point configuration is not frozen")
    # Which document says what the panel is depends on the run. For SR03's own window the
    # point run is the frozen SR02-C1 execution and the binding is SR02-C1's
    # `input.panel_sha256` (the default). A replayed point run over an extended panel, or
    # over another tour's panel, has a hash no frozen SR02-C1 can declare; the authority
    # is then the preceding stage's own run manifest, whose `panel_sha256` was checked
    # above, and the frozen hash is recorded as superseded rather than ignored.
    authority = source.get("panel_binding_authority", "frozen_primary_config")
    frozen_panel = primary_config.get("input", {}).get("panel_sha256")
    plan = config.get("year_plan")
    tour = str(config.get("tour", "ATP")).upper()
    if authority == "frozen_primary_config":
        if frozen_panel != source["panel_sha256"]:
            raise CalibrationError("primary point panel binding differs")
    elif authority == "point_run_manifest":
        if tour == "ATP" and plan is not None and int(plan["panel_end_year"]) <= 2024:
            raise CalibrationError(
                "panel_binding_authority = point_run_manifest is only for a panel that "
                "extends past the frozen SR02-C1 panel, or for another tour; this "
                f"year_plan ends in {plan['panel_end_year']} on the ATP"
            )
        if manifest.get("panel_sha256") != source["panel_sha256"]:
            raise CalibrationError("point run manifest panel binding differs")
    else:
        raise CalibrationError(f"unknown panel_binding_authority: {authority!r}")
    return {
        **manifest,
        "panel_binding_authority": authority,
        "frozen_primary_config_panel_sha256": frozen_panel,
        "tour": tour,
        "declared_binding": {"implementation": implementation, "files": declared_code},
    }


@dataclass(frozen=True)
class Dataset:
    rows: list[dict[str, Any]]
    outcomes: dict[str, int]
    refused_without_rule: list[str]


def load_dataset(
    config: Mapping[str, Any],
    *,
    window: CalibrationWindow = SR03_WINDOW,
    labels: bool = True,
    exclude_without_rule: bool = False,
) -> Dataset:
    """Join the selected point rows onto the panel and read the played outcomes.

    A selected row whose ``rule_status`` is not ``provided`` is refused (SR03) or, with
    ``exclude_without_rule``, dropped and listed (TIER01: ``carry_rule_rows`` refuses to
    invent a rule for an unmappable new event and SR02-C1 declares
    ``missing_rule = emit_point_probabilities_and_refuse_match_probability``).
    """
    source = config["source"]
    panel_rows = read_csv(resolve_under_root(source["panel_path"], label="panel"))
    panel = {row["match_id"]: row for row in panel_rows}
    if len(panel) != len(panel_rows):
        raise CalibrationError("panel contains duplicate match IDs")
    selected_rows = read_csv(
        resolve_under_root(source["selected_matches_path"], label="selected_matches")
    )
    if len(selected_rows) != source["selected_matches_rows"]:
        raise CalibrationError("selected match row count differs")
    if len({row["match_id"] for row in selected_rows}) != len(selected_rows):
        raise CalibrationError("selected matches contain duplicate IDs")

    result: list[dict[str, Any]] = []
    outcomes: dict[str, int] = {}
    refused_without_rule: list[str] = []
    for prediction in selected_rows:
        match_id = prediction["match_id"]
        if match_id not in panel:
            raise CalibrationError(f"selected match is absent from panel: {match_id}")
        source_row = panel[match_id]
        for field in METADATA_FIELDS:
            if prediction[field] != source_row[field]:
                raise CalibrationError(f"selected/panel metadata differs for {match_id}: {field}")
        date = parse_date(prediction["match_date"])
        source_season = int(prediction["source_season"])
        if (
            not window.date_year_min <= date.year <= window.date_year_max
            or not window.source_season_min <= source_season <= window.source_season_max
        ):
            raise CalibrationError(f"date or source season outside declared boundary: {match_id}")
        if int(prediction["player_a"]) >= int(prediction["player_b"]):
            raise CalibrationError(f"nonneutral player order: {match_id}")
        identity_tier = source_row["identity_tier"]
        if identity_tier not in ("primary", "provisional"):
            raise CalibrationError(f"invalid identity tier: {match_id}")
        played = parse_boolean(source_row["played"])
        completed = parse_boolean(source_row["completed"])
        source_agreement = parse_boolean(source_row["source_field_agreement"])
        annual_target_eligible = prediction["annual_target_eligible"]
        if annual_target_eligible not in ("0", "1"):
            raise CalibrationError(f"invalid annual target flag: {match_id}")
        expected_annual = (
            window.annual_eligible_floor_year <= date.year <= window.date_year_max
            and source_season == date.year
        )
        if (annual_target_eligible == "1") != expected_annual:
            raise CalibrationError(f"annual target eligibility differs: {match_id}")
        if prediction.get("rule_status") != "provided":
            if not exclude_without_rule:
                raise CalibrationError(f"selected match lacks an explicit rule: {match_id}")
            refused_without_rule.append(match_id)
            continue
        item: dict[str, Any] = {field: prediction[field] for field in METADATA_FIELDS}
        item.update(
            {
                "date": date,
                "identity_tier": identity_tier,
                "played": played,
                "completed": completed,
                "source_agreement": source_agreement,
                "annual_target_eligible": annual_target_eligible == "1",
            }
        )
        for family, field in FAMILIES:
            value = float(prediction[field])
            sr02_market.probabilities([value])
            item[f"raw_{family}"] = value
        ps_valid = parse_boolean(source_row["PS_valid"])
        item["pinnacle_raw_normalized"] = None
        if ps_valid:
            decimal_a = float(source_row["PS_decimal_a"])
            decimal_b = float(source_row["PS_decimal_b"])
            if not np.isfinite([decimal_a, decimal_b]).all() or decimal_a <= 1 or decimal_b <= 1:
                raise CalibrationError(f"invalid marked Pinnacle pair: {match_id}")
            item["pinnacle_raw_normalized"] = (1 / decimal_a) / (1 / decimal_a + 1 / decimal_b)
            sr02_market.probabilities([item["pinnacle_raw_normalized"]])
        result.append(item)
        if labels:
            if not played or source_row["a_won"] == "":
                # A blank a_won is an outcome not yet known (a prospective target): the
                # row is still predicted, and it trains and scores nothing.
                continue
            # outcome-history read: the panel's a_won for every played selected match,
            # every calendar year in the window, target years included.
            outcomes[match_id] = int(parse_boolean(source_row["a_won"]))
    return Dataset(
        sorted(result, key=lambda row: (row["match_date"], row["match_id"])),
        outcomes,
        refused_without_rule,
    )


def training_rows(
    rows: Sequence[dict[str, Any]],
    outcomes: Mapping[str, int],
    outer_year: int,
    *,
    window: CalibrationWindow = SR03_WINDOW,
) -> list[dict[str, Any]]:
    back = window.training_calendar_years
    low = dt.date(outer_year - back, 1, 1)
    high = dt.date(outer_year, 1, 1) - dt.timedelta(days=2)
    selected = [
        row
        for row in rows
        if low <= row["date"] <= high
        and row["identity_tier"] == "primary"
        and row["played"]
        and int(row["source_season"]) == row["date"].year
        and row["match_id"] in outcomes  # outcome-history read: resolved rows before the cutoff
    ]
    represented = {row["date"].year for row in selected}
    if represented != set(range(outer_year - back, outer_year)):
        raise CalibrationError(
            f"incomplete {back}-calendar-year training membership for {outer_year}"
        )
    if not selected or selected[-1]["date"] > high:
        raise CalibrationError(f"invalid training cutoff for {outer_year}")
    return selected


def target_rows(rows: Sequence[dict[str, Any]], outer_year: int) -> list[dict[str, Any]]:
    selected = [
        row
        for row in rows
        if row["date"].year == outer_year
        and int(row["source_season"]) == outer_year
        and row["played"]
        and row["annual_target_eligible"]
    ]
    if not selected:
        raise CalibrationError(f"no eligible targets for {outer_year}")
    return selected


def fit_and_predict(
    rows: Sequence[dict[str, Any]],
    outcomes: Mapping[str, int],
    outer_years: Sequence[int],
    *,
    window: CalibrationWindow = SR03_WINDOW,
    adapter: Any = sr02_market,
    event_sink: Callable[[dict[str, object]], None] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    predictions: list[dict[str, object]] = []
    fits: list[dict[str, object]] = []
    membership_rows: list[dict[str, object]] = []
    for outer_year in outer_years:
        training = training_rows(rows, outcomes, outer_year, window=window)
        targets = target_rows(rows, outer_year)
        membership_sha = key_hash(training)
        by_year: dict[str, dict[str, object]] = {}
        for year in range(outer_year - window.training_calendar_years, outer_year):
            annual = [row for row in training if row["date"].year == year]
            by_year[str(year)] = {"n": len(annual), "membership_sha256": key_hash(annual)}
        for row in training:
            membership_rows.append(
                {
                    "outer_year": outer_year,
                    "training_calendar_year": row["date"].year,
                    "match_date": row["match_date"],
                    "match_id": row["match_id"],
                    "source_key": row["source_key"],
                    "player_a": row["player_a"],
                    "player_b": row["player_b"],
                }
            )

        products: dict[str, Any] = {}
        for family, _ in FAMILIES:
            record: dict[str, object] = {
                "outer_year": outer_year,
                "family": family,
                "training_n": len(training),
                "training_min_date": training[0]["match_date"],
                "training_max_date": training[-1]["match_date"],
                "training_membership_sha256": membership_sha,
                "training_by_calendar_year": by_year,
            }
            try:
                product = adapter.fit(
                    np.array([row[f"raw_{family}"] for row in training], dtype=float),
                    # outcome-history read: training-year outcomes fit the slope.
                    np.array([outcomes[row["match_id"]] for row in training], dtype=float),
                    penalty=None,
                )
                fit_record = product.record()
                if (
                    fit_record.get("penalty") is not None
                    or fit_record.get("residual_coefficient") != 0.0
                    or fit_record.get("market_slope", -1) < 0
                    or int(fit_record.get("n", -1)) != len(training)
                    or not math.isfinite(float(fit_record.get("market_slope", math.nan)))
                ):
                    raise CalibrationError("calibration adapter returned a nonconforming fit")
            except Exception as exc:
                failed = {**record, "status": "failed", "error": str(exc)}
                if event_sink is not None:
                    event_sink(failed)
                raise CalibrationError(
                    f"calibration fit failed for {outer_year}/{family}: {exc}"
                ) from exc
            products[family] = product
            complete = {**record, "status": "complete", "fit": fit_record}
            fits.append(complete)
            if event_sink is not None:
                event_sink(complete)

        calibrated = {
            family: products[family].predict(
                np.array([row[f"raw_{family}"] for row in targets], dtype=float)
            )
            for family, _ in FAMILIES
        }
        for values in calibrated.values():
            sr02_market.probabilities(values)
        for index, row in enumerate(targets):
            prediction: dict[str, object] = {
                field: row[field] for field in (*METADATA_FIELDS, "identity_tier")
            }
            prediction["calibration_year"] = outer_year
            for family, _ in FAMILIES:
                prediction[f"raw_{family}"] = row[f"raw_{family}"]
                prediction[f"calibrated_{family}"] = float(calibrated[family][index])
            prediction["pinnacle_raw_normalized"] = row["pinnacle_raw_normalized"]
            predictions.append(prediction)
    return predictions, fits, membership_rows


def cohort(row: Mapping[str, Any], name: str) -> bool:
    primary = row["identity_tier"] == "primary"
    return {
        "primary": primary,
        "completed_only": primary and row["completed"],
        "source_agreement": primary and row["source_agreement"],
        "provisional_extension": row["identity_tier"] in ("primary", "provisional"),
    }[name]


def reliability(
    rows: Sequence[Mapping[str, Any]], model: str, edges: Sequence[float]
) -> list[dict[str, object]]:
    output = []
    for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        selected = [
            row
            for row in rows
            if lower <= row[model] < upper or index == len(edges) - 2 and row[model] == upper
        ]
        output.append(
            {
                "scope": "sports_2014_2024",
                "cohort": "primary",
                "model": model,
                "bin": index,
                "lower": lower,
                "upper": upper,
                "n": len(selected),
                "mean_prediction": float(np.mean([row[model] for row in selected]))
                if selected
                else "",
                # outcome-history read: scored outcome rate per reliability bin.
                "outcome_rate": float(np.mean([row["a_won"] for row in selected]))
                if selected
                else "",
            }
        )
    return output


def evaluate(
    source_rows: Sequence[dict[str, Any]],
    outcomes: Mapping[str, int],
    predictions: Sequence[Mapping[str, object]],
    *,
    edges: Sequence[float],
    bootstrap_seed: int,
    bootstrap_repetitions: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object], dict[str, object]]:
    """Proper scores, reliability bins and paired comparisons on the calibrated years.

    This is a scoring read of the outer years' outcomes (``a_won`` joined onto every
    prediction), so with target years among the predictions it scores the target years.
    """
    source = {row["match_id"]: row for row in source_rows}
    if len(source) != len(source_rows) or len({row["match_id"] for row in predictions}) != len(
        predictions
    ):
        raise CalibrationError("source or prediction identity is duplicated")
    joined: list[dict[str, Any]] = []
    for prediction in predictions:
        match_id = str(prediction["match_id"])
        if match_id not in source or match_id not in outcomes:
            raise CalibrationError(
                f"prediction lacks a scoring source or resolved outcome: {match_id}"
            )
        # outcome-history read: the scored outcome of every calibrated outer-year row.
        row = {**source[match_id], **prediction, "a_won": outcomes[match_id]}
        joined.append(row)

    metrics: list[dict[str, object]] = []
    comparisons: dict[str, object] = {}
    cohort_names = ("primary", "completed_only", "source_agreement", "provisional_extension")
    comparison_pairs = (
        ("calibrated_dynamic", "raw_dynamic"),
        ("calibrated_dynamic", "calibrated_unadjusted"),
        ("calibrated_unadjusted", "raw_unadjusted"),
        ("calibrated_simple_unadjusted", "raw_simple_unadjusted"),
    )
    for name in cohort_names:
        population = [row for row in joined if cohort(row, name)]
        if not population:
            raise CalibrationError(f"empty evaluation cohort: {name}")
        years = sorted({int(row["calibration_year"]) for row in population})
        for year in [None, *years]:
            selected = [
                row for row in population if year is None or int(row["calibration_year"]) == year
            ]
            for model in MODEL_FIELDS:
                score = sr02_market.scores(
                    np.array([row[model] for row in selected], dtype=float),
                    np.array(
                        [row["a_won"] for row in selected], dtype=float
                    ),  # outcome-history read
                )
                metrics.append(
                    {
                        "scope": "sports_2014_2024",
                        "cohort": name,
                        "year": "pooled" if year is None else year,
                        "model": model,
                        **score,
                    }
                )
        if name == "primary":
            for treatment, control in comparison_pairs:
                comparisons[f"sports_2014_2024/{name}/{treatment}_minus_{control}"] = (
                    sr02_runner.comparison(
                        population,
                        treatment,
                        control,
                        seed=bootstrap_seed,
                        repetitions=bootstrap_repetitions,
                    )
                )

    primary = [row for row in joined if cohort(row, "primary")]
    priced = [row for row in primary if row["pinnacle_raw_normalized"] is not None]
    if not priced:
        raise CalibrationError("empty valid-price descriptive subset")
    priced_models = (*MODEL_FIELDS, "pinnacle_raw_normalized")
    for year in [None, *sorted({int(row["calibration_year"]) for row in priced})]:
        selected = [row for row in priced if year is None or int(row["calibration_year"]) == year]
        for model in priced_models:
            score = sr02_market.scores(
                np.array([row[model] for row in selected], dtype=float),
                np.array([row["a_won"] for row in selected], dtype=float),  # outcome-history read
            )
            metrics.append(
                {
                    "scope": "priced_primary_2014_2024",
                    "cohort": "primary_valid_pinnacle",
                    "year": "pooled" if year is None else year,
                    "model": model,
                    **score,
                }
            )

    bins = [item for model in MODEL_FIELDS for item in reliability(primary, model, edges)]
    counts = {
        "prediction_rows": len(joined),
        "resolved_outcome_rows": len(joined),
        "unresolved_outcome_rows": 0,
        "cohorts": {name: sum(cohort(row, name) for row in joined) for name in cohort_names},
        "primary_valid_pinnacle_rows": len(priced),
        "primary_missing_pinnacle_rows": len(primary) - len(priced),
        "price_control_scope": "primary_valid_pinnacle_only_quote_timing_unresolved",
    }
    return metrics, bins, comparisons, counts
