"""``tennislab current``: the all-tier table, the filter tuning, the all-tier model and the
pooled current Alcaraz, one step per call (see :mod:`tennislab.alltier.stages`)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from tennislab.alltier.stages import STEPS
from tennislab.chain.common import ChainError, read_config


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tennislab current", description=__doc__)
    parser.add_argument("step", choices=tuple(STEPS))
    parser.add_argument("--config", required=True, help="the step's configuration (JSON)")
    args = parser.parse_args(argv)
    try:
        summary = STEPS[args.step](read_config(args.config))
    except ChainError as error:
        print(f"tennislab current {args.step}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    shown = {k: summary[k] for k in ("rows", "rows_by_tier", "picks", "weights") if k in summary}
    shown["outputs"] = len(summary.get("outputs", {}))
    print(json.dumps(shown, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
