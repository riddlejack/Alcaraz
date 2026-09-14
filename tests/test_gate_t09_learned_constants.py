"""Gate T9 (Lane C2, admitted by archive R15/R17): every learned constant has a receipt
whose horizon precedes the rows it serves.

PASS CRITERION (kept from C2, evaluated on the synthetic run): inventory every raw fitted
model, candidate calibration trial, selected candidate/slope, shared-base slope, market
calibration slope and SR03 family/year slope the pipeline learned. Required receipts
cannot be absent or empty. Fit and selection horizons precede January 1 of their
application year by the D-2 lag; selection has exactly the configured past years; every
training key a fitted model consumed carries a season before its application year; a
selected or shared slope must equal a recorded candidate trial; every per-use receipt
file equals its entry in the completion inventory and nothing is orphaned. Declared
choices (candidate grids, learner parameters, Elo update rules) are design inputs, not
learned constants, and are not receipted here. This is metadata and horizon validation,
not a numerical replay of the estimators.

NEGATIVE CONTROLS (same audit function, on a scratch copy of the receipts): empty
selection / market / shared-base inventories, an application-year selection cutoff, a
missing candidate trial, a shared slope with no matching trial, a missing market receipt,
a missing raw fit manifest, a raw fit horizon inside its application year, a training
key from the application year, empty raw fits, an SR03 horizon inside its application
year and empty SR03 fits each fail.

NOT COVERED HERE: annual tier offsets (``tier_elo/tier_offsets_by_year.csv``) and the
retired 2016-12-31 offset-horizon counterfactual need the tier stages, which the base
synthetic sample does not run.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tests.gate_support import (
    PLACEHOLDERS,
    chain_document,
    finite,
    must_reject,
    read_csv,
    read_json,
    sha256,
    write_csv,
)

SR03_FAMILIES = frozenset({"dynamic", "unadjusted", "simple_unadjusted"})
LAG_DAYS = 2


def _cutoff_for(year: int) -> dt.date:
    return dt.date(year, 1, 1) - dt.timedelta(days=LAG_DAYS)


def _key(record: Mapping[str, Any]) -> tuple[int, str, str]:
    return int(record["outer_year"]), record["learner"], record["block"]


def past_selection(record: Mapping[str, Any], back: int) -> None:
    outer = int(record["outer_year"])
    years = [int(y) for y in record["selection_years"]]
    assert years == list(range(outer - back, outer)), f"invalid selection window: {outer}/{years}"
    cutoff = dt.date.fromisoformat(record["selection_cutoff_inclusive"])
    assert cutoff <= _cutoff_for(outer), f"nonpast selection cutoff: {outer}/{cutoff}"
    assert record.get("outer_labels_used") is False, "outer labels used in selection"
    assert record.get("selection_membership_sha256") not in PLACEHOLDERS, (
        "missing selection membership"
    )
    assert record.get("criterion_sha256") not in PLACEHOLDERS, "missing selection commitment"


def audit_receipts(run_root: Path, chain: Mapping[str, Any]) -> dict[str, Any]:
    plan, config = chain["year_plan"], chain["chain"]
    targets = {int(y) for y in plan["target_years"]}
    back = int(plan["calibration_years_back"])
    raw_years = sorted({year - offset for year in targets for offset in range(back + 1)})
    blocks, learners = config["bundles"], config["learners"]
    assert blocks and learners, "missing declared model family inventory"
    predictor = read_json(run_root.parent / "predictor_config" / "config.json")["settings"]
    menus = {learner: set(predictor[f"{learner}_candidates"]) for learner in learners}
    selection = read_json(run_root / "pipeline" / "selection_complete.json")
    raw = read_json(run_root / "pipeline" / "raw_complete.json")
    assert selection["status"] == "complete" and raw["status"] == "complete"
    assert selection["outer_target_outcomes_scored"] is False
    assert raw["target_outcomes_scored"] is False
    inventory: list[dict[str, Any]] = []

    records = selection.get("selection_records", [])
    expected = {
        (year, learner, block) for year in targets for learner in learners for block in blocks
    }
    assert len(records) == len(expected) and {_key(r) for r in records} == expected, (
        "incomplete selection receipt inventory"
    )
    by_key: dict[tuple[int, str, str], Mapping[str, Any]] = {}
    for record in records:
        past_selection(record, back)
        assert record["status"] == "complete"
        trials = record.get("candidate_trials", {})
        assert set(trials) == menus[record["learner"]], "incomplete candidate calibration receipts"
        for candidate, trial in trials.items():
            assert (
                trial["status"] == "complete" and finite(trial.get("slope")) and trial["slope"] >= 0
            )
            assert set(map(int, trial["annual"])) == set(record["selection_years"]), (
                "candidate horizon/membership years mismatch"
            )
            assert set(map(int, trial["prediction_sources"])) == set(record["selection_years"]), (
                "missing candidate prediction-source receipts"
            )
            inventory.append(
                {
                    "kind": "candidate_slope",
                    "key": [*_key(record), candidate],
                    "horizon": record["selection_cutoff_inclusive"],
                }
            )
        chosen = record["selected_candidate_id"]
        assert chosen in trials and record["selected_slope"] == trials[chosen]["slope"], (
            "selected slope lacks matching receipt"
        )
        ranked = record["selection"]["ranked"]
        assert ranked and ranked[0]["candidate_id"] == chosen, (
            "ranked order does not lead with the selection"
        )
        inventory.append(
            {
                "kind": "selected_candidate_and_slope",
                "key": _key(record),
                "horizon": record["selection_cutoff_inclusive"],
            }
        )
        by_key[_key(record)] = record

    shared = selection.get("shared_base_records", [])
    assert len(shared) == len(expected) and {_key(r) for r in shared} == expected, (
        "incomplete shared-base receipt inventory"
    )
    for record in shared:
        own = by_key[_key(record)]
        base = by_key[(int(record["outer_year"]), record["learner"], "base")]
        assert record["candidate_id"] == base["selected_candidate_id"], (
            "shared-base complexity receipt mismatch"
        )
        assert record["slope"] == own["candidate_trials"][record["candidate_id"]]["slope"], (
            "shared-base slope lacks matching candidate receipt"
        )
        assert record["outer_labels_used"] is False
        inventory.append(
            {
                "kind": "shared_base_slope",
                "key": _key(record),
                "horizon": own["selection_cutoff_inclusive"],
            }
        )

    markets = selection.get("market_records", [])
    assert len(markets) == len(targets) and {int(r["outer_year"]) for r in markets} == targets, (
        "incomplete market slope receipts"
    )
    for record in markets:
        past_selection(record, back)
        own = read_json(
            run_root / "pipeline" / "market" / str(record["outer_year"]) / "calibration.json"
        )
        assert own == record, "market receipt differs from completion inventory"
        assert record["status"] == "complete" and finite(record["slope"]) and record["slope"] >= 0
        assert record["slope"] == record["slope_fit"]["slope"], "market slope lacks fit receipt"
        assert set(map(int, record["slope_fit"]["annual"])) == set(record["selection_years"])
        inventory.append(
            {
                "kind": "market_slope",
                "key": record["outer_year"],
                "horizon": record["selection_cutoff_inclusive"],
            }
        )

    attempts = raw.get("raw_attempts", [])
    expected_raw = {
        (year, learner, block, candidate)
        for year in raw_years
        for learner in learners
        for block in blocks
        for candidate in menus[learner]
    }
    observed_raw = {(int(r["year"]), r["learner"], r["block"], r["candidate_id"]) for r in attempts}
    assert len(attempts) == len(expected_raw) and observed_raw == expected_raw, (
        "incomplete raw fit receipt inventory"
    )
    for record in attempts:
        assert (
            record["status"] == "complete" and record["outcome_labels_used_for_prediction"] is False
        )
        cache = run_root / "pipeline" / "fit_cache" / record["fit_identity_sha256"]
        receipt = cache / "fit_manifest.json"
        fit = read_json(receipt)
        assert sha256(receipt) == record["fit_manifest_sha256"], "raw fit receipt binding mismatch"
        identity = fit["fit_identity"]
        year = int(record["year"])
        assert dt.date.fromisoformat(identity["fit_cutoff"]) <= _cutoff_for(year), (
            "fit horizon violates application-year cutoff"
        )
        assert identity["training_keys_sha256"] == record["training_membership_sha256"]
        assert identity["training_rows"] == record["training_rows"] > 0
        assert fit["status"] == "complete" and fit.get("model_sha256") not in PLACEHOLDERS
        assert sha256(cache / fit["model_path"]) == fit["model_sha256"], (
            "learned model bytes differ"
        )
        keys_file = cache / fit["training_keys_path"]
        assert sha256(keys_file) == fit["training_keys_file_sha256"], "training keys bytes differ"
        _, keys = read_csv(keys_file)
        assert len(keys) == identity["training_rows"], "training key count differs from receipt"
        seasons = {int(k["season"]) for k in keys}
        assert seasons and max(seasons) < year, (
            f"training key season {max(seasons)} does not precede application year {year}"
        )
        assert min(seasons) >= max(
            int(plan["history_floor_year"]), year - int(plan["training_window_years"])
        ), "training key precedes the declared training window"
        inventory.append(
            {
                "kind": "fitted_estimator_and_transforms",
                "key": [year, record["learner"], record["block"], record["candidate_id"]],
                "horizon": identity["fit_cutoff"],
                "training_seasons": sorted(seasons),
                "learned_transform_fields": [
                    k for k in ("rms_scales", "identity_vocabulary") if fit.get(k) is not None
                ],
            }
        )

    fits = read_json(run_root / "sr03_calibration" / "fits.json")
    expected_fits = {(y, f) for y in raw_years for f in SR03_FAMILIES}
    assert (
        len(fits) == len(expected_fits)
        and {(int(r["outer_year"]), r["family"]) for r in fits} == expected_fits
    ), "incomplete SR03 fit receipts"
    for record in fits:
        year = int(record["outer_year"])
        assert record["status"] == "complete"
        assert finite(record["fit"]["market_slope"]) and record["fit"]["market_slope"] >= 0
        assert dt.date.fromisoformat(record["training_max_date"]) <= _cutoff_for(year), (
            "SR03 training horizon after cutoff"
        )
        assert dt.date.fromisoformat(record["training_min_date"]) >= dt.date(year - back, 1, 1)
        assert set(map(int, record["training_by_calendar_year"])) == set(range(year - back, year))
        assert (
            record["training_n"] > 0
            and record.get("training_membership_sha256") not in PLACEHOLDERS
        )
        inventory.append(
            {
                "kind": "SR03_family_slope",
                "key": [year, record["family"]],
                "horizon": record["training_max_date"],
            }
        )

    # Every durable per-use receipt must agree with its completion inventory; an orphan
    # or new learned receipt cannot escape by being absent from that summary.
    families = [
        ("selection", records, lambda r: f"{r['outer_year']}/{r['learner']}/{r['block']}.json"),
        ("shared_base", shared, lambda r: f"{r['outer_year']}/{r['learner']}/{r['block']}.json"),
        (
            "attempts",
            attempts,
            lambda r: f"{r['year']}/{r['learner']}/{r['block']}/{r['candidate_id']}.json",
        ),
        ("market", markets, lambda r: f"{r['outer_year']}/calibration.json"),
    ]
    for family, family_records, suffix in families:
        directory = run_root / "pipeline" / family
        expected_paths = {directory / suffix(r) for r in family_records}
        assert set(directory.rglob("*.json")) == expected_paths, (
            f"missing/orphan {family} receipt files"
        )
        for record in family_records:
            assert read_json(directory / suffix(record)) == record, (
                f"{family} receipt differs from completion inventory"
            )
    expected_manifests = {
        run_root / "pipeline" / "fit_cache" / r["fit_identity_sha256"] / "fit_manifest.json"
        for r in attempts
    }
    assert (
        set((run_root / "pipeline" / "fit_cache").glob("*/fit_manifest.json")) == expected_manifests
    ), "orphan or missing learned-model receipt"
    counts = {
        kind: sum(r["kind"] == kind for r in inventory)
        for kind in sorted({r["kind"] for r in inventory})
    }
    return {"inventory": inventory, "counts": counts}


# ------------------------------------------------------------------ clean behaviour


def test_every_learned_constant_has_a_past_receipt(sample_run: dict[str, Any]) -> None:
    chain = chain_document(sample_run)
    result = audit_receipts(sample_run["run_root"], chain)
    targets = len(chain["year_plan"]["target_years"])
    blocks = len(chain["chain"]["bundles"])
    learners = len(chain["chain"]["learners"])
    raw_years = targets + chain["year_plan"]["calibration_years_back"]
    assert result["counts"] == {
        "SR03_family_slope": raw_years * len(SR03_FAMILIES),
        "candidate_slope": targets * blocks * 2,
        "fitted_estimator_and_transforms": raw_years * learners * blocks * 2,
        "market_slope": targets,
        "selected_candidate_and_slope": targets * blocks * learners,
        "shared_base_slope": targets * blocks * learners,
    }
    for item in result["inventory"]:
        year = item["key"] if isinstance(item["key"], int) else item["key"][0]
        assert dt.date.fromisoformat(item["horizon"]) <= _cutoff_for(int(year)), item


# ------------------------------------------------------------------ negative controls


def _copy_receipts(run_root: Path, destination: Path) -> Path:
    """Only the receipts the audit reads: never the predictions, labels or feature table."""
    run = destination / "run"
    for path in (run_root / "pipeline").rglob("*.json"):
        target = run / path.relative_to(run_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    for path in (run_root / "pipeline" / "fit_cache").glob("*/*"):
        if path.name != "fit_manifest.json":
            shutil.copyfile(path, run / path.relative_to(run_root))
    (run / "sr03_calibration").mkdir()
    shutil.copyfile(
        run_root / "sr03_calibration" / "fits.json", run / "sr03_calibration" / "fits.json"
    )
    (destination / "predictor_config").mkdir()
    shutil.copyfile(
        run_root.parent / "predictor_config" / "config.json",
        destination / "predictor_config" / "config.json",
    )
    return run


def test_each_planted_receipt_defect_fails_the_audit(
    sample_run: dict[str, Any], tmp_path: Path
) -> None:
    chain = chain_document(sample_run)
    run = _copy_receipts(sample_run["run_root"], tmp_path)
    audit_receipts(run, chain)
    detected: list[str] = []

    def reject(name: str, contains: str) -> None:
        must_reject(lambda: audit_receipts(run, chain), contains)
        detected.append(name)

    path = run / "pipeline" / "selection_complete.json"
    original = path.read_text(encoding="utf-8")
    base = json.loads(original)
    for family, message in (
        ("selection_records", "incomplete selection receipt inventory"),
        ("market_records", "incomplete market slope receipts"),
        ("shared_base_records", "incomplete shared-base receipt inventory"),
    ):
        changed = copy.deepcopy(base)
        changed[family] = []
        path.write_text(json.dumps(changed), encoding="utf-8")
        reject(f"empty_{family}", message)
        path.write_text(original, encoding="utf-8")
    first = base["selection_records"][0]
    plants = [
        (
            "future_selection_cutoff",
            lambda d: d["selection_records"][0].update(
                selection_cutoff_inclusive=f"{first['outer_year']}-01-01"
            ),
            "nonpast selection cutoff",
        ),
        (
            "missing_candidate_trial",
            lambda d: d["selection_records"][0]["candidate_trials"].pop(
                next(iter(first["candidate_trials"]))
            ),
            "incomplete candidate calibration receipts",
        ),
        (
            "unreceipted_shared_slope",
            lambda d: d["shared_base_records"][0].update(slope=999.0),
            "shared-base slope lacks matching candidate receipt",
        ),
        (
            "selected_slope_without_trial",
            lambda d: d["selection_records"][0].update(selected_slope=0.5),
            "selected slope lacks matching receipt",
        ),
    ]
    for name, change, message in plants:
        changed = copy.deepcopy(base)
        change(changed)
        path.write_text(json.dumps(changed), encoding="utf-8")
        reject(name, message)
        path.write_text(original, encoding="utf-8")

    market = next((run / "pipeline" / "market").glob("*/calibration.json"))
    saved = market.read_text(encoding="utf-8")
    market.unlink()
    reject("missing_market_file", "missing required receipt")
    market.write_text(saved, encoding="utf-8")

    raw_path = run / "pipeline" / "raw_complete.json"
    raw_original = raw_path.read_text(encoding="utf-8")
    raw_doc = json.loads(raw_original)
    attempt = raw_doc["raw_attempts"][0]
    cache = run / "pipeline" / "fit_cache" / attempt["fit_identity_sha256"]
    fit_path = cache / "fit_manifest.json"
    fit_original = fit_path.read_text(encoding="utf-8")
    fit_path.unlink()
    reject("missing_raw_fit_manifest", "missing required receipt")
    fit_path.write_text(fit_original, encoding="utf-8")

    def rebind_fit(changed_fit: dict[str, Any]) -> None:
        fit_path.write_text(json.dumps(changed_fit), encoding="utf-8")
        raw_doc["raw_attempts"][0]["fit_manifest_sha256"] = sha256(fit_path)
        raw_path.write_text(json.dumps(raw_doc), encoding="utf-8")

    changed_fit = json.loads(fit_original)
    changed_fit["fit_identity"]["fit_cutoff"] = f"{attempt['year']}-01-01"
    rebind_fit(changed_fit)
    reject("future_raw_fit_horizon", "fit horizon violates application-year cutoff")
    fit_path.write_text(fit_original, encoding="utf-8")
    raw_path.write_text(raw_original, encoding="utf-8")

    # A training key from the application year, with the byte hashes rebound so only the
    # horizon predicate can catch it.
    keys_path = cache / json.loads(fit_original)["training_keys_path"]
    keys_original = keys_path.read_bytes()
    header, keys = read_csv(keys_path)
    keys[0] = {"season": str(attempt["year"]), "match_id": f"{attempt['year']}-planted/1"}
    write_csv(keys_path, header, keys)
    changed_fit = json.loads(fit_original)
    changed_fit["training_keys_file_sha256"] = sha256(keys_path)
    raw_doc = json.loads(raw_original)
    rebind_fit(changed_fit)
    reject("application_year_training_key", "does not precede application year")
    keys_path.write_bytes(keys_original)
    fit_path.write_text(fit_original, encoding="utf-8")
    raw_path.write_text(raw_original, encoding="utf-8")

    raw_doc = json.loads(raw_original)
    raw_doc["raw_attempts"] = []
    raw_path.write_text(json.dumps(raw_doc), encoding="utf-8")
    reject("empty_raw_fits", "incomplete raw fit receipt inventory")
    raw_path.write_text(raw_original, encoding="utf-8")

    path = run / "sr03_calibration" / "fits.json"
    original = path.read_text(encoding="utf-8")
    changed = json.loads(original)
    changed[0]["training_max_date"] = f"{changed[0]['outer_year']}-01-01"
    path.write_text(json.dumps(changed), encoding="utf-8")
    reject("future_SR03_horizon", "SR03 training horizon after cutoff")
    path.write_text("[]", encoding="utf-8")
    reject("empty_SR03_fits", "incomplete SR03 fit receipts")
    path.write_text(original, encoding="utf-8")

    audit_receipts(run, chain)  # every plant was reverted; the copy is clean again
    assert detected == [
        "empty_selection_records",
        "empty_market_records",
        "empty_shared_base_records",
        "future_selection_cutoff",
        "missing_candidate_trial",
        "unreceipted_shared_slope",
        "selected_slope_without_trial",
        "missing_market_file",
        "missing_raw_fit_manifest",
        "future_raw_fit_horizon",
        "application_year_training_key",
        "empty_raw_fits",
        "future_SR03_horizon",
        "empty_SR03_fits",
    ]
