"""Versioned normalized snapshots: results, serve state, rankings, quarantine, diff.

A version is built from validated attempts only, written to a fresh directory, and named
by ``versions/latest.json`` after its manifest verifies. Normalized tables carry no wall
clock; times of acquisition live in the receipts the rows reference by ``receipt_id``.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    atomic_csv,
    atomic_json,
    canonical_hash,
    require_nonempty_digest,
    sha256,
)
from tennislab.live import wikitext
from tennislab.live.common import (
    LiveConfig,
    LiveError,
    iso_utc,
    read_json,
    replace_pointer,
    safe_output_id,
    stamp_id,
    utc_now,
)
from tennislab.live.identity import IdentityTable
from tennislab.live.receipts import bind_receipt, validate_attempt

RESULT_COLUMNS = (
    "row_id",
    "tour",
    "event_id",
    "event_name",
    "level",
    "surface",
    "round",
    "player_a_id",
    "player_b_id",
    "player_a_name",
    "player_b_name",
    "winner_side",
    "score",
    "sets",
    "status",
    "target_anchor_date",
    "completion_upper_bound",
    "completion_basis",
    "publication_upper_bound_utc",
    "source_id",
    "source_revision",
    "receipt_id",
    "overlap_unresolved",
    "serve_block_status",
    "serve_source",
)
SERVE_COLUMNS = (
    "tour",
    "player_id",
    "event_anchor",
    "model_event_date",
    "date_basis",
    "event_id",
    "completion_upper_bound",
    "completion_basis",
    "tournament_name",
    "match_id",
    "fields_present",
    "fields_missing",
    "serve_block_valid",
    "source_id",
    "receipt_id",
    "retained_sha256",
    "overlap_unresolved",
)
RANKING_COLUMNS = (
    "tour",
    "player_id",
    "ranking_date",
    "rank",
    "points",
    "publication_basis",
    "source_id",
    "receipt_id",
)
QUARANTINE_COLUMNS = (
    "kind",
    "tour",
    "event_id",
    "round",
    "name_a",
    "name_b",
    "detail",
    "receipt_id",
    "source_revision",
)
DIFF_CATEGORIES = ("added", "revised", "removed", "duplicate", "unresolved", "conflicting")


def row_identity(tour: str, event_id: str, round_code: str, a_id: str, b_id: str) -> str:
    return hashlib.sha256("|".join([tour, event_id, round_code, a_id, b_id]).encode()).hexdigest()


def normalize_captures(
    captures: Iterable[Mapping[str, Any]],
    identity: IdentityTable,
    *,
    receipt_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Results rows, quarantine rows and per-event completeness from parsed captures."""
    results: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    completeness: list[dict[str, Any]] = []
    for capture in captures:
        event = capture["event"]
        if "source" not in capture:
            completeness.append(
                {
                    "event_id": event["event_id"],
                    "status": "no_capture",
                    "error": capture.get("error"),
                }
            )
            continue
        matches, notes = wikitext.parse_draw(capture["source"])
        revision = str(capture["revision_id"])
        published = str(capture["revision_timestamp_utc"])
        window_known = bool(event.get("window_start") and event.get("window_end"))
        seen: dict[str, dict[str, Any]] = {}
        pending = played = 0
        for match in matches:
            base = {
                "kind": "",
                "tour": event["tour"],
                "event_id": event["event_id"],
                "round": match.round,
                "name_a": match.a_title,
                "name_b": match.b_title,
                "detail": "",
                "receipt_id": receipt_id,
                "source_revision": revision,
            }
            if match.round.startswith("unresolved:"):
                quarantine.append(
                    {**base, "kind": "unresolved", "detail": f"round label {match.round}"}
                )
                continue
            if match.winner == "conflict":
                quarantine.append(
                    {
                        **base,
                        "kind": "conflicting",
                        "detail": "both sides marked winner in the bracket",
                    }
                )
                continue
            res_a = identity.resolve(match.a_title, tour=event["tour"])
            res_b = identity.resolve(match.b_title, tour=event["tour"])
            if res_a.status != "resolved" or res_b.status != "resolved":
                detail = f"a:{res_a.status}{list(res_a.candidates)} b:{res_b.status}{list(res_b.candidates)}"
                quarantine.append({**base, "kind": "unresolved", "detail": detail})
                continue
            if res_a.player_id == res_b.player_id:
                quarantine.append(
                    {**base, "kind": "conflicting", "detail": "same player on both sides"}
                )
                continue
            a_first = res_a.player_id < res_b.player_id
            a_id, b_id = (
                (res_a.player_id, res_b.player_id)
                if a_first
                else (res_b.player_id, res_a.player_id)
            )
            a_name, b_name = (
                (match.a_title, match.b_title) if a_first else (match.b_title, match.a_title)
            )
            winner_side = ""
            if match.winner == "a":
                winner_side = "a" if a_first else "b"
            elif match.winner == "b":
                winner_side = "b" if a_first else "a"
            row_id = row_identity(event["tour"], event["event_id"], match.round, a_id, b_id)
            row = {
                "row_id": row_id,
                "tour": event["tour"],
                "event_id": event["event_id"],
                "event_name": event["name"],
                "level": event.get("level", ""),
                "surface": event.get("surface", ""),
                "round": match.round,
                "player_a_id": a_id,
                "player_b_id": b_id,
                "player_a_name": a_name,
                "player_b_name": b_name,
                "winner_side": winner_side,
                "score": match.score,
                "sets": match.sets,
                "status": match.status,
                "target_anchor_date": event.get("window_start", ""),
                "completion_upper_bound": event.get("window_end", "") if window_known else "",
                "completion_basis": "declared_event_end" if window_known else "unknown",
                "publication_upper_bound_utc": published,
                "source_id": "wikipedia_results",
                "source_revision": revision,
                "receipt_id": receipt_id,
                "overlap_unresolved": not window_known,
                "serve_block_status": "absent",
                "serve_source": "none",
            }
            if row_id in seen:
                earlier = seen[row_id]
                same = all(earlier[k] == row[k] for k in ("winner_side", "score", "status"))
                quarantine.append(
                    {
                        **base,
                        "kind": "duplicate" if same else "conflicting",
                        "detail": "identical row twice in one capture"
                        if same
                        else f"templates disagree: {earlier['score']!r} vs {row['score']!r}",
                    }
                )
                if not same:
                    results.remove(earlier)
                    seen.pop(row_id)
                continue
            seen[row_id] = row
            results.append(row)
            if match.status == "pending":
                pending += 1
            else:
                played += 1
        final_decided = any(
            r["round"] == "F" and r["winner_side"]
            for r in results
            if r["event_id"] == event["event_id"]
        )
        byes = sum(1 for note in notes if note["note"] == "bye_or_empty_slot")
        draw_size = int(event.get("draw_size") or 0)
        completeness.append(
            {
                "event_id": event["event_id"],
                "status": "complete" if final_decided and pending == 0 else "incomplete",
                "parsed_matches": played + pending,
                "played": played,
                "pending": pending,
                "bye_or_empty_slots": byes,
                "final_decided": final_decided,
                "declared_draw_size": draw_size,
                "generic_expectation_draw_size_minus_one": draw_size - 1 if draw_size else None,
                "note": "completeness is structural (final decided, no pending slot); the generic count is reported, never used as the criterion",
                "source_revision": revision,
            }
        )
    results.sort(
        key=lambda r: (r["tour"], r["event_id"], r["round"], r["player_a_id"], r["player_b_id"])
    )
    return results, quarantine, completeness


def attach_serve_windows(
    serve_rows: Iterable[Mapping[str, Any]], events: Iterable[Mapping[str, Any]], *, receipt_id: str
) -> list[dict[str, Any]]:
    """Give each event-anchored serve row a completion bound only when a declared event
    with the same tour and anchor exists; otherwise it stays overlap-unresolved (R19)."""
    by_anchor: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for event in events:
        if event.get("window_start"):
            by_anchor.setdefault((event["tour"], event["window_start"]), []).append(event)
    out = []
    for row in serve_rows:
        candidates = by_anchor.get((row["tour"], row["event_anchor"]), [])
        matched = [e for e in candidates if _same_event_name(e["name"], row["tournament_name"])]
        if len(matched) == 1 and matched[0].get("window_end"):
            event_id, bound, basis, unresolved = (
                matched[0]["event_id"],
                matched[0]["window_end"],
                "declared_event_end",
                False,
            )
        else:
            event_id, bound, basis, unresolved = "", "", "unknown", True
        out.append(
            {
                "tour": row["tour"],
                "player_id": row["player_id"],
                "event_anchor": row["event_anchor"],
                "model_event_date": row["event_anchor"],
                "date_basis": "event_anchor",
                "event_id": event_id,
                "completion_upper_bound": bound,
                "completion_basis": basis,
                "tournament_name": row["tournament_name"],
                "match_id": row["match_id"],
                "fields_present": " ".join(row["fields_present"]),
                "fields_missing": " ".join(row["fields_missing"]),
                "serve_block_valid": row["serve_block_valid"],
                "source_id": "tennisabstract_serve",
                "receipt_id": receipt_id,
                "retained_sha256": row["retained_sha256"],
                "overlap_unresolved": unresolved,
            }
        )
    out.sort(key=lambda r: (r["tour"], r["player_id"], r["event_anchor"], r["match_id"]))
    return out


def _same_event_name(declared: str, observed: str) -> bool:
    from tennislab.ratings.elo import normalize_name

    a, b = normalize_name(declared), normalize_name(observed)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def diff_results(
    previous: list[dict[str, str]], current: list[dict[str, Any]], quarantine: list[dict[str, Any]]
) -> dict[str, Any]:
    before = {row["row_id"]: row for row in previous}
    after = {row["row_id"]: row for row in current}
    compare = ("winner_side", "score", "status", "sets")
    diff: dict[str, list[dict[str, Any]]] = {name: [] for name in DIFF_CATEGORIES}
    for row_id, row in after.items():
        if row_id not in before:
            diff["added"].append(
                {"row_id": row_id, "event_id": row["event_id"], "round": row["round"]}
            )
        else:
            old = before[row_id]
            changed = {
                k: {"from": old[k], "to": str(row[k])} for k in compare if old[k] != str(row[k])
            }
            if changed:
                diff["revised"].append(
                    {
                        "row_id": row_id,
                        "event_id": row["event_id"],
                        "round": row["round"],
                        "changes": changed,
                        "previous_revision": old["source_revision"],
                        "revision": row["source_revision"],
                    }
                )
    for row_id, old in before.items():
        if row_id not in after:
            diff["removed"].append(
                {"row_id": row_id, "event_id": old["event_id"], "round": old["round"]}
            )
    for item in quarantine:
        if item["kind"] in diff:
            diff[item["kind"]].append(
                {k: item[k] for k in ("event_id", "round", "name_a", "name_b", "detail")}
            )
    return {"counts": {k: len(v) for k, v in diff.items()}, **diff}


def latest_version(config: LiveConfig) -> Path | None:
    pointer = config.sub("versions", "latest.json")
    if not pointer.is_file():
        return None
    record = read_json(pointer)
    version_id = safe_output_id(str(record["version_id"]), label="latest version id")
    directory = config.sub("versions", version_id)
    expected_manifest = record.get("manifest_sha256")
    if not expected_manifest:
        raise LiveError(f"latest version {directory.name}: pointer has no manifest hash")
    verify_version(directory, expected_manifest_sha256=expected_manifest)
    return directory


def _confined_version_path(root: Path, relative: str, *, label: str) -> Path:
    value = Path(str(relative))
    if value.is_absolute() or ".." in value.parts:
        raise LiveError(f"{label} path is not confined: {relative!r}")
    path = root / value
    current = root
    for part in value.parts:
        current = current / part
        if current.is_symlink():
            raise LiveError(f"{label} path passes through a symbolic link: {current}")
    return path


def verify_version(
    directory: Path, *, expected_manifest_sha256: str | None = None
) -> dict[str, Any]:
    manifest_path = directory / "manifest.json"
    if expected_manifest_sha256 is not None:
        require_nonempty_digest(
            expected_manifest_sha256, label=f"version {directory.name} manifest binding"
        )
        if not manifest_path.is_file() or sha256(manifest_path) != expected_manifest_sha256:
            raise LiveError(
                f"version {directory.name}: manifest hash mismatch from trusted binding"
            )
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "live-version-2":
        raise LiveError(
            f"version {directory.name}: unsupported schema {manifest.get('schema_version')!r}"
        )
    if manifest.get("version_id") != directory.name:
        raise LiveError(f"version {directory.name}: manifest names another version")
    for relative, digest in manifest["files"].items():
        path = _confined_version_path(directory, relative, label=f"version {directory.name}")
        if not path.is_file() or sha256(path) != digest:
            raise LiveError(f"version {directory.name}: {relative} does not hash-verify")
    bindings = manifest.get("acquisition_receipts")
    if not isinstance(bindings, dict) or set(bindings) != set(manifest.get("attempts", {})):
        raise LiveError(f"version {directory.name}: acquisition receipt bindings are incomplete")
    live_root = directory.parent.parent
    for source_id, binding in sorted(bindings.items()):
        if not isinstance(binding, dict):
            raise LiveError(f"version {directory.name}: invalid acquisition receipt binding")
        attempt_id = manifest["attempts"][source_id]
        if binding.get("source_id") != source_id or binding.get("attempt_id") != attempt_id:
            raise LiveError(
                f"version {directory.name}: acquisition receipt identity mismatch for {source_id}"
            )
        path = _confined_version_path(
            live_root,
            str(binding.get("path", "")),
            label=f"acquisition receipt {source_id}/{attempt_id}",
        )
        if not path.is_file() or sha256(path) != binding.get("sha256"):
            raise LiveError(
                f"version {directory.name}: acquisition receipt hash mismatch for {source_id}/{attempt_id}"
            )
        receipt = validate_attempt(path.parent)
        if (
            receipt.get("source_id") != source_id
            or receipt.get("attempt_id") != attempt_id
            or receipt.get("finished_utc") != binding.get("finished_utc")
        ):
            raise LiveError(
                f"version {directory.name}: acquisition receipt content mismatch for {source_id}/{attempt_id}"
            )
    return manifest


def write_version(
    config: LiveConfig,
    *,
    results: list[dict[str, Any]],
    serve: list[dict[str, Any]] | None,
    rankings: list[dict[str, Any]] | None,
    quarantine: list[dict[str, Any]],
    completeness: list[dict[str, Any]],
    attempts: dict[str, str],
    events: list[dict[str, Any]],
    note: str,
) -> Path:
    """Write a new version. Serve state and rankings are carried forward unchanged from the
    latest version when this update does not supply them (a results-only update never
    advances them)."""
    previous_dir = latest_version(config)
    previous_manifest = read_json(previous_dir / "manifest.json") if previous_dir else None
    previous_results = _read_csv(previous_dir / "results.csv") if previous_dir else []
    carried: dict[str, str] = {}
    if serve is None:
        serve = _read_csv(previous_dir / "serve_state.csv") if previous_dir else []
        carried["serve_state"] = previous_dir.name if previous_dir else "none"
    if rankings is None:
        rankings = _read_csv(previous_dir / "rankings.csv") if previous_dir else []
        carried["rankings"] = previous_dir.name if previous_dir else "none"
    # The content hash covers the normalized rows without their receipt reference, so an
    # identical capture yields the same content hash while still naming its own receipt.
    content = {
        "results": [{k: v for k, v in r.items() if k != "receipt_id"} for r in results],
        "serve": [{k: v for k, v in r.items() if k != "receipt_id"} for r in serve],
        "rankings": [{k: v for k, v in r.items() if k != "receipt_id"} for r in rankings],
    }
    content_hash = canonical_hash(content)
    now = utc_now()
    version_id = stamp_id(now, content_hash)
    directory = config.sub("versions", version_id)
    if directory.exists():
        raise LiveError(f"version directory already exists: {directory}")
    directory.mkdir(parents=True)
    files: dict[str, str] = {}
    files["results.csv"] = atomic_csv(directory / "results.csv", RESULT_COLUMNS, results)
    files["serve_state.csv"] = atomic_csv(directory / "serve_state.csv", SERVE_COLUMNS, serve)
    files["rankings.csv"] = atomic_csv(directory / "rankings.csv", RANKING_COLUMNS, rankings)
    files["quarantine/rows.csv"] = atomic_csv(
        directory / "quarantine" / "rows.csv", QUARANTINE_COLUMNS, quarantine
    )
    diff = diff_results(previous_results, results, quarantine)
    files["diff.json"] = atomic_json(directory / "diff.json", diff)
    files["completeness.json"] = atomic_json(directory / "completeness.json", completeness)
    files["events.json"] = atomic_json(directory / "events.json", events)
    no_change = (
        previous_manifest is not None and previous_manifest["content_sha256"] == content_hash
    )
    receipt_bindings = {
        source_id: bind_receipt(config, source_id, attempt_id)
        for source_id, attempt_id in sorted(attempts.items())
    }
    manifest = {
        "schema_version": "live-version-2",
        "version_id": version_id,
        "written_utc": iso_utc(now),
        "previous_version": previous_dir.name if previous_dir else None,
        "content_sha256": content_hash,
        "no_change": no_change,
        "attempts": attempts,
        "acquisition_receipts": receipt_bindings,
        "carried_forward": carried,
        "counts": {
            "results": len(results),
            "serve_state": len(serve),
            "rankings": len(rankings),
            "quarantine": len(quarantine),
        },
        "serve_frontier_observed": serve_frontier(serve),
        "serve_frontier_declared": {
            k: v
            for k, v in config.document.get("serve_frontier_declared", {}).items()
            if k in {"ATP", "WTA"}
        },
        "ranking_frontier_observed": ranking_frontier(rankings),
        "files": files,
        "live_config_sha256": config.sha256,
        "note": note,
    }
    atomic_json(directory / "manifest.json", manifest)
    verify_version(directory)
    replace_pointer(
        config.sub("versions", "latest.json"),
        {
            "version_id": version_id,
            "content_sha256": content_hash,
            "manifest_sha256": sha256(directory / "manifest.json"),
        },
    )
    return directory


def serve_frontier(serve: Iterable[Mapping[str, Any]]) -> dict[str, str | None]:
    out: dict[str, str | None] = {"ATP": None, "WTA": None}
    for row in serve:
        if str(row.get("overlap_unresolved")).lower() == "true" or not row.get(
            "completion_upper_bound"
        ):
            continue
        bound = str(row["completion_upper_bound"])
        if out.get(row["tour"]) is None or bound > str(out[row["tour"]]):
            out[row["tour"]] = bound
    return out


def ranking_frontier(rankings: Iterable[Mapping[str, Any]]) -> dict[str, str | None]:
    out: dict[str, str | None] = {"ATP": None, "WTA": None}
    for row in rankings:
        date = str(row["ranking_date"])
        if out.get(row["tour"]) is None or date > str(out[row["tour"]]):
            out[row["tour"]] = date
    return out


def load_version(directory: Path, *, expected_manifest_sha256: str | None = None) -> dict[str, Any]:
    manifest = verify_version(directory, expected_manifest_sha256=expected_manifest_sha256)
    return {
        "manifest": manifest,
        "results": _read_csv(directory / "results.csv"),
        "serve": _read_csv(directory / "serve_state.csv"),
        "rankings": _read_csv(directory / "rankings.csv"),
        "events": read_json(directory / "events.json"),
        "directory": directory,
    }
