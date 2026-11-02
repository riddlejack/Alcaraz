"""``tennislab reproduce-small``: run a committed synthetic sample chain and check it.

The samples under ``data/sample`` (the base scenario) and ``data/sample_tier`` (the tier
scenario, ``--scenario tier``) are fully synthetic (see their READMEs). This command
copies the scenario's sample into a fresh workspace under ``data/runs/``, drives the chain
from ``rule_mapping`` to ``report`` through :mod:`tennislab.chain.runner`
(``write-configs``, ``dry-run``, ``run --include-report``), and compares the report's
headline numbers with the values pinned in the sample's ``expected.json``. Any mismatch
beyond the pinned tolerance exits non-zero and names the value. The tier scenario runs
the five TIER01 stages beside the JOINT04 chain and judges ``full_tier_minus_full``.
The ``tier_entry`` scenario (``--scenario tier_entry``, pinned in the tier sample's
``expected_entry.json``) is the ARMS01 Arm 1 rehearsal: the same sample with the
features stage's entry/level block enabled, fitting ``full_tier`` and ``full_tier_entry``
and judging ``full_tier_entry_minus_full_tier``.
The ``current`` scenario (``--scenario current``, pinned in ``expected_current.json``)
runs the ``tier_entry`` chain as the previous version and then the current Alcaraz on its
run root: ``tennislab current table``, ``fit`` and ``pool`` with ``configs/current/
sample_*.json``. It is judged on the table's shape, each window's candidate and slope,
and each season's mean all-tier and current forecast, not on a score.

``--pin`` rewrites ``expected.json`` from the run instead of comparing; it is the only
way the pinned values change, and the sample README says which environment they were
pinned on.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tennislab import __version__
from tennislab.chain.common import ChainError
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache

POOLED_COHORT = "primary_priced"
DEFAULT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Scenario:
    """One committed sample and where its reproduction runs and reports."""

    name: str
    sample_dir: Path
    chain_config: Path
    workspace: Path
    report_dir: Path
    pooled_models: tuple[str, ...]
    # A scenario that reuses another scenario's sample pins its own headline file.
    expected_name: str = "expected.json"
    # The current Alcaraz's step configurations, run after the chain (table, fit, pool).
    current_configs: tuple[Path, ...] = ()

    @property
    def expected(self) -> Path:
        return self.sample_dir / self.expected_name


SCENARIOS = {
    "base": Scenario(
        "base",
        Path("data", "sample"),
        Path("configs", "chains", "sample_atp.json"),
        Path("data", "runs", "reproduce_small"),
        Path("work", "sample_atp", "run", "report"),
        ("selected/hgb/base", "selected/hgb/full", "market/calibrated_ps"),
    ),
    "tier": Scenario(
        "tier",
        Path("data", "sample_tier"),
        Path("configs", "chains", "sample_atp_tier.json"),
        Path("data", "runs", "reproduce_small_tier"),
        Path("work", "sample_atp_tier", "run", "report"),
        (
            "selected/hgb/base",
            "selected/hgb/full",
            "selected/hgb/base_tier",
            "selected/hgb/full_tier",
            "selected/hgb/full_tier_noqual",
            "market/calibrated_ps",
        ),
    ),
    # ARMS01 Arm 1 rehearsal: the tier sample with the features stage's entry/level
    # block enabled and the `full_tier_entry` bundle fitted beside `full_tier` (and
    # `base`, which the pipeline's shared-base records require structurally).  The
    # `full_tier` pooled log loss must equal the tier scenario's pinned value: the
    # appended block changes nothing about the bundles that do not read it.
    "tier_entry": Scenario(
        "tier_entry",
        Path("data", "sample_tier"),
        Path("configs", "chains", "sample_atp_tier_entry.json"),
        Path("data", "runs", "reproduce_small_tier_entry"),
        Path("work", "sample_atp_tier_entry", "run", "report"),
        (
            "selected/hgb/base",
            "selected/hgb/full_tier",
            "selected/hgb/full_tier_entry",
            "market/calibrated_ps",
        ),
        expected_name="expected_entry.json",
    ),
    # The current Alcaraz on the tier_entry run: the all-tier table, the all-tier model
    # and the pool, judged on forecasts and selections rather than on the chain's report.
    "current": Scenario(
        "current",
        Path("data", "sample_tier"),
        Path("configs", "chains", "sample_atp_tier_entry.json"),
        Path("data", "runs", "reproduce_small_current"),
        Path("work", "sample_atp_tier_entry", "run", "report"),
        (),
        expected_name="expected_current.json",
        current_configs=(
            Path("configs", "current", "sample_table.json"),
            Path("configs", "current", "sample_alltier.json"),
            Path("configs", "current", "sample_pool.json"),
        ),
    ),
}
CURRENT_STEPS = ("table", "fit", "pool")


class ReproductionError(ChainError):
    """The sample chain did not run, or its headline differs from the pinned values."""


def repository_root(scenario: Scenario) -> Path:
    """The current directory, which must hold the sample and its chain config."""
    root = Path.cwd()
    for required in (scenario.sample_dir, scenario.chain_config, *scenario.current_configs):
        if not (root / required).exists():
            raise ReproductionError(
                f"run from the repository root: {required} not found under {root}"
            )
    return root


def prepare_workspace(root: Path, scenario: Scenario) -> Path:
    """A fresh workspace holding a copy of the sample and of its chain config."""
    workspace = root / scenario.workspace
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(root / scenario.sample_dir, workspace / scenario.sample_dir)
    (workspace / scenario.chain_config).parent.mkdir(parents=True)
    shutil.copyfile(root / scenario.chain_config, workspace / scenario.chain_config)
    for config in scenario.current_configs:
        (workspace / config).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / config, workspace / config)
    return workspace


def run_chain(workspace: Path, scenario: Scenario) -> dict[str, float]:
    """Drive the chain in this process; stages run as subprocesses inside the workspace."""
    from tennislab.chain import runner

    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    timings: dict[str, float] = {}
    try:
        config = str(workspace / scenario.chain_config)
        for label, argv in (
            ("write-configs", ["write-configs", "--config", config]),
            ("dry-run", ["dry-run", "--config", config]),
            ("run", ["run", "--include-report", "--config", config]),
        ):
            started = time.monotonic()
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                status = runner.main(argv)
            timings[label] = time.monotonic() - started
            print(f"reproduce-small: {label} finished in {timings[label]:.1f}s", flush=True)
            if status != 0:
                raise ReproductionError(f"chain {label} exited {status}:\n{captured.getvalue()}")
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()
    return timings


def run_current(workspace: Path, scenario: Scenario) -> dict[str, float]:
    """The current Alcaraz's steps on the chain's run root, in this process."""
    from tennislab.alltier import stages
    from tennislab.chain.common import read_config

    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    timings: dict[str, float] = {}
    try:
        for step, config in zip(CURRENT_STEPS, scenario.current_configs, strict=True):
            started = time.monotonic()
            stages.STEPS[step](read_config(workspace / config))
            timings[step] = time.monotonic() - started
            print(f"reproduce-small: current {step} finished in {timings[step]:.1f}s", flush=True)
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = previous
        reset_workspace_cache()
    return timings


def current_headline(workspace: Path, scenario: Scenario) -> dict[str, Any]:
    """The table's shape, every window's pick and each season's mean forecasts."""
    from tennislab.chain.common import read_config

    sections = [read_config(workspace / config) for config in scenario.current_configs]
    table_dir = workspace / sections[0]["table"]["output_dir"]
    fit_dir = workspace / sections[1]["alltier"]["output_dir"]
    pool_dir = workspace / sections[2]["pool"]["output_dir"]
    table = json.loads((table_dir / "summary.json").read_text(encoding="utf-8"))
    picks = json.loads((fit_dir / "picks.json").read_text(encoding="utf-8"))
    pooled = json.loads((pool_dir / "summary.json").read_text(encoding="utf-8"))
    means: dict[str, dict[str, Any]] = {}
    for year in sorted(picks):
        entry: dict[str, Any] = {}
        for name in ("alltier", "current"):
            with (pool_dir / name / f"{year}.csv").open(newline="", encoding="utf-8") as handle:
                values = [float(row["p_a_wins"]) for row in csv.DictReader(handle)]
            entry["n"] = len(values)
            entry[f"mean_{name}"] = sum(values) / len(values)
        means[year] = entry
    return {
        "table_rows": table["rows"],
        "table_rows_by_tier": table["rows_by_tier"],
        "table_columns": table["columns"],
        "picks": {
            year: {w: {"candidate": d["candidate"], "slope": d["slope"]} for w, d in by.items()}
            for year, by in picks.items()
        },
        "targets_without_alltier_row": pooled["targets_without_alltier_row"],
        "forecasts": means,
    }


def compare_nested(observed: Any, expected: Any, tolerance: float, name: str = "") -> list[str]:
    """Every value of ``expected`` (recursively) that ``observed`` does not reproduce."""
    if isinstance(expected, dict):
        if not isinstance(observed, dict):
            return [f"{name}: observed {observed!r}, pinned an object"]
        problems: list[str] = []
        for key, want in expected.items():
            problems += compare_nested(
                observed.get(key), want, tolerance, f"{name}.{key}".lstrip(".")
            )
        return problems
    if isinstance(expected, float):
        if not isinstance(observed, int | float) or abs(float(observed) - expected) > tolerance:
            return [f"{name}: observed {observed!r}, pinned {expected!r} (tolerance {tolerance})"]
        return []
    return [] if observed == expected else [f"{name}: observed {observed!r}, pinned {expected!r}"]


def headline(workspace: Path, scenario: Scenario) -> dict[str, Any]:
    """The numbers the reproduction is judged on, read from the report stage."""
    report = workspace / scenario.report_dir
    primary = json.loads((report / "primary.json").read_text(encoding="utf-8"))
    pooled: dict[str, float] = {}
    with (report / "pooled_metrics.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["cohort"] == POOLED_COHORT and row["model_id"] in scenario.pooled_models:
                pooled[row["model_id"]] = float(row["log_loss_match_weighted"])
    missing = sorted(set(scenario.pooled_models) - set(pooled))
    if missing:
        raise ReproductionError(f"pooled_metrics.csv lacks {missing} on {POOLED_COHORT}")
    return {
        "primary_contrast": primary["fixed_prediction_bootstrap"]["contrast_id"],
        "n": int(primary["n"]),
        "equal_year_log_loss_delta": float(primary["equal_year_log_loss_delta"]),
        "match_weighted_log_loss_delta": float(primary["match_weighted_log_loss_delta"]),
        "pooled_log_loss_match_weighted": {"cohort": POOLED_COHORT, **pooled},
    }


def compare(observed: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Every pinned value that the observed headline does not reproduce."""
    tolerance = float(expected.get("tolerance", DEFAULT_TOLERANCE))
    problems: list[str] = []

    def check(name: str, got: Any, want: Any) -> None:
        if isinstance(want, float):
            if not isinstance(got, int | float) or abs(float(got) - want) > tolerance:
                problems.append(
                    f"{name}: observed {got!r}, pinned {want!r} (tolerance {tolerance})"
                )
        elif got != want:
            problems.append(f"{name}: observed {got!r}, pinned {want!r}")

    for name in (
        "primary_contrast",
        "n",
        "equal_year_log_loss_delta",
        "match_weighted_log_loss_delta",
    ):
        check(name, observed.get(name), expected.get(name))
    pinned_pooled = expected.get("pooled_log_loss_match_weighted", {})
    observed_pooled = observed.get("pooled_log_loss_match_weighted", {})
    for name, want in pinned_pooled.items():
        check(f"pooled_log_loss_match_weighted.{name}", observed_pooled.get(name), want)
    return problems


def pin_document(observed: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    import numpy
    import scipy
    import sklearn

    source = "tennislab reproduce-small --pin"
    if scenario.name != "base":
        source += f" --scenario {scenario.name}"
    return {
        **observed,
        "tolerance": DEFAULT_TOLERANCE,
        "pinned_on": {
            "environment": "uv.lock",
            "package_version": __version__,
            "python": sys.version.split()[0],
            "numpy": numpy.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "source": source,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tennislab reproduce-small", description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="base",
        help="which committed sample to reproduce (default: base)",
    )
    parser.add_argument(
        "--pin",
        action="store_true",
        help="write the sample's expected.json from this run instead of comparing against it",
    )
    args = parser.parse_args(argv)
    scenario = SCENARIOS[args.scenario]
    try:
        root = repository_root(scenario)
        workspace = prepare_workspace(root, scenario)
        started = time.monotonic()
        run_chain(workspace, scenario)
        if scenario.current_configs:
            run_current(workspace, scenario)
            observed = current_headline(workspace, scenario)
        else:
            observed = headline(workspace, scenario)
        elapsed = time.monotonic() - started
        if args.pin:
            document = pin_document(observed, scenario)
            (root / scenario.expected).write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"reproduce-small: pinned {scenario.expected} after {elapsed:.1f}s")
            print(json.dumps(observed, indent=2, sort_keys=True))
            return 0
        expected_path = root / scenario.expected
        if not expected_path.is_file():
            raise ReproductionError(f"no pinned values at {expected_path}; run with --pin first")
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        if scenario.current_configs:
            pinned = {
                k: v for k, v in expected.items() if k not in ("tolerance", "pinned_on", "source")
            }
            problems = compare_nested(
                observed, pinned, float(expected.get("tolerance", DEFAULT_TOLERANCE))
            )
        else:
            problems = compare(observed, expected)
        print(json.dumps(observed, indent=2, sort_keys=True))
        if problems:
            print("reproduce-small: FAIL, the pinned headline was not reproduced:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        if scenario.current_configs:
            print(f"reproduce-small: PASS, the current Alcaraz reproduced in {elapsed:.1f}s")
            return 0
        print(
            f"reproduce-small: PASS, {expected['primary_contrast']} equal-year log-loss delta "
            f"{observed['equal_year_log_loss_delta']!r} reproduced in {elapsed:.1f}s"
        )
        return 0
    except ChainError as error:
        print(f"reproduce-small: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
