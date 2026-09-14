"""Unit tests for ``tennislab.ratings.elo``.

Ported from ``references/CONFIRM2026_elo/test_confirm2026_elo.py`` class
``EngineTests``. ``test_parameters_match_the_validated_sources`` read two archive
JSON files that are not part of this repository; it is kept as a pin on the frozen
literals themselves, with the archive files named in the assertion message.

``test_pooled_probability_is_the_closed_form_probability_mean`` is new: it pins
ELO-DATE-002-C1 (probability-space mean) with one overall rating pair, one surface
rating pair and the probability computed by hand in the test.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from tennislab.ratings import elo

UNIT_ROW = {
    "date": "2026-01-05",
    "tour": "ATP",
    "tournament": "T",
    "level": "A",
    "round": "R32",
    "surface": "Hard",
    "best_of": "3",
    "winner_id": "1",
    "loser_id": "2",
    "winner_name": "",
    "loser_name": "",
    "source": "unit",
}


def row(**overrides: str) -> dict[str, str]:
    return {**UNIT_ROW, **overrides}


def test_parameters_match_the_validated_sources() -> None:
    """work/MULTI01_features/config.json parameters, experiments/ELO-DATE-002-C1.json."""
    assert elo.INITIAL_RATING == 1500.0
    assert elo.ELO_K == 32.0
    assert elo.ELO_SCALE == 400.0
    assert elo.DEFAULT_LAG_DAYS == 2
    assert elo.POOLED_OVERALL_WEIGHT == 0.5
    assert elo.POOLED_SURFACE_WEIGHT == 0.5
    assert elo.POOLING_DOMAIN == "probability_space_mean"
    assert elo.MODEL_ID == "CONFIRM2026-pooled-elo-v1"
    assert elo.SURFACES == ("Hard", "Clay", "Grass", "Carpet")


def test_pooled_probability_is_the_closed_form_probability_mean() -> None:
    """ELO-DATE-002-C1: p_pooled(A) = 0.5 * p_overall(A) + 0.5 * p_surface(A).

    One overall pair (1600 vs 1500) and one surface pair (1500 vs 1700 on Clay),
    both worked out here rather than read back from the engine:

        p_overall = 1 / (1 + 10 ** ((1500 - 1600) / 400)) = 1 / (1 + 10 ** -0.25)
        p_surface = 1 / (1 + 10 ** ((1700 - 1500) / 400)) = 1 / (1 + 10 ** 0.5)
        p_pooled  = (p_overall + p_surface) / 2
    """
    engine = elo.PooledElo()
    a = elo.player_key("1", "")
    b = elo.player_key("2", "")
    engine.overall[a], engine.overall[b] = 1600.0, 1500.0
    engine.surface[(a, "Clay")], engine.surface[(b, "Clay")] = 1500.0, 1700.0

    expected_overall = 1.0 / (1.0 + 10.0**-0.25)
    expected_surface = 1.0 / (1.0 + 10.0**0.5)
    expected_pooled = 0.5 * expected_overall + 0.5 * expected_surface

    p_overall, p_surface, p_pooled = engine.pooled_probability(a, b, "Clay")
    assert p_overall == expected_overall
    assert p_surface == expected_surface
    assert p_pooled == expected_pooled
    # p_overall = 0.6400649998028851, p_surface = 0.2402530733520421, and the
    # double-precision mean of the two is the value this baseline is frozen at.
    assert repr(p_overall) == "0.6400649998028851"
    assert repr(p_surface) == "0.2402530733520421"
    assert repr(p_pooled) == "0.4401590365774636"
    # Not the Elo logistic of a blended rating difference (the superseded pre-C1 form).
    rating_blend = engine.probability(0.5 * (1600.0 + 1500.0), 0.5 * (1500.0 + 1700.0))
    assert abs(p_pooled - rating_blend) > 0.01


def test_pooling_is_the_probability_mean_not_a_rating_blend() -> None:
    """ELO-DATE-002-C1.design.md line 7: mean of probabilities."""
    engine = elo.PooledElo()
    x = elo.player_key("1", "")
    y = elo.player_key("2", "")
    engine.overall[x], engine.overall[y] = 1700.0, 1500.0
    engine.surface[(x, "Clay")], engine.surface[(y, "Clay")] = 1500.0, 1800.0
    p_overall, p_surface, p_pooled = engine.pooled_probability(x, y, "Clay")
    assert p_pooled == 0.5 * p_overall + 0.5 * p_surface
    rating_blend = engine.probability(0.5 * (1700.0 + 1500.0), 0.5 * (1500.0 + 1800.0))
    assert abs(p_pooled - rating_blend) > 0.01


def test_single_match_update_is_k_times_the_surprise() -> None:
    engine = elo.PooledElo()
    engine.apply_batch(elo.parse_results([row()]))
    winner = elo.player_key("1", "")
    loser = elo.player_key("2", "")
    assert engine.overall_rating(winner) == pytest.approx(1516.0, abs=1e-12)
    assert engine.overall_rating(loser) == pytest.approx(1484.0, abs=1e-12)
    assert engine.surface_rating(winner, "Hard") == pytest.approx(1516.0, abs=1e-12)
    assert engine.surface_rating(loser, "Clay") == 1500.0


def test_ids_take_priority_over_names() -> None:
    assert elo.player_key("104925", "Novak Djokovic") == (0, 104925, "")
    assert elo.player_key("", "Novak Djokovic") == (1, 0, "novak djokovic")
    assert elo.player_key("", "Felix Auger-Aliassime") == (1, 0, "felix auger aliassime")


def test_state_as_of_prospective_and_state_hash() -> None:
    results = elo.parse_results(
        [
            row(),
            row(date="2026-02-05", winner_id="2", loser_id="3"),
        ]
    )
    early = elo.state_as_of(results, dt.date(2026, 1, 31))
    late = elo.state_as_of(results, dt.date(2026, 12, 31))
    assert (early.applied_rows, late.applied_rows) == (1, 2)
    assert early.state_hash() != late.state_hash()
    assert early.state_hash() == elo.state_as_of(results, dt.date(2026, 1, 31)).state_hash()
    priced = late.prospective(
        elo.player_key("1", ""),
        elo.player_key("3", ""),
        "Grass",
        best_of=5,
        date=dt.date(2026, 8, 31),
    )
    assert priced["p_x"] + priced["p_y"] == pytest.approx(1.0, abs=1e-12)
    assert priced["best_of_used_by_model"] is False
    assert priced["cold_start_surface"] is True
    # Grass is unplayed for both, so the surface half is exactly 0.5 and the
    # pooled number is the mean of that and the overall probability.
    assert priced["p_surface_x"] == pytest.approx(0.5, abs=1e-12)
    assert priced["p_x"] == pytest.approx(0.5 * priced["p_overall_x"] + 0.25, abs=1e-12)
    assert priced["p_x"] > 0.5
    assert priced["p_x"] < priced["p_overall_x"]


def test_replay_respects_the_lag_and_neutral_orientation() -> None:
    results = elo.parse_results(
        [
            row(),
            row(date="2026-01-06", round="R16"),
            row(date="2026-01-20", round="QF"),
        ]
    )
    predictions = list(elo.replay(results, lag_days=2))
    assert [p.eligible_through.isoformat() for p in predictions] == [
        "2026-01-03",
        "2026-01-04",
        "2026-01-18",
    ]
    assert predictions[0].p_pooled_a == pytest.approx(0.5, abs=1e-12)
    assert predictions[1].p_pooled_a == pytest.approx(0.5, abs=1e-12)
    assert predictions[2].p_pooled_a > 0.5
    for prediction in predictions:
        assert prediction.player_a < prediction.player_b
        assert prediction.p_pooled_a + prediction.p_pooled_b == pytest.approx(1.0, abs=1e-12)


def test_unsupported_inputs_are_refused() -> None:
    for bad in (
        row(surface="Indoor Hard"),
        row(best_of="4"),
        row(tour="ITF"),
        row(winner_id="1", loser_id="1"),
        row(winner_id="", winner_name=""),
    ):
        with pytest.raises(ValueError):
            elo.parse_results([bad])


def test_normalization_rules() -> None:
    assert elo.normalize_name("Ramos-Vinolas") == "ramos vinolas"
    assert elo.normalize_name("  Novak  Djokovic!  ") == "novak djokovic"
    assert elo.normalize_name("Zverev A.") == "zverev a"


def test_serialization_is_stable_and_key_ordered() -> None:
    engine = elo.state_as_of(elo.parse_results([row()]), dt.date(2026, 1, 31))
    payload = json.loads(engine.serialize())
    assert payload["model_id"] == elo.MODEL_ID
    assert payload["pooling_domain"] == "probability_space_mean"
    assert payload["applied_rows"] == 1
    assert payload["latest_source_date"] == "2026-01-05"
    # Ratings are serialized with repr(), so the state file round-trips exactly.
    assert payload["overall"] == [["1", "1516.0", 1], ["2", "1484.0", 1]]
    assert payload["surface"] == [["1", "Hard", "1516.0", 1], ["2", "Hard", "1484.0", 1]]
    assert engine.serialize() == json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_probability_function_adapter() -> None:
    engine = elo.state_as_of(elo.parse_results([row()]), dt.date(2026, 1, 31))
    price = elo.probability_function(engine, "Hard", best_of=5)
    x, y = elo.player_key("1", ""), elo.player_key("2", "")
    assert price(x, y) == engine.pooled_probability(x, y, "Hard")[2]
    assert price(x, y) + price(y, x) == pytest.approx(1.0, abs=1e-12)


def test_cli_writes_predictions_and_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    from tennislab.config import reset_workspace_cache

    reset_workspace_cache()
    try:
        source = tmp_path / "results.csv"
        source.write_text(
            ",".join(elo.RESULT_COLUMNS)
            + "\n"
            + ",".join(str(UNIT_ROW[column]) for column in elo.RESULT_COLUMNS)
            + "\n",
            encoding="utf-8",
        )
        assert elo._cli(["results.csv", "--out", "p.jsonl", "--state-out", "state.json"]) == 0
        prediction = json.loads((tmp_path / "p.jsonl").read_text(encoding="utf-8").strip())
        assert prediction["p_pooled_a"] == 0.5
        assert prediction["eligible_through"] == "2026-01-03"
        assert (
            json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["applied_rows"] == 0
        )
    finally:
        reset_workspace_cache()
