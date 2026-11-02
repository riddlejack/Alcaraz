"""The serve/return filter of the all-tier table, and the routine that tunes it.

Each player carries a serve skill ``s`` and a return skill ``r`` on the logit scale, each
with its own variance, and per surface (Hard, Clay, Grass, Carpet) a serve deviation ``u``
and a return deviation ``w``. The server's point-win logit against a returner is

    eta = mu[group, surface] + s_srv + u_srv - r_ret - w_ret

where the group is ``tour`` for tour rows and ``lower`` for every other tier. A released
row with valid serve counts is two observations, k of n serve points won by each side,
each Binomial(n, sigmoid(eta)). Each observation takes one Newton step from the prior mean
(an extended Kalman step on the logit link) with a diagonal covariance kept: with
g = tau (k - n p), I = tau n p (1 - p) and V the summed variance of the four parameters
in eta, each parameter moves by +/- v g / (1 + I V) and each variance becomes
v - v^2 I / (1 + I V). The two sides of a match touch disjoint parameters, so both update
from the same prior. ``tau`` tempers lower-tier rows (1 on tour rows).

Variances grow by ``q`` per idle day up to the prior variance V0 (surface deviations by
q V_surf / V0 up to V_surf). The intercept ``mu`` starts at the logit of a 62% serve
share and moves by ``mu_rate`` times the summed untempered per-side Newton steps; a
(lower, surface) intercept not yet updated reads the tour value for that surface.

The filter replays rows in table order under the two-day release rule: before the rows
dated d are read, every earlier row dated d - 2 or before is released. Rows without valid
counts update nothing.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

SURFACES = ("Hard", "Clay", "Grass", "Carpet")
LAG_DAYS = 2
DEFAULT_SERVE_SHARE = 0.62


@dataclass(frozen=True)
class KalmanSettings:
    V0: float
    q: float
    V_surf: float
    temper_lower: float
    mu_rate: float
    mu0: float

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> KalmanSettings:
        share = float(mapping.get("mu0_serve_share", DEFAULT_SERVE_SHARE))
        return cls(
            V0=float(mapping["V0"]),
            q=float(mapping["q"]),
            V_surf=float(mapping["V_surf"]),
            temper_lower=float(mapping["temper_lower"]),
            mu_rate=float(mapping["mu_rate"]),
            mu0=math.log(share / (1 - share)),
        )

    def replace(self, **changes: float) -> KalmanSettings:
        return KalmanSettings(**{**asdict(self), **changes})


# Columns of the per-row state returned by :func:`run_filter`.
STATE_COLUMNS = ("s_a", "r_a", "s_b", "r_b", "var_a", "var_b", "eta_a", "eta_b")


def run_filter(
    day: Sequence[int],
    player_a: Sequence[int],
    player_b: Sequence[int],
    winner: Sequence[int],
    loser: Sequence[int],
    tiers: Sequence[str],
    surfaces: Sequence[str],
    observed: Sequence[bool],
    winner_serve_points: Sequence[float],
    winner_serve_won: Sequence[float],
    loser_serve_points: Sequence[float],
    loser_serve_won: Sequence[float],
    settings: KalmanSettings,
    score_window: tuple[int, int] | None = None,
) -> tuple[np.ndarray, tuple[float, float, int]]:
    """Replay the filter over rows already in table order (``day`` ascending).

    Returns the state at each row's two-day cutoff (columns :data:`STATE_COLUMNS`; the
    variances are each side's total on the row's surface) and, for rows dated inside
    ``score_window`` with valid counts, the Binomial log-likelihood of both sides' serve
    points under that state, the points and the rows: ``(loglik, points, rows)``.
    """
    n = len(day)
    v0, q, vs, tau = settings.V0, settings.q, settings.V_surf, settings.temper_lower
    lam, mu0 = settings.mu_rate, settings.mu0
    qs = q * vs / v0 if v0 > 0 else 0.0
    use_surface = vs > 0
    skills: dict[int, list[float]] = {}  # player -> [s, r, var_s, var_r, last day]
    deviations: dict[tuple[int, str], list[float]] = {}  # (player, surface) -> [u, w, ...]
    mu: dict[tuple[str, str], float] = {}
    exp_, log_ = math.exp, math.log
    state = np.empty((n, len(STATE_COLUMNS)))
    loglik = points = 0.0
    rows = 0
    low, high = score_window if score_window is not None else (1, 0)

    def intercept(tier: str, surface: str) -> tuple[tuple[str, str], float]:
        key = ("tour" if tier == "tour" else "lower", surface if surface in SURFACES else "other")
        value = mu.get(key)
        if value is None:
            value = mu.get(("tour", key[1]), mu0)
        return key, value

    def player(pid: int, d: int) -> tuple[float, float, float, float]:
        entry = skills.get(pid)
        if entry is None:
            return 0.0, 0.0, v0, v0
        dt = d - entry[4]
        return entry[0], entry[1], min(v0, entry[2] + q * dt), min(v0, entry[3] + q * dt)

    def deviation(pid: int, surface: str, d: int) -> tuple[float, float, float, float]:
        if not use_surface or surface not in SURFACES:
            return 0.0, 0.0, 0.0, 0.0
        entry = deviations.get((pid, surface))
        if entry is None:
            return 0.0, 0.0, vs, vs
        dt = d - entry[4]
        return entry[0], entry[1], min(vs, entry[2] + qs * dt), min(vs, entry[3] + qs * dt)

    def release(k: int) -> None:
        d, surface = day[k], surfaces[k]
        temper = tau if tiers[k] != "tour" else 1.0
        sw, rw, vsw, vrw = player(winner[k], d)
        sl, rl, vsl, vrl = player(loser[k], d)
        uw, ww, vuw, vww = deviation(winner[k], surface, d)
        ul, wl, vul, vwl = deviation(loser[k], surface, d)
        key, m = intercept(tiers[k], surface)
        # Side 1: the winner serves against the loser's return; side 2 the reverse.
        p1 = 1.0 / (1.0 + exp_(-(m + sw + uw - rl - wl)))
        p2 = 1.0 / (1.0 + exp_(-(m + sl + ul - rw - ww)))
        n1, k1 = winner_serve_points[k], winner_serve_won[k]
        n2, k2 = loser_serve_points[k], loser_serve_won[k]
        g1, i1 = k1 - n1 * p1, n1 * p1 * (1.0 - p1)
        g2, i2 = k2 - n2 * p2, n2 * p2 * (1.0 - p2)
        mu[key] = m + lam * (g1 / i1 + g2 / i2)
        g1, i1, g2, i2 = temper * g1, temper * i1, temper * g2, temper * i2
        den1 = 1.0 + i1 * (vsw + vuw + vrl + vwl)
        den2 = 1.0 + i2 * (vsl + vul + vrw + vww)
        c1, h1, c2, h2 = g1 / den1, i1 / den1, g2 / den2, i2 / den2
        skills[winner[k]] = [
            sw + vsw * c1,
            rw - vrw * c2,
            vsw - vsw * vsw * h1,
            vrw - vrw * vrw * h2,
            d,
        ]
        skills[loser[k]] = [
            sl + vsl * c2,
            rl - vrl * c1,
            vsl - vsl * vsl * h2,
            vrl - vrl * vrl * h1,
            d,
        ]
        if use_surface and surface in SURFACES:
            deviations[(winner[k], surface)] = [
                uw + vuw * c1,
                ww - vww * c2,
                vuw - vuw * vuw * h1,
                vww - vww * vww * h2,
                d,
            ]
            deviations[(loser[k], surface)] = [
                ul + vul * c2,
                wl - vwl * c1,
                vul - vul * vul * h2,
                vwl - vwl * vwl * h1,
                d,
            ]

    i = released = 0
    while i < n:
        d = day[i]
        while released < i and day[released] <= d - LAG_DAYS:
            if observed[released]:
                release(released)
            released += 1
        j = i
        while j < n and day[j] == d:
            j += 1
        for k in range(i, j):
            surface = surfaces[k]
            _, m = intercept(tiers[k], surface)
            sa, ra, vsa, vra = player(player_a[k], d)
            sb, rb, vsb, vrb = player(player_b[k], d)
            ua, wa, vua, vwa = deviation(player_a[k], surface, d)
            ub, wb, vub, vwb = deviation(player_b[k], surface, d)
            eta_a = m + sa + ua - rb - wb
            eta_b = m + sb + ub - ra - wa
            state[k] = (sa, ra, sb, rb, vsa + vra + vua + vwa, vsb + vrb + vub + vwb, eta_a, eta_b)
            if observed[k] and low <= d <= high:
                eta_w, eta_l = (eta_a, eta_b) if winner[k] == player_a[k] else (eta_b, eta_a)
                for eta, nn, kk in (
                    (eta_w, winner_serve_points[k], winner_serve_won[k]),
                    (eta_l, loser_serve_points[k], loser_serve_won[k]),
                ):
                    p = 1.0 / (1.0 + exp_(-eta))
                    loglik += kk * log_(p) + (nn - kk) * log_(1.0 - p)
                    points += nn
                rows += 1
        i = j
    return state, (loglik, points, rows)


# ------------------------------------------------------------------ tuning


def tune(
    rows: Mapping[str, Sequence[Any]],
    protocol: Mapping[str, Any],
    score_window: tuple[int, int],
) -> dict[str, Any]:
    """Choose the filter settings on the serve points of ``score_window``.

    ``rows`` holds the observed rows only (the filter's arguments by name: ``day``,
    ``player_a``, ... ``loser_serve_won``), in table order. The fixed protocol, every
    value of which comes from ``protocol``:

    1. a reference with the skills off (V0 = q = 0: the intercept alone);
    2. a V0 x q grid with V_surf = 0 and no temper;
    3. at most two extensions on each grid edge where the best value sits;
    4. the surface variances, at the best (V0, q);
    5. the lower-tier tempers, at the best so far;
    6. a refinement: V0 divided, q multiplied, then V_surf at fractions of the best V0.

    Each setting is scored by the summed log-likelihood of both sides' serve points
    under the row's two-day state, before its own update. Returns every setting scored
    and the best one.
    """
    fixed = {
        "mu_rate": float(protocol["mu_rate"]),
        "mu0_serve_share": float(protocol.get("mu0_serve_share", DEFAULT_SERVE_SHARE)),
    }
    results: list[dict[str, Any]] = []
    args = [rows[name] for name in FILTER_ARGUMENTS]

    def run(stage: str, V0: float, q: float, V_surf: float = 0.0, temper_lower: float = 1.0):
        settings = KalmanSettings.from_mapping(
            {**fixed, "V0": V0, "q": q, "V_surf": V_surf, "temper_lower": temper_lower}
        )
        _, (loglik, points, scored) = run_filter(*args, settings, score_window=score_window)
        result = {
            "stage": stage,
            "V0": V0,
            "q": q,
            "V_surf": V_surf,
            "temper_lower": temper_lower,
            "loglik": loglik,
            "points": points,
            "rows": scored,
            "logloss_per_point": -loglik / points,
        }
        results.append(result)
        return result

    def best(stage: str | None = None) -> dict[str, Any]:
        pool = [r for r in results if stage is None or r["stage"] == stage]
        return max(pool, key=lambda r: r["loglik"])

    grid = protocol["grid"]
    run("reference_skills_off", V0=0.0, q=0.0)
    for v0 in grid["V0"]:
        for q in grid["q"]:
            run("grid_V0_q", V0=v0, q=q)
    top = best("grid_V0_q")
    extensions: list[tuple[str, float]] = []
    for name in ("V0", "q"):
        edges = protocol["edge_extensions"][name]
        if top[name] == grid[name][-1]:
            extensions += [(name, float(v)) for v in edges["high"]]
        elif top[name] == grid[name][0]:
            extensions += [(name, float(v)) for v in edges["low"]]
    for name, value in extensions:
        run("edge_extension", **{"V0": top["V0"], "q": top["q"], name: value})
    top = best()
    for value in protocol["surface_variance"]:
        run("surface_variance", V0=top["V0"], q=top["q"], V_surf=value)
    top = best()
    for value in protocol["lower_tier_temper"]:
        run(
            "lower_tier_temper",
            V0=top["V0"],
            q=top["q"],
            V_surf=top["V_surf"],
            temper_lower=value,
        )
    top = best()
    refine = protocol["refinement"]
    kept = {"V_surf": top["V_surf"], "temper_lower": top["temper_lower"]}
    run("refine_V0_q", V0=top["V0"] / refine["V0_divisor"], q=top["q"], **kept)
    run("refine_V0_q", V0=top["V0"], q=top["q"] * refine["q_multiplier"], **kept)
    top = best()
    for divisor in refine["V_surf_divisors_of_V0"]:
        run(
            "refine_V_surf",
            V0=top["V0"],
            q=top["q"],
            V_surf=top["V0"] / divisor,
            temper_lower=top["temper_lower"],
        )
    return {"fixed": fixed, "settings_scored": len(results), "chosen": best(), "grid": results}


FILTER_ARGUMENTS = (
    "day",
    "player_a",
    "player_b",
    "winner",
    "loser",
    "tiers",
    "surfaces",
    "observed",
    "winner_serve_points",
    "winner_serve_won",
    "loser_serve_points",
    "loser_serve_won",
)
