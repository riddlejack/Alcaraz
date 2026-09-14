"""Native T2 repair after archive R28: every discovered source date precedes the cutoff.

PASS CRITERION (kept from C2, evaluated on the synthetic run): discover every date-valued
column from the feature header AND the column dictionary's names, groups, roles and
declared date dtypes (NumPy datetime kind M, timezone datetime64 and Arrow date types);
classify ``match_date`` as the target date, ``eligible_through_date`` as the cutoff and
``date_basis`` / ``archive_date_basis`` as textual date-basis metadata; every other
discovered date is a source or snapshot date and must be <= ``eligible_through_date``
on every row. An unknown date role fails closed (it is audited as a source date, never
dropped). The cutoff must itself precede the target date. Emit coverage and the
min/max cutoff-minus-source lag per discovered column. Zero violations on the sample.

NEGATIVE CONTROLS (same audit function, in-memory copies): a new future source date, a
renamed one, an opaque column whose dictionary role is ``source_date``, an opaque column
listed in a dictionary ``source_date_columns`` group, and one real row whose
``elo_latest_source_date`` is moved one day past its cutoff each fail the audit and
name the column. The R28 counterexample, an opaque provenance column declared
``datetime64[ns]``, and nested dictionary variants must also fail on a future date.

NOT COVERED HERE: C2 T2b (satellite circuit dating, ``tier_stream``) and T2c (base and
tier Elo logit replay at 1e-12, ``tier_elo``) need the tier stages, which the base
synthetic sample does not run. Dates hidden in serialized free text are outside the
header/dictionary enumeration, as in C2. Opaque columns without a date name, role or
declared date dtype remain outside that enumeration.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pytest

from tests.gate_support import must_reject, read_csv, read_json

TARGET_DATE = "match_date"
CUTOFF = "eligible_through_date"
TEXTUAL_BASIS = frozenset({"date_basis", "archive_date_basis"})
DATE_TOKENS = frozenset({"date", "dates", "datetime", "timestamp"})


def _date(value: str | None) -> dt.date | None:
    text = (value or "").strip()
    return dt.date.fromisoformat(text[:10]) if text else None


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", text.lower()))


def _date_dtype(value: str) -> bool:
    """Recognize declared calendar types without interpreting column values as schema."""
    try:
        if np.dtype(value).kind == "M":
            return True
    except TypeError, ValueError:
        pass
    # Timezone-aware pandas declarations are not NumPy dtypes; Arrow's date32/date64
    # spellings likewise carry their semantics in the declared type, not a date token.
    return bool(
        re.fullmatch(r"datetime64\[(?:s|ms|us|ns),\s*[^\[\]]+\]", value)
        or re.fullmatch(r"date(?:32\[day\]|64\[ms\])(?:\[pyarrow\])?", value)
    )


def discover_dates(header: Sequence[str], dictionary: Any) -> dict[str, dict[str, Any]]:
    """Every header column whose name or dictionary description names a date, classified."""
    names = set(header)
    roles: dict[str, set[str]] = defaultdict(set)
    dtypes: dict[str, set[str]] = defaultdict(set)

    def describe(name: str, descriptor: Mapping[str, Any]) -> None:
        roles[name].update(
            str(descriptor.get(k, "")) for k in ("role", "type", "dtype", "description")
        )
        dtypes[name].update(str(descriptor[k]) for k in ("type", "dtype") if k in descriptor)

    def walk(value: Any, context: str) -> None:
        if isinstance(value, dict):
            declared = value.get("name") or value.get("column")
            if declared in names:
                describe(declared, value)
            for key, child in value.items():
                if key in names:
                    roles[key].add(context)
                    if isinstance(child, dict):
                        describe(key, child)
                walk(child, f"{context} {key}")
        elif isinstance(value, list):
            for child in value:
                walk(child, context)
        elif isinstance(value, str) and value in names:
            roles[value].add(context)

    walk(dictionary, "")
    classified: dict[str, dict[str, Any]] = {}
    for name in header:
        descriptor = " ".join(roles[name])
        if not (
            DATE_TOKENS & (_tokens(name) | _tokens(descriptor))
            or any(_date_dtype(dtype) for dtype in dtypes[name])
        ):
            continue
        if name == TARGET_DATE:
            category = "target_date"
        elif name == CUTOFF:
            category = "cutoff"
        elif name in TEXTUAL_BASIS:
            category = "textual_date_basis"
        else:
            category = "source_or_snapshot_date"  # unknown roles fail closed
        classified[name] = {"category": category, "dictionary_roles": sorted(roles[name])}
    assert CUTOFF in classified, "cutoff date column absent"
    assert TARGET_DATE in classified, "target date column absent"
    return classified


def audit_dates(
    header: Sequence[str], rows: Sequence[Mapping[str, str]], dictionary: Any
) -> dict[str, Any]:
    discovery = discover_dates(header, dictionary)
    present = [c for c, meta in discovery.items() if meta["category"] == "source_or_snapshot_date"]
    violations: list[dict[str, Any]] = []
    max_lag: dict[str, int] = {}
    min_lag: dict[str, int] = {}
    populated: dict[str, int] = defaultdict(int)
    for row in rows:
        try:
            cutoff = _date(row.get(CUTOFF))
            target = _date(row.get(TARGET_DATE))
        except ValueError:
            cutoff = target = None
        if cutoff is None or target is None:
            violations.append({"match_id": row.get("match_id"), "reason": "missing/invalid cutoff"})
            continue
        if not cutoff < target:
            violations.append(
                {
                    "match_id": row.get("match_id"),
                    "column": CUTOFF,
                    "reason": "cutoff does not precede the target date",
                }
            )
        for column in present:
            try:
                source = _date(row.get(column))
            except ValueError:
                violations.append(
                    {"match_id": row.get("match_id"), "column": column, "reason": "invalid date"}
                )
                continue
            if source is None:
                continue
            populated[column] += 1
            lag = (cutoff - source).days
            max_lag[column] = max(max_lag.get(column, lag), lag)
            min_lag[column] = min(min_lag.get(column, lag), lag)
            if lag < 0:
                violations.append(
                    {
                        "match_id": row.get("match_id"),
                        "column": column,
                        "source_date": source.isoformat(),
                        "eligible_through": cutoff.isoformat(),
                        "days_after_cutoff": -lag,
                    }
                )
    return {
        "rows_audited": len(rows),
        "columns": present,
        "discovery": discovery,
        "per_column_lag_table": {
            c: {
                "populated_rows": populated[c],
                "max_lag_days": max_lag.get(c),
                "min_lag_days": min_lag.get(c),
            }
            for c in present
        },
        "violation_count": len(violations),
        "violations_sample": violations[:50],
    }


def assert_date_audit(result: Mapping[str, Any]) -> None:
    assert result["violation_count"] == 0, (
        f"{result['violation_count']} date violations: {result['violations_sample'][:3]}"
    )


def _inputs(sample_run: Mapping[str, Any]) -> tuple[list[str], list[dict[str, str]], Any]:
    features = sample_run["run_root"] / "features"
    header, rows = read_csv(features / "features.csv")
    return header, rows, read_json(features / "column_dictionary.json")


# ------------------------------------------------------------------ clean behaviour


def test_every_source_date_precedes_its_cutoff(sample_run: dict[str, Any]) -> None:
    header, rows, dictionary = _inputs(sample_run)
    result = audit_dates(header, rows, dictionary)
    assert_date_audit(result)
    assert result["rows_audited"] == len(rows) > 1000
    # The synthetic feature table carries the archive's five source/snapshot dates and
    # the discovery found every one of them from the header alone and the dictionary.
    assert set(result["columns"]) >= {
        "ranking_snapshot_date",
        "elo_latest_source_date",
        "count_latest_source_date",
        "workload_latest_source_date",
        "lagged_market_latest_source_date",
    }
    for column, lag in result["per_column_lag_table"].items():
        assert lag["populated_rows"] > 0, column
        assert lag["min_lag_days"] >= 0, column
    audit_only = set(dictionary["audit_only_columns"])
    assert all(column in audit_only for column in result["columns"]), (
        "a source date column is not declared audit-only"
    )
    assert result["discovery"][CUTOFF]["category"] == "cutoff"
    assert result["discovery"][TARGET_DATE]["category"] == "target_date"


# ------------------------------------------------------------------ negative controls


@pytest.mark.parametrize(
    "dtype",
    [
        "datetime64[ns]",
        "datetime64[D]",
        "<M8[ms]",
        "M8[us]",
        "datetime64[ns, UTC]",
        "timestamp[ns, tz=UTC]",
        "date32[day]",
        "date64[ms][pyarrow]",
    ],
)
@pytest.mark.parametrize("layout", ["keyed", "nested_named", "nested_column"])
def test_r28_opaque_declared_date_dtype_uses_the_same_audit(dtype: str, layout: str) -> None:
    # Archive R28's original rejected control: 2005-01-13 is three days after this
    # row's cutoff. No source/date word in either the column name or declared role.
    name = "independent_opaque_release_clock"
    descriptor = {"dtype": dtype, "role": "provenance"}
    if layout == "keyed":
        dictionary = {"columns": {name: descriptor}}
    elif layout == "nested_named":
        dictionary = {"schema": {"groups": [{"fields": [{"name": name, **descriptor}]}]}}
    else:
        dictionary = {"schema": {"groups": [{"fields": [{"column": name, **descriptor}]}]}}
    dictionary = json.loads(json.dumps(dictionary))
    row = {
        "match_id": "2005-301/20",
        TARGET_DATE: "2005-01-12",
        CUTOFF: "2005-01-10",
        name: "2005-01-10",
    }
    clean = audit_dates(list(row), [row], dictionary)
    assert_date_audit(clean)
    assert clean["columns"] == [name]
    assert clean["per_column_lag_table"][name] == {
        "populated_rows": 1,
        "max_lag_days": 0,
        "min_lag_days": 0,
    }
    future = audit_dates(list(row), [{**row, name: "2005-01-13"}], dictionary)
    must_reject(lambda: assert_date_audit(future), "1 date violations")
    assert future["violations_sample"][0]["column"] == name
    assert future["violations_sample"][0]["days_after_cutoff"] == 3


@pytest.mark.parametrize("dtype", ["timedelta64[ns]", "float64", "object", "str"])
def test_opaque_non_calendar_dtype_does_not_infer_schema_from_contents(dtype: str) -> None:
    name = "opaque_clock"
    row = {TARGET_DATE: "2005-01-12", CUTOFF: "2005-01-10", name: "2005-01-13"}
    dictionary = {"columns": {name: {"dtype": dtype, "role": "provenance"}}}
    result = audit_dates(list(row), [row], dictionary)
    assert_date_audit(result)
    assert result["columns"] == []


def test_a_future_source_date_fails_the_audit_under_every_disguise(
    sample_run: dict[str, Any],
) -> None:
    header, rows, dictionary = _inputs(sample_run)
    row = dict(rows[0])
    day_after = (_date(row[CUTOFF]) + dt.timedelta(days=1)).isoformat()
    detected = []
    for mode in ("new", "renamed", "dictionary_role", "dictionary_group"):
        candidate = dict(row)
        planted_dictionary = copy.deepcopy(dictionary)
        if mode == "new":
            name = "new_signal_source_date"
        elif mode == "renamed":
            candidate.pop("elo_latest_source_date")
            name = "renamed_signal_source_date"
        elif mode == "dictionary_role":
            name = "opaque_observation_clock"
            planted_dictionary.setdefault("columns", {})[name] = {
                "role": "source_date",
                "dtype": "date",
            }
        else:
            name = "opaque_observation_clock"
            planted_dictionary["source_date_columns"] = [name]
        candidate[name] = day_after
        planted_header = [c for c in header if c in candidate] + [name]
        # A dictionary copy round-trips through JSON like the file the chain writes.
        planted_dictionary = json.loads(json.dumps(planted_dictionary))
        result = audit_dates(planted_header, [candidate], planted_dictionary)
        must_reject(lambda result=result: assert_date_audit(result), "date violations")
        assert any(v.get("column") == name for v in result["violations_sample"]), mode
        detected.append(mode)
    assert detected == ["new", "renamed", "dictionary_role", "dictionary_group"]
    # An opaque name with no dictionary role is invisible to a name-based discovery: the
    # gate's coverage stops at the header/dictionary enumeration, as C2 declared.
    unseen = dict(row, opaque_observation_clock=day_after)
    result = audit_dates([*header, "opaque_observation_clock"], [unseen], dictionary)
    assert "opaque_observation_clock" not in result["columns"]


def test_one_real_row_moved_past_its_cutoff_fails_the_audit(sample_run: dict[str, Any]) -> None:
    header, rows, dictionary = _inputs(sample_run)
    index = next(i for i, r in enumerate(rows) if r["elo_latest_source_date"])
    planted = [dict(r) for r in rows[: index + 1]]
    planted[index]["elo_latest_source_date"] = (
        _date(planted[index][CUTOFF]) + dt.timedelta(days=1)
    ).isoformat()
    result = audit_dates(header, planted, dictionary)
    must_reject(lambda: assert_date_audit(result), "1 date violations")
    violation = result["violations_sample"][0]
    assert violation["column"] == "elo_latest_source_date"
    assert violation["days_after_cutoff"] == 1
    assert violation["match_id"] == rows[index]["match_id"]
    # A cutoff on or after the target date is refused too.
    late_cutoff = [dict(rows[0], **{CUTOFF: rows[0][TARGET_DATE]})]
    result = audit_dates(header, late_cutoff, dictionary)
    must_reject(lambda: assert_date_audit(result), "date violations")
    assert result["violations_sample"][0]["column"] == CUTOFF
