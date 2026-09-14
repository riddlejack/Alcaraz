"""``tennislab reproduce-small``: run the committed synthetic sample chain and check it.

The sample under ``data/sample`` is fully synthetic (see its README). This command copies
it into a fresh workspace under ``data/runs/reproduce_small/``, drives the chain from
``rule_mapping`` to ``report`` through :mod:`tennislab.chain.runner` (``write-configs``,
``dry-run``, ``run --include-report``), and compares the report's headline numbers with
the values pinned in ``data/sample/expected.json``. Any mismatch beyond the pinned
tolerance exits non-zero and names the value.

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
from pathlib import Path
from typing import Any

from tennislab import __version__
from tennislab.chain.common import ChainError
from tennislab.config import WORKSPACE_ENVIRONMENT_VARIABLE, reset_workspace_cache

SAMPLE_DIR = Path("data", "sample")
CHAIN_CONFIG = Path("configs", "chains", "sample_atp.json")
EXPECTED = SAMPLE_DIR / "expected.json"
WORKSPACE = Path("data", "runs", "reproduce_small")
REPORT_DIR = Path("work", "sample_atp", "run", "report")
POOLED_COHORT = "primary_priced"
POOLED_MODELS = ("selected/hgb/base", "selected/hgb/full", "market/calibrated_ps")
DEFAULT_TOLERANCE = 1e-9


class ReproductionError(ChainError):
    """The sample chain did not run, or its headline differs from the pinned values."""


def repository_root() -> Path:
    """The current directory, which must hold the sample and its chain config."""
    root = Path.cwd()
    for required in (SAMPLE_DIR, CHAIN_CONFIG):
        if not (root / required).exists():
            raise ReproductionError(
                f"run from the repository root: {required} not found under {root}"
            )
    return root


def prepare_workspace(root: Path) -> Path:
    """A fresh workspace holding a copy of the sample and of its chain config."""
    workspace = root / WORKSPACE
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(root / SAMPLE_DIR, workspace / SAMPLE_DIR)
    (workspace / CHAIN_CONFIG).parent.mkdir(parents=True)
    shutil.copyfile(root / CHAIN_CONFIG, workspace / CHAIN_CONFIG)
    return workspace


def run_chain(workspace: Path) -> dict[str, float]:
    """Drive the chain in this process; stages run as subprocesses inside the workspace."""
    from tennislab.chain import runner

    previous = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
    os.environ[WORKSPACE_ENVIRONMENT_VARIABLE] = str(workspace)
    reset_workspace_cache()
    timings: dict[str, float] = {}
    try:
        config = str(workspace / CHAIN_CONFIG)
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


def headline(workspace: Path) -> dict[str, Any]:
    """The numbers the reproduction is judged on, read from the report stage."""
    report = workspace / REPORT_DIR
    primary = json.loads((report / "primary.json").read_text(encoding="utf-8"))
    pooled: dict[str, float] = {}
    with (report / "pooled_metrics.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["cohort"] == POOLED_COHORT and row["model_id"] in POOLED_MODELS:
                pooled[row["model_id"]] = float(row["log_loss_match_weighted"])
    missing = sorted(set(POOLED_MODELS) - set(pooled))
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


def pin_document(observed: dict[str, Any]) -> dict[str, Any]:
    import numpy
    import scipy
    import sklearn

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
        "source": "tennislab reproduce-small --pin",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tennislab reproduce-small", description=__doc__)
    parser.add_argument(
        "--pin",
        action="store_true",
        help="write data/sample/expected.json from this run instead of comparing against it",
    )
    args = parser.parse_args(argv)
    try:
        root = repository_root()
        workspace = prepare_workspace(root)
        started = time.monotonic()
        run_chain(workspace)
        observed = headline(workspace)
        elapsed = time.monotonic() - started
        if args.pin:
            document = pin_document(observed)
            (root / EXPECTED).write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"reproduce-small: pinned {EXPECTED} after {elapsed:.1f}s")
            print(json.dumps(observed, indent=2, sort_keys=True))
            return 0
        expected_path = root / EXPECTED
        if not expected_path.is_file():
            raise ReproductionError(f"no pinned values at {expected_path}; run with --pin first")
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        problems = compare(observed, expected)
        print(json.dumps(observed, indent=2, sort_keys=True))
        if problems:
            print("reproduce-small: FAIL, the pinned headline was not reproduced:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
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
