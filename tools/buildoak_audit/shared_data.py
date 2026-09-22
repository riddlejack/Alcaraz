"""Prepare and run the frozen WTA2024 shared-data BuildOak diagnostic.

``prepare`` constructs a native-shaped carrier from the accepted corrected WTA01
panel.  It keeps only the 41,316 primary observations in model state, preserves
literal source-null partial/missing blocks, masks the 105 quarantined-invalid
blocks, and binds the exact incumbent 2024 HGB-full training keys and accepted 2,404
targets.  ``project`` runs only the pinned BuildOak feature worker.  ``forecast``
is a separate, fail-closed fit step and requires an owner-frozen authorization;
it is intentionally never invoked by preparation or projection.
"""

from __future__ import annotations

import argparse
import base64
import collections
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import re
import selectors
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

IMAGE = "sha256:2cafed7f4ec6c964602c61b9802dfa59a8e2fd8e7d62ad5cbdaf74f47d820fa7"
FEATURE_STATUS = "AUTHORIZED_SHARED_WTA_BUILDOAK_FEATURES"
FEATURE_CANDIDATE_STATUS = "REQUIRES_EQUIVALENCE_SHARED_WTA_BUILDOAK_FEATURES"
FORECAST_STATUS = "AUTHORIZED_SHARED_WTA_BUILDOAK_FORECAST"
EQUIVALENCE_STATUS = "AUTHORIZED_SHARED_WTA_INCUMBENT_EQUIVALENCE"
FIT_CUTOFF = "2023-12-30"
EXPECTED_PANEL_ROWS = 42_485
EXPECTED_PRIMARY_ROWS = 41_316
EXPECTED_FIT_ROWS = 10_496
EXPECTED_TARGET_ROWS = 2_404
EXPECTED_TRAINING_KEY_HASH = "392e524302e44291bdd66d74a30a1ab927db33104e69d71236649002e1d321a1"
EXPECTED_TARGET_KEY_HASH = "d8ea95686b31626998afd96a69eb723b159925851417cd22bb22192b4477eb01"
COUNT_FIELDS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")
CORE_COUNT_FIELDS = tuple(field for field in COUNT_FIELDS if field != "SvGms")
ROUND_ORDER = {
    "RR": 0,
    "BR": 0,
    "ER": 0,
    "R128": 1,
    "R64": 2,
    "R32": 3,
    "R16": 4,
    "R4": 5,
    "QF": 6,
    "SF": 7,
    "F": 8,
}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FIXTURE_PLAYER_FIELDS = (
    "id",
    "name",
    "age",
    "ht",
    "seed",
    "rank",
    "rank_points",
    "entry",
    "hand",
    "ioc",
)
FIXTURE_CONTEXT = (
    "tourney_id",
    "match_num",
    "match_date",
    "tourney_name",
    "tourney_level",
    "surface",
    "round",
    "draw_size",
    "best_of",
)


def digest(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False, sort_keys=True) + "\n")


def key_hash(keys: list[tuple[str, str]]) -> str:
    payload = "".join(f"{season},{match_id}\n" for season, match_id in keys)
    return hashlib.sha256(payload.encode()).hexdigest()


def read_unique(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    result = {row["match_id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"duplicate match_id in {path}")
    return result


def parse_bool(value: str, field: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"invalid {field}: {value!r}")


def side_value(row: dict[str, str], side: str, field: str) -> str:
    aliases = {
        "id": "source_id",
        "name": "source_name",
        "age": "age_years",
        "ht": "height_cm",
    }
    return row.get(f"{side}_{aliases.get(field, field)}", "")


def native_row(row: dict[str, str]) -> dict[str, object]:
    a_won = parse_bool(row["a_won"], "a_won")
    winner, loser = ("a", "b") if a_won else ("b", "a")
    result: dict[str, object] = {
        "tourney_id": row["tourney_id"],
        "tourney_name": row["tourney_name"],
        "surface": row["surface"],
        "draw_size": row["draw_size"],
        "tourney_level": row["tourney_level"],
        "tourney_date": row["match_date"].replace("-", ""),
        "match_num": row["match_num"],
        "score": row["score"],
        "best_of": row["best_of"],
        "round": row["round"],
        "minutes": row["minutes"],
    }
    for role, side in (("winner", winner), ("loser", loser)):
        for field in (
            "id",
            "seed",
            "entry",
            "name",
            "hand",
            "ht",
            "ioc",
            "age",
            "rank",
            "rank_points",
        ):
            result[f"{role}_{field}"] = side_value(row, side, field)
        for field in COUNT_FIELDS:
            result[f"{'w' if role == 'winner' else 'l'}_{field}"] = (
                ""
                if row["count_block_status"] == "quarantined_invalid"
                else row.get(f"{side}_{field}", "")
            )
    native_key = f"{result['tourney_id']}/{int(result['match_num'])}"
    if native_key != row["match_id"]:
        raise ValueError(f"panel/native identity mismatch: {row['match_id']} != {native_key}")
    return result


def neutral_fixture(row: dict[str, object]) -> dict[str, object]:
    """Exact trusted projection copied from the bound adapter bench_schema.py."""
    first = "winner" if int(row["winner_id"]) < int(row["loser_id"]) else "loser"
    second = "loser" if first == "winner" else "winner"
    result = {key: row[key] for key in FIXTURE_CONTEXT}
    if row.get("_transport_id"):
        result["_transport_id"] = str(row["_transport_id"])
    for destination, source in (("winner", first), ("loser", second)):
        for field in FIXTURE_PLAYER_FIELDS:
            result[f"{destination}_{field}"] = row.get(f"{source}_{field}")
        result[f"{destination}_rank"] = None
        result[f"{destination}_rank_points"] = None
    result["score"] = ""
    return result


def prepare(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    panel = read_unique(args.panel.resolve())
    if len(panel) != EXPECTED_PANEL_ROWS:
        raise ValueError("changed panel row count")
    primary = {key: row for key, row in panel.items() if row["identity_tier"] == "primary"}
    if len(primary) != EXPECTED_PRIMARY_ROWS:
        raise ValueError("changed primary history population")
    if any(
        row["played"] != "true"
        or row["walkover"] != "false"
        or row["abandoned"] != "false"
        or row["status"] not in {"completed", "retired", "default"}
        for row in primary.values()
    ):
        raise ValueError("primary row fails incumbent parse_record eligibility")
    for row in primary.values():
        if row["count_block_status"] == "partial_missing" and any(
            row.get(f"{side}_{field}", "") for side in ("a", "b") for field in CORE_COUNT_FIELDS
        ):
            raise ValueError("partial_missing row unexpectedly contains a core count")

    with args.training_keys.resolve().open(newline="", encoding="utf-8") as stream:
        fit_rows = list(csv.DictReader(stream))
    fit_keys = [(row["season"], row["match_id"]) for row in fit_rows]
    if len(fit_keys) != EXPECTED_FIT_ROWS or key_hash(fit_keys) != EXPECTED_TRAINING_KEY_HASH:
        raise ValueError("changed selected-2024 HGB-full training membership")
    fit_ids = {match_id for _, match_id in fit_keys}
    if len(fit_ids) != len(fit_keys) or not fit_ids <= set(primary):
        raise ValueError("training membership is duplicate or outside primary panel")
    for season, match_id in fit_keys:
        row = primary[match_id]
        if (
            row["season"] != season
            or not 2019 <= int(season) <= 2023
            or row["match_date"] > FIT_CUTOFF
        ):
            raise ValueError(f"training chronology drift: {match_id}")

    targets = read_unique(args.target_membership.resolve())
    target_keys = [("2024", key) for key in sorted(targets)]
    if len(targets) != EXPECTED_TARGET_ROWS or key_hash(target_keys) != EXPECTED_TARGET_KEY_HASH:
        raise ValueError("changed accepted WTA2024 target membership")
    if not set(targets) <= set(primary) or fit_ids & set(targets):
        raise ValueError("target population outside primary panel or overlaps training")
    if any(primary[key]["season"] != "2024" for key in targets):
        raise ValueError("non-2024 target")

    labels = read_unique(args.incumbent_labels.resolve())
    for key in fit_ids | set(targets):
        if key not in labels or int(labels[key]["a_won"]) != int(
            parse_bool(primary[key]["a_won"], "a_won")
        ):
            raise ValueError(f"incumbent label/panel conflict: {key}")
    ambiguous_consumed = []
    consumed_feature_rows = 0
    with args.incumbent_features.resolve().open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["match_id"] not in fit_ids and row["match_id"] not in targets:
                continue
            consumed_feature_rows += 1
            if row["ranking_ambiguous_a"] == "1" or row["ranking_ambiguous_b"] == "1":
                ambiguous_consumed.append(row["match_id"])
    if consumed_feature_rows != EXPECTED_FIT_ROWS + EXPECTED_TARGET_ROWS or ambiguous_consumed:
        raise ValueError(
            "incumbent consumed membership has missing rows or ambiguous ranking input"
        )

    fit_manifest = json.loads(args.fit_manifest.resolve().read_text())
    fit_identity = fit_manifest["fit_identity"]
    if (
        fit_manifest["status"] != "complete"
        or fit_manifest["fit_identity_sha256"]
        != "09ee0852d56142cb1e820b036ae619692398bff92093cb9efe05c1a39fb06261"
        or fit_identity["training_keys_sha256"] != EXPECTED_TRAINING_KEY_HASH
        or fit_identity["training_rows"] != EXPECTED_FIT_ROWS
        or fit_identity["fit_cutoff"] != FIT_CUTOFF
    ):
        raise ValueError("incumbent final fit identity drift")
    selection = json.loads(args.selection_record.resolve().read_text())
    if (
        selection["selected_candidate_id"] != "hgb_leaf07_depth3"
        or selection["selection_cutoff_inclusive"] != FIT_CUTOFF
        or selection["outer_primary_membership_sha256"] != EXPECTED_TARGET_KEY_HASH
        or selection["outer_primary_rows"] != EXPECTED_TARGET_ROWS
        or selection["selected_prediction_sha256"] != digest(args.selected_forecast)
    ):
        raise ValueError("incumbent selection identity drift")
    selected = read_unique(args.selected_forecast.resolve())
    incumbent = {
        row["match_id"]: row
        for row in csv.DictReader(args.incumbent_predictions.resolve().open())
        if row["tour"] == "WTA" and row["year"] == "2024"
    }
    if set(incumbent) != set(targets):
        raise ValueError("incumbent forecast target membership drift")
    if any(
        selected[key]["p_a_wins"] != incumbent[key]["raw_incumbent"]
        or incumbent[key]["raw_incumbent"] != incumbent[key]["calibrated_incumbent"]
        for key in incumbent
    ):
        raise ValueError("incumbent forecast/calibration identity drift")
    sidecar = json.loads(args.sidecar_manifest.resolve().read_text())
    if (
        sidecar["status"] != "no_fit_no_score"
        or sidecar["inputs"]["bio_players"]["sha256"] != digest(args.players)
        or sidecar["inputs"]["sr02_panel"]["sha256"] != digest(args.panel)
        or sidecar["inputs"]["base_features"]["sha256"] != digest(args.incumbent_features)
    ):
        raise ValueError("incumbent sidecar ancestry drift")

    native_path = output / "common_primary_native.csv"
    native_rows: dict[str, dict[str, object]] = {}
    with native_path.open("w", newline="", encoding="utf-8") as stream:
        writer = None
        for key, row in primary.items():
            converted = native_row(row)
            native_rows[key] = converted
            if writer is None:
                writer = csv.DictWriter(stream, fieldnames=list(converted))
                writer.writeheader()
            writer.writerow(converted)

    plan = []
    with native_path.open(newline="", encoding="utf-8") as stream:
        for source_line, carrier in enumerate(csv.DictReader(stream), start=2):
            key = f"{carrier['tourney_id']}/{int(carrier['match_num'])}"
            row = primary[key]
            target_date = row["match_date"]
            cutoff = (dt.date.fromisoformat(target_date) - dt.timedelta(days=2)).isoformat()
            plan.append(
                {
                    "match_id": key,
                    "tour": "wta",
                    "event_id": row["tourney_id"],
                    "event_name": row["tourney_name"],
                    "round": row["round"],
                    "level": row["tourney_level"],
                    "surface": row["surface"],
                    "source_file": native_path.name,
                    "source_line": source_line,
                    "target_date_proxy": target_date,
                    "available_date_proxy": target_date,
                    "eligible_through_date": cutoff,
                    "release_basis": "accepted_reported_date_D_minus_2_target_cutoff",
                    "fit_target": key in fit_ids,
                    "evaluation_target": key in targets,
                }
            )
    plan_path = output / "date_hierarchy_plan.json"
    save(plan_path, sorted(plan, key=lambda row: row["match_id"]))
    (output / "fit_membership.txt").write_text("\n".join(sorted(fit_ids)) + "\n")
    (output / "target_membership.txt").write_text("\n".join(sorted(targets)) + "\n")

    ranking_path = output / "common_rankings.csv"
    ranking_all_path = output / "common_rankings_normalized_all.csv.gz"
    incumbent_ranking_path = output / "common_rankings_incumbent_qualified.csv.gz"
    incumbent_index_path = output / "common_rankings_incumbent_edition_index.json"
    ranking_db = output / "ranking_sort.sqlite"
    connection = sqlite3.connect(ranking_db)
    connection.execute(
        "CREATE TABLE ranking(day INTEGER, player INTEGER, rank INTEGER, points INTEGER, "
        "source_member TEXT, source_line INTEGER, sequence INTEGER PRIMARY KEY)"
    )
    ranking_source_rows = 0
    with gzip.open(args.rankings.resolve(), "rt", newline="", encoding="utf-8") as source:
        batch = []
        for row in csv.DictReader(source):
            date = row["effective_date"]
            dt.date.fromisoformat(date)
            try:
                points = float(row["ranking_points"])
            except (TypeError, ValueError) as error:
                _ = error
                points = None
            batch.append(
                (
                    int(date.replace("-", "")),
                    int(row["player_id"]),
                    int(row["rank"]),
                    None if points is None else int(points),
                    row["source_member"],
                    int(row["source_physical_line"]),
                    ranking_source_rows,
                )
            )
            ranking_source_rows += 1
            if len(batch) == 10_000:
                connection.executemany("INSERT INTO ranking VALUES (?,?,?,?,?,?,?)", batch)
                batch = []
        connection.executemany("INSERT INTO ranking VALUES (?,?,?,?,?,?,?)", batch)
    connection.commit()
    connection.execute("CREATE INDEX ranking_key ON ranking(day,player)")
    connection.execute(
        "CREATE TABLE conflicting AS SELECT day,player FROM ranking GROUP BY day,player "
        "HAVING COUNT(DISTINCT printf('%.17g',rank)||'|'||COALESCE(printf('%.17g',points),'NULL')) > 1"
    )
    connection.execute("CREATE UNIQUE INDEX conflicting_key ON conflicting(day,player)")
    duplicate_groups = connection.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM ranking GROUP BY day,player HAVING COUNT(*)>1)"
    ).fetchone()[0]
    conflicting_groups = connection.execute("SELECT COUNT(*) FROM conflicting").fetchone()[0]
    exact_duplicate_groups = duplicate_groups - conflicting_groups
    if (ranking_source_rows, exact_duplicate_groups, conflicting_groups) != (1_543_106, 0, 190):
        raise ValueError("ranking duplicate qualification drift")
    normalized_hasher = hashlib.sha256()
    query = (
        "SELECT day,player,rank,points,source_member,source_line FROM ranking "
        "ORDER BY day,player,sequence"
    )
    with gzip.open(ranking_all_path, "wt", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(
            ["ranking_date", "player", "rank", "points", "source_member", "source_physical_line"]
        )
        for row in connection.execute(query):
            rendered = [*row]
            writer.writerow(rendered)
            normalized_hasher.update(
                (json.dumps(rendered, separators=(",", ":"), allow_nan=False) + "\n").encode()
            )
    with ranking_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(["ranking_date", "player", "rank", "points"])
        writer.writerows(
            connection.execute(
                "SELECT r.day,r.player,r.rank,r.points FROM ranking r "
                "LEFT JOIN conflicting c ON r.day=c.day AND r.player=c.player "
                "WHERE c.day IS NULL ORDER BY r.day,r.player,r.sequence"
            )
        )
    ranking_rows = connection.execute(
        "SELECT COUNT(*) FROM ranking r LEFT JOIN conflicting c "
        "ON r.day=c.day AND r.player=c.player WHERE c.day IS NULL"
    ).fetchone()[0]
    with gzip.open(incumbent_ranking_path, "wt", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(
            [
                "effective_date",
                "rank",
                "player_id",
                "ranking_points",
                "source_member",
                "source_physical_line",
            ]
        )
        for day, player, rank, points, source_member, source_line in connection.execute(
            "SELECT r.day,r.player,r.rank,r.points,r.source_member,r.source_line FROM ranking r "
            "LEFT JOIN conflicting c ON r.day=c.day AND r.player=c.player "
            "WHERE c.day IS NULL ORDER BY r.day,r.player,r.sequence"
        ):
            day_text = dt.datetime.strptime(str(day), "%Y%m%d").date().isoformat()
            writer.writerow(
                [
                    day_text,
                    rank,
                    player,
                    "" if points is None else points,
                    source_member,
                    source_line,
                ]
            )
    edition_rows = [
        {
            "effective_date": dt.datetime.strptime(str(day), "%Y%m%d").date().isoformat(),
            "row_count": count,
        }
        for day, count in connection.execute(
            "SELECT r.day,COUNT(*) FROM ranking r LEFT JOIN conflicting c "
            "ON r.day=c.day AND r.player=c.player WHERE c.day IS NULL GROUP BY r.day ORDER BY r.day"
        )
    ]
    known_players = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT r.player FROM ranking r LEFT JOIN conflicting c "
            "ON r.day=c.day AND r.player=c.player WHERE c.day IS NULL ORDER BY r.player"
        )
    ]
    connection.close()
    ranking_db.unlink()

    original_index = json.loads(args.incumbent_edition_index.resolve().read_text())
    if [row["effective_date"] for row in edition_rows] != [
        row["effective_date"] for row in original_index["editions"]
    ]:
        raise ValueError("qualified ranking carrier changes the incumbent global edition dates")
    if known_players != original_index["known_player_ids"]:
        raise ValueError("qualified ranking carrier changes the incumbent known-player universe")
    incumbent_index = {
        "editions": edition_rows,
        "known_player_ids": known_players,
        "schema_version": original_index["schema_version"],
        "source_bytes": incumbent_ranking_path.stat().st_size,
        "source_header": original_index["source_header"],
        "source_path": str(incumbent_ranking_path.resolve()),
        "source_rows": ranking_rows,
        "source_sha256": digest(incumbent_ranking_path),
    }
    save(incumbent_index_path, incumbent_index)

    incumbent_feature_config = json.loads(args.incumbent_feature_config.resolve().read_text())
    incumbent_feature_config["design"] = {
        "path": str(args.design.resolve()),
        "sha256": digest(args.design),
    }
    incumbent_feature_config["output_dir"] = str(args.equivalence_output.resolve())
    incumbent_feature_config["ranking_source"] = {
        "path": str(incumbent_ranking_path.resolve()),
        "sha256": digest(incumbent_ranking_path),
    }
    incumbent_feature_config["ranking_index"] = {
        "path": str(incumbent_index_path.resolve()),
        "sha256": digest(incumbent_index_path),
    }
    equivalence_config_path = output / "incumbent_equivalence_config.json"
    save(equivalence_config_path, incumbent_feature_config)

    ordered_fit = sorted(
        fit_ids,
        key=lambda key: (
            primary[key]["match_date"],
            primary[key]["tourney_name"],
            ROUND_ORDER.get(primary[key]["round"], 0),
            int(primary[key]["match_num"]),
            key,
        ),
    )
    ioc_counts: collections.Counter[str] = collections.Counter()
    for key in ordered_fit:
        row = primary[key]
        for side in ("a", "b"):
            value = row[f"{side}_ioc"].strip().upper()
            if value:
                ioc_counts[value] += 1
    vocabulary = [key for key, _ in ioc_counts.most_common(10)]
    save(
        output / "ioc_vocabulary.json",
        {
            "basis": "exact selected-2024 HGB-full training membership",
            "counts": ioc_counts,
            "vocabulary": vocabulary,
        },
    )

    tasks = sorted(
        {
            row["eligible_through_date"]
            for row in plan
            if row["fit_target"] or row["evaluation_target"]
        }
    )
    releases = sorted(plan, key=lambda row: (row["available_date_proxy"], row["match_id"]))
    cursor = 0
    latest_history_date = ""
    replay_batches = 0
    for cutoff in tasks:
        incoming = []
        while cursor < len(releases) and releases[cursor]["available_date_proxy"] <= cutoff:
            incoming.append(releases[cursor])
            cursor += 1
        if incoming and incoming[0]["target_date_proxy"] < latest_history_date:
            replay_batches += 1
        if incoming:
            latest_history_date = max(
                latest_history_date, max(row["target_date_proxy"] for row in incoming)
            )
    if replay_batches:
        raise ValueError("unexpected late-date replay in common panel schedule")

    count_status = collections.Counter(row["count_block_status"] for row in primary.values())
    source_bindings = {
        str(path.resolve()): digest(path)
        for path in (
            args.panel,
            args.rankings,
            args.players,
            args.training_keys,
            args.target_membership,
            args.incumbent_features,
            args.incumbent_labels,
            args.fit_manifest,
            args.selection_record,
            args.selected_forecast,
            args.incumbent_predictions,
            args.sidecar_manifest,
            args.incumbent_feature_config,
            args.design,
            args.incumbent_edition_index,
            args.ranking_lookup_module,
            args.feature_builder,
            args.pipeline_manifest,
            args.protocol,
            args.scorer,
            args.reconstruct,
            Path(__file__),
        )
    }
    output_bindings = {
        str(path.resolve()): digest(path) for path in output.iterdir() if path.is_file()
    }
    manifest = {
        "status": "prepared_no_fit_no_scores",
        "estimand": "controlled_shared_data_WTA2024",
        "panel_rows_retained_for_provenance": len(panel),
        "primary_state_history_rows": len(primary),
        "provisional_state_history_rows": 0,
        "fit_rows": len(fit_ids),
        "target_rows": len(targets),
        "fit_cutoff": FIT_CUTOFF,
        "training_membership_key_hash": key_hash(fit_keys),
        "target_membership_key_hash": key_hash(target_keys),
        "count_block_status_primary": dict(count_status),
        "count_contract": {
            "usable_rows_retained": count_status["usable"],
            "policy": "mask_quarantined_invalid_only_preserve_literal_other_values",
            "rows_all_nine_fields_masked_per_player": count_status["quarantined_invalid"],
            "masked_statuses": ["quarantined_invalid"],
            "partial_missing_rows_with_all_core_16_values_blank": count_status["partial_missing"],
            "qualification_note": "partial/missing rows are never rehydrated; SvGms may remain a literal source value and is a pipeline-specific transformation input",
        },
        "history_contract": "identity_tier=primary and incumbent parse_record eligibility; available on accepted reported date; target snapshot at D-2",
        "metadata_contract": {
            "common_available_sources": [str(args.panel.resolve()), str(args.players.resolve())],
            "buildoak_transform": "accepted corrected panel per-row age/height/hand/IOC; player master bound but not joined",
            "incumbent_transform": "base rows plus separately built player-master trait sidecar",
        },
        "ranking_contract": {
            "source": str(args.rankings.resolve()),
            "source_rows": ranking_source_rows,
            "normalized_all_rows": ranking_source_rows,
            "normalized_all_values_sha256": normalized_hasher.hexdigest(),
            "normalized_all_carrier": str(ranking_all_path),
            "exact_duplicate_groups": exact_duplicate_groups,
            "conflicting_duplicate_groups": conflicting_groups,
            "conflicting_rows_excluded_from_both_pipeline_rank_inputs": ranking_source_rows
            - ranking_rows,
            "qualified_rows": ranking_rows,
            "qualified_carrier": str(ranking_path),
            "incumbent_qualified_carrier": str(incumbent_ranking_path),
            "incumbent_qualified_carrier_sha256": digest(incumbent_ranking_path),
            "incumbent_qualified_edition_index": str(incumbent_index_path),
            "global_edition_dates_equal_incumbent": True,
            "known_player_universe_equal_incumbent": True,
            "incumbent_conflict_policy": "conflicting selected edition/player resolves to rank/points missing",
            "shared_qualification": "exclude every row in each conflicting date/player group before either pipeline transform",
        },
        "replay_schedule": {
            "cutoff_batches": len(tasks),
            "late_date_replay_batches": replay_batches,
        },
        "incumbent_reuse_receipt": {
            "consumed_feature_rows": consumed_feature_rows,
            "ranking_ambiguous_rows": len(ambiguous_consumed),
            "fit_identity_sha256": fit_manifest["fit_identity_sha256"],
            "fit_manifest_sha256": digest(args.fit_manifest),
            "training_keys_file_sha256": digest(args.training_keys),
            "selection_record_sha256": digest(args.selection_record),
            "selected_candidate_id": selection["selected_candidate_id"],
            "selected_slope": selection["selected_slope"],
            "selected_forecast_sha256": digest(args.selected_forecast),
            "incumbent_carrier_sha256": digest(args.incumbent_predictions),
            "forecast_and_carrier_identity_rows": len(incumbent),
            "calibration_identity": "raw_incumbent equals calibrated_incumbent on all 2404 targets",
            "sidecar_manifest_sha256": digest(args.sidecar_manifest),
        },
        "source_bindings": source_bindings,
        "output_bindings": output_bindings,
        "limits": [
            "exposed retrospective diagnostic",
            "common observations and supervised membership do not imply common feature columns or architecture",
            "reported dates are qualified proxies, not verified publication clocks",
            "no score, fit, or calibration was generated by preparation",
        ],
    }
    manifest_path = output / "preparation.json"
    save(manifest_path, manifest)

    runtime = args.runtime.resolve()
    controller = runtime / "empirical_controller.py"
    bench_schema = runtime / "adapter/bench_schema.py"
    feature_auth = {
        "status": FEATURE_CANDIDATE_STATUS,
        "tour": "wta",
        "attempt_id": args.attempt_id + "-features",
        "image_id": IMAGE,
        "docker_context": args.docker_context,
        "cpus": 2,
        "memory_bytes": 8 * 1024**3,
        "cpu_seconds": 7200,
        "wall_seconds": 7200,
        "feature_response_bytes": 64 * 1024**2,
        "fit_stdout_bytes": 96 * 1024**2,
        "fit_artifact_bytes": 64 * 1024**2,
        "scratch_bytes": 1024**3,
        "fit_cutoff": FIT_CUTOFF,
        "fit_rows": EXPECTED_FIT_ROWS,
        "target_rows": EXPECTED_TARGET_ROWS,
        "recent_rows": EXPECTED_FIT_ROWS,
        "ioc_buckets": vocabulary,
        "plan_path": str(plan_path),
        "native_match_files": [str(native_path)],
        "ranking_files": [str(ranking_path)],
        "runtime_path": str(runtime),
        "output_directory": str(args.feature_output.resolve()),
        "audit_scoring_bindings": {
            str(args.target_membership.resolve()): digest(args.target_membership),
            str(args.panel.resolve()): digest(args.panel),
            str(args.protocol.resolve()): digest(args.protocol),
            str(args.scorer.resolve()): digest(args.scorer),
            str(args.reconstruct.resolve()): digest(args.reconstruct),
        },
        "bindings": {
            **source_bindings,
            **output_bindings,
            str(manifest_path): digest(manifest_path),
            str(controller): digest(controller),
            str(bench_schema): digest(bench_schema),
        },
    }
    feature_candidate_path = output / "feature_authorization_candidate.json"
    save(feature_candidate_path, feature_auth)
    equivalence_auth = {
        "status": EQUIVALENCE_STATUS,
        "python": sys.executable,
        "builder": str(args.feature_builder.resolve()),
        "config": str(equivalence_config_path),
        "output_directory": str(args.equivalence_output.resolve()),
        "original_features": str(args.incumbent_features.resolve()),
        "original_labels": str(args.incumbent_labels.resolve()),
        "sidecar_manifest": str(args.sidecar_manifest.resolve()),
        "pipeline_manifest": str(args.pipeline_manifest.resolve()),
        "selection_record": str(args.selection_record.resolve()),
        "selected_forecast": str(args.selected_forecast.resolve()),
        "feature_authorization_candidate": str(feature_candidate_path),
        "bindings": {
            **source_bindings,
            **output_bindings,
            str(manifest_path): digest(manifest_path),
            str(equivalence_config_path): digest(equivalence_config_path),
            str(feature_candidate_path): digest(feature_candidate_path),
        },
    }
    save(output / "incumbent_equivalence_authorization.json", equivalence_auth)
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "status",
                    "primary_state_history_rows",
                    "fit_rows",
                    "target_rows",
                    "count_block_status_primary",
                    "replay_schedule",
                )
            },
            indent=2,
        )
    )


def verify_bindings(auth: dict) -> None:
    for raw_path, expected in auth["bindings"].items():
        path = Path(raw_path).resolve()
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest(path) != expected:
            raise ValueError(f"binding mismatch: {path}")


def equivalence(args: argparse.Namespace) -> None:
    """Replay incumbent base features after shared ranking qualification and prove identity."""
    authorization = args.authorization.resolve()
    auth = json.loads(authorization.read_text())
    if auth.get("status") != EQUIVALENCE_STATUS:
        raise ValueError("exact incumbent-equivalence authorization required")
    verify_bindings(auth)
    output = Path(auth["output_directory"]).resolve()
    if output.exists():
        raise FileExistsError(f"equivalence output already exists: {output}")
    environment = dict(os.environ)
    environment.update(
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        VECLIB_MAXIMUM_THREADS="1",
    )
    started = time.monotonic()
    run = subprocess.run(
        [auth["python"], "-B", auth["builder"], "--config", auth["config"]],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    if run.returncode:
        raise RuntimeError(f"incumbent feature replay failed: {run.stderr[-4000:]}")
    (output / "equivalence_stdout.txt").write_text(run.stdout)
    (output / "equivalence_stderr.txt").write_text(run.stderr)

    original_features = Path(auth["original_features"])
    original_labels = Path(auth["original_labels"])
    rebuilt_features = output / "features.csv"
    rebuilt_labels = output / "labels.csv"
    exact_features = digest(original_features) == digest(rebuilt_features)
    exact_labels = digest(original_labels) == digest(rebuilt_labels)
    if not exact_features or not exact_labels:
        raise ValueError("qualified ranking replay changed incumbent features or labels")

    with rebuilt_features.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        feature_fields = reader.fieldnames or []
        feature_rows = sum(1 for _ in reader)
    if feature_rows != EXPECTED_PANEL_ROWS:
        raise ValueError("equivalence replay feature population drift")
    ranking_audit_fields = [
        name for name in feature_fields if name.startswith("ranking_") or name.startswith("rank_")
    ]
    count_dynamic_fields = [
        name
        for name in feature_fields
        if any(
            token in name
            for token in ("serve_", "return_", "count_", "volume_", "elo_", "workload_")
        )
    ]

    sidecar_manifest_path = Path(auth["sidecar_manifest"])
    sidecar = json.loads(sidecar_manifest_path.read_text())
    sidecar_root = sidecar_manifest_path.parent
    sidecar_outputs = {}
    for name, spec in sidecar["outputs"].items():
        actual = digest(sidecar_root / name)
        if actual != spec["sha256"]:
            raise ValueError(f"incumbent sidecar output drift: {name}")
        sidecar_outputs[name] = actual
    if sidecar["inputs"]["base_features"]["sha256"] != digest(rebuilt_features):
        raise ValueError("rebuilt base features do not preserve bound BIO sidecar ancestry")

    selection_path = Path(auth["selection_record"])
    selection = json.loads(selection_path.read_text())
    pipeline_root = selection_path.parents[3]
    selector_predictions = {}
    for candidate_id, candidate in selection["candidate_trials"].items():
        for year, source in candidate["prediction_sources"].items():
            raw_path = pipeline_root / "raw" / year / "hgb" / "full" / f"{candidate_id}.csv"
            actual = digest(raw_path)
            if actual != source["prediction_sha256"]:
                raise ValueError(f"selector prediction drift: {year}/{candidate_id}")
            selector_predictions[str(raw_path)] = actual
    selected_forecast = Path(auth["selected_forecast"])
    if digest(selected_forecast) != selection["selected_prediction_sha256"]:
        raise ValueError("selected full forecast drift")

    receipt = {
        "status": "PASS_full_ancestry_incumbent_input_equivalence",
        "authorization_sha256": digest(authorization),
        "ranking_intervention": {
            "normalized_all_rows_bound": 1_543_106,
            "conflicting_groups_removed": 190,
            "conflicting_rows_removed": 380,
            "qualified_rows": 1_542_726,
            "global_edition_dates_equal": True,
            "known_player_universe_equal": True,
        },
        "base_feature_equivalence": {
            "rows": feature_rows,
            "ordered_bytes_equal": exact_features,
            "original_sha256": digest(original_features),
            "rebuilt_sha256": digest(rebuilt_features),
            "labels_ordered_bytes_equal": exact_labels,
            "original_labels_sha256": digest(original_labels),
            "rebuilt_labels_sha256": digest(rebuilt_labels),
            "ranking_audit_fields_proved_equal": ranking_audit_fields,
            "count_and_dynamic_state_fields_proved_equal": count_dynamic_fields,
        },
        "bio_sidecar_equivalence": {
            "manifest_sha256": digest(sidecar_manifest_path),
            "base_feature_input_matches_rebuilt": True,
            "outputs": sidecar_outputs,
        },
        "selector_and_final_reuse": {
            "scope": "2021-2023 HGB-full selector holdouts and selected 2024 HGB-full forecast",
            "selection_record_sha256": digest(selection_path),
            "selection_membership_sha256": selection["selection_membership_sha256"],
            "selection_rows": selection["selection_rows"],
            "selection_years": selection["selection_years"],
            "selector_prediction_files": selector_predictions,
            "selected_candidate_id": selection["selected_candidate_id"],
            "selected_forecast_sha256": digest(selected_forecast),
            "outer_primary_membership_sha256": selection["outer_primary_membership_sha256"],
            "outer_primary_rows": selection["outer_primary_rows"],
            "pipeline_manifest_sha256": digest(auth["pipeline_manifest"]),
            "reuse_basis": "all ordered base feature values and labels are byte-identical; the bound BIO sidecar and frozen downstream artifacts are unchanged",
        },
        "runtime": {
            "wall_seconds": time.monotonic() - started,
            "thread_environment": {
                key: environment[key]
                for key in sorted(environment)
                if key.endswith("NUM_THREADS") or key == "VECLIB_MAXIMUM_THREADS"
            },
            "builder": auth["builder"],
            "builder_sha256": digest(auth["builder"]),
        },
    }
    receipt_path = output / "INCUMBENT_EQUIVALENCE_RECEIPT.json"
    save(receipt_path, receipt)
    feature_candidate_path = Path(auth["feature_authorization_candidate"])
    feature_auth = json.loads(feature_candidate_path.read_text())
    if feature_auth.get("status") != FEATURE_CANDIDATE_STATUS:
        raise ValueError("feature authorization candidate status drift")
    feature_auth["status"] = FEATURE_STATUS
    feature_auth["incumbent_equivalence_receipt"] = str(receipt_path)
    feature_auth["bindings"][str(receipt_path)] = digest(receipt_path)
    save(output / "feature_authorization.json", feature_auth)
    print(json.dumps(receipt, indent=2))


def normalize(row: dict[str, str]) -> dict[str, object]:
    result: dict[str, object] = dict(row)
    for key in ("match_num", "winner_id", "loser_id", "draw_size", "best_of"):
        result[key] = int(float(row[key])) if row.get(key) else None
    numeric_suffixes = {"rank", "rank_points", "seed", "age", "ht"}
    for key, value in list(result.items()):
        numeric = key.startswith(("w_", "l_")) or key == "minutes"
        numeric |= (
            key.startswith(("winner_", "loser_")) and key.split("_", 1)[1] in numeric_suffixes
        )
        if numeric:
            try:
                number = float(value) if value not in (None, "") else None
                result[key] = number if number is None or math.isfinite(number) else None
            except (TypeError, ValueError) as error:
                _ = error
                result[key] = None
    return result


def ranking_groups(files: list[str]):
    group: dict[int, dict[str, object]] = {}
    current = None
    last = None
    for filename in files:
        with Path(filename).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                when = dt.datetime.strptime(row["ranking_date"], "%Y%m%d").date().isoformat()
                player, rank = int(row["player"]), float(row["rank"])
                if last is not None and when < last:
                    raise ValueError("ranking carrier date order drift")
                last = when
                if current is not None and when != current:
                    yield current, [group[key] for key in sorted(group)]
                    group = {}
                current = when
                try:
                    points = float(row["points"])
                except (TypeError, ValueError) as error:
                    _ = error
                    points = None
                if player in group:
                    raise ValueError("ranking carrier duplicate player/date")
                group[player] = {
                    "player_id": player,
                    "ranking_date": when,
                    "rank": rank,
                    "points": points,
                }
    if current is not None:
        yield current, [group[key] for key in sorted(group)]


def docker_base(auth: dict) -> list[str]:
    context = auth.get("docker_context")
    if not isinstance(context, str) or not context or any(char.isspace() for char in context):
        raise ValueError("invalid Docker context")
    return ["docker", "--context", context]


def limits(auth: dict) -> list[str]:
    if float(auth["cpus"]) > 2 or int(auth["memory_bytes"]) > 16 * 1024**3:
        raise ValueError("shared audit resource ceiling exceeded")
    return [
        "--network",
        "none",
        "--read-only",
        "--memory",
        str(auth["memory_bytes"]),
        "--memory-swap",
        str(auth["memory_bytes"]),
        "--cpus",
        format(float(auth["cpus"]), "g"),
        "--pids-limit",
        "32",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--ulimit",
        f"cpu={int(auth['cpu_seconds'])}:{int(auth['cpu_seconds'])}",
    ]


def project(args: argparse.Namespace) -> None:
    authorization = args.authorization.resolve()
    auth = json.loads(authorization.read_text())
    if auth.get("status") != FEATURE_STATUS or auth["image_id"] != IMAGE:
        raise ValueError("exact feature-only authorization and image required")
    verify_bindings(auth)
    equivalence_receipt = Path(auth["incumbent_equivalence_receipt"]).resolve()
    equivalence = json.loads(equivalence_receipt.read_text())
    if (
        equivalence.get("status") != "PASS_full_ancestry_incumbent_input_equivalence"
        or not equivalence["base_feature_equivalence"]["ordered_bytes_equal"]
        or not equivalence["base_feature_equivalence"]["labels_ordered_bytes_equal"]
    ):
        raise ValueError("full-ancestry incumbent equivalence receipt required")
    output = Path(auth["output_directory"]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "authorization_copy.json").write_text(authorization.read_text())
    start = time.monotonic()

    plan = json.loads(Path(auth["plan_path"]).read_text())
    by_id = {row["match_id"]: row for row in plan}
    if len(by_id) != len(plan):
        raise ValueError("duplicate plan match_id")
    by_locator = {(row["source_file"], int(row["source_line"])): row for row in plan}
    raw: dict[str, dict[str, object]] = {}
    sequence = 0
    for filename in auth["native_match_files"]:
        with Path(filename).open(newline="", encoding="utf-8") as stream:
            for line, row in enumerate(csv.DictReader(stream), start=2):
                spec = by_locator[(Path(filename).name, line)]
                key = spec["match_id"]
                record = normalize(row)
                record.update(
                    _native_sequence=sequence,
                    _transport_id=key,
                    match_date=spec["target_date_proxy"],
                    available_date=spec["available_date_proxy"],
                )
                raw[key] = record
                sequence += 1
    if set(raw) != set(by_id):
        raise ValueError("plan/native carrier membership mismatch")
    tasks: dict[str, list[str]] = collections.defaultdict(list)
    for row in plan:
        if row["fit_target"] or row["evaluation_target"]:
            tasks[row["eligible_through_date"]].append(row["match_id"])
    releases = sorted(plan, key=lambda row: (row["available_date_proxy"], row["match_id"]))
    rank_stream = iter(ranking_groups(auth["ranking_files"]))
    next_ranks = next(rank_stream, None)
    cursor = 0
    base = docker_base(auth)
    image = auth["image_id"]
    if (
        subprocess.check_output(
            base + ["image", "inspect", image, "--format", "{{.Id}}"], text=True
        ).strip()
        != image
    ):
        raise ValueError("Docker image ID mismatch")
    name = auth["attempt_id"]
    if not SAFE_NAME.fullmatch(name):
        raise ValueError("unsafe attempt_id")
    stderr = (output / "feature_stderr.txt").open("w")
    worker = subprocess.Popen(
        base
        + ["run", "--name", name, "-i"]
        + limits(auth)
        + [image, "python", "feature_worker.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=True,
        bufsize=1,
    )
    if worker.stdin is None or worker.stdout is None:
        raise RuntimeError("feature worker pipe unavailable")
    selector = selectors.DefaultSelector()
    selector.register(worker.stdout, selectors.EVENT_READ)
    deadline = start + int(auth["wall_seconds"])

    def exchange(message: dict) -> dict:
        worker.stdin.write(json.dumps(message, allow_nan=False, separators=(",", ":")) + "\n")
        worker.stdin.flush()
        if not selector.select(timeout=max(0, deadline - time.monotonic())):
            raise TimeoutError("feature worker wall cap")
        line = worker.stdout.readline(int(auth["feature_response_bytes"]) + 1)
        if not line:
            raise RuntimeError("feature worker exited")
        return json.loads(line)

    try:
        if exchange({"reference_date": auth["fit_cutoff"], "ioc_buckets": auth["ioc_buckets"]}) != {
            "ready": True
        }:
            raise ValueError("feature worker initialization mismatch")
        handles = {
            role: (output / f"{role}_features.csv").open("w", newline="")
            for role in ("training", "target")
        }
        writers: dict[str, csv.DictWriter] = {}
        header = None
        counts: collections.Counter[str] = collections.Counter()
        with (output / "release_receipts.jsonl").open("w") as receipts:
            for cutoff, keys in sorted(tasks.items()):
                history = []
                while cursor < len(releases) and releases[cursor]["available_date_proxy"] <= cutoff:
                    history.append(raw[releases[cursor]["match_id"]])
                    cursor += 1
                rankings = []
                while next_ranks is not None and next_ranks[0] <= cutoff:
                    rankings.extend(next_ranks[1])
                    next_ranks = next(rank_stream, None)
                answer = exchange(
                    {
                        "cutoff": cutoff,
                        "history": history,
                        "rankings": rankings,
                        "targets": [neutral_fixture(raw[key]) for key in sorted(keys)],
                    }
                )
                if {row["match_id"] for row in answer["outputs"]} != set(keys):
                    raise ValueError("worker target membership mismatch")
                receipts.write(json.dumps(answer["receipt"], separators=(",", ":")) + "\n")
                for row in answer["outputs"]:
                    key = row["match_id"]
                    role = "training" if by_id[key]["fit_target"] else "target"
                    if row["label"] is not None:
                        raise ValueError("target outcome crossed worker boundary")
                    if role == "training":
                        row["label"] = int(int(raw[key]["winner_id"]) < int(raw[key]["loser_id"]))
                    if header is None:
                        header = list(row)
                    if list(row) != header:
                        raise ValueError("feature schema drift")
                    if role not in writers:
                        writers[role] = csv.DictWriter(handles[role], fieldnames=header)
                        writers[role].writeheader()
                    writers[role].writerow(row)
                    counts[role] += 1
        for handle in handles.values():
            handle.close()
        worker.stdin.close()
        worker.wait(timeout=max(1, deadline - time.monotonic()))
        if worker.returncode:
            raise RuntimeError("feature worker failed")
        stderr.close()
        (output / "feature_container_inspect.json").write_bytes(
            subprocess.check_output(base + ["inspect", name])
        )
        if counts != {"training": EXPECTED_FIT_ROWS, "target": EXPECTED_TARGET_ROWS}:
            raise ValueError(f"feature membership mismatch: {counts}")
        replay = {"batches": 0, "rows": 0}
        with (output / "release_receipts.jsonl").open() as stream:
            for line in stream:
                receipt = json.loads(line)
                replay["batches"] = receipt["cumulative_chronology_replays"]
                replay["rows"] = receipt["cumulative_replayed_rows"]
        inputs = output / "fit_inputs"
        inputs.mkdir()
        for filename in ("training_features.csv", "target_features.csv"):
            os.link(output / filename, inputs / filename)
        fit_config = {
            "tour": "wta",
            "fit_cutoff": FIT_CUTOFF,
            "fit_rows": EXPECTED_FIT_ROWS,
            "target_rows": EXPECTED_TARGET_ROWS,
            "recent_rows": EXPECTED_FIT_ROWS,
            "fit_artifact_bytes": int(auth["fit_artifact_bytes"]),
            "inputs": {
                filename: digest(inputs / filename)
                for filename in ("training_features.csv", "target_features.csv")
            },
        }
        save(inputs / "fit_config.json", fit_config)
        commitment = {
            "status": "features_complete_no_fit_no_scores",
            "authorization_sha256": digest(authorization),
            "incumbent_equivalence_receipt_sha256": digest(equivalence_receipt),
            "image_id": image,
            "feature_input_hashes": fit_config["inputs"],
            "fit_config_sha256": digest(inputs / "fit_config.json"),
            "release_receipts_sha256": digest(output / "release_receipts.jsonl"),
            "counts": dict(counts),
            "chronology_replay": replay,
            "wall_seconds": time.monotonic() - start,
        }
        save(output / "FEATURE_COMMITMENT.json", commitment)
        candidate = dict(auth)
        candidate.update(
            status="REQUIRES_OWNER_FREEZE_SHARED_WTA_BUILDOAK_FORECAST",
            attempt_id=auth["attempt_id"].removesuffix("-features") + "-fit",
            feature_directory=str(output),
            feature_commitment_path=str(output / "FEATURE_COMMITMENT.json"),
            output_directory=str(output.parent / "forecast_attempt_001"),
        )
        candidate["bindings"] = {
            **auth["bindings"],
            str(output / "FEATURE_COMMITMENT.json"): digest(output / "FEATURE_COMMITMENT.json"),
            str(inputs / "fit_config.json"): digest(inputs / "fit_config.json"),
            str(inputs / "training_features.csv"): digest(inputs / "training_features.csv"),
            str(inputs / "target_features.csv"): digest(inputs / "target_features.csv"),
            str(Path(__file__).resolve()): digest(__file__),
        }
        save(output / "forecast_authorization_candidate.json", candidate)
        print(json.dumps(commitment, indent=2))
    finally:
        subprocess.run(base + ["kill", name], capture_output=True)
        subprocess.run(base + ["rm", name], capture_output=True)
        if not stderr.closed:
            stderr.close()


def retain_fit(stdout: str, destination: Path, max_bytes: int) -> dict:
    message = json.loads(stdout)
    artifacts = message["artifacts_base64"]
    destination.mkdir(exist_ok=False)
    total = 0
    for name, encoded in sorted(artifacts.items()):
        if not SAFE_NAME.fullmatch(name) or not name.endswith((".json", ".csv")):
            raise ValueError("unsafe fit artifact")
        content = base64.b64decode(encoded, validate=True)
        total += len(content)
        if total > max_bytes:
            raise ValueError("fit artifact ceiling")
        (destination / name).write_bytes(content)
    return {key: value for key, value in message.items() if key != "artifacts_base64"}


def validate_wta_forecast(
    retained: dict, forecast_dir: Path, feature_dir: Path, config: dict, control: bool
) -> dict:
    """Fail closed on the exact retained WTA family, activation, and target carrier."""
    expected_artifacts = {
        "fit_receipt.json",
        "global_component_01.json",
        "global_component_02.json",
        "native_forecasts.csv",
        "segment_Hard.json",
        "segment_I.json",
    }
    actual_artifacts = {path.name for path in forecast_dir.iterdir()}
    if (
        actual_artifacts != expected_artifacts
        or set(retained["artifact_inventory"]) != expected_artifacts
    ):
        raise ValueError("unexpected retained WTA artifact inventory")
    receipt = json.loads((forecast_dir / "fit_receipt.json").read_text())
    if (
        retained.get("tour") != "wta"
        or receipt.get("tour") != "wta"
        or retained.get("fit_members") != 4
        or retained.get("fit_rows") != config["fit_rows"]
        or retained.get("target_rows") != config["target_rows"]
        or retained.get("native_rows") != config["target_rows"]
        or receipt.get("fit_rows") != config["fit_rows"]
        or receipt.get("target_rows") != config["target_rows"]
        or receipt.get("native_rows") != config["target_rows"]
        or receipt.get("fit_cutoff") != config["fit_cutoff"]
    ):
        raise ValueError("retained WTA fit/target/native identity mismatch")
    if not control and (
        config["fit_rows"] != EXPECTED_FIT_ROWS or config["target_rows"] != EXPECTED_TARGET_ROWS
    ):
        raise ValueError("empirical WTA fit/target population drift")

    expected_menu = {
        "global_component_01": {
            "role": "full_global",
            "trees": 800,
            "ensemble_weight": 0.65,
            "n_estimators": 800,
        },
        "global_component_02": {
            "role": "full_global",
            "trees": 650,
            "ensemble_weight": 0.35,
            "n_estimators": 650,
        },
        "segment_Hard": {
            "role": "segment_specialist",
            "trees": 900,
            "segment_column": "surface",
            "segment_value": "Hard",
            "global_weight": 0.1,
            "n_estimators": 900,
        },
        "segment_I": {
            "role": "segment_specialist",
            "trees": 900,
            "segment_column": "tourney_level",
            "segment_value": "I",
            "global_weight": 0.1,
            "n_estimators": 900,
        },
    }
    menu = {entry["member"]: entry for entry in receipt["fit_menu"]}
    if set(menu) != set(expected_menu):
        raise ValueError("retained WTA model menu drift")
    for member, expected in expected_menu.items():
        entry = menu[member]
        for field, value in expected.items():
            actual = entry["parameters"][field] if field == "n_estimators" else entry.get(field)
            if actual != value:
                raise ValueError(f"retained WTA model specification drift: {member}/{field}")
        if entry["rows"] <= 0:
            raise ValueError(f"retained WTA member has no training rows: {member}")
    temporal = receipt["activation"]["temporal"]
    if temporal != {
        "recent_start": "2017-01-01",
        "recent_weight": 0.35,
        "min_recent_rows": 15_000,
        "recent_rows": config["recent_rows"],
        "active": False,
    }:
        raise ValueError("retained WTA temporal activation drift")
    expected_segments = {
        ("surface", "Hard", 0.1, True),
        ("tourney_level", "I", 0.1, True),
    }
    segments = {
        (row["column"], row["value"], row["global_weight"], row["active"])
        for row in receipt["activation"]["segments"]
        if row["rows"] > 0
    }
    if segments != expected_segments:
        raise ValueError("retained WTA segment activation drift")
    if set(receipt["artifact_sha256"]) != expected_artifacts - {"fit_receipt.json"}:
        raise ValueError("retained WTA receipt artifact hash inventory drift")
    for name, expected in receipt["artifact_sha256"].items():
        if name == "fit_receipt.json" or digest(forecast_dir / name) != expected:
            raise ValueError(f"retained WTA artifact hash mismatch: {name}")

    target_path = feature_dir / "fit_inputs" / "target_features.csv"
    with target_path.open(newline="", encoding="utf-8") as stream:
        target_rows = list(csv.DictReader(stream))
    targets = {row["match_id"]: row for row in target_rows}
    if len(targets) != len(target_rows) or len(targets) != config["target_rows"]:
        raise ValueError("committed WTA target membership is duplicate or incomplete")
    with (forecast_dir / "native_forecasts.csv").open(newline="", encoding="utf-8") as stream:
        forecast_rows = list(csv.DictReader(stream))
    forecasts = {row["match_id"]: row for row in forecast_rows}
    if len(forecasts) != len(forecast_rows) or set(forecasts) != set(targets):
        raise ValueError("native WTA forecast target membership mismatch")
    for match_id, row in forecasts.items():
        probability = float(row["p_a_native"])
        if (
            row["native_status"] != "native"
            or int(row["canonical_a_source_id"]) != int(float(targets[match_id]["player_a_id"]))
            or not math.isfinite(probability)
            or not 0 <= probability <= 1
        ):
            raise ValueError(f"invalid native WTA forecast row: {match_id}")
    membership_sha256 = key_hash([("2024", key) for key in sorted(forecasts)])
    if not control and membership_sha256 != EXPECTED_TARGET_KEY_HASH:
        raise ValueError("native WTA forecast frozen target membership drift")
    return {
        "fit_menu_members": sorted(menu),
        "recent_active": temporal["active"],
        "native_membership_rows": len(forecasts),
        "native_membership_sha256": membership_sha256,
        "verified_artifacts": sorted(actual_artifacts),
    }


def forecast(args: argparse.Namespace) -> None:
    authorization = args.authorization.resolve()
    auth = json.loads(authorization.read_text())
    if auth.get("status") != FORECAST_STATUS or auth["image_id"] != IMAGE:
        raise ValueError("owner-frozen shared forecast authorization required")
    verify_bindings(auth)
    feature = Path(auth["feature_directory"]).resolve()
    commitment = json.loads(Path(auth["feature_commitment_path"]).read_text())
    if commitment["status"] != "features_complete_no_fit_no_scores":
        raise ValueError("feature commitment incomplete")
    for filename, expected in commitment["feature_input_hashes"].items():
        if digest(feature / "fit_inputs" / filename) != expected:
            raise ValueError("committed feature input changed")
    fit_config_path = feature / "fit_inputs" / "fit_config.json"
    if digest(fit_config_path) != commitment["fit_config_sha256"]:
        raise ValueError("committed fit configuration changed")
    fit_config = json.loads(fit_config_path.read_text())
    if fit_config.get("tour") != "wta" or fit_config.get("recent_rows") >= 15_000:
        raise ValueError("shared WTA recipe or recent-branch activation drift")
    output = Path(auth["output_directory"]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "authorization_copy.json").write_text(authorization.read_text())
    base = docker_base(auth)
    name = auth["attempt_id"]
    volume = name + "-inputs"
    staging = name + "-staging"
    subprocess.run(base + ["volume", "create", volume], check=True, capture_output=True)
    try:
        subprocess.run(
            base
            + [
                "create",
                "--name",
                staging,
                "--network",
                "none",
                "--mount",
                f"type=volume,source={volume},target=/inputs",
                IMAGE,
                "true",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            base + ["cp", str(feature / "fit_inputs") + "/.", staging + ":/inputs"],
            check=True,
            capture_output=True,
        )
        subprocess.run(base + ["rm", staging], check=True, capture_output=True)
        subprocess.run(
            base
            + ["create", "--name", name]
            + limits(auth)
            + [
                "--mount",
                f"type=volume,source={volume},target=/inputs,readonly",
                IMAGE,
                "python",
                "fit_worker.py",
            ],
            check=True,
            capture_output=True,
        )
        run = subprocess.run(
            base + ["start", "-a", name],
            capture_output=True,
            text=True,
            timeout=int(auth["wall_seconds"]),
            check=False,
        )
        (output / "fit_stdout.txt").write_text(run.stdout)
        (output / "fit_stderr.txt").write_text(run.stderr)
        (output / "fit_container_inspect.json").write_bytes(
            subprocess.check_output(base + ["inspect", name])
        )
        if run.returncode:
            raise RuntimeError("fit worker failed")
        retained = retain_fit(run.stdout, output / "forecast", int(auth["fit_artifact_bytes"]))
        if retained.get("status") != "forecast_complete_no_scores":
            raise ValueError("fit worker completion mismatch")
        forecast_validation = validate_wta_forecast(
            retained,
            output / "forecast",
            feature,
            fit_config,
            control=bool(commitment.get("control")),
        )
        result = {
            "status": "forecast_complete_no_scores",
            "tour": "wta",
            "authorization_sha256": digest(authorization),
            "image_id": IMAGE,
            "feature_commitment_sha256": digest(auth["feature_commitment_path"]),
            "audit_scoring_bindings": auth["audit_scoring_bindings"],
            "forecast_validation": forecast_validation,
            "forecast_sha256": {
                path.name: digest(path) for path in sorted((output / "forecast").iterdir())
            },
        }
        save(output / "FORECAST_COMMITMENT.json", result)
        print(json.dumps(result, indent=2))
    finally:
        subprocess.run(base + ["kill", name], capture_output=True)
        subprocess.run(base + ["rm", name], capture_output=True)
        subprocess.run(base + ["rm", staging], capture_output=True)
        subprocess.run(base + ["volume", "rm", volume], capture_output=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--panel", type=Path, required=True)
    prep.add_argument("--rankings", type=Path, required=True)
    prep.add_argument("--players", type=Path, required=True)
    prep.add_argument("--training-keys", type=Path, required=True)
    prep.add_argument("--target-membership", type=Path, required=True)
    prep.add_argument("--incumbent-features", type=Path, required=True)
    prep.add_argument("--incumbent-labels", type=Path, required=True)
    prep.add_argument("--fit-manifest", type=Path, required=True)
    prep.add_argument("--selection-record", type=Path, required=True)
    prep.add_argument("--selected-forecast", type=Path, required=True)
    prep.add_argument("--incumbent-predictions", type=Path, required=True)
    prep.add_argument("--sidecar-manifest", type=Path, required=True)
    prep.add_argument("--incumbent-feature-config", type=Path, required=True)
    prep.add_argument("--design", type=Path, required=True)
    prep.add_argument("--incumbent-edition-index", type=Path, required=True)
    prep.add_argument("--ranking-lookup-module", type=Path, required=True)
    prep.add_argument("--feature-builder", type=Path, required=True)
    prep.add_argument("--pipeline-manifest", type=Path, required=True)
    prep.add_argument("--equivalence-output", type=Path, required=True)
    prep.add_argument("--protocol", type=Path, required=True)
    prep.add_argument("--scorer", type=Path, required=True)
    prep.add_argument("--reconstruct", type=Path, required=True)
    prep.add_argument("--runtime", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--feature-output", type=Path, required=True)
    prep.add_argument("--attempt-id", default="wta-shared-2024-001")
    prep.add_argument("--docker-context", default="colima-buildoak-extension-20260917")
    prep.set_defaults(func=prepare)
    for name, function in (("equivalence", equivalence), ("forecast", forecast)):
        command = commands.add_parser(name)
        command.add_argument("--authorization", type=Path, required=True)
        command.set_defaults(func=function)
    projection = commands.add_parser("project")
    projection.add_argument("--authorization", type=Path, required=True)
    projection.set_defaults(func=project)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
