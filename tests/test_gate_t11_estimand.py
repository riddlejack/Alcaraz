"""Gate T11 (Lane C2, admitted by archive R15/R17): paired population and estimand
consistency, recomputed from the persisted forecasts and labels.

PASS CRITERION (kept from C2, evaluated on the synthetic run): (a) the selection records
form a complete, duplicate-free inventory over target years x learners x blocks, every
record carries a positive primary population and a well-formed membership hash, and
within each year every block shares the same population and hash; (b) for the primary
and the priced cohorts, the annual and pooled log-loss and Brier deltas of the primary
contrast, the annual paired n and membership hashes, the pooled n, the pooled per-block
scores, the raw market score on the priced cohort and every number ``primary.json``
publishes reproduce from ``pipeline/selected/<year>/<learner>/<block>.csv``,
``features/labels.csv`` and ``features/features.csv`` within 1e-12, with the reporter's
score definition (log loss clipped at 1e-15, Brier unclipped). No missing-data exemption.

NEGATIVE CONTROLS (same recompute function, on a scratch copy of the tables): a
1e-8 perturbation of the published priced pooled delta, of an annual delta and of a
pooled block score, a corrupted annual membership hash, a NaN pooled score, a dropped
prediction row, a corrupted primary-population membership hash and a duplicated
selection identity each fail.

NOT COVERED HERE: the archive leaderboard rows (``registries/leaderboard.csv``) the C2
check also reconciled; the product repository publishes no leaderboard. WTA has no
scoring in the base sample, as in C2.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from tests.gate_support import (
    PLACEHOLDERS,
    chain_document,
    finite,
    must_reject,
    read_csv,
    read_json,
    write_csv,
)

TOL = 1e-12
SCORE_CLIP = 1e-15
HEX64 = re.compile(r"[0-9a-f]{64}")


def _key_hash(keys: list[tuple[str, str]]) -> str:
    import hashlib

    return hashlib.sha256("".join(f"{s},{m}\n" for s, m in keys).encode()).hexdigest()


def _scores(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    clipped = np.clip(p, SCORE_CLIP, 1.0 - SCORE_CLIP)
    return -(y * np.log(clipped) + (1.0 - y) * np.log1p(-clipped)), (p - y) ** 2


def _contrast(chain: Mapping[str, Any]) -> tuple[str, dict[str, float]]:
    name = chain["chain"]["reporting_primary_contrast"]
    treatment, control = name.split("_minus_")
    assert {treatment, control} <= set(chain["chain"]["bundles"]), (
        "primary contrast names an unfitted block"
    )
    return name, {treatment: 1.0, control: -1.0}


# ------------------------------------------------------------------ part A


def check_paired_populations(run_root: Path, chain: Mapping[str, Any]) -> dict[str, Any]:
    records = read_json(run_root / "pipeline" / "selection_complete.json").get(
        "selection_records", []
    )
    assert records, "missing selection records"
    expected = {
        (int(y), learner, block)
        for y in chain["year_plan"]["target_years"]
        for learner in chain["chain"]["learners"]
        for block in chain["chain"]["bundles"]
    }
    identities = [(int(r["outer_year"]), r["learner"], r["block"]) for r in records]
    assert len(identities) == len(set(identities)), "duplicate selection identity"
    assert set(identities) == expected, "incomplete paired population inventory"
    by_year: dict[int, dict[str, tuple[int, str]]] = {}
    for record in records:
        assert record.get("outer_primary_rows", 0) > 0, "missing primary population size"
        digest = record.get("outer_primary_membership_sha256")
        assert isinstance(digest, str) and HEX64.fullmatch(digest) and digest not in PLACEHOLDERS, (
            "missing/malformed primary membership hash"
        )
        by_year.setdefault(int(record["outer_year"]), {})[
            f"{record['learner']}/{record['block']}"
        ] = (
            int(record["outer_primary_rows"]),
            digest,
        )
    disagreements = [
        {"year": year, "blocks": blocks}
        for year, blocks in by_year.items()
        if len(set(blocks.values())) != 1
    ]
    assert not disagreements, f"blocks do not share identical populations: {disagreements[:3]}"
    return {
        "outer_years": sorted(by_year),
        "rows_by_year": {y: next(iter(b.values()))[0] for y, b in by_year.items()},
    }


# ------------------------------------------------------------------ part B


def recompute_estimand(run_root: Path, chain: Mapping[str, Any]) -> dict[str, Any]:
    contrast_id, coefficients = _contrast(chain)
    treatment = next(b for b, c in coefficients.items() if c > 0)
    control = next(b for b, c in coefficients.items() if c < 0)
    years = [int(y) for y in chain["year_plan"]["target_years"]]
    learner = "hgb"
    _, labels = read_csv(run_root / "features" / "labels.csv")
    outcome = {(r["calendar_year"], r["match_id"]): int(r["a_won"]) for r in labels}
    assert len(outcome) == len(labels), "duplicate label keys"
    primary = {
        (r["calendar_year"], r["match_id"])
        for r in labels
        if r["identity_tier"] == "primary" and r["primary_target"] == "1"
    }
    _, features = read_csv(run_root / "features" / "features.csv")
    prices = {
        (r["calendar_year"], r["match_id"]): float(r["ps_probability_a"])
        for r in features
        if r["ps_missing"] == "0" and r["ps_probability_a"] != ""
    }
    _, annual = read_csv(run_root / "report" / "annual_contrasts.csv")
    _, summary = read_csv(run_root / "report" / "contrast_summary.csv")
    _, pooled = read_csv(run_root / "report" / "pooled_metrics.csv")
    published_primary = read_json(run_root / "report" / "primary.json")

    def select(rows: list[dict[str, str]], **wanted: str) -> list[dict[str, str]]:
        return [r for r in rows if all(r[k] == v for k, v in wanted.items())]

    results: dict[str, Any] = {}
    errors: list[float] = []
    for cohort in ("primary", "primary_priced"):
        expected = select(
            annual,
            forecast_kind="selected",
            learner=learner,
            cohort=cohort,
            contrast_id=contrast_id,
        )
        assert {int(r["season"]) for r in expected} == set(years) and len(expected) == len(years), (
            f"missing annual cohort rows: {cohort}"
        )
        summed = select(
            summary,
            forecast_kind="selected",
            learner=learner,
            cohort=cohort,
            contrast_id=contrast_id,
        )
        assert len(summed) == 1, f"missing contrast summary: {cohort}"
        summed_row = summed[0]
        losses = {treatment: [], control: []}
        briers = {treatment: [], control: []}
        market_losses: list[float] = []
        annual_deltas: dict[int, float] = {}
        memberships: dict[int, dict[str, Any]] = {}
        for row in sorted(expected, key=lambda r: int(r["season"])):
            year = int(row["season"])
            predictions: dict[str, dict[tuple[str, str], float]] = {}
            for block in (treatment, control):
                _, rows = read_csv(
                    run_root / "pipeline" / "selected" / str(year) / learner / f"{block}.csv"
                )
                predictions[block] = {
                    (r["season"], r["match_id"]): float(r["p_a_wins"]) for r in rows
                }
                assert len(predictions[block]) == len(rows) > 0, (
                    "duplicate or empty prediction keys"
                )
                assert all(int(k[0]) == year for k in predictions[block]), (
                    "prediction season differs"
                )
            assert list(predictions[treatment]) == list(predictions[control]), (
                "paired membership differs"
            )
            assert set(predictions[treatment]) <= set(outcome), "missing labels for predictions"
            keys = [
                k
                for k in predictions[treatment]
                if k in primary and (cohort == "primary" or k in prices)
            ]
            assert len(keys) == int(row["n"]) > 0, f"annual paired n differs: {cohort}/{year}"
            membership = _key_hash(keys)
            assert membership == row["membership_sha256"], (
                f"annual membership hash differs: {cohort}/{year}"
            )
            y = np.asarray([outcome[k] for k in keys], dtype=np.float64)
            per_block = {}
            for block in (treatment, control):
                p = np.asarray([predictions[block][k] for k in keys], dtype=np.float64)
                assert np.all(np.isfinite(p)) and np.all((p >= 0) & (p <= 1)), (
                    "invalid forecast probability"
                )
                per_block[block] = _scores(p, y)
                losses[block].append(per_block[block][0])
                briers[block].append(per_block[block][1])
            loss_delta = float(np.mean(per_block[treatment][0] - per_block[control][0]))
            brier_delta = float(np.mean(per_block[treatment][1] - per_block[control][1]))
            errors.append(abs(loss_delta - float(row["log_loss_delta"])))
            errors.append(abs(brier_delta - float(row["brier_delta"])))
            annual_deltas[year] = loss_delta
            memberships[year] = {"n": len(keys), "sha256": membership}
            if cohort == "primary_priced":
                market_losses.append(_scores(np.asarray([prices[k] for k in keys]), y)[0])
        pooled_delta = float(
            np.mean(np.concatenate(losses[treatment]) - np.concatenate(losses[control]))
        )
        pooled_brier = float(
            np.mean(np.concatenate(briers[treatment]) - np.concatenate(briers[control]))
        )
        equal_year = float(np.mean(list(annual_deltas.values())))
        n = sum(m["n"] for m in memberships.values())
        assert n == int(summed_row["n"]), f"pooled n differs: {cohort}"
        errors.append(abs(pooled_delta - float(summed_row["match_weighted_log_loss_delta"])))
        errors.append(abs(equal_year - float(summed_row["equal_year_log_loss_delta"])))
        errors.append(abs(pooled_brier - float(summed_row["match_weighted_brier_delta"])))
        block_scores = {}
        for block in (treatment, control):
            published = select(
                pooled, forecast_kind="selected", learner=learner, block=block, cohort=cohort
            )
            assert len(published) == 1, f"missing pooled metrics: {cohort}/{block}"
            assert int(published[0]["n"]) == n, f"pooled block n differs: {cohort}/{block}"
            score = float(np.mean(np.concatenate(losses[block])))
            block_scores[block] = score
            errors.append(abs(score - float(published[0]["log_loss_match_weighted"])))
            errors.append(
                abs(
                    float(np.mean(list(map(np.mean, losses[block]))))
                    - float(published[0]["log_loss_equal_year"])
                )
            )
        result: dict[str, Any] = {
            "n": n,
            "equal_year_delta": equal_year,
            "pooled_delta": pooled_delta,
            "memberships": memberships,
            "block_scores": block_scores,
        }
        if cohort == "primary":
            assert int(published_primary["n"]) == n, "primary.json n differs"
            assert {int(k) for k in published_primary["annual_deltas"]} == set(years)
            errors += [
                abs(annual_deltas[int(k)] - float(v))
                for k, v in published_primary["annual_deltas"].items()
            ]
            errors.append(abs(equal_year - float(published_primary["equal_year_log_loss_delta"])))
            errors.append(
                abs(pooled_delta - float(published_primary["match_weighted_log_loss_delta"]))
            )
            assert published_primary["years_negative"] == sum(v < 0 for v in annual_deltas.values())
            assert published_primary["years_positive"] == sum(v > 0 for v in annual_deltas.values())
        else:
            priced = published_primary["priced_descriptive"]
            assert int(priced["n"]) == n, "primary.json priced n differs"
            errors.append(abs(equal_year - float(priced["equal_year_log_loss_delta"])))
            errors.append(abs(pooled_delta - float(priced["match_weighted_log_loss_delta"])))
            market = float(np.mean(np.concatenate(market_losses)))
            published = select(pooled, forecast_kind="market", candidate_id="raw_ps", cohort=cohort)
            assert len(published) == 1, "missing raw market pooled metrics"
            assert int(published[0]["n"]) == n, "market n differs"
            errors.append(abs(market - float(published[0]["log_loss_match_weighted"])))
            result["raw_market_log_loss"] = market
            result["treatment_minus_market_pooled"] = block_scores[treatment] - market
        results[cohort] = result
    assert all(finite(e) for e in errors), "nonfinite score/delta error"
    worst = max(errors)
    assert worst <= TOL, f"score/delta error {worst} exceeds {TOL}"
    return {
        "cohorts": results,
        "max_error": worst,
        "comparisons": len(errors),
        "contrast_id": contrast_id,
    }


# ------------------------------------------------------------------ clean behaviour


def test_blocks_share_one_population_per_year(sample_run: dict[str, Any]) -> None:
    result = check_paired_populations(sample_run["run_root"], chain_document(sample_run))
    assert result["outer_years"] == [
        int(y) for y in chain_document(sample_run)["year_plan"]["target_years"]
    ]
    assert all(rows > 100 for rows in result["rows_by_year"].values())


def test_the_published_estimand_recomputes_from_the_persisted_forecasts(
    sample_run: dict[str, Any],
) -> None:
    chain = chain_document(sample_run)
    result = recompute_estimand(sample_run["run_root"], chain)
    assert result["max_error"] <= TOL and result["comparisons"] >= 30
    primary, priced = result["cohorts"]["primary"], result["cohorts"]["primary_priced"]
    assert primary["n"] > priced["n"] > 0
    reporting = read_json(sample_run["workspace"] / chain["chain"]["reporting_config"])
    assert primary["n"] == reporting["expected_membership"]["selected_primary_rows"]
    assert priced["n"] == reporting["expected_membership"]["selected_primary_priced_rows"]
    # The primary population is exactly the pipeline's committed membership.
    populations = check_paired_populations(sample_run["run_root"], chain)["rows_by_year"]
    assert {y: m["n"] for y, m in primary["memberships"].items()} == populations


# ------------------------------------------------------------------ negative controls


def _copy_tables(
    sample_run: Mapping[str, Any], destination: Path, chain: Mapping[str, Any]
) -> Path:
    source: Path = sample_run["run_root"]
    run = destination / "run"
    relative = [
        "features/features.csv",
        "features/labels.csv",
        "report/annual_contrasts.csv",
        "report/contrast_summary.csv",
        "report/pooled_metrics.csv",
        "report/primary.json",
        "pipeline/selection_complete.json",
    ]
    relative += [
        f"pipeline/selected/{y}/hgb/{b}.csv"
        for y in chain["year_plan"]["target_years"]
        for b in chain["chain"]["bundles"]
    ]
    for item in relative:
        (run / item).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / item, run / item)
    return run


def _edit_csv(path: Path, change: Any) -> None:
    header, rows = read_csv(path)
    for row in rows:
        change(row)
    write_csv(path, header, rows)


def test_each_planted_estimand_defect_fails_the_recompute(
    sample_run: dict[str, Any], tmp_path: Path
) -> None:
    chain = chain_document(sample_run)
    contrast_id, _ = _contrast(chain)
    run = _copy_tables(sample_run, tmp_path, chain)
    recompute_estimand(run, chain)
    check_paired_populations(run, chain)
    detected: list[str] = []

    def perturbed(cohort: str, field: str) -> Any:
        def change(row: dict[str, str]) -> None:
            if (
                row["forecast_kind"] == "selected"
                and row["cohort"] == cohort
                and row["contrast_id"] == contrast_id
            ):
                row[field] = repr(float(row[field]) + 1e-8)

        return change

    summary = run / "report" / "contrast_summary.csv"
    original = summary.read_bytes()
    _edit_csv(summary, perturbed("primary_priced", "match_weighted_log_loss_delta"))
    detected.append(must_reject(lambda: recompute_estimand(run, chain), "exceeds 1e-12"))
    summary.write_bytes(original)

    annual = run / "report" / "annual_contrasts.csv"
    original = annual.read_bytes()
    _edit_csv(annual, perturbed("primary", "log_loss_delta"))
    detected.append(must_reject(lambda: recompute_estimand(run, chain), "exceeds 1e-12"))
    annual.write_bytes(original)
    header, rows = read_csv(annual)
    target = next(
        r
        for r in rows
        if r["forecast_kind"] == "selected"
        and r["cohort"] == "primary"
        and r["contrast_id"] == contrast_id
    )
    target["membership_sha256"] = "c" * 64
    write_csv(annual, header, rows)
    detected.append(
        must_reject(lambda: recompute_estimand(run, chain), "annual membership hash differs")
    )
    annual.write_bytes(original)

    pooled = run / "report" / "pooled_metrics.csv"
    original = pooled.read_bytes()

    def nan_score(row: dict[str, str]) -> None:
        if row["forecast_kind"] == "market" and row["candidate_id"] == "raw_ps":
            row["log_loss_match_weighted"] = "nan"

    _edit_csv(pooled, nan_score)
    detected.append(
        must_reject(lambda: recompute_estimand(run, chain), "nonfinite score/delta error")
    )
    pooled.write_bytes(original)

    def bump_block(row: dict[str, str]) -> None:
        if (
            row["forecast_kind"] == "selected"
            and row["cohort"] == "primary"
            and row["block"] == "full"
        ):
            row["log_loss_match_weighted"] = repr(float(row["log_loss_match_weighted"]) + 1e-8)

    _edit_csv(pooled, bump_block)
    detected.append(must_reject(lambda: recompute_estimand(run, chain), "exceeds 1e-12"))
    pooled.write_bytes(original)

    year = str(chain["year_plan"]["target_years"][0])
    forecast = run / "pipeline" / "selected" / year / "hgb" / "full.csv"
    original = forecast.read_bytes()
    header, rows = read_csv(forecast)
    write_csv(forecast, header, rows[:-1])
    detected.append(
        must_reject(lambda: recompute_estimand(run, chain), "paired membership differs")
    )
    forecast.write_bytes(original)

    primary = run / "report" / "primary.json"
    original = primary.read_bytes()
    document = json.loads(original)
    document["priced_descriptive"]["n"] += 1
    primary.write_text(json.dumps(document), "utf-8")
    detected.append(
        must_reject(lambda: recompute_estimand(run, chain), "primary.json priced n differs")
    )
    primary.write_bytes(original)

    selection = run / "pipeline" / "selection_complete.json"
    original = selection.read_bytes()
    document = json.loads(original)
    corrupted = copy.deepcopy(document)
    corrupted["selection_records"][0]["outer_primary_membership_sha256"] = "c" * 64
    selection.write_text(json.dumps(corrupted), "utf-8")
    detected.append(
        must_reject(lambda: check_paired_populations(run, chain), "identical populations")
    )
    duplicated = copy.deepcopy(document)
    duplicated["selection_records"].append(dict(duplicated["selection_records"][0]))
    selection.write_text(json.dumps(duplicated), "utf-8")
    detected.append(
        must_reject(lambda: check_paired_populations(run, chain), "duplicate selection identity")
    )
    selection.write_bytes(original)

    recompute_estimand(run, chain)  # every plant was reverted
    assert len(detected) == 9
