"""The all-tier table: score parsing, the Elo/RD/serve-rate pieces by hand, and the timing
and orientation controls on a synthetic source."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tennislab.alltier import table
from tests.alltier_support import FILTER, swap_outcome, synthetic_rows


@pytest.mark.parametrize(
    "score,expected",
    [
        ("6-4 6-3", (table.COMPLETED, 12, 7, 2, 0)),
        ("7-6(5) 6-7(3) 6-4", (table.COMPLETED, 19, 17, 2, 1)),
        ("6-4 2-1 RET", (table.RETIRED, 8, 5, 1, 0)),
        ("6-4 7-5 RET", (table.RETIRED, 13, 9, 2, 0)),
        ("6-3 [10-8]", (table.COMPLETED, 7, 3, 2, 0)),
        ("W/O", (table.WALKOVER, 0, 0, 0, 0)),
        ("6-2 DEF", (table.DEFAULTED, 6, 2, 1, 0)),
        ("", (table.UNKNOWN, 0, 0, 0, 0)),
        ("Played and abandoned", (table.ABANDONED, 0, 0, 0, 0)),
    ],
)
def test_parse_score(score, expected):
    assert table.parse_score(score) == expected


def one_match(**overrides):
    """Two newcomers on tour: a beats b on day 100, then meet again on day 102."""
    rows = synthetic_rows(seed=1, rows=2)
    cols = {k: v.copy() for k, v in rows.columns.items()}
    cols.update(
        day=np.array([100, 102]),
        tier=np.array(["tour", "tour"], dtype=object),
        winner_id=np.array([1, 1]),
        loser_id=np.array([2, 2]),
        player_a=np.array([1, 1]),
        player_b=np.array([2, 2]),
        score=np.array(["6-4 6-4", "6-4 6-4"], dtype=object),
        surface=np.array(["Clay", "Clay"], dtype=object),
        tourney_level=np.array(["A", "A"], dtype=object),
        w_svpt=np.array(["60", "60"], dtype=object),
        w_1stWon=np.array(["30", "30"], dtype=object),
        w_2ndWon=np.array(["10", "10"], dtype=object),
        l_svpt=np.array(["50", "50"], dtype=object),
        l_1stWon=np.array(["20", "20"], dtype=object),
        l_2ndWon=np.array(["8", "8"], dtype=object),
    )
    cols.update(overrides)
    return table.build(type(rows)(cols), FILTER).columns


def test_elo_rd_and_serve_rates_by_hand():
    t = one_match()
    ln = math.log(10) / 400
    assert t["elo_all_logit"][0] == 0.0
    assert t["elo_all_logit"][1] == pytest.approx((1516 - 1484) * ln)
    assert t["elo_tour_logit"][1] == pytest.approx((1516 - 1484) * ln)
    assert t["elo_surface_logit"][1] == pytest.approx((1516 - 1484) * ln)
    # Glicko-1 RD after one result from 350 each, two days earlier (inflation capped at 350).
    q = math.log(10) / 400
    g = 1 / math.sqrt(1 + 3 * q * q * 350 * 350 / math.pi**2)
    rd = 1 / math.sqrt(1 / 350**2 + q * q * g * g * 0.25)
    rd_now = min(350.0, math.sqrt(rd * rd + table.RD_C2 * 2))
    assert t["rd_mean"][1] == pytest.approx(rd_now)
    # Serve shares: decayed counts plus 50 points at the pooled average 68/110.
    f = 2.0 ** (-2 / 180)
    avg = 68 / 110
    sa = (40 * f + 50 * avg) / (60 * f + 50)
    sb = (28 * f + 50 * avg) / (50 * f + 50)
    assert t["serve_rate_diff"][1] == pytest.approx(sa - sb)
    ra = (22 * f + 50 * (1 - avg)) / (50 * f + 50)
    rb = (20 * f + 50 * (1 - avg)) / (60 * f + 50)
    assert t["return_rate_diff"][1] == pytest.approx(ra - rb)
    # Head-to-head share with its one-match prior; form from one win.
    assert t["h2h_share_c"][1] == pytest.approx((1 + 0.5) / 2 - 0.5)
    assert t["form_win5_diff"][1] == 1.0
    assert t["act_n7_diff"][1] == 0.0
    assert t["a_won"].tolist() == [1, 1]


def test_walkover_updates_no_rating():
    t = one_match(score=np.array(["W/O", "6-4 6-4"], dtype=object))
    assert t["elo_all_logit"][1] == 0.0
    assert t["act_wo90_diff"][1] == -1.0


def numeric_by_row(built: table.Table) -> dict[str, bytes]:
    matrix, _ = built.numeric()
    matrix = np.where(np.isnan(matrix), np.nan, matrix)
    return {r: matrix[i].tobytes() for i, r in enumerate(built.columns["row_id"])}


@pytest.fixture(scope="module")
def base():
    rows = synthetic_rows()
    return rows, table.build(rows, FILTER)


def test_own_row_mutation(base):
    rows, built = base
    day = rows["day"]
    d0 = int(np.median(day))
    window = (day >= d0) & (day <= d0 + 1)
    assert window.sum() >= 5
    mutated = table.build(swap_outcome(rows, window), FILTER)
    a, b = numeric_by_row(built), numeric_by_row(mutated)
    own = set(rows["row_id"][window])
    assert all(a[r] == b[r] for r in own)
    later = [r for r in rows["row_id"][day >= d0 + 2] if a[r] != b[r]]
    assert later, "the mutation must reach later rows"


@pytest.mark.parametrize("quantile", [0.3, 0.7])
def test_future_mutation_and_deletion(base, quantile):
    rows, built = base
    day = rows["day"]
    cut = int(np.quantile(day, quantile))
    a = numeric_by_row(built)
    mutated = numeric_by_row(table.build(swap_outcome(rows, day >= cut), FILTER))
    checked = rows["row_id"][day - 2 < cut]
    assert len(checked) > 100
    assert all(a[r] == mutated[r] for r in checked)
    assert any(a[r] != mutated[r] for r in rows["row_id"][day >= cut + 2])
    deleted = numeric_by_row(table.build(rows.subset(day <= cut), FILTER))
    assert set(deleted) == set(rows["row_id"][day <= cut])
    assert all(a[r] == deleted[r] for r in deleted)


def test_orientation_swap(base):
    rows, built = base
    rng = np.random.default_rng(4)
    swapped = rng.random(len(rows)) < 0.25
    flipped = rows.replace(
        player_a=np.where(swapped, rows["player_b"], rows["player_a"]),
        player_b=np.where(swapped, rows["player_a"], rows["player_b"]),
    )
    other = table.build(flipped, FILTER)
    index = {r: i for i, r in enumerate(other.columns["row_id"])}
    order = np.array([index[r] for r in built.columns["row_id"]])
    mask = np.isin(built.columns["row_id"], rows["row_id"][swapped])
    for name in built.groups["signed"]:
        x, y = built.columns[name][mask], other.columns[name][order][mask]
        assert np.array_equal(np.isnan(x), np.isnan(y)), name
        assert np.allclose(x, -y, rtol=0, atol=1e-12, equal_nan=True), name
    for name in built.groups["context"]:
        x, y = built.columns[name], other.columns[name][order]
        assert np.array_equal(x.astype(str), y.astype(str)), name
    assert np.array_equal(built.columns["a_won"][mask], 1 - other.columns["a_won"][order][mask])
    share = built.columns["a_games_share"][mask] + other.columns["a_games_share"][order][mask]
    assert np.allclose(share[~np.isnan(share)], 1.0)
    a, b = numeric_by_row(built), numeric_by_row(other)
    assert all(a[r] == b[r] for r in rows["row_id"][~swapped])


def test_csv_and_matrix_round_trip(base):
    _, built = base
    text = table.csv_text(built)
    header = text.split("\n", 1)[0].split(",")
    assert header == list(built.columns)
    arrays = table.matrix_arrays(text, built.groups)
    signed = np.column_stack([built.columns[c] for c in built.groups["signed"]])
    # The matrix holds the file's 12-significant-digit values.
    assert np.allclose(arrays["signed"], signed, rtol=1e-11, atol=0, equal_nan=True)
    assert arrays["context"].shape[1] == len(arrays["context_cols"])
    assert list(arrays["target_cols"]) == list(table.MATRIX_TARGETS)
