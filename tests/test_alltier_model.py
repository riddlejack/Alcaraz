"""The all-tier model: the previous run's memberships, past-only selection and slope
against the pipeline's own functions, the windows and the symmetric fit."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from tennislab.alltier import model
from tennislab.models import pipeline

LABEL_FIELDS = (
    "match_id", "calendar_year", "source_season", "match_date", "identity_tier",
    "primary_target", "a_won",
)  # fmt: skip


def write_csv(path: Path, header, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def previous_run(tmp_path: Path, years=range(2014, 2019), per_year=40, seed=2) -> model.PreviousRun:
    """A run root with labels, selected/raw forecasts and recorded selection keys."""
    rng = np.random.default_rng(seed)
    root = tmp_path / "run"
    labels, by_year = [], {}
    for year in years:
        keys = []
        for i in range(per_year):
            match_id = f"{year}-{i:03d}"
            month, day = (12, 31) if i == 0 else (1 + i % 12, 1 + i % 28)
            kind = "provisional" if i == 1 else "primary"
            season = str(year - 1) if i == 2 else str(year)
            labels.append(
                (match_id, str(year), season, f"{year}-{month:02d}-{day:02d}", kind,
                 "1" if kind == "primary" else "0", str(int(rng.random() < 0.5)))
            )  # fmt: skip
            keys.append((str(year), match_id))
        by_year[year] = sorted(keys)
        rows = [(*k, repr(float(rng.uniform(0.05, 0.95)))) for k in by_year[year]]
        if year >= 2017:
            write_csv(
                root / f"pipeline/selected/{year}/hgb/full_tier_entry.csv",
                ("season", "match_id", "p_a_wins"),
                rows,
            )
        write_csv(
            root / f"pipeline/raw/{year}/hgb/full_tier_entry/hgb_leaf07_depth3.csv",
            ("season", "match_id", "p_a_wins"),
            rows,
        )
    write_csv(root / "features/labels.csv", LABEL_FIELDS, labels)
    return model.PreviousRun(root, "hgb", "full_tier_entry")


def test_targets_and_selection_membership(tmp_path):
    run = previous_run(tmp_path)
    targets = run.targets(2016)
    # The provisional row and the row of another source season are not targets.
    assert len(targets) == 38 and ("2016", "2016-001") not in targets
    assert ("2016", "2016-002") not in targets and targets == tuple(sorted(targets))
    selection = run.selection(2017, 3)
    assert sorted(selection) == [2014, 2015, 2016]
    # Dec 31 of the last selection season is past the Dec 30 cutoff.
    assert ("2016", "2016-000") not in selection[2016]
    assert ("2015", "2015-000") in selection[2015]
    recorded = tmp_path / "run/pipeline/selection/2017/selection_keys.csv"
    pipeline.write_selection_keys(recorded, [k for v in selection.values() for k in v])
    assert run.selection(2017, 3) == selection
    pipeline.write_selection_keys(recorded, [k for v in selection.values() for k in v][1:])
    with pytest.raises(model.AllTierModelError):
        run.selection(2017, 3)


def settings(candidates=("small", "large")) -> model.ModelSettings:
    return model.ModelSettings.from_mapping(
        {
            "windows": [2, 3],
            "training_tiers": ["tour", "qualifying", "challenger"],
            "base_params": {"max_iter": 5, "random_state": 1},
            "candidates": [{"id": c, "params": {}} for c in candidates],
            "selection_years_back": 3,
        }
    )


def test_selection_and_slope_equal_the_pipeline(tmp_path):
    run = previous_run(tmp_path)
    rng = np.random.default_rng(8)
    raw = {}
    for candidate in ("small", "large"):
        raw[candidate] = {}
        for year in range(2014, 2018):
            p = rng.uniform(0.02, 0.98, len(run.targets(year)))
            p[rng.random(len(p)) < 0.1] = np.nan  # targets without a table row
            raw[candidate][year] = p
    decision = model.select_window(raw, run, 2017, settings())
    membership = run.selection(2017, 3)
    trials = {}
    for candidate in ("small", "large"):
        ps, ys = {}, {}
        for year, keys in membership.items():
            position = {k: i for i, k in enumerate(run.targets(year))}
            p = raw[candidate][year][[position[k] for k in keys]]
            y = np.array([int(run.labels()[k]["a_won"]) for k in keys])
            ps[year], ys[year] = p[np.isfinite(p)], y[np.isfinite(p)]
        trials[candidate] = pipeline.fit_nonnegative_slope(ps, ys, [2014, 2015, 2016])
    expected = pipeline.select_calibrated_candidate(trials, ["small", "large"])
    assert decision["candidate"] == expected["selected_candidate_id"]
    assert decision["slope"] == expected["selected_slope"]
    assert sum(decision["selection_rows_without_forecast"].values()) > 0
    calibrated = model.apply_slope(raw[decision["candidate"]][2017], decision["slope"])
    finite = np.isfinite(raw[decision["candidate"]][2017])
    assert np.array_equal(np.isfinite(calibrated), finite)
    assert np.array_equal(
        calibrated[finite],
        pipeline.apply_slope(raw[decision["candidate"]][2017][finite], decision["slope"]),
    )


def test_settings_and_raw_years():
    s = settings()
    assert s.raw_years([2017, 2018]) == [2014, 2015, 2016, 2017, 2018]
    with pytest.raises(model.AllTierModelError):
        settings(candidates=("small", "small"))


def table_npz(path: Path, n=400, seed=5) -> model.TableView:
    rng = np.random.default_rng(seed)
    dates = np.array([f"{2010 + i // 100}-{1 + i % 12:02d}-{1 + i % 28:02d}" for i in range(n)])
    dates[5] = "2012-12-31"
    tiers = np.array(["tour", "qualifying", "challenger", "futures"])[rng.integers(0, 4, n)]
    targets = np.column_stack(
        [rng.integers(0, 2, n).astype(float), np.full(n, np.nan), np.full(n, np.nan),
         (rng.random(n) < 0.9).astype(float), np.zeros(n), np.zeros(n), np.zeros(n)]
    )  # fmt: skip
    targets[7, 0] = np.nan
    np.savez_compressed(
        path,
        signed=rng.normal(size=(n, 4)),
        context=rng.normal(size=(n, 2)),
        targets=targets,
        target_cols=np.array(
            [
                "a_won",
                "a_points_share",
                "a_games_share",
                "is_completed",
                "is_retired",
                "is_walkover",
                "has_serve_stats",
            ]
        ),  # fmt: skip
        tier=tiers,
        date=dates,
        lab_match_id=np.array([f"m{i}" if i % 3 else "" for i in range(n)]),
    )
    return model.TableView(path)


def test_window_rows_respect_dates_tiers_and_status(tmp_path):
    view = table_npz(tmp_path / "t.npz")
    rows = view.window_rows(2013, 2, ("tour", "qualifying", "challenger"))
    dates = view.date[rows]
    assert dates.min() >= np.datetime64("2011-01-01")
    assert dates.max() <= np.datetime64("2012-12-30")
    assert 5 not in rows and 7 not in rows
    assert not np.isin(view.tier[rows], ["futures"]).any()
    assert view.trainable[rows].all()
    assert view.rows_of([("2012", "m4"), ("2012", "m3"), ("2012", "nope")]).tolist() == [4, -1, -1]


def test_symmetric_fit_is_swap_symmetric():
    rng = np.random.default_rng(1)
    signed, context = rng.normal(size=(300, 3)), rng.normal(size=(300, 2))
    y = (signed[:, 0] + 0.3 * rng.normal(size=300) > 0).astype(float)
    params = {"max_iter": 20, "random_state": 3}
    test_s, test_c = rng.normal(size=(50, 3)), rng.normal(size=(50, 2))
    p = model.fit_symmetric(signed, context, y, np.ones(300), test_s, test_c, params)
    q = model.fit_symmetric(signed, context, y, np.ones(300), -test_s, test_c, params)
    assert np.allclose(p + q, 1.0, atol=1e-15)


def test_forecast_files_round_trip(tmp_path):
    keys = [("2020", "a"), ("2020", "b"), ("2020", "c")]
    values = np.array([0.1 + 1e-17, np.nan, 2 / 3])
    model.write_forecasts(tmp_path / "f.csv", keys, values)
    back = model.read_forecasts(tmp_path / "f.csv", keys)
    assert back[0] == values[0] and np.isnan(back[1]) and back[2] == values[2]
    with pytest.raises(model.AllTierModelError):
        model.read_forecasts(tmp_path / "f.csv", keys[:1])
