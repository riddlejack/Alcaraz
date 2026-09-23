"""Ported from the archive's ``MULTI01_features/test_features.py``, the parent of the
TIER01/WTA02 revisions of ``build_features.py``.

Substance is unchanged; the fixtures import from the package instead of loading
``build_features`` and ``MULTI01_ranking_lookup`` off ``sys.path``. One test is added for
the WTA02 revision of ``CountHistory.player_summary``: a one-sided count history leaves
``missing_{domain}`` at 0 and is counted, not asserted away.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections import Counter
from pathlib import Path

import pytest

from tennislab.chain.common import ChainError
from tennislab.chronology.ranking_lookup import LookupRequest, RankingLookup
from tennislab.features import base as bf

PARAMETERS = {
    "source_year_min": 2005,
    "source_year_max": 2024,
    "lag_calendar_days": 2,
    "count_prior_denominator_units": 50.0,
    "count_half_life_days": 180.0,
    "initial_serve_rate": 0.6,
    "initial_return_rate": 0.4,
    "elo_initial_rating": 1500.0,
    "elo_k": 32.0,
    "elo_scale": 400.0,
    "workload_windows_days": [7, 28],
    "rest_days_cap": 90,
    "ranking_stale_days": 14,
    "primary_history_identity_tier": "primary",
}


def counts(seed: int = 0) -> bf.Counts:
    return bf.Counts(
        ace=5 + seed,
        double_faults=3,
        serve_points=60 + seed,
        first_in=36,
        first_won=24,
        second_won=11,
        break_points_saved=4,
        break_points_faced=6,
    )


def record(
    match_id: str,
    day: dt.date,
    a: int,
    b: int,
    *,
    a_won: bool = True,
    tier: str = "primary",
    with_counts: bool = True,
    ps: float | None = 0.6,
    surface: str = "Hard",
    court: str = "Outdoor",
) -> bf.Record:
    assert a < b
    return bf.Record(
        match_id=match_id,
        match_date=day,
        calendar_year=day.year,
        source_season=day.year,
        tourney_id=f"{day.year}-T",
        tourney_name="Fixture",
        tourney_level="A",
        competition_type="individual_tour",
        round="R32",
        surface=surface,
        best_of=3,
        court_recorded=court,
        player_a=a,
        player_b=b,
        a_won=a_won,
        identity_tier=tier,
        status="completed",
        date_basis="qualified_reported_match_date",
        archive_date_basis="event_anchor_only_no_match_date_or_clock",
        source_field_agreement=True,
        counts_a=counts(0) if with_counts else None,
        counts_b=counts(2) if with_counts else None,
        ps_probability_a=ps,
    )


def rank_row(day: dt.date, rank: int, player: int, points: int | None, line: int) -> dict[str, str]:
    return {
        "effective_date": day.isoformat(),
        "rank": str(rank),
        "player_id": str(player),
        "ranking_points": "" if points is None else str(points),
        "source_member": "fixture.csv",
        "source_physical_line": str(line),
    }


def rank_map(records: list[bf.Record]) -> dict[tuple[dt.date, int], object]:
    players = sorted({player for item in records for player in (item.player_a, item.player_b)})
    first = min(item.match_date for item in records) - dt.timedelta(days=7)
    rows = [
        rank_row(first, index + 1, player, 1000 - index, index + 2)
        for index, player in enumerate(players)
    ]
    lookup = RankingLookup.from_rows(rows)
    keys = sorted(
        {(item.match_date, player) for item in records for player in (item.player_a, item.player_b)}
    )
    results = lookup.lookup_many([LookupRequest(day, player) for day, player in keys])
    return dict(zip(keys, results, strict=True))


def features(records: list[bf.Record]) -> dict[str, dict[str, object]]:
    return {
        item.match_id: row for item, row in bf.stream_rows(records, rank_map(records), PARAMETERS)
    }


def test_joint_second_serve_bound_rejects_impossible_counts() -> None:
    invalid = bf.Counts(1, 5, 20, 15, 10, 1, 0, 0)
    with pytest.raises(ChainError, match="joint second-serve"):
        invalid.validate()


def test_exact_d_minus_two_boundary_and_future_label_isolation() -> None:
    d0 = dt.date(2020, 1, 1)
    source = record("s", d0, 1, 3, a_won=True)
    day_one = record("d1", d0 + dt.timedelta(days=1), 1, 2, a_won=False)
    day_two = record("d2", d0 + dt.timedelta(days=2), 1, 2, a_won=False)
    observed = features([source, day_one, day_two])
    assert observed["d1"]["elo_overall_logit"] == 0.0
    assert observed["d2"]["elo_overall_logit"] > 0.0

    mutated = [
        source,
        bf.replace(day_one, a_won=True, counts_a=counts(4)),
        bf.replace(day_two, a_won=True, counts_b=counts(5)),
    ]
    changed = features(mutated)
    for key in ("d1", "d2"):
        for column in bf.SIGNED_BASES + bf.linear_interactions() + bf.rank_global_interactions():
            assert observed[key][column] == changed[key][column]


def test_same_date_order_is_invariant() -> None:
    d0 = dt.date(2020, 1, 1)
    first = record("a", d0, 1, 3, a_won=True)
    second = record("b", d0, 1, 4, a_won=False)
    target = record("t", d0 + dt.timedelta(days=2), 1, 2)
    assert features([first, second, target])["t"] == features([second, first, target])["t"]


def test_missing_counts_still_update_result_and_match_workload() -> None:
    d0 = dt.date(2020, 1, 1)
    source = record("s", d0, 1, 3, with_counts=False, a_won=True)
    target = record("t", d0 + dt.timedelta(days=2), 1, 2)
    row = features([source, target])["t"]
    assert row["elo_overall_logit"] > 0.0
    assert row["matches_7d_diff"] == 1
    assert row["points_missing_7d_diff"] == 1
    assert row["count_denominator_overall_a"] == 0.0
    assert row["count_denominator_overall_b"] == 0.0


def test_provisional_targets_never_update_primary_states() -> None:
    d0 = dt.date(2020, 1, 1)
    provisional = record("p", d0, 1, 3, tier="provisional", a_won=True)
    target = record("t", d0 + dt.timedelta(days=2), 1, 2)
    row = features([provisional, target])["t"]
    assert row["elo_overall_logit"] == 0.0
    assert row["matches_7d_diff"] == 0
    assert row["count_denominator_overall_a"] == 0.0


def test_lagged_market_state_does_not_use_actual_winner() -> None:
    d0 = dt.date(2020, 1, 1)
    source = record("s", d0, 1, 3, a_won=True, ps=0.7)
    target = record("t", d0 + dt.timedelta(days=2), 1, 2)
    winner_a = features([source, target])["t"]
    winner_b = features([bf.replace(source, a_won=False), target])["t"]
    assert winner_a["elo_overall_logit"] != winner_b["elo_overall_logit"]
    assert (
        winner_a["lagged_market_elo_overall_logit"] == winner_b["lagged_market_elo_overall_logit"]
    )
    assert (
        winner_a["lagged_market_elo_surface_logit"] == winner_b["lagged_market_elo_surface_logit"]
    )


def test_player_swap_complements_market_and_negates_signed_features() -> None:
    d0 = dt.date(2020, 1, 1)
    source = record("s", d0, 1, 3, a_won=True, ps=0.7)
    target = record("t", d0 + dt.timedelta(days=2), 1, 2, ps=0.65, surface="Clay", court="Indoor")
    ranking = rank_map([source, target])
    states = list(bf.stream_rows([source, target], ranking, PARAMETERS))
    original = states[-1][1]

    # Recreate the same pre-target states explicitly, then evaluate the
    # opposite orientation. Input parsing still requires canonical A < B.
    sports = bf.EloHistory(1500.0, 32.0, 400.0)
    market = bf.EloHistory(1500.0, 32.0, 400.0)
    history = bf.CountHistory(180.0, 50.0, 0.6, 0.4)
    workload = bf.WorkloadHistory()
    history.advance(target.match_date)
    sports.apply_batch([source])
    market.apply_batch([source], pseudo_outcome=True)
    history.add_match(source, target.match_date)
    workload.add_match(source)
    assert target.ps_probability_a is not None
    swapped = bf.replace(
        target,
        player_a=target.player_b,
        player_b=target.player_a,
        a_won=not target.a_won,
        counts_a=target.counts_b,
        counts_b=target.counts_a,
        ps_probability_a=1.0 - target.ps_probability_a,
    )
    opposite = bf.build_feature_row(
        swapped,
        swapped.match_date - dt.timedelta(days=2),
        sports,
        history,
        workload,
        market,
        ranking[(target.match_date, target.player_b)],
        ranking[(target.match_date, target.player_a)],
        (7, 28),
        90,
    )
    for column in bf.SIGNED_BASES + bf.linear_interactions() + bf.rank_global_interactions():
        assert float(original[column]) == pytest.approx(-float(opposite[column]), abs=1e-14)
    assert float(original["ps_probability_a"]) == pytest.approx(
        1.0 - float(opposite["ps_probability_a"]), abs=1e-14
    )
    assert float(original["ps_logit_a"]) == pytest.approx(-float(opposite["ps_logit_a"]), abs=1e-14)
    assert float(original["lagged_market_elo_overall_logit"]) == pytest.approx(
        -float(opposite["lagged_market_elo_overall_logit"]), abs=1e-14
    )
    assert opposite["context_indoor"] == 1


def test_unknown_court_is_not_encoded_as_known_outdoor() -> None:
    item = record("t", dt.date(2020, 1, 1), 1, 2, court="")
    context = bf.context_values(item)
    assert context["context_indoor"] == 0
    assert context["context_indoor_unknown"] == 1


def test_ranking_has_no_player_specific_fallback() -> None:
    older = dt.date(2020, 1, 1)
    latest = dt.date(2020, 1, 8)
    lookup = RankingLookup.from_rows(
        [rank_row(older, 10, 1, 100, 2), rank_row(latest, 20, 2, 90, 3)]
    )
    absent, present, unknown = lookup.lookup_many(
        [
            LookupRequest(dt.date(2020, 1, 10), 1),
            LookupRequest(dt.date(2020, 1, 10), 2),
            LookupRequest(dt.date(2020, 1, 10), 999),
        ]
    )
    assert absent.player_missing_on_snapshot
    assert absent.rank is None
    assert not absent.unknown_player_id
    assert present.rank == 20
    assert unknown.unknown_player_id


def test_dictionary_keeps_labels_and_odds_out_of_sports_predictors() -> None:
    dictionary = bf.column_dictionary()
    sports = set(dictionary["linear_sports_model_features"])
    assert len(dictionary["signed_base_model_features"]) == 22
    assert len(dictionary["signed_context_interactions"]) == 132
    assert len(dictionary["rank_global_age_stale_interactions"]) == 8
    assert not {"a_won", "status", "score", "ps_probability_a", "ps_logit_a"} & sports
    assert "context_carpet" in dictionary["binary_context_columns"]


def test_label_file_holds_only_keys_and_the_outcome() -> None:
    dictionary = bf.column_dictionary()
    assert dictionary["label_file_columns"] == list(bf.LABEL_HEADER)
    assert set(bf.LABEL_HEADER) & set(bf.feature_header()) == {
        "match_id",
        "calendar_year",
        "source_season",
        "match_date",
        "tourney_id",
        "identity_tier",
        "primary_target",
        "source_field_agreement",
    }
    assert "a_won" not in bf.feature_header()
    assert "status" not in bf.feature_header()
    assert set(bf.label_row(record("t", dt.date(2020, 1, 1), 1, 2))) == set(bf.LABEL_HEADER)


def test_labels_are_written_in_target_order(tmp_path) -> None:
    d0 = dt.date(2020, 1, 1)
    rows = [
        record("b", d0 + dt.timedelta(days=2), 1, 2, a_won=False),
        record("a", d0, 1, 3, a_won=True),
    ]
    path = tmp_path / "labels.csv"
    bf.write_labels(path, sorted(rows, key=bf.Record.order_key))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(bf.LABEL_HEADER)
    assert [line.split(",")[0] for line in lines[1:]] == ["a", "b"]
    assert [line.split(",")[7] for line in lines[1:]] == ["1", "0"]


def test_one_sided_count_history_is_counted_not_asserted_away() -> None:
    """The WTA02 revision: a zero-serve-point match leaves one domain one-sided."""
    history = bf.CountHistory(180.0, 50.0, 0.6, 0.4)
    day = dt.date(2020, 1, 1)
    history.advance(day)
    zero_server = bf.Counts(0, 0, 0, 0, 0, 0, 0, 0)
    history.add_match(
        bf.replace(
            record("s", day, 1, 3, a_won=True),
            counts_a=zero_server,
            counts_b=counts(0),
        ),
        day,
    )
    summary = history.player_summary(1, "Hard")
    assert summary["serve_overall_denominator"] == 0.0
    assert summary["return_overall_denominator"] > 0.0
    assert summary["missing_overall"] == 0
    assert history.diverged["overall"] == 1


# ------------------------------------------------------------ ARMS01: the entry/level block


def test_entry_level_values_flag_only_q_ll_wc_pr_and_indicate_only_g_m_a_f() -> None:
    day = dt.date(2020, 1, 1)
    base = record("t", day, 1, 2)
    cases = {
        # (entry_a, entry_b, level) -> (q, ll, wc, pr, any_qualifier, g, m, a, f)
        ("Q", "", "A"): (1, 0, 0, 0, 1, 0, 0, 1, 0),
        ("", "Q", "G"): (-1, 0, 0, 0, 1, 1, 0, 0, 0),
        ("LL", "WC", "M"): (0, 1, -1, 0, 1, 0, 1, 0, 0),
        ("PR", "PR", "F"): (0, 0, 0, 0, 0, 0, 0, 0, 1),
        ("SE", "ALT", "D"): (0, 0, 0, 0, 0, 0, 0, 0, 0),
        ("Alt", "W", "O"): (0, 0, 0, 0, 0, 0, 0, 0, 0),
        (" q ", "ll", "a"): (1, -1, 0, 0, 1, 0, 0, 1, 0),  # whitespace and case normalised
        ("", "", "C"): (0, 0, 0, 0, 0, 0, 0, 0, 0),
    }
    for (entry_a, entry_b, level), expected in cases.items():
        item = bf.replace(base, entry_a=entry_a, entry_b=entry_b, tourney_level=level)
        values = bf.entry_level_values(item)
        assert tuple(values) == bf.ENTRY_LEVEL_COLUMNS
        assert tuple(values.values()) == expected, (entry_a, entry_b, level)
        assert sum(values[column] for column in bf.LEVEL_CONTEXT) <= 1
    # The round is not an input: changing it changes nothing.
    assert bf.entry_level_values(bf.replace(base, round="F")) == bf.entry_level_values(base)


def test_the_entry_level_block_is_appended_last_and_only_its_signed_columns_negate() -> None:
    plain = bf.feature_header()
    extended = bf.feature_header(entry_level=True)
    assert extended[: len(plain)] == plain
    assert extended[len(plain) :] == bf.ENTRY_RAW_AUDIT_COLUMNS + bf.ENTRY_LEVEL_COLUMNS
    assert bf.ENTRY_LEVEL_COLUMNS == bf.ENTRY_LEVEL_SIGNED + bf.ENTRY_LEVEL_CONTEXT
    d0 = dt.date(2020, 1, 1)
    source = record("s", d0, 1, 3, a_won=True)
    target = bf.replace(
        record("t", d0 + dt.timedelta(days=2), 1, 2, surface="Clay"),
        entry_a="Q",
        entry_b="WC",
        tourney_level="M",
    )
    ranking = rank_map([source, target])
    rows = dict(bf.stream_rows([source, target], ranking, PARAMETERS, entry_level=True))
    original = rows[target]
    assert (original["a_entry"], original["b_entry"]) == ("Q", "WC")
    assert [original[column] for column in bf.ENTRY_LEVEL_COLUMNS] == [1, 0, -1, 0, 1, 0, 1, 0, 0]
    without = dict(bf.stream_rows([source, target], ranking, PARAMETERS))[target]
    assert set(without) == set(plain)
    assert {k: v for k, v in original.items() if k in plain} == without
    # The opposite orientation: signed entry differences negate, the context stays.
    sports = bf.EloHistory(1500.0, 32.0, 400.0)
    market = bf.EloHistory(1500.0, 32.0, 400.0)
    history = bf.CountHistory(180.0, 50.0, 0.6, 0.4)
    workload = bf.WorkloadHistory()
    history.advance(target.match_date)
    sports.apply_batch([source])
    market.apply_batch([source], pseudo_outcome=True)
    history.add_match(source, target.match_date)
    workload.add_match(source)
    swapped = bf.replace(
        target,
        player_a=target.player_b,
        player_b=target.player_a,
        a_won=not target.a_won,
        counts_a=target.counts_b,
        counts_b=target.counts_a,
        ps_probability_a=1.0 - target.ps_probability_a,
        entry_a=target.entry_b,
        entry_b=target.entry_a,
    )
    opposite = bf.build_feature_row(
        swapped,
        swapped.match_date - dt.timedelta(days=2),
        sports,
        history,
        workload,
        market,
        ranking[(target.match_date, target.player_b)],
        ranking[(target.match_date, target.player_a)],
        (7, 28),
        90,
        entry_level=True,
    )
    for column in bf.ENTRY_LEVEL_SIGNED:
        assert opposite[column] == -original[column], column
    for column in bf.ENTRY_LEVEL_CONTEXT:
        assert opposite[column] == original[column], column
    assert (opposite["a_entry"], opposite["b_entry"]) == ("WC", "Q")


def test_the_dictionary_declares_the_block_only_when_enabled() -> None:
    plain = bf.column_dictionary()
    assert "entry_level_columns" not in plain
    assert plain["ordered_feature_file_columns"] == list(bf.feature_header())
    extended = bf.column_dictionary(entry_level=True)
    assert extended["entry_level_columns"] == list(bf.ENTRY_LEVEL_COLUMNS)
    assert extended["entry_level_signed_columns"] == list(bf.ENTRY_LEVEL_SIGNED)
    assert extended["entry_level_context_columns"] == list(bf.ENTRY_LEVEL_CONTEXT)
    assert extended["ordered_feature_file_columns"] == list(bf.feature_header(entry_level=True))
    # The raw codes are audit columns and, with the raw level and the round, forbidden.
    assert extended["entry_raw_audit_columns"] == ["a_entry", "b_entry"]
    for raw in ("a_entry", "b_entry", "tourney_level", "round"):
        assert raw in extended["forbidden_from_sports_predictors"], raw
    assert extended["audit_only_columns"][-2:] == ["a_entry", "b_entry"]
    # Every list the frozen contract reads is unchanged by the block.
    for key in (
        "linear_sports_model_features",
        "signed_base_model_features",
        "binary_context_columns",
        "hgb_sports_model_features",
        "identifier_and_split_columns",
        "label_file_columns",
    ):
        assert extended[key] == plain[key], key


def test_the_stage_config_switch_is_a_boolean_outside_the_frozen_parameters() -> None:
    assert bf.entry_level_enabled({}) is False
    assert bf.entry_level_enabled({"entry_level_block": True}) is True
    assert bf.ENTRY_LEVEL_BLOCK_KEY not in bf.FIXED_PARAMETERS


# ------------------------------------- ARMS01 Arm 1-LLx: lucky loser read as no flag


def test_ll_as_no_flag_changes_only_the_ll_and_any_qualifier_columns_on_ll_rows() -> None:
    base = record("t", dt.date(2020, 1, 1), 1, 2)
    codes = ("", "Q", "LL", "ll ", "WC", "PR", "SE", "Alt")
    changed = {"entry_ll_diff", "entry_any_qualifier"}
    for entry_a in codes:
        for entry_b in codes:
            item = bf.replace(base, entry_a=entry_a, entry_b=entry_b, tourney_level="M")
            flagged = bf.entry_level_values(item)
            assert bf.entry_level_values(item, ll_as_no_flag=False) == flagged
            unflagged = bf.entry_level_values(item, ll_as_no_flag=True)
            assert tuple(unflagged) == bf.ENTRY_LEVEL_COLUMNS
            has_ll = "LL" in (entry_a.strip().upper(), entry_b.strip().upper())
            has_q = "Q" in (entry_a, entry_b)
            assert unflagged["entry_ll_diff"] == 0
            assert unflagged["entry_any_qualifier"] == int(has_q)
            differing = {column for column in flagged if flagged[column] != unflagged[column]}
            assert differing <= changed, (entry_a, entry_b)
            if not has_ll:
                assert differing == set(), (entry_a, entry_b)
    # A one-sided LL is a flagged row whose block the option changes.
    only_ll = bf.replace(base, entry_a="LL", entry_b="")
    assert bf.entry_level_values(only_ll)["entry_ll_diff"] == 1
    assert bf.entry_level_values(only_ll)["entry_any_qualifier"] == 1
    # Q against LL keeps the any-qualifier flag through Q.
    q_ll = bf.replace(base, entry_a="Q", entry_b="LL")
    assert bf.entry_level_values(q_ll, ll_as_no_flag=True)["entry_any_qualifier"] == 1
    assert bf.entry_level_values(q_ll, ll_as_no_flag=True)["entry_q_diff"] == 1


def write_and_validate(
    tmp_path: Path, records: list[bf.Record], name: str, **options: bool
) -> tuple[Path, list[bf.Record], dict[str, object]]:
    features_path = tmp_path / f"{name}.features.csv"
    labels_path = tmp_path / f"{name}.labels.csv"
    written, _ = bf.write_features(
        features_path, records, rank_map(records), PARAMETERS, Counter(), **options
    )
    bf.write_labels(labels_path, written)
    dictionary = bf.column_dictionary(
        options.get("entry_level", False), options.get("ll_as_no_flag", False)
    )
    result = bf.validate_written_outputs(
        features_path, labels_path, written, dictionary, PARAMETERS
    )
    assert result["status"] == "PASS"
    return features_path, written, dictionary


def test_the_ll_option_off_writes_identical_bytes_and_on_changes_only_ll_rows(
    tmp_path: Path,
) -> None:
    d0 = dt.date(2020, 1, 1)
    plan = [
        ("s1", 0, 1, 2, "", ""),
        ("t1", 2, 1, 3, "LL", ""),
        ("t2", 2, 2, 4, "Q", "LL"),
        ("t3", 3, 3, 4, "LL", "LL"),
        ("t4", 3, 1, 4, "WC", " ll"),
        ("t5", 4, 2, 3, "Q", ""),
        ("t6", 4, 1, 2, "PR", "SE"),
        ("t7", 5, 3, 5, "", "WC"),
    ]
    records = [
        bf.replace(record(match_id, d0 + dt.timedelta(days=offset), a, b), entry_a=ea, entry_b=eb)
        for match_id, offset, a, b, ea, eb in plan
    ]
    default, _, dictionary = write_and_validate(tmp_path, records, "default", entry_level=True)
    off, _, off_dictionary = write_and_validate(
        tmp_path, records, "off", entry_level=True, ll_as_no_flag=False
    )
    on, written, on_dictionary = write_and_validate(
        tmp_path, records, "on", entry_level=True, ll_as_no_flag=True
    )
    # Option off: byte-identical file and dictionary.
    assert off.read_bytes() == default.read_bytes()
    assert off_dictionary == dictionary
    # Option on: same header, every other cell identical, only the two columns change
    # and only on rows with LL on a side.
    with default.open(newline="", encoding="utf-8") as handle:
        flagged_rows = list(csv.DictReader(handle))
    with on.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(bf.feature_header(entry_level=True))
        unflagged_rows = list(reader)
    assert len(unflagged_rows) == len(flagged_rows) == len(records)
    ll_rows = set()
    for flagged, unflagged in zip(flagged_rows, unflagged_rows, strict=True):
        assert flagged["match_id"] == unflagged["match_id"]
        differing = {column for column in flagged if flagged[column] != unflagged[column]}
        assert differing <= {"entry_ll_diff", "entry_any_qualifier"}
        assert unflagged["entry_ll_diff"] == "0"
        if "LL" in (flagged["a_entry"].strip().upper(), flagged["b_entry"].strip().upper()):
            ll_rows.add(flagged["match_id"])
        else:
            assert differing == set(), flagged["match_id"]
    assert ll_rows == {"t1", "t2", "t3", "t4"}
    changed = {
        row["match_id"]
        for row, other in zip(flagged_rows, unflagged_rows, strict=True)
        if row != other
    }
    assert changed == ll_rows
    # t2 keeps any_qualifier through its Q; t1, t3 and t4 lose it.
    by_id = {row["match_id"]: row for row in unflagged_rows}
    assert [by_id[key]["entry_any_qualifier"] for key in ("t1", "t2", "t3", "t4")] == [
        "0",
        "1",
        "0",
        "0",
    ]
    # The dictionary declares the option; its column lists are those of Arm 1.
    assert on_dictionary["entry_level_ll_as_no_flag"] is True
    assert "entry_level_ll_as_no_flag" not in dictionary
    assert {key for key in on_dictionary if on_dictionary[key] != dictionary.get(key)} == {
        "entry_level_ll_as_no_flag",
        "entry_level_semantics",
    }
    # Negative control: the validator recomputes the block under the dictionary's option.
    labels = tmp_path / "on.labels.csv"
    with pytest.raises(ChainError, match="wrong entry_"):
        bf.validate_written_outputs(on, labels, written, dictionary, PARAMETERS)
    with pytest.raises(ChainError, match="wrong entry_"):
        bf.validate_written_outputs(
            default, tmp_path / "default.labels.csv", written, on_dictionary, PARAMETERS
        )


def test_the_ll_option_is_recorded_in_the_receipts_and_needs_the_block() -> None:
    d0 = dt.date(2020, 1, 1)
    records = [
        bf.replace(record("a", d0, 1, 2), entry_a="LL", entry_b=""),
        bf.replace(record("b", d0, 1, 3), entry_a="Q", entry_b="ll"),
        bf.replace(record("c", d0.replace(year=2021), 1, 3), entry_a="Q", entry_b=""),
    ]
    plain = bf.entry_level_receipts(records)
    assert bf.ENTRY_LL_AS_NO_FLAG_KEY not in plain
    assert plain["flagged_entry_codes"] == ["Q", "LL", "WC", "PR"]
    receipt = bf.entry_level_receipts(records, ll_as_no_flag=True)
    assert receipt[bf.ENTRY_LL_AS_NO_FLAG_KEY] is True
    assert receipt["flagged_entry_codes"] == ["Q", "WC", "PR"]
    assert receipt["ll_either_side_rows_read_as_no_flag_by_season"] == {"2020": 2}
    assert {key: value for key, value in receipt.items() if key in plain} == {
        **plain,
        "flagged_entry_codes": ["Q", "WC", "PR"],
    }
    assert bf.entry_ll_as_no_flag({}) is False
    assert bf.entry_ll_as_no_flag({bf.ENTRY_LL_AS_NO_FLAG_KEY: True}) is True
    assert bf.ENTRY_LL_AS_NO_FLAG_KEY not in bf.FIXED_PARAMETERS
    with pytest.raises(ChainError, match=bf.ENTRY_LL_AS_NO_FLAG_KEY):
        bf.column_dictionary(entry_level=False, ll_as_no_flag=True)


# ------------------------ ARMS01 attempt 002: the registered Q-only any-qualifier flag


def test_any_qualifier_counts_ll_false_counts_q_only_and_keeps_the_signed_ll_column() -> None:
    base = record("t", dt.date(2020, 1, 1), 1, 2)
    codes = ("", "Q", "LL", " ll", "WC", "PR", "SE", "Alt")
    for entry_a in codes:
        for entry_b in codes:
            item = bf.replace(base, entry_a=entry_a, entry_b=entry_b, tourney_level="G")
            default = bf.entry_level_values(item)
            assert bf.entry_level_values(item, any_qualifier_counts_ll=True) == default
            registered = bf.entry_level_values(item, any_qualifier_counts_ll=False)
            assert tuple(registered) == bf.ENTRY_LEVEL_COLUMNS
            normalised = {entry_a.strip().upper(), entry_b.strip().upper()}
            assert registered["entry_any_qualifier"] == int("Q" in normalised)
            # Only the flag can change, and only where LL is on a side and Q is on neither.
            differing = {column for column in default if default[column] != registered[column]}
            ll_without_q = "LL" in normalised and "Q" not in normalised
            assert differing == ({"entry_any_qualifier"} if ll_without_q else set()), (
                entry_a,
                entry_b,
            )
            # entry_ll_diff stays the signed LL difference.
            assert registered["entry_ll_diff"] == default["entry_ll_diff"]
    one_sided = bf.replace(base, entry_a="", entry_b="LL")
    assert bf.entry_level_values(one_sided, any_qualifier_counts_ll=False)["entry_ll_diff"] == -1
    # Combined with the LL-as-no-flag sensitivity the flag is Q only either way.
    for item in (one_sided, bf.replace(base, entry_a="Q", entry_b="LL")):
        assert bf.entry_level_values(
            item, ll_as_no_flag=True, any_qualifier_counts_ll=False
        ) == bf.entry_level_values(item, ll_as_no_flag=True)


def test_any_qualifier_option_absent_or_true_is_byte_identical_and_false_changes_only_ll_rows(
    tmp_path: Path,
) -> None:
    d0 = dt.date(2020, 1, 1)
    plan = [
        ("s1", 0, 1, 2, "", ""),
        ("t1", 2, 1, 3, "LL", ""),
        ("t2", 2, 2, 4, "Q", "LL"),
        ("t3", 3, 3, 4, "LL", "LL"),
        ("t4", 3, 1, 4, "WC", " ll"),
        ("t5", 4, 2, 3, "Q", ""),
        ("t6", 4, 1, 2, "PR", "SE"),
        ("t7", 5, 3, 5, "", "WC"),
    ]
    records = [
        bf.replace(record(match_id, d0 + dt.timedelta(days=offset), a, b), entry_a=ea, entry_b=eb)
        for match_id, offset, a, b, ea, eb in plan
    ]

    def written(name: str, **options: bool) -> tuple[Path, dict[str, object]]:
        features_path = tmp_path / f"{name}.features.csv"
        labels_path = tmp_path / f"{name}.labels.csv"
        rows, _ = bf.write_features(
            features_path, records, rank_map(records), PARAMETERS, Counter(), **options
        )
        bf.write_labels(labels_path, rows)
        dictionary = bf.column_dictionary(
            True, any_qualifier_counts_ll=options.get("any_qualifier_counts_ll", True)
        )
        assert (
            bf.validate_written_outputs(features_path, labels_path, rows, dictionary, PARAMETERS)[
                "status"
            ]
            == "PASS"
        )
        return features_path, dictionary

    absent, absent_dictionary = written("absent", entry_level=True)
    explicit, explicit_dictionary = written("true", entry_level=True, any_qualifier_counts_ll=True)
    registered, registered_dictionary = written(
        "false", entry_level=True, any_qualifier_counts_ll=False
    )
    # Absent and true: identical bytes and dictionary, and the dictionary names no option.
    assert explicit.read_bytes() == absent.read_bytes()
    assert explicit_dictionary == absent_dictionary == bf.column_dictionary(True)
    assert bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY not in absent_dictionary
    # False: same header; only entry_any_qualifier changes, only on LL-without-Q rows.
    with absent.open(newline="", encoding="utf-8") as handle:
        before = list(csv.DictReader(handle))
    with registered.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(bf.feature_header(entry_level=True))
        after = list(reader)
    changed = set()
    for old, new in zip(before, after, strict=True):
        differing = {column for column in old if old[column] != new[column]}
        assert differing <= {"entry_any_qualifier"}, old["match_id"]
        if differing:
            changed.add(old["match_id"])
        assert new["entry_ll_diff"] == old["entry_ll_diff"]
    assert changed == {"t1", "t3", "t4"}  # t2 keeps the flag through its Q
    assert registered_dictionary[bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY] is False
    assert {
        key
        for key in registered_dictionary
        if registered_dictionary[key] != absent_dictionary.get(key)
    } == {bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY, "entry_level_semantics"}
    # Negative controls: each file fails validation against the other dictionary.
    ordered = sorted(records, key=bf.Record.order_key)
    with pytest.raises(ChainError, match="wrong entry_any_qualifier"):
        bf.validate_written_outputs(
            registered, tmp_path / "false.labels.csv", ordered, absent_dictionary, PARAMETERS
        )
    with pytest.raises(ChainError, match="wrong entry_any_qualifier"):
        bf.validate_written_outputs(
            absent, tmp_path / "absent.labels.csv", ordered, registered_dictionary, PARAMETERS
        )


def test_any_qualifier_option_is_recorded_in_the_receipts_and_needs_the_block() -> None:
    d0 = dt.date(2020, 1, 1)
    records = [
        bf.replace(record("a", d0, 1, 2), entry_a="LL", entry_b=""),
        bf.replace(record("b", d0, 1, 3), entry_a="Q", entry_b="ll"),
        bf.replace(record("c", d0.replace(year=2021), 1, 3), entry_a="LL", entry_b="LL"),
    ]
    plain = bf.entry_level_receipts(records)
    assert bf.entry_level_receipts(records, any_qualifier_counts_ll=True) == plain
    assert bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY not in plain
    receipt = bf.entry_level_receipts(records, any_qualifier_counts_ll=False)
    assert receipt[bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY] is False
    assert receipt["any_qualifier_rows_with_ll_and_no_q_by_season"] == {"2020": 1, "2021": 1}
    assert {key: value for key, value in receipt.items() if key in plain} == plain
    assert bf.entry_any_qualifier_counts_ll({}) is True
    assert bf.entry_any_qualifier_counts_ll({bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY: True}) is True
    assert bf.entry_any_qualifier_counts_ll({bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY: False}) is False
    assert bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY not in bf.FIXED_PARAMETERS
    with pytest.raises(ChainError, match=bf.ENTRY_ANY_QUALIFIER_COUNTS_LL_KEY):
        bf.column_dictionary(entry_level=False, any_qualifier_counts_ll=False)
