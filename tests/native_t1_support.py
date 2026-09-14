"""Test-local fixture, full outcome/stat intervention and exact native T1 comparator."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path
from typing import Any

TARGET_DATE = "2020-01-08"
CUTOFF = "2020-01-06"
COUNTS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")
# Valid complete blocks, deliberately unlike the generated rows, keyed to neutral players.
NEW_COUNTS = {
    "a": dict(zip(COUNTS, (11, 4, 101, 62, 44, 19, 15, 7, 12), strict=True)),
    "b": dict(zip(COUNTS, (3, 7, 113, 69, 40, 20, 17, 9, 15), strict=True)),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def rows(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", newline="") as handle:
        return list(csv.DictReader(handle))


def csv_bytes(header: list[str], records: list[dict[str, Any]]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return handle.getvalue().encode()


def archive_members(path: Path) -> dict[str, bytes]:
    with tarfile.open(path) as archive:
        return {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }


def write_archive(path: Path, members: dict[str, bytes]) -> None:
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name, payload in sorted(members.items()):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(payload))


def rebind(workspace: Path, config: Path, sample: Path) -> None:
    """Rebind only changed input bytes; never change a fitted setting or expected score."""
    panel = sample / "panel.csv"
    manifest = read_json(sample / "panel_manifest.json")
    manifest["panel_sha256"] = digest(panel)
    write_json(sample / "panel_manifest.json", manifest)
    primary = read_json(sample / "sr02_primary.json")
    primary["input"]["panel_sha256"] = digest(panel)
    write_json(sample / "sr02_primary.json", primary)
    if (sample / "archive_manifest.json").exists():
        members = archive_members(sample / "archive.tar.gz")
        inventory = []
        for name, payload in sorted(members.items()):
            inventory.append(
                {
                    "path": name.split("/", 1)[1],
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "git_blob_sha1": hashlib.sha1(
                        f"blob {len(payload)}\0".encode() + payload
                    ).hexdigest(),
                    "git_mode": "100644",
                }
            )
        (sample / "snapshot_file_inventory.csv").write_bytes(
            csv_bytes(list(inventory[0]), inventory)
        )
        custody = read_json(sample / "archive_manifest.json")
        for entry in custody["files"]:
            path = workspace / entry["path"]
            entry.update(sha256=digest(path), bytes=path.stat().st_size)
        write_json(sample / "archive_manifest.json", custody)
    document = read_json(config)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                path = workspace / value["path"]
                if path.is_file():
                    value["sha256"] = digest(path)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    write_json(config, document)
    receipt = read_json(sample / "manifest.json")
    receipt["native_t1_test_copy"] = True
    receipt["files"] = {name: digest(sample / name) for name in receipt["files"]}
    write_json(sample / "manifest.json", receipt)


def build_fixture(root: Path, workspace: Path, tour: str) -> dict[str, Any]:
    tier = tour == "ATP"
    sample_rel = Path("data", "sample_tier" if tier else "sample")
    config_rel = Path("configs", "chains", "sample_atp_tier.json" if tier else "sample_atp.json")
    assert (root / sample_rel / "manifest.json").is_file(), "required committed fixture absent"
    sample = workspace / sample_rel
    sample.parent.mkdir(parents=True)
    shutil.copytree(root / sample_rel, sample)
    config = workspace / config_rel
    config.parent.mkdir(parents=True)
    shutil.copy2(root / config_rel, config)
    document = read_json(config)
    chain = document["chain"]
    if tour == "WTA":
        # Synthetic branch coverage: preserve identities/calendar, use only ordinary BO3.
        panel = rows(sample / "panel.csv")
        for row in panel:
            row.update(best_of="3", tourney_level="A")
            row["score"] = (
                "6-4 6-3"
                if row["status"] == "completed"
                else "6-4 1-0 " + ("RET" if row["status"] == "retired" else "DEF")
            )
            row["source_member"] = row["source_member"].replace("atp_", "wta_")
        (sample / "panel.csv").write_bytes(csv_bytes(list(panel[0]), panel))
        members = archive_members(sample / "archive.tar.gz")
        translated = {}
        for name, payload in members.items():
            name = name.replace("/atp/", "/wta/").replace("/atp_", "/wta_")
            if "/wta_rankings_" in name:
                reader = csv.DictReader(io.StringIO(payload.decode()))
                header = [*reader.fieldnames, "tours"]
                records = [{**row, "tours": "0"} for row in reader]
                payload = csv_bytes(header, records)
            if "/wta_matches_" in name:
                records = list(csv.DictReader(io.StringIO(payload.decode())))
                for row in records:
                    row.update(best_of="3", tourney_level="A")
                    row["score"] = (
                        "6-4 1-0 RET"
                        if "RET" in row["score"]
                        else "6-4 1-0 DEF"
                        if "DEF" in row["score"]
                        else "6-4 6-3"
                    )
                payload = csv_bytes(list(records[0]), records)
            translated[name] = payload
        write_archive(sample / "archive.tar.gz", translated)
        # A synthetic rule contract, explicitly declared rather than inferred from outcomes.
        rules = {
            "regular_set": {"mode": "tiebreak", "tiebreak_at_games": 6, "tiebreak_points": 7},
            "ordinary_wta": {
                "best_of": 3,
                "levels": ["A"],
                "deciding_set": {"mode": "tiebreak", "tiebreak_at_games": 6, "tiebreak_points": 7},
                "basis": "synthetic_declared_format_before_mutation",
            },
            "declared_assumptions": [
                "Synthetic ordinary WTA BO3 format, declared before outcome mutation."
            ],
            "information_set_limit": "Synthetic branch coverage only; no empirical WTA rule claim.",
            "grand_slam_names": {},
            "grand_slams": {},
        }
        write_json(sample / "native_wta_rules.json", rules)
        (sample / "native_wta_inventory.csv").write_text("tourney_id\n")
        chain["tour"] = "WTA"
        chain["skip_stages"].remove("bridge")
        chain["count_history_from_year"] = 2012
        chain["wta_bio_players"] = chain["inputs"]["bio_players"]
        for name in ("wta_market_manifest", "wta_event_map_manifest", "wta_sources_module"):
            chain["inputs"][name] = chain["inputs"]["bio_contract"].copy()
        for name, filename in (
            ("wta_rule_config", "native_wta_rules.json"),
            ("wta_rule_inventory", "native_wta_inventory.csv"),
        ):
            chain["inputs"][name] = {
                "path": str(sample_rel / filename),
                "sha256": digest(sample / filename),
            }
        chain["stage_config_overrides"]["rule_mapping"] = {
            "wta_rule_rows": {"panel": {"path": str(sample_rel / "panel.csv")}}
        }
        chain["stage_config_overrides"]["sidecar"]["inputs"]["bio_players"] = chain["inputs"][
            "bio_players"
        ].copy()
    write_json(config, document)
    rebind(workspace, config, sample)
    return {
        "workspace": workspace,
        "config": str(config),
        "sample": sample,
        "run_root": workspace / chain["run_root"],
        "tour": tour,
    }


def replace_panel_bundle(row: dict[str, str]) -> None:
    row["a_won"] = "false" if row["a_won"] == "true" else "true"
    row["a_source_side"], row["b_source_side"] = row["b_source_side"], row["a_source_side"]
    row["status"] = "retired" if row["status"] == "completed" else "completed"
    row["completed"] = str(row["status"] == "completed").lower()
    row["retired"] = str(row["status"] == "retired").lower()
    row["defaulted"] = "false"
    row["started_evidence"] = ""
    row["score"] = (
        "6-3 2-1 RET"
        if row["status"] == "retired"
        else "6-3 6-2" + (" 6-4" if row["best_of"] == "5" else "")
    )
    row["minutes"] = str(int(row["minutes"] or 0) + 31)
    row["count_block_status"] = "usable"
    for side in ("a", "b"):
        for suffix, value in NEW_COUNTS[side].items():
            row[f"{side}_{suffix}"] = str(value)


def replace_archive_bundle(row: dict[str, str], panel: dict[str, str] | None) -> None:
    for name in list(row):
        if name.startswith("winner_"):
            other = "loser_" + name[len("winner_") :]
            row[name], row[other] = row[other], row[name]
    if panel is None:
        row["score"] = "6-3 6-2" if "RET" in row["score"] else "6-3 2-1 RET"
        row["minutes"] = str(int(row["minutes"] or 0) + 31)
    else:
        expected_winner = panel["player_a"] if panel["a_won"] == "true" else panel["player_b"]
        assert row["winner_id"] == expected_winner
        row["score"], row["minutes"] = panel["score"], panel["minutes"]
    a_side = "w" if int(row["winner_id"]) < int(row["loser_id"]) else "l"
    for side, prefix in (("a", a_side), ("b", "l" if a_side == "w" else "w")):
        for suffix, value in NEW_COUNTS[side].items():
            row[f"{prefix}_{suffix}"] = str(value)


def mutate(clean: dict[str, Any], destination: Path) -> dict[str, Any]:
    shutil.copytree(clean["workspace"], destination)
    config = destination / Path(clean["config"]).relative_to(clean["workspace"])
    sample = destination / clean["sample"].relative_to(clean["workspace"])
    run_root = destination / clean["run_root"].relative_to(clean["workspace"])
    shutil.rmtree(run_root.parent)
    panel = rows(sample / "panel.csv")
    originals = {row["match_id"]: row.copy() for row in panel}
    targets = {row["match_id"] for row in panel if row["match_date"] == TARGET_DATE}
    assert targets and any(row["match_date"] == CUTOFF for row in panel)
    changed = {}
    for row in panel:
        if row["match_date"] > CUTOFF:
            replace_panel_bundle(row)
            changed[row["match_id"]] = row
        else:
            assert row == originals[row["match_id"]]
    assert targets <= changed.keys()
    (sample / "panel.csv").write_bytes(csv_bytes(list(panel[0]), panel))
    lower_dates = {}
    if clean["tour"] == "ATP":
        lower_dates = {
            row["match_id"]: row["date"]
            for row in rows(clean["run_root"] / "tier_stream" / "tier_results.csv.gz")
        }
    members = archive_members(sample / "archive.tar.gz")
    changed_lower = 0
    changed_tour = set()
    for name, payload in list(members.items()):
        if "_matches_" not in name or not name.endswith(".csv"):
            continue
        reader = csv.DictReader(io.StringIO(payload.decode()))
        header = list(reader.fieldnames or [])
        records = list(reader)
        for row in records:
            key = f"{row['tourney_id']}/{row['match_num']}"
            family = (
                "atp_qual_chall"
                if "_qual_chall_" in name
                else "atp_futures"
                if "_futures_" in name
                else None
            )
            if family is None and key in changed:
                replace_archive_bundle(row, changed[key])
                changed_tour.add(key)
            elif family and lower_dates.get(f"tier:{family}:{key}", "") > CUTOFF:
                replace_archive_bundle(row, None)
                changed_lower += 1
        members[name] = csv_bytes(header, records)
    assert changed_tour == changed.keys()
    if clean["tour"] == "ATP":
        assert changed_lower > 0
    write_archive(sample / "archive.tar.gz", members)
    rebind(destination, config, sample)
    return {
        **clean,
        "workspace": destination,
        "config": str(config),
        "sample": sample,
        "run_root": run_root,
        "targets": targets,
        "mutation": {"panel_rows": len(changed), "lower_rows": changed_lower},
    }


def target_rows(path: Path, targets: set[str]) -> list[dict[str, str]]:
    selected = [row for row in rows(path) if row.get("match_id") in targets]
    return sorted(selected, key=lambda row: json.dumps(row, sort_keys=True))


def assert_same_targets(
    clean: Path, changed: Path, targets: set[str], expected_targets: set[str] | None = None
) -> int:
    expected = targets if expected_targets is None else expected_targets
    assert expected <= targets
    # Inspect every chosen target, including those forbidden from the priced subset.
    before, after = target_rows(clean, targets), target_rows(changed, targets)
    for path, records in ((clean, before), (changed, after)):
        assert {row["match_id"] for row in records} == expected, f"target coverage: {path}"
        assert len(records) == len(expected), f"duplicate target rows: {path}"
    assert before == after, f"future outcome changed target rows: {clean}"
    return len(before)


def compare_runs(clean: dict[str, Any], changed: dict[str, Any]) -> dict[str, int]:
    fixed = [
        "features/features.csv",
        "sidecar/trait_latent_sidecar.csv",
        "sr02_replay/selected_matches.csv",
        "sr03_calibration/predictions.csv",
    ]
    if clean["tour"] == "ATP":
        fixed += [
            "tier_elo/tier_elo_features.csv",
            "tier_block/trait_latent_sidecar.csv",
            "sr02_tier_replay/selected_matches.csv",
            "sr02_tier_noqual_replay/selected_matches.csv",
        ]
    compared = {}
    for filename in fixed:
        compared[filename] = assert_same_targets(
            clean["run_root"] / filename, changed["run_root"] / filename, changed["targets"]
        )
    priced_targets = {
        row["match_id"]
        for row in rows(clean["run_root"] / "features" / "features.csv")
        if row["match_id"] in changed["targets"] and row["ps_missing"] == "0"
    }
    assert priced_targets, "the fixture must exercise the market forecast path"
    for directory in ("raw", "selected", "shared_base", "market"):
        expected_targets = priced_targets if directory == "market" else changed["targets"]
        before = sorted(
            path.relative_to(clean["run_root"])
            for path in (clean["run_root"] / "pipeline" / directory).rglob("*.csv")
        )
        after = sorted(
            path.relative_to(changed["run_root"])
            for path in (changed["run_root"] / "pipeline" / directory).rglob("*.csv")
        )
        assert before == after and before
        count = 0
        for filename in before:
            # All registered target-year forecasts must cover their declared targets;
            # neither an empty file nor an equally omitted target can disappear here.
            if filename.parts[2] != TARGET_DATE[:4]:
                continue
            if directory == "market" and filename.name == "selection_keys.csv":
                continue  # Past calibration membership, not a forecast artifact.
            compared[str(filename)] = assert_same_targets(
                clean["run_root"] / filename,
                changed["run_root"] / filename,
                changed["targets"],
                expected_targets,
            )
            count += 1
        assert count > 0, directory
    return compared
