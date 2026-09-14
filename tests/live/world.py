"""A fully synthetic live world for rehearsing every public live command.

Nothing here is a real player, event, result or page. The world writes a workspace with
a player master, a CONFIRM2026-schema history table, a replay directory holding a
synthetic Wikipedia REST envelope per event, a parsed serve feed in the TAPLAYER01
layout, a Sackmann-layout ranking file and a copy of the live config with the history
bound by hash. Tests drive ``tennislab.cli.main`` inside that workspace.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from tennislab import cli
from tennislab.chain.common import sha256
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache
from tennislab.live import common
from tennislab.live.transport import write_replay_response

REPO = Path.cwd()
PLAYERS = [
    ("300001", "Ada", "Alpha"),
    ("300002", "Bo", "Beta"),
    ("300003", "Cy", "Gamma"),
    ("300004", "Di", "Delta"),
    ("300005", "Ed", "Epsilon"),
    ("300006", "Fi", "Zeta"),
    ("300007", "Gus", "Eta"),
    ("300008", "Hal", "Theta"),
    ("300009", "Ida", "Iota"),  # two masters share this name: ambiguous by design
    ("300010", "Ida", "Iota"),
    ("300011", "Jo", "Kappa"),
]
ENDPOINT = "https://api.wikimedia.org/core/v1/wikipedia/en/page/{title}"
EVENT_1 = {
    "event_id": "2026-E1",
    "tour": "ATP",
    "name": "Sample Open",
    "level": "A",
    "surface": "Hard",
    "best_of": 3,
    "draw_size": 8,
    "wikipedia_title": "2026 Sample Open – Singles",
    "window_start": "2026-08-03",
    "window_end": "2026-08-09",
}
EVENT_2 = {
    "event_id": "2026-E2",
    "tour": "ATP",
    "name": "Next Open",
    "level": "A",
    "surface": "Hard",
    "best_of": 3,
    "draw_size": 8,
    "wikipedia_title": "2026 Next Open – Singles",
    "window_start": "2026-08-10",
    "window_end": "2026-08-16",
}
ISSUE_CLOCK = dt.datetime(2026, 8, 10, 12, 0, tzinfo=dt.UTC)


def name_of(pid: str) -> str:
    for ident, first, last in PLAYERS:
        if ident == pid:
            return f"{first} {last}"
    raise KeyError(pid)


# --- wikitext ---------------------------------------------------------------------------------


def team_cell(name: str, bold: bool) -> str:
    inner = f"{{{{flagicon|SYN}}}} [[{name}]]"
    return f"'''{inner}'''" if bold else inner


def score_cells(
    rd: str,
    base: int,
    sets: Sequence[tuple[str, str]],
    *,
    winner_is_first: bool,
    retired: bool = False,
    walkover: bool = False,
) -> list[str]:
    lines = []
    for index in range(1, 4):
        if walkover:
            first = "<small>w/o</small>" if index == 1 else ""
            second = ""
        elif index <= len(sets):
            first, second = sets[index - 1]
            first_bold = winner_is_first and int(first) > int(second)
            second_bold = (not winner_is_first) and int(second) > int(first)
            if retired and index == len(sets):
                if winner_is_first:
                    second = f"{second}<sup>r</sup>"
                else:
                    first = f"{first}<sup>r</sup>"
            first = f"'''{first}'''" if first_bold else first
            second = f"'''{second}'''" if second_bold else second
        else:
            first = second = ""
        lines.append(f"|{rd}-score{base}-{index}={first}")
        lines.append(f"|{rd}-score{base + 1}-{index}={second}")
    return lines


def bracket_page(rounds: dict[str, list[dict[str, Any]]], *, qualifying: bool = True) -> str:
    """An 8-draw page: one ``{{8TeamBracket-Tennis3}}`` under ``==Draw==``.

    ``rounds`` maps ``QF``/``SF``/``F`` to match dicts with ``a``, ``b`` (names),
    ``winner`` (``"a"``, ``"b"`` or ``""`` pending), ``sets`` (list of (a_games, b_games)),
    and optional ``retired`` / ``walkover``.
    """
    labels = {"QF": "Quarterfinals", "SF": "Semifinals", "F": "Final"}
    lines = [
        "'''2026 Sample''' page.",
        "",
        "==Seeds==",
        "# seeds",
        "",
        "==Draw==",
        "===Finals===",
        "{{8TeamBracket-Tennis3",
    ]
    for index, code in enumerate(["QF", "SF", "F"], 1):
        lines.append(f"|RD{index}={labels[code]}")
    for index, code in enumerate(["QF", "SF", "F"], 1):
        for slot, match in enumerate(rounds.get(code, []), 1):
            base = 2 * slot - 1
            a_bold = match["winner"] == "a"
            b_bold = match["winner"] == "b"
            lines.append(f"|RD{index}-seed{base}=")
            lines.append(f"|RD{index}-team{base}={team_cell(match['a'], a_bold)}")
            lines.append(f"|RD{index}-seed{base + 1}=")
            lines.append(f"|RD{index}-team{base + 1}={team_cell(match['b'], b_bold)}")
            lines.extend(
                score_cells(
                    f"RD{index}",
                    base,
                    match.get("sets", []),
                    winner_is_first=a_bold,
                    retired=match.get("retired", False),
                    walkover=match.get("walkover", False),
                )
            )
    lines.append("}}")
    if qualifying:
        lines += [
            "",
            "==Qualifying==",
            "{{4TeamBracket-Tennis3-v2",
            "| RD1=First round",
            "| RD2=Qualifying competition",
            "| RD1-team1='''[[Jo Kappa]]'''",
            "| RD1-score1-1='''6'''",
            "| RD1-team2=[[Ada Alpha]]",
            "| RD1-score2-1=1",
            "}}",
        ]
    lines += ["", "==References=="]
    return "\n".join(lines) + "\n"


def envelope(title: str, source: str, *, revision: int, timestamp: str) -> str:
    return json.dumps(
        {
            "id": 1,
            "key": title.replace(" ", "_"),
            "title": title,
            "latest": {"id": revision, "timestamp": timestamp},
            "content_model": "wikitext",
            "license": {
                "url": "https://creativecommons.org/licenses/by-sa/4.0/deed.en",
                "title": "CC BY-SA 4.0",
            },
            "source": source,
        }
    )


def complete_rounds() -> dict[str, list[dict[str, Any]]]:
    n = name_of
    return {
        "QF": [
            {"a": n("300001"), "b": n("300008"), "winner": "a", "sets": [("6", "3"), ("6", "4")]},
            {"a": n("300004"), "b": n("300005"), "winner": "b", "sets": [("4", "6"), ("3", "6")]},
            {
                "a": n("300003"),
                "b": n("300006"),
                "winner": "a",
                "sets": [("7", "6"), ("2", "6"), ("6", "3")],
            },
            {
                "a": n("300002"),
                "b": n("300007"),
                "winner": "a",
                "sets": [("6", "1"), ("2", "1")],
                "retired": True,
            },
        ],
        "SF": [
            {"a": n("300001"), "b": n("300005"), "winner": "a", "sets": [("6", "4"), ("6", "4")]},
            {"a": n("300003"), "b": n("300002"), "winner": "b", "sets": [], "walkover": True},
        ],
        "F": [
            {"a": n("300001"), "b": n("300002"), "winner": "a", "sets": [("6", "2"), ("6", "2")]}
        ],
    }


def replay_dir_for(
    workspace: Path,
    rounds: dict[str, list[dict[str, Any]]],
    *,
    revision: int,
    timestamp: str = "2026-08-09T22:00:00Z",
    name: str = "replay",
    e2_rounds: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    from tennislab.live.sources import wikipedia_url

    directory = workspace / name
    write_replay_response(
        directory,
        wikipedia_url(ENDPOINT, EVENT_1["wikipedia_title"]),
        status=200,
        body=envelope(
            EVENT_1["wikipedia_title"], bracket_page(rounds), revision=revision, timestamp=timestamp
        ),
        headers={"cache-control": "no-cache", "age": "0"},
    )
    pending = e2_rounds or {
        "QF": [
            {"a": name_of("300001"), "b": name_of("300004"), "winner": "", "sets": []},
            {"a": name_of("300002"), "b": name_of("300003"), "winner": "", "sets": []},
        ]
    }
    write_replay_response(
        directory,
        wikipedia_url(ENDPOINT, EVENT_2["wikipedia_title"]),
        status=200,
        body=envelope(
            EVENT_2["wikipedia_title"],
            bracket_page(pending, qualifying=False),
            revision=revision + 1,
            timestamp=timestamp,
        ),
        headers={"cache-control": "no-cache"},
    )
    return directory


# --- workspace ----------------------------------------------------------------------------------


def history_rows() -> list[dict[str, str]]:
    n = name_of
    rows = []
    fixtures = [
        ("2025-03-03", "Hard", "300001", "300002"),
        ("2025-03-03", "Hard", "300003", "300004"),
        ("2025-03-10", "Clay", "300001", "300003"),
        ("2025-03-10", "Clay", "300002", "300004"),
        ("2025-04-07", "Hard", "300001", "300004"),
        ("2025-04-07", "Hard", "300005", "300006"),
        ("2025-05-05", "Hard", "300007", "300008"),
        ("2025-05-05", "Clay", "300005", "300007"),
        ("2026-07-27", "Hard", "300001", "300005"),
        ("2026-07-27", "Hard", "300002", "300006"),
    ]
    for date, surface, winner, loser in fixtures:
        rows.append(
            {
                "date": date,
                "tour": "ATP",
                "tournament": "Synthetic",
                "level": "A",
                "round": "R16",
                "surface": surface,
                "best_of": "3",
                "winner_id": winner,
                "loser_id": loser,
                "winner_name": n(winner),
                "loser_name": n(loser),
                "source": "synthetic",
                "date_basis": "reported_match_date",
                "completion_upper_bound": date,
                "completion_basis": "reported_match_date",
                "publication_upper_bound_utc": "2026-08-01T00:00:00Z",
                "receipt_time_utc": "2026-08-01T01:00:00Z",
                "status": "completed",
                "overlap_unresolved": "false",
            }
        )
    return rows


def write_csv(path: Path, header: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = list(header)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in header})


TA_HEADER = "tour,player_id,player_slug,date,date_basis,tournament_name,tournament_level,surface,round,result,score,best_of,player_rank,player_seed,player_entry,opponent_name,opponent_id,opponent_rank,opponent_seed,opponent_entry,minutes,p_ace,p_df,p_svpt,p_1stIn,p_1stWon,p_2ndWon,p_SvGms,p_bpSaved,p_bpFaced,o_ace,o_df,o_svpt,o_1stIn,o_1stWon,o_2ndWon,o_SvGms,o_bpSaved,o_bpFaced,serve_block_valid,opponent_serve_block_valid,match_id,source,asserted_by,retained_file,retained_sha256,attribution".split(
    ","
)


def serve_feed(workspace: Path, *, name: str = "serve_feed") -> Path:
    directory = workspace / name
    rows = []
    counts = {
        "p_ace": 5,
        "p_df": 2,
        "p_svpt": 70,
        "p_1stIn": 45,
        "p_1stWon": 33,
        "p_2ndWon": 12,
        "p_SvGms": 11,
        "p_bpSaved": 2,
        "p_bpFaced": 3,
        "o_ace": 3,
        "o_df": 4,
        "o_svpt": 66,
        "o_1stIn": 40,
        "o_1stWon": 28,
        "o_2ndWon": 11,
        "o_SvGms": 10,
        "o_bpSaved": 4,
        "o_bpFaced": 7,
    }
    rows.append(
        {
            "tour": "atp",
            "player_id": "300001",
            "player_slug": "AdaAlpha",
            "date": "20260803",
            "date_basis": "event_anchor",
            "tournament_name": "Sample Open",
            "tournament_level": "A",
            "surface": "Hard",
            "round": "QF",
            "result": "W",
            "score": "6-3 6-4",
            "best_of": "3",
            "opponent_name": name_of("300008"),
            "opponent_id": "300008",
            "match_id": "2026-E1-1",
            "serve_block_valid": "true",
            "opponent_serve_block_valid": "true",
            **counts,
        }
    )
    partial = {k: v for k, v in counts.items() if k not in {"p_SvGms", "o_SvGms"}}
    rows.append(
        {
            "tour": "atp",
            "player_id": "300002",
            "player_slug": "BoBeta",
            "date": "20260803",
            "date_basis": "event_anchor",
            "tournament_name": "Sample Open",
            "tournament_level": "A",
            "surface": "Hard",
            "round": "QF",
            "result": "W",
            "score": "6-1 2-1",
            "best_of": "3",
            "opponent_name": name_of("300007"),
            "opponent_id": "300007",
            "match_id": "2026-E1-4",
            "serve_block_valid": "false",
            "opponent_serve_block_valid": "false",
            **partial,
        }
    )
    # an anchor with no declared event window: stays overlap-unresolved, never usable
    rows.append(
        {
            "tour": "atp",
            "player_id": "300001",
            "player_slug": "AdaAlpha",
            "date": "20260810",
            "date_basis": "event_anchor",
            "tournament_name": "Unknown Cup",
            "tournament_level": "A",
            "surface": "Hard",
            "round": "R32",
            "result": "W",
            "score": "6-0 6-0",
            "best_of": "3",
            "opponent_name": name_of("300011"),
            "opponent_id": "300011",
            "match_id": "2026-X-1",
            "serve_block_valid": "true",
            "opponent_serve_block_valid": "true",
            **counts,
        }
    )
    write_csv(
        directory / "atp_AdaAlpha.csv", TA_HEADER, [r for r in rows if r["player_id"] == "300001"]
    )
    write_csv(
        directory / "atp_BoBeta.csv", TA_HEADER, [r for r in rows if r["player_id"] == "300002"]
    )
    return directory


def rankings_file(workspace: Path, *, dates: Sequence[str] = ("20260803", "20260810")) -> Path:
    path = workspace / "rankings" / "atp_rankings_current.csv"
    rows = []
    for date in dates:
        for rank, pid in enumerate(["300001", "300002", "300003", "300004", "300005"], 1):
            rows.append(
                {"ranking_date": date, "rank": rank, "player": pid, "points": 1000 - 100 * rank}
            )
    write_csv(path, ["ranking_date", "rank", "player", "points"], rows)
    return path


def build_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "docs" / "live").mkdir(parents=True)
    shutil.copyfile(REPO / "docs" / "live" / "DESIGN.md", workspace / "docs" / "live" / "DESIGN.md")
    shutil.copyfile(REPO / "docs" / "live" / "REPAIR.md", workspace / "docs" / "live" / "REPAIR.md")
    shutil.copyfile(
        REPO / "docs" / "live" / "REPAIR2.md", workspace / "docs" / "live" / "REPAIR2.md"
    )
    shutil.copyfile(
        REPO / "docs" / "live" / "REPAIR3.md", workspace / "docs" / "live" / "REPAIR3.md"
    )
    (workspace / "configs").mkdir()
    shutil.copyfile(REPO / "configs" / "elo.json", workspace / "configs" / "elo.json")
    write_csv(
        workspace / "data" / "live" / "identity" / "players.csv",
        ["player_id", "name_first", "name_last", "hand", "dob", "ioc", "height", "wikidata_id"],
        [
            {"player_id": p, "name_first": f, "name_last": last, "ioc": "SYN"}
            for p, f, last in PLAYERS
        ],
    )
    write_csv(
        workspace / "data" / "live" / "identity" / "aliases.csv",
        ["alias", "player_id", "tour", "note"],
        [{"alias": "H. Theta", "player_id": "300008", "tour": "ATP", "note": "synthetic alias"}],
    )
    history = workspace / "data" / "live" / "history" / "atp_results.csv"
    write_csv(
        history,
        [
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
            "date_basis",
            "completion_upper_bound",
            "completion_basis",
            "publication_upper_bound_utc",
            "receipt_time_utc",
            "status",
            "overlap_unresolved",
        ],
        history_rows(),
    )
    config = json.loads((REPO / "configs" / "live" / "live.json").read_text(encoding="utf-8"))
    config["history"]["ATP"] = {
        "results_csv": "data/live/history/atp_results.csv",
        "sha256": sha256(history),
        "admissible_completion_bases": ["reported_match_date"],
    }
    (workspace / "configs" / "live").mkdir()
    (workspace / "configs" / "live" / "live.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (workspace / "events.json").write_text(
        json.dumps({"events": [EVENT_1, EVENT_2]}, indent=2), encoding="utf-8"
    )
    return workspace


def write_fixtures(
    workspace: Path,
    rows: list[dict[str, Any]],
    *,
    name: str = "pending.csv",
    extra_columns: Sequence[str] = (),
) -> Path:
    from tennislab.live.fixtures import FIXTURE_INPUT

    path = workspace / name
    write_csv(path, [*FIXTURE_INPUT, *extra_columns], rows)
    return path


def fixture_row(
    ref: str,
    x: str,
    y: str,
    *,
    event_id: str = "2026-E2",
    round_code: str = "R16",
    start: str = "2026-08-11T15:00:00+00:00",
    surface: str = "Hard",
    best_of: str = "3",
    source: str = "synthetic order of play",
    tz: str = "UTC",
    uncertainty: str = "2",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "fixture_ref": ref,
        "tour": "ATP",
        "event_id": event_id,
        "round": round_code,
        "player_x_id": x,
        "player_x_name": name_of(x) if x else "",
        "player_y_id": y,
        "player_y_name": name_of(y) if y else "",
        "surface": surface,
        "best_of": best_of,
        "best_of_source": "declared rule" if best_of else "",
        "scheduled_start": start,
        "scheduled_start_source": source,
        "scheduled_start_timezone": tz,
        "start_uncertainty_hours": uncertainty,
        **extra,
    }


class Runner:
    """Run ``tennislab`` commands inside the workspace with a pinned clock."""

    def __init__(self, workspace: Path, capsys: Any) -> None:
        self.workspace = workspace
        self.capsys = capsys
        self.clock = ISSUE_CLOCK

    def at(self, moment: dt.datetime) -> None:
        self.clock = moment

    def run(self, *argv: str) -> tuple[int, str, str]:
        previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
        os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(self.workspace)
        reset_workspace_cache()
        common.set_clock(lambda: self.clock)
        cwd = Path.cwd()
        os.chdir(self.workspace)
        try:
            self.capsys.readouterr()
            code = cli.main(list(argv))
            captured = self.capsys.readouterr()
            return code, captured.out, captured.err
        finally:
            os.chdir(cwd)
            common.set_clock(None)
            if previous is None:
                os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
            else:
                os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
            reset_workspace_cache()

    def ok(self, *argv: str) -> dict[str, Any]:
        code, out, err = self.run(*argv)
        assert code == 0, f"{argv}: exit {code}\n{out}\n{err}"
        return json.loads(out) if out.strip().startswith(("{", "[")) else {"raw": out}

    def fails(self, *argv: str) -> str:
        code, out, err = self.run(*argv)
        assert code != 0, f"{argv}: unexpectedly succeeded\n{out}"
        return err + out


CONFIG = "configs/live/live.json"
