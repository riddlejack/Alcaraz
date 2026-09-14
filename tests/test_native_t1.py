"""Native B2 T1: actual forecast paths, full future outcome/stat mutations, both tours.

The design is frozen in docs/NATIVE_T1.md. No archive mount or fixture-absence skip.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from tennislab.chain import runner
from tests.conftest import drive, rewind
from tests.native_t1_support import (
    CUTOFF,
    TARGET_DATE,
    assert_same_targets,
    build_fixture,
    compare_runs,
    mutate,
    read_json,
    rows,
)
from tests.test_barrier_gate import _install_shim


def run_to_pipeline(run: dict[str, Any]) -> None:
    assert drive(run["workspace"], ["write-configs", "--config", run["config"]]) == 0
    assert drive(run["workspace"], ["run", "--to", "pipeline", "--config", run["config"]]) == 0
    run["stages"] = [
        json.loads(line)["stage"]
        for line in (run["run_root"] / runner.LEDGER).read_text().splitlines()
    ]


@pytest.fixture(scope="module", params=["ATP", "WTA"])
def pair(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    directory = tmp_path_factory.mktemp(f"native_t1_{request.param.lower()}")
    start = time.monotonic()
    clean = build_fixture(Path(request.config.rootpath), directory / "clean", request.param)
    run_to_pipeline(clean)
    changed = mutate(clean, directory / "mutated")
    run_to_pipeline(changed)
    comparisons = compare_runs(clean, changed)
    record = {
        "tour": request.param,
        "target_date": TARGET_DATE,
        "eligible_through_date": CUTOFF,
        "targets": sorted(changed["targets"]),
        "mutation": changed["mutation"],
        "compared_rows_by_artifact": comparisons,
        "runtime_seconds": time.monotonic() - start,
    }
    (directory / "result.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print("native T1:", json.dumps(record, sort_keys=True))
    return {"clean": clean, "changed": changed, "record": record}


def test_native_forecasts_are_invariant_under_future_full_bundle_mutation(
    pair: dict[str, Any],
) -> None:
    assert pair["record"]["compared_rows_by_artifact"]
    clean, changed = pair["clean"], pair["changed"]
    features = rows(clean["run_root"] / "features" / "features.csv")
    target = [row for row in features if row["match_id"] in changed["targets"]]
    assert target and {row["eligible_through_date"] for row in target} == {CUTOFF}
    labels_before = {
        row["match_id"]: row["a_won"] for row in rows(clean["run_root"] / "features" / "labels.csv")
    }
    labels_after = {
        row["match_id"]: row["a_won"]
        for row in rows(changed["run_root"] / "features" / "labels.csv")
    }
    assert all(labels_before[key] != labels_after[key] for key in changed["targets"])
    # Native tour-specific dispatch, rather than silently running the ATP chain twice.
    manifest = read_json(clean["run_root"] / "rule_mapping" / "stage_manifest.json")
    assert ("wta_rules" in json.dumps(manifest)) == (clean["tour"] == "WTA")


def test_the_intervention_changes_later_native_state_outputs(pair: dict[str, Any]) -> None:
    clean, changed = pair["clean"], pair["changed"]
    paths = [
        "features/features.csv",
        "sr02_replay/selected_matches.csv",
        "sidecar/trait_latent_sidecar.csv",
    ]
    if clean["tour"] == "ATP":
        paths += [
            "tier_elo/tier_elo_features.csv",
            "sr02_tier_replay/selected_matches.csv",
            "sr02_tier_noqual_replay/selected_matches.csv",
            "tier_block/trait_latent_sidecar.csv",
        ]
    for filename in paths:
        left = {row["match_id"]: row for row in rows(clean["run_root"] / filename)}
        right = {row["match_id"]: row for row in rows(changed["run_root"] / filename)}
        assert left.keys() == right.keys()
        # Input changes really reach each stage when they legitimately become history.
        assert any(left[key] != right[key] for key in left if key not in changed["targets"]), (
            filename
        )


def test_native_intervention_preserves_the_cutoff_and_changes_all_future_panel_rows(
    pair: dict[str, Any],
) -> None:
    clean, changed = pair["clean"], pair["changed"]
    before = rows(clean["sample"] / "panel.csv")
    after = rows(changed["sample"] / "panel.csv")
    assert len(before) == len(after)
    at_cutoff = future = 0
    for left, right in zip(before, after, strict=True):
        if left["match_date"] <= CUTOFF:
            assert left == right
            at_cutoff += left["match_date"] == CUTOFF
        else:
            assert left["a_won"] != right["a_won"]
            assert left["status"] != right["status"]
            assert left["minutes"] != right["minutes"]
            assert any(
                left[f"{side}_{suffix}"] != right[f"{side}_{suffix}"]
                for side in ("a", "b")
                for suffix in ("svpt", "1stIn", "1stWon", "2ndWon")
            )
            future += 1
    assert at_cutoff > 0 and future == changed["mutation"]["panel_rows"]


FUTURE_SIDECAR = '''
"""Controlled outcome-dependent feature writer, under the real history declaration."""
import csv, json, sys
from pathlib import Path
from tennislab.features import sidecar
from tennislab.chain.common import resolve_under_root

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    status = sidecar.main(argv)
    config = json.loads(Path(argv[argv.index("--config") + 1]).read_text())
    panel = resolve_under_root(config["inputs"]["sr02_panel"]["path"], label="test panel")
    with panel.open(newline="") as handle:
        labels = {row["match_id"]: row["a_won"] for row in csv.DictReader(handle)}
    output = resolve_under_root(config["output"]["sidecar"], label="test output")
    with output.open(newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        records = list(reader)
    for row in records:
        row["dynamic_match_probability_a"] = "0.9" if labels[row["match_id"]] == "true" else "0.1"
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(records)
    return status

if __name__ == "__main__":
    raise SystemExit(main())
'''


def test_native_t1_rejects_controlled_future_outcome_use(
    pair: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_shim(tmp_path / "shims", "native_t1_future_sidecar", FUTURE_SIDECAR, monkeypatch)
    monkeypatch.setitem(runner.MODULES, "sidecar", "native_t1_future_sidecar")
    planted = []
    for name in ("clean", "changed"):
        source = pair[name]
        workspace = tmp_path / name
        shutil.copytree(source["workspace"], workspace)
        run = {
            **source,
            "workspace": workspace,
            "config": str(workspace / Path(source["config"]).relative_to(source["workspace"])),
            "run_root": workspace / source["run_root"].relative_to(source["workspace"]),
        }
        rewind(run, "sidecar")
        assert (
            drive(
                workspace,
                ["run", "--from", "sidecar", "--to", "sidecar", "--config", run["config"]],
            )
            == 0
        )
        manifest = read_json(run["run_root"] / "sidecar" / "stage_manifest.json")
        assert manifest["outcome_access"]["declared"] == "history"
        assert manifest["outcome_access"]["violations"] == []
        planted.append(run["run_root"] / "sidecar" / "trait_latent_sidecar.csv")
    with pytest.raises(AssertionError, match="future outcome changed target rows"):
        assert_same_targets(planted[0], planted[1], pair["changed"]["targets"])
