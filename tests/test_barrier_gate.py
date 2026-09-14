"""Decision RB14 at the public chain interface: the clean chain passes, planted leaks fail.

Positive (clean) behaviour on the session's synthetic run: no metric-shaped artifact
before the barrier, every stage's observed outcome access matches its declaration, the
fold readers' receipts precede their folds, ``verify`` passes, and the SR03 component
metrics are computed after the barrier from the persisted predictions.

Negative controls, each through the chain driver with a substituted stage module:

* a stage that writes a JSON metric, a nested CSV metric, a JSONL metric and a gzip CSV
  metric before the barrier -- the barrier refuses to freeze the run tree and names all
  four;
* a stage declared ``none`` that parses the panel -- the stage fails;
* a fold reader (the pipeline) that opens ``labels.csv`` outside the accessor and takes a
  receipt without a fold -- the stage fails on both counts;
* an accessor asked for a ceiling that does not precede its fold -- refused;
* a selection commitment that does not match the recomputed criterion -- the reporter
  refuses.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import textwrap
from pathlib import Path
from typing import Any

import pytest

from tennislab.chain import barrier_scan, runner
from tennislab.chain.common import ChainError
from tennislab.chain.labels import LabelHistory, LabelHistoryError, PanelOutcomeHistory
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache
from tennislab.evaluation import report
from tests.conftest import copy_run, drive, rewind

PRE_BARRIER = (
    "rule_mapping",
    "sr02_replay",
    "sr03_calibration",
    "rankings",
    "edition_index",
    "features",
    "sidecar",
    "predictor_config",
    "preflight",
    "pipeline",
)


def manifest(run: dict[str, Any], stage: str) -> dict[str, Any]:
    return json.loads((run["run_root"] / stage / "stage_manifest.json").read_text("utf-8"))


# ------------------------------------------------------------------ clean behaviour


def test_no_metric_shaped_artifact_before_the_barrier(sample_run: dict[str, Any]) -> None:
    scan = barrier_scan.scan_tree(sample_run["run_root"], list(PRE_BARRIER))
    assert scan["findings"] == []
    assert len(scan["scanned"]) > 100
    barrier = manifest(sample_run, "barrier")
    assert barrier["content_scan"]["findings"] == []
    assert "run_tree_sha256" in barrier and barrier["integrity_violations"] == []


def test_every_stage_matches_its_declaration(sample_run: dict[str, Any]) -> None:
    declared = {stage.name: stage.outcome_access for stage in runner.stages({"tour": "ATP"})}
    declared["report"] = "target"
    declared["sr03_component"] = "target"
    for name in sample_run["stages"]:
        record = manifest(sample_run, name)["outcome_access"]
        assert record["declared"] == declared[name], name
        assert record["violations"] == [], name
        parsed = [item for item in record["observed"] if item["access"] == "parsed"]
        if record["declared"] == "none":
            assert parsed == [], name
        if record["declared"] == "fold":
            assert parsed, name
            assert all(item["opener"] in runner.ACCESSOR_OPENERS for item in parsed), name
            assert record["receipts"], name
            for receipt in record["receipts"]:
                if receipt["accessor"] == "projected_rows":
                    assert "a_won" in receipt["outcome_columns_dropped"], name
                    continue
                assert receipt["year_ceiling"] < receipt["fold_outer_year"], name
                assert receipt["max_season_returned"] <= receipt["year_ceiling"], name
    # The declaration is not the evidence: the runner observed the reads it reports.
    features = manifest(sample_run, "features")["outcome_access"]["observed"]
    assert any(
        item["path"].endswith("panel.csv") and item["access"] == "parsed" for item in features
    )
    predictor = manifest(sample_run, "predictor_config")["outcome_access"]["observed"]
    assert predictor == [] or all(item["access"] == "hash_only" for item in predictor)


def test_verify_passes_on_the_clean_run(sample_run: dict[str, Any]) -> None:
    assert drive(sample_run["workspace"], ["verify", "--config", sample_run["config"]]) == 0


def test_sr03_component_metrics_are_computed_after_the_barrier(sample_run: dict[str, Any]) -> None:
    run_root = sample_run["run_root"]
    assert sample_run["stages"].index("sr03_component") > sample_run["stages"].index("barrier")
    for name in ("metrics.csv", "reliability.csv", "comparisons.json", "cohort_counts.json"):
        assert (run_root / "sr03_component" / name).is_file()
        assert not (run_root / "sr03_calibration" / name).exists()
    component = json.loads((run_root / "sr03_component" / "component_manifest.json").read_text())
    calibration = json.loads((run_root / "sr03_calibration" / "run_manifest.json").read_text())
    assert component["predictions_sha256"] == calibration["artifacts"]["predictions.csv"]
    assert component["unresolved_rows"] == 0
    with (run_root / "sr03_component" / "metrics.csv").open(newline="") as handle:
        years = {row["year"] for row in csv.DictReader(handle)}
    boundary = json.loads((run_root / "sr03_calibration" / "scoring_boundary.json").read_text())
    assert {str(y) for y in boundary["outer_years_deferred_to_sr03_component_stage"]} <= years


def test_the_reporter_publishes_the_selection_scores_it_recomputed(
    sample_run: dict[str, Any],
) -> None:
    trials = json.loads((sample_run["run_root"] / "report" / "selection_trials.json").read_text())
    assert trials["status"] == "recomputed_after_barrier"
    record = trials["selection_records"][0]
    chosen = record["selection"]["selected_candidate_id"]
    assert record["candidate_trials"][chosen]["equal_year_mean_log_loss"] is not None
    # And the pre-barrier record carried the commitment, not the scores.
    pre = json.loads(
        (
            sample_run["run_root"]
            / "pipeline"
            / "selection"
            / str(record["outer_year"])
            / record["learner"]
            / f"{record['block']}.json"
        ).read_text()
    )
    assert pre["criterion_sha256"] == record["criterion_sha256"]
    assert "equal_year_mean_log_loss" not in pre["candidate_trials"][chosen]
    assert all("score" not in item for item in pre["selection"]["ranked"])


# ------------------------------------------------------------------ content scan controls


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_the_content_scan_catches_each_planted_metric_shape(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    (run_root / "clean").mkdir(parents=True)
    _write_json(
        run_root / "clean" / "fits.json", {"slope": 0.9, "n": 12, "annual": {"2014": {"n": 4}}}
    )
    (run_root / "clean" / "predictions.csv").write_text("season,match_id,p_a_wins\n2014,m1,0.5\n")
    assert barrier_scan.scan_tree(run_root, ["clean"])["findings"] == []

    (run_root / "leak").mkdir()
    _write_json(run_root / "leak" / "anything.json", {"diagnostic": {"brier_score": 0.21}})
    (run_root / "leak" / "nested").mkdir()
    (run_root / "leak" / "nested" / "table.csv").write_text(
        "year,model,mean_log_loss\n2017,a,0.6\n"
    )
    (run_root / "leak" / "events.jsonl").write_text(
        json.dumps({"fit": 1}) + "\n" + json.dumps({"year": 2017, "score": 0.61}) + "\n"
    )
    with gzip.open(run_root / "leak" / "bins.csv.gz", "wb") as handle:
        handle.write(b"bin,n,outcome_rate\n1,10,0.4\n")
    _write_json(run_root / "leak" / "long.json", {"metric": "log_loss", "value": 0.6})
    _write_json(
        run_root / "leak" / "delta.json",
        {"contrast": {"annual": [{"year": 2017, "delta": -0.01}]}},
    )
    found = {item["artifact"] for item in barrier_scan.scan_tree(run_root, ["leak"])["findings"]}
    assert found == {
        "leak/anything.json",
        "leak/nested/table.csv",
        "leak/events.jsonl",
        "leak/bins.csv.gz",
        "leak/long.json",
        "leak/delta.json",
    }


# ------------------------------------------------------------------ runtime plants

LEAKY_SIDECAR = '''
"""A sidecar that also writes four metric-shaped artifacts before the barrier."""
import csv, gzip, json, sys
from pathlib import Path
from tennislab.features import sidecar

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    status = sidecar.main(argv)
    config = json.loads(Path(argv[argv.index("--config") + 1]).read_text())
    out = Path(config["output"]["sidecar"]).parent
    (out / "diagnostic.json").write_text(json.dumps({"fit": {"log_loss": 0.61}}))
    (out / "deep").mkdir(exist_ok=True)
    (out / "deep" / "table.csv").write_text("year,model,brier\\n2017,x,0.2\\n")
    (out / "events.jsonl").write_text(json.dumps({"year": 2018, "loss": 0.6}) + "\\n")
    with gzip.open(out / "bins.csv.gz", "wb") as handle:
        handle.write(b"bin,outcome_rate\\n1,0.5\\n")
    return status

if __name__ == "__main__":
    raise SystemExit(main())
'''

LEAKY_EDITION_INDEX = '''
"""An edition index that parses the panel's outcomes although it is declared none."""
import csv, os, sys
from tennislab.chronology import edition_index

def main(argv=None):
    with open(os.environ["LEAK_PANEL"], newline="", encoding="utf-8") as handle:
        rows = [row["a_won"] for row in csv.DictReader(handle)]
    assert rows
    return edition_index.main(argv)

if __name__ == "__main__":
    raise SystemExit(main())
'''

LEAKY_PIPELINE = '''
"""A pipeline that reads labels outside the accessor and takes receipts without a fold."""
import csv, os, sys
from tennislab.chain.labels import LabelHistory
from tennislab.models import pipeline

def label_subset_without_fold(path, expected_sha256, keys, metadata, *, purpose, year_ceiling, fold_outer_year=None):
    history = LabelHistory(path, expected_sha256, purpose=purpose, year_ceiling=year_ceiling)
    return history.selected(keys, metadata)

def main(argv=None):
    with open(os.environ["LEAK_LABELS"], newline="", encoding="utf-8") as handle:
        rows = [row["a_won"] for row in csv.DictReader(handle)]
    assert rows
    pipeline.label_subset = label_subset_without_fold
    return pipeline.main(argv)

if __name__ == "__main__":
    raise SystemExit(main())
'''


def _install_shim(directory: Path, name: str, source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.py").write_text(textwrap.dedent(source), encoding="utf-8")
    # The stage subprocess finds the shim through PYTHONPATH; the driver's in-process
    # code receipt imports it too.
    monkeypatch.setenv("PYTHONPATH", str(directory))
    monkeypatch.syspath_prepend(str(directory))


def test_the_barrier_refuses_a_stage_that_writes_metrics(
    sample_run: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = copy_run(sample_run, tmp_path / "ws")
    rewind(run, "sidecar")
    _install_shim(tmp_path / "shims", "leaky_sidecar", LEAKY_SIDECAR, monkeypatch)
    monkeypatch.setitem(runner.MODULES, "sidecar", "leaky_sidecar")
    with pytest.raises(ChainError, match="metric-shaped content before the barrier"):
        drive(
            run["workspace"],
            ["run", "--from", "sidecar", "--to", "barrier", "--config", run["config"]],
        )
    barrier = manifest(run, "barrier")
    assert barrier.get("status") == "refused" and "run_tree_sha256" not in barrier
    found = {item["artifact"] for item in barrier["content_scan"]["findings"]}
    assert found == {
        "sidecar/diagnostic.json",
        "sidecar/deep/table.csv",
        "sidecar/events.jsonl",
        "sidecar/bins.csv.gz",
    }
    ledger = (run["run_root"] / runner.LEDGER).read_text(encoding="utf-8").splitlines()
    assert json.loads(ledger[-1])["integrity"] == "fail"
    with pytest.raises(ChainError):
        drive(run["workspace"], ["verify", "--config", run["config"]])


def test_a_stage_declared_none_fails_when_it_parses_outcomes(
    sample_run: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = copy_run(sample_run, tmp_path / "ws")
    rewind(run, "edition_index")
    _install_shim(tmp_path / "shims", "leaky_edition_index", LEAKY_EDITION_INDEX, monkeypatch)
    monkeypatch.setenv("LEAK_PANEL", str(run["workspace"] / "data" / "sample" / "panel.csv"))
    monkeypatch.setitem(runner.MODULES, "edition_index", "leaky_edition_index")
    with pytest.raises(ChainError, match="declares no outcome access but parsed"):
        drive(
            run["workspace"],
            ["run", "--from", "edition_index", "--to", "edition_index", "--config", run["config"]],
        )
    record = manifest(run, "edition_index")["outcome_access"]
    assert record["declared"] == "none"
    assert any(
        item["path"].endswith("panel.csv") and item["access"] == "parsed"
        for item in record["observed"]
    )
    assert record["violations"]


def test_a_fold_reader_fails_outside_the_accessor_or_without_a_fold(
    sample_run: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = copy_run(sample_run, tmp_path / "ws")
    rewind(run, "pipeline")
    _install_shim(tmp_path / "shims", "leaky_pipeline", LEAKY_PIPELINE, monkeypatch)
    monkeypatch.setenv("LEAK_LABELS", str(run["run_root"] / "features" / "labels.csv"))
    monkeypatch.setitem(runner.MODULES, "pipeline", "leaky_pipeline")
    with pytest.raises(ChainError, match="failed the integrity check"):
        drive(
            run["workspace"],
            ["run", "--from", "pipeline", "--to", "pipeline", "--config", run["config"]],
        )
    violations = manifest(run, "pipeline")["outcome_access"]["violations"]
    assert any("outside the accessors" in item for item in violations)
    assert any("names no fold" in item for item in violations)


def test_an_accessor_refuses_a_ceiling_that_reaches_its_fold(sample_run: dict[str, Any]) -> None:
    labels = sample_run["run_root"] / "features" / "labels.csv"
    panel = sample_run["workspace"] / "data" / "sample" / "panel.csv"
    from tennislab.chain.common import sha256

    with pytest.raises(LabelHistoryError, match="does not precede fold"):
        LabelHistory(
            labels, sha256(labels), purpose="training_fit", year_ceiling=2018, fold_outer_year=2018
        )
    with pytest.raises(LabelHistoryError, match="does not precede fold"):
        PanelOutcomeHistory(
            panel,
            sha256(panel),
            purpose="calibration_slope_fit",
            year_ceiling=2019,
            fold_outer_year=2018,
        )
    history = PanelOutcomeHistory(
        panel, sha256(panel), purpose="calibration_slope_fit", year_ceiling=2017
    )
    with panel.open(newline="", encoding="utf-8") as handle:
        late = next(
            row["match_id"] for row in csv.DictReader(handle) if row["source_season"] == "2018"
        )
    with pytest.raises(LabelHistoryError, match="after the 2017 ceiling"):
        history.selected([late])


def test_the_reporter_refuses_a_commitment_that_does_not_match(sample_run: dict[str, Any]) -> None:
    workspace = sample_run["workspace"]
    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    try:
        config = json.loads(Path(sample_run["config"]).read_text(encoding="utf-8"))["chain"]
        inputs = report.preflight(workspace / config["reporting_config"])
        assert report.recompute_selection_criteria(inputs)["status"] == "recomputed_after_barrier"
        record = inputs.selection_records[0]
        original = record["criterion_sha256"]
        record["criterion_sha256"] = "0" * 64
        with pytest.raises(ChainError, match="differs from the pipeline's commitment"):
            report.recompute_selection_criteria(inputs)
        record["criterion_sha256"] = original
        # A decision that is not the argmin of its own criterion.
        record["selected_candidate_id"] = "not-the-argmin"
        with pytest.raises(ChainError, match="not the argmin"):
            report.recompute_selection_criteria(inputs)
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()
        report.configure_identity()
        report.configure_years(report.DEFAULT_YEAR_PLAN, report.DEFAULT_T_CRITICAL_95)
        report.configure_cohort()
        report.configure_bundles()
