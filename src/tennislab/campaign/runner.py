"""CLI for the confined forecast, barrier, report, and verification stages."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Install the single-thread numerical contract before importing modules that load NumPy,
# SciPy, or scikit-learn. This also covers the `tennislab campaign` console entry point,
# where this module is imported rather than executed with `python -m`.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from tennislab.campaign.artifacts import load_inputs
from tennislab.campaign.barrier import run_barrier, verify_barrier
from tennislab.campaign.contracts import CampaignConfig, load_campaign_config
from tennislab.campaign.forecast import run_forecast
from tennislab.campaign.report import run_report, verify_report
from tennislab.chain.common import atomic_json, resolve_output_under_root

COMMANDS = ("forecast", "barrier", "report", "verify")


class CampaignRunnerError(ValueError):
    """The requested stage cannot run inside the declared campaign boundary."""


def _output_root(config: CampaignConfig, value: str) -> Path:
    output = resolve_output_under_root(value, label="campaign output")
    if output != config.output_prefix and config.output_prefix not in output.parents:
        raise CampaignRunnerError(
            f"campaign output must be inside declared prefix {config.output_prefix}: {output}"
        )
    current = config.output_prefix
    for part in output.relative_to(config.output_prefix).parts:
        current = current / part
        if current.is_symlink():
            raise CampaignRunnerError(f"campaign output passes through symlink: {current}")
    return output


def _write_failure(output: Path | None, command: str, error: Exception) -> None:
    if output is None:
        return
    directory = output / "failures"
    directory.mkdir(parents=True, exist_ok=True)
    index = 1
    while (directory / f"{command}_{index:03d}.json").exists():
        index += 1
    atomic_json(
        directory / f"{command}_{index:03d}.json",
        {
            "status": "failed",
            "command": command,
            "error": {"type": type(error).__name__, "message": str(error)},
            "preserved_for_review": True,
        },
    )


def verify_run(config: CampaignConfig, output: Path) -> dict[str, Any]:
    load_inputs(config)
    barrier = verify_barrier(config, output)
    report_status = "not_run"
    report_artifacts = 0
    report = verify_report(config, output)
    if report is not None:
        report_artifacts = len(report["artifacts"])
        report_status = "verified"
    return {
        "schema": "campaign_verify/v1",
        "stage": "verify",
        "status": "PASS",
        "campaign_id": config.document["campaign_id"],
        "config_sha256": config.sha256,
        "forecast_tree_sha256": barrier["forecast_tree_sha256"],
        "barrier_verified": True,
        "report_status": report_status,
        "report_artifacts_verified": report_artifacts,
        "scientific_validity_established": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--execute-frozen-real",
        action="store_true",
        help="acknowledge a separately reviewed empirical freeze; synthetic runs do not use this",
    )
    args = parser.parse_args(argv)
    output: Path | None = None
    try:
        config = load_campaign_config(args.config)
        output = _output_root(config, args.output)
        if config.document["execution_scope"] == "frozen_real_inputs":
            if not args.execute_frozen_real:
                raise CampaignRunnerError("real campaign forecast requires --execute-frozen-real")
            if config.document.get("empirical_freeze_status") != "independently_reviewed_complete":
                raise CampaignRunnerError("real campaign remains blocked before empirical freeze")
        if args.command == "forecast":
            result = run_forecast(config, output)
        elif args.command == "barrier":
            result = run_barrier(config, output)
        elif args.command == "report":
            result = run_report(config, output)
        else:
            result = verify_run(config, output)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as error:
        _write_failure(output, args.command, error)
        print(f"campaign {args.command} failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
