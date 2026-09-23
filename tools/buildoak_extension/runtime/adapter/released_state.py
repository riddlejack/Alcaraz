"""D97 release boundary around the pinned feature formulas.

Only this process's already released history enters state. This module does not
read files, score outcomes, fit models or infer history completion dates.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from bench_schema import neutral_fixture, source_id, validate_fixture
from tennis_predict.data import ROUND_ORDER
from tennis_predict.features import RankingsIndex, feature_engine


def chronological_key(row):
    """Exact native load_matches ordering, plus retained source order for ties."""
    return (
        str(row["match_date"]),
        str(row["tourney_name"]),
        ROUND_ORDER.get(row["round"], 0),
        int(row["match_num"]),
        str(row.get("winner_name", "")),
        str(row.get("loser_name", "")),
        int(row.get("_native_sequence", 0)),
    )


def ordered_release(history, cutoff, released_ids):
    """Trusted scheduler projection; a proxy date's scientific basis is external."""
    date = pd.Timestamp(cutoff)
    eligible = [
        r
        for r in history
        if source_id(r) not in released_ids and pd.Timestamp(r["available_date"]) <= date
    ]
    return sorted(eligible, key=chronological_key)


class ReleasedState:
    def __init__(self, reference_date, ioc_buckets):
        self.reference_date = reference_date
        self.ioc_buckets = tuple(ioc_buckets)
        self.rankings = RankingsIndex({}, {}, {})
        self.engine = feature_engine(reference_date, self.ioc_buckets, self.rankings)
        next(self.engine)
        self.cutoff = None
        self.released_ids = set()
        self.history_by_id = {}
        self.latest_history_key = None
        self.replay_count = 0
        self.replayed_rows = 0
        self.receipts = []

    def _rebuild_chronologically(self):
        """Rebuild only after a newly available result precedes current state."""
        self.engine = feature_engine(self.reference_date, self.ioc_buckets, self.rankings)
        next(self.engine)
        ordered = sorted(self.history_by_id.values(), key=chronological_key)
        for row in ordered:
            update = dict(row)
            update["match_date"] = pd.Timestamp(update["match_date"])
            assert self.engine.send(("history", update)) is None
        self.latest_history_key = chronological_key(ordered[-1]) if ordered else None
        self.replay_count += 1
        self.replayed_rows += len(ordered)
        return len(ordered)

    def step(self, cutoff, history, rankings, targets):
        """One externally delivered cutoff message, with no future-file access."""
        date = pd.Timestamp(cutoff)
        if self.cutoff is not None and date <= self.cutoff:
            raise ValueError("cutoff must advance; group all same-cutoff targets into one message")
        for target in targets:
            validate_fixture(target)
        target_ids = {source_id(t) for t in targets}
        if len(target_ids) != len(targets):
            raise ValueError("duplicate target ID")
        if target_ids & self.released_ids:
            raise ValueError("target already consumed as history")
        incoming_ids = set()
        for row in history:
            key = source_id(row)
            if key in self.released_ids or key in incoming_ids or key in target_ids:
                raise ValueError("duplicate or self history release")
            if pd.Timestamp(row["available_date"]) > date:
                raise ValueError("future history release")
            incoming_ids.add(key)
        for row in rankings:
            if pd.Timestamp(row["ranking_date"]) > date:
                raise ValueError("future ranking release")
        for row in sorted(rankings, key=lambda r: (int(r["player_id"]), str(r["ranking_date"]))):
            player = int(row["player_id"])
            when = np.datetime64(row["ranking_date"], "ns")
            old = self.rankings.dates_by_player.get(player, np.array([], dtype="datetime64[ns]"))
            if len(old) and when <= old[-1]:
                raise ValueError("duplicate or backward ranking date")
            self.rankings.dates_by_player[player] = np.append(old, when)
            self.rankings.ranks_by_player[player] = np.append(
                self.rankings.ranks_by_player.get(player, np.array([], dtype=float)),
                float(row["rank"]),
            )
            self.rankings.points_by_player[player] = np.append(
                self.rankings.points_by_player.get(player, np.array([], dtype=float)),
                float(row["points"]) if row["points"] is not None else np.nan,
            )
        incoming = ordered_release(history, date, self.released_ids)
        for row in incoming:
            self.history_by_id[source_id(row)] = row
        replayed = bool(
            incoming
            and self.latest_history_key is not None
            and chronological_key(incoming[0]) < self.latest_history_key
        )
        replay_rows = self._rebuild_chronologically() if replayed else 0
        if not replayed:
            for row in incoming:
                update = dict(row)
                update["match_date"] = pd.Timestamp(update["match_date"])
                assert self.engine.send(("history", update)) is None
                self.latest_history_key = chronological_key(row)
        self.released_ids.update(incoming_ids)
        outputs = []
        for target in sorted(targets, key=source_id):
            row = neutral_fixture(target)
            row["match_date"] = pd.Timestamp(row["match_date"])
            if date > row["match_date"]:
                raise ValueError("target cutoff after target date")
            for role in ["winner", "loser"]:
                player = int(row[role + "_id"])
                dates = self.rankings.dates_by_player.get(player)
                # Rank and points are always sourced from released rankings.
                row[role + "_rank"] = np.nan
                row[role + "_rank_points"] = np.nan
                if dates is not None and len(dates):
                    row[role + "_rank"] = self.rankings.ranks_by_player[player][-1]
                    row[role + "_rank_points"] = self.rankings.points_by_player[player][-1]
            output = self.engine.send(("target", row))
            output["match_id"] = source_id(target)
            outputs.append(output)
        self.cutoff = date
        self.receipts.append(
            {
                "cutoff": date.date().isoformat(),
                "history_ids_released": sorted(incoming_ids),
                "target_ids": sorted(target_ids),
                "rankings_released": len(rankings),
                "chronology_replay": replayed,
                "chronology_replay_rows": replay_rows,
                "cumulative_chronology_replays": self.replay_count,
                "cumulative_replayed_rows": self.replayed_rows,
            }
        )
        return outputs


def probability_for_requested_order(model, frame, requested_first, canonical_first):
    """Trees see native canonical order; API reversal complements that result."""
    probability = float(model.predict_proba(frame)[0, 1])
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("invalid native probability")
    return probability if requested_first == canonical_first else 1 - probability
