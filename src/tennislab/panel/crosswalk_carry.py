"""Carry the MULTI01 event crosswalk forward to the seasons it does not cover.

Stage ``event_carry_forward`` (ATP). Ported from the archive's
``TIER01_models/carry_event_crosswalk.py`` (revision 7); the ``WTA02_models`` copy of
that file is byte-identical, so there is one revision and nothing to merge. The WTA tour
has its own carry-forward program (:mod:`tennislab.panel.wta_crosswalk_carry`).

What changed: ``join_candidates.normalized`` is imported by name from
:mod:`tennislab.panel.join` instead of being loaded by path, and the running code's
receipt moves out of the report's ``inputs`` map (which stays a pure path -> sha256 map
of the three data inputs) into its own ``code`` field.

``prepare_panel.qualify`` admits a *weak-branch* candidate row
(``candidate_q4_unique_pair_round_date_event_unmapped``) only when the qualified event
crosswalk carries a row for that ``(season, market_location, market_tournament)`` whose
``archive_tourney_id`` is the one the join selected. That file stops at 2024, so this
stage carries each event's latest mapped edition forward, per the design's
"Event qualification" paragraph, and nothing else.

The rule, per ``(market_location, market_tournament)`` pair seen in a season after the
last season the base crosswalk covers:

 1. **Prior mapping.** Walk back to the latest earlier season in which one of the three
    named paths mapped that pair to a mirror tourney: the MULTI01 crosswalk (an
    accepting row for that season), CH01's pins (``pinned_ch01_event``), or the
    exact-name path (``event_name_exact_normalized``, ``event_code_exact``). A carried
    row is never itself prior evidence.
 2. **Target edition.** The mirror must hold exactly one edition of *that tourney name*
    in the target season, matched on the name normalized exactly as
    :func:`tennislab.panel.join.normalized` does.
 3. **Carried row.** One crosswalk row for ``(target season, location, tournament)`` ->
    that season's ``tourney_id``, ``final_recommendation = proposed_accept``, carrying
    the source season and the evidence path it came from.

**No-op below the crosswalk's own horizon.** Nothing is carried into a season at or
before the last season the base crosswalk covers, so a chain whose ``panel_end_year`` is
2024 emits an extended file whose rows are the base file's rows, in order, unchanged.

RESERVED WINDOW. This stage runs downstream of the panel build and the join, the
declared outcome-access events. It reads event names, mirror edition names and
classifications; it reads no outcome field.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    code_receipt,
    read_config,
    relative_to_root,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
)
from tennislab.panel.join import normalized

DEFAULT_BASE_CROSSWALK = "work/MULTI01_event_crosswalk/qualified_event_crosswalk.csv"
# The three strong paths `join.event_evidence` can return; a weak path
# (`event_name_containment`, `event_unmapped`) is precisely the case that needs the
# crosswalk, so it cannot also serve as the evidence that qualifies the prior edition.
STRONG_EVIDENCE = frozenset(
    {"pinned_ch01_event", "event_code_exact", "event_name_exact_normalized"}
)
ACCEPTING = frozenset({"proposed_accept", "proposed_accept_event_identity_only"})
WEAK_CLASSIFICATION = "candidate_q4_unique_pair_round_date_event_unmapped"
CARRY_COLUMNS = ("carry_source_season", "carry_source_basis", "carry_evidence_path")
DRIVER_FILES = frozenset({"stdout.txt", "stderr.txt", "stage_manifest.json"})


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def event_key(season: Any, location: str, tournament: str) -> tuple[int, str, str]:
    return int(season), location.strip(), tournament.strip()


def mirror_editions(panel_path: Path, seasons: set[int]) -> dict[tuple[int, str], dict[str, str]]:
    """``(season, normalized tourney_name) -> {tourney_id: tourney_name}`` for ``seasons``.

    The panel is large and carries a ``raw_row_json`` column; it is streamed and only the
    three identity fields of the wanted seasons are kept.
    """
    editions: dict[tuple[int, str], dict[str, str]] = defaultdict(dict)
    with panel_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                season = int(row["season"])
            except KeyError, TypeError, ValueError:
                continue
            if season not in seasons:
                continue
            editions[(season, normalized(row["tourney_name"]))][row["tourney_id"]] = row[
                "tourney_name"
            ]
    return dict(editions)


def build(output: Path, config: Mapping[str, Any] | None) -> dict[str, Any]:
    document = config or {}
    section = document.get("carry_event_crosswalk", document)
    plan = document.get("year_plan", {})
    if "panel_end_year" in plan:
        panel_end_year = int(plan["panel_end_year"])
    else:
        panel_end_year = int(section["panel_end_year"])

    base_path = resolve_under_root(
        section.get("base_event_crosswalk", DEFAULT_BASE_CROSSWALK), label="base_event_crosswalk"
    )
    candidates_path = (
        resolve_under_root(section["candidates_dir"], label="candidates_dir")
        / "common_panel_candidates.csv"
    )
    panel_path = (
        resolve_under_root(section["archive_panel_dir"], label="archive_panel_dir")
        / "source_panel.csv"
    )
    for label, path in (
        ("base_event_crosswalk", base_path),
        ("candidates", candidates_path),
        ("source_panel", panel_path),
    ):
        if not path.is_file():
            raise ChainError(f"carry_event_crosswalk input missing: {label}: {path}")

    # The driver creates the stage directory and writes `stdout.txt`, `stderr.txt` and
    # `stage_manifest.json` into it itself, so those three are not "existing output".
    existing = (
        [item.name for item in output.iterdir() if item.name not in DRIVER_FILES]
        if output.exists()
        else []
    )
    if existing:
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}: {existing}")
    output.mkdir(parents=True, exist_ok=True)

    base_fields, base_rows = read_rows(base_path)
    base_by_key = {
        event_key(row["season"], row["market_location"], row["market_tournament"]): row
        for row in base_rows
    }
    base_max_season = max(int(row["season"]) for row in base_rows)

    # --- the join's own view of every event, per season ------------------------------
    blocks: dict[tuple[int, str, str], dict[str, Any]] = {}
    with candidates_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = event_key(row["market_season"], row["market_location"], row["market_tournament"])
            block = blocks.setdefault(
                key,
                {
                    "rows": 0,
                    "weak_rows": 0,
                    "tourney_names": Counter(),
                    "tourney_ids": Counter(),
                    "evidence": Counter(),
                    "strong_rows": 0,
                },
            )
            block["rows"] += 1
            if row["classification"] == WEAK_CLASSIFICATION:
                block["weak_rows"] += 1
            block["tourney_names"][row["archive_tourney_name"]] += 1
            block["tourney_ids"][row["archive_tourney_id"]] += 1
            block["evidence"][row["event_evidence"]] += 1
            if row["event_evidence"] in STRONG_EVIDENCE:
                block["strong_rows"] += 1

    # --- every prior mapping the three named paths supply ----------------------------
    # `(location, tournament) -> season -> mapping`. The MULTI01 crosswalk contributes
    # its own accepting rows; the join's candidate output contributes an edition its
    # *strong* paths resolved. A weak-branch edition contributes nothing, which is why a
    # carried 2025 mapping cannot then qualify 2026.
    prior_mappings: dict[tuple[str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    disagreements: dict[tuple[int, str, str], dict[str, Any]] = {}

    def offer(key: tuple[int, str, str], tourney_id: str, name: str, basis: str) -> None:
        season, location, tournament = key
        held = prior_mappings[(location, tournament)].get(season)
        if held is None:
            prior_mappings[(location, tournament)][season] = {
                "archive_tourney_id": tourney_id,
                "archive_tourney_name": name,
                "basis": basis,
            }
            return
        if normalized(held["archive_tourney_name"]) != normalized(name):
            disagreements[key] = {
                "held": held["archive_tourney_name"],
                "offered": name,
                "held_basis": held["basis"],
                "offered_basis": basis,
            }
            prior_mappings[(location, tournament)].pop(season, None)

    for row in base_rows:
        if row["final_recommendation"] not in ACCEPTING:
            continue
        offer(
            event_key(row["season"], row["market_location"], row["market_tournament"]),
            row["archive_tourney_id"],
            row["archive_tourney_name"],
            "multi01_qualified_event_crosswalk",
        )
    for key, block in blocks.items():
        if not block["strong_rows"] or len(block["tourney_names"]) != 1:
            continue
        offer(
            key,
            block["tourney_ids"].most_common(1)[0][0],
            next(iter(block["tourney_names"])),
            "|".join(sorted(name for name in block["evidence"] if name in STRONG_EVIDENCE)),
        )

    target_seasons = sorted(
        {season for season, _, _ in blocks if base_max_season < season <= panel_end_year}
    )
    editions = mirror_editions(panel_path, set(target_seasons)) if target_seasons else {}

    # --- carry ------------------------------------------------------------------------
    carried: list[dict[str, Any]] = []
    unqualified: list[dict[str, Any]] = []
    evidence_path = relative_to_root(candidates_path)

    for key in sorted(blocks):
        season, location, tournament = key
        if season not in target_seasons:
            continue
        block = blocks[key]
        record: dict[str, Any] = {
            "season": season,
            "market_location": location,
            "market_tournament": tournament,
            "candidate_rows": block["rows"],
            "weak_branch_rows": block["weak_rows"],
        }
        if key in base_by_key:
            record["reason"] = "already_in_base_crosswalk"
            unqualified.append(record)
            continue

        held = prior_mappings.get((location, tournament), {})
        earlier_seasons = sorted((s for s in held if s < season), reverse=True)
        if not earlier_seasons:
            record["reason"] = "no_prior_mapped_edition_of_this_event_name"
            record["seasons_seen_in_the_join"] = sorted(
                s for s, loc, tour in blocks if (loc, tour) == (location, tournament)
            )
            record["mapping_disagreements"] = [
                {"season": s, **detail}
                for (s, loc, tour), detail in disagreements.items()
                if (loc, tour) == (location, tournament)
            ]
            unqualified.append(record)
            continue
        prior_season = earlier_seasons[0]
        prior = held[prior_season]
        prior_name = prior["archive_tourney_name"]
        prior_id = prior["archive_tourney_id"]
        basis = prior["basis"]
        record["prior_season"] = prior_season
        record["prior_tourney_name"] = prior_name
        record["carry_source_basis"] = basis

        found = editions.get((season, normalized(prior_name)), {})
        if not found:
            record["reason"] = "mirror_holds_no_edition_of_that_tourney_in_target_year"
            unqualified.append(record)
            continue
        if len(found) != 1:
            record["reason"] = "mirror_holds_more_than_one_edition_of_that_tourney_name"
            record["mirror_tourney_ids"] = sorted(found)
            unqualified.append(record)
            continue
        target_id, target_name = next(iter(found.items()))

        carried.append(
            {
                "season": season,
                "market_location": location,
                "market_tournament": tournament,
                "archive_tourney_id": target_id,
                "archive_tourney_name": target_name,
                "carry_source_season": prior_season,
                "carry_source_tourney_id": prior_id,
                "carry_source_tourney_name": prior_name,
                "carry_source_basis": basis,
                "carry_evidence_path": evidence_path,
                "candidate_rows": block["rows"],
                "weak_branch_rows": block["weak_rows"],
                # The carried id must be the one the join actually selected for these
                # rows, or `prepare.qualify` rejects them anyway; report both.
                "weak_rows_on_carried_tourney_id": sum(
                    count
                    for tourney_id, count in block["tourney_ids"].items()
                    if tourney_id == target_id
                ),
                "candidate_tourney_ids": dict(block["tourney_ids"]),
            }
        )

    # --- the extended crosswalk -------------------------------------------------------
    fields = list(base_fields) + [c for c in CARRY_COLUMNS if c not in base_fields]
    extended = output / "extended_event_crosswalk.csv"
    with extended.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in base_rows:
            writer.writerow({**{c: "" for c in CARRY_COLUMNS}, **row})
        for item in carried:
            writer.writerow(
                {
                    **{field: "" for field in fields},
                    "season": item["season"],
                    "market_location": item["market_location"],
                    "market_tournament": item["market_tournament"],
                    "archive_tourney_id": item["archive_tourney_id"],
                    "archive_tourney_name": item["archive_tourney_name"],
                    "evidence_status": "carried_forward_prior_edition_mapping",
                    "proposed_action": (
                        "carry the prior edition's mirror tourney into this season's "
                        "edition of the same tourney name"
                    ),
                    "final_recommendation": "proposed_accept",
                    "final_confidence": "carried_forward_declared_assumption",
                    "final_evidence": (
                        f"{item['carry_source_basis']} on the {item['carry_source_season']} "
                        f"edition -> {item['carry_source_tourney_id']} "
                        f"({item['carry_source_tourney_name']})"
                    ),
                    "carry_source_season": item["carry_source_season"],
                    "carry_source_basis": item["carry_source_basis"],
                    "carry_evidence_path": item["carry_evidence_path"],
                }
            )

    still_unqualified = [item for item in unqualified if item["weak_branch_rows"]]
    report = {
        "status": "event_crosswalk_carried_forward",
        "design_paragraph": "CONFIRM2026.design.md, Procedures frozen, Event qualification",
        "panel_end_year": panel_end_year,
        "base_crosswalk_last_season": base_max_season,
        "target_seasons": target_seasons,
        "no_op": not carried,
        "base_rows": len(base_rows),
        "carried_rows": len(carried),
        "extended_rows": len(base_rows) + len(carried),
        "carried_by_season": dict(Counter(item["season"] for item in carried)),
        "carried_basis_counts": dict(Counter(item["carry_source_basis"] for item in carried)),
        "weak_branch_rows_covered_by_season": {
            str(season): sum(
                item["weak_rows_on_carried_tourney_id"]
                for item in carried
                if item["season"] == season
            )
            for season in target_seasons
        },
        "weak_branch_rows_still_unqualified_by_season": {
            str(season): sum(
                item["weak_branch_rows"] for item in still_unqualified if item["season"] == season
            )
            for season in target_seasons
        },
        "carried": carried,
        "unqualified_events": unqualified,
        "unqualified_reason_counts": dict(Counter(item["reason"] for item in unqualified)),
        "assumption": (
            "A carried mapping is written as proposed_accept, so its rows enter the "
            "primary identity tier. That is the declared consequence of the design's "
            "carry-forward paragraph, not a measurement of the event's identity."
        ),
        "inputs": {
            relative_to_root(path): sha256(path)
            for path in (base_path, candidates_path, panel_path)
        },
        "code": code_receipt(__name__),
        "outputs": {extended.name: sha256(extended)},
    }
    atomic_json(output / "carry_forward_report.json", report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "no_op",
                    "base_rows",
                    "carried_rows",
                    "extended_rows",
                    "carried_by_season",
                    "weak_branch_rows_covered_by_season",
                    "weak_branch_rows_still_unqualified_by_season",
                    "unqualified_reason_counts",
                )
            },
            sort_keys=True,
        )
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="resolve and check the inputs only")
    args = parser.parse_args(argv)
    document = read_config(args.config)
    if args.dry_run:
        section = document.get("carry_event_crosswalk", document)
        resolved = {
            "base_event_crosswalk": resolve_under_root(
                section.get("base_event_crosswalk", DEFAULT_BASE_CROSSWALK),
                label="base_event_crosswalk",
            ),
            "candidates_dir": resolve_under_root(section["candidates_dir"], label="candidates_dir"),
            "archive_panel_dir": resolve_under_root(
                section["archive_panel_dir"], label="archive_panel_dir"
            ),
        }
        missing = [name for name, path in resolved.items() if not path.exists()]
        print(
            json.dumps(
                {
                    "status": "dry_run_ok" if not missing else "dry_run_inputs_missing",
                    "missing": missing,
                    "inputs": {name: relative_to_root(path) for name, path in resolved.items()},
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    build(resolve_output_under_root(args.output, label="output"), document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
