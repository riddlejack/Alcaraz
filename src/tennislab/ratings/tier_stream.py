"""The ATP lower-tier match stream, built from the pinned ARCHIVE01 mirror.

Stage ``tier_stream``. Ported from the archive's ``TIER01_models/tier_stream.py``
(revision 2, satellite-circuit dating); there is no WTA02 copy. One pass over the
tarball produces the two streams the rest of TIER01 consumes:

* ``tier_results.csv.gz`` -- the outcome stream in ``ratings.elo.RESULT_COLUMNS``'
  canonical schema plus ``match_id``, ``family``, ``tier``, ``season``, ``anchor_date``
  and ``is_final``; ``ratings.tier_elo`` replays it. It carries no service count.
* ``tier_source_rows.csv.gz`` -- the serve-count stream in SR02's own
  ``dynamics.dynamic.SOURCE_ROW_FIELDS`` schema and nothing else, so the SR02 feed
  physically cannot see ``winner_id``, ``loser_id`` or any label. ATP
  qualifying/Challenger only, from ``serve_counts_start_year``.

Families and years: ``atp/atp_matches_qual_chall_YYYY.csv`` and
``atp/atp_matches_futures_YYYY.csv`` from ``first_year`` to ``last_year``, which must equal
the year plan's ``panel_end_year`` (a reserved year needs the acknowledgement below). The
tarball, the inventory and the ARCHIVE01 manifest are hash-verified, the manifest must pin
the other two, and every member read is verified against the inventory before a byte is
parsed.

The tier split is the audit's: a ``round`` matching ``^Q\\d$`` is a qualifying draw,
anything else at ``tourney_level = C`` is a Challenger main draw, every Futures row is
Futures, and a main-draw row at a tour level inside the qualifying/Challenger family is
refused rather than guessed.

**The reported date.** A lower-tier row has no match clock, only ``tourney_date``, the
event anchor. The declared rule is ``reported date = anchor + reported_date_offset_days``
(7, or 0 for the declared sensitivity). With ``satellite_circuit_dating`` true a
satellite circuit's component editions -- tourney ids of the shape
``<base>-<YYYY><leg letter>`` sharing one anchor -- are all dated at the circuit's last
possible completion, :func:`tennislab.chronology.dating.satellite_circuit_end`
(anchor + 7 days per leg; the Spain 1 2006 counterexample, four legs anchored
2006-02-27, is dated 2006-03-27). The leg count is taken over every row *read* for the
base id, before any exclusion. Both the anchor and the reported date are written.

What changed in the port: paths resolve through ``resolve_under_root`` and manifests
record ``relative_to_root`` strings; the code receipt is ``code_receipt(__name__)``; the
circuit end is computed by the chronology module instead of inline arithmetic, so the
circuit rule requires the declared 7-day leg length (an offset of 0 with circuit dating
on was never run and is refused). Every data output is byte-identical to the archive's.

RESERVED WINDOW. A ``last_year`` at or after 2025 opens reserved-year result files. As in
the bridge, it is refused unless the ``tier_stream`` section carries
``reserved_release_acknowledged: true``; the chain runner copies the chain config's own
``reserved_release_acknowledged`` here, so one acknowledgement covers both stages. The
summary's ``span`` then lists the reserved years opened and those never opened. With no
reserved year in the span, nothing here changes.

    python -m tennislab.ratings.tier_stream --config <configs/tier_stream.json> [--output-dir D]
    python -m tennislab.ratings.tier_stream --config <...> --dry-run
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_csv,
    atomic_json,
    code_receipt,
    read_config,
    relative_to_root,
    require_hash,
    resolve_output_under_root,
    resolve_under_root,
    year_plan,
)
from tennislab.chronology.dating import DAYS_PER_CIRCUIT_LEG, satellite_circuit_end

csv.field_size_limit(1 << 24)

# --------------------------------------------------------------- frozen vocabulary

# The archive panel builder's raw header, copied verbatim (the audit copied the same).
RAW_FIELDS = (
    "tourney_id",
    "tourney_name",
    "surface",
    "draw_size",
    "tourney_level",
    "tourney_date",
    "match_num",
    "winner_id",
    "winner_seed",
    "winner_entry",
    "winner_name",
    "winner_hand",
    "winner_ht",
    "winner_ioc",
    "winner_age",
    "loser_id",
    "loser_seed",
    "loser_entry",
    "loser_name",
    "loser_hand",
    "loser_ht",
    "loser_ioc",
    "loser_age",
    "score",
    "best_of",
    "round",
    "minutes",
    "w_ace",
    "w_df",
    "w_svpt",
    "w_1stIn",
    "w_1stWon",
    "w_2ndWon",
    "w_SvGms",
    "w_bpSaved",
    "w_bpFaced",
    "l_ace",
    "l_df",
    "l_svpt",
    "l_1stIn",
    "l_1stWon",
    "l_2ndWon",
    "l_SvGms",
    "l_bpSaved",
    "l_bpFaced",
    "winner_rank",
    "winner_rank_points",
    "loser_rank",
    "loser_rank_points",
)
COUNT_FIELDS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")
# SR02 reads eight of the nine; `SvGms` must be present for a block to count as complete
# (the panel builder's rule) but is not itself an SR02 input.
SR02_COUNT_SUFFIXES = ("svpt", "1stIn", "1stWon", "2ndWon", "df", "ace", "bpSaved", "bpFaced")
SOURCE_ROW_FIELDS = (
    "match_id",
    "match_date",
    "tourney_id",
    "surface",
    "player_a",
    "player_b",
    "a_entity_id",
    "b_entity_id",
    "identity_tier",
    "status",
    "played",
    "walkover",
    "abandoned",
    "count_block_status",
    "started_evidence",
    *(f"{side}_{suffix}" for side in ("a", "b") for suffix in SR02_COUNT_SUFFIXES),
)
RESULT_FIELDS = (
    "date",
    "tour",
    "tournament",
    "level",
    "round",
    "surface",
    "best_of",
    "winner_id",
    "loser_id",
    "winner_name",
    "loser_name",
    "source",
    "match_id",
    "family",
    "tier",
    "season",
    "anchor_date",
    "is_final",
)
SURFACES = ("Hard", "Clay", "Grass", "Carpet")
QUALIFYING_ROUND = re.compile(r"^Q\d$")
COUNT_RE = re.compile(r"^-?[0-9]+$")
# A satellite-circuit component edition: the ordinary tourney id followed by a single
# lower-case leg letter. The retained 1991-2024 stream carries this pattern and no other
# sibling pattern: 911 base ids, suffixes a/b/c/d, 3,642 component editions.
CIRCUIT_LEG_ID = re.compile(r"^(?P<base>.*-\d{4})(?P<leg>[a-z])$")
HISTORY_STATUSES = ("completed", "retired")

FAMILIES = {
    "atp_qual_chall": "atp/atp_matches_qual_chall_{year}.csv",
    "atp_futures": "atp/atp_matches_futures_{year}.csv",
}
TIERS = ("challenger", "qualifying", "futures")
RESERVED_YEARS = (2025, 2026)

DEFAULT_PARAMETERS = {
    "first_year": 1991,
    "elo_start_year": 2005,
    "experience_start_year": 1991,
    "serve_counts_start_year": 2010,
    "reported_date_offset_days": 7,
    # False reproduces revision 1 (attempt 001).
    "satellite_circuit_dating": False,
}


class TierStreamError(ChainError):
    """Fail-closed custody, span, schema or chronology error."""


# ------------------------------------------------------------------ MULTI01 rules


def classify_status(score: str) -> tuple[str, str]:
    """Verbatim from the archive panel builder (and the TIER01 audit)."""
    text = score.strip().upper()
    if text == "WALKOVER" or "W/O" in text:
        return "walkover", "false"
    if re.search(r"\bRET\b", text):
        return "retired", "true"
    if re.search(r"\bDEF(?:AULT)?\b", text):
        return "default", ""
    if re.search(r"\b(?:ABN|ABD|ABANDONED)\b", text):
        return "abandoned", ""
    if not text or re.search(r"[A-Z]", text):
        return "unknown", ""
    return "completed", "true"


def count_violations(counts: Mapping[str, int]) -> list[str]:
    """The eight MULTI01 service-count identities, verbatim."""
    second_opportunities = counts["svpt"] - counts["1stIn"]
    checks = {
        "first_in_le_serve_points": counts["1stIn"] <= counts["svpt"],
        "first_won_le_first_in": counts["1stWon"] <= counts["1stIn"],
        "second_won_le_second_opportunities": counts["2ndWon"] <= second_opportunities,
        "double_faults_le_second_opportunities": counts["df"] <= second_opportunities,
        "second_won_plus_df_le_second_opportunities": counts["2ndWon"] + counts["df"]
        <= second_opportunities,
        "aces_le_total_service_points_won": counts["ace"] <= counts["1stWon"] + counts["2ndWon"],
        "break_points_saved_le_faced": counts["bpSaved"] <= counts["bpFaced"],
        "service_points_won_le_serve_points": counts["1stWon"] + counts["2ndWon"] <= counts["svpt"],
    }
    return [name for name, valid in checks.items() if not valid]


def parse_counts(row: Mapping[str, str], side: str) -> tuple[dict[str, int] | None, str]:
    """Verbatim from the TIER01 audit: the nine-field block's presence state."""
    values: dict[str, int] = {}
    present = 0
    malformed = False
    for name in COUNT_FIELDS:
        raw = (row[f"{side}_{name}"] or "").strip()
        if raw == "":
            continue
        present += 1
        if not COUNT_RE.match(raw):
            malformed = True
            continue
        values[name] = int(raw)
    if present == 0:
        return None, "absent"
    if malformed or present < len(COUNT_FIELDS):
        return None, "partial_or_malformed"
    if any(value < 0 for value in values.values()):
        return values, "negative"
    return values, "present"


def count_block_status(row: Mapping[str, str]) -> tuple[str, list[str]]:
    """``usable``, ``missing_all`` or ``quarantined_invalid``, the panel builder's labels.

    ``partial_or_malformed`` and ``negative`` blocks carry no interpretable denominator, so
    they are labelled ``missing_all`` for SR02 -- the state simply is not updated -- while
    an identity failure is ``quarantined_invalid``, which the design excludes outright.
    """
    states: dict[str, str] = {}
    counts: dict[str, dict[str, int] | None] = {}
    for side in ("w", "l"):
        counts[side], states[side] = parse_counts(row, side)
    if set(states.values()) != {"present"}:
        return "missing_all", []
    violations: list[str] = []
    for side in ("w", "l"):
        violations.extend(f"{side}:{check}" for check in count_violations(counts[side]))
    if violations:
        return "quarantined_invalid", violations
    return "usable", []


# ------------------------------------------------------------------ utilities


def parse_archive_date(value: str) -> dt.date | None:
    text = (value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return dt.date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def integer_id(value: str) -> int | None:
    text = (value or "").strip()
    if not text or not text.isdigit():
        return None
    return int(text)


def tier_of(family: str, level: str, round_name: str) -> str:
    if family == "atp_futures":
        return "futures"
    if QUALIFYING_ROUND.match(round_name or ""):
        return "qualifying"
    if (level or "").strip() == "C":
        return "challenger"
    # A main-draw row at a tour level inside the qualifying/Challenger file would be a
    # tour-level main draw hiding in the wrong family. The audit found zero of them
    # (every A/G/M row is Q1-Q3); refuse rather than guess.
    raise TierStreamError(
        f"main-draw row at tourney_level {level!r} inside the qualifying/Challenger family"
    )


def circuit_leg_key(tourney_id: str) -> tuple[str, str] | None:
    """``("2006-M-SA-ESP-01A-2006", "b")`` for a satellite component edition, else None."""
    match = CIRCUIT_LEG_ID.match((tourney_id or "").strip())
    if match is None:
        return None
    return match.group("base"), match.group("leg")


def circuit_reported_dates(
    legs_by_base: Mapping[str, set[str]],
    anchors_by_tourney: Mapping[str, dt.date],
) -> dict[str, dt.date]:
    """The corrected reported date of every satellite component edition.

    Every leg of a circuit takes the circuit's last possible completion,
    :func:`satellite_circuit_end` of the circuit anchor and its leg count, so no leg can
    release a result before the final leg has been played: a four-week circuit enters at
    anchor + 28. The circuit anchor is the earliest anchor its component editions carry;
    in the retained stream every leg of every circuit carries the same one. A base id
    with a single leg is left at anchor + 7, which is the single-edition rule.
    """
    dates: dict[str, dt.date] = {}
    for base, legs in legs_by_base.items():
        members = [f"{base}{leg}" for leg in sorted(legs)]
        anchors = [anchors_by_tourney[name] for name in members if name in anchors_by_tourney]
        if not anchors:
            continue
        reported = satellite_circuit_end(min(anchors), len(legs))
        for name in members:
            if name in anchors_by_tourney:
                dates[name] = reported
    return dates


def write_csv_gz(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> str:
    """The archive's writer: ``gzip.compress(..., mtime=0)`` of a ``\\n``-terminated CSV."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=list(fields), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    payload = gzip.compress(buffer.getvalue().encode("utf-8"), mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return hashlib.sha256(payload).hexdigest()


# ------------------------------------------------------------------ the build


def members_wanted(parameters: Mapping[str, Any], last_year: int) -> dict[str, tuple[str, int]]:
    wanted: dict[str, tuple[str, int]] = {}
    for family, template in FAMILIES.items():
        for year in range(int(parameters["first_year"]), last_year + 1):
            wanted[template.format(year=year)] = (family, year)
    return wanted


def read_parameters(section: Mapping[str, Any], plan: Any) -> tuple[dict[str, Any], int, int]:
    """(parameters, reported-date offset, last year), every refusal the archive makes."""
    parameters = dict(DEFAULT_PARAMETERS)
    parameters.update(section.get("parameters", {}))
    for name in DEFAULT_PARAMETERS:
        if name not in parameters:
            raise TierStreamError(f"missing tier_stream parameter: {name}")
    offset_days = int(parameters["reported_date_offset_days"])
    if offset_days not in (7, 0):
        raise TierStreamError(
            "reported_date_offset_days is the declared 7 (or 0 for the declared "
            f"sensitivity); refusing {offset_days}"
        )
    circuit_dating = parameters["satellite_circuit_dating"]
    if not isinstance(circuit_dating, bool):
        raise TierStreamError("satellite_circuit_dating must be a boolean")
    if circuit_dating and offset_days != DAYS_PER_CIRCUIT_LEG:
        raise TierStreamError(
            "satellite_circuit_dating dates a circuit at anchor + "
            f"{DAYS_PER_CIRCUIT_LEG} days per leg; it cannot run with "
            f"reported_date_offset_days {offset_days}"
        )
    last_year = int(section.get("last_year", plan.panel_end_year))
    if last_year != plan.panel_end_year:
        raise TierStreamError(
            f"tier_stream last_year {last_year} must equal the plan's panel_end_year "
            f"{plan.panel_end_year}"
        )
    if (
        last_year >= min(RESERVED_YEARS)
        and section.get("reserved_release_acknowledged") is not True
    ):
        raise TierStreamError(
            f"refusing to read a reserved year: last_year {last_year} >= {min(RESERVED_YEARS)}"
        )
    if int(parameters["first_year"]) > int(parameters["elo_start_year"]):
        raise TierStreamError("elo_start_year precedes the first year read")
    return parameters, offset_days, last_year


def verify_custody(section: Mapping[str, Any]) -> tuple[dict[str, Path], dict[str, str]]:
    """Hash the tarball, the inventory and the manifest; the manifest must pin the other two."""
    archive_entry = section["archive"]
    inventory_entry = section["inventory"]
    manifest_entry = section["archive_manifest"]
    paths = {
        "archive": resolve_under_root(archive_entry["path"], label="archive"),
        "inventory": resolve_under_root(inventory_entry["path"], label="inventory"),
        "archive_manifest": resolve_under_root(manifest_entry["path"], label="archive_manifest"),
    }
    hashes = {
        "archive_manifest": require_hash(
            paths["archive_manifest"], manifest_entry.get("sha256"), label="archive_manifest"
        ),
        "archive": require_hash(paths["archive"], archive_entry.get("sha256"), label="archive"),
        "inventory": require_hash(
            paths["inventory"], inventory_entry.get("sha256"), label="inventory"
        ),
    }
    manifest = json.loads(paths["archive_manifest"].read_text(encoding="utf-8"))
    pinned_by_manifest = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    for label in ("archive", "inventory"):
        relative = relative_to_root(paths[label], label=label)
        if pinned_by_manifest.get(relative) != hashes[label]:
            raise TierStreamError(f"ARCHIVE01 manifest does not pin {relative} at its hash")
    return paths, hashes


def build(config: Mapping[str, Any]) -> dict[str, Any]:
    section = config.get("tier_stream")
    if not isinstance(section, dict):
        raise TierStreamError("configuration has no tier_stream object")
    plan = year_plan(config)
    parameters, offset_days, last_year = read_parameters(section, plan)
    circuit_dating = bool(parameters["satellite_circuit_dating"])

    paths, hashes = verify_custody(section)
    archive_path = paths["archive"]
    with paths["inventory"].open(newline="", encoding="utf-8") as handle:
        pinned_members = {row["path"]: row["sha256"] for row in csv.DictReader(handle)}

    tar_root = str(section["archive"]["tar_root"])
    wanted = members_wanted(parameters, last_year)
    output_dir = resolve_output_under_root(section["output_dir"], label="output_dir")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise TierStreamError(f"refusing to overwrite a nonempty output directory: {output_dir}")

    results: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    member_hashes: dict[str, str] = {}
    per_year: Counter[tuple[str, str, int]] = Counter()
    feed_by_key: Counter[tuple[str, str, int]] = Counter()
    excluded: Counter[str] = Counter()
    excluded_by_year: Counter[tuple[str, int]] = Counter()
    totals: Counter[str] = Counter()
    identity_failures: list[dict[str, str]] = []
    winner_equals_loser: list[dict[str, str]] = []
    later_season_rows: list[dict[str, str]] = []
    best_of_other: Counter[str] = Counter()
    surfaces_seen: Counter[str] = Counter()
    # The satellite-circuit leg index, collected over every row *read* (so a leg whose
    # rows are all excluded still delays its siblings) and the anchor each component
    # edition carries.
    circuit_legs: dict[str, set[str]] = {}
    anchors_by_tourney: dict[str, dt.date] = {}

    def exclude(reason: str, year: int) -> None:
        excluded[reason] += 1
        excluded_by_year[(reason, year)] += 1

    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            name = member.name
            relative = name[len(tar_root) + 1 :] if name.startswith(tar_root + "/") else name
            entry = wanted.get(relative)
            if entry is None:
                continue
            family, year = entry
            payload = archive.extractfile(member).read()
            observed = hashlib.sha256(payload).hexdigest()
            expected = pinned_members.get(relative)
            if expected is None:
                raise TierStreamError(f"member absent from the pinned inventory: {relative}")
            if observed != expected:
                raise TierStreamError(f"member hash mismatch: {relative}")
            member_hashes[relative] = observed
            reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
            if tuple(reader.fieldnames or ()) != RAW_FIELDS:
                raise TierStreamError(f"schema drift in {relative}")
            for line, row in enumerate(reader, 2):
                totals["rows_read"] += 1
                totals[f"rows_read_{family}"] += 1
                locator = {
                    "family": family,
                    "year": str(year),
                    "line": str(line),
                    "tourney_id": row["tourney_id"],
                    "match_num": row["match_num"],
                }
                leg_key = circuit_leg_key(row["tourney_id"])
                if leg_key is not None:
                    circuit_legs.setdefault(leg_key[0], set()).add(leg_key[1])

                winner = integer_id(row["winner_id"])
                loser = integer_id(row["loser_id"])
                if winner is None or loser is None:
                    exclude("player_id_unusable", year)
                    continue
                if winner == loser:
                    winner_equals_loser.append(locator)
                    exclude("winner_equals_loser", year)
                    continue
                anchor = parse_archive_date(row["tourney_date"])
                if anchor is None:
                    exclude("date_unusable", year)
                    continue
                if anchor.year > year:
                    later_season_rows.append({**locator, "tourney_date": row["tourney_date"]})
                    exclude("dated_in_a_later_season", year)
                    continue
                if anchor.year < year:
                    totals["rows_dated_in_the_previous_december"] += 1
                anchors_by_tourney.setdefault(row["tourney_id"], anchor)
                if anchors_by_tourney[row["tourney_id"]] != anchor:
                    anchors_by_tourney[row["tourney_id"]] = min(
                        anchors_by_tourney[row["tourney_id"]], anchor
                    )
                surface = (row["surface"] or "").strip()
                surfaces_seen[surface or "(blank)"] += 1
                if surface not in SURFACES:
                    exclude("surface_unsupported", year)
                    continue
                status, played = classify_status(row["score"])
                block, violations = count_block_status(row)
                if violations:
                    identity_failures.append({**locator, "checks": ";".join(violations)})
                    exclude("count_identity_failure", year)
                    continue
                if status not in HISTORY_STATUSES:
                    exclude(f"status_{status}", year)
                    continue

                tier = tier_of(family, row["tourney_level"], row["round"])
                reported = anchor + dt.timedelta(days=offset_days)
                best_of = (row["best_of"] or "").strip()
                if best_of not in {"3", "5"}:
                    best_of_other[best_of or "(blank)"] += 1
                match_id = f"tier:{family}:{row['tourney_id']}/{row['match_num']}"
                is_final = int(
                    not QUALIFYING_ROUND.match(row["round"] or "")
                    and (row["round"] or "").strip() == "F"
                )
                results.append(
                    {
                        "date": reported.isoformat(),
                        "tour": "ATP",
                        "tournament": row["tourney_name"],
                        "level": row["tourney_level"],
                        "round": row["round"],
                        "surface": surface,
                        "best_of": best_of if best_of in {"3", "5"} else "",
                        "winner_id": str(winner),
                        "loser_id": str(loser),
                        "winner_name": "",
                        "loser_name": "",
                        "source": f"TIER01-{tier}",
                        "match_id": match_id,
                        "family": family,
                        "tier": tier,
                        "season": str(year),
                        "anchor_date": anchor.isoformat(),
                        "is_final": str(is_final),
                        # Not in RESULT_FIELDS, so never written: the key the circuit
                        # redating pass joins on.
                        "_tourney_id": row["tourney_id"],
                    }
                )
                per_year[(family, tier, year)] += 1
                totals["rows_retained"] += 1
                totals[f"rows_retained_{tier}"] += 1
                if year >= int(parameters["elo_start_year"]):
                    totals["rows_elo_eligible"] += 1

                # The SR02 feed: qualifying/Challenger only, from the first year the
                # audit found a usable serve block in the family.
                if family != "atp_qual_chall" or year < int(parameters["serve_counts_start_year"]):
                    continue
                if block not in {"usable", "missing_all"}:
                    raise TierStreamError(f"unexpected count block status {block} at {locator}")
                a_side, b_side = ("w", "l") if winner < loser else ("l", "w")
                player_a, player_b = (winner, loser) if winner < loser else (loser, winner)
                feed: dict[str, Any] = {
                    "match_id": match_id,
                    "match_date": reported.isoformat(),
                    "tourney_id": row["tourney_id"],
                    "surface": surface,
                    "player_a": str(player_a),
                    "player_b": str(player_b),
                    "a_entity_id": str(player_a),
                    "b_entity_id": str(player_b),
                    # The archive resolves every id in the pinned player master (the audit
                    # found 100% resolution in every year), and no lower-tier row carries a
                    # market quote, so there is no provisional identity to express.
                    "identity_tier": "primary",
                    "status": status,
                    "played": played,
                    "walkover": "false",
                    "abandoned": "false",
                    "count_block_status": block,
                    "started_evidence": "",
                }
                for label, side in (("a", a_side), ("b", b_side)):
                    for suffix in SR02_COUNT_SUFFIXES:
                        raw = (row[f"{side}_{suffix}"] or "").strip()
                        feed[f"{label}_{suffix}"] = raw if block == "usable" else ""
                source_rows.append(feed)
                totals["sr02_feed_rows"] += 1
                totals[f"sr02_feed_{block}"] += 1
                feed_by_key[(family, tier, year)] += 1

    missing_members = sorted(set(wanted) - set(member_hashes))
    if missing_members:
        raise TierStreamError(f"members absent from the archive: {missing_members}")
    if later_season_rows:
        raise TierStreamError(
            "rows dated in a later season than their file were found; the audit found "
            f"none, so this is drift: {later_season_rows[:5]}"
        )

    # The satellite-circuit redating pass: every leg of a sibling circuit is moved to the
    # circuit's last possible completion. Nothing else moves, and with the flag false
    # nothing moves at all.
    circuit_rows: list[dict[str, Any]] = []
    if circuit_dating:
        corrected_dates = circuit_reported_dates(circuit_legs, anchors_by_tourney)
        for row in results:
            corrected = corrected_dates.get(row["_tourney_id"])
            if corrected is None:
                continue
            before = row["date"]
            row["date"] = corrected.isoformat()
            totals["circuit_rows_redated"] += int(before != row["date"])
            totals["circuit_rows"] += 1
        for row in source_rows:
            corrected = corrected_dates.get(row["tourney_id"])
            if corrected is not None:
                row["match_date"] = corrected.isoformat()
                totals["circuit_feed_rows"] += 1
        rows_by_tourney: Counter[str] = Counter(row["_tourney_id"] for row in results)
        for base, legs in sorted(circuit_legs.items()):
            members = [f"{base}{leg}" for leg in sorted(legs)]
            present = [name for name in members if name in anchors_by_tourney]
            if not present:
                continue
            circuit_rows.append(
                {
                    "circuit_base": base,
                    "legs": len(legs),
                    "anchor_date": min(anchors_by_tourney[name] for name in present).isoformat(),
                    "reported_date": corrected_dates[present[0]].isoformat(),
                    "component_editions": ";".join(present),
                    "retained_rows": sum(rows_by_tourney[name] for name in present),
                }
            )
        totals["circuit_bases"] = len(circuit_rows)
        totals["circuit_component_editions"] = sum(
            len(row["component_editions"].split(";")) for row in circuit_rows
        )

    results.sort(key=lambda row: (row["date"], row["match_id"]))
    source_rows.sort(key=lambda row: (row["match_date"], row["match_id"]))
    if len({row["match_id"] for row in results}) != len(results):
        raise TierStreamError("duplicate lower-tier match_id")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "tier_results.csv.gz": write_csv_gz(
            output_dir / "tier_results.csv.gz", RESULT_FIELDS, results
        ),
        "tier_source_rows.csv.gz": write_csv_gz(
            output_dir / "tier_source_rows.csv.gz", SOURCE_ROW_FIELDS, source_rows
        ),
    }

    count_fields = (
        "family",
        "tier",
        "season",
        "retained_rows",
        "elo_eligible_rows",
        "experience_eligible_rows",
        "sr02_feed_rows",
        "finals",
    )
    finals_by_key: Counter[tuple[str, str, int]] = Counter()
    for row in results:
        if row["is_final"] == "1":
            finals_by_key[(row["family"], row["tier"], int(row["season"]))] += 1
    count_rows = []
    for family, tier, year in sorted(per_year):
        retained = per_year[(family, tier, year)]
        count_rows.append(
            {
                "family": family,
                "tier": tier,
                "season": year,
                "retained_rows": retained,
                "elo_eligible_rows": retained if year >= int(parameters["elo_start_year"]) else 0,
                "experience_eligible_rows": retained
                if year >= int(parameters["experience_start_year"])
                else 0,
                "sr02_feed_rows": feed_by_key[(family, tier, year)],
                "finals": finals_by_key[(family, tier, year)],
            }
        )
    outputs["tier_counts_by_year.csv"] = atomic_csv(
        output_dir / "tier_counts_by_year.csv", count_fields, count_rows
    )
    if circuit_dating:
        outputs["tier_circuit_dating.csv"] = atomic_csv(
            output_dir / "tier_circuit_dating.csv",
            (
                "circuit_base",
                "legs",
                "anchor_date",
                "reported_date",
                "component_editions",
                "retained_rows",
            ),
            circuit_rows,
        )
    outputs["tier_exclusions.csv"] = atomic_csv(
        output_dir / "tier_exclusions.csv",
        ("reason", "season", "rows"),
        [
            {"reason": reason, "season": year, "rows": count}
            for (reason, year), count in sorted(excluded_by_year.items())
        ],
    )

    # Every year of the span is read (a missing member is refused above), so a reserved
    # year inside it was opened. With none opened the span and the limits are unchanged.
    first_year = int(parameters["first_year"])
    reserved_opened = [year for year in RESERVED_YEARS if first_year <= year <= last_year]
    span: dict[str, Any] = {
        "first_year": first_year,
        "last_year": last_year,
        "reserved_years_never_opened": [
            year for year in RESERVED_YEARS if year not in reserved_opened
        ],
    }
    if reserved_opened:
        span["reserved_years_opened"] = reserved_opened
        span["reserved_release_acknowledged"] = True
        futures_limit = (
            "Futures is outcome history only: the SR02 feed takes qualifying/Challenger "
            "rows alone. The audit's finding (0 of 498,555 Futures rows with a serve "
            "count, 1991-2024) does not cover the reserved years opened here "
            f"({', '.join(map(str, reserved_opened))}). A Futures row there that carries a "
            "complete serve block meets the same count-identity screen as every row, and "
            "one that fails it is dropped from the outcome stream "
            "(count_identity_failure_rows lists it)."
        )
    else:
        futures_limit = (
            "Futures carries no serve count in any year read here (the audit: 0 of "
            "498,555 rows, 1991-2024), so the family can only ever be outcome history."
        )

    summary = {
        "id": "TIER01-tier-stream",
        "status": "complete",
        "artifact_kind": "lower_tier_match_stream_no_fit_no_score",
        "year_plan": plan.as_document(),
        "parameters": dict(parameters),
        "span": span,
        "inputs": {
            **{
                name: {"path": relative_to_root(paths[name], label=name), "sha256": hashes[name]}
                for name in ("archive", "inventory", "archive_manifest")
            },
            "members": dict(sorted(member_hashes.items())),
        },
        "code": code_receipt(__name__),
        "totals": dict(sorted(totals.items())),
        "excluded": dict(sorted(excluded.items())),
        "excluded_total": sum(excluded.values()),
        "winner_equals_loser_rows": winner_equals_loser,
        "count_identity_failure_rows": identity_failures,
        "rows_dated_in_a_later_season": later_season_rows,
        "best_of_outside_3_5": dict(sorted(best_of_other.items())),
        "surfaces_seen": dict(sorted(surfaces_seen.items())),
        "retained_by_tier": {
            tier: sum(count for (_, this, _year), count in per_year.items() if this == tier)
            for tier in TIERS
        },
        "retained_by_tier_from_elo_start": {
            tier: sum(
                count
                for (_, this, year), count in per_year.items()
                if this == tier and year >= int(parameters["elo_start_year"])
            )
            for tier in TIERS
        },
        "outputs": outputs,
        "satellite_circuit_dating": {
            "enabled": circuit_dating,
            "rule": (
                f"circuit anchor + {offset_days} days x (number of legs) for every row of "
                "every component edition -- the end of the final leg -- identified by the "
                "tourney id shape <base>-<YYYY><leg letter>"
                if circuit_dating
                else f"disabled: every row is dated anchor + {offset_days} days (revision 1)"
            ),
            "basis": "docs/reviews/astra_review_2026-09-12.md finding 3",
            "circuits": totals.get("circuit_bases", 0),
            "component_editions": totals.get("circuit_component_editions", 0),
            "rows_in_circuits": totals.get("circuit_rows", 0),
            "rows_redated": totals.get("circuit_rows_redated", 0),
            "feed_rows_redated": totals.get("circuit_feed_rows", 0),
        },
        "limits": [
            "tourney_date is an event anchor, not a match clock; the reported date is "
            f"anchor + {offset_days} days so no lower-tier result becomes eligible "
            "before it was played -- except for a satellite circuit, whose component "
            "draws share one anchor and whose later legs are played in later weeks. "
            "With satellite_circuit_dating true every leg takes the circuit's last "
            "possible completion instead.  Within-event ordering is not recoverable "
            "from these bytes.",
            futures_limit,
            "Coverage of Futures and qualifying is nonrandom across countries and eras.",
            "An identity-failing row is dropped entirely, per the design's exclusion "
            "list; every retained row still carries the usable/missing_all labelling.",
        ],
    }
    outputs["summary.json"] = atomic_json(output_dir / "summary.json", summary)
    summary["outputs"] = outputs
    return summary


def dry_run(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the config, the custody chain and the span; write nothing."""
    plan = year_plan(config)
    section = config["tier_stream"]
    for name in ("archive", "inventory", "archive_manifest"):
        entry = section[name]
        path = resolve_under_root(entry["path"], label=name)
        require_hash(path, entry.get("sha256"), label=name)
    last_year = int(section.get("last_year", plan.panel_end_year))
    if (
        last_year >= min(RESERVED_YEARS)
        and section.get("reserved_release_acknowledged") is not True
    ):
        raise TierStreamError("configured span reaches a reserved year")
    return {"status": "dry_run_ok", "last_year": last_year, "year_plan": plan.as_document()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the config, the custody chain and the span only",
    )
    args = parser.parse_args(argv)
    config = read_config(args.config)
    if args.output_dir is not None:
        config["tier_stream"]["output_dir"] = str(args.output_dir)
    if args.dry_run:
        print(json.dumps(dry_run(config), sort_keys=True))
        return 0
    summary = build(config)
    print(
        json.dumps(
            {
                "rows_read": summary["totals"].get("rows_read"),
                "rows_retained": summary["totals"].get("rows_retained"),
                "retained_by_tier": summary["retained_by_tier"],
                "sr02_feed_rows": summary["totals"].get("sr02_feed_rows"),
                "excluded": summary["excluded"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
