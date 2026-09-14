"""Decision RB3, the label barrier, on the committed synthetic sample.

Prospective situation: the final target year's outcomes are not yet known. The sample is
regenerated with every ``a_won`` of the last season blank, and the chain is driven from
``rule_mapping`` to ``reporting_config`` exactly as ``reproduce-small`` drives it. Every
stage before the report must complete and write its outputs, the SR03 calibration must
score no target year, the pipeline must read outcomes only through ``LabelHistory`` with
a declared purpose and a year ceiling below the year it forecasts, and the report must
refuse the year rather than score blanks.

Structural check: with ``labels.csv`` made unreadable after the ``features`` stage, the
``sidecar``, ``predictor_config`` and ``preflight`` programs still complete, so none of
them opens the file.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tennislab.chain import configs, runner
from tennislab.chain.common import ChainError
from tennislab.chain.labels import LabelHistory
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache
from tennislab.evaluation import report
from tennislab.features import sidecar
from tennislab.models import pipeline

CHAIN_CONFIG = Path("configs", "chains", "sample_atp.json")
RUN_ROOT = Path("work", "sample_atp", "run")
FINAL_YEAR = 2020
STAGES_BEFORE_REPORT = (
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
    "barrier",
    "reporting_config",
)


class RecordingLabelHistory(LabelHistory):
    """The accessor with every construction and every requested key set recorded."""

    log: list[dict[str, Any]] = []

    def __init__(self, path: Path, expected_sha256: str, *, purpose: str, year_ceiling=None):
        super().__init__(path, expected_sha256, purpose=purpose, year_ceiling=year_ceiling)
        self.entry = {"purpose": purpose, "year_ceiling": year_ceiling, "max_season": None}
        RecordingLabelHistory.log.append(self.entry)

    def selected(self, keys, metadata):
        self.entry["max_season"] = max(int(season) for season, _ in keys)
        return super().selected(keys, metadata)


def inside(workspace: Path, argv: list[str]) -> int:
    """Run one chain-driver command with the workspace installed for this process."""
    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    try:
        return runner.main(argv)
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()


def restore_module_defaults() -> None:
    # The in-process calls install the sample's year plan and bundles into the module
    # globals of the pipeline and the reporter; put JOINT04's defaults back.
    pipeline.configure_identity()
    pipeline.configure_years(pipeline.DEFAULT_YEAR_PLAN)
    pipeline.configure_cohort()
    pipeline.configure_bundles()
    report.configure_identity()
    report.configure_years(report.DEFAULT_YEAR_PLAN, report.DEFAULT_T_CRITICAL_95)
    report.configure_cohort()
    report.configure_bundles()


@pytest.fixture(scope="module")
def chain(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[dict[str, Any]]:
    root = Path(request.config.rootpath)
    workspace = tmp_path_factory.mktemp("label_barrier")
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(root / "tools" / "make_sample.py"),
            "--workspace",
            str(workspace),
            "--template",
            str(root / CHAIN_CONFIG),
            "--unknown-outcomes-final-year",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    config = str(workspace / CHAIN_CONFIG)
    record: dict[str, Any] = {"workspace": workspace, "config": config}
    assert inside(workspace, ["write-configs", "--config", config]) == 0
    assert inside(workspace, ["dry-run", "--config", config]) == 0
    assert inside(workspace, ["run", "--to", "features", "--config", config]) == 0

    # Structural check: the label file is unreadable while the three programs that
    # follow the features stage run in this process.
    labels = workspace / RUN_ROOT / "features" / "labels.csv"
    scratch = workspace / "inprocess"
    scratch.mkdir()
    mode = labels.stat().st_mode
    labels.chmod(0)
    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    try:
        with pytest.raises(PermissionError):
            labels.read_bytes()
        section = json.loads(Path(config).read_text(encoding="utf-8"))["chain"]
        stage = next(item for item in runner.stages(section) if item.name == "sidecar")
        overrides, _ = runner.fill_pending(stage, section, workspace / RUN_ROOT)
        filled = json.loads((workspace / overrides["configs.sidecar"]).read_text(encoding="utf-8"))
        filled["output"] = {
            "sidecar": (scratch / "sidecar" / "trait_latent_sidecar.csv").as_posix(),
            "lineage": (scratch / "sidecar" / "trait_lineage_groups.csv.gz").as_posix(),
            "conflicts": (scratch / "sidecar" / "trait_conflicts.csv").as_posix(),
        }
        sidecar_config = scratch / "sidecar.json"
        sidecar_config.write_text(json.dumps(filled, indent=2, sort_keys=True), encoding="utf-8")
        sidecar.run(sidecar_config)
        predictor = scratch / "predictor.json"
        status = configs.main(
            [
                "predictor",
                "--year-plan",
                section["configs"]["year_plan"],
                "--features",
                section["features"],
                "--dictionary",
                section["dictionary"],
                "--sidecar",
                (scratch / "sidecar" / "trait_latent_sidecar.csv").as_posix(),
                "--labels",
                section["labels"],
                "--design",
                section["design"],
                "--output",
                predictor.as_posix(),
            ]
        )
        assert status == 0
        assert pipeline.main(["preflight", "--config", predictor.as_posix()]) == 0
        record["unreadable_label_programs"] = ["sidecar", "predictor_config", "preflight"]
    finally:
        labels.chmod(mode)
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()

    # The rest of the chain, up to and including reporting_config.
    assert inside(workspace, ["run", "--from", "sidecar", "--config", config]) == 0

    # The pipeline again, in this process, with the accessor recording every read.
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    try:
        RecordingLabelHistory.log.clear()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(pipeline, "LabelHistory", RecordingLabelHistory)
            predictor_path = workspace / section["predictor_config"]
            output = scratch / "pipeline"
            pipeline.run_raw_stage(predictor_path, output, execute_frozen_real=True)
            pipeline.run_selection_stage(predictor_path, output, execute_frozen_real=True)
        record["label_reads"] = list(RecordingLabelHistory.log)
        # The report refuses the year whose outcomes are unknown.
        with pytest.raises(ChainError, match="stage report exited"):
            inside(workspace, ["report", "--config", config])
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()
        restore_module_defaults()
    yield record


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_every_stage_before_the_report_completes(chain: dict[str, Any]) -> None:
    run_root = chain["workspace"] / RUN_ROOT
    for name in STAGES_BEFORE_REPORT:
        manifest = json.loads((run_root / name / "stage_manifest.json").read_text(encoding="utf-8"))
        assert manifest["exit_status"] == 0, name
        if name != "barrier":
            assert manifest["output_count"] > 0, name
    assert inside(chain["workspace"], ["verify", "--config", chain["config"]]) == 0


def test_the_final_year_has_no_label_and_updates_no_state(chain: dict[str, Any]) -> None:
    rows = read_rows(chain["workspace"] / RUN_ROOT / "features" / "labels.csv")
    final = [row for row in rows if row["calendar_year"] == str(FINAL_YEAR)]
    earlier = [row for row in rows if row["calendar_year"] != str(FINAL_YEAR)]
    assert final and all(row["a_won"] == "" for row in final)
    assert all(row["a_won"] in {"0", "1"} for row in earlier)
    features = read_rows(chain["workspace"] / RUN_ROOT / "features" / "features.csv")
    # No result of the final year entered the result-Elo state: the latest Elo source
    # date on every row stays before that year.
    assert all(row["elo_latest_source_date"][:4] < str(FINAL_YEAR) for row in features)


def test_sr03_calibration_scores_no_target_year(chain: dict[str, Any]) -> None:
    stage = chain["workspace"] / RUN_ROOT / "sr03_calibration"
    boundary = json.loads((stage / "scoring_boundary.json").read_text(encoding="utf-8"))
    assert FINAL_YEAR in boundary["outer_years_suppressed_until_report_stage"]
    assert max(boundary["outer_years_scored"]) < min(
        boundary["outer_years_suppressed_until_report_stage"]
    )
    scored_years = {row["year"] for row in read_rows(stage / "metrics.csv")}
    assert str(FINAL_YEAR) not in scored_years
    predicted_years = {row["calibration_year"] for row in read_rows(stage / "predictions.csv")}
    assert str(FINAL_YEAR) in predicted_years


def test_sidecar_predictor_config_and_preflight_do_not_open_the_label_file(
    chain: dict[str, Any],
) -> None:
    assert chain["unreadable_label_programs"] == ["sidecar", "predictor_config", "preflight"]
    manifest = json.loads(
        (chain["workspace"] / RUN_ROOT / "sidecar" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["not_read"]["labels"]["path"].endswith("labels.csv")


def test_the_pipeline_reads_outcomes_only_as_declared_history(chain: dict[str, Any]) -> None:
    reads = chain["label_reads"]
    assert reads, "the pipeline read no labels through LabelHistory"
    purposes = {entry["purpose"] for entry in reads}
    assert purposes == {"training_fit", "past_selection_calibration", "past_market_calibration"}
    for entry in reads:
        assert entry["year_ceiling"] is not None and entry["year_ceiling"] < FINAL_YEAR
        assert entry["max_season"] is not None and entry["max_season"] <= entry["year_ceiling"]
    training_ceilings = sorted(
        entry["year_ceiling"] for entry in reads if entry["purpose"] == "training_fit"
    )
    assert training_ceilings == [2015, 2016, 2017, 2018, 2019]
    selection_ceilings = sorted(
        entry["year_ceiling"] for entry in reads if entry["purpose"] == "past_selection_calibration"
    )
    assert selection_ceilings == [2017, 2018, 2019]
    selection = json.loads(
        (chain["workspace"] / RUN_ROOT / "pipeline" / "selection_complete.json").read_text(
            encoding="utf-8"
        )
    )
    assert selection["status"] == "complete"
    assert selection["outer_target_outcomes_scored"] is False
    final_records = [
        record for record in selection["selection_records"] if record["outer_year"] == FINAL_YEAR
    ]
    assert final_records and all(record["status"] == "complete" for record in final_records)


def test_the_report_refuses_the_year_with_unknown_outcomes(chain: dict[str, Any]) -> None:
    stage = chain["workspace"] / RUN_ROOT / "report"
    manifest = json.loads((stage / "stage_manifest.json").read_text(encoding="utf-8"))
    assert manifest["exit_status"] != 0
    stderr = (stage / "stderr.txt").read_text(encoding="utf-8")
    assert "unresolved outcome (blank a_won)" in stderr
    assert f"('{FINAL_YEAR}'" in stderr
    assert not (stage / "primary.json").exists()
