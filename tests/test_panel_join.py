"""The archive's ``MULTI01_join/test_join_candidates.py``, importing from the package.

Every case is the archive's, unchanged; only the import and the ``dt`` reference differ.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from tennislab.panel import join


def archive_row(key: str = "2020-0123/1", anchor: str = "2020-01-06") -> dict[str, str]:
    return {
        "season": "2020",
        "source_key": key,
        "tourney_id": "2020-0123",
        "tourney_name": "Example Open",
        "tourney_anchor_date": anchor,
        "round": "R32",
        "draw_size": "32",
        "a_entity_id": "100",
        "b_entity_id": "200",
        "a_won": "true",
        "score": "6-4 6-3",
        "surface": "Hard",
        "best_of": "3",
        "status": "retired",
    }


def market_row() -> dict[str, Any]:
    return {
        "market_season": 2020,
        "market_source_path": "fixture.xlsx",
        "market_source_row": 2,
        "market_date": dt.date(2020, 1, 7),
        "ATP": "123",
        "Tournament": "Different Display Name",
        "Round": "1st Round",
        "Winner": "Alpha A.",
        "Loser": "Beta B.",
        "Surface": "Clay",
        "Best of": "5",
        "Comment": "Retired",
        "W1": "6",
        "L1": "4",
        "W2": "6",
        "L2": "3",
    }


def test_compound_name_signature() -> None:
    signatures = join.source_signatures("Juan Martin del Potro")
    assert ("delpotro", "jm") in signatures
    assert join.td_signature("Del Potro J.M.") == ("delpotro", "jm")


def test_selection_is_pair_symmetric_and_ignores_validation_fields() -> None:
    archive = archive_row()
    index = {(2020, (100, 200)): [archive]}
    unique_a = {"ids": {100}, "basis": "initial_surname_unique", "signature": ""}
    unique_b = {"ids": {200}, "basis": "initial_surname_unique", "signature": ""}
    market = market_row()
    first = join.classify_market_row(market, index, unique_a, unique_b, None)
    second = join.classify_market_row(market, index, unique_b, unique_a, None)
    assert first["selected"]["archive"]["source_key"] == second["selected"]["archive"]["source_key"]
    assert first["classification"] == "candidate_q2_unique_alias_event"
    validation, _ = join.validate_selected(first)
    assert validation["winner_agreement"] == "agree"
    assert validation["surface_agreement"] == "disagree"
    assert validation["best_of_agreement"] == "disagree"
    assert validation["status_agreement"] == "agree"
    swapped_validation, _ = join.validate_selected(second)
    assert swapped_validation["winner_agreement"] == "disagree"


def test_ambiguity_and_date_error_remain_candidates() -> None:
    market = market_row()
    aliases_a = {"ids": {100}, "basis": "initial_surname_unique", "signature": ""}
    aliases_b = {"ids": {200}, "basis": "initial_surname_unique", "signature": ""}
    duplicate = archive_row("2020-0123/2")
    ambiguous = join.classify_market_row(
        market, {(2020, (100, 200)): [archive_row(), duplicate]}, aliases_a, aliases_b, None
    )
    assert ambiguous["classification"] == "ambiguous_multiple_strong"
    old_market = dict(market)
    old_market["market_date"] = dt.date(2019, 1, 7)
    correction = join.classify_market_row(
        old_market, {(2020, (100, 200)): [archive_row()]}, aliases_a, aliases_b, None
    )
    assert correction["classification"] == "date_correction_candidate"


def test_known_source_date_anomaly_rules_are_narrow() -> None:
    row = market_row()
    row.update(
        market_season=2006,
        market_date=dt.date(2005, 11, 5),
        Tournament="BNP Paribas",
    )
    assert join.source_date_anomaly_rule(row) == "2006_bnp_paribas_isolated_prior_year_cell"
    row.update(
        market_season=2013,
        market_date=dt.date(2012, 10, 4),
        Tournament="China Open",
    )
    assert join.source_date_anomaly_rule(row) == "2013_china_japan_prior_year_event_block"
    row["market_date"] = dt.date(2012, 12, 31)
    assert join.source_date_anomaly_rule(row) is None
    row.update(market_date=dt.date(2012, 10, 4), Tournament="Different Event")
    assert join.source_date_anomaly_rule(row) is None
