"""Ported from the archive's ``TIER01_models/test_tier01.py``: ``OneColumnList`` (the
tier_block half; the pipeline half lives in ``test_models_pipeline.py``), importing from
the package, plus the join itself on a synthetic sidecar.

The archive ran ``verify_forbidden`` against the real MULTI01 column dictionary when it
was on disk; here a dictionary of the same 162/22/6 shape is written into the scratch
workspace so the guard runs unconditionally.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from tennislab.chain.common import ChainError
from tennislab.config import reset_workspace_cache
from tennislab.features import tier_block
from tennislab.models import pipeline
from tennislab.ratings import tier_elo

YEAR_PLAN = {
    "panel_end_year": 2019,
    "feature_end_year": 2019,
    "target_years": [2019],
    "calibration_years_back": 3,
    "history_floor_year": 2011,
    "training_window_years": 5,
}
BINARY_CONTEXT = tuple(
    f"context_{name}"
    for name in ("clay", "grass", "carpet", "best_of_5", "indoor", "indoor_unknown")
)
SIGNED = tuple(f"base_{index}" for index in range(22))
LINEAR = (*SIGNED, *(f"linear_{index}" for index in range(140)))


@pytest.fixture(autouse=True)
def _restore_bundles() -> Iterator[None]:
    yield
    pipeline.configure_bundles()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    yield tmp_path
    reset_workspace_cache()


def write_dictionary(path: Path, **overrides: list[str]) -> Path:
    document = {
        "linear_sports_model_features": list(LINEAR),
        "signed_base_model_features": list(SIGNED),
        "binary_context_columns": list(BINARY_CONTEXT),
        "identifier_and_split_columns": ["match_id"],
        "label_file_columns": ["a_won", "status"],
        **overrides,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# --------------------------------------------------------------- one column list


def test_pipeline_and_builder_agree() -> None:
    assert pipeline.TIER_SIGNED == tier_block.TIER_SIGNED
    assert pipeline.TIER_DYNAMIC_SIGNED == tier_block.TIER_DYNAMIC_SIGNED
    assert pipeline.TIER_PROVENANCE_ONLY_COLUMNS == tier_block.TIER_PROVENANCE_ONLY_COLUMNS
    assert pipeline.TIER_DYNAMIC_PROBABILITY == tier_block.TIER_DYNAMIC_PROBABILITY
    assert pipeline.TIER_NOQUAL_DYNAMIC_SIGNED == tier_block.TIER_NOQUAL_DYNAMIC_SIGNED
    assert pipeline.TIER_NOQUAL_DYNAMIC_PROBABILITY == tier_block.TIER_NOQUAL_DYNAMIC_PROBABILITY
    assert (
        pipeline.TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS
        == tier_block.TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS
    )


def test_no_tier_model_column_is_forbidden_and_every_provenance_column_is() -> None:
    model = (*tier_block.TIER_SIGNED, *tier_block.TIER_DYNAMIC_SIGNED)
    assert sorted(pipeline.FORBIDDEN_MODEL_COLUMNS.intersection(model)) == []
    provenance = {
        *tier_block.TIER_PROVENANCE_ONLY_COLUMNS,
        *tier_block.TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS,
    }
    assert sorted(provenance - pipeline.FORBIDDEN_MODEL_COLUMNS) == []
    # The sidecar block is the signed inputs, the dynamic probability and the provenance.
    assert len(tier_block.SIDECAR_COLUMNS) == 4 + 1 + 20
    assert len(tier_block.NOQUAL_SIDECAR_COLUMNS) == 1 + 3


def test_the_tier_elo_stage_emits_every_column_the_block_reads() -> None:
    read_from_elo = {
        name
        for name in tier_block.TIER_PROVENANCE_ONLY_COLUMNS
        if not name.startswith(("tier_prior_tour", "tier_thin", "tier_dynamic"))
    } | {"tier_elo_overall_logit", "tier_elo_surface_logit"}
    assert read_from_elo <= set(tier_elo.FEATURE_FIELDS)


def test_the_forbidden_guard_passes_on_a_contract_shaped_dictionary(tmp_path: Path) -> None:
    dictionary = write_dictionary(tmp_path / "dictionary.json")
    report = tier_block.verify_forbidden(dictionary)
    assert report["in_model_column_set"] is False
    assert report["in_forbidden_model_columns"] is True
    assert report["base_tier_signed_columns"] == 22 + 4
    assert report["full_tier_signed_columns"] == 22 + 7 + 1 + 4 + 1
    assert "full_tier_noqual_signed_columns" not in report
    ablated = tier_block.verify_forbidden(dictionary, noqual=True)
    assert ablated["full_tier_noqual_signed_columns"] == ablated["full_tier_signed_columns"]
    assert ablated["provenance_only_columns"][-3:] == list(
        tier_block.TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS
    )


def test_the_forbidden_guard_refuses_a_provenance_column_in_a_model_list(tmp_path: Path) -> None:
    linear = list(LINEAR)
    linear[-1] = "tier_thin_side"
    dictionary = write_dictionary(tmp_path / "dictionary.json", linear_sports_model_features=linear)
    with pytest.raises(ChainError):
        tier_block.verify_forbidden(dictionary)


# --------------------------------------------------------------- prior tour history


def test_tour_history_counts_through_the_cutoff_by_bisect() -> None:
    history = tier_block.TourHistory()
    for day in (1, 3, 5):
        history.add(7, dt.date(2019, 5, day))
    assert history.count_through(7, dt.date(2019, 4, 30)) == 0
    assert history.count_through(7, dt.date(2019, 5, 3)) == 2
    assert history.count_through(7, dt.date(2019, 5, 4)) == 2
    assert history.count_through(8, dt.date(2019, 5, 4)) == 0
    with pytest.raises(tier_block.TierBlockError):
        history.add(7, dt.date(2019, 5, 4))


def test_panel_order_thin_counts_replicate_the_audits_no_lag_rule() -> None:
    rows = [
        {"match_id": "A", "match_date": "2019-01-01", "player_a": "1", "player_b": "2"},
        {"match_id": "B", "match_date": "2019-01-02", "player_a": "1", "player_b": "2"},
        {"match_id": "C", "match_date": "2019-01-03", "player_a": "1", "player_b": "3"},
    ]
    report = tier_block.panel_order_thin_counts(rows, 2)
    assert report["thin_by_year"] == {2019: 3}
    assert report["rows_by_year"] == {2019: 3}
    assert report["thin_2017_2024"] == 3
    report = tier_block.panel_order_thin_counts(rows, 1)
    assert report["thin_by_year"] == {2019: 2}


# --------------------------------------------------------------- the join


SIDECAR_FIELDS = (
    "match_id",
    "match_date",
    "player_a",
    "player_b",
    "primary_target",
    "identity_tier",
    "sr02_selected_match_present",
    "dynamic_match_probability_a",
    "trait_z_age_diff",
)
# (match_id, date, a, b, primary, dynamic probability)
SIDECAR = (
    ("R1", "2019-05-10", 10, 20, "1", "0.55"),
    ("R2", "2019-05-12", 10, 30, "1", ""),
    ("R3", "2019-05-20", 20, 30, "0", "0.4"),
)


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def elo_row(match_id: str, date: str, a: int, b: int, *, raw_b: int = 0) -> dict:
    row = dict.fromkeys(tier_elo.FEATURE_FIELDS, "")
    row.update(
        {
            "match_id": match_id,
            "match_date": date,
            "surface": "Hard",
            "player_a": a,
            "player_b": b,
            "tier_elo_overall_logit": "0.25",
            "tier_elo_surface_logit": "-0.125",
            "tier_prior_matches_a": 0,
            "tier_prior_matches_b": min(raw_b, 300),
            "tier_prior_titles_a": 0,
            "tier_prior_titles_b": min(raw_b // 10, 20),
            "tier_prior_matches_raw_a": 0,
            "tier_prior_matches_raw_b": raw_b,
            "tier_prior_titles_raw_a": 0,
            "tier_prior_titles_raw_b": raw_b // 10,
            "tier_first_tier_a": "tour",
            "tier_first_tier_b": "futures" if raw_b else "",
            "tier_initial_offset_applied_a": 0,
            "tier_initial_offset_applied_b": int(bool(raw_b)),
            "tier_last_lower_match_days_a": "",
            "tier_last_lower_match_days_b": 30 if raw_b else "",
            "tier_history_absent_overall_a": 0,
            "tier_history_absent_overall_b": int(not raw_b),
            "tier_history_absent_surface_a": 0,
            "tier_history_absent_surface_b": int(not raw_b),
            "elo_overall_logit_base": "0.2",
            "elo_surface_logit_base": "-0.1",
        }
    )
    return row


def build_fixture(root: Path, *, noqual: bool = True) -> dict:
    inputs = root / "inputs"
    inputs.mkdir()
    # The panel: twenty earlier rows for player 10, one for player 20 the day before R1
    # (inside R1's D-2 lag, so it does not count for R1 but does for R3), and the targets.
    panel = [
        {
            "match_id": f"P{index:02d}",
            "match_date": (dt.date(2018, 1, 1) + dt.timedelta(days=index)).isoformat(),
            "player_a": "10",
            "player_b": str(1000 + index),
            "identity_tier": "primary",
        }
        for index in range(20)
    ]
    panel.append(
        {
            "match_id": "P20",
            "match_date": "2019-05-09",
            "player_a": "20",
            "player_b": "40",
            "identity_tier": "primary",
        }
    )
    panel.extend(
        {
            "match_id": m,
            "match_date": d,
            "player_a": str(a),
            "player_b": str(b),
            "identity_tier": "primary",
        }
        for m, d, a, b, _p, _q in SIDECAR
    )
    write_csv(inputs / "panel.csv", tuple(panel[0]), panel)
    write_csv(
        inputs / "sidecar.csv",
        SIDECAR_FIELDS,
        [
            {
                "match_id": m,
                "match_date": d,
                "player_a": a,
                "player_b": b,
                "primary_target": p,
                "identity_tier": "primary",
                "sr02_selected_match_present": int(q != ""),
                "dynamic_match_probability_a": q,
                "trait_z_age_diff": "0.1",
            }
            for m, d, a, b, p, q in SIDECAR
        ],
    )
    write_csv(
        inputs / "tier_elo_features.csv",
        tier_elo.FEATURE_FIELDS,
        [elo_row(m, d, a, b, raw_b=315 if m == "R1" else 0) for m, d, a, b, _p, _q in SIDECAR],
    )
    dynamic_fields = (
        "match_id",
        "dynamic_match_probability_a",
        "dynamic_state_stale_days_a",
        "dynamic_state_stale_days_b",
        "dynamic_state_stale_days",
    )
    dynamic = [
        {
            "match_id": m,
            "dynamic_match_probability_a": "0.6" if m == "R1" else "0.45",
            "dynamic_state_stale_days_a": 3,
            "dynamic_state_stale_days_b": 9,
            "dynamic_state_stale_days": 9,
        }
        for m, _d, _a, _b, _p, q in SIDECAR
        if q != ""
    ]
    write_csv(inputs / "tier_dynamic.csv", dynamic_fields, dynamic)
    ablated = [{**row, "dynamic_match_probability_a": "0.5"} for row in dynamic]
    write_csv(inputs / "tier_noqual_dynamic.csv", dynamic_fields, ablated)
    write_dictionary(inputs / "column_dictionary.json")
    section = {
        "panel": {"path": "inputs/panel.csv"},
        "sidecar": {"path": "inputs/sidecar.csv"},
        "tier_elo_features": {"path": "inputs/tier_elo_features.csv"},
        "tier_dynamic": {"path": "inputs/tier_dynamic.csv"},
        "base_dictionary": {"path": "inputs/column_dictionary.json"},
        "parameters": {"lag_calendar_days": 2, "thin_side_prior_match_threshold": 20},
        "output_dir": "out/tier_block",
    }
    if noqual:
        section["tier_noqual_dynamic"] = {"path": "inputs/tier_noqual_dynamic.csv"}
    return {"year_plan": dict(YEAR_PLAN), "tier_block": section}


def test_the_block_is_appended_after_every_sidecar_column(workspace: Path) -> None:
    summary = tier_block.run(build_fixture(workspace))
    out = workspace / "out/tier_block"
    with (out / "trait_latent_sidecar.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        rows = {row["match_id"]: row for row in reader}
    assert header == (
        *SIDECAR_FIELDS,
        *tier_block.SIDECAR_COLUMNS,
        *tier_block.NOQUAL_SIDECAR_COLUMNS,
    )
    assert set(rows) == {"R1", "R2", "R3"}
    r1, r2, r3 = rows["R1"], rows["R2"], rows["R3"]
    # The signed differences use the capped counts; the raw counts are provenance.
    assert r1["tier_prior_matches_diff"] == "-300.0"
    assert r1["tier_prior_titles_diff"] == "-20.0"
    assert r1["tier_prior_matches_raw_b"] == "315"
    # Membership: the tier probability is blank exactly where the base one is blank.
    assert r1["tier_dynamic_match_probability_a"] == "0.6"
    assert r2["tier_dynamic_match_probability_a"] == ""
    assert r2["tier_dynamic_state_stale_days"] == ""
    assert r1["tier_noqual_dynamic_match_probability_a"] == "0.5"
    # The D-2 prior tour count: player 20's 05-09 row is inside R1's lag, not R3's.
    assert (r1["tier_prior_tour_matches_a"], r1["tier_prior_tour_matches_b"]) == ("20", "0")
    assert r1["tier_thin_side"] == "1"
    assert (r2["tier_prior_tour_matches_a"], r2["tier_prior_tour_matches_b"]) == ("21", "0")
    assert (r3["tier_prior_tour_matches_a"], r3["tier_prior_tour_matches_b"]) == ("2", "1")
    assert r3["tier_thin_side"] == "1"
    # Every original value survives untouched.
    assert r1["trait_z_age_diff"] == "0.1" and r1["dynamic_match_probability_a"] == "0.55"

    assert summary["counters"] == {"rows": 3, "thin_side_rows": 3, "tier_dynamic_present": 2}
    thin = summary["thin_side_2017_2024"]
    assert thin["primary_rows"] == 2  # R3 is not a primary target
    assert thin["thin_side_rows"] == 2
    assert thin["thin_side_with_lower_history"] == 1  # R1's thin side b has lower history
    assert thin["aligned_primary_candidates"] == 1
    assert (
        summary["panel_order_thin_side"]["thin_2017_2024"] == 24
    )  # every panel row is thin, no lag
    assert summary["forbidden_check"]["full_tier_noqual_signed_columns"] == 35
    assert summary["code"]["runner"]["module"] == "tennislab.models.pipeline"
    assert summary["inputs"]["panel"]["path"] == "inputs/panel.csv"

    dictionary = json.loads((out / "tier_dictionary.json").read_text(encoding="utf-8"))
    assert dictionary["tier_noqual_dynamic_model_feature"] == ["tier_noqual_dynamic_match_logit"]
    assert "full_tier_noqual" in dictionary["bundles"]
    with gzip.open(out / "tier_detail.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        detail = list(csv.DictReader(handle))
    assert [row["aligned_primary_candidate"] for row in detail] == ["1", "0", "0"]
    with (out / "thin_side_membership.csv").open(newline="", encoding="utf-8") as handle:
        membership = list(csv.DictReader(handle))
    assert [(row["match_id"], row["thin_side"]) for row in membership] == [("R1", "b"), ("R2", "b")]


def test_without_the_ablation_replay_no_noqual_column_is_written(workspace: Path) -> None:
    tier_block.run(build_fixture(workspace, noqual=False))
    out = workspace / "out/tier_block"
    with (out / "trait_latent_sidecar.csv").open(newline="", encoding="utf-8") as handle:
        header = tuple(csv.DictReader(handle).fieldnames or ())
    assert header == (*SIDECAR_FIELDS, *tier_block.SIDECAR_COLUMNS)
    dictionary = json.loads((out / "tier_dictionary.json").read_text(encoding="utf-8"))
    assert dictionary["tier_noqual_dynamic_sidecar_input"] is None
    assert list(dictionary["bundles"]) == ["base_tier", "full_tier"]


def test_a_membership_difference_between_tier_and_base_dynamic_is_refused(workspace: Path) -> None:
    config = build_fixture(workspace)
    path = workspace / "inputs/tier_dynamic.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line for line in lines if not line.startswith("R1,")) + "\n")
    with pytest.raises(tier_block.TierBlockError, match="different target set"):
        tier_block.run(config)
    config["tier_block"].pop("tier_noqual_dynamic")
    with pytest.raises(tier_block.TierBlockError, match="membership differ"):
        tier_block.run(config)


def test_the_lag_and_threshold_are_fixed(workspace: Path) -> None:
    config = build_fixture(workspace)
    config["tier_block"]["parameters"]["lag_calendar_days"] = 1
    with pytest.raises(tier_block.TierBlockError):
        tier_block.run(config)
    config["tier_block"]["parameters"]["lag_calendar_days"] = 2
    config["tier_block"]["parameters"]["thin_side_prior_match_threshold"] = 10
    with pytest.raises(tier_block.TierBlockError):
        tier_block.run(config)
