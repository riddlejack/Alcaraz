"""Equal-player match simulation and separate trace reconstruction.

The fixed fixture schedule is an exogenous collection of matches, not a regenerated
elimination bracket. Every played match is legal; event/round metadata is context.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

COUNTS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")


def simulate(rng: np.random.Generator, best_of: int, final_tb: int = 7) -> dict[str, Any]:
    if best_of not in (3, 5) or final_tb not in (7, 10):
        raise ValueError("unsupported declared rules")
    counts = [{name: 0 for name in COUNTS} for _ in range(2)]
    server = int(rng.integers(2))
    first_server = server
    trace, scores = [], []
    sets_won = [0, 0]
    npoints = 0
    while max(sets_won) < best_of // 2 + 1:
        games = [0, 0]
        set_trace = []
        while True:
            tb = games == [6, 6]
            target = final_tb if len(scores) == best_of - 1 else 7
            points = [0, 0]
            first = server
            codes = []
            if not tb:
                counts[server]["SvGms"] += 1
            while True:
                k = len(codes)
                srv = first if not tb or k == 0 else first ^ ((1 + (k - 1) // 2) % 2)
                receive = 1 - srv
                block = counts[srv]
                bp = not tb and points[receive] >= 3 and points[receive] - points[srv] >= 1
                block["svpt"] += 1
                if bp:
                    block["bpFaced"] += 1
                if rng.random() < 0.62:
                    block["1stIn"] += 1
                    won = rng.random() < 0.65
                    if won:
                        block["1stWon"] += 1
                        ace = rng.random() < 0.12
                        block["ace"] += int(ace)
                        code = "A" if ace else "W"
                    else:
                        code = "L"
                elif rng.random() >= 0.94:
                    won = False
                    code = "D"
                    block["df"] += 1
                else:
                    won = rng.random() < 0.53
                    code = "w" if won else "l"
                    block["2ndWon"] += int(won)
                if bp and won:
                    block["bpSaved"] += 1
                winner = srv if won else receive
                points[winner] += 1
                codes.append(code)
                npoints += 1
                if npoints > 10_000:
                    raise ValueError("predeclared point guard exceeded; no resampling")
                if max(points) >= (target if tb else 4) and abs(points[0] - points[1]) >= 2:
                    break
            set_trace.append({"server": first, "tiebreak": tb, "points": "".join(codes)})
            games[winner] += 1
            server = 1 - first
            if tb or max(games) >= 6 and abs(games[0] - games[1]) >= 2:
                break
        sets_won[winner] += 1
        scores.append(games)
        trace.append(set_trace)
    winner = int(sets_won[1] > sets_won[0])
    score = " ".join(f"{g[winner]}-{g[1 - winner]}" for g in scores)
    return {
        "best_of": best_of,
        "final_tb": final_tb,
        "first_server": first_server,
        "winner": winner,
        "counts": counts,
        "score": score,
        "points": npoints,
        "trace": trace,
    }


def mirror_participants(match: dict[str, Any]) -> dict[str, Any]:
    """Supplemental T1: exchange complete neutral-player point paths, not labels alone."""
    result = copy.deepcopy(match)
    result["first_server"] ^= 1
    result["winner"] ^= 1
    result["counts"].reverse()
    for played_set in result["trace"]:
        for game in played_set:
            game["server"] ^= 1
    reconstruct(result)
    return result


def reconstruct(match: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct all primitives from point codes, checking each legal stop and server.

    This does not call the generator or use its counters/winner for state updates.
    """
    blocks = [{name: 0 for name in COUNTS} for _ in range(2)]
    set_wins = np.zeros(2, dtype=int)
    service = match["first_server"]
    set_scores = []
    breaks = [0, 0]
    total = 0
    for set_index, recorded_set in enumerate(match["trace"]):
        if max(set_wins) >= (match["best_of"] + 1) // 2:
            raise ValueError("points after match finished")
        game_score = np.zeros(2, dtype=int)
        set_over = False
        for recorded_game in recorded_set:
            if set_over or recorded_game["server"] != service:
                raise ValueError("illegal game continuation or service order")
            tie = tuple(game_score) == (6, 6)
            if recorded_game["tiebreak"] != tie:
                raise ValueError("illegal tiebreak placement")
            point_score = np.zeros(2, dtype=int)
            goal = (match["final_tb"] if set_index + 1 == match["best_of"] else 7) if tie else 4
            game_over = False
            for index, code in enumerate(recorded_game["points"]):
                if game_over or code not in "AWLDwl":
                    raise ValueError("illegal point or points after game finished")
                serving = service
                if tie and index % 4 in (1, 2):
                    serving = 1 - service
                other = 1 - serving
                counter = blocks[serving]
                on_break = (
                    not tie
                    and point_score[other] >= 3
                    and point_score[other] > point_score[serving]
                )
                point_winner = serving if code in "AWw" else other
                counter["svpt"] += 1
                counter["1stIn"] += int(code in "AWL")
                counter["1stWon"] += int(code in "AW")
                counter["2ndWon"] += int(code == "w")
                counter["ace"] += int(code == "A")
                counter["df"] += int(code == "D")
                counter["bpFaced"] += int(on_break)
                counter["bpSaved"] += int(on_break and point_winner == serving)
                point_score[point_winner] += 1
                total += 1
                game_over = max(point_score) >= goal and abs(point_score[0] - point_score[1]) > 1
            if not game_over:
                raise ValueError("incomplete game")
            game_winner = int(point_score[1] > point_score[0])
            if not tie:
                blocks[service]["SvGms"] += 1
                breaks[service] += int(game_winner != service)
            game_score[game_winner] += 1
            service = 1 - service
            set_over = tie or max(game_score) >= 6 and abs(game_score[0] - game_score[1]) > 1
        if not set_over:
            raise ValueError("incomplete set")
        set_wins[int(game_score[1] > game_score[0])] += 1
        set_scores.append(game_score)
    if max(set_wins) != (match["best_of"] + 1) // 2:
        raise ValueError("incomplete match")
    winner = int(set_wins[1] > set_wins[0])
    score = " ".join(f"{s[winner]}-{s[1 - winner]}" for s in set_scores)
    for side, block in enumerate(blocks):
        if block["bpFaced"] - block["bpSaved"] != breaks[side]:
            raise ValueError("break-point/game reconciliation failed")
        if not (0 <= block["ace"] <= block["1stWon"] <= block["1stIn"] <= block["svpt"]):
            raise ValueError("first-serve arithmetic failed")
        if not (0 <= block["2ndWon"] + block["df"] <= block["svpt"] - block["1stIn"]):
            raise ValueError("second-serve arithmetic failed")
    observed = {"counts": blocks, "winner": winner, "score": score, "points": total}
    if any(match[name] != value for name, value in observed.items()):
        raise ValueError("primitive values differ from independent point reconstruction")
    return observed
