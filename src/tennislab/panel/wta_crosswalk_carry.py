"""Carry the frozen WTA event crosswalk forward to the seasons it does not cover.

Stage ``event_carry_forward`` (WTA). Ported from the archive's
``references/WTA02_models/wta_carry_event_crosswalk.py``; there is no TIER01 counterpart
of this file (the ATP tour has :mod:`tennislab.panel.crosswalk_carry`), so nothing was
merged.

WTA02, declared rule 2. :mod:`tennislab.panel.wta_join` pairs a tennis-data workbook
block ``(Location, Tournament)`` with a mirror edition only through an accepted row of
the frozen WTA event crosswalk, and that file stops at 2024. This stage extends it for
the seasons after its horizon, mechanically:

tier A
    the block's exact ``(Location, Tournament)`` pair maps to the mirror tourney name its
    latest earlier ACCEPTED crosswalk edition mapped to, when the target season's mirror
    holds exactly one edition of that name;
tier B
    when no exact pair exists, the ``Location`` alone carries, provided that location
    mapped to exactly one distinct mirror tourney name across all accepted seasons and
    appears in exactly one block of the target season.

At most one block may claim a mirror edition: with two claimants the tier-A one wins if
it is alone in its tier, otherwise every claimant stays unresolved. A carried row is
``status = accepted_carried_forward``, takes the source edition's ``round_alignment``,
is not link-dependent, and so enters the primary identity tier with ``carried_forward``
provenance downstream -- the declared assumption. Everything else is listed with its
reason and row count.

No-op below the horizon: nothing is carried into a season the frozen crosswalk covers.

What changed from the archive revision: ``wta_sources`` is imported by name as
:mod:`tennislab.sources.wta_sources` instead of being loaded by path (its config entry
stays a declared binding, still resolved and hashed into ``inputs.sources_module``), and
``inputs.code`` is the package module's receipt instead of the archive file's path and
hash.

RESERVED WINDOW: downstream of the bridge, the declared outcome-access event; this stage
reads no outcome field. It reads only the event-identity columns of each workbook --
Location, Tournament, WTA number, Date, Tier, Court, Surface.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    code_receipt,
    declared_binding,
    read_config,
    read_csv_rows,
    relative_to_root,
    require_hash,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
    year_plan,
)
from tennislab.sources import wta_sources as sources

ACCEPTED = ("accepted", "accepted_split")
CARRIED_STATUS = "accepted_carried_forward"
CARRY_COLUMNS = (
    "carry_source_season",
    "carry_source_tourney_id",
    "carry_source_tourney_name",
    "carry_basis",
)
DRIVER_FILES = frozenset({"stdout.txt", "stderr.txt", "stage_manifest.json"})


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()[:10]
    return str(value).strip()


def workbook_blocks(path: Path, season: int) -> dict[tuple[str, str], dict[str, Any]]:
    """Per ``(Location, Tournament)`` block of one workbook: counts, numbers, dates, fields.

    Only the event-identity columns are read. Winner, loser, score and price columns are
    never touched here.
    """
    header, raw = sources._read_xlsx(str(path))
    index = {name: position for position, name in enumerate(header) if name}
    wanted = ("Location", "Tournament", "WTA", "Date", "Tier", "Court", "Surface")
    missing = [name for name in wanted if name not in index]
    if missing:
        raise ChainError(f"{path}: workbook lacks columns {missing}")
    blocks: dict[tuple[str, str], dict[str, Any]] = {}
    for values in raw:
        if sources._blank(values):
            continue
        cell = {
            name: (values[index[name]] if index[name] < len(values) else None) for name in wanted
        }
        key = (text(cell["Location"]), text(cell["Tournament"]))
        block = blocks.setdefault(
            key,
            {
                "rows": 0,
                "event_numbers": Counter(),
                "dates": [],
                "tiers": Counter(),
                "courts": Counter(),
                "surfaces": Counter(),
                "missing_dates": 0,
            },
        )
        block["rows"] += 1
        block["event_numbers"][text(cell["WTA"])] += 1
        date = sources._as_date(cell["Date"])
        if date is None:
            block["missing_dates"] += 1
        else:
            block["dates"].append(date)
        block["tiers"][text(cell["Tier"])] += 1
        block["courts"][text(cell["Court"])] += 1
        block["surfaces"][text(cell["Surface"])] += 1
    _ = season
    return blocks


def mirror_editions(
    panel_path: Path, seasons: set[int], norm: Any
) -> dict[int, dict[str, dict[str, Any]]]:
    """season -> normalized tourney_name -> {tourney_id: edition record}."""
    editions: dict[int, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    with panel_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                season = int(row["season"])
            except KeyError, TypeError, ValueError:
                continue
            if season not in seasons:
                continue
            record = editions[season][norm(row["tourney_name"])].setdefault(
                row["tourney_id"],
                {
                    "tourney_id": row["tourney_id"],
                    "tourney_name": row["tourney_name"],
                    "tourney_anchor_date": row.get("tourney_anchor_date", ""),
                    "surface": row.get("surface", ""),
                    "draw_size": row.get("draw_size", ""),
                    "tourney_level": row.get("tourney_level", ""),
                    "rows": 0,
                },
            )
            record["rows"] += 1
    return {season: dict(names) for season, names in editions.items()}


def build(output: Path, config_path: Path) -> dict[str, Any]:
    document = read_config(config_path)
    plan = year_plan(document)
    section = document.get("wta_carry_event_crosswalk")
    if not isinstance(section, dict):
        raise ChainError("configuration has no wta_carry_event_crosswalk object")

    sources_binding = declared_binding(section["sources_module"], label="sources_module")
    norm = sources.norm_name

    base_entry = section["base_event_crosswalk"]
    base_path = resolve_under_root(base_entry["path"], label="base_event_crosswalk")
    manifest_entry = section["event_map_manifest"]
    manifest_path = resolve_under_root(manifest_entry["path"], label="event_map_manifest")
    manifest_hash = require_hash(
        manifest_path, manifest_entry.get("sha256"), label="event_map_manifest"
    )
    bound = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    base_hash = require_hash(
        base_path, bound[base_path.name]["sha256"], label="base_event_crosswalk"
    )
    base_fields, base_rows = read_csv_rows(base_path)
    base_max_season = max(int(row["season"]) for row in base_rows)

    market_entry = section["market_manifest"]
    market_path = resolve_under_root(market_entry["path"], label="market_manifest")
    market_hash = require_hash(market_path, market_entry.get("sha256"), label="market_manifest")
    market_records = {
        int(record["year"]): record
        for record in json.loads(market_path.read_text(encoding="utf-8"))["records"]
        if record.get("tour") == "WTA" and record.get("year")
    }
    panel_path = (
        resolve_under_root(section["archive_panel_dir"], label="archive_panel_dir")
        / "source_panel.csv"
    )
    if not panel_path.is_file():
        raise ChainError(f"archive panel not found: {panel_path}")

    existing = (
        [item.name for item in output.iterdir() if item.name not in DRIVER_FILES]
        if output.exists()
        else []
    )
    if existing:
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}: {existing}")
    output.mkdir(parents=True, exist_ok=True)

    target_seasons = sorted(
        season for season in market_records if base_max_season < season <= plan.panel_end_year
    )

    # --- prior mappings from the frozen crosswalk's accepted rows ---------------------
    pair_prior: dict[tuple[str, str], dict[int, dict[str, str]]] = defaultdict(dict)
    location_prior: dict[str, dict[int, dict[str, str]]] = defaultdict(dict)
    location_names: dict[str, set[str]] = defaultdict(set)
    for row in base_rows:
        if row["status"] not in ACCEPTED:
            continue
        season = int(row["season"])
        pair_key = (norm(row["td_location"]), norm(row["td_tournament"]))
        pair_prior[pair_key][season] = row
        location_key = norm(row["td_location"])
        # A split season (two editions of one pair) offers no single location mapping.
        if (
            season in location_prior[location_key]
            and location_prior[location_key][season] is not row
        ):
            location_prior[location_key][season] = {"__ambiguous__": "true"}
        else:
            location_prior[location_key].setdefault(season, row)
        location_names[location_key].add(norm(row["tourney_name"]))

    editions = mirror_editions(panel_path, set(target_seasons), norm) if target_seasons else {}

    carried: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    blocks_by_season: dict[int, dict[tuple[str, str], dict[str, Any]]] = {}
    for season in target_seasons:
        workbook = resolve_under_root(market_records[season]["path"], label=f"workbook {season}")
        require_hash(workbook, market_records[season].get("sha256"), label=f"workbook {season}")
        blocks_by_season[season] = workbook_blocks(workbook, season)

    for season in target_seasons:
        blocks = blocks_by_season[season]
        location_counts = Counter(norm(location) for location, _ in blocks)
        candidates: list[dict[str, Any]] = []
        for (location, tournament), block in sorted(blocks.items()):
            record: dict[str, Any] = {
                "season": season,
                "td_location": location,
                "td_tournament": tournament,
                "td_rows": block["rows"],
                "td_event_numbers": sorted(block["event_numbers"]),
                "td_date_min": min(block["dates"]).isoformat() if block["dates"] else "",
                "td_date_max": max(block["dates"]).isoformat() if block["dates"] else "",
            }
            pair_key = (norm(location), norm(tournament))
            location_key = norm(location)
            prior: dict[str, str] | None = None
            basis = ""
            seasons_pair = sorted(
                (s for s in pair_prior.get(pair_key, {}) if s < season), reverse=True
            )
            if seasons_pair:
                prior = pair_prior[pair_key][seasons_pair[0]]
                basis = "carried_forward_tier_a_pair"
            else:
                names = location_names.get(location_key, set())
                seasons_loc = sorted(
                    (
                        s
                        for s, row in location_prior.get(location_key, {}).items()
                        if s < season and "__ambiguous__" not in row
                    ),
                    reverse=True,
                )
                if not names:
                    record["reason"] = "no_prior_accepted_edition_of_this_pair_or_location"
                    unresolved.append(record)
                    continue
                if len(names) != 1:
                    record["reason"] = (
                        "location_maps_to_more_than_one_mirror_tourney_name_in_the_frozen_crosswalk"
                    )
                    record["prior_tourney_names"] = sorted(names)
                    unresolved.append(record)
                    continue
                if location_counts[location_key] != 1:
                    record["reason"] = (
                        "location_appears_in_more_than_one_block_of_the_target_season"
                    )
                    unresolved.append(record)
                    continue
                if not seasons_loc:
                    record["reason"] = "no_unambiguous_prior_location_mapping"
                    unresolved.append(record)
                    continue
                prior = location_prior[location_key][seasons_loc[0]]
                basis = "carried_forward_tier_b_location"
            prior_name = prior["tourney_name"]
            found = editions.get(season, {}).get(norm(prior_name), {})
            record.update(
                {
                    "prior_season": int(prior["season"]),
                    "prior_tourney_id": prior["tourney_id"],
                    "prior_tourney_name": prior_name,
                    "carry_basis": basis,
                }
            )
            if not found:
                record["reason"] = "mirror_holds_no_edition_of_that_tourney_name_in_target_season"
                unresolved.append(record)
                continue
            if len(found) != 1:
                if len(record["td_event_numbers"]) > 1:
                    record["reason"] = "split_block_not_carried_mirror_holds_more_than_one_edition"
                else:
                    record["reason"] = "mirror_holds_more_than_one_edition_of_that_tourney_name"
                record["mirror_tourney_ids"] = sorted(found)
                unresolved.append(record)
                continue
            target = next(iter(found.values()))
            record.update(
                {
                    "tourney_id": target["tourney_id"],
                    "tourney_name": target["tourney_name"],
                    "mirror_tourney_date": target["tourney_anchor_date"],
                    "mirror_draw_size": target["draw_size"],
                    "mirror_level": target["tourney_level"],
                    "mirror_rows": target["rows"],
                    "surface_mirror": target["surface"],
                    "surface_td": block["surfaces"].most_common(1)[0][0]
                    if block["surfaces"]
                    else "",
                    "td_tier": block["tiers"].most_common(1)[0][0] if block["tiers"] else "",
                    "td_court": block["courts"].most_common(1)[0][0] if block["courts"] else "",
                    "round_alignment": prior.get("round_alignment") or "absolute_round_label",
                }
            )
            candidates.append(record)

        # one block per mirror edition
        claims: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in candidates:
            claims[record["tourney_id"]].append(record)
        for _tourney_id, claimants in claims.items():
            if len(claimants) == 1:
                carried.append(claimants[0])
                continue
            tier_a = [
                item for item in claimants if item["carry_basis"] == "carried_forward_tier_a_pair"
            ]
            keep = tier_a[0] if len(tier_a) == 1 else None
            for item in claimants:
                if item is keep:
                    carried.append(item)
                else:
                    item["reason"] = "ambiguous_duplicate_claim_on_one_mirror_edition"
                    item["other_claimants"] = [
                        f"{other['td_location']}|{other['td_tournament']}"
                        for other in claimants
                        if other is not item
                    ]
                    unresolved.append(item)

    carried.sort(key=lambda item: (item["season"], item["td_location"], item["td_tournament"]))

    # --- the extended crosswalk -------------------------------------------------------
    fields = list(base_fields) + [column for column in CARRY_COLUMNS if column not in base_fields]
    extended = output / "extended_wta_event_crosswalk.csv"
    with extended.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in base_rows:
            writer.writerow({**{column: "" for column in CARRY_COLUMNS}, **row})
        for item in carried:
            anchor = None
            try:
                anchor = dt.datetime.strptime(item["mirror_tourney_date"], "%Y%m%d").date()
            except TypeError, ValueError:
                pass
            gap = ""
            if anchor is not None and item["td_date_min"]:
                gap = (dt.date.fromisoformat(item["td_date_min"]) - anchor).days
            writer.writerow(
                {
                    **{field: "" for field in fields},
                    "season": item["season"],
                    "td_location": item["td_location"],
                    "td_tournament": item["td_tournament"],
                    "tourney_id": item["tourney_id"],
                    "tourney_name": item["tourney_name"],
                    "surface_td": item["surface_td"],
                    "surface_mirror": item["surface_mirror"],
                    "date_gap_days": gap,
                    "td_rows": item["td_rows"],
                    "mirror_rows": item["mirror_rows"],
                    "method": item["carry_basis"],
                    "status": CARRIED_STATUS,
                    "td_event_number": "|".join(item["td_event_numbers"]),
                    "td_tier": item["td_tier"],
                    "td_court": item["td_court"],
                    "td_date_min": item["td_date_min"],
                    "td_date_max": item["td_date_max"],
                    "mirror_tourney_date": item["mirror_tourney_date"],
                    "mirror_draw_size": item["mirror_draw_size"],
                    "mirror_level": item["mirror_level"],
                    "name_evidence": "carried_forward_declared_assumption",
                    "round_alignment": item["round_alignment"],
                    "depends_on_surname_link": "False",
                    "carry_source_season": item["prior_season"],
                    "carry_source_tourney_id": item["prior_tourney_id"],
                    "carry_source_tourney_name": item["prior_tourney_name"],
                    "carry_basis": item["carry_basis"],
                }
            )

    report = {
        "id": "WTA02-event-crosswalk-carry-forward",
        "status": "event_crosswalk_carried_forward",
        "design_paragraph": "WTA02.design.md, declared rule 2",
        "year_plan": plan.as_document(),
        "base_crosswalk_last_season": base_max_season,
        "target_seasons": target_seasons,
        "no_op": not carried,
        "base_rows": len(base_rows),
        "carried_rows": len(carried),
        "extended_rows": len(base_rows) + len(carried),
        "carried_by_season": dict(sorted(Counter(item["season"] for item in carried).items())),
        "carried_basis_counts": dict(
            sorted(Counter(item["carry_basis"] for item in carried).items())
        ),
        "td_rows_covered_by_season": {
            str(season): sum(item["td_rows"] for item in carried if item["season"] == season)
            for season in target_seasons
        },
        "td_rows_unresolved_by_season": {
            str(season): sum(item["td_rows"] for item in unresolved if item["season"] == season)
            for season in target_seasons
        },
        "blocks_by_season": {
            str(season): len(blocks_by_season[season]) for season in target_seasons
        },
        "carried": carried,
        "unresolved_blocks": unresolved,
        "unresolved_reason_counts": dict(
            sorted(Counter(item["reason"] for item in unresolved).items())
        ),
        "assumption": (
            "A carried mapping asserts that a tennis-data block names the same mirror tourney "
            "as the latest earlier accepted edition of its pair (tier A) or its location "
            "(tier B), and enters the primary identity tier. That is the declared rule, not "
            "a measurement of event identity."
        ),
        "inputs": {
            "base_event_crosswalk": {
                "path": relative_to_root(base_path),
                "sha256": base_hash,
            },
            "event_map_manifest": {
                "path": relative_to_root(manifest_path),
                "sha256": manifest_hash,
            },
            "market_manifest": {"path": relative_to_root(market_path), "sha256": market_hash},
            "sources_module": sources_binding,
            "archive_panel": {"path": relative_to_root(panel_path), "sha256": sha256(panel_path)},
            "code": code_receipt(__name__),
        },
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
                    "carried_basis_counts",
                    "td_rows_covered_by_season",
                    "td_rows_unresolved_by_season",
                    "unresolved_reason_counts",
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        document = read_config(args.config)
        plan = year_plan(document)
        section = document["wta_carry_event_crosswalk"]
        for name in ("base_event_crosswalk", "event_map_manifest", "sources_module"):
            entry = section[name]
            require_hash(
                resolve_under_root(entry["path"], label=name), entry.get("sha256"), label=name
            )
        print(json.dumps({"status": "dry_run_ok", "year_plan": plan.as_document()}, sort_keys=True))
        return 0
    build(resolve_output_under_root(args.output, label="output"), args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
