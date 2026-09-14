"""Map source player names onto Sackmann player ids.

Base revision: ``references/CONFIRM2026_elo/crosswalk.py`` (the only revision; the
later ``crosswalk_v2.py`` in TIER01_models/WTA02_models wraps this one and is a
separate port). Normalisation, the method order, the ambiguity quarantine, the
output column order and the round-trip report are carried over unchanged.

What changed in the port: the ``sys.path`` insertion and the sibling imports
``from elo_engine import ...`` / ``from mirror import ...`` are replaced by package
imports (``tennislab.ratings.elo``, ``tennislab.panel.mirror``); the names they
brought into this module's namespace are still re-exported, because
``crosswalk_v2`` reads several of them off this module. The ``_cli`` resolves its
``--archive``, ``--names``, ``--out-dir`` and ``--report`` through
:func:`tennislab.chain.common.resolve_under_root`.

Why this exists: ``work/CONFIRM2026_feasibility.md`` section 9 records that the
repository has no general name -> id table. The two existing files are
deliberately row-scoped (``work/MULTI01_player_aliases/derived/accepted_alias_mappings.csv``,
8 rows, "apply only when alias, season, source path and source row appear in
row_context_validation.csv"; ``data/raw/MQ01/identity_crosswalk.csv``, 4 rows,
"accepted_for_this_case_only"). Neither is a spelling-global substitution table
and this module does not turn them into one -- it produces a *candidate*
crosswalk with an explicit method and confidence per row, plus an
``unmatched.csv`` for manual review. Nothing here is authoritative identity.

Reference population: ``atp_players.csv`` / ``wta_players.csv`` inside the
preserved mirror, restricted to players with at least one included tour-level
main-draw match in 2023-2024 (that activity window is the whole reason the
ambiguity rate is tolerable -- 66,912 ATP and 70,571 WTA lifetime rows collide
far more often than the active set does).

RESERVED WINDOW: activity is derived from the 2023 and 2024 match files only.
The 2025 and 2026 match files are referenced by NAME ONLY (see
``reserved_files_listed_not_read`` in the report) and are never opened; the
guard lives in ``tennislab.panel.mirror.guard_member``.

Normalization: lowercase, ASCII fold (NFKD + drop combining marks + drop
non-ASCII), every non-alphanumeric character becomes a space, whitespace
collapsed. So "Ramos-Vinolas" -> "ramos vinolas", "Zverev A." -> "zverev a".

Match methods, tried in this order and stopping at the first that resolves
uniquely:
  1. ``exact_full``        -- normalized "first last" (or "last first") equal.
  2. ``surname_initial``   -- normalized surname equal AND first initial equal.
  3. ``surname_unique``    -- normalized surname equal and unique in the active set.
A method that resolves to more than one active id does not fall through to a
weaker method; the query is written to ``unmatched.csv`` with
``reason=ambiguous_<method>`` and its candidate ids, because silently choosing
one of several real players is the failure mode this repository has already
been burned by (``kuznetsov_collision_candidates.csv``).

Public interface kept for:

* ``references/TIER01_models/crosswalk_v2.py`` and
  ``references/WTA02_models/crosswalk_v2.py`` (``_elo_crosswalk``): ``Player``,
  ``ACTIVITY_YEARS``, ``TENNIS_DATA_STYLE``, ``load_players``, ``build``, and the
  ``Crosswalk`` attributes ``active``, ``by_id`` and method ``lookup``. Those two
  files also read ``ARCHIVE_DEFAULT``, ``ARCHIVE_ROOT`` and ``RESERVED_YEARS`` off
  ``mirror``; this module keeps re-exporting them as the archive copy did.
* ``experiments/runs/CONFIRM2026/elo_001/build_stream.py``: ``build``.
* The archive unit tests (now ``tests/test_elo_crosswalk.py``): ``round_trip``,
  ``resolve_many``, ``write_outputs``, ``CROSSWALK_COLUMNS``,
  ``UNMATCHED_COLUMNS``, ``CONFIDENCE``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from tennislab.chain.common import resolve_under_root
from tennislab.panel.mirror import (
    ARCHIVE_DEFAULT,
    ARCHIVE_ROOT,
    RESERVED_YEARS,
    extract_results,
    read_member_rows,
    resolve_archive,
)
from tennislab.ratings.elo import normalize_name

__all__ = [
    "ACTIVITY_YEARS",
    "ARCHIVE_DEFAULT",
    "ARCHIVE_ROOT",
    "CONFIDENCE",
    "CROSSWALK_COLUMNS",
    "RESERVED_YEARS",
    "TENNIS_DATA_STYLE",
    "UNMATCHED_COLUMNS",
    "Crosswalk",
    "Player",
    "build",
    "extract_results",
    "load_players",
    "normalize_name",
    "read_member_rows",
    "resolve_archive",
    "resolve_many",
    "round_trip",
    "write_outputs",
]

ACTIVITY_YEARS = (2023, 2024)
# tennis-data market style: "Zverev A.", "Ramos-Vinolas A.", "Bautista Agut R."
TENNIS_DATA_STYLE = re.compile(r"^(?P<last>.+?)\s+(?P<initial>[A-Za-z])\.?$")

CROSSWALK_COLUMNS = (
    "query_name",
    "query_style",
    "tour",
    "player_id",
    "sackmann_name",
    "match_method",
    "confidence",
    "candidates_considered",
)
UNMATCHED_COLUMNS = ("query_name", "query_style", "tour", "reason", "candidate_ids")

CONFIDENCE = {
    "exact_full": "high",
    "surname_initial": "medium",
    "surname_unique": "low",
}


@dataclass(frozen=True)
class Player:
    player_id: str
    name_first: str
    name_last: str
    ioc: str

    @property
    def display(self) -> str:
        return f"{self.name_first} {self.name_last}".strip()


class Crosswalk:
    def __init__(self, players: list[Player], active_ids: set[str]):
        self.active = [p for p in players if p.player_id in active_ids]
        self.by_id = {p.player_id: p for p in self.active}
        self.full: dict[str, list[str]] = defaultdict(list)
        self.surname_initial: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.surname: dict[str, list[str]] = defaultdict(list)
        for player in self.active:
            first = normalize_name(player.name_first)
            last = normalize_name(player.name_last)
            if first and last:
                self.full[f"{first} {last}"].append(player.player_id)
                reversed_key = f"{last} {first}"
                if reversed_key != f"{first} {last}":
                    self.full[reversed_key].append(player.player_id)
            elif last:
                self.full[last].append(player.player_id)
            if last and first:
                self.surname_initial[(last, first[0])].append(player.player_id)
            if last:
                self.surname[last].append(player.player_id)

    def lookup(self, query: str) -> dict[str, object]:
        """Return a resolution record: method, player_id (or None) and candidates."""
        raw = (query or "").strip()
        style = "full_name"
        attempts: list[tuple[str, list[str]]] = []
        tennis_data = TENNIS_DATA_STYLE.match(raw)
        surname_guess = ""
        initial_guess = ""
        normalized = normalize_name(raw)
        if tennis_data and "." in raw:
            style = "surname_initial"
            surname_guess = normalize_name(tennis_data.group("last"))
            initial_guess = normalize_name(tennis_data.group("initial"))
        else:
            tokens = normalized.split()
            if len(tokens) >= 2:
                surname_guess = " ".join(tokens[1:])
                initial_guess = tokens[0][0]
            elif tokens:
                surname_guess = tokens[0]

        if style == "full_name" and normalized:
            attempts.append(("exact_full", list(dict.fromkeys(self.full.get(normalized, [])))))
        if surname_guess and initial_guess:
            attempts.append(
                (
                    "surname_initial",
                    list(
                        dict.fromkeys(self.surname_initial.get((surname_guess, initial_guess), []))
                    ),
                )
            )
        if surname_guess:
            attempts.append(
                ("surname_unique", list(dict.fromkeys(self.surname.get(surname_guess, []))))
            )

        for method, candidates in attempts:
            if len(candidates) == 1:
                player = self.by_id[candidates[0]]
                return {
                    "query_name": raw,
                    "query_style": style,
                    "player_id": player.player_id,
                    "sackmann_name": player.display,
                    "match_method": method,
                    "confidence": CONFIDENCE[method],
                    "candidates_considered": 1,
                    "matched": True,
                }
            if len(candidates) > 1:
                return {
                    "query_name": raw,
                    "query_style": style,
                    "player_id": None,
                    "match_method": method,
                    "reason": f"ambiguous_{method}",
                    "candidate_ids": ";".join(candidates),
                    "matched": False,
                }
        return {
            "query_name": raw,
            "query_style": style,
            "player_id": None,
            "match_method": "",
            "reason": "no_candidate",
            "candidate_ids": "",
            "matched": False,
        }


def load_players(archive: str | Path, tour: str) -> list[Player]:
    member = f"{ARCHIVE_ROOT}/{tour.lower()}/{tour.lower()}_players.csv"
    rows, _digest = read_member_rows(archive, member)
    return [
        Player(
            row["player_id"],
            row.get("name_first", ""),
            row.get("name_last", ""),
            row.get("ioc", ""),
        )
        for row in rows
        if row.get("player_id")
    ]


def build(archive: str | Path, tour: str, years: tuple[int, ...] = ACTIVITY_YEARS) -> Crosswalk:
    rows, _stats, _hashes = extract_results(archive, tour, list(years))
    active = {str(r["winner_id"]) for r in rows} | {str(r["loser_id"]) for r in rows}
    return Crosswalk(load_players(archive, tour), active)


def resolve_many(
    crosswalk: Crosswalk, queries: list[str], tour: str
) -> tuple[list[dict], list[dict]]:
    matched: list[dict] = []
    unmatched: list[dict] = []
    for query in queries:
        record = crosswalk.lookup(query)
        record["tour"] = tour
        (matched if record["matched"] else unmatched).append(record)
    return matched, unmatched


def write_outputs(matched: list[dict], unmatched: list[dict], out_dir: str | Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "crosswalk.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CROSSWALK_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(matched)
    with open(out_dir / "unmatched.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=UNMATCHED_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unmatched)


def round_trip(archive: str | Path, tour: str, season: int = 2024) -> dict[str, object]:
    """Test: regenerate every name style for the full season player set and map it back."""
    crosswalk = build(archive, tour)
    rows, _stats, _hashes = extract_results(archive, tour, [season])
    season_ids = sorted({str(r["winner_id"]) for r in rows} | {str(r["loser_id"]) for r in rows})
    players = [crosswalk.by_id[pid] for pid in season_ids if pid in crosswalk.by_id]
    styles = {
        "draw_full_name": lambda p: p.display,
        "odds_api_full_name": lambda p: f"{p.name_first} {p.name_last}".strip(),
        "tennis_data_surname_initial": lambda p: (
            f"{p.name_last} {p.name_first[:1]}." if p.name_first else p.name_last
        ),
    }
    report: dict[str, object] = {
        "tour": tour,
        "season": season,
        "season_player_ids": len(season_ids),
        "season_player_ids_present_in_players_file": len(players),
        "active_reference_players": len(crosswalk.active),
        "styles": {},
    }
    for style_name, render in styles.items():
        correct = wrong = unresolved = 0
        methods: dict[str, int] = defaultdict(int)
        failures: list[dict[str, str]] = []
        for player in players:
            record = crosswalk.lookup(render(player))
            if not record["matched"]:
                unresolved += 1
                failures.append(
                    {
                        "name": render(player),
                        "expected_id": player.player_id,
                        "reason": str(record["reason"]),
                    }
                )
            elif record["player_id"] == player.player_id:
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
        total = len(players)
        report["styles"][style_name] = {
            "queries": total,
            "correct_id": correct,
            "wrong_id": wrong,
            "unresolved": unresolved,
            "coverage": correct / total if total else 0.0,
            "methods_used": dict(sorted(methods.items())),
            "failure_examples": failures[:15],
            "failures": len(failures),
        }
    return report


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Name -> Sackmann player id crosswalk")
    parser.add_argument("--archive", default=ARCHIVE_DEFAULT)
    parser.add_argument("--tour", default="ATP")
    parser.add_argument("--names", help="text file, one source name per line")
    parser.add_argument("--out-dir", default="work/CONFIRM2026_elo/crosswalk")
    parser.add_argument(
        "--round-trip", action="store_true", help="run the 2024 full-player-set round trip"
    )
    parser.add_argument("--report", help="write the round-trip report JSON here")
    args = parser.parse_args(argv)
    archive = resolve_archive(args.archive)

    if args.round_trip:
        report = {
            "activity_window": list(ACTIVITY_YEARS),
            "reserved_files_listed_not_read": [
                f"{ARCHIVE_ROOT}/{t}/{t}_matches_{y}.csv"
                for t in ("atp", "wta")
                for y in RESERVED_YEARS
            ],
            "runs": [round_trip(archive, tour) for tour in ("ATP", "WTA")],
        }
        text = json.dumps(report, indent=2)
        if args.report:
            resolve_under_root(args.report, label="report").write_text(
                text + "\n", encoding="utf-8"
            )
        print(text)
        return 0

    if not args.names:
        parser.error("--names or --round-trip is required")
    names_path = resolve_under_root(args.names, label="names")
    queries = [
        line.strip() for line in names_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    crosswalk = build(archive, args.tour)
    matched, unmatched = resolve_many(crosswalk, queries, args.tour)
    out_dir = resolve_under_root(args.out_dir, label="out_dir")
    write_outputs(matched, unmatched, out_dir)
    print(
        json.dumps(
            {
                "queries": len(queries),
                "matched": len(matched),
                "unmatched": len(unmatched),
                "out_dir": args.out_dir,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
