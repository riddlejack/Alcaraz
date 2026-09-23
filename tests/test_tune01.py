"""TUNE01: the per-bundle HGB menu and the bagged, temporally early-stopped candidates.

The contract is ``configs/menus/tune01_hgb_menu.json`` (byte-identical to the archive's
``references/TUNE01/menu.json``) and analysis_spec §2 of the TUNE01 registration: two
anchors fitted exactly as today, grid candidates early-stopped on the window's last year
with a patience rule, refitted on the whole window at the best iteration and bagged as
five 80% row subsamples averaged in probability, the same subsamples for every
candidate.  Everything here runs on synthetic rows; nothing reads a real outcome.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from tennislab.chain import access
from tennislab.chain.common import ChainError
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache
from tennislab.models import numerical as num
from tennislab.models import pipeline as runner

MENU = Path("configs", "menus", "tune01_hgb_menu.json")
TUNE01_CHAIN = Path("configs", "chains", "atp_tune01_2017_2024.json")
ARMS01_CHAIN = Path("configs", "chains", "atp_arms01_attempt002_2017_2024.json")
SIGNED = tuple(f"s{index}" for index in range(6))
CONTEXT = ("c0", "c1")
TUNING = {
    "kind": num.TUNING_KIND,
    "menu_sha256": "0" * 64,
    "max_iter_cap": 60,
    "patience": 5,
    "tol": 1e-7,
    "members": 5,
    "row_subsample_fraction": 0.8,
    "base_seed": 71101,
}


@pytest.fixture(autouse=True)
def _single_thread_and_default_state() -> Iterator[None]:
    with threadpool_limits(1):
        yield
    runner.configure_identity()
    runner.configure_years(runner.DEFAULT_YEAR_PLAN)
    runner.configure_cohort()
    runner.configure_bundles()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grid_config(**overrides: Any) -> dict[str, Any]:
    params = {
        **runner.HGB_GRID_FIXED,
        "learning_rate": 0.1,
        "max_leaf_nodes": 7,
        "min_samples_leaf": 40,
        "l2_regularization": 10.0,
        "max_iter": TUNING["max_iter_cap"],
    }
    params.update(overrides)
    return {
        "config_id": "hgb__full_tier_entry__tune_test",
        "family": "hist_gradient_boosting",
        "signed_numeric_columns": list(SIGNED),
        "context_columns": list(CONTEXT),
        "estimator_params": params,
        "tuning": dict(TUNING),
    }


def synthetic_rows(seasons: range, per_season: int, seed: int) -> list[dict[str, str]]:
    rng = np.random.default_rng(seed)
    rows = []
    for season in seasons:
        for index in range(per_season):
            row = {"season": str(season), "match_id": f"{season}-{index:04d}"}
            for column in SIGNED:
                row[column] = repr(float(rng.normal()))
            for column in CONTEXT:
                row[column] = repr(float(rng.integers(0, 2)))
            rows.append(row)
    return rows


def synthetic_window(
    per_season: int = 160, seed: int = 20260923
) -> tuple[num.FeatureTable, num.LabelTable]:
    table = num.FeatureTable.from_rows(
        synthetic_rows(range(2011, 2016), per_season, seed),
        ("season", "match_id", *SIGNED, *CONTEXT),
    )
    rng = np.random.default_rng(seed + 1)
    labels = {}
    for key, row in zip(table.keys, table.rows, strict=True):
        strength = float(row["s0"]) + 0.5 * float(row["s1"]) * float(row["c0"])
        labels[key] = int(rng.random() < 1.0 / (1.0 + np.exp(-strength)))
    return table, num.LabelTable.from_values(labels)


def stopping_sets(
    table: num.FeatureTable,
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    train = tuple(key for key in table.keys if key[0] <= "2013")
    validation = tuple(key for key in table.keys if key[0] == "2015")
    return train, validation


def bagged_inputs(
    config: dict[str, Any], table: num.FeatureTable, labels: num.LabelTable
) -> num.BaggedTreeInputs:
    train, validation = stopping_sets(table)
    return num.prepare_bagged_tree_inputs(
        config,
        table,
        labels,
        stopping_train_keys=train,
        stopping_validation_keys=validation,
        raw_year=2016,
    )


# ------------------------------------------------------------------ the menu file


def test_the_menu_is_110_candidates_with_the_anchors_first(request: pytest.FixtureRequest) -> None:
    root = Path(request.config.rootpath)
    menu = runner.load_hgb_menu(root / MENU, MENU.as_posix())
    assert menu.candidate_ids[:2] == ("hgb_leaf07_depth3", "hgb_leaf15_depth4")
    assert len(menu.candidate_ids) == 110 and len(set(menu.candidate_ids)) == 110
    assert len(menu.grid_params) == 108
    assert menu.candidate_ids[2] == "tune_lr100_leaf07_min160_reg30"
    assert menu.candidate_ids[-1] == "tune_lr020_leaf31_min040_reg01"
    assert menu.sha256 == sha256(root / MENU)
    assert menu.tuning == {
        **TUNING,
        "max_iter_cap": 1000,
        "patience": 20,
        "menu_sha256": menu.sha256,
    }
    axes = {
        (p["learning_rate"], p["max_leaf_nodes"], p["min_samples_leaf"], p["l2_regularization"])
        for p in menu.grid_params.values()
    }
    assert len(axes) == 3 * 4 * 3 * 3


def test_the_tune01_chain_binds_the_product_menu_bytes(request: pytest.FixtureRequest) -> None:
    root = Path(request.config.rootpath)
    tune = json.loads((root / TUNE01_CHAIN).read_text(encoding="utf-8"))["chain"]
    arms = json.loads((root / ARMS01_CHAIN).read_text(encoding="utf-8"))["chain"]
    assert tune["hgb_menus"]["full_tier_entry"]["sha256"] == sha256(root / MENU)
    assert tune["inputs"] == arms["inputs"]
    assert tune["experiment_id"] == "TUNE01"
    assert tune["bundles"] == ["base", "full_tier", "full_tier_entry"]
    assert tune["entry_any_qualifier_counts_ll"] is False


def edited_menu(tmp_path: Path, request: pytest.FixtureRequest, edit: Any) -> Path:
    document = json.loads((Path(request.config.rootpath) / MENU).read_text(encoding="utf-8"))
    edit(document)
    path = tmp_path / "menu.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(
            lambda d: d["anchors"][0]["estimator_params"].update(max_iter=300), id="anchor"
        ),
        pytest.param(lambda d: d["grid"].pop(), id="incomplete-grid"),
        pytest.param(lambda d: d["grid"][0].update(candidate_id="tune_other"), id="id"),
        pytest.param(lambda d: d["grid"][0]["estimator_params"].update(max_bins=63), id="fixed"),
        pytest.param(lambda d: d["bagging"].update(rng="numpy.random.default_rng(1)"), id="rng"),
        pytest.param(lambda d: d["early_stopping"].update(patience=1000), id="patience"),
    ],
)
def test_a_menu_that_departs_from_the_contract_is_refused(
    tmp_path: Path, request: pytest.FixtureRequest, edit: Any
) -> None:
    path = edited_menu(tmp_path, request, edit)
    with pytest.raises(ChainError):
        runner.load_hgb_menu(path, "menu.json")


def test_a_bound_menu_enlarges_only_its_bundle_and_is_recorded_in_the_settings(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(request.config.rootpath)
    (tmp_path / "menus").mkdir()
    (tmp_path / "menus" / "menu.json").write_bytes((root / MENU).read_bytes())
    monkeypatch.setenv(WORKSPACE_ENVIRONMENT_VARIABLE, str(tmp_path))
    reset_workspace_cache()
    try:
        runner.configure_bundles(["base", "full_tier", "full_tier_entry"], ["hgb"])
        before = runner.settings_document()
        assert "hgb_menus" not in before and runner.expected_fit_attempts() == 2 * 3 * 11
        binding = {"path": "menus/menu.json", "sha256": sha256(root / MENU)}
        runner.configure_hgb_menus({"full_tier_entry": binding})
        assert runner.settings_document() == {**before, "hgb_menus": {"full_tier_entry": binding}}
        assert runner.candidate_ids("hgb", "full_tier") == runner.candidate_ids("hgb")
        assert len(runner.candidate_ids("hgb", "full_tier_entry")) == 110
        assert runner.expected_fit_attempts() == (2 + 2 + 110) * 11
        with pytest.raises(ChainError):
            runner.configure_hgb_menus({"full": binding})
        with pytest.raises(ChainError):
            runner.configure_hgb_menus({"full_tier_entry": {**binding, "sha256": "1" * 64}})
        # Reinstalling the bundles drops the menu, so no stale menu reaches another run.
        runner.configure_bundles(["base", "full_tier", "full_tier_entry"], ["hgb"])
        assert runner.settings_document() == before
    finally:
        reset_workspace_cache()


def test_anchor_configs_under_a_menu_are_todays_configs(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The anchors of the enlarged menu produce today's numerical config byte-for-byte, so
    their fit identities, fits and forecasts are the default menu's."""
    from tests.test_models_pipeline import entry_contract

    root = Path(request.config.rootpath)
    (tmp_path / "menu.json").write_bytes((root / MENU).read_bytes())
    monkeypatch.setenv(WORKSPACE_ENVIRONMENT_VARIABLE, str(tmp_path))
    reset_workspace_cache()
    try:
        runner.configure_bundles(["base", "full_tier", "full_tier_entry"], ["hgb"])
        contract = entry_contract()
        today = {
            q: num.canonical_json(runner.numerical_config(contract, "hgb", "full_tier_entry", q))
            for q, _, _ in runner.HGB_CANDIDATES
        }
        runner.configure_hgb_menus(
            {"full_tier_entry": {"path": "menu.json", "sha256": sha256(root / MENU)}}
        )
        for q, encoded in today.items():
            config = runner.numerical_config(contract, "hgb", "full_tier_entry", q)
            assert num.canonical_json(config) == encoded
        grid = runner.numerical_config(
            contract, "hgb", "full_tier_entry", "tune_lr020_leaf31_min040_reg01"
        )
        assert grid["tuning"]["menu_sha256"] == sha256(root / MENU)
        assert grid["estimator_params"]["max_iter"] == 1000
        assert grid["estimator_params"]["max_depth"] is None
        assert (
            grid["signed_numeric_columns"]
            == json.loads(today["hgb_leaf07_depth3"])["signed_numeric_columns"]
        )
    finally:
        reset_workspace_cache()


# ------------------------------------------------------------------ the patience rule


def test_the_patience_rule_fires_after_patience_iterations_without_improvement() -> None:
    curve = [1.0 - 0.01 * k for k in range(10)] + [0.95] * 30
    decision = num.early_stopping_decision(curve, patience=5, tol=1e-7)
    # Best 0.91 at k = 10; k = 15 is the first k whose last five do not improve on it.
    assert decision == {"k_star": 10, "k_stop": 15, "stop_status": "patience"}


def test_the_rule_keeps_the_best_iteration_not_the_stop_point_and_ties_go_first() -> None:
    curve = [0.9, 0.8, 0.7, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
    # k = 6: min L(4..6) = 0.7 is not above min L(1..3) = 0.7, so the rule waits (a
    # repeat of the best is not a failure to improve); k = 7: 0.75 > 0.7 fires.  The best
    # value is tied at k = 3 and 4; the first wins.
    assert num.early_stopping_decision(curve, patience=3, tol=0.0) == {
        "k_star": 3,
        "k_stop": 7,
        "stop_status": "patience",
    }


def test_an_improvement_within_tol_does_not_reset_patience() -> None:
    curve = [1.0, 0.5] + [0.5 - 1e-9 * k for k in range(1, 10)]
    strict = num.early_stopping_decision(curve, patience=3, tol=0.0)
    tolerant = num.early_stopping_decision(curve, patience=3, tol=1e-7)
    assert strict["stop_status"] == "cap" and strict["k_star"] == len(curve)
    assert tolerant == {"k_star": 5, "k_stop": 5, "stop_status": "patience"}


def test_a_curve_that_keeps_improving_stops_at_the_cap() -> None:
    curve = [1.0 / k for k in range(1, 101)]
    assert num.early_stopping_decision(curve, patience=20, tol=1e-7) == {
        "k_star": 100,
        "k_stop": None,
        "stop_status": "cap",
    }


# ------------------------------------------------------------------ subsamples and rows


def test_subsamples_are_deterministic_shared_by_candidates_and_equal_the_augmentation() -> None:
    table, labels = synthetic_window()
    first = bagged_inputs(grid_config(), table, labels)
    again = bagged_inputs(grid_config(learning_rate=0.02, max_leaf_nodes=31), table, labels)
    assert first.receipt == again.receipt
    for key, positions in first.subsamples.items():
        np.testing.assert_array_equal(positions, again.subsamples[key])
    train, validation = stopping_sets(table)
    keys = table.keys
    for (role, member), positions in first.subsamples.items():
        expected_size = int(0.8 * (len(train) if role == 0 else len(keys)))
        assert len(positions) == expected_size == len(set(positions.tolist()))
        drawn = [keys[index] for index in positions]
        if role == 0:
            assert set(drawn) <= set(train)
        generator = np.random.Generator(
            np.random.PCG64(np.random.SeedSequence([71101, 2016, role, member]))
        )
        pool = [keys.index(key) for key in train] if role == 0 else list(range(len(keys)))
        chosen = np.sort(generator.choice(len(pool), size=expected_size, replace=False))
        assert [pool[index] for index in chosen] == positions.tolist()
        # A subsample's rows are exactly the augmentation of the subsampled matches.
        subset = table.subset(drawn)
        matrix, target, weight = num._tree_augmentation(
            subset.matrix(SIGNED),
            subset.matrix(CONTEXT),
            labels.subset(drawn).align_exact(subset.keys),
        )
        rows = first.rows(role, member)
        np.testing.assert_array_equal(first.fit_matrix[rows], matrix)
        np.testing.assert_array_equal(first.fit_labels[rows], target)
        np.testing.assert_array_equal(first.fit_weights[rows], weight)
    assert first.receipt["stopping_validation_keys"] == len(validation)
    assert first.receipt["keys_in_neither_stopping_set"] == len(keys) - len(train) - len(validation)


def test_overlapping_or_outside_stopping_keys_are_refused() -> None:
    table, labels = synthetic_window(per_season=40)
    train, validation = stopping_sets(table)
    with pytest.raises(ChainError):
        num.prepare_bagged_tree_inputs(
            grid_config(), table, labels,
            stopping_train_keys=train + validation[:1],
            stopping_validation_keys=validation,
            raw_year=2016,
        )  # fmt: skip
    with pytest.raises(ChainError):
        num.prepare_bagged_tree_inputs(
            grid_config(), table, labels,
            stopping_train_keys=train,
            stopping_validation_keys=(*validation, ("2016", "later")),
            raw_year=2016,
        )  # fmt: skip


def test_the_stopping_partition_is_the_last_window_year_and_never_reaches_the_raw_year() -> None:
    metadata = {}
    for day in (
        "2014-01-01", "2014-12-30", "2014-12-31", "2015-01-01", "2015-06-01",
        "2015-12-30", "2015-12-31", "2016-01-02", "2011-03-01", "2010-12-30",
    ):  # fmt: skip
        year = day[:4]
        metadata[(year, f"m{day}")] = {
            "calendar_year": year,
            "source_season": year,
            "match_date": day,
            "primary_target": "1",
            "identity_tier": "primary",
            "sr02_selected_match_present": "1",
            "dynamic_match_probability_a": "0.5",
        }
    train, validation = runner.stopping_partition(metadata, 2016)
    assert [key[1] for key in validation] == ["m2015-01-01", "m2015-06-01", "m2015-12-30"]
    assert [key[1] for key in train] == ["m2011-03-01", "m2014-01-01", "m2014-12-30"]
    window = set(runner.training_keys(metadata, 2016))
    assert window - set(train) - set(validation) == {("2014", "m2014-12-31")}


# ------------------------------------------------------------------ staged curve and refit


def test_a_fit_stopped_at_k_reproduces_the_staged_forecast_at_k() -> None:
    table, labels = synthetic_window(per_season=120)
    inputs = bagged_inputs(grid_config(), table, labels)
    rows = inputs.rows(0, 0)
    params = {k: v for k, v in grid_config()["estimator_params"].items() if k != "max_iter"}
    full = num.HistGradientBoostingClassifier(**params, max_iter=60)
    full.fit(
        inputs.fit_matrix[rows], inputs.fit_labels[rows], sample_weight=inputs.fit_weights[rows]
    )
    staged = list(full.staged_predict_proba(inputs.validation_original))
    for k in (1, 17, 60):
        short = num.HistGradientBoostingClassifier(**params, max_iter=k)
        short.fit(
            inputs.fit_matrix[rows], inputs.fit_labels[rows], sample_weight=inputs.fit_weights[rows]
        )
        assert np.array_equal(short.predict_proba(inputs.validation_original), staged[k - 1])


def test_early_stopping_picks_the_best_bagged_iteration_and_refits_at_that_count() -> None:
    table, labels = synthetic_window()
    config = grid_config()
    inputs = bagged_inputs(config, table, labels)
    attempt = num.fit_bagged_early_stopped(config, inputs)
    assert attempt.status == "complete", attempt.error
    assert attempt.tuning is not None and isinstance(attempt.fitted, num.BaggedProcedure)
    # Recompute the curve from independently fitted stopping members.
    params = {k: v for k, v in config["estimator_params"].items() if k != "max_iter"}
    members = []
    for member in range(5):
        rows = inputs.rows(0, member)
        estimator = num.HistGradientBoostingClassifier(**params, max_iter=60)
        estimator.fit(
            inputs.fit_matrix[rows], inputs.fit_labels[rows], sample_weight=inputs.fit_weights[rows]
        )
        members.append(estimator)
    y = inputs.validation_labels
    curve = []
    for k in range(60):
        total = None
        for estimator in members:
            p_original = list(estimator.staged_predict_proba(inputs.validation_original))[k][:, 1]
            p_swapped = list(estimator.staged_predict_proba(inputs.validation_swapped))[k][:, 1]
            member_p = 0.5 * (p_original + 1.0 - p_swapped)
            total = member_p if total is None else total + member_p
        mean = np.clip(total / 5, 1e-15, 1 - 1e-15)
        curve.append(float(np.mean(-np.log(np.where(y == 1.0, mean, 1.0 - mean)))))
    decision = num.early_stopping_decision(curve, patience=5, tol=1e-7)
    assert attempt.tuning["curve_sha256"] == num.sha256_json(curve)
    assert {key: attempt.tuning[key] for key in decision} == decision
    k_star = decision["k_star"]
    assert curve[k_star - 1] == min(curve[: decision["k_stop"] or 60])
    assert attempt.tuning["refit_member_n_iter"] == [k_star] * 5
    for member, procedure in enumerate(attempt.fitted.members):
        assert procedure.estimator.n_iter_ == k_star
        assert procedure.config["estimator_params"]["max_iter"] == k_star
        assert "tuning" not in procedure.config
        rows = inputs.rows(1, member)
        refit = num.HistGradientBoostingClassifier(**params, max_iter=k_star)
        refit.fit(
            inputs.fit_matrix[rows], inputs.fit_labels[rows], sample_weight=inputs.fit_weights[rows]
        )
        assert np.array_equal(
            refit.predict_proba(inputs.validation_original),
            procedure.estimator.predict_proba(inputs.validation_original),
        )
    # No curve value leaves the adapter: the receipt carries its hash only.
    assert not any(
        isinstance(value, list) and len(value) == 60 for value in attempt.tuning.values()
    )


def test_the_bagged_forecast_is_the_member_mean_and_exactly_swap_symmetric() -> None:
    table, labels = synthetic_window()
    config = grid_config()
    attempt = num.fit_bagged_early_stopped(config, bagged_inputs(config, table, labels))
    assert isinstance(attempt.fitted, num.BaggedProcedure)
    header = ("season", "match_id", *SIGNED, *CONTEXT)
    rows = synthetic_rows(range(2016, 2017), 300, seed=7)
    mirrored = [{**row, **{c: repr(-float(row[c])) for c in SIGNED}} for row in rows]
    original = attempt.fitted.predict(num.FeatureTable.from_rows(rows, header))
    swapped = attempt.fitted.predict(num.FeatureTable.from_rows(mirrored, header))
    assert np.max(np.abs(original.probabilities + swapped.probabilities - 1.0)) <= 1e-12
    members = [
        member.predict(num.FeatureTable.from_rows(rows, header)).probabilities
        for member in attempt.fitted.members
    ]
    total = members[0].copy()
    for probabilities in members[1:]:
        total = total + probabilities
    assert np.array_equal(original.probabilities, total / 5)
    assert np.std(original.probabilities) > 0.0


def test_future_labels_cannot_move_a_bagged_forecast() -> None:
    """Raw year R's fit sees the window's labels only: flipping every label dated at or
    after the window end (the raw year's own outcomes included) changes no forecast."""
    header = ("season", "match_id", *SIGNED, *CONTEXT)
    table = num.FeatureTable.from_rows(synthetic_rows(range(2011, 2017), 160, 5), header)
    rng = np.random.default_rng(3)
    truth = {key: int(rng.random() < 0.5 + 0.1 * float(row["s0"])) for key, row in zip(table.keys, table.rows, strict=True)}  # fmt: skip
    planted = {key: (1 - value if key[0] >= "2016" else value) for key, value in truth.items()}
    window = tuple(key for key in table.keys if key[0] <= "2015")
    prediction = table.subset(key for key in table.keys if key[0] == "2016")
    forecasts = []
    for values in (truth, planted):
        labels = num.LabelTable.from_values(values).subset(window)
        config = grid_config()
        inputs = bagged_inputs(config, table.subset(window), labels)
        attempt = num.fit_bagged_early_stopped(config, inputs)
        assert attempt.fitted is not None
        forecasts.append(attempt.fitted.predict(prediction).probabilities)
    assert np.array_equal(forecasts[0], forecasts[1])


# ------------------------------------------------------------------ cache and workers


def test_a_bagged_fit_is_cached_with_its_receipt_and_no_stopping_model(tmp_path: Path) -> None:
    table, labels = synthetic_window(per_season=80)
    config = grid_config()
    inputs = bagged_inputs(config, table, labels)
    identity = {
        **num.fit_identity(config, "2015-12-30", table, labels, "0" * 64),
        "bagging": inputs.receipt,
    }
    cache = num.FileFitCache(tmp_path / "fits")
    shared = {
        "cache_root": str(tmp_path / "fits"),
        "training_keys": table.keys,
        "prediction_features": table,
        "inputs": {"full_tier_entry": inputs},
    }
    task = {"block": "full_tier_entry", "config": config, "identity": identity, "prediction_path": str(tmp_path / "a.csv")}  # fmt: skip
    first = num.execute_bagged_task(task, shared)
    second = num.execute_bagged_task({**task, "prediction_path": str(tmp_path / "b.csv")}, shared)
    assert first["status"] == second["status"] == "complete"
    assert first["fit_cache_reused"] is False and second["fit_cache_reused"] is True
    assert first["tuning"] == second["tuning"]
    assert (tmp_path / "a.csv").read_bytes() == (tmp_path / "b.csv").read_bytes()
    (directory,) = (tmp_path / "fits").iterdir()
    manifest = json.loads((directory / "fit_manifest.json").read_text(encoding="utf-8"))
    assert manifest["tuning"]["k_star"] == first["tuning"]["k_star"]
    assert manifest["bag_members"] == 5 and "estimator_get_params" not in manifest
    assert sorted(path.name for path in directory.iterdir()) == [
        "fit_manifest.json",
        "model.joblib",
        "training_keys.csv",
    ]
    reloaded, _ = cache.fit_or_load(identity, table.keys, lambda: pytest.fail("refit"))
    assert reloaded.tuning == first["tuning"]


def test_a_worker_process_gives_the_in_process_bytes_and_returns_its_file_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    table, labels = synthetic_window(per_season=80)
    config = grid_config()
    inputs = bagged_inputs(config, table, labels)
    identity = {
        **num.fit_identity(config, "2015-12-30", table, labels, "0" * 64),
        "bagging": inputs.receipt,
    }
    tasks = {}
    for name in ("inline", "worker"):
        root = tmp_path / name
        shared = {
            "cache_root": str(root / "fits"),
            "training_keys": table.keys,
            "prediction_features": table,
            "inputs": {"full_tier_entry": inputs},
        }
        tasks[name] = (shared, {"block": "full_tier_entry", "config": config, "identity": identity, "prediction_path": str(root / "p.csv")})  # fmt: skip
    inline = num.execute_bagged_task(tasks["inline"][1], tasks["inline"][0])
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=num.init_bagged_worker,
        initargs=(tasks["worker"][0],),
    ) as pool:
        worker = pool.submit(num.run_bagged_task, tasks["worker"][1]).result()
    records = worker.pop("access")
    assert set(records) == {"opens", "receipts"}
    assert worker["tuning"] == inline["tuning"]
    assert worker["prediction_sha256"] == inline["prediction_sha256"]
    assert (tmp_path / "worker" / "p.csv").read_bytes() == (
        tmp_path / "inline" / "p.csv"
    ).read_bytes()


def test_drained_worker_records_are_absorbed_into_the_stage_log() -> None:
    saved = access.drain()
    try:
        access.absorb(
            {
                "opens": [["work/x.csv", "r", "tennislab.chain.common:sha256", 2]],
                "receipts": [{"accessor": "LabelHistory", "purpose": "training_fit"}],
            }
        )
        drained = access.drain()
        assert drained == {
            "opens": [["work/x.csv", "r", "tennislab.chain.common:sha256", 2]],
            "receipts": [{"accessor": "LabelHistory", "purpose": "training_fit"}],
        }
    finally:
        access.absorb(saved)


def test_the_worker_count_comes_from_the_environment_and_defaults_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(runner.WORKERS_ENVIRONMENT_VARIABLE, raising=False)
    assert runner.pipeline_workers() == 1
    monkeypatch.setenv(runner.WORKERS_ENVIRONMENT_VARIABLE, "12")
    assert runner.pipeline_workers() == 12
    for bad in ("0", "-2", "many"):
        monkeypatch.setenv(runner.WORKERS_ENVIRONMENT_VARIABLE, bad)
        with pytest.raises(ChainError):
            runner.pipeline_workers()


def test_a_selection_record_carries_the_stopped_count_and_bag_seeds_of_each_raw_year() -> None:
    table, labels = synthetic_window(per_season=60)
    config = grid_config()
    attempt = num.fit_bagged_early_stopped(config, bagged_inputs(config, table, labels))
    summary = runner._tuning_summary({"tuning": attempt.tuning})
    assert set(summary["tuning"]) == {
        "k_star",
        "k_stop",
        "stop_status",
        "curve_sha256",
        "bag_seeds",
    }
    assert summary["tuning"]["bag_seeds"] == {
        role: [[71101, 2016, index, member] for member in range(5)]
        for role, index in (("stopping", 0), ("refit", 1))
    }
    assert runner._tuning_summary({"prediction_sha256": "x"}) == {}
    # Nothing in the receipt is a score the barrier scan would flag.
    from tennislab.chain import barrier_scan

    assert list(barrier_scan.metric_paths({"tuning": attempt.tuning, **summary})) == []
