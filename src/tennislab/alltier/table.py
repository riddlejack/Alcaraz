"""The all-tier point-in-time table.

Every row r has a date M_r (:mod:`tennislab.alltier.source`). Rows are put in one total
order by (M, tier, tourney_id, round, match_num) and replayed day by day: before the
features of the rows dated d are read, every earlier row dated d - 2 or before is
*released*, in that order, and only a release changes any rating or history. A feature of
row r therefore uses the results of rows released by M_r - 2 and the static pre-match
facts printed on row r itself (tier, level, round, surface, best-of, draw, entry codes,
seeds, rank, points, age, height, hand). Nothing is normalised or fitted over the table,
so no feature depends on a later row.

Signed features are a - b and negate under an a/b swap; context columns are symmetric.
Only completed or retired rows update outcome-based state; walkovers count as activity
for the player given the walkover. Features, in groups:

1. Elo: all-tier (K = 32 x tier weight, tier weights 1 / 0.8 / 0.8 / 0.6, newcomers at
   1500 / 1400 / 1400 / 1300 by the tier of their first row), tour-only and all-tier per
   surface, as logits; a Glicko-1 rating deviation (350 at most, widening from 50 to 350
   over three idle years).
2. Serve and return: decayed serve- and return-point shares (180-day half-life, a
   50-point prior at the running serve average), the decayed serve-point volume, and an
   opponent-adjusted point model (one gradient step per released match) with its
   iid-points match logit.
3. Form: tier-weighted win rates over the last 5/10/25 matches, game and set shares over
   the last 10/25, the mean Elo of the last ten opponents.
4. Activity: matches in the last 7/14/30/90 days, days since the last match,
   retirements and walkovers given over 90/365 days, days since the last retirement.
5. Experience: career matches by tier, tour finals and titles, Slam and Masters matches,
   wins over top-50 opponents (log1p differences).
6. Ranking: log rank and log points on the row, and points momentum over 28/91 days.
7. Traits: age, age squared, height, left-handedness, with missing flags.
8. Head-to-head shares, overall and on the surface (a one-match prior, centred).
9. Entry codes and seeds on the row.
10. The serve/return filter of :mod:`tennislab.alltier.kalman` (when enabled): base serve
    and return skills, the point-logit difference, its match logit and the variances.

Identity columns carry ``lab_match_id``, the previous version's (the package's) match id
for tour rows joined to its panel, empty elsewhere: the key that joins targets to the table.

Targets (never features): ``a_won``, point/game/set shares and counts, the result status
flags, ``minutes`` and ``has_serve_stats``.
"""

from __future__ import annotations

import bisect
import csv
import gzip
import io
import math
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tennislab.alltier import kalman, pointmodel
from tennislab.alltier.source import SourceRows, day_iso, numbers

# ------------------------------------------------------------------ parameters

K_FACTOR = 32.0
TIER_WEIGHT = {"tour": 1.0, "qualifying": 0.8, "challenger": 0.8, "futures": 0.6}
NEWCOMER_ELO = {"tour": 1500.0, "qualifying": 1400.0, "challenger": 1400.0, "futures": 1300.0}
TOUR_ELO_START = 1500.0
RD_MAX, RD_MIN_REFERENCE = 350.0, 50.0
RD_C2 = (RD_MAX**2 - RD_MIN_REFERENCE**2) / (3 * 365.0)
Q_GLICKO = math.log(10) / 400.0
HALF_LIFE_DAYS = 180.0
PRIOR_POINTS = 50.0
DEFAULT_SERVE_SHARE = kalman.DEFAULT_SERVE_SHARE
SKILL_RATE = 0.002
INTERCEPT_RATE = 0.0001
LN10_400 = math.log(10) / 400.0
LAG_DAYS = kalman.LAG_DAYS

TIERS = ("tour", "qualifying", "challenger", "futures")
TIER_CODE = {t: i for i, t in enumerate(TIERS)}
ROUND_SORT = {
    "Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, "ER": 4, "RR": 5, "R128": 6, "R64": 7,
    "R32": 8, "R16": 9, "QF": 10, "SF": 11, "BR": 12, "F": 13,
}  # fmt: skip
ROUND_CODE = {
    "Q1": -4, "Q2": -3, "Q3": -2, "Q4": -1, "ER": -1, "R128": 0, "R64": 1, "R32": 2,
    "R16": 3, "RR": 3, "QF": 4, "SF": 5, "BR": 6, "F": 6,
}  # fmt: skip
SURFACES = kalman.SURFACES
ENTRY_CODES = ("Q", "LL", "WC", "PR", "SE", "ALT")
STATUS = ("completed", "retired", "defaulted", "walkover", "abandoned", "unknown")
COMPLETED, RETIRED, DEFAULTED, WALKOVER, ABANDONED, UNKNOWN = range(6)
SYMBOLIC_CONTEXT = ("tier", "level", "round", "surface")

PARAMETERS = {
    "K": K_FACTOR,
    "tier_weight": TIER_WEIGHT,
    "newcomer_all_tier_elo": NEWCOMER_ELO,
    "tour_elo_start": TOUR_ELO_START,
    "rd_max": RD_MAX,
    "rd_c2_per_day": RD_C2,
    "serve_half_life_days": HALF_LIFE_DAYS,
    "serve_prior_points": PRIOR_POINTS,
    "serve_skill_eta": SKILL_RATE,
    "serve_mu_eta": INTERCEPT_RATE,
    "lag_days": LAG_DAYS,
}

# Per-player values read at a row's cutoff, in this order.
SIDE_NAMES = (
    "elo_all", "elo_tour", "elo_surface", "rd", "serve_rate", "return_rate", "serve_skill",
    "return_skill", "win5", "win10", "win25", "games10", "games25", "sets10", "sets25",
    "opp_elo10", "n7", "n14", "n30", "n90", "days_since", "unseen", "ret90", "ret365", "wo90",
    "wo365", "days_since_ret", "c_tour", "c_qual", "c_chall", "c_fut", "titles", "finals",
    "slam_m", "masters_m", "top50_wins", "lp28", "lp91", "serve_pts_eff",
)  # fmt: skip
SI = {name: i for i, name in enumerate(SIDE_NAMES)}


# ------------------------------------------------------------------ scores

SET_RE = re.compile(r"^(\[)?(\d+)-(\d+)\]?(?:\((\d+)\))?\??$")


def parse_score(score: str) -> tuple[int, int, int, int, int]:
    """(status, games won, games lost, sets won, sets lost), from the winner's side.

    A retirement counts the games played and only the completed sets; a walkover counts
    nothing; a ``[10-8]`` match tiebreak counts as one game and one set.
    """
    tokens = score.replace("&nbsp;", " ").split()
    upper = {t.upper().rstrip(".") for t in tokens}
    if "W/O" in upper or "WALKOVER" in upper:
        return WALKOVER, 0, 0, 0, 0
    if "RET" in upper or "RE" in upper:
        status = RETIRED
    elif "DEF" in upper or "DEFAULT" in upper:
        status = DEFAULTED
    elif upper & {"PLAYED", "ABANDONED", "ABD", "UNFINISHED"}:
        status = ABANDONED
    else:
        status = COMPLETED
    sets = []
    for token in tokens:
        match = SET_RE.match(token)
        if match:
            sets.append(
                (
                    match.group(1) is not None,
                    int(match.group(2)),
                    int(match.group(3)),
                    match.group(4) is not None,
                )
            )
    if not sets:
        return (UNKNOWN if status == COMPLETED else status), 0, 0, 0, 0
    gw = gl = sw = sl = 0
    last = len(sets) - 1
    for j, (bracket, x, y, tiebreak) in enumerate(sets):
        if bracket:
            complete = x != y
            if complete:
                if x > y:
                    gw += 1
                else:
                    gl += 1
        else:
            gw += x
            gl += y
            if status == COMPLETED or j < last:
                complete = x != y
            else:
                hi, lo = max(x, y), min(x, y)
                complete = (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo == 6) or tiebreak
        if complete:
            if x > y:
                sw += 1
            elif y > x:
                sl += 1
    return status, gw, gl, sw, sl


# ------------------------------------------------------------------ the replay


class Player:
    __slots__ = (
        "init", "elo", "elo_t", "elo_s", "rd", "rd_t", "svw", "svp", "rtw", "rtp", "sv_t",
        "s", "r", "recent", "dates", "ret", "wo", "cnt", "titles", "finals", "slam",
        "masters", "top50", "pd", "pv",
    )  # fmt: skip

    def __init__(self, tier: str, day: int):
        self.init = NEWCOMER_ELO[tier]
        self.elo = self.init
        self.elo_t = TOUR_ELO_START
        self.elo_s: dict[str, float] = {}
        self.rd, self.rd_t = RD_MAX, day
        self.svw = self.svp = self.rtw = self.rtp = 0.0
        self.sv_t = day
        self.s = self.r = 0.0
        self.recent: deque = deque(maxlen=25)
        self.dates: list[int] = []
        self.ret: list[int] = []
        self.wo: list[int] = []
        self.cnt = [0, 0, 0, 0]
        self.titles = self.finals = self.slam = self.masters = self.top50 = 0
        self.pd: list[int] = []
        self.pv: list[float] = []


def table_order(rows: SourceRows) -> np.ndarray:
    """The total order: (date, tier, tourney_id, round, match_num), stable."""
    day, tiers, tourney = rows["day"], rows["tier"], rows["tourney_id"]
    rounds, match_num = rows["round"], rows["match_num"]
    keys = [
        (
            int(day[i]),
            TIER_CODE[tiers[i]],
            tourney[i],
            ROUND_SORT.get(rounds[i], 99),
            int(match_num[i]),
        )
        for i in range(len(day))
    ]
    return np.array(sorted(range(len(keys)), key=keys.__getitem__), dtype=np.int64)


def serve_counts(rows: SourceRows, status: np.ndarray):
    """Serve points played and won by each side, and the mask of valid completed/retired rows."""
    w_sv = numbers(rows["w_svpt"])
    w_sp = numbers(rows["w_1stWon"]) + numbers(rows["w_2ndWon"])
    l_sv = numbers(rows["l_svpt"])
    l_sp = numbers(rows["l_1stWon"]) + numbers(rows["l_2ndWon"])
    with np.errstate(invalid="ignore"):
        ok = (
            (w_sv > 0)
            & (l_sv > 0)
            & (w_sp >= 0)
            & (l_sp >= 0)
            & (w_sp <= w_sv)
            & (l_sp <= l_sv)
            & np.isin(status, [COMPLETED, RETIRED])
        )
    return ok, w_sv, w_sp, l_sv, l_sp


@dataclass
class Table:
    """The built table: columns in output order and the column groups."""

    columns: dict[str, np.ndarray]
    groups: dict[str, list[str]]

    def __len__(self) -> int:
        return len(self.columns["row_id"])

    def numeric(self) -> tuple[np.ndarray, list[str]]:
        """Signed plus numeric context columns as float64 (the controls compare these)."""
        names = self.groups["signed"] + [
            c for c in self.groups["context"] if c not in SYMBOLIC_CONTEXT
        ]
        return np.column_stack([self.columns[c].astype(float) for c in names]), names


def build(rows: SourceRows, filter_settings: kalman.KalmanSettings | None) -> Table:
    """Replay ``rows`` and assemble the table, in table order."""
    rows = rows.subset(table_order(rows))
    n = len(rows)
    parsed = [parse_score(s) for s in rows["score"]]
    status = np.array([p[0] for p in parsed])
    gwl = np.array([p[1:] for p in parsed], dtype=float).reshape(n, 4)
    stats_ok, w_sv, w_sp, l_sv, l_sp = serve_counts(rows, status)
    l_rank = numbers(rows["loser_rank"])
    w_pts = numbers(rows["winner_rank_points"])
    l_pts = numbers(rows["loser_rank_points"])

    M = rows["day"].tolist()
    W = rows["winner_id"].tolist()
    L = rows["loser_id"].tolist()
    A = rows["player_a"].tolist()
    B = rows["player_b"].tolist()
    tiers = list(rows["tier"])
    tc = [TIER_CODE[t] for t in tiers]
    surf = list(rows["surface"])
    lvl = list(rows["tourney_level"])
    rnd = list(rows["round"])
    status_l = status.tolist()
    stats_l = stats_ok.tolist()
    wsv, wsp, lsv, lsp = w_sv.tolist(), w_sp.tolist(), l_sv.tolist(), l_sp.tolist()
    lrank_l = l_rank.tolist()
    wlp = np.log1p(w_pts).tolist()
    llp = np.log1p(l_pts).tolist()
    gwl_l = gwl.tolist()

    players: dict[int, Player] = {}
    h2h: dict[tuple, list[int]] = {}
    pool = {
        "svw": 0.0,
        "svp": 0.0,
        "mu": math.log(DEFAULT_SERVE_SHARE / (1 - DEFAULT_SERVE_SHARE)),
    }
    FA: list[Any] = [None] * n
    FB: list[Any] = [None] * n
    HH: list[Any] = [None] * n
    MU = np.zeros(n)
    nan = math.nan
    isnan = math.isnan
    bl, br = bisect.bisect_left, bisect.bisect_right

    def get(pid: int, k: int) -> Player:
        p = players.get(pid)
        if p is None:
            p = Player(tiers[k], M[k])
            players[pid] = p
        return p

    def feats(p: Player, dd: int, sf: str, avg: float) -> tuple:
        rd = min(RD_MAX, math.sqrt(p.rd * p.rd + RD_C2 * (dd - p.rd_t)))
        f = 2.0 ** (-(dd - p.sv_t) / HALF_LIFE_DAYS)
        svp = p.svp * f
        sv = (p.svw * f + PRIOR_POINTS * avg) / (svp + PRIOR_POINTS)
        rt = (p.rtw * f + PRIOR_POINTS * (1 - avg)) / (p.rtp * f + PRIOR_POINTS)
        es = p.elo_s.get(sf, p.init) if sf in SURFACES else nan
        rec = p.recent
        nr = len(rec)
        w5 = w10 = w25 = g10 = g25 = s10 = s25 = oe10 = nan
        if nr:
            sw = sww = 0.0
            gw = gt = sw_ = st = 0.0
            oe = 0.0
            k = 0
            c5, c10, c25 = min(5, nr), min(10, nr), nr
            for e in reversed(rec):
                k += 1
                sww += e[1] * e[0]
                sw += e[1]
                gw += e[2]
                gt += e[3]
                sw_ += e[4]
                st += e[5]
                if k <= 10:
                    oe += e[6]
                if k == c5:
                    w5 = sww / sw
                if k == c10:
                    w10 = sww / sw
                    g10 = gw / gt if gt else nan
                    s10 = sw_ / st if st else nan
                    oe10 = oe / k
                if k == c25:
                    w25 = sww / sw
                    g25 = gw / gt if gt else nan
                    s25 = sw_ / st if st else nan
        ds = p.dates
        nd = len(ds)
        if nd:
            n7 = nd - bl(ds, dd - 7)
            n14 = nd - bl(ds, dd - 14)
            n30 = nd - bl(ds, dd - 30)
            n90 = nd - bl(ds, dd - 90)
            since = min(365, dd - ds[-1])
            unseen = 0
        else:
            n7 = n14 = n30 = n90 = 0
            since = 365
            unseen = 1
        rt_ = p.ret
        wo = p.wo
        ret90 = len(rt_) - bl(rt_, dd - 90)
        ret365 = len(rt_) - bl(rt_, dd - 365)
        wo90 = len(wo) - bl(wo, dd - 90)
        wo365 = len(wo) - bl(wo, dd - 365)
        since_ret = min(365, dd - rt_[-1]) if rt_ else 365
        j = br(p.pd, dd - 28) - 1
        lp28 = p.pv[j] if j >= 0 else nan
        j = br(p.pd, dd - 91) - 1
        lp91 = p.pv[j] if j >= 0 else nan
        c = p.cnt
        return (
            p.elo, p.elo_t, es, rd, sv, rt, p.s, p.r, w5, w10, w25, g10, g25, s10, s25, oe10,
            n7, n14, n30, n90, since, unseen, ret90, ret365, wo90, wo365, since_ret,
            c[0], c[1], c[2], c[3], p.titles, p.finals, p.slam, p.masters, p.top50,
            lp28, lp91, svp,
        )  # fmt: skip

    def elo_step(rw: float, rl: float, kk: float) -> float:
        ew = 1.0 / (1.0 + 10.0 ** ((rl - rw) / 400.0))
        return kk * (1.0 - ew)

    def rd_update(p: Player, opp: Player, ms: int, rself: float, ropp: float) -> float:
        rd_pre = min(RD_MAX, math.sqrt(p.rd * p.rd + RD_C2 * (ms - p.rd_t)))
        ro = min(RD_MAX, math.sqrt(opp.rd * opp.rd + RD_C2 * (ms - opp.rd_t)))
        gg = 1.0 / math.sqrt(1.0 + 3.0 * Q_GLICKO**2 * ro * ro / math.pi**2)
        e = 1.0 / (1.0 + 10.0 ** (-gg * (rself - ropp) / 400.0))
        inv_d2 = Q_GLICKO**2 * gg * gg * e * (1.0 - e)
        return 1.0 / math.sqrt(1.0 / (rd_pre * rd_pre) + inv_d2)

    def release(k: int) -> None:
        ms = M[k]
        pw, pl = players[W[k]], players[L[k]]
        st = status_l[k]
        t = tc[k]
        tour = t == 0
        if not isnan(wlp[k]):
            pw.pd.append(ms)
            pw.pv.append(wlp[k])
        if not isnan(llp[k]):
            pl.pd.append(ms)
            pl.pv.append(llp[k])
        if st == WALKOVER:
            pl.wo.append(ms)
        else:
            pw.dates.append(ms)
            pl.dates.append(ms)
            pw.cnt[t] += 1
            pl.cnt[t] += 1
            if tour and lvl[k] == "G":
                pw.slam += 1
                pl.slam += 1
            elif tour and lvl[k] == "M":
                pw.masters += 1
                pl.masters += 1
        if st == RETIRED:
            pl.ret.append(ms)
        if tour and rnd[k] == "F" and st != UNKNOWN:
            pw.finals += 1
            pl.finals += 1
            pw.titles += 1
        if st == COMPLETED or st == RETIRED:
            tw = TIER_WEIGHT[tiers[k]]
            gw_, gl_, sw_, sl_ = gwl_l[k]
            rw, rl = pw.elo, pl.elo
            pw.recent.append((1.0, tw, gw_, gw_ + gl_, sw_, sw_ + sl_, rl))
            pl.recent.append((0.0, tw, gl_, gw_ + gl_, sl_, sw_ + sl_, rw))
            rdw = rd_update(pw, pl, ms, rw, rl)
            rdl = rd_update(pl, pw, ms, rl, rw)
            pw.rd, pw.rd_t, pl.rd, pl.rd_t = rdw, ms, rdl, ms
            dlt = elo_step(rw, rl, K_FACTOR * tw)
            pw.elo = rw + dlt
            pl.elo = rl - dlt
            if tour:
                dlt = elo_step(pw.elo_t, pl.elo_t, K_FACTOR)
                pw.elo_t += dlt
                pl.elo_t -= dlt
            sf = surf[k]
            if sf in SURFACES:
                a_ = pw.elo_s.get(sf, pw.init)
                b_ = pl.elo_s.get(sf, pl.init)
                dlt = elo_step(a_, b_, K_FACTOR * tw)
                pw.elo_s[sf] = a_ + dlt
                pl.elo_s[sf] = b_ - dlt
            lo, hi = (W[k], L[k]) if W[k] < L[k] else (L[k], W[k])
            win_lo = 1 if W[k] == lo else 0
            for key in ((lo, hi), (lo, hi, sf)) if sf in SURFACES else ((lo, hi),):
                e = h2h.get(key)
                if e is None:
                    h2h[key] = [1, win_lo]
                else:
                    e[0] += 1
                    e[1] += win_lo
            if lrank_l[k] <= 50:
                pw.top50 += 1
        if stats_l[k]:
            a1, b1, a2, b2 = wsv[k], wsp[k], lsv[k], lsp[k]
            for p, svn, svk, rtn, rtk in ((pw, a1, b1, a2, a2 - b2), (pl, a2, b2, a1, a1 - b1)):
                f = 2.0 ** (-(ms - p.sv_t) / HALF_LIFE_DAYS)
                p.svw = p.svw * f + svk
                p.svp = p.svp * f + svn
                p.rtw = p.rtw * f + rtk
                p.rtp = p.rtp * f + rtn
                p.sv_t = ms
            pool["svw"] += b1 + b2
            pool["svp"] += a1 + a2
            mu = pool["mu"]
            gw_res = b1 - a1 / (1.0 + math.exp(-(mu + pw.s - pl.r)))
            gl_res = b2 - a2 / (1.0 + math.exp(-(mu + pl.s - pw.r)))
            pw.s += SKILL_RATE * gw_res
            pl.r -= SKILL_RATE * gw_res
            pl.s += SKILL_RATE * gl_res
            pw.r -= SKILL_RATE * gl_res
            pool["mu"] = mu + INTERCEPT_RATE * (gw_res + gl_res)

    i = 0
    released = 0
    while i < n:
        dd = M[i]
        while released < i and M[released] <= dd - LAG_DAYS:
            release(released)
            released += 1
        avg = pool["svw"] / pool["svp"] if pool["svp"] > 0 else DEFAULT_SERVE_SHARE
        mu = pool["mu"]
        j = i
        while j < n and M[j] == dd:
            j += 1
        for k in range(i, j):
            a, b = A[k], B[k]
            pa_, pb_ = get(a, k), get(b, k)
            sf = surf[k]
            FA[k] = feats(pa_, dd, sf, avg)
            FB[k] = feats(pb_, dd, sf, avg)
            lo, hi = (a, b) if a < b else (b, a)
            e = h2h.get((lo, hi))
            hn, hw = (e[0], e[1]) if e else (0, 0)
            if a != lo:
                hw = hn - hw
            e = h2h.get((lo, hi, sf))
            sn, sw = (e[0], e[1]) if e else (0, 0)
            if a != lo:
                sw = sn - sw
            HH[k] = (hn, (hw + 0.5) / (hn + 1) - 0.5, sn, (sw + 0.5) / (sn + 1) - 0.5)
            MU[k] = mu
        i = j

    state = None
    if filter_settings is not None:
        state, _ = kalman.run_filter(
            M, A, B, W, L, tiers, surf, stats_l, wsv, wsp, lsv, lsp, filter_settings
        )
    return assemble(
        rows,
        np.array(FA, dtype=float).reshape(n, len(SIDE_NAMES)),
        np.array(FB, dtype=float).reshape(n, len(SIDE_NAMES)),
        np.array(HH, dtype=float).reshape(n, 4),
        MU,
        gwl,
        status,
        stats_ok,
        (w_sv, w_sp, l_sv, l_sp),
        state,
    )


def assemble(rows, FA, FB, HH, MU, gwl, status, stats_ok, counts, state) -> Table:
    w_sv, w_sp, l_sv, l_sp = counts
    a_is_w = rows["player_a"] == rows["winner_id"]
    out: dict[str, np.ndarray] = {
        "row_id": rows["row_id"],
        "family": rows["family"],
        "tier": rows["tier"],
        "season": rows["season"],
        "date": np.array([day_iso(int(d)) for d in rows["day"]], dtype=object),
        "date_source": rows["date_source"],
        "tourney_id": rows["tourney_id"],
        "match_num": rows["match_num"],
        "level": rows["tourney_level"],
        "round": rows["round"],
        "lab_match_id": rows["match_id"],
        "player_a": rows["player_a"],
        "player_b": rows["player_b"],
    }

    def side(winner_values: np.ndarray, loser_values: np.ndarray):
        return np.where(a_is_w, winner_values, loser_values), np.where(
            a_is_w, loser_values, winner_values
        )

    def num_side(name: str):
        return side(numbers(rows[f"winner_{name}"]), numbers(rows[f"loser_{name}"]))

    def diff(name: str) -> np.ndarray:
        return FA[:, SI[name]] - FB[:, SI[name]]

    def log1p_diff(name: str) -> np.ndarray:
        return np.log1p(FA[:, SI[name]]) - np.log1p(FB[:, SI[name]])

    S: dict[str, np.ndarray] = {}
    S["elo_all_logit"] = diff("elo_all") * LN10_400
    S["elo_tour_logit"] = diff("elo_tour") * LN10_400
    S["elo_surface_logit"] = diff("elo_surface") * LN10_400
    S["elo_blend_logit"] = 0.5 * (S["elo_all_logit"] + S["elo_surface_logit"])
    S["rd_diff"] = diff("rd")
    S["serve_rate_diff"] = diff("serve_rate")
    S["return_rate_diff"] = diff("return_rate")
    S["serve_pts_eff_log_diff"] = log1p_diff("serve_pts_eff")
    S["serve_skill_diff"] = diff("serve_skill")
    S["return_skill_diff"] = diff("return_skill")
    xa = MU + FA[:, SI["serve_skill"]] - FB[:, SI["return_skill"]]
    xb = MU + FB[:, SI["serve_skill"]] - FA[:, SI["return_skill"]]
    S["oa_serve_logit_diff"] = xa - xb
    best_of = np.nan_to_num(numbers(rows["best_of"]), nan=3.0)
    S["oa_match_logit"] = pointmodel.match_logit(
        1 / (1 + np.exp(-xa)), 1 / (1 + np.exp(-xb)), best_of
    )
    for name in ("win5", "win10", "win25", "games10", "games25", "sets10", "sets25"):
        S[f"form_{name}_diff"] = diff(name)
    S["opp_elo10_logit"] = diff("opp_elo10") * LN10_400
    for name in (
        "n7", "n14", "n30", "n90", "days_since", "unseen", "ret90", "ret365", "wo90",
        "wo365", "days_since_ret",
    ):  # fmt: skip
        S[f"act_{name}_diff"] = diff(name)
    for name in (
        "c_tour", "c_qual", "c_chall", "c_fut", "titles", "finals", "slam_m", "masters_m",
        "top50_wins",
    ):  # fmt: skip
        S[f"exp_{name}_log_diff"] = log1p_diff(name)
    ra, rb = num_side("rank")
    qa, qb = num_side("rank_points")
    with np.errstate(divide="ignore", invalid="ignore"):
        S["log_rank_diff"] = np.log(ra) - np.log(rb)
        S["log_points_diff"] = np.log1p(qa) - np.log1p(qb)
        S["rank_missing_diff"] = np.isnan(ra).astype(float) - np.isnan(rb).astype(float)
        S["points_missing_diff"] = np.isnan(qa).astype(float) - np.isnan(qb).astype(float)
        S["mom28_diff"] = (np.log1p(qa) - FA[:, SI["lp28"]]) - (np.log1p(qb) - FB[:, SI["lp28"]])
        S["mom91_diff"] = (np.log1p(qa) - FA[:, SI["lp91"]]) - (np.log1p(qb) - FB[:, SI["lp91"]])
    ga, gb = side(rows["winner_age"], rows["loser_age"])
    ha, hb = side(rows["winner_ht"], rows["loser_ht"])
    hda, hdb = side(rows["winner_hand"], rows["loser_hand"])
    S["age_diff"] = ga - gb
    S["age_sq_diff"] = ga**2 - gb**2
    S["height_diff"] = ha - hb
    S["lefty_diff"] = (hda == "L").astype(float) - (hdb == "L").astype(float)
    S["age_missing_diff"] = np.isnan(ga).astype(float) - np.isnan(gb).astype(float)
    S["height_missing_diff"] = np.isnan(ha).astype(float) - np.isnan(hb).astype(float)
    S["hand_missing_diff"] = (~np.isin(hda, ["R", "L", "A"])).astype(float) - (
        ~np.isin(hdb, ["R", "L", "A"])
    ).astype(float)
    S["h2h_share_c"] = HH[:, 1]
    S["h2h_surface_share_c"] = HH[:, 3]
    ea, eb = side(rows["winner_entry"], rows["loser_entry"])
    ea = np.array([str(v).upper() for v in ea], dtype=object)
    eb = np.array([str(v).upper() for v in eb], dtype=object)
    for code in ENTRY_CODES:
        S[f"entry_{code.lower()}_diff"] = (ea == code).astype(float) - (eb == code).astype(float)
    sa, sb = num_side("seed")
    S["seeded_diff"] = (~np.isnan(sa)).astype(float) - (~np.isnan(sb)).astype(float)
    with np.errstate(invalid="ignore"):
        S["log_seed_diff"] = np.log(sa) - np.log(sb)
    if state is not None:
        S["k_serve_diff"] = state[:, 0] - state[:, 2]
        S["k_return_diff"] = state[:, 1] - state[:, 3]
        S["k_point_logit_diff"] = state[:, 6] - state[:, 7]
        S["k_match_logit"] = pointmodel.match_logit(
            1 / (1 + np.exp(-state[:, 6])), 1 / (1 + np.exp(-state[:, 7])), best_of
        )
        S["k_var_diff"] = state[:, 4] - state[:, 5]

    C: dict[str, np.ndarray] = {}
    C["tier_code"] = np.array([TIER_CODE[t] for t in rows["tier"]], dtype=np.int64)
    C["round_code"] = np.array([ROUND_CODE.get(r, np.nan) for r in rows["round"]], dtype=float)
    surface = rows["surface"]
    for s_ in SURFACES:
        C[f"surface_{s_.lower()}"] = (surface == s_).astype(float)
    C["best_of"] = best_of
    C["draw_size"] = numbers(rows["draw_size"])
    C["any_qualifier"] = (np.isin(ea, ["Q", "LL"]) | np.isin(eb, ["Q", "LL"])).astype(float)
    C["any_seeded"] = ((~np.isnan(sa)) | (~np.isnan(sb))).astype(float)
    C["h2h_n"] = HH[:, 0]
    C["h2h_surface_n"] = HH[:, 2]
    C["elo_all_mean"] = 0.5 * (FA[:, SI["elo_all"]] + FB[:, SI["elo_all"]])
    C["rd_mean"] = 0.5 * (FA[:, SI["rd"]] + FB[:, SI["rd"]])
    if state is not None:
        C["k_var_sum"] = state[:, 4] + state[:, 5]

    T: dict[str, np.ndarray] = {}
    T["a_won"] = a_is_w.astype(np.int8)
    a_sp = np.where(a_is_w, w_sp + (l_sv - l_sp), l_sp + (w_sv - w_sp))
    gw, gl, sw, sl = gwl.T
    played = ~np.isin(status, [WALKOVER, UNKNOWN])
    with np.errstate(invalid="ignore", divide="ignore"):
        T["a_points_share"] = np.where(stats_ok, a_sp / (w_sv + l_sv), np.nan)
        T["a_games"] = np.where(a_is_w, gw, gl)
        T["b_games"] = np.where(a_is_w, gl, gw)
        T["a_sets"] = np.where(a_is_w, sw, sl)
        T["b_sets"] = np.where(a_is_w, sl, sw)
        T["a_games_share"] = np.where(played & (gw + gl > 0), T["a_games"] / (gw + gl), np.nan)
        T["a_sets_share"] = np.where(played & (sw + sl > 0), T["a_sets"] / (sw + sl), np.nan)
    for code, name in enumerate(STATUS):
        T[f"is_{name}"] = (status == code).astype(float)
    T["minutes"] = numbers(rows["minutes"])
    T["has_serve_stats"] = stats_ok.astype(float)

    columns = {**out, "surface": surface, **S, **C, **T}
    groups = {
        "id": list(out),
        "signed": list(S),
        "context": [*SYMBOLIC_CONTEXT, *C],
        "target": list(T),
    }
    return Table(columns, groups)


# ------------------------------------------------------------------ output

FLOAT_FORMAT = "%.12g"


def _cell(value: Any, is_float: bool) -> str:
    if is_float:
        return "" if value != value else FLOAT_FORMAT % value
    return str(value)


def csv_text(table: Table) -> str:
    """The table as CSV: floats at 12 significant digits, NaN blank, ``\\n`` line ends."""
    names = list(table.columns)
    kinds = [table.columns[c].dtype.kind == "f" for c in names]
    arrays = [table.columns[c].tolist() for c in names]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(names)
    for i in range(len(table)):
        writer.writerow([_cell(col[i], kind) for col, kind in zip(arrays, kinds, strict=True)])
    return buffer.getvalue()


def write_csv_gz(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(gzip.compress(text.encode("utf-8"), compresslevel=4, mtime=0))
    temporary.replace(path)


# ------------------------------------------------------------------ numeric matrix

LEVELS = ("G", "M", "A", "F", "C", "S", "15", "25", "O")
MATRIX_META = (
    "row_id", "tier", "season", "date", "lab_match_id", "level", "round", "player_a", "player_b",
)  # fmt: skip
MATRIX_TARGETS = (
    "a_won", "a_points_share", "a_games_share", "is_completed", "is_retired", "is_walkover",
    "has_serve_stats",
)  # fmt: skip


def _parse(text: str) -> float:
    return float(text) if text != "" else np.nan


def matrix_arrays(text: str, groups: Mapping[str, Sequence[str]]) -> dict[str, np.ndarray]:
    """The model's numeric view, parsed from the written CSV (so the model reads exactly the
    12-digit values the file carries): signed and numeric context columns plus level
    one-hots, the targets the model reads, and the row metadata as text."""
    signed_cols = list(groups["signed"])
    context_cols = [c for c in groups["context"] if c not in SYMBOLIC_CONTEXT]
    reader = csv.DictReader(io.StringIO(text, newline=""))
    meta: dict[str, list[str]] = {k: [] for k in MATRIX_META}
    signed, context, targets = [], [], []
    for r in reader:
        for k in MATRIX_META:
            meta[k].append(r[k])
        signed.append([_parse(r[c]) for c in signed_cols])
        level = r["level"] if r["level"] in LEVELS else "O"
        context.append([_parse(r[c]) for c in context_cols] + [float(level == v) for v in LEVELS])
        targets.append([_parse(r[c]) for c in MATRIX_TARGETS])
    return {
        "signed": np.array(signed),
        "context": np.array(context),
        "targets": np.array(targets),
        "signed_cols": np.array(signed_cols),
        "context_cols": np.array(context_cols + [f"level_{v}" for v in LEVELS]),
        "target_cols": np.array(MATRIX_TARGETS),
        **{k: np.array(v) for k, v in meta.items()},
    }
