"""Gate T13 (Lane C2, admitted by archive R15/R17): univariate label-copy alarm.

PASS CRITERION (kept from C2, evaluated on the synthetic run): screen every numeric-valued
column of the feature table, excluding only the dictionary's identifier/split columns,
against the aligned-primary outcome in each target year and require
max(AUC, 1 - AUC) <= 0.85 (a constant column scores 0.5). Temporal-copy sentinel: the
same bound holds against each of player A's and player B's outcome at their next
strictly later dated match. Record every feature/year result, the excluded and the
unscorable cohorts (fewer than 30 paired rows or one class); an unscorable feature is
not certified. The 0.85 threshold is a conservative alarm above ordinary Elo-like
discrimination near 0.70, not a validity proof; string or category columns are not
univariate-certified. The AUC is the Mann-Whitney rank statistic with average ranks for
ties (numpy), which equals ``sklearn.metrics.roc_auc_score``.

NEGATIVE CONTROLS (same screen and assertion, in-memory copies of the feature table):
the true label, its reversed orientation and player A's next-match outcome
(orientation-corrected when A is that match's B) planted as feature columns each score
1.0 discrimination against their own target in every target year and fail the screen.
A four-row oracle checks the shifted-target construction itself.

NOT COVERED HERE: nothing of the C2 criterion; the screen is a monotone numeric
current/next-player copy alarm, not a general future-data detector, as C2 declared.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from tests.gate_support import aligned_primary, chain_document, must_reject, read_csv, read_json

THRESHOLD = 0.85
MIN_N = 30


def auc(scores: np.ndarray, outcomes: np.ndarray) -> float:
    """Area under the ROC curve as the normalized Mann-Whitney U with average tie ranks."""
    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(len(scores), dtype=np.float64)
    boundaries = np.flatnonzero(np.diff(sorted_scores)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(scores)]))
    for start, end in zip(starts, ends, strict=True):
        ranks[order[start:end]] = (start + end + 1) / 2.0  # 1-based average rank
    positives = outcomes == 1
    n_pos = int(positives.sum())
    n_neg = len(outcomes) - n_pos
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def next_player_targets(
    rows: Sequence[Mapping[str, str]], labels: Sequence[int]
) -> tuple[dict[str, list[int | None]], dict[str, list[dict[str, str] | None]]]:
    """Each focal player's win at their next strictly later dated match, or None.

    Same-date rows are never ordered causally; when several matches share the next date
    the lexically first match_id is the reproducible sentinel source.
    """
    histories: dict[str, list[tuple[str, str, int, int]]] = defaultdict(list)
    for index, (row, label) in enumerate(zip(rows, labels, strict=True)):
        histories[row["player_a"]].append((row["match_date"], row["match_id"], index, int(label)))
        histories[row["player_b"]].append(
            (row["match_date"], row["match_id"], index, 1 - int(label))
        )
    for history in histories.values():
        history.sort()
    dates = {player: [entry[0] for entry in history] for player, history in histories.items()}
    shifted: dict[str, list[int | None]] = {}
    links: dict[str, list[dict[str, str] | None]] = {}
    for side in ("a", "b"):
        values: list[int | None] = []
        sources: list[dict[str, str] | None] = []
        for row in rows:
            player = row[f"player_{side}"]
            position = bisect.bisect_right(dates[player], row["match_date"])
            if position == len(histories[player]):
                values.append(None)
                sources.append(None)
            else:
                date, match_id, _, outcome = histories[player][position]
                values.append(outcome)
                sources.append(
                    {"player": player, "source_match_id": match_id, "source_match_date": date}
                )
        shifted[f"next_player_{side}"] = values
        links[f"next_player_{side}"] = sources
    return shifted, links


def screen(
    rows: Sequence[Mapping[str, str]],
    header: Sequence[str],
    labels: Sequence[int],
    excluded_columns: set[str],
    years: Sequence[int],
) -> dict[str, Any]:
    shifted, _ = next_player_targets(rows, labels)
    targets = {"current_label": list(labels), **shifted}
    row_years = np.asarray([int(row["calendar_year"]) for row in rows])
    values: dict[str, np.ndarray] = {}
    excluded: dict[str, str] = {}
    for column in header:
        if column in excluded_columns:
            excluded[column] = "dictionary identifier/split column"
            continue
        numeric = []
        for row in rows:
            raw = row[column]
            try:
                value = float(raw) if raw != "" else math.nan
            except ValueError:
                excluded[column] = "contains nonnumeric category/text values"
                break
            if raw != "" and not math.isfinite(value):
                raise AssertionError(f"nonfinite populated feature {column}")
            numeric.append(value)
        else:
            values[column] = np.asarray(numeric, dtype=np.float64)
    records: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    unscorable: list[dict[str, Any]] = []
    for year in years:
        in_year = row_years == year
        for target_name, target in targets.items():
            yy = np.asarray([math.nan if y is None else y for y in target], dtype=np.float64)
            for column, feature in values.items():
                mask = in_year & np.isfinite(feature) & np.isfinite(yy)
                n = int(mask.sum())
                record: dict[str, Any] = {
                    "year": year,
                    "feature": column,
                    "target": target_name,
                    "n": n,
                    "missing_pairs": int(in_year.sum()) - n,
                }
                if n < MIN_N or len(np.unique(yy[mask])) < 2:
                    record["reason"] = f"fewer than {MIN_N} pairs or one outcome class"
                    unscorable.append(record)
                    continue
                area = auc(feature[mask], yy[mask].astype(np.int64))
                discrimination = max(area, 1.0 - area)
                record.update({"auc": area, "discrimination": discrimination})
                records.append(record)
                if discrimination > THRESHOLD:
                    violations.append(record)
    assert all(any(r["year"] == year for r in records) for year in years), (
        "a target year was not screened"
    )
    return {
        "threshold": THRESHOLD,
        "minimum_pairs": MIN_N,
        "records": records,
        "violations": violations,
        "excluded": excluded,
        "unscorable": unscorable,
        "columns_screened": len(values),
        "years": list(years),
    }


def assert_screen(result: Mapping[str, Any]) -> None:
    assert not result["violations"], (
        f"univariate copy alarm: {[(v['year'], v['feature'], v['target'], v['discrimination']) for v in result['violations'][:5]]}"
    )


def _inputs(
    sample_run: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, str]], list[int], set[str], list[int]]:
    features = sample_run["run_root"] / "features"
    years = [int(y) for y in chain_document(sample_run)["year_plan"]["target_years"]]
    header, feature_rows = read_csv(features / "features.csv")
    rows = [r for r in feature_rows if int(r["calendar_year"]) in years and aligned_primary(r)]
    _, label_rows = read_csv(features / "labels.csv")
    outcome = {(r["calendar_year"], r["match_id"]): int(r["a_won"]) for r in label_rows}
    assert len(outcome) == len(label_rows), "duplicate label keys"
    labels = [outcome[(r["calendar_year"], r["match_id"])] for r in rows]
    excluded = set(read_json(features / "column_dictionary.json")["identifier_and_split_columns"])
    return header, rows, labels, excluded, years


# ------------------------------------------------------------------ clean behaviour


def test_the_auc_matches_the_closed_form_on_small_cases() -> None:
    assert auc(np.asarray([0.1, 0.4, 0.35, 0.8]), np.asarray([0, 0, 1, 1])) == 0.75
    assert auc(np.asarray([1.0, 1.0, 1.0, 1.0]), np.asarray([0, 1, 0, 1])) == 0.5
    assert auc(np.asarray([0.2, 0.2, 0.9, 0.9]), np.asarray([0, 0, 1, 1])) == 1.0
    assert auc(np.asarray([0.9, 0.9, 0.2, 0.2]), np.asarray([0, 0, 1, 1])) == 0.0
    assert auc(np.asarray([0.5, 0.5, 0.7]), np.asarray([0, 1, 1])) == 0.75


def test_no_numeric_feature_copies_the_current_or_next_outcome(sample_run: dict[str, Any]) -> None:
    header, rows, labels, excluded, years = _inputs(sample_run)
    assert len(rows) > 1000 and sum(labels) not in (0, len(labels))
    result = screen(rows, header, labels, excluded, years)
    assert_screen(result)
    assert result["columns_screened"] >= 200
    assert set(result["excluded"]) >= excluded
    current = [r for r in result["records"] if r["target"] == "current_label"]
    assert {r["year"] for r in current} == set(years)
    assert {r["feature"] for r in current} >= {"elo_overall_logit", "ps_probability_a"}
    # The market and the Elo difference are informative but far from a label copy.
    elo = max(r["discrimination"] for r in current if r["feature"] == "elo_overall_logit")
    assert 0.55 < elo <= THRESHOLD
    assert all(r["n"] >= MIN_N for r in current)
    for target in ("next_player_a", "next_player_b"):
        scored = [r for r in result["records"] if r["target"] == target]
        assert {r["year"] for r in scored} == set(years), target


# ------------------------------------------------------------------ negative controls


def test_the_shifted_target_oracle() -> None:
    oracle = [
        {"player_a": "10", "player_b": "20", "match_date": "2020-01-01", "match_id": "m1"},
        {"player_a": "10", "player_b": "30", "match_date": "2020-01-01", "match_id": "m0"},
        {"player_a": "5", "player_b": "10", "match_date": "2020-01-02", "match_id": "m2"},
        {"player_a": "20", "player_b": "30", "match_date": "2020-01-03", "match_id": "m3"},
    ]
    shifted, links = next_player_targets(oracle, [1, 1, 1, 0])
    # A (player 10) loses on Jan 2 as that match's B; same-date rows are never sources.
    assert shifted["next_player_a"] == [0, 0, None, None]
    assert shifted["next_player_b"] == [0, 1, None, None]
    assert links["next_player_a"][0] == {
        "player": "10",
        "source_match_id": "m2",
        "source_match_date": "2020-01-02",
    }


def test_each_planted_label_copy_trips_the_screen(sample_run: dict[str, Any]) -> None:
    header, rows, labels, excluded, years = _inputs(sample_run)
    shifted, links = next_player_targets(rows, labels)
    y = np.asarray(labels)
    controls = {}
    for name, planted, target in (
        ("true_label", list(y), "current_label"),
        ("reversed_true_label", list(1 - y), "current_label"),
        ("next_same_player_label", shifted["next_player_a"], "next_player_a"),
    ):
        column = f"planted_{name}"
        copied = [
            dict(row, **{column: "" if v is None else str(v)})
            for row, v in zip(rows, planted, strict=True)
        ]
        result = screen(copied, [*header, column], labels, excluded, years)
        message = must_reject(lambda result=result: assert_screen(result), "univariate copy alarm")
        hits = [r for r in result["violations"] if r["feature"] == column and r["target"] == target]
        assert {r["year"] for r in hits} == set(years), (name, message)
        assert all(r["discrimination"] == 1.0 for r in hits), name
        # The planted column is the only alarm: the clean columns still pass.
        assert {r["feature"] for r in result["violations"]} == {column}, name
        controls[name] = {
            "years": sorted({r["year"] for r in hits}),
            "current_label_discrimination": [
                r["discrimination"]
                for r in result["records"]
                if r["feature"] == column and r["target"] == "current_label"
            ],
        }
    # The next-outcome copy is not a copy of the current label: its current-label
    # discrimination is ordinary, so only the temporal sentinel can catch it.
    assert all(
        d < THRESHOLD for d in controls["next_same_player_label"]["current_label_discrimination"]
    )
    assert sum(link is not None for link in links["next_player_a"]) > len(rows) // 2
