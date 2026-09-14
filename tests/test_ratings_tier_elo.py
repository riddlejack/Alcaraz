"""Ported from the archive's ``TIER01_models/test_tier01.py``: ``EngineChanges``,
``SyntheticReplay`` and ``TrainingWindowOffsets``, importing from the package.

The synthetic panel's reference Elo columns are produced by the parent
``tennislab.ratings.elo.replay``, so the regression compares ``tier_elo`` against the
engine itself rather than against a constant. The fixture writes ``labels.csv`` with the
fixed label header, because the port reads outcomes through the label accessor, which
checks every returned row's metadata against ``features.csv``.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
from collections.abc import Iterator
from pathlib import Path

import pytest

from tennislab.chain.common import ChainError
from tennislab.chain.labels import LABEL_COLUMNS
from tennislab.config import reset_workspace_cache
from tennislab.models import pipeline
from tennislab.ratings import elo, tier_elo, tier_stream

YEAR_PLAN = {
    "panel_end_year": 2020,
    "feature_end_year": 2020,
    "target_years": [2020],
    "calibration_years_back": 3,
    "history_floor_year": 2011,
    "training_window_years": 5,
}
FULL_PLAN = {
    "panel_end_year": 2024,
    "feature_end_year": 2024,
    "target_years": list(range(2017, 2025)),
    "calibration_years_back": 3,
    "history_floor_year": 2011,
    "training_window_years": 5,
}

# (match_id, date, player_a, player_b, a_won)
TOUR = (
    ("T1", "2020-01-06", 101, 102, 1),
    ("T2", "2020-01-13", 101, 103, 1),
    ("T3", "2020-03-02", 102, 103, 0),
    ("T4", "2020-03-09", 101, 102, 1),
    ("T5", "2020-06-01", 101, 201, 0),
    ("T6", "2020-07-01", 101, 201, 1),
)
# (match_id, date, winner, loser, tier, is_final)
LOWER = [
    ("L1", "2020-01-02", 201, 202, "futures", 0),
    ("L2", "2020-02-01", 201, 202, "challenger", 1),
    ("L3", "2020-03-07", 102, 201, "challenger", 0),  # exactly T4's D-2 cutoff
    ("L4", "2020-03-08", 102, 202, "challenger", 0),  # one day too late for T4
]
# 309 further challenger rows so player 201 crosses both caps before T6.
for _index in range(309):
    LOWER.append(
        (
            f"B{_index:03d}",
            (dt.date(2020, 4, 1) + dt.timedelta(days=_index // 12)).isoformat(),
            201,
            202,
            "challenger",
            1 if _index < 24 else 0,
        )
    )

FEATURE_HEADER = (
    "match_id",
    "calendar_year",
    "source_season",
    "match_date",
    "tourney_id",
    "tourney_name",
    "tourney_level",
    "round",
    "surface",
    "best_of",
    "player_a",
    "player_b",
    "primary_target",
    "identity_tier",
    "source_field_agreement",
    "elo_overall_logit",
    "elo_surface_logit",
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    yield tmp_path
    reset_workspace_cache()


@pytest.fixture(autouse=True)
def _restore_pipeline_years() -> Iterator[None]:
    yield
    pipeline.configure_years(pipeline.DEFAULT_YEAR_PLAN)


# --------------------------------------------------------------- the engine


def one_match(tier: str, winner: int, loser: int, date: str = "2020-05-04") -> list:
    source = "MULTI01-panel" if tier == "tour" else f"TIER01-{tier}"
    return elo.parse_results(
        [
            {
                "date": date,
                "tour": "ATP",
                "tournament": "T",
                "level": "C",
                "round": "R32",
                "surface": "Hard",
                "best_of": "3",
                "winner_id": str(winner),
                "loser_id": str(loser),
                "winner_name": "",
                "loser_name": "",
                "source": source,
            }
        ]
    )


@pytest.mark.parametrize(
    ("tier", "expected"),
    [("tour", 16.0), ("challenger", 12.8), ("qualifying", 12.8), ("futures", 9.6)],
)
def test_k_multiplier_by_tier(tier: str, expected: float) -> None:
    engine = tier_elo.make_engine(tier_elo.DECLARED_MULTIPLIERS, 0.0)
    engine.apply_batch(one_match(tier, 101, 102))
    key_a = elo.player_key("101", "")
    key_b = elo.player_key("102", "")
    # Both start equal, so p = 0.5 and the delta is k * multiplier * 0.5.
    assert engine.overall_rating(key_a) - 1500.0 == pytest.approx(expected, abs=1e-12)
    assert 1500.0 - engine.overall_rating(key_b) == pytest.approx(expected, abs=1e-12)
    assert engine.surface_rating(key_a, "Hard") - 1500.0 == pytest.approx(expected, abs=1e-12)


def test_a_lower_tier_debut_starts_at_the_offset() -> None:
    engine = tier_elo.make_engine(tier_elo.DECLARED_MULTIPLIERS, -120.0)
    key = elo.player_key("201", "")
    assert engine.overall_rating(key) == 1500.0  # never seen: the tour default
    engine.apply_batch(one_match("futures", 201, 202))
    assert engine.debut_tier[key] == "futures"
    # 1500 - 120 + 32*0.6*0.5
    assert engine.overall_rating(key) == pytest.approx(1380.0 + 9.6, abs=1e-12)
    assert engine.surface_rating(key, "Hard") == pytest.approx(1380.0 + 9.6, abs=1e-12)


def test_a_tour_debut_keeps_the_tour_default() -> None:
    engine = tier_elo.make_engine(tier_elo.DECLARED_MULTIPLIERS, -120.0)
    engine.apply_batch(one_match("tour", 101, 102))
    key = elo.player_key("101", "")
    assert engine.debut_tier[key] == "tour"
    assert engine.overall_rating(key) == pytest.approx(1516.0, abs=1e-12)


def test_an_unknown_stream_source_is_refused() -> None:
    with pytest.raises(tier_elo.TierEloError):
        tier_elo.tier_of_source("TIER01-wta")


def test_with_no_lower_tier_row_the_engine_is_the_parent() -> None:
    parent = elo.PooledElo()
    tiered = tier_elo.make_engine(tier_elo.DECLARED_MULTIPLIERS, -120.0)
    batch = one_match("tour", 101, 102)
    parent.apply_batch(batch)
    tiered.apply_batch(batch)
    assert parent.serialize() == tiered.serialize()


# --------------------------------------------------------------- the synthetic panel


def tour_stream_rows() -> list[dict[str, str]]:
    rows = []
    for match_id, date, a, b, a_won in TOUR:
        winner, loser = (a, b) if a_won else (b, a)
        rows.append(
            {
                "date": date,
                "tour": "ATP",
                "tournament": "T",
                "level": "A",
                "round": "R32",
                "surface": "Hard",
                "best_of": "3",
                "winner_id": str(winner),
                "loser_id": str(loser),
                "winner_name": "",
                "loser_name": "",
                "source": "MULTI01-panel",
                "match_id": match_id,
            }
        )
    return rows


def write_fixture(directory: Path, lower: list[tuple] | None = None) -> dict[str, Path]:
    """Write features.csv, labels.csv and tier_results.csv.gz for the synthetic panel."""
    rows = tour_stream_rows()
    reference = {}
    for prediction, row in zip(elo.replay(elo.parse_results(rows), lag_days=2), rows, strict=True):
        reference[row["match_id"]] = (
            repr(float(prediction.elo_overall_logit)),
            repr(float(prediction.elo_surface_logit)),
        )
    directory.mkdir(parents=True, exist_ok=True)
    features = directory / "features.csv"
    with features.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FEATURE_HEADER), lineterminator="\n")
        writer.writeheader()
        for match_id, date, a, b, _a_won in TOUR:
            overall, surface = reference[match_id]
            writer.writerow(
                {
                    "match_id": match_id,
                    "calendar_year": date[:4],
                    "source_season": date[:4],
                    "match_date": date,
                    "tourney_id": f"{date[:4]}-T",
                    "tourney_name": "T",
                    "tourney_level": "A",
                    "round": "R32",
                    "surface": "Hard",
                    "best_of": "3",
                    "player_a": a,
                    "player_b": b,
                    "primary_target": "1",
                    "identity_tier": "primary",
                    "source_field_agreement": "0",
                    "elo_overall_logit": overall,
                    "elo_surface_logit": surface,
                }
            )
    labels = directory / "labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LABEL_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for match_id, date, _a, _b, a_won in TOUR:
            writer.writerow(
                {
                    "match_id": match_id,
                    "calendar_year": date[:4],
                    "source_season": date[:4],
                    "match_date": date,
                    "tourney_id": f"{date[:4]}-T",
                    "identity_tier": "primary",
                    "primary_target": "1",
                    "a_won": a_won,
                    "status": "completed",
                    "source_field_agreement": "0",
                }
            )

    results = directory / "tier_results.csv.gz"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(tier_stream.RESULT_FIELDS), lineterminator="\n")
    writer.writeheader()
    for match_id, date, winner, loser, tier, is_final in lower or LOWER:
        writer.writerow(
            {
                "date": date,
                "tour": "ATP",
                "tournament": "L",
                "level": "C",
                "round": "F" if is_final else "R32",
                "surface": "Hard",
                "best_of": "3",
                "winner_id": winner,
                "loser_id": loser,
                "winner_name": "",
                "loser_name": "",
                "source": f"TIER01-{tier}",
                "match_id": f"tier:x:{match_id}",
                "family": "atp_futures" if tier == "futures" else "atp_qual_chall",
                "tier": tier,
                "season": date[:4],
                "anchor_date": date,
                "is_final": is_final,
            }
        )
    results.write_bytes(gzip.compress(buffer.getvalue().encode("utf-8"), mtime=0))
    return {"features": features, "labels": labels, "tier_results": results}


def elo_config(
    directory: Path, paths: dict[str, Path], *, offset=None, include_lower_tier: bool = True
) -> dict:
    return {
        "year_plan": dict(YEAR_PLAN),
        "tier_elo": {
            "elo_engine": {"path": "references/CONFIRM2026_elo/elo_engine.py", "sha256": "0" * 64},
            "features": {"path": str(paths["features"])},
            "labels": {"path": str(paths["labels"])},
            "tier_results": {"path": str(paths["tier_results"])},
            "include_lower_tier": include_lower_tier,
            "parameters": {
                "lag_calendar_days": 2,
                "elo_start_year": 2005,
                "experience_start_year": 1991,
                "offset_measurement_end_year": 2020,
                "prior_match_cap": 300,
                "prior_title_cap": 20,
                "k_multipliers": dict(tier_elo.DECLARED_MULTIPLIERS),
                "lower_tier_initial_offset": offset,
            },
            "output_dir": str(directory / "out"),
        },
    }


def read_emitted(directory: Path) -> list[dict[str, str]]:
    with (directory / "out" / "tier_elo_features.csv").open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def run_fixture(
    directory: Path, lower: list[tuple] | None = None, *, include_lower_tier: bool = True
) -> tuple[dict, list[dict[str, str]]]:
    paths = write_fixture(directory, lower)
    config = elo_config(directory, paths, include_lower_tier=include_lower_tier)
    if include_lower_tier:
        measurement = tier_elo.run(config, measure_only=True)
        config["tier_elo"]["parameters"]["lower_tier_initial_offset"] = measurement[
            "offset_measurement"
        ]["lower_tier_initial_offset"]
    summary = tier_elo.run(config)
    return summary, read_emitted(directory)


# --------------------------------------------------------------- the replay


def test_with_no_lower_tier_stream_the_elo_columns_are_reproduced_exactly(workspace: Path) -> None:
    summary, emitted = run_fixture(workspace, include_lower_tier=False)
    regression = summary["regression_against_multi01_elo"]
    assert regression["rows_compared"] == len(TOUR)
    assert regression["max_abs_diff_elo_overall_logit"] == 0.0
    assert regression["max_abs_diff_elo_surface_logit"] == 0.0
    assert regression["exact"] is True
    assert summary["stream"]["lower_tier_elo_rows"] == 0
    assert tuple(emitted[0]) == tier_elo.FEATURE_FIELDS
    for row in emitted:
        assert row["tier_prior_matches_raw_a"] == "0"
        assert row["tier_prior_titles_raw_b"] == "0"
    assert "a_won" not in emitted[0]


def test_the_lower_tier_stream_changes_the_logits(workspace: Path) -> None:
    summary, _ = run_fixture(workspace)
    assert summary["regression_against_multi01_elo"]["max_abs_diff_elo_overall_logit"] > 0.0
    assert summary["stream"]["source_rows_applied_by_tier"]["futures"] == 1
    assert summary["stream"]["players_with_a_lower_tier_debut"] > 0
    assert summary["code"]["declared_binding"]["path"] == "references/CONFIRM2026_elo/elo_engine.py"
    assert summary["code"]["elo_engine"]["module"] == "tennislab.ratings.elo"
    assert summary["outcome_reads"] == [
        {"purpose": tier_elo.ELO_STATE_PURPOSE, "rows": len(TOUR), "year_ceiling": 2020}
    ]


def test_d_minus_two_admits_the_cutoff_day_and_refuses_the_day_after(workspace: Path) -> None:
    _, emitted = run_fixture(workspace)
    rows = {row["match_id"]: row for row in emitted}
    # T4 is 2020-03-09, so its cutoff is 2020-03-07: L3 (that day) counts for player
    # 102 and L4 (2020-03-08) does not.
    assert rows["T4"]["player_b"] == "102"
    assert rows["T4"]["tier_prior_matches_raw_b"] == "1"
    assert rows["T4"]["tier_last_lower_match_days_b"] == "2"
    assert rows["T5"]["player_a"] == "101"
    assert rows["T5"]["tier_prior_matches_raw_a"] == "0"


def test_the_experience_counts_are_capped_at_300_and_20(workspace: Path) -> None:
    _, emitted = run_fixture(workspace)
    target = {row["match_id"]: row for row in emitted}["T6"]
    assert target["player_b"] == "201"
    assert int(target["tier_prior_matches_raw_b"]) > 300
    assert int(target["tier_prior_titles_raw_b"]) > 20
    assert target["tier_prior_matches_b"] == "300"
    assert target["tier_prior_titles_b"] == "20"


def test_the_first_tier_and_offset_provenance_follow_the_debut(workspace: Path) -> None:
    _, emitted = run_fixture(workspace)
    row = {row["match_id"]: row for row in emitted}["T6"]
    assert row["tier_first_tier_b"] == "futures"
    assert row["tier_initial_offset_applied_b"] == "1"
    assert row["tier_first_tier_a"] == "tour"
    assert row["tier_initial_offset_applied_a"] == "0"


def test_a_declared_offset_that_drifts_is_refused(workspace: Path) -> None:
    paths = write_fixture(workspace)
    with pytest.raises(tier_elo.TierEloError):
        tier_elo.run(elo_config(workspace, paths, offset=-1.0))


def test_appending_a_later_lower_tier_match_changes_no_earlier_row(workspace: Path) -> None:
    _, before = run_fixture(workspace / "first")
    later = [*LOWER, ("LZ", "2020-12-31", 201, 102, "challenger", 1)]
    _, after = run_fixture(workspace / "second", later)
    assert before == after


def test_a_lower_tier_row_after_the_panel_end_year_is_refused(workspace: Path) -> None:
    later = [*LOWER, ("LZ", "2021-02-01", 201, 102, "challenger", 0)]
    with pytest.raises(tier_elo.TierEloError):
        run_fixture(workspace, later)


def test_a_label_whose_metadata_drifts_from_the_feature_row_is_refused(workspace: Path) -> None:
    """The accessor, not this stage, checks the join; the read is declared as history."""
    paths = write_fixture(workspace)
    text = (
        paths["labels"]
        .read_text(encoding="utf-8")
        .replace("T1,2020,2020,2020-01-06", "T1,2020,2020,2020-01-07")
    )
    paths["labels"].write_text(text, encoding="utf-8")
    with pytest.raises(ChainError, match="match_date mismatch"):
        tier_elo.run(elo_config(workspace, paths, include_lower_tier=False))
    with pytest.raises(tier_elo.TierEloError):
        tier_elo.EloStateHistory(paths["labels"], "0" * 64, year_ceiling=0)


def test_the_satellite_circuit_end_date_is_the_date_a_leg_enters_the_state(workspace: Path) -> None:
    """Astra finding 3 through the public interface: a leg enters on its corrected date."""
    corrected = dt.date(2006, 3, 27).isoformat()
    _, emitted = run_fixture(workspace, [("LS", corrected, 201, 202, "challenger", 0)])
    rows = {row["match_id"]: row for row in emitted}
    assert rows["T5"]["tier_prior_matches_raw_b"] == "1"
    assert rows["T5"]["tier_last_lower_match_days_b"] == str(
        (dt.date(2020, 6, 1) - dt.date(2006, 3, 27)).days
    )


# ------------------------------------------------- the offset and every boundary


def test_the_horizon_is_the_day_before_every_training_window_starts() -> None:
    plan = pipeline.configure_years(FULL_PLAN)
    for year in plan.raw_years:
        start, _end = pipeline.training_window(year)
        assert tier_elo.offset_window_start(year, plan) == start, year
        assert tier_elo.offset_year_horizon(year, plan) == start.year - 1, year


def test_the_horizon_never_reaches_the_year_it_serves() -> None:
    plan = pipeline.configure_years(FULL_PLAN)
    for year in range(2005, 2025):
        assert tier_elo.offset_year_horizon(year, plan) < max(year, 2011), year


def test_the_2014_to_2016_selector_years_no_longer_read_2016() -> None:
    """The specific defect: one number measured through 2016 served 2014's fits."""
    plan = pipeline.configure_years(FULL_PLAN)
    for year in (2014, 2015, 2016):
        assert tier_elo.offset_year_horizon(year, plan) == 2010, year


def test_an_unknown_offset_mode_is_refused(workspace: Path) -> None:
    paths = write_fixture(workspace)
    config = elo_config(workspace, paths, offset=-1.0)
    config["tier_elo"]["parameters"]["offset_mode"] = "whatever"
    with pytest.raises(tier_elo.TierEloError):
        tier_elo.run(config)


def test_per_window_mode_refuses_an_undeclared_and_a_drifted_offset(workspace: Path) -> None:
    paths = write_fixture(workspace)
    config = elo_config(workspace, paths)
    config["tier_elo"]["parameters"]["offset_mode"] = "per_training_window"
    with pytest.raises(tier_elo.TierEloError):
        tier_elo.run(config)
    measurement = tier_elo.run(config, measure_only=True)
    horizons = measurement["offset_horizon_by_year"]
    measured = measurement["offset_measurement_by_horizon"]
    declared = {
        year: measured[str(horizon)]["lower_tier_initial_offset"]
        for year, horizon in horizons.items()
    }
    config["tier_elo"]["parameters"]["lower_tier_initial_offset_by_year"] = {
        **declared,
        "2020": 0.5,
    }
    with pytest.raises(tier_elo.TierEloError):
        tier_elo.run(config)
    config["tier_elo"]["parameters"]["lower_tier_initial_offset_by_year"] = declared
    summary = tier_elo.run(config)
    assert summary["offset_by_training_window"]["mode"] == "per_training_window"
    assert (workspace / "out" / "tier_offsets_by_year.csv").is_file()


def test_the_offset_receipt_precedes_every_row_it_is_applied_to(workspace: Path) -> None:
    """Rule 8: each learned offset carries the horizon it was measured through, and that
    horizon precedes every row the offset serves inside the plan's fit range."""
    paths = write_fixture(workspace)
    config = elo_config(workspace, paths)
    config["tier_elo"]["parameters"]["offset_mode"] = "per_training_window"
    measurement = tier_elo.run(config, measure_only=True)
    config["tier_elo"]["parameters"]["lower_tier_initial_offset_by_year"] = {
        year: measurement["offset_measurement_by_horizon"][str(horizon)][
            "lower_tier_initial_offset"
        ]
        for year, horizon in measurement["offset_horizon_by_year"].items()
    }
    tier_elo.run(config)
    with (workspace / "out" / "tier_offsets_by_year.csv").open(newline="", encoding="utf-8") as h:
        receipts = list(csv.DictReader(h))
    assert tuple(receipts[0]) == tier_elo.OFFSET_FIELDS
    assert [int(row["season"]) for row in receipts] == list(range(2005, 2021))
    emitted = {row["match_id"]: row["match_date"] for row in read_emitted(workspace)}
    for row in receipts:
        season = int(row["season"])
        measured_through = dt.date.fromisoformat(row["offset_measured_through"])
        window_start = dt.date.fromisoformat(row["training_window_start"])
        assert measured_through < window_start, row
        # A season inside the fit range is served by a horizon strictly before it; the
        # seasons before the history floor are never fit rows and take the floor window.
        if season >= YEAR_PLAN["history_floor_year"]:
            assert measured_through < dt.date(season, 1, 1), row
        else:
            assert window_start == dt.date(YEAR_PLAN["history_floor_year"], 1, 1), row
        applied_to = [date for date in emitted.values() if int(date[:4]) == season]
        for date in applied_to:
            assert measured_through < dt.date.fromisoformat(date), (row, date)
    # Every emitted row is a 2020 row, served by the horizon before 2015-01-01.
    served = {row["season"]: row["offset_measured_through"] for row in receipts}
    assert served["2020"] == "2014-12-31"
