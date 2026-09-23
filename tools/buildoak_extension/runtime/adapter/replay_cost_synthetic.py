"""Generated-data timing for chronology replay; no tennis inputs or model fit."""

import datetime as dt
import gc
import json
import resource
import time

from bench_schema import neutral_fixture
from released_state import ReleasedState


def row(i, date, winner=1, loser=2, available=None):
    value = dict(
        tourney_id=f"SYNTHETIC-{i // 50}",
        match_num=i + 1,
        match_date=date,
        available_date=available or date,
        tourney_name="Synthetic Open",
        tourney_level="A",
        surface="Hard",
        round="R32",
        draw_size=32,
        best_of=3,
        score="6-4 6-4",
        minutes=80,
        _native_sequence=i,
    )
    for role, player in [("winner", winner), ("loser", loser)]:
        value.update(
            {
                f"{role}_id": player,
                f"{role}_name": f"Player {player}",
                f"{role}_age": 25 + player,
                f"{role}_ht": 180 + player,
                f"{role}_seed": None,
                f"{role}_rank": 10 * player,
                f"{role}_rank_points": 1000 / player,
                f"{role}_entry": "",
                f"{role}_hand": "R",
                f"{role}_ioc": "USA" if player % 2 else "GBR",
            }
        )
    for prefix in ["w", "l"]:
        value.update(
            {
                f"{prefix}_ace": 5,
                f"{prefix}_df": 2,
                f"{prefix}_svpt": 60,
                f"{prefix}_1stIn": 40,
                f"{prefix}_1stWon": 30,
                f"{prefix}_2ndWon": 10,
                f"{prefix}_SvGms": 10,
                f"{prefix}_bpSaved": 3,
                f"{prefix}_bpFaced": 5,
            }
        )
    return value


results = []
for n in [2000, 10000, 50000]:
    start_date = dt.date(2020, 1, 1)
    history = [
        row(
            i,
            (start_date + dt.timedelta(days=i // 50)).isoformat(),
            1 if i % 2 else 2,
            2 if i % 2 else 1,
        )
        for i in range(n)
    ]
    state = ReleasedState("2023-12-30", ("USA", "GBR"))
    target = row(n + 2, "2024-01-25", 1, 2)
    t = time.monotonic()
    state.step("2024-01-21", history, [], [neutral_fixture(target)])
    initial = time.monotonic() - t
    late = row(n + 1, "2020-01-01", 1, 2, available="2024-01-22")
    late["_native_sequence"] = -1
    t = time.monotonic()
    state.step(
        "2024-01-23", [late], [], [neutral_fixture(target | {"tourney_id": "SYNTHETIC-TARGET-2"})]
    )
    replay = time.monotonic() - t
    results.append(
        {
            "rows": n + 1,
            "initial_seconds": initial,
            "replay_seconds": replay,
            "replay_rows_per_second": (n + 1) / replay,
        }
    )
    del state, history
    gc.collect()
print(
    json.dumps(
        {
            "status": "PASS",
            "synthetic_only": True,
            "measurements": results,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        },
        indent=2,
    )
)
