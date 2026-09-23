"""Focused duplicate-native-key and chronology-replay control."""

import json

from bench_schema import neutral_fixture
from released_state import ReleasedState, chronological_key


def row(tourney_id, transport_id, date, available, winner, loser, sequence):
    result = {
        "tourney_id": tourney_id,
        "match_num": 1,
        "match_date": date,
        "available_date": available,
        "_transport_id": transport_id,
        "_native_sequence": sequence,
        "tourney_name": "Synthetic Duplicate Control",
        "tourney_level": "I",
        "surface": "Hard",
        "round": "R32",
        "draw_size": 32,
        "best_of": 3,
        "score": "6-4 6-4",
        "minutes": 80,
    }
    for role, player in [("winner", winner), ("loser", loser)]:
        values = {
            "id": player,
            "name": "Player " + str(player),
            "age": 25.0 + player,
            "ht": 170.0 + player,
            "seed": None,
            "rank": None,
            "rank_points": None,
            "entry": "",
            "hand": "R",
            "ioc": "USA" if player % 2 else "GBR",
        }
        for key, value in values.items():
            result[role + "_" + key] = value
    for prefix in ["w", "l"]:
        for field in [
            "ace",
            "df",
            "svpt",
            "1stIn",
            "1stWon",
            "2ndWon",
            "SvGms",
            "bpSaved",
            "bpFaced",
        ]:
            result[prefix + "_" + field] = None
    return result


state = ReleasedState("2024-12-31", ["USA", "GBR"])
first = row("NATIVE-DUP", "NATIVE-DUP/1@first.csv:2", "2020-02-01", "2020-02-02", 1, 2, 1)
late = row("NATIVE-DUP", "NATIVE-DUP/1@late.csv:2", "2020-01-01", "2020-02-04", 3, 4, 2)
target1 = row("TARGET-1", "TARGET-1/1", "2020-02-01", "2020-02-01", 1, 2, 3)
target2 = row("TARGET-2", "TARGET-2/1", "2020-02-03", "2020-02-03", 1, 2, 4)
target3 = row("TARGET-3", "TARGET-3/1", "2020-02-05", "2020-02-05", 3, 4, 5)

state.step("2020-01-31", [], [], [neutral_fixture(target1)])
after_first = state.step("2020-02-02", [first], [], [neutral_fixture(target2)])[0]
after_replay = state.step("2020-02-04", [late], [], [neutral_fixture(target3)])[0]

assert len(state.history_by_id) == 2
assert set(state.history_by_id) == {first["_transport_id"], late["_transport_id"]}
assert all(
    item["tourney_id"] == "NATIVE-DUP" and item["match_num"] == 1
    for item in state.history_by_id.values()
)
assert state.replay_count == 1 and state.replayed_rows == 2
assert (
    sorted(state.history_by_id.values(), key=chronological_key)[0]["_transport_id"]
    == late["_transport_id"]
)
assert after_first["career_matches_sum"] == 2.0 and after_first["career_matches_diff"] == 0.0
assert after_replay["career_matches_sum"] == 2.0 and after_replay["career_matches_diff"] == 0.0

print(
    json.dumps(
        {
            "status": "PASS",
            "checks": [
                "duplicate_native_key_retains_both_transport_rows",
                "original_tourney_id_and_match_num_preserved",
                "late_earlier_row_triggers_full_chronology_replay",
                "career_matches_sum_and_diff_reconstructed_after_release",
            ],
            "history_ids": sorted(state.history_by_id),
            "replay_count": state.replay_count,
            "replayed_rows": state.replayed_rows,
            "career_after_first": {
                "sum": after_first["career_matches_sum"],
                "diff": after_first["career_matches_diff"],
            },
            "career_after_replay": {
                "sum": after_replay["career_matches_sum"],
                "diff": after_replay["career_matches_diff"],
            },
        },
        indent=2,
    )
)
