"""Name -> Sackmann player id, with the two repairs the Elo replay run showed were needed.

Ported from ``references/TIER01_models/crosswalk_v2.py`` (byte-identical to the
``WTA02_models`` copy, so there is nothing to merge). What changed: the three frozen Elo
modules were loaded by path through the archive's sibling-package helper and are now imported by
name (``tennislab.ratings.elo``, ``tennislab.panel.elo_crosswalk``,
``tennislab.panel.mirror``); the CLI's ``--archive`` string resolves under the workspace
through ``mirror.resolve_archive``. Arithmetic, indexes, iteration order, record fields
and report serialization are untouched.

Observed failure (reported by the research lead from the CONFIRM2026 Elo replay):
the frozen Elo crosswalk restricts its reference population to players with at least
one included tour-level main-draw match in 2023-2024, and matches names verbatim.
Against 2025/2026 source names that left **294 distinct names unmatched (146 ATP, 148
WTA; 291 of them ``no_candidate``)**, costing 1,634 tennis-data and 130 Wikipedia
matches. Two causes, two repairs:

1. **Wikipedia disambiguators.** A draw page can carry the article title, e.g.
   ``"Hugo Dellien (tennis)"`` or ``"... (tennis player)"``. The trailing parenthetical
   is stripped before matching and the fact is recorded per row.
2. **The active window is too narrow.** A player whose first tour-level main-draw win
   is in 2025 or 2026 -- or who was injured through 2023-2024 -- is simply not in the
   active set, so *no* name spelling can resolve. After the active pass returns
   ``no_candidate``, this module falls back to the **full** ``atp_players.csv`` /
   ``wta_players.csv`` lifetime files, accepting only a unique hit: first an exact
   normalized full name, then surname-plus-initial.

What is deliberately *not* changed. An **ambiguous** active-set hit does not fall
through to the full file. The active set exists because the lifetime files collide far
more often; if two active players share a surname, widening the population can only
add candidates, never resolve them, and picking one is the
``kuznetsov_collision_candidates.csv`` failure mode. Such a query stays unmatched with
``reason=ambiguous_<method>`` and its candidate ids, for manual review.

Every resolution records ``match_method``, ``confidence``, ``reference_population``
(``active_2023_2024`` or ``full_players_file``), ``disambiguator_stripped`` and
``candidates_considered``, so a downstream row can be filtered by how it was resolved.
Nothing here is authoritative identity.

RESERVED WINDOW. Activity is still derived from the 2023 and 2024 match files only; the
full players file is a player master, not a results file, and carries no match outcome.
The 2025/2026 match files are never opened by this module -- the guard is
``mirror.guard_member``, reached through ``mirror.extract_results``.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import ChainError, atomic_csv, atomic_json
from tennislab.panel import elo_crosswalk as _elo_crosswalk
from tennislab.panel import mirror as _mirror
from tennislab.ratings import elo as _elo_engine

normalize_name = _elo_engine.normalize_name
Player = _elo_crosswalk.Player
ARCHIVE_DEFAULT = _mirror.ARCHIVE_DEFAULT
ARCHIVE_ROOT = _mirror.ARCHIVE_ROOT
RESERVED_YEARS = _mirror.RESERVED_YEARS
ACTIVITY_YEARS = _elo_crosswalk.ACTIVITY_YEARS

# " (tennis)", " (tennis player)", " (Bolivian tennis player)", " (born 2004)", ...
DISAMBIGUATOR = re.compile(r"\s*\((?:[^()]*\b(?:tennis|born|player)\b[^()]*)\)\s*$", re.IGNORECASE)

CONFIDENCE = {
    "exact_full": "high",
    "surname_initial": "medium",
    "surname_unique": "low",
    "full_file_exact_full": "medium",
    "full_file_surname_initial": "low",
}
POPULATION = {
    "exact_full": "active_2023_2024",
    "surname_initial": "active_2023_2024",
    "surname_unique": "active_2023_2024",
    "full_file_exact_full": "full_players_file",
    "full_file_surname_initial": "full_players_file",
}

# The bridge accepts only these confidence tiers and quarantines the rest.  The
# held-out-activity test is why: every wrong id it found came from a `low` method.
ACCEPTED_CONFIDENCE = frozenset({"high", "medium"})

CROSSWALK_COLUMNS = (
    "query_name",
    "query_after_strip",
    "disambiguator_stripped",
    "query_style",
    "tour",
    "player_id",
    "sackmann_name",
    "match_method",
    "reference_population",
    "confidence",
    "candidates_considered",
)
UNMATCHED_COLUMNS = (
    "query_name",
    "query_after_strip",
    "disambiguator_stripped",
    "query_style",
    "tour",
    "reason",
    "candidate_ids",
)


def strip_disambiguator(name: str) -> tuple[str, bool]:
    raw = (name or "").strip()
    stripped = DISAMBIGUATOR.sub("", raw).strip()
    return (stripped or raw), stripped != raw and bool(stripped)


class FullFileIndex:
    """Exact-full-name and surname+initial indexes over every row of the players file."""

    def __init__(self, players: Sequence[Any]):
        self.by_id = {player.player_id: player for player in players}
        self.full: dict[str, list[str]] = defaultdict(list)
        self.surname_initial: dict[tuple[str, str], list[str]] = defaultdict(list)
        for player in players:
            first = normalize_name(player.name_first)
            last = normalize_name(player.name_last)
            if first and last:
                self.full[f"{first} {last}"].append(player.player_id)
                reversed_key = f"{last} {first}"
                if reversed_key != f"{first} {last}":
                    self.full[reversed_key].append(player.player_id)
                self.surname_initial[(last, first[0])].append(player.player_id)
            elif last:
                self.full[last].append(player.player_id)
        self.rows = len(players)

    def lookup(self, query: str, style: str) -> tuple[str | None, str, list[str]]:
        normalized = normalize_name(query)
        attempts: list[tuple[str, list[str]]] = []
        if style == "full_name" and normalized:
            attempts.append(
                ("full_file_exact_full", list(dict.fromkeys(self.full.get(normalized, []))))
            )
        surname, initial = _surname_initial(query, style)
        if surname and initial:
            attempts.append(
                (
                    "full_file_surname_initial",
                    list(dict.fromkeys(self.surname_initial.get((surname, initial), []))),
                )
            )
        for method, candidates in attempts:
            if len(candidates) == 1:
                return candidates[0], method, candidates
            if len(candidates) > 1:
                return None, f"ambiguous_{method}", candidates
        return None, "no_candidate_full_file", []


def _surname_initial(query: str, style: str) -> tuple[str, str]:
    if style == "surname_initial":
        match = _elo_crosswalk.TENNIS_DATA_STYLE.match(query.strip())
        if match:
            return normalize_name(match.group("last")), normalize_name(match.group("initial"))
        return "", ""
    tokens = normalize_name(query).split()
    if len(tokens) >= 2:
        return " ".join(tokens[1:]), tokens[0][0]
    return "", ""


class CrosswalkV2:
    def __init__(self, active: Any, full_index: FullFileIndex, tour: str):
        self.active = active
        self.full = full_index
        self.tour = tour

    def lookup(self, query: str) -> dict[str, Any]:
        stripped, was_stripped = strip_disambiguator(query)
        record = dict(self.active.lookup(stripped))
        record["query_name"] = (query or "").strip()
        record["query_after_strip"] = stripped
        record["disambiguator_stripped"] = was_stripped
        record["tour"] = self.tour
        if record["matched"]:
            method = str(record["match_method"])
            record["reference_population"] = POPULATION[method]
            record["confidence"] = CONFIDENCE[method]
            return record
        if str(record.get("reason", "")).startswith("ambiguous_"):
            # An ambiguous active hit is not widened; see the module docstring.
            record["candidate_ids"] = record.get("candidate_ids", "")
            return record
        player_id, method, candidates = self.full.lookup(stripped, str(record["query_style"]))
        if player_id is not None:
            player = self.full.by_id[player_id]
            record.update(
                {
                    "matched": True,
                    "player_id": player_id,
                    "sackmann_name": player.display,
                    "match_method": method,
                    "reference_population": POPULATION[method],
                    "confidence": CONFIDENCE[method],
                    "candidates_considered": 1,
                    "reason": "",
                    "candidate_ids": "",
                }
            )
            return record
        record.update(
            {
                "matched": False,
                "player_id": None,
                "match_method": "",
                "reason": method,
                "candidate_ids": ";".join(candidates),
            }
        )
        return record


def build(
    archive: str | Path = ARCHIVE_DEFAULT,
    tour: str = "ATP",
    years: tuple[int, ...] = ACTIVITY_YEARS,
) -> CrosswalkV2:
    tour = tour.upper()
    players = _elo_crosswalk.load_players(archive, tour)
    active = _elo_crosswalk.build(archive, tour, years)
    return CrosswalkV2(active, FullFileIndex(players), tour)


def resolve_many(
    crosswalk: CrosswalkV2, queries: Sequence[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for query in queries:
        record = crosswalk.lookup(query)
        (matched if record["matched"] else unmatched).append(record)
    return matched, unmatched


def write_outputs(
    matched: list[dict[str, Any]], unmatched: list[dict[str, Any]], out_dir: str | Path
) -> dict[str, str]:
    out_dir = Path(out_dir)
    return {
        "crosswalk.csv": atomic_csv(out_dir / "crosswalk.csv", CROSSWALK_COLUMNS, matched),
        "unmatched.csv": atomic_csv(out_dir / "unmatched.csv", UNMATCHED_COLUMNS, unmatched),
    }


# ---------------------------------------------------------------- tests / reports


def round_trip(archive: str | Path, tour: str, season: int = 2024) -> dict[str, Any]:
    """The Elo crosswalk's own 2024 round trip, re-run against both crosswalks.

    Same three rendering styles, same player set: every player with a 2024 included
    tour-level main-draw match.  Reported side by side so the change is attributable.
    """
    if season in RESERVED_YEARS:
        raise ChainError(f"season {season} is inside the reserved outcome window")
    old = _elo_crosswalk.build(archive, tour)
    new = build(archive, tour)
    rows, _stats, _hashes = _mirror.extract_results(archive, tour, [season])
    season_ids = sorted(
        {str(row["winner_id"]) for row in rows} | {str(row["loser_id"]) for row in rows}
    )
    reference = {player.player_id: player for player in _elo_crosswalk.load_players(archive, tour)}
    players = [reference[pid] for pid in season_ids if pid in reference]
    styles = {
        "draw_full_name": lambda p: p.display,
        "draw_full_name_with_disambiguator": lambda p: f"{p.display} (tennis)",
        "odds_api_full_name": lambda p: f"{p.name_first} {p.name_last}".strip(),
        "tennis_data_surname_initial": (
            lambda p: f"{p.name_last} {p.name_first[:1]}." if p.name_first else p.name_last
        ),
    }
    report: dict[str, Any] = {
        "tour": tour,
        "season": season,
        "season_player_ids": len(season_ids),
        "season_player_ids_present_in_players_file": len(players),
        "active_reference_players": len(old.active),
        "full_reference_players": new.full.rows,
        "styles": {},
    }
    for style_name, render in styles.items():
        entry: dict[str, Any] = {}
        for label, walk in (("frozen_elo_crosswalk", old), ("crosswalk_v2", new)):
            correct = wrong = unresolved = 0
            methods: Counter[str] = Counter()
            failures: list[dict[str, str]] = []
            for player in players:
                record = walk.lookup(render(player))
                if not record["matched"]:
                    unresolved += 1
                    failures.append(
                        {
                            "name": render(player),
                            "expected_id": player.player_id,
                            "reason": str(record.get("reason", "")),
                        }
                    )
                elif str(record["player_id"]) == player.player_id:
                    correct += 1
                    methods[str(record["match_method"])] += 1
                else:
                    wrong += 1
                    failures.append(
                        {
                            "name": render(player),
                            "expected_id": player.player_id,
                            "reason": f"wrong_id_{record['player_id']}",
                        }
                    )
            entry[label] = {
                "queries": len(players),
                "correct_id": correct,
                "wrong_id": wrong,
                "unresolved": unresolved,
                "coverage": correct / len(players) if players else 0.0,
                "methods_used": dict(sorted(methods.items())),
                "failures": len(failures),
                "failure_examples": failures[:10],
            }
        entry["unresolved_change"] = (
            entry["crosswalk_v2"]["unresolved"] - entry["frozen_elo_crosswalk"]["unresolved"]
        )
        entry["wrong_id_change"] = (
            entry["crosswalk_v2"]["wrong_id"] - entry["frozen_elo_crosswalk"]["wrong_id"]
        )
        report["styles"][style_name] = entry
    return report


def self_id_check(archive: str | Path, tour: str, season: int = 2024) -> dict[str, Any]:
    """Every winner and loser name in the mirror's own season file must resolve to its id.

    This is the strict version of the round trip: the *name as the mirror writes it*
    on every included row, not a rendered style, and the id the mirror puts beside it.
    """
    if season in RESERVED_YEARS:
        raise ChainError(f"season {season} is inside the reserved outcome window")
    walk = build(archive, tour)
    old = _elo_crosswalk.build(archive, tour)
    rows, stats, hashes = _mirror.extract_results(archive, tour, [season])
    pairs: Counter[tuple[str, str]] = Counter()
    for row in rows:
        pairs[(str(row["winner_name"]), str(row["winner_id"]))] += 1
        pairs[(str(row["loser_name"]), str(row["loser_id"]))] += 1
    result: dict[str, Any] = {
        "tour": tour,
        "season": season,
        "member_sha256": hashes,
        "included_rows": stats.get("included", 0),
        "distinct_name_id_pairs": len(pairs),
    }
    for label, crosswalk in (("frozen_elo_crosswalk", old), ("crosswalk_v2", walk)):
        correct = wrong = unresolved = 0
        methods: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        failures: list[dict[str, Any]] = []
        for (name, player_id), appearances in sorted(pairs.items()):
            record = crosswalk.lookup(name)
            if not record["matched"]:
                unresolved += 1
                reasons[str(record.get("reason", ""))] += 1
                failures.append(
                    {
                        "name": name,
                        "expected_id": player_id,
                        "reason": str(record.get("reason", "")),
                        "rows": appearances,
                    }
                )
            elif str(record["player_id"]) == player_id:
                correct += 1
                methods[str(record["match_method"])] += 1
            else:
                wrong += 1
                failures.append(
                    {
                        "name": name,
                        "expected_id": player_id,
                        "reason": f"wrong_id_{record['player_id']}",
                        "rows": appearances,
                    }
                )
        result[label] = {
            "queries": len(pairs),
            "resolved_to_own_id": correct,
            "wrong_id": wrong,
            "unresolved": unresolved,
            "coverage": correct / len(pairs) if pairs else 0.0,
            "methods_used": dict(sorted(methods.items())),
            "unresolved_reasons": dict(sorted(reasons.items())),
            "failure_examples": failures[:15],
        }
    result["unresolved_change"] = (
        result["crosswalk_v2"]["unresolved"] - result["frozen_elo_crosswalk"]["unresolved"]
    )
    result["wrong_id_change"] = (
        result["crosswalk_v2"]["wrong_id"] - result["frozen_elo_crosswalk"]["wrong_id"]
    )
    result["status"] = "PASS" if result["crosswalk_v2"]["wrong_id"] == 0 else "FAIL"
    return result


def _duplicate_name_groups(index: FullFileIndex) -> dict[str, list[str]]:
    """Player ids grouped by normalized display name, over the whole players file.

    `atp_players.csv` really does carry duplicate records for the same person -- for
    instance 211776 and 212021 are both "Martin Landaluce" -- so an exact full-name hit
    that is unique *within the active set* can still be the wrong record of a pair when
    the active set is artificially narrowed.  The held-out test classifies such a wrong
    id separately, because it is a source defect rather than a matching error.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for player_id, player in index.by_id.items():
        groups[normalize_name(player.display)].append(player_id)
    return dict(groups)


def held_out_activity(
    archive: str | Path, tour: str, season: int = 2024, activity: tuple[int, ...] = (2021, 2022)
) -> dict[str, Any]:
    """Exercise the full-file fallback on exposed data by narrowing the activity window.

    The 2024 self-id and round-trip tests cannot exercise repair (2): every player with
    a 2024 match is in the 2023-2024 active set by construction, so the fallback is
    never reached.  Narrowing the activity window to 2021-2022 and then querying the
    *2024* name set reproduces the real 2025/2026 condition -- a player absent from the
    active set -- using only exposed seasons.
    """
    for year in (season, *activity):
        if year in RESERVED_YEARS:
            raise ChainError(f"year {year} is inside the reserved outcome window")
    old = _elo_crosswalk.build(archive, tour, activity)
    new = CrosswalkV2(old, FullFileIndex(_elo_crosswalk.load_players(archive, tour)), tour.upper())
    rows, _stats, _hashes = _mirror.extract_results(archive, tour, [season])
    pairs = sorted(
        {(str(row["winner_name"]), str(row["winner_id"])) for row in rows}
        | {(str(row["loser_name"]), str(row["loser_id"])) for row in rows}
    )
    result: dict[str, Any] = {
        "tour": tour.upper(),
        "season_queried": season,
        "activity_window": list(activity),
        "active_reference_players": len(old.active),
        "full_reference_players": new.full.rows,
        "distinct_name_id_pairs": len(pairs),
    }
    for label, crosswalk, accepted in (
        ("active_window_only", old, ACCEPTED_CONFIDENCE | {"low"}),
        ("crosswalk_v2_with_fallback", new, ACCEPTED_CONFIDENCE | {"low"}),
        ("crosswalk_v2_high_and_medium_only", new, ACCEPTED_CONFIDENCE),
    ):
        correct = wrong = unresolved = wrong_duplicate_record = 0
        methods: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        failures: list[dict[str, Any]] = []
        for name, player_id in pairs:
            record = crosswalk.lookup(name)
            if (
                record["matched"]
                and CONFIDENCE.get(str(record["match_method"]), "low") not in accepted
            ):
                record = {
                    **record,
                    "matched": False,
                    "reason": f"below_accepted_confidence_{record['match_method']}",
                }
            if not record["matched"]:
                unresolved += 1
                reasons[str(record.get("reason", ""))] += 1
                failures.append(
                    {
                        "name": name,
                        "expected_id": player_id,
                        "reason": str(record.get("reason", "")),
                    }
                )
            elif str(record["player_id"]) == player_id:
                correct += 1
                methods[str(record["match_method"])] += 1
            else:
                wrong += 1
                returned = str(record["player_id"])
                duplicate = (
                    normalize_name(new.full.by_id[returned].display)
                    == normalize_name(new.full.by_id[player_id].display)
                    if returned in new.full.by_id and player_id in new.full.by_id
                    else False
                )
                if duplicate:
                    wrong_duplicate_record += 1
                failures.append(
                    {
                        "name": name,
                        "expected_id": player_id,
                        "reason": f"wrong_id_{returned}",
                        "method": str(record["match_method"]),
                        "players_file_duplicate_record": duplicate,
                    }
                )
        result[label] = {
            "queries": len(pairs),
            "resolved_to_own_id": correct,
            "wrong_id": wrong,
            "wrong_id_players_file_duplicate_record": wrong_duplicate_record,
            "wrong_id_not_explained_by_a_duplicate_record": wrong - wrong_duplicate_record,
            "unresolved": unresolved,
            "coverage": correct / len(pairs) if pairs else 0.0,
            "methods_used": dict(sorted(methods.items())),
            "unresolved_reasons": dict(sorted(reasons.items())),
            "failure_examples": failures[:15],
        }
    result["players_file_duplicate_normalized_names"] = sum(
        1 for ids in _duplicate_name_groups(new.full).values() if len(ids) > 1
    )
    result["unresolved_change"] = (
        result["crosswalk_v2_with_fallback"]["unresolved"]
        - result["active_window_only"]["unresolved"]
    )
    result["wrong_id_change"] = (
        result["crosswalk_v2_with_fallback"]["wrong_id"] - result["active_window_only"]["wrong_id"]
    )
    # The gate is "no regression, and none of the wrong ids survive the confidence
    # filter the bridge applies".  The 2 wrong ids per tour in *both* unfiltered
    # columns come from the frozen active-set `surname_unique` method picking a
    # different family member once the activity window is narrowed; they are a
    # pre-existing property of that low-confidence method, not an effect of the
    # fallback, and `ACCEPTED_CONFIDENCE` excludes them.
    result["status"] = (
        "PASS"
        if result["unresolved_change"] <= 0
        and result["wrong_id_change"] <= 0
        and result["crosswalk_v2_high_and_medium_only"][
            "wrong_id_not_explained_by_a_duplicate_record"
        ]
        == 0
        else "FAIL"
    )
    return result


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default=ARCHIVE_DEFAULT)
    parser.add_argument("--tour", default="ATP")
    parser.add_argument("--names", help="text file, one source name per line")
    parser.add_argument("--out-dir", default="work/CONFIRM2026_joint04/crosswalk_v2")
    parser.add_argument("--round-trip", action="store_true")
    parser.add_argument("--self-id-check", action="store_true")
    parser.add_argument(
        "--held-out-activity",
        action="store_true",
        help="narrow the activity window to 2021-2022 and query the season name set",
    )
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    archive = _mirror.resolve_archive(args.archive)

    if args.round_trip or args.self_id_check or args.held_out_activity:
        report: dict[str, Any] = {
            "activity_window": list(ACTIVITY_YEARS),
            "season_tested": args.season,
            "reserved_files_never_opened": [
                f"{ARCHIVE_ROOT}/{tour}/{tour}_matches_{year}.csv"
                for tour in ("atp", "wta")
                for year in RESERVED_YEARS
            ],
        }
        tours = ("ATP", "WTA")
        if args.round_trip:
            report["round_trip"] = [round_trip(archive, tour, args.season) for tour in tours]
        statuses = []
        if args.self_id_check:
            report["self_id_check"] = [self_id_check(archive, tour, args.season) for tour in tours]
            statuses += [item["status"] for item in report["self_id_check"]]
        if args.held_out_activity:
            report["held_out_activity"] = [
                held_out_activity(archive, tour, args.season) for tour in tours
            ]
            statuses += [item["status"] for item in report["held_out_activity"]]
        if statuses:
            report["status"] = "PASS" if all(value == "PASS" for value in statuses) else "FAIL"
        text = json.dumps(report, indent=2, sort_keys=True)
        if args.report:
            atomic_json(args.report, report)
        print(text)
        return 0 if report.get("status", "PASS") == "PASS" else 1

    if not args.names:
        parser.error("--names, --round-trip or --self-id-check is required")
    queries = [
        line.strip()
        for line in Path(args.names).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    crosswalk = build(archive, args.tour)
    matched, unmatched = resolve_many(crosswalk, queries)
    outputs = write_outputs(matched, unmatched, args.out_dir)
    print(
        json.dumps(
            {
                "queries": len(queries),
                "matched": len(matched),
                "unmatched": len(unmatched),
                "by_method": dict(sorted(Counter(row["match_method"] for row in matched).items())),
                "by_population": dict(
                    sorted(Counter(row["reference_population"] for row in matched).items())
                ),
                "outputs": outputs,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
