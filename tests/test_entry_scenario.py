"""ARMS01 Arm 1 rehearsal: the entry/level block through the real chain driver.

``configs/chains/sample_atp_tier_entry.json`` is the committed tier sample with the
features stage's ``entry_level_block`` switched on and the bundles ``base``, ``full_tier``
and ``full_tier_entry``. The chain is regenerated into a temporary workspace and driven
from ``rule_mapping`` to ``report`` exactly as ``tennislab reproduce-small --scenario
tier_entry`` drives it. Two things are checked beyond "it runs": the block is appended
after every existing column and reaches only the entry bundle, and the bundles that do
not read it (``base``, ``full_tier``) reproduce the tier scenario's pinned pooled log
losses to the pin's tolerance, which is the Arm 0 reproduction check on synthetic data.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tennislab import reproduce
from tennislab.chain import runner
from tennislab.features import base as features
from tennislab.models import pipeline
from tests.test_tier_scenario import SAMPLE, committed_sample, generate, inside

CHAIN_CONFIG = Path("configs", "chains", "sample_atp_tier_entry.json")
RUN_ROOT = Path("work", "sample_atp_tier_entry", "run")
BLOCK = features.ENTRY_RAW_AUDIT_COLUMNS + features.ENTRY_LEVEL_COLUMNS


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


@pytest.fixture(scope="module")
def entry_chain(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[dict[str, Any]]:
    root = Path(request.config.rootpath)
    committed_sample(root)
    assert (root / CHAIN_CONFIG).is_file(), f"the entry chain config is absent: {CHAIN_CONFIG}"
    workspace = tmp_path_factory.mktemp("entry_scenario")
    # The generator re-pins the tier sample and its template; the entry config binds the
    # same sample files, so it is copied beside them unchanged.
    generate(root, workspace)
    (workspace / CHAIN_CONFIG).write_bytes((root / CHAIN_CONFIG).read_bytes())
    config = str(workspace / CHAIN_CONFIG)
    assert inside(workspace, ["write-configs", "--config", config]) == 0
    assert inside(workspace, ["dry-run", "--config", config]) == 0
    assert inside(workspace, ["run", "--include-report", "--config", config]) == 0
    yield {"workspace": workspace, "config": config, "root": root}


def test_the_entry_config_binds_the_tier_sample_and_declares_the_block(
    request: pytest.FixtureRequest,
) -> None:
    root = Path(request.config.rootpath)
    tier = read_json(root / "configs" / "chains" / "sample_atp_tier.json")["chain"]
    entry = read_json(root / CHAIN_CONFIG)["chain"]
    assert entry["inputs"] == tier["inputs"]
    assert entry["entry_level_block"] is True
    assert entry["bundles"] == ["base", "full_tier", "full_tier_entry"]
    assert entry["reporting_primary_contrast"] == "full_tier_entry_minus_full_tier"
    assert entry["tier_initial_rating_offset_by_year"] == tier["tier_initial_rating_offset_by_year"]
    assert reproduce.SCENARIOS["tier_entry"].expected.name == "expected_entry.json"


def test_every_stage_completes_and_the_features_stage_appends_the_block(
    entry_chain: dict[str, Any],
) -> None:
    run_root = entry_chain["workspace"] / RUN_ROOT
    stage_names = [
        stage.name for stage in runner.stages(read_json(Path(entry_chain["config"]))["chain"])
    ]
    for name in stage_names:
        if (run_root / name / "stage_manifest.json").is_file():
            assert read_json(run_root / name / "stage_manifest.json")["exit_status"] == 0, name
    header, rows = read_csv(run_root / "features" / "features.csv")
    assert tuple(header) == features.feature_header(entry_level=True)
    assert tuple(header[-len(BLOCK) :]) == BLOCK
    assert tuple(header[: -len(BLOCK)]) == features.feature_header()
    dictionary = read_json(run_root / "features" / "column_dictionary.json")
    assert dictionary["entry_level_columns"] == list(features.ENTRY_LEVEL_COLUMNS)
    assert dictionary["ordered_feature_file_columns"] == header
    # The sample draws Q and WC entries and G/M/A levels, so the block is not constant.
    assert any(row["entry_q_diff"] != "0" for row in rows)
    assert any(row["entry_wc_diff"] != "0" for row in rows)
    assert any(row["entry_any_qualifier"] == "1" for row in rows)
    assert {row["level_context_g"] for row in rows} == {"0", "1"}
    for row in rows:
        assert row["entry_q_diff"] in {"-1", "0", "1"}
        assert sum(int(row[column]) for column in features.LEVEL_CONTEXT) <= 1
    summary = read_json(run_root / "features" / "summary.json")["entry_level_block"]
    assert summary["flagged_entry_codes"] == ["Q", "LL", "WC", "PR"]
    assert set(summary["counts_by_season"]) and isinstance(
        summary["events_without_any_entry_code"], list
    )
    assert inside(entry_chain["workspace"], ["verify", "--config", entry_chain["config"]]) == 0


def test_the_block_reaches_only_the_entry_bundle(entry_chain: dict[str, Any]) -> None:
    workspace = entry_chain["workspace"]
    section = read_json(Path(entry_chain["config"]))["chain"]
    predictor = read_json(workspace / section["predictor_config"])
    columns = predictor["ordered_model_columns"]["hgb"]
    tier = columns["full_tier"]
    entry = columns["full_tier_entry"]
    assert entry["numeric_or_signed"] == [*tier["numeric_or_signed"], *pipeline.ENTRY_LEVEL_SIGNED]
    assert entry["symmetric_context"] == [*tier["symmetric_context"], *pipeline.ENTRY_LEVEL_CONTEXT]
    for block in ("base", "full_tier"):
        assert not set(pipeline.ENTRY_LEVEL_COLUMNS) & set(columns[block]["numeric_or_signed"])
        assert not set(pipeline.ENTRY_LEVEL_COLUMNS) & set(columns[block]["symmetric_context"])
    assert predictor["settings"]["entry_level_columns"] == list(pipeline.ENTRY_LEVEL_COLUMNS)
    assert predictor["settings"]["blocks"] == ["base", "full_tier", "full_tier_entry"]
    assert predictor["experiment_id"] == "TIER01"  # the emitted year plan names no id


def test_the_bundles_without_the_block_reproduce_the_tier_pin(entry_chain: dict[str, Any]) -> None:
    """Arm 0 on synthetic data: appending the block changes nothing for the bundles that do
    not read it, so `base` and `full_tier` match the tier scenario's pinned pooled values."""
    observed = reproduce.headline(entry_chain["workspace"], reproduce.SCENARIOS["tier_entry"])
    assert observed["primary_contrast"] == "full_tier_entry_minus_full_tier"
    tier_pin = read_json(entry_chain["root"] / SAMPLE / "expected.json")
    tolerance = float(tier_pin["tolerance"])
    for model in ("selected/hgb/base", "selected/hgb/full_tier", "market/calibrated_ps"):
        pinned = tier_pin["pooled_log_loss_match_weighted"][model]
        assert abs(observed["pooled_log_loss_match_weighted"][model] - pinned) <= tolerance, model
    entry_pin = read_json(entry_chain["root"] / SAMPLE / "expected_entry.json")
    assert reproduce.compare(observed, entry_pin) == []
    primary = read_json(entry_chain["workspace"] / RUN_ROOT / "report" / "primary.json")
    assert primary["effect_direction"] == "negative_favors_entry_level_block"
    assert primary["secondary_contrasts"] == {}
