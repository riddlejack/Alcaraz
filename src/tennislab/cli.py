"""`tennislab` command line: the entry points named in the rebuild plan.

Every subcommand is a thin wrapper over a pure function in the package. Subcommands
that are not yet ported say so and exit non-zero rather than pretending.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tennislab import __version__

PORTED: dict[str, str] = {}
PLANNED = ("panel", "features", "fit", "report", "update", "forecast", "verify")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tennislab", description=__doc__)
    parser.add_argument("--version", action="version", version=f"tennislab {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "reproduce-small", help="reproduce one headline number from the committed sample"
    )
    for name in PLANNED:
        subparsers.add_parser(name, help=f"{name} (not yet ported)")
    return parser


def reproduce_small() -> int:
    print("tennislab reproduce-small: rebuild in progress; no sample reproduction is wired yet.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "reproduce-small":
        return reproduce_small()
    print(f"tennislab {args.command}: not yet ported", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
