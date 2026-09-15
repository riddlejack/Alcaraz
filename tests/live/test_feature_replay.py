from __future__ import annotations

import csv
import datetime as dt
import json
from dataclasses import replace
from pathlib import Path

import pytest

from tennislab.chain.common import sha256
from tennislab.chronology.ranking_lookup import LookupRequest, RankingLookup
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache
from tennislab.features import base
from tennislab.live.common import LiveConfig, LiveError
from tennislab.live.feature_replay import (
    QualifiedPanel,
    _base_feature,
    _fixture_record,
    _input_review_binding,
    _qualified,
)
from tennislab.live.fixtures import eligible_history, serve_freshness
from tennislab.live.readiness import _snapshot
from tests.live import world
from tests.live.world import CONFIG, Runner


def _record(match_id: str, day: int, player_a: int, player_b: int, a_won: bool | None):
    counts_a = base.Counts(5, 2, 60, 35, 25, 12, 3, 5) if a_won is not None else None
    counts_b = base.Counts(3, 3, 58, 34, 23, 11, 2, 5) if a_won is not None else None
    return base.Record(
        match_id=match_id,
        match_date=dt.date(2024, 1, day),
        calendar_year=2024,
        source_season=2024,
        tourney_id="2024-SYN",
        tourney_name="Synthetic",
        tourney_level="A",
        competition_type="individual_tour",
        round="R16",
        surface="Hard",
        best_of=3,
        court_recorded="Outdoor",
        player_a=player_a,
        player_b=player_b,
        a_won=a_won,
        identity_tier="primary",
        status="prospective" if a_won is None else "completed",
        date_basis="synthetic",
        archive_date_basis="synthetic",
        source_field_agreement=True,
        counts_a=counts_a,
        counts_b=counts_b,
        ps_probability_a=0.55 if a_won is not None else None,
    )


def test_exact_base_replay_visits_native_target_dates() -> None:
    history = [_record("h1", 1, 1, 2, True), _record("h2", 10, 1, 3, False)]
    target = _record("target", 31, 1, 2, None)
    ranking_rows = [
        {
            "effective_date": date,
            "rank": str(index),
            "player_id": str(player),
            "ranking_points": str(1000 - 100 * index),
            "source_member": "synthetic",
            "source_physical_line": str(index),
        }
        for date in ("2023-12-25", "2024-01-08", "2024-01-29")
        for index, player in enumerate((1, 2, 3), 1)
    ]
    lookup = RankingLookup.from_rows(ranking_rows)
    records = [*history, target]
    requests = sorted(
        {
            (record.match_date, player)
            for record in records
            for player in (record.player_a, record.player_b)
        }
    )
    ranking = dict(
        zip(
            requests,
            lookup.lookup_many([LookupRequest(*request) for request in requests]),
            strict=True,
        )
    )
    expected = dict(base.stream_rows(records, ranking, base.FIXED_PARAMETERS))[target]
    panel = QualifiedPanel(tuple(), tuple(history), "0" * 64, Path("synthetic.csv"), {})
    actual = _base_feature(panel, target, lookup)
    assert actual == expected
    future = replace(history[0], match_id="future", match_date=dt.date(2024, 2, 5), a_won=False)
    future_panel = replace(panel, records=(*panel.records, future))
    assert _base_feature(future_panel, target, lookup) == actual


def test_trained_route_rejects_fixture_outcome_and_stats() -> None:
    fixture = {
        "fixture_id": "prospective",
        "scheduled_start_local_date": "2026-09-17",
        "player_a_id": "1",
        "player_b_id": "2",
        "event_id": "2026-SYN",
        "event_name": "Synthetic",
        "level": "A",
        "round": "R16",
        "surface": "Hard",
        "best_of": 3,
        "a_svpt": "60",
    }
    with pytest.raises(LiveError, match="outcome/stat fields .*a_svpt"):
        _fixture_record(fixture)


def test_modeled_event_after_completion_is_a_contradiction() -> None:
    row = {
        "model_event_date": "2026-09-12",
        "completion_upper_bound": "2026-09-11",
        "completion_basis": "observed",
        "publication_upper_bound_utc": "2026-09-11T20:00:00Z",
        "receipt_time_utc": "2026-09-11T20:00:00Z",
        "overlap_unresolved": "false",
    }
    with pytest.raises(LiveError, match="modeled event date after completion upper bound"):
        _qualified(
            row,
            admitted_bases={"observed"},
            cutoff=dt.date(2026, 9, 15),
            issue_time=dt.datetime(2026, 9, 15, 20, tzinfo=dt.UTC),
            index=2,
            label="synthetic panel",
        )
    assert (
        _qualified(
            {**row, "completion_upper_bound": "", "overlap_unresolved": "true"},
            admitted_bases={"observed"},
            cutoff=dt.date(2026, 9, 15),
            issue_time=dt.datetime(2026, 9, 15, 20, tzinfo=dt.UTC),
            index=2,
            label="synthetic panel",
        )
        == "overlap_unresolved"
    )


def test_input_review_receipt_cannot_cover_a_different_history_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = world.build_workspace(tmp_path)
    manifest_path = workspace / "input_manifest.json"
    manifest_path.write_text(
        json.dumps({"history_candidates": {"ATP": {"sha256": "f" * 64}}}),
        encoding="utf-8",
    )
    manifest_sha = sha256(manifest_path)
    receipt_path = workspace / "input_review.json"
    receipt_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "checked_utc": "2026-09-15T19:00:00Z",
                "manifest_sha256": manifest_sha,
            }
        ),
        encoding="utf-8",
    )
    config_path = workspace / CONFIG
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["feature_replay"]["input_review_receipt"] = {
        "path": "input_review.json",
        "sha256": sha256(receipt_path),
        "checked_utc": "2026-09-15T19:00:00Z",
        "input_manifest_path": "input_manifest.json",
        "input_manifest_sha256": manifest_sha,
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv(WORKSPACE_ENVIRONMENT_VARIABLE, str(workspace))
    reset_workspace_cache()
    try:
        with pytest.raises(LiveError, match="history binding differs"):
            _input_review_binding(LiveConfig(CONFIG), "ATP")
    finally:
        reset_workspace_cache()


def test_empty_incremental_results_use_bound_history_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = world.build_workspace(tmp_path)
    monkeypatch.setenv(WORKSPACE_ENVIRONMENT_VARIABLE, str(workspace))
    reset_workspace_cache()
    loaded = {
        "manifest": {
            "content_sha256": "a" * 64,
            "counts": {"results": 0, "serve_state": 2, "rankings": 2},
            "serve_frontier_observed": {"ATP": "2026-09-01", "WTA": "2026-09-01"},
            "ranking_frontier_observed": {"ATP": "2026-06-08", "WTA": "2026-06-08"},
        },
        "results": [],
        "serve": [{"tour": "ATP"}, {"tour": "WTA"}],
        "rankings": [{"tour": "ATP"}, {"tour": "WTA"}],
    }
    monkeypatch.setattr(
        "tennislab.live.readiness.versions.latest_version", lambda config: Path("v")
    )
    monkeypatch.setattr("tennislab.live.readiness.versions.load_version", lambda path: loaded)
    try:
        report = _snapshot(
            LiveConfig(CONFIG), {"ATP": {"status": "ready"}, "WTA": {"status": "ready"}}
        )
    finally:
        reset_workspace_cache()
    assert report["status"] == "ready"
    assert report["tours"]["results"] == []
    assert report["coverage_tours"]["results"] == ["ATP", "WTA"]
    assert report["results_mode"] == "bound_history_no_live_delta"
    assert report["incremental_results_rows"] == 0


def test_serve_state_age_is_separate_from_availability_age() -> None:
    freshness = serve_freshness(
        [
            {
                "tour": "ATP",
                "player_id": "1",
                "event_anchor": "2026-01-01",
                "model_event_date": "2026-01-01",
                "date_basis": "qualified_annual_reported_date_not_publication_clock",
                "completion_upper_bound": "2026-09-11",
                "completion_basis": "observed_in_archive_at_receipt",
                "match_id": "history",
                "fields_present": "ace svpt",
                "fields_missing": "",
                "serve_block_valid": "true",
                "source_id": "accepted_panel",
                "receipt_id": "receipt",
                "overlap_unresolved": "false",
            }
        ],
        tour="ATP",
        player_id="1",
        cutoff=dt.date(2026, 9, 15),
        start=dt.date(2026, 9, 17),
    )
    assert freshness["state_as_of"] == "2026-01-01"
    assert freshness["staleness_days"] == 259
    assert freshness["staleness_basis"] == "model_event_date"
    assert freshness["availability_age_days"] == 6


def test_history_availability_bound_does_not_replace_modeled_event_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    workspace = world.build_workspace(tmp_path)
    Runner(workspace, capsys)
    history_path = workspace / "data/live/history/atp_results.csv"
    with history_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = [*(reader.fieldnames or []), "model_event_date"]
        rows = [dict(row) for row in reader]
    for row in rows:
        row["model_event_date"] = row["date"]
        row["completion_upper_bound"] = "2026-08-01"
    world.write_csv(history_path, header, rows)
    config_path = workspace / CONFIG
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["history"]["ATP"]["sha256"] = sha256(history_path)
    config_path.write_text(json.dumps(config), encoding="utf-8")

    monkeypatch.setenv(WORKSPACE_ENVIRONMENT_VARIABLE, str(workspace))
    reset_workspace_cache()
    try:
        eligible, _, withheld, _ = eligible_history(
            LiveConfig(CONFIG),
            "ATP",
            cutoff=dt.date(2026, 8, 9),
            issue_time=dt.datetime(2026, 8, 10, 12, tzinfo=dt.UTC),
        )
    finally:
        reset_workspace_cache()
    assert len(eligible) == 10
    assert max(result.date for result in eligible) == dt.date(2026, 7, 27)
    assert withheld["model_event_after_cutoff"] == 0
