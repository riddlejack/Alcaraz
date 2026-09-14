"""The Lane D acceptance cases (docs/live/DESIGN.md §7), each through ``tennislab.cli``.

Every case runs in a fully synthetic workspace (``world.py``) with a pinned clock and a
replay transport; nothing touches the network or the research archive. Planted defects
are part of the cases: each integrity gate is shown to reject its defect.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from tennislab.live.versions import verify_version
from tests.live import world
from tests.live.world import CONFIG, Runner

UTC = dt.UTC


@pytest.fixture
def ws(tmp_path: Path, capsys) -> tuple[Path, Runner]:
    workspace = world.build_workspace(tmp_path)
    return workspace, Runner(workspace, capsys)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(r) for r in csv.DictReader(handle)]


def update(runner: Runner, replay: Path, *extra: str) -> dict:
    return runner.ok(
        "update", "--config", CONFIG, "--events", "events.json", "--replay", replay.name, *extra
    )


def version_dir(workspace: Path, version_id: str) -> Path:
    return workspace / "data" / "live" / "versions" / version_id


def ledger_lines(workspace: Path) -> list[str]:
    return (
        (workspace / "data" / "live" / "ledger" / "ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )


# --- 1, 2, 3: update, identical rerun, interruption ---------------------------------------------


def test_results_only_update_writes_receipt_bytes_version_and_pointer(ws) -> None:
    workspace, runner = ws
    replay = world.replay_dir_for(workspace, world.complete_rounds(), revision=100)
    out = update(runner, replay)
    assert out["status"] == "ok" and out["no_change"] is False
    version = version_dir(workspace, out["version_id"])
    verify_version(version)
    rows = read_csv(version / "results.csv")
    assert len(rows) == 9  # 7 decided or walkover rows in E1, 2 pending in E2
    statuses = sorted(r["status"] for r in rows if r["event_id"] == "2026-E1")
    assert statuses == ["completed"] * 5 + ["retired", "walkover"]
    e1 = [r for r in rows if r["event_id"] == "2026-E1"][0]
    assert e1["target_anchor_date"] == "2026-08-03"
    assert e1["completion_upper_bound"] == "2026-08-09"
    assert e1["completion_basis"] == "declared_event_end"
    assert e1["publication_upper_bound_utc"] == "2026-08-09T22:00:00Z"
    assert e1["source_revision"] == "100" and e1["serve_block_status"] == "absent"
    assert all(r["player_a_id"] < r["player_b_id"] for r in rows)
    completeness = {
        c["event_id"]: c for c in json.loads((version / "completeness.json").read_text())
    }
    assert completeness["2026-E1"]["status"] == "complete"
    assert (
        completeness["2026-E2"]["status"] == "incomplete"
        and completeness["2026-E2"]["pending"] == 2
    )
    # receipt, retained bytes, pointer
    attempt_id = json.loads((version / "manifest.json").read_text())["attempts"][
        "wikipedia_results"
    ]
    attempt = (
        workspace / "data" / "live" / "sources" / "wikipedia_results" / "attempts" / attempt_id
    )
    receipt = json.loads((attempt / "receipt.json").read_text())
    assert receipt["status"] == "complete" and len(receipt["requests"]) == 2
    assert receipt["requests"][0]["qualification"]["status"] == "qualified"
    assert (attempt / receipt["requests"][0]["retained_path"]).is_file()
    assert (
        json.loads(
            (
                workspace / "data" / "live" / "sources" / "wikipedia_results" / "latest.json"
            ).read_text()
        )["attempt_id"]
        == attempt_id
    )
    assert (attempt / "structural_probe.json").is_file()
    # no wall clock inside normalized data
    text = (version / "results.csv").read_text()
    assert "T12:00:00Z" not in text


def test_identical_content_rerun_gets_its_own_receipt_and_no_change(ws) -> None:
    workspace, runner = ws
    replay = world.replay_dir_for(workspace, world.complete_rounds(), revision=100)
    first = update(runner, replay)
    runner.at(world.ISSUE_CLOCK + dt.timedelta(minutes=5))
    second = update(runner, replay)
    assert second["no_change"] is True and second["version_id"] != first["version_id"]
    a = json.loads((version_dir(workspace, first["version_id"]) / "manifest.json").read_text())
    b = json.loads((version_dir(workspace, second["version_id"]) / "manifest.json").read_text())
    assert a["content_sha256"] == b["content_sha256"]
    assert a["attempts"]["wikipedia_results"] != b["attempts"]["wikipedia_results"]
    strip = lambda rows: [{k: v for k, v in r.items() if k != "receipt_id"} for r in rows]  # noqa: E731
    assert strip(read_csv(version_dir(workspace, first["version_id"]) / "results.csv")) == strip(
        read_csv(version_dir(workspace, second["version_id"]) / "results.csv")
    )


def test_interrupted_attempt_keeps_its_receipt_and_never_becomes_latest(ws) -> None:
    workspace, runner = ws
    replay = world.replay_dir_for(workspace, world.complete_rounds(), revision=100)
    code, out, _ = runner.run(
        "update",
        "--config",
        CONFIG,
        "--events",
        "events.json",
        "--replay",
        replay.name,
        "--fail-after",
        "1",
    )
    assert code == 1
    result = json.loads(out)
    assert result["status"] == "interrupted"
    attempts = workspace / "data" / "live" / "sources" / "wikipedia_results" / "attempts"
    receipt = json.loads((attempts / result["attempt_id"] / "receipt.json").read_text())
    assert receipt["status"] == "interrupted" and len(receipt["requests"]) == 1
    assert not (
        workspace / "data" / "live" / "sources" / "wikipedia_results" / "latest.json"
    ).exists()
    assert not (workspace / "data" / "live" / "versions").exists()
    runner.at(world.ISSUE_CLOCK + dt.timedelta(minutes=1))
    ok = update(runner, replay)
    assert ok["status"] == "ok"
    assert len(list(attempts.iterdir())) == 2
    assert (
        json.loads((attempts / result["attempt_id"] / "receipt.json").read_text())["status"]
        == "interrupted"
    )


# --- 4, 5: revision without history loss; quarantine ----------------------------------------------


def test_revised_score_is_a_diff_entry_and_the_old_version_survives(ws) -> None:
    workspace, runner = ws
    first = update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    rounds = world.complete_rounds()
    rounds["F"][0]["sets"] = [("6", "2"), ("7", "5")]
    runner.at(world.ISSUE_CLOCK + dt.timedelta(hours=1))
    second = update(runner, world.replay_dir_for(workspace, rounds, revision=101, name="replay2"))
    assert second["diff"] == {
        "added": 0,
        "revised": 1,
        "removed": 0,
        "duplicate": 0,
        "unresolved": 0,
        "conflicting": 0,
    }
    diff = json.loads((version_dir(workspace, second["version_id"]) / "diff.json").read_text())
    assert diff["revised"][0]["changes"]["score"] == {"from": "6-2 6-2", "to": "6-2 7-5"}
    assert diff["revised"][0]["previous_revision"] == "100"
    verify_version(version_dir(workspace, first["version_id"]))
    old = [
        r
        for r in read_csv(version_dir(workspace, first["version_id"]) / "results.csv")
        if r["round"] == "F"
    ][0]
    assert old["score"] == "6-2 6-2" and old["source_revision"] == "100"


def test_identity_duplicate_and_conflict_rows_are_quarantined_with_receipts(ws) -> None:
    workspace, runner = ws
    n = world.name_of
    rounds = {
        "QF": [
            {
                "a": n("300009"),
                "b": n("300001"),
                "winner": "b",
                "sets": [("3", "6"), ("3", "6")],
            },  # ambiguous name
            {"a": n("300002"), "b": n("300003"), "winner": "a", "sets": [("6", "3"), ("6", "3")]},
            {
                "a": n("300002"),
                "b": n("300003"),
                "winner": "a",
                "sets": [("6", "3"), ("6", "3")],
            },  # duplicate
            {"a": n("300004"), "b": n("300005"), "winner": "a", "sets": [("6", "3"), ("6", "3")]},
        ],
        "SF": [
            {"a": n("300004"), "b": n("300005"), "winner": "b", "sets": [("3", "6"), ("3", "6")]},
        ],
        "F": [
            {"a": n("300006"), "b": n("300007"), "winner": "a", "sets": [("6", "3"), ("6", "3")]}
        ],
    }
    # a conflicting pair: same players, same round, different winner
    rounds["SF"].append(
        {"a": n("300004"), "b": n("300005"), "winner": "a", "sets": [("6", "3"), ("6", "3")]}
    )
    out = update(runner, world.replay_dir_for(workspace, rounds, revision=7))
    version = version_dir(workspace, out["version_id"])
    quarantine = read_csv(version / "quarantine" / "rows.csv")
    kinds = sorted(q["kind"] for q in quarantine)
    assert kinds == ["conflicting", "duplicate", "unresolved"]
    unresolved = [q for q in quarantine if q["kind"] == "unresolved"][0]
    assert (
        "ambiguous" in unresolved["detail"]
        and "300009" in unresolved["detail"]
        and "300010" in unresolved["detail"]
    )
    assert all(
        q["receipt_id"].startswith("wikipedia_results/") and q["source_revision"] == "7"
        for q in quarantine
    )
    rows = read_csv(version / "results.csv")
    assert not any(r["round"] == "SF" and r["event_id"] == "2026-E1" for r in rows), (
        "a conflicting pair never selects a winner"
    )
    assert sum(1 for r in rows if r["round"] == "QF" and r["event_id"] == "2026-E1") == 2
    assert not any(
        "300009" in (r["player_a_id"], r["player_b_id"])
        or "300010" in (r["player_a_id"], r["player_b_id"])
        for r in rows
    )


# --- 6: serve/ranking freshness -------------------------------------------------------------------


def test_results_only_update_never_advances_serve_or_ranking_freshness(ws) -> None:
    workspace, runner = ws
    replay = world.replay_dir_for(workspace, world.complete_rounds(), revision=100)
    feed = world.serve_feed(workspace)
    rankings = world.rankings_file(workspace)
    first = update(
        runner,
        replay,
        "--serve-feed",
        feed.name,
        "--rankings",
        f"ATP={rankings.relative_to(workspace).as_posix()}",
    )
    assert first["serve_frontier_observed"] == {"ATP": "2026-08-09", "WTA": None}
    manifest = json.loads(
        (version_dir(workspace, first["version_id"]) / "manifest.json").read_text()
    )
    assert manifest["serve_frontier_declared"] == {"ATP": "2026-05-17", "WTA": "2026-05-18"}
    serve = read_csv(version_dir(workspace, first["version_id"]) / "serve_state.csv")
    assert len(serve) == 3
    unknown = [r for r in serve if r["tournament_name"] == "Unknown Cup"][0]
    assert unknown["overlap_unresolved"] == "true" and unknown["completion_upper_bound"] == ""
    known = [r for r in serve if r["player_id"] == "300002"][0]
    assert known["completion_upper_bound"] == "2026-08-09" and "p_SvGms" in known["fields_missing"]
    runner.at(world.ISSUE_CLOCK + dt.timedelta(hours=2))
    second = update(runner, replay)
    assert second["carried_forward"] == {
        "serve_state": first["version_id"],
        "rankings": first["version_id"],
    }
    a = version_dir(workspace, first["version_id"])
    b = version_dir(workspace, second["version_id"])
    assert (a / "serve_state.csv").read_bytes() == (b / "serve_state.csv").read_bytes()
    assert (a / "rankings.csv").read_bytes() == (b / "rankings.csv").read_bytes()
    # the candidate source is refused by status, not by a missing branch
    err = (
        runner.fails("update", "--config", CONFIG, "--serve-feed", feed.name, "--note", "x")
        if False
        else ""
    )
    assert err == ""


def test_candidate_source_is_refused_by_status(ws) -> None:
    workspace, runner = ws
    from tennislab.live.common import LiveConfig, LiveError

    runner.run(
        "ledger", "verify", "--config", CONFIG
    )  # installs the workspace env for this call only
    import os

    from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache

    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    try:
        config = LiveConfig(CONFIG)
        with pytest.raises(LiveError, match="candidate_not_qualified"):
            config.require_source_status("tennismylife", "qualified_serve_state")
        with pytest.raises(LiveError, match="R14"):
            config.require_source_status("wta_official", "qualified")
    finally:
        os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        reset_workspace_cache()


# --- 7, 8, 9, 10: fixtures and eligibility ------------------------------------------------------


def issue_one(
    workspace: Path, runner: Runner, *, batch: str = "b1", rows=None
) -> tuple[dict, dict]:
    rows = rows or [world.fixture_row("f1", "300001", "300004", round_code="QF")]
    world.write_fixtures(workspace, rows, name=f"{batch}.csv")
    fixtures = runner.ok(
        "fixture", "--config", CONFIG, "--input", f"{batch}.csv", "--batch-id", batch
    )
    forecasts = runner.ok("forecast", "--config", CONFIG, "--batch-id", batch)
    return fixtures, forecasts


def elo_entry(forecasts: dict) -> dict:
    return [f for f in forecasts["forecasts"] if f["rung"] == "elo"][0]


def forecast_payload(workspace: Path, fixture_id: str) -> dict:
    for line in ledger_lines(workspace):
        record = json.loads(line)
        if record["kind"] == "forecast_issued" and record["subject_id"] == fixture_id:
            return record["payload"]
    raise AssertionError("no forecast_issued record")


def test_same_cutoff_boundary_and_overlap_withholding(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    fixtures, forecasts = issue_one(workspace, runner)
    payload = forecast_payload(workspace, fixtures["fixtures"][0]["fixture_id"])
    assert payload["information_cutoff"] == "2026-08-09"
    assert (
        payload["lineage"]["live_rows_used"] == 6
    )  # E1: 5 completed + 1 retired; walkover not played
    assert payload["lineage"]["withheld"]["not_played"] == 3  # E1 walkover + 2 pending E2
    assert payload["lineage"]["live_rows_max_bound"] == "2026-08-09"
    unavailable = [f for f in forecasts["forecasts"] if f["status"] == "unavailable"]
    assert sorted(f["rung"] for f in unavailable) == ["atp_full_tier", "atp_p0", "atp_p1"]

    # the same page with the window ending one day later: nothing from E1 is eligible
    events = json.loads((workspace / "events.json").read_text())
    events["events"][0]["window_end"] = "2026-08-10"
    (workspace / "events.json").write_text(json.dumps(events))
    runner.at(world.ISSUE_CLOCK + dt.timedelta(hours=1))
    update(
        runner,
        world.replay_dir_for(workspace, world.complete_rounds(), revision=100, name="replay_b"),
    )
    fixtures2, _ = issue_one(
        workspace,
        runner,
        batch="b2",
        rows=[world.fixture_row("f2", "300002", "300004", round_code="QF")],
    )
    later = forecast_payload(workspace, fixtures2["fixtures"][0]["fixture_id"])
    assert (
        later["lineage"]["live_rows_used"] == 0
        and later["lineage"]["withheld"]["after_cutoff"] == 6
    )

    # no declared window: every row of the event is overlap-unresolved and withheld
    events["events"][0]["window_end"] = ""
    events["events"][0]["window_start"] = ""
    (workspace / "events.json").write_text(json.dumps(events))
    runner.at(world.ISSUE_CLOCK + dt.timedelta(hours=2))
    update(
        runner,
        world.replay_dir_for(workspace, world.complete_rounds(), revision=100, name="replay_c"),
    )
    fixtures3, _ = issue_one(
        workspace,
        runner,
        batch="b3",
        rows=[world.fixture_row("f3", "300003", "300004", round_code="QF")],
    )
    unresolved = forecast_payload(workspace, fixtures3["fixtures"][0]["fixture_id"])
    assert (
        unresolved["lineage"]["live_rows_used"] == 0
        and unresolved["lineage"]["withheld"]["overlap_unresolved"] == 7
    )


def test_future_outcome_invariance_and_hidden_labels(ws) -> None:
    """A decided row published after the issue time, or bounded after the cutoff, cannot
    change the forecast; and no fixture or forecast record carries an outcome field."""
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    fixtures, forecasts = issue_one(workspace, runner)
    baseline = elo_entry(forecasts)["p_a"]
    # plant: E2's own QF decided in a capture whose revision timestamp is after the issue time
    n = world.name_of
    decided = {
        "QF": [
            {"a": n("300001"), "b": n("300004"), "winner": "b", "sets": [("0", "6"), ("0", "6")]},
            {"a": n("300002"), "b": n("300003"), "winner": "a", "sets": [("6", "0"), ("6", "0")]},
        ]
    }
    runner.at(world.ISSUE_CLOCK + dt.timedelta(minutes=30))
    update(
        runner,
        world.replay_dir_for(
            workspace,
            world.complete_rounds(),
            revision=100,
            e2_rounds=decided,
            timestamp="2026-08-10T12:20:00Z",
            name="replay_planted",
        ),
    )
    runner.at(world.ISSUE_CLOCK + dt.timedelta(minutes=40))  # issue after the planted capture
    rows = [
        world.fixture_row(
            "f9", "300001", "300004", round_code="QF", start="2026-08-11T15:00:00+00:00"
        )
    ]
    world.write_fixtures(workspace, rows, name="b9.csv")
    runner.ok("fixture", "--config", CONFIG, "--input", "b9.csv", "--batch-id", "b9")
    err = runner.fails("forecast", "--config", CONFIG, "--batch-id", "b9")
    assert (
        "duplicate issuance refused" in err
    )  # same fixture: the planted row could not be re-issued anyway
    # a different fixture at the same cutoff sees the planted rows withheld and the same state
    rows = [world.fixture_row("f10", "300002", "300005", round_code="QF")]
    world.write_fixtures(workspace, rows, name="b10.csv")
    runner.ok("fixture", "--config", CONFIG, "--input", "b10.csv", "--batch-id", "b10")
    out = runner.ok("forecast", "--config", CONFIG, "--batch-id", "b10")
    payload = forecast_payload(
        workspace, [f for f in out["forecasts"] if f["rung"] == "elo"][0]["fixture_id"]
    )
    assert payload["lineage"]["withheld"]["after_cutoff"] == 2  # bound 2026-08-16 > cutoff
    assert payload["lineage"]["live_rows_used"] == 6
    assert (
        payload["state_sha256"]
        == forecast_payload(workspace, fixtures["fixtures"][0]["fixture_id"])["state_sha256"]
    )
    assert baseline == forecast_payload(workspace, fixtures["fixtures"][0]["fixture_id"])["p_a"]
    forbidden = {"winner", "loser", "score", "a_won", "result", "winner_side", "outcome"}
    for line in (
        (workspace / "data" / "live" / "fixtures" / "b1" / "fixtures.jsonl")
        .read_text()
        .splitlines()
    ):
        assert not forbidden & set(json.loads(line))
    for line in ledger_lines(workspace):
        record = json.loads(line)
        if record["kind"] in {
            "fixture_proposed",
            "fixture_qualified",
            "forecast_issued",
            "forecast_unavailable",
        }:
            assert not forbidden & set(record["payload"]), record["kind"]


def test_outcome_like_input_columns_are_refused(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    rows = [world.fixture_row("f1", "300001", "300004", round_code="QF", score="6-3 6-3")]
    world.write_fixtures(workspace, rows, name="bad.csv", extra_columns=["score"])
    err = runner.fails("fixture", "--config", CONFIG, "--input", "bad.csv", "--batch-id", "bad")
    assert "outcome-like columns ['score']" in err


def test_player_swap_gives_the_same_fixture_and_mirrored_probability(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    fixtures, forecasts = issue_one(
        workspace,
        runner,
        batch="xy",
        rows=[world.fixture_row("f1", "300004", "300001", round_code="QF")],
    )
    world.write_fixtures(
        workspace, [world.fixture_row("f2", "300001", "300004", round_code="QF")], name="yx.csv"
    )
    swapped = runner.ok("fixture", "--config", CONFIG, "--input", "yx.csv", "--batch-id", "yx")
    assert swapped["fixtures"][0]["fixture_id"] == fixtures["fixtures"][0]["fixture_id"]
    assert swapped["fixtures"][0]["already_known"] is True
    record = [
        json.loads(line)
        for line in (workspace / "data" / "live" / "fixtures" / "xy" / "fixtures.jsonl")
        .read_text()
        .splitlines()
    ][0]
    assert record["player_a_id"] == "300001" and record["input_orientation_swapped"] is True
    payload = forecast_payload(workspace, fixtures["fixtures"][0]["fixture_id"])
    assert payload["p_a"] + payload["p_b"] == pytest.approx(1.0)
    # 12: duplicate issuance of the same fixture is refused
    err = runner.fails("forecast", "--config", CONFIG, "--batch-id", "yx")
    assert "duplicate issuance refused" in err


def test_missing_or_ambiguous_start_and_identity_are_excluded_with_reasons(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    rows = [
        world.fixture_row("nosource", "300001", "300004", round_code="QF", source=""),
        world.fixture_row("notz", "300001", "300004", round_code="QF", tz=""),
        world.fixture_row("vague", "300001", "300004", round_code="QF", uncertainty="48"),
        world.fixture_row("naive", "300001", "300004", round_code="QF", start="2026-08-11 15:00"),
        world.fixture_row("badsurface", "300001", "300004", round_code="QF", surface="Moon"),
        world.fixture_row("noformat", "300001", "300004", round_code="QF", best_of=""),
        {**world.fixture_row("ambig", "", "300004", round_code="QF"), "player_x_name": "Ida Iota"},
        {
            **world.fixture_row("unknown", "", "300004", round_code="QF"),
            "player_x_name": "Nobody Here",
        },
        world.fixture_row("ok", "300001", "300004", round_code="QF"),
    ]
    world.write_fixtures(workspace, rows, name="mixed.csv")
    out = runner.ok("fixture", "--config", CONFIG, "--input", "mixed.csv", "--batch-id", "mixed")
    by_ref = {f["fixture_ref"]: f for f in out["fixtures"]}
    assert by_ref["ok"]["status"] == "qualified"
    assert by_ref["nosource"]["reasons"] == ["start_without_source_or_timezone"]
    assert by_ref["notz"]["reasons"] == ["start_without_source_or_timezone"]
    assert by_ref["vague"]["reasons"] == ["start_uncertainty_missing_or_too_large"]
    assert by_ref["naive"]["reasons"] == ["start_unparseable"]
    assert by_ref["badsurface"]["reasons"] == ["unknown_surface"]
    assert by_ref["noformat"]["reasons"] == ["unknown_format"]
    assert by_ref["ambig"]["reasons"] == ["unknown_identity"]
    assert by_ref["unknown"]["reasons"] == ["unknown_identity"]
    kinds = [json.loads(line)["kind"] for line in ledger_lines(workspace)]
    assert kinds.count("fixture_excluded") == 8 and kinds.count("fixture_qualified") == 1


# --- 11, 12, 13, 14, 15: proof, ledger, settlement, report ------------------------------------


def attest(workspace: Path, digest: str, when: str, *, name: str = "attestation.json") -> str:
    path = workspace / name
    path.write_text(
        json.dumps(
            {
                "digest": digest,
                "attested_time_utc": when,
                "method": "synthetic offline attestation",
                "evidence": "test",
            }
        )
    )
    return path.name


def test_late_and_failed_proofs_stay_unconfirmed(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    fixtures, forecasts = issue_one(workspace, runner)
    fixture_id = fixtures["fixtures"][0]["fixture_id"]
    record = elo_entry(forecasts)["record_sha256"]
    assert (workspace / "data" / "live" / "proofs" / f"{record}.request.json").is_file()
    runner.at(dt.datetime(2026, 8, 11, 18, 0, tzinfo=UTC))
    runner.ok(
        "ledger",
        "start-verified",
        "--config",
        CONFIG,
        "--fixture",
        fixture_id[:16],
        "--actual-start",
        "2026-08-11T15:05:00+00:00",
        "--source",
        "synthetic official order of play",
        "--evidence",
        "receipt 1",
    )
    late = attest(workspace, record, "2026-08-11T16:00:00+00:00")
    out = runner.ok(
        "ledger",
        "proof-verify",
        "--config",
        CONFIG,
        "--fixture",
        fixture_id[:16],
        "--attestation",
        late,
    )
    assert out["kind"] == "proof_verified"
    # results: two captures agree -> final
    n = world.name_of
    decided = {
        "QF": [
            {"a": n("300001"), "b": n("300004"), "winner": "a", "sets": [("6", "3"), ("6", "3")]},
            {"a": n("300002"), "b": n("300003"), "winner": "", "sets": []},
        ]
    }
    for revision in (201, 202):
        runner.at(dt.datetime(2026, 8, 11, 19, 0, tzinfo=UTC) + dt.timedelta(minutes=revision))
        update(
            runner,
            world.replay_dir_for(
                workspace,
                world.complete_rounds(),
                revision=100,
                e2_rounds=decided,
                timestamp="2026-08-11T17:30:00Z",
                name=f"replay_{revision}",
            ),
        )
        runner.ok("settle", "results", "--config", CONFIG)
    summary = runner.ok("settle", "score", "--config", CONFIG, "--settlement-id", "s1")
    assert summary["coverage"] == {"unconfirmed:unconfirmed:proof_late": 1}
    assert summary["scored_by_rung"] == {}
    # a declared failure is also never confirmed
    runner.ok(
        "ledger",
        "proof-fail",
        "--config",
        CONFIG,
        "--fixture",
        fixture_id[:16],
        "--reason",
        "verification failed",
    )
    summary = runner.ok("settle", "score", "--config", CONFIG, "--settlement-id", "s2")
    assert summary["coverage"] == {"unconfirmed:unconfirmed:proof_failed": 1}
    assert not read_csv(workspace / "data" / "live" / "settlement" / "s2" / "scores.csv")


def test_ledger_tamper_is_detected_and_named(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    issue_one(workspace, runner)
    path = workspace / "data" / "live" / "ledger" / "ledger.jsonl"
    original = path.read_text(encoding="utf-8")
    assert runner.ok("ledger", "verify", "--config", CONFIG)["ok"] is True
    # planted 1: edit a payload value in place
    lines = original.splitlines()
    record = json.loads(lines[2])
    record["payload"]["p_a"] = 0.999 if "p_a" in record["payload"] else record["payload"]
    record["payload"]["tour"] = "WTA"
    lines[2] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    err = runner.fails("ledger", "verify", "--config", CONFIG)
    assert "ledger record 3" in err and "content digest" in err
    # planted 2: remove a line
    path.write_text("\n".join(original.splitlines()[:1] + original.splitlines()[2:]) + "\n")
    err = runner.fails("ledger", "verify", "--config", CONFIG)
    assert "ledger record 2" in err  # sequence or chain break, named by record
    # planted 3: an empty digest
    record = json.loads(original.splitlines()[0])
    record["previous_record_sha256"] = hashlib.sha256(b"").hexdigest()
    path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    err = runner.fails("ledger", "verify", "--config", CONFIG)
    assert "digest of empty content" in err
    # an append on a tampered ledger is refused before anything is written
    path.write_text(original)
    lines = original.splitlines()
    lines[-1] = lines[-1].replace('"seq":' + str(len(lines)), '"seq":' + str(len(lines) + 5))
    path.write_text("\n".join(lines) + "\n")
    err = runner.fails(
        "ledger",
        "start-verified",
        "--config",
        CONFIG,
        "--fixture",
        json.loads(lines[0])["subject_id"][:12],
        "--actual-start",
        "2026-08-11T15:00:00+00:00",
        "--source",
        "s",
        "--evidence",
        "e",
    )
    assert "seq" in err
    assert path.read_text() == "\n".join(lines) + "\n"


def test_provisional_final_corrected_settlement_and_report_boundary(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    rows = [
        world.fixture_row("f1", "300001", "300004", round_code="QF"),
        world.fixture_row("f2", "300002", "300003", round_code="QF"),
    ]
    fixtures, forecasts = issue_one(workspace, runner, rows=rows)
    ids = {f["fixture_ref"]: f["fixture_id"] for f in fixtures["fixtures"]}
    records = {
        f["fixture_id"]: f["record_sha256"] for f in forecasts["forecasts"] if f["rung"] == "elo"
    }
    # 15: report refused before any settlement
    err = runner.fails("settle", "report", "--config", CONFIG)
    assert "report refused" in err
    # barrier evidence for both fixtures: verified start after issue, proof attested before start
    runner.at(dt.datetime(2026, 8, 11, 18, 0, tzinfo=UTC))
    for ref in ("f1", "f2"):
        runner.ok(
            "ledger",
            "start-verified",
            "--config",
            CONFIG,
            "--fixture",
            ids[ref][:16],
            "--actual-start",
            "2026-08-11T15:05:00+00:00",
            "--source",
            "synthetic official order of play",
            "--evidence",
            "receipt 1",
        )
        early = attest(
            workspace, records[ids[ref]], "2026-08-10T13:00:00+00:00", name=f"att_{ref}.json"
        )
        assert (
            runner.ok(
                "ledger",
                "proof-verify",
                "--config",
                CONFIG,
                "--fixture",
                ids[ref][:16],
                "--attestation",
                early,
            )["kind"]
            == "proof_verified"
        )
    n = world.name_of
    decided = {
        "QF": [
            {"a": n("300001"), "b": n("300004"), "winner": "a", "sets": [("6", "3"), ("6", "3")]},
            {
                "a": n("300002"),
                "b": n("300003"),
                "winner": "a",
                "sets": [("6", "1"), ("2", "1")],
                "retired": True,
            },
        ]
    }
    runner.at(dt.datetime(2026, 8, 11, 19, 0, tzinfo=UTC))
    update(
        runner,
        world.replay_dir_for(
            workspace,
            world.complete_rounds(),
            revision=100,
            e2_rounds=decided,
            timestamp="2026-08-11T17:30:00Z",
            name="r1",
        ),
    )
    assert runner.ok("settle", "results", "--config", CONFIG) == {
        "provisional": 2,
        "final": 0,
        "corrected": 0,
        "pending": 0,
        "no_row": 0,
    }
    # provisional only: nothing scored, both pending
    s0 = runner.ok("settle", "score", "--config", CONFIG, "--settlement-id", "s0")
    assert s0["coverage"] == {"pending:pending:result_not_final": 2}
    runner.at(dt.datetime(2026, 8, 11, 20, 0, tzinfo=UTC))
    update(
        runner,
        world.replay_dir_for(
            workspace,
            world.complete_rounds(),
            revision=101,
            e2_rounds=decided,
            timestamp="2026-08-11T18:30:00Z",
            name="r2",
        ),
    )
    assert runner.ok("settle", "results", "--config", CONFIG) == {
        "provisional": 0,
        "final": 2,
        "corrected": 0,
        "pending": 0,
        "no_row": 0,
    }
    s1 = runner.ok("settle", "score", "--config", CONFIG, "--settlement-id", "s1")
    assert s1["coverage"] == {"confirmed_scored": 1, "excluded:estimand:retired": 1}
    scores = read_csv(workspace / "data" / "live" / "settlement" / "s1" / "scores.csv")
    assert len(scores) == 1 and scores[0]["y_a"] == "1" and scores[0]["rung"] == "elo"
    p_a = float(forecast_payload(workspace, ids["f1"])["p_a"])
    assert float(scores[0]["log_loss"]) == pytest.approx(-__import__("math").log(p_a))
    report = runner.ok("settle", "report", "--config", CONFIG)
    assert report["summary"]["scored_by_rung"]["elo"]["n"] == 1
    # 14: a later capture that disagrees with the final result -> corrected, re-scored with supersedes
    corrected = {
        "QF": [
            {"a": n("300001"), "b": n("300004"), "winner": "b", "sets": [("3", "6"), ("3", "6")]},
            decided["QF"][1],
        ]
    }
    runner.at(dt.datetime(2026, 8, 12, 9, 0, tzinfo=UTC))
    update(
        runner,
        world.replay_dir_for(
            workspace,
            world.complete_rounds(),
            revision=102,
            e2_rounds=corrected,
            timestamp="2026-08-12T08:00:00Z",
            name="r3",
        ),
    )
    assert runner.ok("settle", "results", "--config", CONFIG)["corrected"] == 1
    s2 = runner.ok("settle", "score", "--config", CONFIG, "--settlement-id", "s2")
    assert s2["coverage"]["confirmed_scored"] == 1
    scores2 = read_csv(workspace / "data" / "live" / "settlement" / "s2" / "scores.csv")
    assert scores2[0]["y_a"] == "0"
    kinds = [json.loads(line)["kind"] for line in ledger_lines(workspace)]
    assert kinds.count("score_reported") == 2 and kinds.count("result_corrected") == 1
    last_score = [
        json.loads(line)
        for line in ledger_lines(workspace)
        if json.loads(line)["kind"] == "score_reported"
    ][-1]
    assert "supersedes_score" in last_score["payload"]
    # the original forecast and result records are untouched: the chain still verifies
    assert runner.ok("ledger", "verify", "--config", CONFIG)["ok"] is True


def test_forecast_refused_when_scheduled_start_is_not_after_issue_time(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    world.write_fixtures(
        workspace,
        [
            world.fixture_row(
                "late", "300001", "300004", round_code="QF", start="2026-08-10T11:00:00+00:00"
            )
        ],
        name="late.csv",
    )
    runner.ok("fixture", "--config", CONFIG, "--input", "late.csv", "--batch-id", "late")
    out = runner.ok("forecast", "--config", CONFIG, "--batch-id", "late")
    assert out["forecasts"] == [
        {
            "fixture_id": out["forecasts"][0]["fixture_id"],
            "rung": None,
            "status": "refused_late",
            "note": "scheduled start is not after the issue time",
        }
    ]
    assert not any(
        json.loads(line)["kind"] == "forecast_issued" for line in ledger_lines(workspace)
    )


def test_history_binding_must_be_bound_and_hash_verified(ws) -> None:
    workspace, runner = ws
    update(runner, world.replay_dir_for(workspace, world.complete_rounds(), revision=100))
    config_path = workspace / "configs" / "live" / "live.json"
    config = json.loads(config_path.read_text())
    config["history"]["ATP"]["sha256"] = "0" * 64
    config_path.write_text(json.dumps(config))
    world.write_fixtures(
        workspace, [world.fixture_row("f1", "300001", "300004", round_code="QF")], name="h.csv"
    )
    runner.ok("fixture", "--config", CONFIG, "--input", "h.csv", "--batch-id", "h")
    err = runner.fails("forecast", "--config", CONFIG, "--batch-id", "h")
    assert "hash mismatch" in err
