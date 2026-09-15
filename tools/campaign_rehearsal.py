"""Prepare the deterministic Lane E public-interface rehearsal workspace."""

from __future__ import annotations

import argparse
from pathlib import Path

from tennislab.campaign.synthetic import prepare_rehearsal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="new workspace-relative rehearsal directory")
    parser.add_argument(
        "--design",
        default="docs/CAMPAIGN_E_V1.md",
        help="workspace-relative reviewed implementation contract",
    )
    parser.add_argument("--tour", choices=("ATP", "WTA"), default="ATP")
    args = parser.parse_args()
    config = prepare_rehearsal(Path(args.root), Path(args.design), tour=args.tour)
    print(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
