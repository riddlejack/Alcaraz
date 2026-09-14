"""Integrate qualified event/player evidence without fitting any model.

Stage ``prepare_panel``, both tours. Base revision:
``references/WTA02_models/prepare_panel.py``, which is a superset of
``references/TIER01_models/prepare_panel.py`` -- the ATP integration is byte-identical
between the two copies (one blank line apart) and the WTA02 copy adds the ``tour``
switch, :func:`build_wta`, :func:`wta_tier` and :func:`wta_exclusion`. Nothing had to be
merged back from the TIER01 copy.

``tour = "ATP"`` runs MULTI01's own integration on the ATP join's candidate files:
the identity tier is decided before any outcome field is read, then the guarded count
corrections, the alias context tiers, the named exclusions and the price orientation.
``tour = "WTA"`` turns :mod:`tennislab.panel.wta_join`'s paired market rows into a panel
with the same 99-column header, so every stage downstream consumes one panel contract.

What changed from the archive revision: the ATP branch's seven module-level input
globals and their ``configure()`` rebinding become a frozen :class:`PrepareSettings`;
the join is imported by name (:mod:`tennislab.panel.join`) instead of loaded by path,
and the two code files that were hashed into ``manifest.inputs`` become a ``code`` field
holding both modules' receipts.

RESERVED WINDOW. Run against an extended archive panel this program reads 2025/2026
match rows. It is downstream of the panel build, the declared exposure event.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    code_receipt,
    read_config,
    relative_to_root,
    resolve_under_root,
    sha256,
)
from tennislab.panel import join as join_module

DEFAULT_JOIN_DIR = "work/MULTI01_join"
DEFAULT_BASE = f"{DEFAULT_JOIN_DIR}/attempt_005_candidates"
DEFAULT_EVENTS = "work/MULTI01_event_crosswalk/qualified_event_crosswalk.csv"
DEFAULT_ALIASES = "work/MULTI01_player_aliases/derived/row_context_validation.csv"
DEFAULT_RG = "data/raw/MULTI01/source_cases/rg_comparison.json"
DEFAULT_RESOLUTIONS = "work/MULTI01_ambiguity_resolution"
COUNTS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")
# The archive printed every report key but `inputs`, `outputs` and `upstream`; the
# package adds `code` (the running modules' receipt), which is provenance and is
# omitted from the summary line so stdout stays the archive's bytes.
_SUMMARY_OMITTED = frozenset({"inputs", "outputs", "upstream", "code"})


@dataclass(frozen=True)
class PrepareSettings:
    """The ATP integration's resolved inputs."""

    base: Path
    events: Path
    aliases: Path
    rg: Path
    resolutions: Path

    def describe(self) -> dict[str, str]:
        return {
            "candidates_dir": relative_to_root(self.base),
            "event_crosswalk": relative_to_root(self.events),
            "alias_context": relative_to_root(self.aliases),
            "rg_comparison": relative_to_root(self.rg),
            "resolutions_dir": relative_to_root(self.resolutions),
        }


def configure(config: Mapping[str, Any] | None) -> PrepareSettings:
    """Resolve the five ATP inputs from a config document.

    Keys, all optional, under a ``prepare`` object or at the top level:
    ``candidates_dir``, ``event_crosswalk``, ``alias_context``, ``rg_comparison``,
    ``resolutions_dir``. Anything omitted keeps MULTI01's value, so an empty config
    reproduces MULTI01's own run. The archive's ``join_module`` key named the join
    program by path; the join is now imported by name and the key is ignored.
    """
    config = config or {}
    section = config.get("prepare", config)

    def _path(key: str, default: str) -> Path:
        value = section.get(key)
        return resolve_under_root(default if value is None else value, label=f"prepare {key}")

    return PrepareSettings(
        base=_path("candidates_dir", DEFAULT_BASE),
        events=_path("event_crosswalk", DEFAULT_EVENTS),
        aliases=_path("alias_context", DEFAULT_ALIASES),
        rg=_path("rg_comparison", DEFAULT_RG),
        resolutions=_path("resolutions_dir", DEFAULT_RESOLUTIONS),
    )


def sha(path: Path | str) -> str:
    return sha256(path)


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ChainError(message)


def read(path: Path | str) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def key(row: Mapping[str, Any]) -> tuple[int, str, int]:
    return (
        int(row.get("market_season", row.get("season"))),
        row["market_source_path"],
        int(row["market_source_row"]),
    )


def event_key(row: Mapping[str, Any]) -> tuple[int, str, str]:
    return (
        int(row.get("market_season", row.get("season"))),
        row["market_location"].strip(),
        row["market_tournament"].strip(),
    )


def correct_counts(row: Mapping[str, str], case: Mapping[str, Any]) -> dict[str, str]:
    """Restore quarantined primitives only from guarded primary evidence."""
    out = dict(row)
    raw = json.loads(row["raw_row_json"])
    for correction in case["assert_before_replacements"]:
        field = correction["field"]
        if int(raw[field]) != correction["assert"]:
            raise ChainError(f"Count correction precondition failed: {row['source_key']}/{field}")
        raw[field] = correction["replace"]
    for side in ("a", "b"):
        raw_side = row[f"{side}_source_side"]
        values = {c: int(raw[f"{raw_side}_{c}"]) for c in COUNTS}
        if not (
            all(v >= 0 for v in values.values())
            and values["1stIn"] <= values["svpt"]
            and values["1stWon"] <= values["1stIn"]
            and values["2ndWon"] + values["df"] <= values["svpt"] - values["1stIn"]
            and values["ace"] <= values["1stWon"] + values["2ndWon"]
            and values["bpSaved"] <= values["bpFaced"]
        ):
            raise ChainError(f"Corrected count invariant failed: {row['source_key']}/{side}")
        out.update({f"{side}_{c}": str(v) for c, v in values.items()})
    out["count_block_status"] = "usable"
    out["count_correction_applied"] = "true"
    out["additional_count_evidence"] = case["official_url"]
    return out


def qualify(row: Mapping[str, Any], event: Mapping[str, str] | None) -> tuple[str, str]:
    """Independent identity tier first; outcome validity cannot select an identity."""
    classification = row["classification"]
    if classification == "candidate_q4_unique_pair_round_date_event_unmapped":
        if event is None or event["archive_tourney_id"] != row["archive_tourney_id"]:
            return "excluded", "unqualified_event"
        if event["final_recommendation"] == "provisional_recurrence_supported":
            return "provisional", "recurrence_only_event"
        if event["final_recommendation"] not in {
            "proposed_accept",
            "proposed_accept_event_identity_only",
        }:
            return "excluded", "unqualified_event"
    if row.get("alias_context_tier") == "provisional":
        return "provisional", "alias_context_provisional"
    return "primary", "qualified_unique_identity_context"


CARRIED_EVENT_EVIDENCE_STATUS = "carried_forward_prior_edition_mapping"
CARRY_FORWARD_PROVENANCE_COLUMN = "carried_forward"


def carried_event_mapping(row: Mapping[str, Any], event: Mapping[str, str] | None) -> bool:
    """True when this row qualified only through a carried prior-edition event mapping.

    :mod:`tennislab.panel.crosswalk_carry` writes those rows into the extended crosswalk
    with ``evidence_status = carried_forward_prior_edition_mapping``; only the weak
    (``event_unmapped``) branch consults the crosswalk at all. The flag is provenance for
    the design's declared sensitivity and never a feature.
    """
    if row["classification"] != "candidate_q4_unique_pair_round_date_event_unmapped":
        return False
    if event is None or event["archive_tourney_id"] != row["archive_tourney_id"]:
        return False
    return event.get("evidence_status", "") == CARRIED_EVENT_EVIDENCE_STATUS


def write(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    fields = fields or sorted({k for r in rows for k in r})
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


WTA_MARKET_STATUS = {"Completed": "completed", "Retired": "retired", "Walkover": "walkover"}
WTA_PRICE_BOOKS = ("PS", "B365")
# Written on every WTA row so the panel header is the ATP panel's 99 columns exactly.
WTA_EMPTY_EVIDENCE_FIELDS = ("additional_count_evidence", "started_evidence", "source_correction")


def wta_tier(row: Mapping[str, str]) -> tuple[str, str]:
    """Identity tier from pairing evidence alone; no outcome field is consulted."""
    if row["link_dependent"] == "true":
        return "provisional", "surname_class_link_dependent_pair_key"
    return "primary", "unique_pair_key_in_accepted_edition"


def wta_exclusion(row: Mapping[str, str]) -> str | None:
    """The first named reason this paired market row cannot enter the panel, or None."""
    if row["pairing_status"] != "matched":
        return row["pairing_status"]
    if row["winner_agreement"] != "agree":
        return "unresolved_outcome_or_quote_orientation"
    if not row["market_date"]:
        return "market_date_missing"
    if row["date_window_agreement"] != "true":
        return "market_date_outside_event_window"
    if row["market_comment"] not in WTA_MARKET_STATUS:
        return "market_status_vocabulary_unrecognized"
    # D5: `Cancelled` is not in WTA_MARKET_STATUS, so the vocabulary check above claims
    # such a row first and this branch could never see one. Naming it here as well read
    # as a live classification that does not exist; only `Walkover` reaches this line.
    if row["market_comment"] == "Walkover":
        return "start_status_disagreement"
    if row["archive_status"] not in {"completed", "retired"}:
        return "nonstart_or_unresolved_status"
    if row["archive_score"].strip().upper() in {"RET", "DEF", "DEF."}:
        return "start_not_established_by_score"
    return None


def build_wta(output: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    """The WTA branch: qualified market rows plus the archive panel -> panel.csv."""
    section = config.get("wta_prepare", {})
    if not section.get("join_dir") or not section.get("archive_panel_dir"):
        raise ChainError("wta_prepare needs join_dir and archive_panel_dir")
    join_dir = resolve_under_root(section["join_dir"], label="wta_prepare join_dir")
    panel_dir = resolve_under_root(
        section["archive_panel_dir"], label="wta_prepare archive_panel_dir"
    )
    if output.exists() and any(output.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    archive = {row["source_key"]: row for row in read(panel_dir / "source_panel.csv")}
    market = read(join_dir / "market_rows.csv")
    join_manifest = json.loads((join_dir / "join_manifest.json").read_text())

    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(market, key=lambda row: (int(row["season"]), int(row["market_source_row"]))):
        market_key = f"{item['season']}/{item['market_source_path']}/{item['market_source_row']}"
        reject = wta_exclusion(item)
        if reject:
            exclusions.append(
                {
                    "market_key": market_key,
                    "source_key": item["archive_source_key"],
                    "reason": reject,
                }
            )
            continue
        source_key = item["archive_source_key"]
        if source_key in seen:
            raise ChainError("More than one market row resolves to the same match")
        seen.add(source_key)
        a = archive[source_key]
        tier, basis = wta_tier(item)
        match_date = date.fromisoformat(item["market_date"])
        agreement_fields = (
            "score_agreement",
            "surface_agreement",
            "best_of_agreement",
            "status_agreement",
        )
        out = {name: value for name, value in a.items() if name != "raw_row_json"}
        out.update(
            season=str(match_date.year),
            source_season=a["season"],
            match_id=a["source_key"],
            match_date=match_date.isoformat(),
            player_a=a["a_entity_id"],
            player_b=a["b_entity_id"],
            archive_date_basis=a["date_basis"],
            # WTA02 declared rule 4: a draw-page row's date is the inferred event end and
            # is labelled as such, never as a reported date.
            date_basis=(
                "inferred_event_end"
                if item.get("market_date_basis") == "inferred_event_end"
                else "qualified_annual_reported_date_not_publication_clock"
            ),
            identity_tier=tier,
            identity_basis=basis,
            market_source_path=item["market_source_path"],
            market_source_row=item["market_source_row"],
            market_source_sha256=item["market_source_sha256"],
            court_recorded=item["market_court"],
            source_field_agreement=str(
                all(item[field] == "agree" for field in agreement_fields)
            ).lower(),
        )
        out.update({field: "" for field in WTA_EMPTY_EVIDENCE_FIELDS})
        if item["crosswalk_status"] == "accepted_carried_forward":
            # WTA02: the row qualified only through a carried event mapping (declared
            # rule 2). Written on carried rows only, so a panel with no carried edition
            # keeps the 99-column header.
            out["carried_forward"] = "true"
        for book in WTA_PRICE_BOOKS:
            valid = item[f"{book}_pair_quality"] == "valid_decimal_gt_1"
            win, lose = item[f"{book}W"], item[f"{book}L"]
            # outcome-history read: the panel's own orientation names the price sides.
            price_a, price_b = (win, lose) if a["a_won"] == "true" else (lose, win)
            out[f"{book}_decimal_a"], out[f"{book}_decimal_b"] = price_a, price_b
            out[f"{book}_valid"] = str(valid).lower()
        rows.append(out)
    rows.sort(key=lambda row: (row["match_date"], row["match_id"]))
    write(output / "panel.csv", rows)
    write(output / "exclusions.csv", exclusions, fields=["market_key", "source_key", "reason"])
    write(output / "corrections.csv", [], fields=["season", "source_key", "correction_type"])
    flow = Counter((r["season"], r["identity_tier"], r["status"], r["PS_valid"]) for r in rows)
    write(
        output / "coverage.csv",
        [
            dict(season=k[0], identity_tier=k[1], status=k[2], PS_valid=k[3], matches=v)
            for k, v in sorted(flow.items())
        ],
    )
    input_paths = [
        join_dir / "market_rows.csv",
        join_dir / "join_manifest.json",
        panel_dir / "source_panel.csv",
    ]
    report = {
        "status": "integration_candidate_no_models",
        "tour": "WTA",
        "rows": len(rows),
        "identity_tiers": dict(Counter(r["identity_tier"] for r in rows)),
        "rows_by_season": dict(sorted(Counter(r["season"] for r in rows).items())),
        "primary_by_season": dict(
            sorted(Counter(r["season"] for r in rows if r["identity_tier"] == "primary").items())
        ),
        "priced_by_season": dict(
            sorted(Counter(r["season"] for r in rows if r["PS_valid"] == "true").items())
        ),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "source_field_agreement_true": sum(
            1 for r in rows if r["source_field_agreement"] == "true"
        ),
        "rows_by_date_basis": dict(sorted(Counter(r["date_basis"] for r in rows).items())),
        "inferred_event_end_rows_by_season": dict(
            sorted(
                Counter(
                    r["season"] for r in rows if r["date_basis"] == "inferred_event_end"
                ).items()
            )
        ),
        "carried_forward_event_mapping_rows": sum(
            1 for r in rows if r.get("carried_forward") == "true"
        ),
        "carried_forward_event_mapping_rows_by_season": dict(
            sorted(Counter(r["season"] for r in rows if r.get("carried_forward") == "true").items())
        ),
        "exclusion_reasons": dict(Counter(r["reason"] for r in exclusions)),
        "panel_columns": len(rows[0]) if rows else 0,
        "identity_corrections_applied": 0,
        "count_corrections_applied": 0,
        "guarded_date_or_round_corrections": 0,
        "inputs": {relative_to_root(p): sha(p) for p in input_paths},
        "code": {"prepare": code_receipt(__name__)},
        "upstream": {"join": join_manifest["inputs"], "join_status": join_manifest["status"]},
        "outputs": {p.name: sha(p) for p in output.glob("*.csv")},
        "remaining": (
            "Primary excludes link-dependent pair keys. The 13 winner-orientation conflicts, "
            "the 4 tennis-data-only matches, the 2 date defects and the 2 missing dates are "
            "excluded and counted, never resolved. No WTA identity or count correction exists "
            "and none was applied. Surface, best_of, status and score disagreements are "
            "retained as flags with no truth certification. No model fit."
        ),
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in _SUMMARY_OMITTED}))
    return report


def _recovered_alias_rows(
    settings: PrepareSettings,
    join_settings: join_module.JoinSettings,
    archive_by_key: dict[str, dict[str, str]],
    markets: dict[tuple[int, str, int], dict[str, Any]],
    original: dict[tuple[int, str, int], dict[str, str]],
    candidates: dict[tuple[int, str, int], dict[str, Any]],
) -> tuple[dict[tuple[int, str, int], list[dict[str, str]]], list[dict[str, str]]]:
    """MULTI01's recovered row-scoped aliases, folded into ``candidates`` in place."""
    _ = join_settings
    alias_rows: dict[tuple[int, str, int], list[dict[str, str]]] = defaultdict(list)
    for r in read(settings.aliases):
        alias_rows[key(r)].append(r)
    alias_rejections: list[dict[str, str]] = []
    for row_key, evidence in sorted(alias_rows.items()):
        if row_key in candidates:
            raise ChainError("Recovered alias overlaps existing candidate")
        source_keys = {r["archive_source_key"] for r in evidence}
        if len(source_keys) != 1:
            raise ChainError("Alias evidence disagrees on match identity")
        market, old = markets[row_key], original[row_key]
        if join_module.source_date_anomaly_rule(market):
            alias_rejections.append(
                {"market_key": str(row_key), "reason": "source_date_anomaly_unresolved"}
            )
            continue
        selected = archive_by_key[next(iter(source_keys))]
        overrides = {r["market_alias"]: int(r["canonical_entity_id"]) for r in evidence}
        aliases = []
        inferred_opponent = False
        for side, raw_name in [("winner", "Winner"), ("loser", "Loser")]:
            ids = {int(x) for x in old[f"{side}_alias_candidates"].split(";") if x}
            basis = old[f"{side}_alias_basis"]
            if market[raw_name] in overrides:
                ids, basis = {overrides[market[raw_name]]}, "qualified_row_scoped_alias"
            if not ids:
                # This explicitly weaker branch is supported only by the audited
                # event/round context.
                others = {
                    int(r["archive_other_entity_id"])
                    for r in evidence
                    if r["market_opponent_name"] == market[raw_name]
                }
                if len(others) != 1:
                    raise ChainError("Unresolved opposite player in recovered alias row")
                ids, basis = others, "provisional_unique_event_round_opponent"
                inferred_opponent = True
            aliases.append({"ids": ids, "basis": basis})
        pair = {int(selected["a_entity_id"]), int(selected["b_entity_id"])}
        if not any({a, b} == pair for a in aliases[0]["ids"] for b in aliases[1]["ids"]):
            raise ChainError("Alias candidates do not include the selected neutral pair")
        item = join_module.candidate_record(
            selected, market, "qualified_row_scoped_alias_context", True
        )
        if not item["round_agreement"] or not item["date_window_agreement"]:
            alias_rejections.append(
                {"market_key": str(row_key), "reason": "round_or_date_requires_correction"}
            )
            continue
        result = {
            "market": market,
            "selected": item,
            "candidate_pool": [item],
            "winner_alias": aliases[0],
            "loser_alias": aliases[1],
            "classification": "qualified_row_scoped_alias_context",
        }
        validation, _unused = join_module.validate_selected(result)
        flat = join_module.flattened_candidate(result, validation)
        flat["alias_context_tier"] = (
            "provisional"
            if inferred_opponent
            or any(
                r["event_crosswalk_recommendation"] == "provisional_recurrence_supported"
                for r in evidence
            )
            else "primary"
        )
        candidates[row_key] = flat
    return alias_rows, alias_rejections


def _resolved_rows(
    settings: PrepareSettings,
    archive_by_key: dict[str, dict[str, str]],
    markets: dict[tuple[int, str, int], dict[str, Any]],
    original: dict[tuple[int, str, int], dict[str, str]],
    candidates: dict[tuple[int, str, int], dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """MULTI01's ambiguity and row-defect resolutions, folded into ``candidates``."""
    corrections: list[dict[str, str]] = []
    resolved_rows = read(settings.resolutions / "ambiguous_row_resolutions.csv")
    resolved_rows += [
        r
        for r in read(settings.resolutions / "row_defect_resolutions.csv")
        if r["resolution_status"] == "accepted"
    ]
    for resolution in resolved_rows:
        row_key = key(resolution)
        if row_key in candidates:
            raise ChainError("Resolution unexpectedly overlaps an existing selected row")
        market, old = dict(markets[row_key]), original[row_key]
        correction = resolution.get("required_versioned_correction", "")
        if correction:
            field, change = correction.split(":", 1)
            before, after = change.split("->", 1)
            if field == "match_date":
                require(
                    market["market_date"].isoformat() == before,
                    "Date correction precondition failed",
                )
                market["market_date"] = date.fromisoformat(after)
            elif field == "round":
                require(market["Round"] == before, "Round correction precondition failed")
                # Preserve official vocabulary separately; use the original parser's TD
                # round vocabulary.
                market["Round"] = {"Quarter": "Quarterfinals", "Round of 16": "2nd Round"}[after]
            else:
                raise ChainError("Unsupported correction field")
            for field_prefix in ("official_raw", "official_receipt"):
                evidence_path = resolve_under_root(
                    resolution[field_prefix + "_path"], label=field_prefix
                )
                require(
                    sha(evidence_path) == resolution[field_prefix + "_sha256"],
                    "Correction evidence hash drift",
                )
            corrections.append(
                dict(
                    market_key=str(row_key),
                    source_key=resolution["persistent_match_id"],
                    source_correction=correction,
                    official_locator=resolution["official_locator"],
                )
            )
        selected = archive_by_key[resolution["persistent_match_id"]]
        item = join_module.candidate_record(selected, market, "qualified_event_resolution", True)
        if not item["round_agreement"] or not item["date_window_agreement"]:
            raise ChainError("Resolved row failed declared round/date checks")
        aliases = [
            {
                "ids": {int(x) for x in old[f"{side}_alias_candidates"].split(";") if x},
                "basis": old[f"{side}_alias_basis"],
            }
            for side in ("winner", "loser")
        ]
        result = {
            "market": market,
            "selected": item,
            "candidate_pool": [item],
            "winner_alias": aliases[0],
            "loser_alias": aliases[1],
            "classification": "qualified_event_resolution",
        }
        validation, _unused = join_module.validate_selected(result)
        flat = join_module.flattened_candidate(result, validation)
        flat["alias_context_tier"] = (
            "provisional" if resolution["resolution_status"] == "provisional" else "primary"
        )
        flat["source_correction"] = correction
        candidates[row_key] = flat
    return resolved_rows, corrections


def build_atp(
    output: Path, settings: PrepareSettings, join_settings: join_module.JoinSettings
) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    archive, market_rows, provenance = join_module.load_inputs(join_settings)
    archive_by_key = {r["source_key"]: r for r in archive}
    markets = {key(r): r for r in market_rows}
    original = {key(r): r for r in read(settings.base / "market_row_candidates.csv")}
    candidates = {key(r): r for r in read(settings.base / "common_panel_candidates.csv")}
    events = {event_key(r): r for r in read(settings.events)}

    alias_rows, alias_rejections = _recovered_alias_rows(
        settings, join_settings, archive_by_key, markets, original, candidates
    )
    resolved_rows, corrections = _resolved_rows(
        settings, archive_by_key, markets, original, candidates
    )

    defaults = {r["source_key"]: r for r in read(settings.resolutions / "default_cases.csv")}
    for _source_key, evidence in defaults.items():
        require(evidence["resolution_status"] == "accepted", "Unresolved default case")
        require(
            evidence["official_advancing_player"] == evidence["archive_advancing_player"],
            "Default winner disagreement",
        )
        for prefix in (
            "official_pdf",
            "official_rendered",
            "official_extracted_text",
            "official_header",
        ):
            path = resolve_under_root(evidence[prefix + "_path"], label=prefix)
            require(sha(path) == evidence[prefix + "_sha256"], "Default evidence hash drift")
    status_cases = {r["source_key"]: r for r in read(settings.resolutions / "status_cases.csv")}
    for evidence in status_cases.values():
        path = resolve_under_root(evidence["official_raw_path"], label="official_raw")
        require(sha(path) == evidence["official_raw_sha256"], "Status evidence hash drift")

    rg = json.loads(settings.rg.read_text())
    for case in rg["cases"]:
        for source in case["sources"]:
            path = resolve_under_root(source["path"], label="rg source")
            if sha(path) != source["sha256"]:
                raise ChainError("RG evidence hash drift")
        archive_by_key[case["match_key"]] = correct_counts(archive_by_key[case["match_key"]], case)

    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = list(alias_rejections)
    seen: set[str] = set()
    for row_key, row in sorted(candidates.items()):
        if row["archive_source_key"] in seen:
            raise ChainError("More than one market row resolves to the same match")
        seen.add(row["archive_source_key"])
        event = events.get(event_key(row))
        tier, reason = qualify(row, event)
        carried = carried_event_mapping(row, event)
        reject = None
        if tier == "excluded":
            reject = reason
        elif row["winner_agreement"] != "agree":
            reject = "unresolved_outcome_or_quote_orientation"
        elif (
            row["archive_status"] not in {"completed", "retired"}
            and row["archive_source_key"] not in defaults
        ):
            reject = "nonstart_or_unresolved_status"
        elif row["market_comment"] in {"Walkover", "Cancelled"}:
            reject = "start_status_disagreement"
        elif (
            row["archive_score"].strip().upper() in {"RET", "DEF", "DEF."}
            and row["archive_source_key"] not in status_cases
        ):
            reject = "start_not_established_by_score"
        if reject:
            exclusions.append(
                {
                    "market_key": str(row_key),
                    "source_key": row["archive_source_key"],
                    "reason": reject,
                }
            )
            continue
        a = archive_by_key[row["archive_source_key"]]
        d = date.fromisoformat(row["market_match_date"])
        out = {k: v for k, v in a.items() if k != "raw_row_json"}
        out.update(
            season=str(d.year),
            source_season=a["season"],
            match_id=a["source_key"],
            match_date=d.isoformat(),
            player_a=a["a_entity_id"],
            player_b=a["b_entity_id"],
            archive_date_basis=a["date_basis"],
            date_basis="qualified_annual_reported_date_not_publication_clock",
            identity_tier=tier,
            identity_basis=reason,
            market_source_path=row["market_source_path"],
            market_source_row=row["market_source_row"],
            market_source_sha256=row["market_source_sha256"],
            court_recorded=row["market_court"],
            source_field_agreement=str(
                all(
                    row[f"{f}_agreement"] == "agree"
                    for f in ("score", "surface", "best_of", "status")
                )
            ).lower(),
        )
        if a["source_key"] in defaults:
            out["played"] = "true"
            out["started_evidence"] = defaults[a["source_key"]]["official_locator"]
        elif a["source_key"] in status_cases:
            out["started_evidence"] = status_cases[a["source_key"]]["official_locator"]
        out["source_correction"] = row.get("source_correction", "")
        # Provenance only, written on carried rows alone so a panel with no carried
        # mapping keeps MULTI01's exact header. Never a model feature.
        if carried:
            out["carried_forward"] = "true"
        for book in ("PS", "B365"):
            valid = row[f"{book}_pair_quality"] == "valid_decimal_gt_1"
            # Outcome orientation is validated separately above; raw price columns are
            # named to their source participants.
            win, lose = row[f"{book}W"], row[f"{book}L"]
            # outcome-history read: the panel's own orientation names the price sides.
            price_a, price_b = (win, lose) if a["a_won"] == "true" else (lose, win)
            out[f"{book}_decimal_a"], out[f"{book}_decimal_b"] = price_a, price_b
            out[f"{book}_valid"] = str(valid).lower()
        rows.append(out)
    rows.sort(key=lambda r: (r["match_date"], r["match_id"]))
    write(output / "panel.csv", rows)
    write(output / "exclusions.csv", exclusions)
    write(output / "corrections.csv", corrections)
    flow = Counter((r["season"], r["identity_tier"], r["status"], r["PS_valid"]) for r in rows)
    write(
        output / "coverage.csv",
        [
            dict(season=k[0], identity_tier=k[1], status=k[2], PS_valid=k[3], matches=v)
            for k, v in sorted(flow.items())
        ],
    )
    input_paths = [
        settings.base / "market_row_candidates.csv",
        settings.base / "common_panel_candidates.csv",
        settings.events,
        settings.aliases,
        settings.rg,
    ]
    input_paths += [
        settings.resolutions / name
        for name in (
            "ambiguous_row_resolutions.csv",
            "row_defect_resolutions.csv",
            "default_cases.csv",
            "status_cases.csv",
        )
    ]
    report = {
        "status": "integration_candidate_no_models",
        "rows": len(rows),
        "identity_tiers": dict(Counter(r["identity_tier"] for r in rows)),
        "carried_forward_event_mapping_rows": sum(
            1 for r in rows if r.get("carried_forward") == "true"
        ),
        "carried_forward_event_mapping_rows_by_season": dict(
            Counter(r["season"] for r in rows if r.get("carried_forward") == "true")
        ),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "additional_guarded_RG_corrections": 6,
        "rg_cases_verified": len(rg["cases"]),
        "recovered_alias_rows_examined": len(alias_rows),
        "exclusion_reasons": dict(Counter(r["reason"] for r in exclusions)),
        "resolved_ambiguity_rows": 279,
        "resolution_rows_read": len(resolved_rows),
        "guarded_date_or_round_corrections": len(corrections),
        "official_default_cases": len(defaults),
        "inputs": {relative_to_root(p): sha(p) for p in input_paths},
        "code": {"prepare": code_receipt(__name__), "join": code_receipt(join_module.__name__)},
        "upstream": provenance,
        "outputs": {p.name: sha(p) for p in output.glob("*.csv")},
        "remaining": "Primary excludes provisional event context. Undated source rows do not update chronological states. Source archive surface/format retained with disagreement flags per MULTI01 design; no truth certification of disputed fields. No model fit.",
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in _SUMMARY_OMITTED}))
    return report


def build(output: Path, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    document = config or {}
    if str(document.get("tour", "ATP")).upper() == "WTA":
        return build_wta(output, document)
    return build_atp(output, configure(document), join_module.configure(dict(document)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        help="JSON with an optional `prepare` object, a `join` object and `year_plan`",
    )
    parser.add_argument("--dry-run", action="store_true", help="resolve and hash the inputs only")
    args = parser.parse_args(argv)
    document = read_config(args.config) if args.config else None
    output = resolve_under_root(args.output, label="output")
    if args.dry_run and str((document or {}).get("tour", "ATP")).upper() == "WTA":
        section = (document or {}).get("wta_prepare", {})
        resolved = {}
        for label in ("join_dir", "archive_panel_dir"):
            if not section.get(label):
                raise ChainError(f"wta_prepare input missing: {label}")
            path = resolve_under_root(section[label], label=label)
            if not path.exists():
                raise ChainError(f"wta_prepare input missing: {label}: {path}")
            resolved[label] = relative_to_root(path)
        print(
            json.dumps(
                {"status": "dry_run_ok", "tour": "WTA", "inputs": resolved},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.dry_run:
        settings = configure(document)
        for label, path in (
            ("candidates_dir", settings.base),
            ("event_crosswalk", settings.events),
            ("alias_context", settings.aliases),
            ("rg_comparison", settings.rg),
            ("resolutions_dir", settings.resolutions),
        ):
            if not path.exists():
                raise ChainError(f"prepare input missing: {label}: {path}")
        resolved = settings.describe()
        resolved["join"] = join_module.configure(dict(document or {})).describe()
        print(json.dumps({"status": "dry_run_ok", "inputs": resolved}, indent=2, sort_keys=True))
        return 0
    build(output, document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
