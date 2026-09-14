"""The WTA era-table assignment and the WTA panel's exclusion order.

The archive ships no unit test for ``wta_rule_rows.py`` or the WTA branch of
``prepare_panel.py``; these cover the two pure decisions the equivalence run cannot
isolate -- which era a Slam row takes (and when a carried one is labelled as carried),
and which named reason claims a market row first.
"""

from __future__ import annotations

from tennislab.panel.prepare import wta_exclusion, wta_tier
from tennislab.panel.wta_rules import packaged_rule_config, rule_for

CONFIG, BINDING = packaged_rule_config()


def slam_row(season: int, name: str = "Australian Open") -> dict[str, str]:
    return {
        "source_key": f"{season}-580/1",
        "match_id": f"{season}-580/1",
        "source_season": str(season),
        "tourney_id": f"{season}-580",
        "tourney_name": name,
        "tourney_level": "G",
        "round": "R32",
        "best_of": "3",
    }


def test_packaged_era_table_is_the_declared_one() -> None:
    assert BINDING["resource"] == "tennislab.panel/wta_rules.json"
    assert CONFIG["id"] == "WTA01-scoring-rules-v1"
    assert CONFIG["ordinary_wta"]["best_of"] == 3


def test_slam_era_is_selected_by_season_and_normalized_name() -> None:
    assignment, reason, deciding = rule_for(CONFIG, slam_row(2010))
    assert reason == ""
    assert assignment["rule_group"] == "grand_slam_580_2007_2018"
    assert deciding["mode"] == "advantage"
    assignment, _, deciding = rule_for(CONFIG, slam_row(2020))
    assert assignment["rule_group"] == "grand_slam_580_2019_2024"
    assert deciding == {"mode": "tiebreak", "tiebreak_at_games": 6, "tiebreak_points": 10}


def test_a_season_past_the_last_era_is_refused_unless_carried() -> None:
    assignment, reason, _ = rule_for(CONFIG, slam_row(2026))
    assert assignment is None
    assert reason == "no_declared_era_for_580_2026"
    assignment, reason, _ = rule_for(CONFIG, slam_row(2026), era_carry_from_year=2024)
    assert reason == ""
    assert assignment["rule_group"] == "grand_slam_580_2019_2024_carried_forward"
    assert "carried_forward_from_2024_edition_declared_assumption_WTA02" in assignment["rule_basis"]


def test_an_unrecognized_slam_name_is_refused_never_defaulted() -> None:
    assignment, reason, _ = rule_for(CONFIG, slam_row(2010, name="Some Other Major"))
    assert assignment is None
    assert reason == "unrecognized_grand_slam_name_some other major"


def test_ordinary_level_takes_the_tour_rule_and_an_unknown_level_is_refused() -> None:
    row = {**slam_row(2015), "tourney_level": "PM", "tourney_name": "Indian Wells"}
    assignment, reason, _ = rule_for(CONFIG, row)
    assert reason == ""
    assert assignment["rule_group"] == "ordinary_wta_best_of_three"
    assignment, reason, _ = rule_for(CONFIG, {**row, "tourney_level": "D"})
    assert assignment is None
    assert reason == "no_tour_default_for_level_D"


def paired_row(**overrides: str) -> dict[str, str]:
    row = {
        "pairing_status": "matched",
        "winner_agreement": "agree",
        "market_date": "2015-01-12",
        "date_window_agreement": "true",
        "market_comment": "Completed",
        "archive_status": "completed",
        "archive_score": "6-4 6-3",
        "link_dependent": "false",
    }
    row.update(overrides)
    return row


def test_exclusion_order_is_the_declared_one() -> None:
    assert wta_exclusion(paired_row()) is None
    assert wta_exclusion(paired_row(pairing_status="ambiguous_pair_key")) == "ambiguous_pair_key"
    assert (
        wta_exclusion(paired_row(winner_agreement="reversed"))
        == "unresolved_outcome_or_quote_orientation"
    )
    assert wta_exclusion(paired_row(market_date="")) == "market_date_missing"
    assert (
        wta_exclusion(paired_row(date_window_agreement="false"))
        == "market_date_outside_event_window"
    )
    # `Cancelled` is outside the workbook's own status vocabulary, so the vocabulary
    # check claims it before the walkover branch can.
    assert (
        wta_exclusion(paired_row(market_comment="Cancelled"))
        == "market_status_vocabulary_unrecognized"
    )
    assert wta_exclusion(paired_row(market_comment="Walkover")) == "start_status_disagreement"
    assert (
        wta_exclusion(paired_row(market_comment="Retired", archive_status="walkover"))
        == "nonstart_or_unresolved_status"
    )
    assert wta_exclusion(paired_row(archive_score="RET")) == "start_not_established_by_score"


def test_a_link_dependent_pair_key_cannot_be_primary() -> None:
    assert wta_tier(paired_row()) == ("primary", "unique_pair_key_in_accepted_edition")
    assert wta_tier(paired_row(link_dependent="true")) == (
        "provisional",
        "surname_class_link_dependent_pair_key",
    )
