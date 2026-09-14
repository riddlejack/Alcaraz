"""Write one WTA match-format rule row per panel row from the declared era table.

Stage ``rule_mapping`` (WTA). Ported from the archive's
``references/WTA02_models/wta_rule_rows.py``; there is no TIER01 counterpart of this
file (the ATP tour has :mod:`tennislab.panel.rules`), so nothing was merged.

:mod:`tennislab.panel.rules` cannot serve this tour: that program *extends* an existing
rule mapping to later editions, and there is no WTA base mapping to extend -- SR02's
``rules.csv`` is 51,222 ATP rows keyed on ATP ``tourney_id``s. So the WTA rows are
generated from ``wta_rules.json``, whose eras are the event map's inventory of the
mirror's own deciding-set scores. That table travels with this module as the package
resource ``tennislab/panel/wta_rules.json``; a config that declares ``rule_config``
still reads and hash-verifies the file it names, and the resource is the default when it
does not.

Output schema is the ATP ``RULE_FIELDS`` exactly, because the SR02 replay reads it.

Rule assignment, and nothing else:

* ``tourney_level == "G"`` -- the era of that Slam for that season. A Slam is identified
  by its normalized ``tourney_name`` because the WTA mirror renumbers its Slam
  ``tourney_id``s in 2016; an unrecognized G-level name is **refused**, never defaulted.
* a level in ``ordinary_wta.levels`` with ``best_of == 3`` -- the ordinary tour rule.
* anything else -- refused, with a reason. A refused row gets no rule, so SR02 emits
  point probabilities and refuses that match's probability. Nothing is guessed.

Beside the rules it writes the evidence join the design owes: for every edition in the
panel, what the inventory actually observed about that edition's deciding sets, and
whether it corroborates, is silent on, or contradicts the era rule applied.

What changed from the archive revision: paths resolve through the workspace, the era
table is available as a package resource, and ``inputs.code`` is the package module's
receipt instead of the archive file's path and hash (so
``manifest_sha256_of_inputs``, which hashes that map, changes with it).

This program reads no serve count, no price and no label. The inventory it joins was
computed once, in the event-map folder, and is bound by hash.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_csv,
    atomic_json,
    canonical_hash,
    code_receipt,
    read_config,
    read_csv_rows,
    relative_to_root,
    require_hash,
    resolve_output_under_root,
    resolve_under_root,
    sha256_bytes,
    year_plan,
)

RULE_CONFIG_RESOURCE = "wta_rules.json"

RULE_FIELDS = (
    "source_key",
    "match_id",
    "source_season",
    "tourney_id",
    "round",
    "best_of",
    "rule_group",
    "rule_basis",
    "match_rule",
)
REFUSED_FIELDS = (
    "source_key",
    "match_id",
    "source_season",
    "tourney_id",
    "tourney_name",
    "tourney_level",
    "round",
    "best_of",
    "reason",
)
EVIDENCE_FIELDS = (
    "source_season",
    "tourney_id",
    "tourney_name",
    "tourney_level",
    "panel_rows",
    "rule_group",
    "deciding_mode",
    "deciding_tiebreak_at_games",
    "deciding_tiebreak_points",
    "inventory_observation",
    "inventory_basis",
    "longest_deciding_set_games",
    "evidence_relation",
)


def packaged_rule_config() -> tuple[dict[str, Any], dict[str, str]]:
    """The era table shipped with the package, and the binding to record for it."""
    payload = (resources.files(__package__) / RULE_CONFIG_RESOURCE).read_bytes()
    return json.loads(payload.decode("utf-8")), {
        "resource": f"{__package__}/{RULE_CONFIG_RESOURCE}",
        "sha256": sha256_bytes(payload),
    }


def normalized_name(value: str) -> str:
    return " ".join((value or "").strip().casefold().replace(".", " ").split())


def era_for(eras: list[list[Any]], season: int) -> list[Any] | None:
    for era in eras:
        if int(era[0]) <= season <= int(era[1]):
            return era
    return None


def deciding_set(era: list[Any]) -> dict[str, Any]:
    mode, at_games, points = era[2], era[3], era[4]
    return {
        "mode": mode,
        "tiebreak_at_games": None if at_games is None else int(at_games),
        "tiebreak_points": None if points is None else int(points),
    }


def match_rule_document(regular: Mapping[str, Any], deciding: Mapping[str, Any]) -> str:
    return json.dumps(
        {"sets_to_win": 2, "regular_set": dict(regular), "deciding_set": dict(deciding)},
        sort_keys=True,
        separators=(",", ":"),
    )


CARRY_SUFFIX = "_carried_forward"


def rule_for(
    config: Mapping[str, Any], row: Mapping[str, str], era_carry_from_year: int | None = None
) -> tuple[dict[str, str] | None, str, dict[str, Any] | None]:
    """(rule fields, reason, deciding set) for one panel row.

    WTA02, declared rule 2. With ``era_carry_from_year`` set, a season after the last
    declared era of a Slam takes that era when the era ends at ``era_carry_from_year``
    (assumption: no WTA final-set rule change after that season), and an ordinary tour
    row of such a season carries the same label on its basis. The rule group and basis
    say ``carried_forward``, so a carried row is never mistaken for a declared one.
    Without the setting the behaviour is WTA01's: a season outside every declared era is
    refused.
    """
    season = int(row["source_season"])
    level = row["tourney_level"].strip()
    best_of = int(row["best_of"])
    regular = config["regular_set"]
    carried_season = era_carry_from_year is not None and season > int(era_carry_from_year)
    carry_note = (
        f";carried_forward_from_{era_carry_from_year}_edition_declared_assumption_WTA02"
        if carried_season
        else ""
    )
    if best_of != int(config["ordinary_wta"]["best_of"]):
        return None, f"unsupported_best_of_{best_of}", None
    if level == "G":
        code = config["grand_slam_names"].get(normalized_name(row["tourney_name"]))
        if code is None:
            return (
                None,
                f"unrecognized_grand_slam_name_{normalized_name(row['tourney_name'])}",
                None,
            )
        slam = config["grand_slams"][code]
        era = era_for(slam["eras"], season)
        carried = False
        if era is None and carried_season:
            last = max(slam["eras"], key=lambda item: int(item[1]))
            if int(last[1]) == int(era_carry_from_year):
                era, carried = last, True
        if era is None:
            return None, f"no_declared_era_for_{code}_{season}", None
        deciding = deciding_set(era)
        return (
            {
                "rule_group": f"grand_slam_{code}_{era[0]}_{era[1]}"
                + (CARRY_SUFFIX if carried else ""),
                "rule_basis": era[5] + (carry_note if carried else ""),
                "match_rule": match_rule_document(regular, deciding),
            },
            "",
            deciding,
        )
    ordinary = config["ordinary_wta"]
    if level in ordinary["levels"]:
        deciding = ordinary["deciding_set"]
        return (
            {
                "rule_group": "ordinary_wta_best_of_three"
                + (CARRY_SUFFIX if carried_season else ""),
                "rule_basis": ordinary["basis"] + carry_note,
                "match_rule": match_rule_document(regular, deciding),
            },
            "",
            dict(deciding),
        )
    return None, f"no_tour_default_for_level_{level}", None


def build(
    config: Mapping[str, Any],
    panel_rows: list[dict[str, str]],
    inventory: Mapping[str, dict[str, str]],
    era_carry_from_year: int | None = None,
) -> dict[str, Any]:
    rules: list[dict[str, str]] = []
    refused: list[dict[str, str]] = []
    editions: dict[str, dict[str, Any]] = {}
    for row in panel_rows:
        assignment, reason, deciding = rule_for(config, row, era_carry_from_year)
        base = {
            "source_key": row["source_key"],
            "match_id": row["match_id"],
            "source_season": row["source_season"],
            "tourney_id": row["tourney_id"],
            "round": row["round"],
            "best_of": row["best_of"],
        }
        if assignment is None:
            refused.append(
                {
                    **base,
                    "tourney_name": row["tourney_name"],
                    "tourney_level": row["tourney_level"],
                    "reason": reason,
                }
            )
            continue
        rules.append({**base, **assignment})
        edition = editions.setdefault(
            row["tourney_id"],
            {
                "source_season": row["source_season"],
                "tourney_id": row["tourney_id"],
                "tourney_name": row["tourney_name"],
                "tourney_level": row["tourney_level"],
                "panel_rows": 0,
                "rule_group": assignment["rule_group"],
                "deciding_mode": deciding["mode"],
                "deciding_tiebreak_at_games": ""
                if deciding["tiebreak_at_games"] is None
                else deciding["tiebreak_at_games"],
                "deciding_tiebreak_points": ""
                if deciding["tiebreak_points"] is None
                else deciding["tiebreak_points"],
            },
        )
        edition["panel_rows"] += 1

    evidence: list[dict[str, Any]] = []
    for tourney_id, edition in sorted(editions.items()):
        observed = inventory.get(tourney_id)
        inferred = (observed or {}).get("inferred_final_set_rule", "edition_absent_from_inventory")
        mode = edition["deciding_mode"]
        at_games = edition["deciding_tiebreak_at_games"]
        ran_past_six_all = inferred in {
            "advantage_deciding_set",
            "deciding_set_extends_past_6_all_cap_unknown",
        }
        if inferred.startswith("not_observable") or inferred == "edition_absent_from_inventory":
            relation = "silent_era_continuity_assumption"
        elif ran_past_six_all:
            # The deciding sets ran past 6-all, so the rule is not a tiebreak *at* 6-all.
            # That is equally consistent with an advantage set and with a cap above 6-all
            # (Wimbledon's announced 12-all), and the inventory itself says the cap is
            # unknown, so a cap above 6-all is corroborated in position, not contradicted.
            if mode == "advantage":
                relation = "corroborates"
            elif mode == "tiebreak" and at_games != "" and int(at_games) > 6:
                relation = "corroborates_position_cap_from_a_retained_announcement"
            else:
                relation = "contradicts"
        elif inferred == "deciding_set_tiebreak_at_6_all_length_unknown":
            relation = (
                "corroborates_position_length_assumed"
                if mode == "tiebreak" and at_games != "" and int(at_games) == 6
                else "contradicts"
            )
        else:
            relation = "contradicts"
        evidence.append(
            {
                **edition,
                "inventory_observation": inferred,
                "inventory_basis": (observed or {}).get("inference_basis", ""),
                "longest_deciding_set_games": (observed or {}).get(
                    "longest_deciding_set_games", ""
                ),
                "evidence_relation": relation,
            }
        )
    rules.sort(key=lambda row: (int(row["source_season"]), row["tourney_id"], row["source_key"]))
    return {"rules": rules, "refused": refused, "evidence": evidence}


def run(config_path: Path) -> dict[str, Any]:
    document = read_config(config_path)
    plan = year_plan(document)
    section = document.get("wta_rule_rows")
    if not isinstance(section, dict):
        raise ChainError("configuration has no wta_rule_rows object")

    rule_config_entry = section.get("rule_config")
    if rule_config_entry is None:
        config, rule_config_binding = packaged_rule_config()
    else:
        rule_config_path = resolve_under_root(rule_config_entry["path"], label="rule_config")
        rule_config_binding = {
            "path": relative_to_root(rule_config_path),
            "sha256": require_hash(
                rule_config_path, rule_config_entry.get("sha256"), label="rule_config"
            ),
        }
        config = json.loads(rule_config_path.read_text(encoding="utf-8"))
    panel_path = resolve_under_root(section["panel"]["path"], label="panel")
    panel_hash = require_hash(panel_path, section["panel"].get("sha256"), label="panel")
    inventory_path = resolve_under_root(section["rule_inventory"]["path"], label="rule_inventory")
    inventory_hash = require_hash(
        inventory_path, section["rule_inventory"].get("sha256"), label="rule_inventory"
    )
    output_dir = resolve_output_under_root(section["output_dir"], label="output_dir")

    # Any retained rule source the era table cites is re-hashed here, so an era that
    # claims a published announcement cannot drift away from the bytes it claims.
    retained = {}
    for name, entry in (config.get("retained_sources") or {}).items():
        path = resolve_under_root(entry["path"], label=f"retained source {name}")
        retained[name] = {
            "path": relative_to_root(path),
            "sha256": require_hash(path, entry.get("sha256"), label=f"retained source {name}"),
        }
    _, panel_rows = read_csv_rows(panel_path)
    _, inventory_rows = read_csv_rows(inventory_path)
    inventory = {row["tourney_id"]: row for row in inventory_rows}

    seasons = {int(row["source_season"]) for row in panel_rows}
    if seasons and max(seasons) > plan.panel_end_year:
        raise ChainError(
            f"panel reaches {max(seasons)} beyond panel_end_year {plan.panel_end_year}"
        )
    era_carry_from_year = section.get("era_carry_from_year")
    if era_carry_from_year is not None:
        era_carry_from_year = int(era_carry_from_year)
        if era_carry_from_year >= plan.panel_end_year:
            raise ChainError(
                f"era_carry_from_year {era_carry_from_year} must precede panel_end_year "
                f"{plan.panel_end_year}"
            )

    result = build(config, panel_rows, inventory, era_carry_from_year)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    silent = [
        row
        for row in result["evidence"]
        if row["evidence_relation"] == "silent_era_continuity_assumption"
    ]
    outputs = {
        "rules.csv": atomic_csv(output_dir / "rules.csv", RULE_FIELDS, result["rules"]),
        "rule_rows_refused.csv": atomic_csv(
            output_dir / "rule_rows_refused.csv", REFUSED_FIELDS, result["refused"]
        ),
        "rule_evidence_by_edition.csv": atomic_csv(
            output_dir / "rule_evidence_by_edition.csv", EVIDENCE_FIELDS, result["evidence"]
        ),
        "rule_editions_without_observed_evidence.csv": atomic_csv(
            output_dir / "rule_editions_without_observed_evidence.csv", EVIDENCE_FIELDS, silent
        ),
    }
    manifest = {
        "id": "WTA01-rule-rows",
        "tour": "WTA",
        "status": "era_rule_rows_from_the_event_map_inventory",
        "year_plan": plan.as_document(),
        "inputs": {
            "rule_config": rule_config_binding,
            "retained_rule_sources": retained,
            "panel": {"path": relative_to_root(panel_path), "sha256": panel_hash},
            "rule_inventory": {
                "path": relative_to_root(inventory_path),
                "sha256": inventory_hash,
            },
            "code": code_receipt(__name__),
        },
        "panel_rows": len(panel_rows),
        "total_rule_rows": len(result["rules"]),
        "era_carry_from_year": era_carry_from_year,
        "carried_rule_rows": sum(
            1 for row in result["rules"] if row["rule_group"].endswith(CARRY_SUFFIX)
        ),
        "carried_rule_rows_by_season": dict(
            sorted(
                Counter(
                    row["source_season"]
                    for row in result["rules"]
                    if row["rule_group"].endswith(CARRY_SUFFIX)
                ).items()
            )
        ),
        "refused_rows": len(result["refused"]),
        "refusal_reason_counts": dict(
            sorted(Counter(row["reason"] for row in result["refused"]).items())
        ),
        "rule_group_counts": dict(
            sorted(Counter(row["rule_group"] for row in result["rules"]).items())
        ),
        "distinct_match_rules": dict(
            sorted(Counter(row["match_rule"] for row in result["rules"]).items())
        ),
        "editions": len(result["evidence"]),
        "evidence_relation_counts": dict(
            sorted(Counter(row["evidence_relation"] for row in result["evidence"]).items())
        ),
        "editions_without_observed_evidence": len(silent),
        "declared_assumptions": config["declared_assumptions"],
        "information_set_limit": config["information_set_limit"],
        "outputs": outputs,
        "limits": [
            "Eras are the event map's reading of the mirror's deciding-set scores, not a "
            "retained WTA rulebook or announcement.",
            "Deciding-tiebreak length is assumed (7 at tour level, 10 at a Slam from its "
            "harmonisation year); the scores cannot distinguish the two.",
            "A refused row has no rule, so SR02 refuses that match's probability.",
        ],
    }
    manifest["manifest_sha256_of_inputs"] = canonical_hash(manifest["inputs"])
    atomic_json(output_dir / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        document = read_config(args.config)
        plan = year_plan(document)
        section = document["wta_rule_rows"]
        for name in ("rule_config", "panel", "rule_inventory"):
            entry = section.get(name)
            if entry is None:
                continue
            require_hash(
                resolve_under_root(entry["path"], label=name), entry.get("sha256"), label=name
            )
        print(json.dumps({"status": "dry_run_ok", "year_plan": plan.as_document()}, sort_keys=True))
        return 0
    manifest = run(args.config)
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "panel_rows",
                    "total_rule_rows",
                    "refused_rows",
                    "rule_group_counts",
                    "evidence_relation_counts",
                    "editions_without_observed_evidence",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
