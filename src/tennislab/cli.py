"""``tennislab``: the command line over the package.

Every subcommand is a thin wrapper over a function in the package; the chain commands
delegate to :mod:`tennislab.chain.runner`, which is the only process that launches
stages.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tennislab import __version__

CHAIN_COMMANDS = ("print", "write-configs", "dry-run", "run", "report", "verify")
LIVE_COMMANDS = ("update", "fixture", "forecast", "ledger", "settle")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tennislab", description=__doc__)
    parser.add_argument("--version", action="version", version=f"tennislab {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    chain = subparsers.add_parser(
        "chain", help="drive a chain run stage by stage with a hash barrier"
    )
    chain.add_argument("chain_command", choices=CHAIN_COMMANDS)
    chain.add_argument("--config", required=True, help="the chain configuration (JSON)")
    chain.add_argument("--from", dest="start")
    chain.add_argument("--to", dest="stop")
    chain.add_argument("--include-report", action="store_true")
    reproduce = subparsers.add_parser(
        "reproduce-small", help="reproduce one headline number from the committed sample"
    )
    reproduce.add_argument(
        "--scenario",
        choices=("base", "tier"),
        default="base",
        help="the committed sample to reproduce: base (data/sample) or tier (data/sample_tier)",
    )
    reproduce.add_argument(
        "--pin",
        action="store_true",
        help="write the sample's expected.json from this run instead of comparing against it",
    )
    ladder = subparsers.add_parser("report", help="reporting over completed runs")
    ladder.add_argument("--ladder", action="store_true", help="the per-tour, per-year model ladder")
    ladder.add_argument(
        "--runs",
        nargs="*",
        default=[],
        metavar="TOUR=RUN_ROOT",
        help="completed run roots, e.g. ATP=data/runs/atp_tier01/run",
    )
    for name in LIVE_COMMANDS:
        subparsers.add_parser(name, help=f"live commands: tennislab {name} --help", add_help=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in LIVE_COMMANDS:
        from tennislab.live import cli as live_cli

        return live_cli.main(argv)
    args = build_parser().parse_args(argv)
    if args.command == "chain":
        from tennislab.chain import runner

        forwarded = [args.chain_command, "--config", args.config]
        if args.start:
            forwarded += ["--from", args.start]
        if args.stop:
            forwarded += ["--to", args.stop]
        if args.include_report:
            forwarded.append("--include-report")
        return runner.main(forwarded)
    if args.command == "reproduce-small":
        from tennislab import reproduce

        forwarded = ["--scenario", args.scenario] if args.scenario != "base" else []
        return reproduce.main([*forwarded, "--pin"] if args.pin else forwarded)
    if args.command == "report":
        if not args.ladder:
            print("tennislab report: pass --ladder", file=sys.stderr)
            return 2
        from tennislab.evaluation import ladder

        forwarded: list[str] = []
        for item in args.runs:
            forwarded += ["--run", item]
        return ladder.main(forwarded)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
