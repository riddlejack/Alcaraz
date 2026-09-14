"""Read the preserved Sackmann mirror and emit the canonical results schema.

Base revision: ``references/CONFIRM2026_elo/mirror.py`` (the only revision). The
event rule, status classification, exclusion counters, row filter, sort key and CSV
column order are carried over unchanged: the CONFIRM2026 results stream this module
produces is compared byte-for-byte.

What changed in the port: ``ARCHIVE_DEFAULT`` stays a workspace-relative *string*
and is turned into a path only by :func:`resolve_archive`, which goes through
:func:`tennislab.chain.common.resolve_under_root`; the ``_cli`` resolves its
``--archive`` and ``--out`` the same way. The low-level readers still accept any
``str | Path`` so a caller can hand them a fixture or an already-resolved path.

Source: ``data/raw/ARCHIVE01/snapshot/tennis-sackmann-archive-<commit>.tar.gz``
(the mirror is preserved as a tarball; nothing is extracted to disk).

Scope and exclusions are copied from ``work/MULTI01_archive_panel/build_archive_panel.py``:
``TEAM_EVENTS`` / ``NEXTGEN_EVENTS`` / ``TOUR_FINALS_EVENTS`` (lines 45-47),
``event_rule`` (lines 115-127) and ``classify_status`` (lines 100-112); the row
filter then matches ``build_features.parse_record`` (lines 297-310): played,
not walkover, not abandoned, status in {completed, retired, default}.

DATE LIMIT, stated because it is the reason a mirror-only replay cannot
reproduce the MULTI01 Elo columns: the Sackmann annual files carry only
``tourney_date`` (the event anchor). MULTI01's per-match ``match_date`` comes
from the tennis-data annual market join, and differs from the anchor on 86% of
its rows (offsets -2..+14 days). ``date_rule='event_anchor'`` is therefore the
only date this module can honestly emit from the mirror alone.

RESERVED-WINDOW GUARD: every member path is checked against
``FORBIDDEN_MEMBER_PATTERN`` before it is opened. 2025 and 2026 match files are
refused, so this module cannot read a reserved outcome even if asked to.

``ReservedWindowError`` stays a ``RuntimeError`` rather than a ``ChainError``: it is
the guard other unported archive programs catch by that base, and it already fails
closed. Narrowing it is a separate, whole-repository change.

Public interface kept for:

* ``references/TIER01_models/crosswalk_v2.py`` and
  ``references/WTA02_models/crosswalk_v2.py`` (``_mirror``): ``ARCHIVE_DEFAULT``,
  ``ARCHIVE_ROOT``, ``RESERVED_YEARS``, ``extract_results``.
* ``references/CONFIRM2026_elo/crosswalk.py`` -> ``tennislab.panel.elo_crosswalk``:
  ``ARCHIVE_DEFAULT``, ``ARCHIVE_ROOT``, ``RESERVED_YEARS``, ``extract_results``,
  ``read_member_rows``.
* ``references/CONFIRM2026_elo/regression.py``: ``ARCHIVE_DEFAULT``,
  ``extract_results``.
* ``experiments/runs/CONFIRM2026/elo_001/build_stream.py``: ``ARCHIVE_DEFAULT``,
  ``extract_results``.
* The archive unit tests (now ``tests/test_mirror.py``): ``ReservedWindowError``,
  ``guard_member``, ``extract_results``.
* Kept because they are part of the module's declared surface and have no other
  home: ``list_members``, ``classify_status``, ``event_rule``, ``anchor_date``,
  ``CANONICAL_COLUMNS``, ``write_results_csv``, ``active_player_ids``,
  ``TEAM_EVENTS``, ``NEXTGEN_EVENTS``, ``TOUR_FINALS_EVENTS``, ``SURFACES``,
  ``TOUR_LEVELS``, ``TOUR_FINALS_BY_TOUR``, ``TEAM_EVENT_SUBSTRINGS``,
  ``ACCEPTED_STATUS``, ``FORBIDDEN_MEMBER_PATTERN``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import tarfile
from collections import Counter
from pathlib import Path

from tennislab.chain.common import resolve_under_root

ARCHIVE_DEFAULT = "data/raw/ARCHIVE01/snapshot/tennis-sackmann-archive-83733587353df8a41f2fd4f516147d5aa83f5a8d.tar.gz"
ARCHIVE_ROOT = "tennis-sackmann-archive-83733587353df8a41f2fd4f516147d5aa83f5a8d"

# build_archive_panel.py lines 45-48, verbatim (ATP scope).
TEAM_EVENTS = {"atp cup", "united cup", "laver cup"}
NEXTGEN_EVENTS = {"nextgen finals", "next gen finals"}
TOUR_FINALS_EVENTS = {"masters cup", "tour finals"}
SURFACES = {"Hard", "Clay", "Grass", "Carpet"}

# DECLARED EXTENSION, not inherited: MULTI01 never scoped the WTA, so the WTA
# tour-level vocabulary below is new work and is labelled as such. WTA
# tour-level main draws are levels G / PM / P / I; level D is the BJK Cup (a
# team event) and is excluded the same way ATP level D (Davis Cup) already was.
TOUR_LEVELS = {"ATP": {"A", "M", "G"}, "WTA": {"G", "PM", "P", "I"}}
TOUR_FINALS_BY_TOUR = {
    "ATP": TOUR_FINALS_EVENTS,
    "WTA": TOUR_FINALS_EVENTS | {"riyadh finals", "wta finals", "wta tour finals"},
}
TEAM_EVENT_SUBSTRINGS = ("bjk cup", "fed cup", "davis cup", "billie jean king cup")

ACCEPTED_STATUS = {"completed", "retired", "default"}

# Reserved outcome window. Any member matching this is refused outright.
FORBIDDEN_MEMBER_PATTERN = re.compile(
    r"(?:_|/)(?:matches|matches_qual_chall|matches_doubles)_(?:2025|2026)\.csv$|(?:2025|2026)\.csv$|RES2026",
    re.IGNORECASE,
)
RESERVED_YEARS = (2025, 2026)


class ReservedWindowError(RuntimeError):
    """Raised when a member inside the reserved outcome window is requested."""


def resolve_archive(value: str | Path = ARCHIVE_DEFAULT) -> Path:
    """The workspace path of a mirror tarball named by a workspace-relative string."""
    return resolve_under_root(value, label="archive")


def guard_member(member: str) -> None:
    if FORBIDDEN_MEMBER_PATTERN.search(member):
        raise ReservedWindowError(
            f"refusing to open {member!r}: inside the reserved 2025/2026 outcome window"
        )


def list_members(archive: str | Path) -> list[tuple[str, int]]:
    """Names and sizes only -- never opens a member."""
    with tarfile.open(archive, "r:gz") as tar:
        return [(info.name, info.size) for info in tar.getmembers() if info.isfile()]


def read_member_rows(archive: str | Path, member: str) -> tuple[list[dict[str, str]], str]:
    """Return (rows, sha256 of the member bytes). Guarded."""
    guard_member(member)
    with tarfile.open(archive, "r:gz") as tar:
        handle = tar.extractfile(member)
        if handle is None:
            raise FileNotFoundError(member)
        payload = handle.read()
    digest = hashlib.sha256(payload).hexdigest()
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    return list(reader), digest


def classify_status(score: str) -> tuple[str, str]:
    """build_archive_panel.py lines 100-112, verbatim."""
    text = (score or "").strip().upper()
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


def event_rule(row: dict[str, str], tour: str = "ATP") -> tuple[bool, str, str]:
    """build_archive_panel.py lines 115-127 for ATP; WTA levels are the declared
    extension documented at TOUR_LEVELS."""
    name = (row.get("tourney_name") or "").strip().lower()
    if name in TEAM_EVENTS or any(token in name for token in TEAM_EVENT_SUBSTRINGS):
        return False, "excluded_team", "team"
    if name in NEXTGEN_EVENTS:
        return False, "excluded_nextgen", "nextgen"
    if name in TOUR_FINALS_BY_TOUR[tour]:
        return True, "main_tour_finals", "tour_finals"
    if "olympic" in name:
        return (
            True,
            "olympics_consistency_override" if row.get("tourney_level") == "O" else "level_A",
            "olympics",
        )
    if row.get("tourney_level") in TOUR_LEVELS[tour]:
        return True, f"level_{row['tourney_level']}", "individual_tour"
    return False, "excluded_other_level", "other"


def anchor_date(raw: str) -> dt.date:
    raw = (raw or "").strip()
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"unparseable tourney_date {raw!r}")
    return dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def extract_results(
    archive: str | Path,
    tour: str,
    years: list[int],
) -> tuple[list[dict[str, object]], dict[str, int], dict[str, str]]:
    """Emit canonical-schema rows plus exclusion counts and member hashes."""
    tour = tour.upper()
    if tour not in {"ATP", "WTA"}:
        raise ValueError(f"unsupported tour {tour!r}")
    for year in years:
        if year in RESERVED_YEARS:
            raise ReservedWindowError(f"year {year} is inside the reserved outcome window")
    stats: Counter[str] = Counter()
    hashes: dict[str, str] = {}
    out: list[dict[str, object]] = []
    for year in sorted(years):
        member = f"{ARCHIVE_ROOT}/{tour.lower()}/{tour.lower()}_matches_{year}.csv"
        rows, digest = read_member_rows(archive, member)
        hashes[member] = digest
        stats["source_rows"] += len(rows)
        for row in rows:
            include, _basis, competition_type = event_rule(row, tour)
            if not include:
                stats["excluded_event"] += 1
                continue
            status, played = classify_status(row.get("score", ""))
            if played != "true" or status not in ACCEPTED_STATUS:
                stats[f"excluded_status_{status}"] += 1
                continue
            surface = (row.get("surface") or "").strip()
            if surface not in SURFACES:
                stats["excluded_surface"] += 1
                continue
            best_of = (row.get("best_of") or "").strip()
            if best_of not in {"3", "5"}:
                stats["excluded_best_of"] += 1
                continue
            if not (row.get("winner_id") or "").strip() or not (row.get("loser_id") or "").strip():
                stats["excluded_missing_id"] += 1
                continue
            stats["included"] += 1
            out.append(
                {
                    "date": anchor_date(row["tourney_date"]).isoformat(),
                    "tour": tour,
                    "tournament": (row.get("tourney_name") or "").strip(),
                    "level": (row.get("tourney_level") or "").strip(),
                    "round": (row.get("round") or "").strip(),
                    "surface": surface,
                    "best_of": best_of,
                    # outcome-history read: winner/loser of a non-reserved season
                    "winner_id": row["winner_id"].strip(),
                    "loser_id": row["loser_id"].strip(),
                    "winner_name": (row.get("winner_name") or "").strip(),
                    "loser_name": (row.get("loser_name") or "").strip(),
                    "source": f"{member}#{row.get('tourney_id', '')}/{row.get('match_num', '')}",
                    "tourney_id": (row.get("tourney_id") or "").strip(),
                    "match_num": (row.get("match_num") or "").strip(),
                    "competition_type": competition_type,
                }
            )
    # Chronological, then the mirror's own within-file order (tourney_id, match_num).
    out.sort(key=lambda r: (r["date"], r["tourney_id"], int(r["match_num"] or 0)))
    return out, dict(sorted(stats.items())), hashes


CANONICAL_COLUMNS = (
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
)


def write_results_csv(
    rows: list[dict[str, object]], path: str | Path, *, extra_columns: tuple[str, ...] = ()
) -> None:
    columns = list(CANONICAL_COLUMNS) + list(extra_columns)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def active_player_ids(archive: str | Path, tour: str, years: list[int]) -> set[str]:
    """Player ids with at least one included match in ``years``."""
    rows, _stats, _hashes = extract_results(archive, tour, years)
    return {str(row["winner_id"]) for row in rows} | {str(row["loser_id"]) for row in rows}


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract canonical results rows from the Sackmann mirror."
    )
    parser.add_argument("--archive", default=ARCHIVE_DEFAULT)
    parser.add_argument("--tour", default="ATP")
    parser.add_argument("--year-min", type=int, default=2005)
    parser.add_argument("--year-max", type=int, default=2024)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--keep-source-keys", action="store_true", help="also write tourney_id/match_num"
    )
    args = parser.parse_args(argv)
    years = list(range(args.year_min, args.year_max + 1))
    rows, stats, hashes = extract_results(resolve_archive(args.archive), args.tour, years)
    extra = ("tourney_id", "match_num") if args.keep_source_keys else ()
    write_results_csv(rows, resolve_under_root(args.out, label="out"), extra_columns=extra)
    print(json.dumps({"rows": len(rows), "stats": stats, "member_sha256": hashes}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
