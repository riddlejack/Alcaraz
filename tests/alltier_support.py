"""A small synthetic all-tier source: rows of every tier with scores, serve counts,
rankings, seeds, entries and traits, drawn from a seeded generator."""

from __future__ import annotations

import numpy as np

from tennislab.alltier.kalman import KalmanSettings
from tennislab.alltier.source import SourceRows

TIERS = ("tour", "qualifying", "challenger", "futures")
FAMILY = {
    "tour": "atp_tour",
    "qualifying": "atp_qual_chall",
    "challenger": "atp_qual_chall",
    "futures": "atp_futures",
}
LEVEL = {"tour": "A", "qualifying": "A", "challenger": "C", "futures": "15"}
ROUNDS = {"tour": ("R32", "R16", "QF", "SF", "F"), "qualifying": ("Q1", "Q2", "Q3")}
SCORES = ("6-4 6-3", "7-6(5) 3-6 6-2", "6-4 2-1 RET", "W/O", "6-3 [10-8]", "6-2 6-7(4) 7-5", "")
SURFACES = ("Hard", "Clay", "Grass", "Carpet", "")
FILTER = KalmanSettings.from_mapping(
    {"V0": 0.005, "q": 1e-5, "V_surf": 0.001, "temper_lower": 1.0, "mu_rate": 0.002}
)


def synthetic_rows(
    seed: int = 7, rows: int = 2400, players: int = 70, days: int = 500
) -> SourceRows:
    rng = np.random.default_rng(seed)
    start = 15000  # day number of the first possible row
    day = np.sort(rng.integers(start, start + days, rows))
    tier = np.array([TIERS[i] for i in rng.choice(4, rows, p=[0.3, 0.2, 0.3, 0.2])], dtype=object)
    winner = 1000 + rng.integers(0, players, rows)
    loser = 1000 + (winner - 1000 + 1 + rng.integers(0, players - 1, rows)) % players
    cols: dict[str, np.ndarray] = {}
    cols["day"] = day.astype(np.int64)
    cols["tourney_day"] = (day - day % 7).astype(np.int64)
    cols["tier"] = tier
    cols["family"] = np.array([FAMILY[t] for t in tier], dtype=object)
    cols["season"] = np.array([2000 + (d - start) // 365 for d in day], dtype=np.int64)
    cols["tourney_id"] = np.array(
        [f"{2000 + (d - start) // 365}-{t[:2]}{d // 7}" for d, t in zip(day, tier, strict=True)],
        dtype=object,
    )
    cols["match_num"] = np.arange(rows, dtype=np.int64)
    cols["row_id"] = np.array(
        [
            f"{f}:{t}/{m}"
            for f, t, m in zip(cols["family"], cols["tourney_id"], cols["match_num"], strict=True)
        ],
        dtype=object,
    )
    cols["tourney_level"] = np.array(
        [LEVEL[t] if rng.random() > 0.1 or t != "tour" else "G" for t in tier], dtype=object
    )
    cols["round"] = np.array(
        [rng.choice(ROUNDS.get(t, ("R32", "R16", "QF", "SF", "F"))) for t in tier], dtype=object
    )
    cols["surface"] = np.array(
        [SURFACES[i] for i in rng.choice(5, rows, p=[0.4, 0.3, 0.15, 0.1, 0.05])], dtype=object
    )
    cols["draw_size"] = np.array([str(v) for v in rng.choice([16, 32, 128], rows)], dtype=object)
    cols["best_of"] = np.array(
        ["5" if (lv == "G") else "3" for lv in cols["tourney_level"]], dtype=object
    )
    cols["score"] = np.array(
        [
            SCORES[i]
            for i in rng.choice(len(SCORES), rows, p=[0.35, 0.2, 0.08, 0.07, 0.1, 0.15, 0.05])
        ],
        dtype=object,
    )
    cols["minutes"] = np.array(
        [str(v) if v > 60 else "" for v in rng.integers(40, 200, rows)], dtype=object
    )
    cols["winner_id"] = winner.astype(np.int64)
    cols["loser_id"] = loser.astype(np.int64)
    cols["player_a"] = np.minimum(winner, loser).astype(np.int64)
    cols["player_b"] = np.maximum(winner, loser).astype(np.int64)
    cols["date_source"] = np.array(["synthetic"] * rows, dtype=object)
    cols["match_id"] = np.array(
        [f"m{i}" if t == "tour" else "" for i, t in enumerate(tier)], dtype=object
    )
    has_stats = (tier != "futures") & (rng.random(rows) < 0.85)
    for side in ("w", "l"):
        svpt = rng.integers(40, 110, rows)
        first = (svpt * rng.uniform(0.35, 0.5, rows)).astype(int)
        second = (svpt * rng.uniform(0.1, 0.2, rows)).astype(int)
        cols[f"{side}_svpt"] = np.array(
            [str(v) if h else "" for v, h in zip(svpt, has_stats, strict=True)], dtype=object
        )
        cols[f"{side}_1stWon"] = np.array(
            [str(v) if h else "" for v, h in zip(first, has_stats, strict=True)], dtype=object
        )
        cols[f"{side}_2ndWon"] = np.array(
            [str(v) if h else "" for v, h in zip(second, has_stats, strict=True)], dtype=object
        )
    for side in ("winner", "loser"):
        cols[f"{side}_seed"] = np.array(
            [str(v) if v < 9 else "" for v in rng.integers(1, 30, rows)], dtype=object
        )
        cols[f"{side}_entry"] = np.array(
            [rng.choice(["", "", "", "Q", "WC", "LL", "PR"]) for _ in range(rows)], dtype=object
        )
        cols[f"{side}_rank"] = np.array(
            [str(v) if v < 400 else "" for v in rng.integers(1, 450, rows)], dtype=object
        )
        cols[f"{side}_rank_points"] = np.array(
            [str(v) if v > 10 else "" for v in rng.integers(0, 3000, rows)], dtype=object
        )
        cols[f"{side}_age"] = np.where(rng.random(rows) < 0.97, rng.uniform(17, 35, rows), np.nan)
        cols[f"{side}_ht"] = np.where(
            rng.random(rows) < 0.8, rng.integers(170, 205, rows).astype(float), np.nan
        )
        cols[f"{side}_hand"] = np.array(
            [rng.choice(["R", "R", "R", "L", "U"]) for _ in range(rows)], dtype=object
        )
    return SourceRows(cols)


def swap_outcome(rows: SourceRows, mask: np.ndarray, seed: int = 11) -> SourceRows:
    """Flip winner and loser on ``mask`` (each side's facts move with its player) and
    scramble the score, the serve counts and the minutes."""
    rng = np.random.default_rng(seed)
    cols = {k: v.copy() for k, v in rows.columns.items()}
    idx = np.flatnonzero(mask)
    pairs = [(c, "loser" + c[len("winner") :]) for c in cols if c.startswith("winner")]
    pairs += [(c, "l_" + c[2:]) for c in cols if c.startswith("w_")]
    for cw, cl in pairs:
        cols[cw][idx], cols[cl][idx] = rows[cl][idx].copy(), rows[cw][idx].copy()
    cols["score"][idx] = rng.choice(
        ["6-1 6-1", "7-6(2) 6-7(3) 6-0", "6-2 1-0 RET", "W/O"], len(idx)
    )
    for name in ("w_svpt", "l_svpt"):
        cols[name][idx] = rng.integers(40, 120, len(idx)).astype(str)
    for name in ("w_1stWon", "w_2ndWon", "l_1stWon", "l_2ndWon", "minutes"):
        cols[name][idx] = rng.integers(5, 40, len(idx)).astype(str)
    return SourceRows(cols)
