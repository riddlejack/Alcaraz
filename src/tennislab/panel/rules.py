"""Extend the SR02 match-format rule mapping to new event editions by carry-forward.

Stage ``rule_mapping`` (ATP). Ported from the archive's
``TIER01_models/carry_rule_rows.py``; the ``WTA02_models`` copy of that file is
byte-identical, so there is one revision and nothing to merge. The WTA tour has no base
mapping to extend and generates its rule rows instead
(:mod:`tennislab.panel.wta_rules`).

Why this exists. SR02's rule derivation and ``experiments/SR02.rules.json`` are both
closed at 2024, so without new rows SR02 emits point probabilities and *refuses* the
match probability for 2025/2026. The design declares the resolution in advance: carry
each event's latest edition rule row forward, and give an unknown new event the tour
default for its level. This program does that and nothing else. It never invents a rule
era, never reads a score, a status, a serve count or an outcome, and writes a per-row
receipt for every rule it did not inherit from a real carry-source edition.

Matching, in this order, stopping at the first that resolves:

 1. ``event_code`` -- the ``tourney_id`` suffix (``2026-560`` -> ``560``) equals a
    carry-source edition's suffix. This is the mirror's event identifier and is stable
    across editions.
 2. ``tourney_name`` -- the normalized event name equals exactly one carry-source name.
    Used when the archive renumbers an event.

A code that resolves to more than one carry-source name, or a name that resolves to more
than one code, is not carried: it goes to the default file with
``reason=ambiguous_<basis>``.

Tour default, used only for an event with no carry-source edition: an ordinary level
with ``best_of == 3`` takes the config's ordinary rule; ``tourney_level == "G"`` is
**refused**, and so is anything else. A refused row has no rule, so SR02 refuses that
match's probability rather than pricing it under a guess.

What changed from the archive revision: paths resolve through the workspace, and
``manifest.inputs.code`` is the package module's receipt instead of the archive file's
path and hash (so ``manifest_sha256_of_inputs``, which hashes that map, changes with it).

RESERVED WINDOW. The carry-forward reads the extended panel, whose 2025/2026 rows exist
only after the panel build has read those seasons. It is downstream of that exposure
event, not the event itself; it uses only ``(source_season, tourney_id, tourney_name,
tourney_level, round, best_of, source_key, match_id)``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
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
    resolve_under_root,
    year_plan,
)

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
CARRIED_FIELDS = (
    "source_key",
    "match_id",
    "source_season",
    "tourney_id",
    "tourney_name",
    "tourney_level",
    "round",
    "best_of",
    "carry_basis",
    "carried_from_source_season",
    "carried_from_tourney_id",
    "carried_from_tourney_name",
    "rule_group",
    "rule_basis",
    "match_rule",
)
DEFAULT_FIELDS = (
    "source_key",
    "match_id",
    "source_season",
    "tourney_id",
    "tourney_name",
    "tourney_level",
    "round",
    "best_of",
    "reason",
    "rule_group",
    "rule_basis",
    "match_rule",
)
PANEL_KEYS = (
    "source_key",
    "match_id",
    "source_season",
    "tourney_id",
    "tourney_name",
    "tourney_level",
    "round",
    "best_of",
)


def normalized_name(value: str) -> str:
    return " ".join((value or "").strip().casefold().replace("-", " ").split())


def event_code(tourney_id: str) -> str:
    text = (tourney_id or "").strip()
    if "-" not in text:
        raise ChainError(f"tourney_id has no edition prefix: {tourney_id!r}")
    return text.rsplit("-", 1)[1]


def panel_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        missing = [field for field in PANEL_KEYS if field not in row]
        if missing:
            raise ChainError(f"panel row lacks {missing}")
        key = row["source_key"]
        if key in index:
            raise ChainError(f"duplicate panel source_key: {key}")
        index[key] = {field: row[field] for field in PANEL_KEYS}
    return index


def carry_source(
    base_rules: list[dict[str, str]],
    panel: Mapping[str, Mapping[str, str]],
    carry_from_year: int,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    """Index the carry-source editions by event code and by normalized name.

    One entry per (event code, round, best_of) is not enough: the deciding-set rule can
    differ by round (the 2005-2007 best-of-five finals branch), so the carried rule is
    looked up by the *new* row's round and best_of within the matched event, and an
    event that cannot supply that combination falls through to the default path.
    """
    by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    for rule in base_rules:
        if int(rule["source_season"]) != carry_from_year:
            continue
        meta = panel.get(rule["source_key"])
        if meta is None:
            raise ChainError(f"carry-source rule row has no panel row: {rule['source_key']}")
        record = {
            **rule,
            "tourney_name": meta["tourney_name"],
            "tourney_level": meta["tourney_level"],
            "event_code": event_code(rule["tourney_id"]),
        }
        by_code[record["event_code"]].append(record)
        by_name[normalized_name(meta["tourney_name"])].append(record)
    return dict(by_code), dict(by_name)


def _unique_event(candidates: list[dict[str, str]]) -> tuple[str | None, str]:
    """Return the single ``tourney_id`` the candidate rows agree on, or a reason."""
    editions = {row["tourney_id"] for row in candidates}
    if len(editions) != 1:
        return None, "multiple_carry_source_editions"
    return editions.pop(), ""


def pick_rule(
    candidates: list[dict[str, str]], new_round: str, best_of: str
) -> tuple[dict[str, str] | None, str]:
    exact = [row for row in candidates if row["round"] == new_round and row["best_of"] == best_of]
    pool = exact if exact else [row for row in candidates if row["best_of"] == best_of]
    if not pool:
        return None, "no_carry_source_row_for_best_of"
    rules = {(row["rule_group"], row["rule_basis"], row["match_rule"]) for row in pool}
    if len(rules) != 1:
        return None, "carry_source_rows_disagree_on_rule"
    return pool[0], "round_and_best_of" if exact else "best_of_only"


def tour_default(
    rule_config: Mapping[str, Any], level: str, best_of: int
) -> tuple[dict[str, str] | None, str]:
    ordinary = rule_config["ordinary_atp"]
    if level == "G":
        return None, "no_tour_default_for_grand_slam"
    if level in ordinary["levels"] and best_of == 3:
        rule = {
            "sets_to_win": 2,
            "regular_set": rule_config["regular_set"],
            "deciding_set": ordinary["deciding_set"],
        }
        return (
            {
                "rule_group": "ordinary_atp_best_of_three",
                "rule_basis": ordinary["basis"],
                "match_rule": json.dumps(rule, sort_keys=True, separators=(",", ":")),
            },
            "tour_default_ordinary_atp_best_of_three",
        )
    return None, f"no_tour_default_for_level_{level}_best_of_{best_of}"


def extend(
    base_rules: list[dict[str, str]],
    base_panel_rows: list[dict[str, str]],
    extended_panel_rows: list[dict[str, str]],
    rule_config: Mapping[str, Any],
    carry_from_year: int,
    new_years: tuple[int, ...],
) -> dict[str, Any]:
    panel = panel_index(extended_panel_rows)
    for key, meta in panel_index(base_panel_rows).items():
        panel.setdefault(key, meta)
    existing = {row["source_key"] for row in base_rules}
    if len(existing) != len(base_rules):
        raise ChainError("duplicate source_key in the base rule mapping")
    by_code, by_name = carry_source(base_rules, panel, carry_from_year)
    if not by_code:
        raise ChainError(f"no carry-source rule rows for {carry_from_year}")

    carried: list[dict[str, str]] = []
    defaulted: list[dict[str, str]] = []
    new_rules: list[dict[str, str]] = []
    for key in sorted(panel):
        if key in existing:
            continue
        meta = panel[key]
        season = int(meta["source_season"])
        if season not in new_years:
            raise ChainError(
                f"panel row {key} has source_season {season} outside the configured "
                f"new years {new_years} and no base rule row"
            )
        code = event_code(meta["tourney_id"])
        resolution: dict[str, str] | None = None
        basis = ""
        reason = ""
        for candidate_basis, pool in (
            ("event_code", by_code.get(code, [])),
            ("tourney_name", by_name.get(normalized_name(meta["tourney_name"]), [])),
        ):
            if not pool:
                continue
            edition, edition_reason = _unique_event(pool)
            if edition is None:
                reason = f"ambiguous_{candidate_basis}_{edition_reason}"
                continue
            chosen, pick_reason = pick_rule(pool, meta["round"], meta["best_of"])
            if chosen is None:
                reason = f"{candidate_basis}_{pick_reason}"
                continue
            resolution = chosen
            basis = f"{candidate_basis}:{pick_reason}"
            break
        if resolution is not None:
            row = {
                **{field: meta[field] for field in PANEL_KEYS},
                "carry_basis": basis,
                "carried_from_source_season": resolution["source_season"],
                "carried_from_tourney_id": resolution["tourney_id"],
                "carried_from_tourney_name": resolution["tourney_name"],
                "rule_group": resolution["rule_group"],
                "rule_basis": (
                    f"{resolution['rule_basis']}"
                    f";carried_forward_from_{resolution['source_season']}_edition"
                ),
                "match_rule": resolution["match_rule"],
            }
            carried.append(row)
            new_rules.append({field: row[field] for field in RULE_FIELDS})
            continue
        default, default_reason = tour_default(
            rule_config, meta["tourney_level"], int(meta["best_of"])
        )
        entry = {
            **{field: meta[field] for field in PANEL_KEYS},
            "reason": reason or default_reason,
            "rule_group": "",
            "rule_basis": "",
            "match_rule": "",
        }
        if default is not None:
            entry.update(default)
            entry["reason"] = default_reason if not reason else f"{reason};{default_reason}"
            new_rules.append({field: entry[field] for field in RULE_FIELDS})
        defaulted.append(entry)

    merged = [*base_rules, *new_rules]
    merged.sort(key=lambda row: (int(row["source_season"]), row["tourney_id"], row["source_key"]))
    return {
        "rules": merged,
        "carried": carried,
        "defaulted": defaulted,
        "new_rules": new_rules,
    }


def run(config_path: Path) -> dict[str, Any]:
    document = read_config(config_path)
    plan = year_plan(document)
    section = document.get("rule_carry_forward")
    if not isinstance(section, dict):
        raise ChainError("configuration has no rule_carry_forward object")

    base_rules_path = resolve_under_root(section["base_rules"]["path"], label="base_rules")
    base_panel_path = resolve_under_root(section["base_panel"]["path"], label="base_panel")
    rule_config_path = resolve_under_root(section["rule_config"]["path"], label="rule_config")
    extended_path = resolve_under_root(section["extended_panel"]["path"], label="extended_panel")
    output_dir = resolve_under_root(section["output_dir"], label="output_dir")
    hashes = {
        "base_rules": require_hash(
            base_rules_path, section["base_rules"].get("sha256"), label="base_rules"
        ),
        "base_panel": require_hash(
            base_panel_path, section["base_panel"].get("sha256"), label="base_panel"
        ),
        "rule_config": require_hash(
            rule_config_path, section["rule_config"].get("sha256"), label="rule_config"
        ),
        "extended_panel": require_hash(
            extended_path, section["extended_panel"].get("sha256"), label="extended_panel"
        ),
    }

    _, base_rules = read_csv_rows(base_rules_path)
    _, base_panel_rows = read_csv_rows(base_panel_path)
    _, extended_rows = read_csv_rows(extended_path)
    rule_config = json.loads(rule_config_path.read_text(encoding="utf-8"))

    base_years = sorted({int(row["source_season"]) for row in base_rules})
    carry_from_year = int(section.get("carry_from_year", max(base_years)))
    if carry_from_year not in base_years:
        raise ChainError(
            f"carry_from_year {carry_from_year} is not in the base mapping {base_years}"
        )
    new_years = tuple(year for year in range(carry_from_year + 1, plan.panel_end_year + 1))
    if not new_years:
        raise ChainError(
            f"nothing to carry: carry_from_year {carry_from_year} is at or after "
            f"panel_end_year {plan.panel_end_year}"
        )

    result = extend(
        base_rules, base_panel_rows, extended_rows, rule_config, carry_from_year, new_years
    )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "rules.csv": atomic_csv(output_dir / "rules.csv", RULE_FIELDS, result["rules"]),
        "rule_rows_carried_forward.csv": atomic_csv(
            output_dir / "rule_rows_carried_forward.csv", CARRIED_FIELDS, result["carried"]
        ),
        "rule_rows_tour_default.csv": atomic_csv(
            output_dir / "rule_rows_tour_default.csv", DEFAULT_FIELDS, result["defaulted"]
        ),
    }
    manifest = {
        "id": "CONFIRM2026-rule-carry-forward",
        "year_plan": plan.as_document(),
        "carry_from_year": carry_from_year,
        "new_years": list(new_years),
        "inputs": {
            "base_rules": {
                "path": relative_to_root(base_rules_path),
                "sha256": hashes["base_rules"],
            },
            "base_panel": {
                "path": relative_to_root(base_panel_path),
                "sha256": hashes["base_panel"],
            },
            "rule_config": {
                "path": relative_to_root(rule_config_path),
                "sha256": hashes["rule_config"],
            },
            "extended_panel": {
                "path": relative_to_root(extended_path),
                "sha256": hashes["extended_panel"],
            },
            "code": code_receipt(__name__),
        },
        "base_rule_rows": len(base_rules),
        "carried_rows": len(result["carried"]),
        "tour_default_rows": sum(1 for row in result["defaulted"] if row["match_rule"]),
        "refused_rows": sum(1 for row in result["defaulted"] if not row["match_rule"]),
        "total_rule_rows": len(result["rules"]),
        "carry_basis_counts": dict(
            sorted(Counter(row["carry_basis"] for row in result["carried"]).items())
        ),
        "default_reason_counts": dict(
            sorted(Counter(row["reason"] for row in result["defaulted"]).items())
        ),
        "outputs": outputs,
        "limits": [
            "Carried rows assume the matched event's 2024 final-set rule still applies; "
            "the 2022 final-set tiebreak harmonisation is already in force in the 2024 rows.",
            "A refused row has no rule, so SR02 emits point probabilities and refuses that "
            "match's probability. Nothing is guessed.",
        ],
    }
    manifest["manifest_sha256_of_inputs"] = canonical_hash(manifest["inputs"])
    atomic_json(output_dir / "manifest.json", manifest)
    return manifest


def self_test(config_path: Path, hold_out_year: int) -> dict[str, Any]:
    """Drop year ``hold_out_year`` from the base mapping, regenerate it, compare."""
    document = read_config(config_path)
    plan = year_plan(document)
    section = document["rule_carry_forward"]
    base_rules_path = resolve_under_root(section["base_rules"]["path"], label="base_rules")
    base_panel_path = resolve_under_root(section["base_panel"]["path"], label="base_panel")
    rule_config_path = resolve_under_root(section["rule_config"]["path"], label="rule_config")
    require_hash(base_rules_path, section["base_rules"].get("sha256"), label="base_rules")
    require_hash(base_panel_path, section["base_panel"].get("sha256"), label="base_panel")

    _, base_rules = read_csv_rows(base_rules_path)
    _, panel_rows = read_csv_rows(base_panel_path)
    rule_config = json.loads(rule_config_path.read_text(encoding="utf-8"))
    truth = {
        row["source_key"]: row for row in base_rules if int(row["source_season"]) == hold_out_year
    }
    if not truth:
        raise ChainError(f"no base rule rows in {hold_out_year}")
    kept = [row for row in base_rules if int(row["source_season"]) < hold_out_year]
    held_panel = [row for row in panel_rows if int(row["source_season"]) <= hold_out_year]
    result = extend(kept, held_panel, held_panel, rule_config, hold_out_year - 1, (hold_out_year,))
    regenerated = {row["source_key"]: row for row in result["new_rules"]}
    compared = ("rule_group", "match_rule")
    differences = []
    for key, expected in sorted(truth.items()):
        actual = regenerated.get(key)
        if actual is None:
            differences.append(
                {"source_key": key, "field": "*", "expected": "present", "actual": "missing"}
            )
            continue
        for field in compared:
            if actual[field] != expected[field]:
                differences.append(
                    {
                        "source_key": key,
                        "field": field,
                        "expected": expected[field],
                        "actual": actual[field],
                    }
                )
    extra = sorted(set(regenerated) - set(truth))
    return {
        "hold_out_year": hold_out_year,
        "carry_from_year": hold_out_year - 1,
        "year_plan": plan.as_document(),
        "target_rows": len(truth),
        "regenerated_rows": len(regenerated),
        "carried_rows": len(result["carried"]),
        "tour_default_rows": sum(1 for row in result["defaulted"] if row["match_rule"]),
        "refused_rows": sum(1 for row in result["defaulted"] if not row["match_rule"]),
        "compared_fields": list(compared),
        "differences": differences[:50],
        "difference_count": len(differences),
        "unexpected_rows": extra[:20],
        "carry_basis_counts": dict(
            sorted(Counter(row["carry_basis"] for row in result["carried"]).items())
        ),
        "refusal_reason_counts": dict(
            sorted(
                Counter(
                    row["reason"] for row in result["defaulted"] if not row["match_rule"]
                ).items()
            )
        ),
        "status": "PASS" if not differences and not extra else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--self-test-year", type=int, help="hold out this year and regenerate it")
    parser.add_argument("--report", type=Path, help="write the self-test report JSON here")
    parser.add_argument("--dry-run", action="store_true", help="validate the config and paths only")
    args = parser.parse_args(argv)
    if args.dry_run:
        document = read_config(args.config)
        plan = year_plan(document)
        section = document["rule_carry_forward"]
        for name in ("base_rules", "base_panel", "rule_config", "extended_panel"):
            entry = section[name]
            path = resolve_under_root(entry["path"], label=name)
            require_hash(path, entry.get("sha256"), label=name)
        print(json.dumps({"status": "dry_run_ok", "year_plan": plan.as_document()}, sort_keys=True))
        return 0
    if args.self_test_year is not None:
        report = self_test(args.config, args.self_test_year)
        text = json.dumps(report, indent=2, sort_keys=True)
        if args.report:
            atomic_json(resolve_under_root(args.report, label="report"), report)
        print(text)
        return 0 if report["status"] == "PASS" else 1
    manifest = run(args.config)
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "carry_from_year",
                    "new_years",
                    "carried_rows",
                    "tour_default_rows",
                    "refused_rows",
                    "total_rule_rows",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
