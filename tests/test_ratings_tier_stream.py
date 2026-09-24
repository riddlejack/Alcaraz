"""Ported from the archive's ``TIER01_models/test_tier01.py``: ``StreamVocabulary`` and
``SatelliteCircuitDating``, importing from the package.

The archive pinned the built stream's Spain 1 2006 record only when its own corrected
stream was present on disk; here the same counterexample is built end to end from a
synthetic ARCHIVE01 tarball, inventory and manifest inside a scratch workspace, so the
regression does not depend on the research archive.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tennislab.config import reset_workspace_cache
from tennislab.ratings import tier_stream

YEAR_PLAN = {
    "panel_end_year": 2020,
    "feature_end_year": 2020,
    "target_years": [2020],
    "calibration_years_back": 3,
    "history_floor_year": 2011,
    "training_window_years": 5,
}
COUNTS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")
GOOD = {
    "ace": 5,
    "df": 2,
    "svpt": 60,
    "1stIn": 36,
    "1stWon": 27,
    "2ndWon": 12,
    "SvGms": 10,
    "bpSaved": 3,
    "bpFaced": 5,
}
BAD_SECOND_SERVE = {**GOOD, "2ndWon": 25}  # 2ndWon > svpt - 1stIn, and with df too

SPAIN_BASE = "2006-M-SA-ESP-01A-2006"
SPAIN_LEGS = ("a", "b", "c", "d")
SPAIN_ANCHOR = dt.date(2006, 2, 27)
SPAIN_EXPECTED = dt.date(2006, 3, 27)


def count_row(winner: dict[str, int] | None, loser: dict[str, int] | None) -> dict[str, str]:
    row: dict[str, str] = {}
    for side, values in (("w", winner), ("l", loser)):
        for name in COUNTS:
            row[f"{side}_{name}"] = "" if values is None else str(values.get(name, ""))
    return row


# --------------------------------------------------------------- the vocabulary


def test_the_eight_identities_are_the_multi01_checks() -> None:
    assert tier_stream.count_violations(GOOD) == []
    assert sorted(tier_stream.count_violations(BAD_SECOND_SERVE)) == [
        "second_won_le_second_opportunities",
        "second_won_plus_df_le_second_opportunities",
    ]


def test_count_block_status_labels() -> None:
    assert tier_stream.count_block_status(count_row(GOOD, GOOD))[0] == "usable"
    assert tier_stream.count_block_status(count_row(None, None))[0] == "missing_all"
    assert tier_stream.count_block_status(count_row(GOOD, None))[0] == "missing_all"
    partial = count_row(GOOD, GOOD)
    partial["l_SvGms"] = ""
    assert tier_stream.count_block_status(partial)[0] == "missing_all"
    status, violations = tier_stream.count_block_status(count_row(GOOD, BAD_SECOND_SERVE))
    assert status == "quarantined_invalid"
    assert violations


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        ("6-3 6-4", "completed"),
        ("6-3 2-1 RET", "retired"),
        ("W/O", "walkover"),
        ("6-0 DEF", "default"),
        ("ABN", "abandoned"),
        ("", "unknown"),
    ],
)
def test_status_vocabulary(score: str, expected: str) -> None:
    assert tier_stream.classify_status(score)[0] == expected


def test_tier_split_is_the_audits_own() -> None:
    assert tier_stream.tier_of("atp_qual_chall", "C", "R32") == "challenger"
    assert tier_stream.tier_of("atp_qual_chall", "C", "Q1") == "qualifying"
    assert tier_stream.tier_of("atp_qual_chall", "G", "Q3") == "qualifying"
    assert tier_stream.tier_of("atp_qual_chall", "M", "Q2") == "qualifying"
    assert tier_stream.tier_of("atp_futures", "S", "F") == "futures"
    with pytest.raises(tier_stream.TierStreamError):
        tier_stream.tier_of("atp_qual_chall", "A", "R32")


def stream_config(**parameters: object) -> dict:
    return {
        "year_plan": dict(YEAR_PLAN),
        "tier_stream": {
            "archive": {"path": "data/raw/ARCHIVE01/snapshot/x.tar.gz", "tar_root": "x"},
            "inventory": {"path": "data/raw/ARCHIVE01/snapshot_file_inventory.csv"},
            "archive_manifest": {"path": "data/manifests/ARCHIVE01.json"},
            "last_year": 2020,
            "parameters": {**tier_stream.DEFAULT_PARAMETERS, **parameters},
            "output_dir": "work/TIER01/never_written",
        },
    }


def test_an_undeclared_reported_date_offset_is_refused() -> None:
    with pytest.raises(tier_stream.TierStreamError):
        tier_stream.build(stream_config(reported_date_offset_days=3))


def test_circuit_dating_needs_the_seven_day_leg() -> None:
    # The sensitivity offset of 0 has no circuit-end meaning; the combination was never run.
    with pytest.raises(tier_stream.TierStreamError):
        tier_stream.build(stream_config(reported_date_offset_days=0, satellite_circuit_dating=True))


def test_a_span_reaching_a_reserved_year_is_refused() -> None:
    config = stream_config()
    config["year_plan"]["panel_end_year"] = 2025
    config["year_plan"]["feature_end_year"] = 2025
    config["tier_stream"]["last_year"] = 2025
    with pytest.raises(tier_stream.TierStreamError):
        tier_stream.build(config)


# --------------------------------------------------- satellite-circuit dating


def test_the_leg_key_reads_the_component_edition_shape() -> None:
    for leg in SPAIN_LEGS:
        assert tier_stream.circuit_leg_key(f"{SPAIN_BASE}{leg}") == (SPAIN_BASE, leg)
    # An ordinary edition has no leg letter and is never redated.
    assert tier_stream.circuit_leg_key("2006-M-FU-ESP-01A-2006") is None
    assert tier_stream.circuit_leg_key("2015-560") is None


def test_every_spain_1_2006_leg_is_dated_at_the_circuits_last_completion() -> None:
    """Astra finding 3: anchor + 7 (2006-03-06) released three later weeks of results."""
    anchors = {f"{SPAIN_BASE}{leg}": SPAIN_ANCHOR for leg in SPAIN_LEGS}
    dates = tier_stream.circuit_reported_dates({SPAIN_BASE: set(SPAIN_LEGS)}, anchors)
    assert sorted(dates) == sorted(anchors)
    assert set(dates.values()) == {SPAIN_EXPECTED}
    assert SPAIN_EXPECTED != SPAIN_ANCHOR + dt.timedelta(days=7)
    # A target two days before the corrected date cannot see any leg of the circuit.
    assert SPAIN_ANCHOR + dt.timedelta(days=7) < SPAIN_EXPECTED - dt.timedelta(days=2)


def test_a_single_edition_event_keeps_anchor_plus_seven() -> None:
    base = "2006-M-SA-XXX-01A-2006"
    dates = tier_stream.circuit_reported_dates({base: {"a"}}, {f"{base}a": SPAIN_ANCHOR})
    assert dates[f"{base}a"] == SPAIN_ANCHOR + dt.timedelta(days=7)


def test_a_two_leg_circuit_takes_two_weeks() -> None:
    base = "2006-M-SA-YYY-01A-2006"
    anchors = {f"{base}a": SPAIN_ANCHOR, f"{base}b": SPAIN_ANCHOR}
    dates = tier_stream.circuit_reported_dates({base: {"a", "b"}}, anchors)
    assert set(dates.values()) == {SPAIN_ANCHOR + dt.timedelta(days=14)}


# ----------------------------------------------------- the build, end to end


def raw_row(
    tourney_id: str,
    anchor: str,
    winner: int,
    loser: int,
    *,
    level: str = "C",
    round_name: str = "R32",
    score: str = "6-3 6-4",
    counts: dict[str, int] | None = None,
) -> dict[str, str]:
    row = dict.fromkeys(tier_stream.RAW_FIELDS, "")
    row.update(
        {
            "tourney_id": tourney_id,
            "tourney_name": "T",
            "surface": "Hard",
            "tourney_level": level,
            "tourney_date": anchor,
            "winner_id": str(winner),
            "loser_id": str(loser),
            "score": score,
            "best_of": "3",
            "round": round_name,
        }
    )
    row.update(count_row(counts, counts))
    return row


def member_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(tier_stream.RAW_FIELDS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    yield tmp_path
    reset_workspace_cache()


def build_fixture(root: Path) -> dict:
    """A one-season ARCHIVE01 look-alike: the Spain 1 2006 circuit plus a Challenger."""
    match_num = iter(range(1, 100))
    qual_chall = [
        raw_row("2006-1234", "20060227", 101, 102, round_name="F", counts=GOOD),
        raw_row("2006-1234", "20060227", 103, 104, round_name="Q1"),
        raw_row("2006-1234", "20060227", 105, 106, score="W/O"),  # excluded: walkover
        raw_row("2006-1234", "20060227", 107, 107),  # excluded: winner equals loser
    ]
    futures = [
        raw_row(f"{SPAIN_BASE}{leg}", "20060227", 200 + index, 300 + index, level="S")
        for index, leg in enumerate(SPAIN_LEGS)
    ]
    for row in (*qual_chall, *futures):
        row["match_num"] = str(next(match_num))
    members = {
        "atp/atp_matches_qual_chall_2006.csv": member_bytes(qual_chall),
        "atp/atp_matches_futures_2006.csv": member_bytes(futures),
    }
    snapshot = root / "data/raw/ARCHIVE01/snapshot"
    snapshot.mkdir(parents=True)
    archive = snapshot / "x.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(f"x/{name}")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    inventory = root / "data/raw/ARCHIVE01/snapshot_file_inventory.csv"
    with inventory.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "sha256"])
        writer.writeheader()
        for name, payload in members.items():
            writer.writerow({"path": name, "sha256": hashlib.sha256(payload).hexdigest()})
    manifest = root / "data/manifests/ARCHIVE01.json"
    manifest.parent.mkdir(parents=True)
    pinned = {
        "data/raw/ARCHIVE01/snapshot/x.tar.gz": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "data/raw/ARCHIVE01/snapshot_file_inventory.csv": hashlib.sha256(
            inventory.read_bytes()
        ).hexdigest(),
    }
    manifest.write_text(
        json.dumps(
            {"files": [{"path": path, "sha256": digest} for path, digest in pinned.items()]}
        ),
        encoding="utf-8",
    )
    return {
        "year_plan": {
            "panel_end_year": 2006,
            "feature_end_year": 2006,
            "target_years": [2006],
            "calibration_years_back": 1,
            "history_floor_year": 2005,
            "training_window_years": 1,
        },
        "tier_stream": {
            "archive": {
                "path": "data/raw/ARCHIVE01/snapshot/x.tar.gz",
                "sha256": pinned["data/raw/ARCHIVE01/snapshot/x.tar.gz"],
                "tar_root": "x",
            },
            "inventory": {"path": "data/raw/ARCHIVE01/snapshot_file_inventory.csv"},
            "archive_manifest": {"path": "data/manifests/ARCHIVE01.json"},
            "last_year": 2006,
            "parameters": {
                "first_year": 2006,
                "elo_start_year": 2006,
                "experience_start_year": 2006,
                "serve_counts_start_year": 2006,
                "reported_date_offset_days": 7,
                "satellite_circuit_dating": True,
            },
            "output_dir": "work/TIER01/test/tier_stream",
        },
    }


def test_the_built_stream_records_the_spain_1_2006_counterexample(workspace: Path) -> None:
    config = build_fixture(workspace)
    summary = tier_stream.build(config)
    output = workspace / "work/TIER01/test/tier_stream"

    with (output / "tier_circuit_dating.csv").open(newline="", encoding="utf-8") as handle:
        circuits = {row["circuit_base"]: row for row in csv.DictReader(handle)}
    assert list(circuits) == [SPAIN_BASE]
    record = circuits[SPAIN_BASE]
    assert int(record["legs"]) == 4
    assert record["anchor_date"] == SPAIN_ANCHOR.isoformat()
    assert record["reported_date"] == SPAIN_EXPECTED.isoformat()
    assert record["component_editions"] == ";".join(f"{SPAIN_BASE}{leg}" for leg in SPAIN_LEGS)
    assert int(record["retained_rows"]) == 4

    with gzip.open(output / "tier_results.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        results = list(csv.DictReader(handle))
    assert tuple(results[0]) == tier_stream.RESULT_FIELDS
    spain = [row for row in results if row["match_id"].split(":")[2].startswith(SPAIN_BASE)]
    assert len(spain) == 4
    assert {row["date"] for row in spain} == {SPAIN_EXPECTED.isoformat()}
    assert {row["anchor_date"] for row in spain} == {SPAIN_ANCHOR.isoformat()}
    assert {row["tier"] for row in spain} == {"futures"}
    # The single-edition Challenger keeps anchor + 7 and its final is a title.
    challenger = {
        row["round"]: row for row in results if row["match_id"].startswith("tier:atp_qual_chall")
    }
    assert set(challenger) == {"F", "Q1"}
    assert challenger["F"]["date"] == "2006-03-06"
    assert challenger["F"]["tier"] == "challenger" and challenger["F"]["is_final"] == "1"
    assert challenger["Q1"]["tier"] == "qualifying" and challenger["Q1"]["is_final"] == "0"
    assert "winner_id" in results[0] and "a_won" not in results[0]

    with gzip.open(
        output / "tier_source_rows.csv.gz", "rt", encoding="utf-8", newline=""
    ) as handle:
        feed = list(csv.DictReader(handle))
    assert tuple(feed[0]) == tier_stream.SOURCE_ROW_FIELDS
    assert [row["count_block_status"] for row in feed] == ["usable", "missing_all"]
    assert feed[0]["a_svpt"] == "60" and feed[1]["a_svpt"] == ""

    assert summary["excluded"] == {"status_walkover": 1, "winner_equals_loser": 1}
    assert summary["retained_by_tier"] == {"challenger": 1, "qualifying": 1, "futures": 4}
    assert summary["satellite_circuit_dating"]["rows_redated"] == 4
    assert summary["code"]["module"] == "tennislab.ratings.tier_stream"
    assert summary["inputs"]["archive"]["path"] == "data/raw/ARCHIVE01/snapshot/x.tar.gz"
    with pytest.raises(tier_stream.TierStreamError):
        tier_stream.build(config)  # the output directory is no longer empty


def test_a_tampered_inventory_is_refused_by_the_manifest(workspace: Path) -> None:
    config = build_fixture(workspace)
    inventory = workspace / "data/raw/ARCHIVE01/snapshot_file_inventory.csv"
    lines = inventory.read_text(encoding="utf-8").splitlines()
    inventory.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    with pytest.raises(tier_stream.TierStreamError, match="manifest does not pin"):
        tier_stream.build(config)


# ------------------------------------------------------------ the reserved window

# The two messages a reserved span has always been refused with; they must not drift.
REFUSED_BUILD = "refusing to read a reserved year: last_year 2025 >= 2025"
REFUSED_DRY_RUN = "configured span reaches a reserved year"
FUTURES_LIMIT_THROUGH_2024 = (
    "Futures carries no serve count in any year read here (the audit: 0 of "
    "498,555 rows, 1991-2024), so the family can only ever be outcome history."
)


def write_two_season_archive(root: Path) -> dict:
    """An ARCHIVE01 look-alike holding 2024 and 2025; returns the custody entries.

    2025 Futures carry serve counts (2024's carry none, as in the audit): one complete
    block that passes the count identities and one that fails them.
    """
    match_num = iter(range(1, 100))
    members_rows = {
        "atp/atp_matches_qual_chall_2024.csv": [
            raw_row("2024-1234", "20240304", 101, 102, round_name="F", counts=GOOD),
            raw_row("2024-1234", "20240304", 103, 104, round_name="Q1"),
        ],
        "atp/atp_matches_futures_2024.csv": [
            raw_row("2024-M-ITF-FRA-01A-2024", "20240311", 201, 202, level="S"),
        ],
        "atp/atp_matches_qual_chall_2025.csv": [
            raw_row("2025-1234", "20250303", 101, 103, counts=GOOD),
        ],
        "atp/atp_matches_futures_2025.csv": [
            raw_row("2025-M-ITF-FRA-01A-2025", "20250310", 203, 204, level="S", counts=GOOD),
            raw_row(
                "2025-M-ITF-FRA-01A-2025",
                "20250310",
                205,
                206,
                level="S",
                counts=BAD_SECOND_SERVE,
            ),
        ],
    }
    members: dict[str, bytes] = {}
    for name, rows in members_rows.items():
        for row in rows:
            row["match_num"] = str(next(match_num))
        members[name] = member_bytes(rows)
    snapshot = root / "data/raw/ARCHIVE01/snapshot"
    snapshot.mkdir(parents=True)
    archive = snapshot / "x.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(f"x/{name}")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    inventory = root / "data/raw/ARCHIVE01/snapshot_file_inventory.csv"
    with inventory.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "sha256"])
        writer.writeheader()
        for name, payload in members.items():
            writer.writerow({"path": name, "sha256": hashlib.sha256(payload).hexdigest()})
    manifest = root / "data/manifests/ARCHIVE01.json"
    manifest.parent.mkdir(parents=True)
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    pinned = {
        "data/raw/ARCHIVE01/snapshot/x.tar.gz": archive_sha,
        "data/raw/ARCHIVE01/snapshot_file_inventory.csv": hashlib.sha256(
            inventory.read_bytes()
        ).hexdigest(),
    }
    manifest.write_text(
        json.dumps({"files": [{"path": path, "sha256": sha} for path, sha in pinned.items()]}),
        encoding="utf-8",
    )
    return {
        "archive": {
            "path": "data/raw/ARCHIVE01/snapshot/x.tar.gz",
            "sha256": archive_sha,
            "tar_root": "x",
        },
        "inventory": {"path": "data/raw/ARCHIVE01/snapshot_file_inventory.csv"},
        "archive_manifest": {"path": "data/manifests/ARCHIVE01.json"},
    }


def span_config(custody: dict, last_year: int, output: str, **section: object) -> dict:
    """A 2024-first span ending at ``last_year``, with the plan ending there too."""
    return {
        "year_plan": {
            "panel_end_year": last_year,
            "feature_end_year": last_year,
            "target_years": [last_year],
            "calibration_years_back": 1,
            "history_floor_year": last_year - 1,
            "training_window_years": 1,
        },
        "tier_stream": {
            **custody,
            "last_year": last_year,
            "parameters": {
                "first_year": 2024,
                "elo_start_year": 2024,
                "experience_start_year": 2024,
                "serve_counts_start_year": 2024,
                "reported_date_offset_days": 7,
                "satellite_circuit_dating": True,
            },
            "output_dir": output,
            **section,
        },
    }


def read_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize(
    "acknowledgement",
    [{}, {"reserved_release_acknowledged": False}, {"reserved_release_acknowledged": "true"}],
)
def test_a_reserved_span_is_refused_with_the_same_messages_unless_acknowledged(
    workspace: Path, acknowledgement: dict
) -> None:
    custody = write_two_season_archive(workspace)
    config = span_config(custody, 2025, "work/TIER01/test/refused", **acknowledgement)
    with pytest.raises(tier_stream.TierStreamError) as refused:
        tier_stream.build(config)
    assert str(refused.value) == REFUSED_BUILD
    with pytest.raises(tier_stream.TierStreamError) as refused_dry:
        tier_stream.dry_run(config)
    assert str(refused_dry.value) == REFUSED_DRY_RUN
    assert not (workspace / "work/TIER01/test/refused").exists()


def test_an_acknowledged_reserved_span_is_admitted_and_says_what_it_opened(
    workspace: Path,
) -> None:
    custody = write_two_season_archive(workspace)
    config = span_config(
        custody, 2025, "work/TIER01/test/reserved", reserved_release_acknowledged=True
    )
    assert tier_stream.dry_run(config)["status"] == "dry_run_ok"
    # The acknowledgement does not relax last_year == panel_end_year.
    mismatched = span_config(
        custody, 2025, "work/TIER01/test/never", reserved_release_acknowledged=True
    )
    mismatched["year_plan"]["panel_end_year"] = 2026
    with pytest.raises(tier_stream.TierStreamError, match="must equal the plan's panel_end_year"):
        tier_stream.build(mismatched)

    summary = tier_stream.build(config)
    assert summary["span"] == {
        "first_year": 2024,
        "last_year": 2025,
        "reserved_years_opened": [2025],
        "reserved_years_never_opened": [2026],
        "reserved_release_acknowledged": True,
    }
    assert sorted(summary["inputs"]["members"]) == [
        "atp/atp_matches_futures_2024.csv",
        "atp/atp_matches_futures_2025.csv",
        "atp/atp_matches_qual_chall_2024.csv",
        "atp/atp_matches_qual_chall_2025.csv",
    ]
    futures_limit = summary["limits"][1]
    assert futures_limit != FUTURES_LIMIT_THROUGH_2024
    assert "reserved years opened here (2025)" in futures_limit
    assert "count-identity screen" in futures_limit
    # What the sentence claims: a 2025 Futures block that fails an identity drops the
    # row from the outcome stream; one that passes stays as history; neither is fed.
    assert summary["excluded"] == {"count_identity_failure": 1}
    assert [(row["family"], row["year"]) for row in summary["count_identity_failure_rows"]] == [
        ("atp_futures", "2025")
    ]
    output = workspace / "work/TIER01/test/reserved"
    results = read_gz(output / "tier_results.csv.gz")
    assert [row["season"] for row in results if row["tier"] == "futures"] == ["2024", "2025"]
    feed = read_gz(output / "tier_source_rows.csv.gz")
    assert [row["match_date"][:4] for row in feed] == ["2024", "2024", "2025"]
    assert all(row["tourney_id"].split("-")[1] == "1234" for row in feed)


@pytest.mark.parametrize("acknowledgement", [{}, {"reserved_release_acknowledged": True}])
def test_a_span_ending_in_2024_is_unchanged_by_the_reserved_window_rule(
    workspace: Path, acknowledgement: dict
) -> None:
    custody = write_two_season_archive(workspace)
    summary = tier_stream.build(
        span_config(custody, 2024, "work/TIER01/test/through_2024", **acknowledgement)
    )
    # The span and the limit sentence are exactly what every pre-window build wrote.
    assert summary["span"] == {
        "first_year": 2024,
        "last_year": 2024,
        "reserved_years_never_opened": [2025, 2026],
    }
    assert summary["limits"][1] == FUTURES_LIMIT_THROUGH_2024
    assert sorted(summary["inputs"]["members"]) == [
        "atp/atp_matches_futures_2024.csv",
        "atp/atp_matches_qual_chall_2024.csv",
    ]
    # Opening 2025 leaves every 2024 row as it was.
    tier_stream.build(
        span_config(
            custody, 2025, "work/TIER01/test/through_2025", reserved_release_acknowledged=True
        )
    )
    for name in ("tier_results.csv.gz", "tier_source_rows.csv.gz"):
        through_2024 = read_gz(workspace / "work/TIER01/test/through_2024" / name)
        through_2025 = read_gz(workspace / "work/TIER01/test/through_2025" / name)
        date_field = "date" if name == "tier_results.csv.gz" else "match_date"
        assert through_2024 == [row for row in through_2025 if row[date_field] < "2025-01-01"]
        assert len(through_2025) > len(through_2024)
