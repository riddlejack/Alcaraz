"""Map committed native WTA forecasts to the accepted WTA01 panel orientation.

``native_forecasts.csv`` gives ``p_a_native`` for the smaller source ID. The panel's player
A is ``a_source_id``: ``p_a_wins = p_a_native`` when A is the canonical player, else
``1 - p_a_native`` -- the accepted WTA 2024 ``paired_rows.csv`` ``external_p_a``
convention. With ``--paired-rows`` the output is copied from the accepted paired rows'
``external_p_a`` and must equal this mapping of the same committed forecasts, string for
string. Only ``match_id``, ``a_source_id``, ``b_source_id`` (panel) and ``match_id``,
``external_p_a`` (paired rows) are read; no outcome column is kept and nothing is scored.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def columns(path: Path, names: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Only the named columns of a CSV; every other column is discarded unparsed."""
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = [header.index(name) for name in names]
        return [tuple(row[i] for i in index) for row in reader]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="controller output directory")
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--membership", type=Path, required=True, help="target_membership.txt")
    parser.add_argument("--panel", type=Path, required=True, help="WTA01 prepare_panel/panel.csv")
    parser.add_argument("--paired-rows", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    commitment_path = run / "FORECAST_COMMITMENT.json"
    commitment = json.loads(commitment_path.read_text())
    verification = json.loads(args.verification.read_text())
    if verification.get("status") != "PASS" or verification.get("commitment_sha256") != digest(
        commitment_path
    ):
        raise ValueError("forecast commitment is not verified")
    forecasts_path = run / "forecast" / "native_forecasts.csv"
    if digest(forecasts_path) != commitment["forecast_sha256"]["native_forecasts.csv"]:
        raise ValueError("native forecasts differ from the commitment")
    membership = args.membership.read_text().splitlines()
    if len(membership) != len(set(membership)):
        raise ValueError("duplicate membership key")
    panel = {}
    for key, a_id, b_id in columns(args.panel, ("match_id", "a_source_id", "b_source_id")):
        if key in panel:
            raise ValueError("duplicate panel key: " + key)
        panel[key] = (int(a_id), int(b_id))
    mapped: dict[str, str] = {}
    flipped = 0
    for key, canonical, probability, status in columns(
        forecasts_path, ("match_id", "canonical_a_source_id", "p_a_native", "native_status")
    ):
        a_id, b_id = panel[key]
        if int(canonical) != min(a_id, b_id):
            raise ValueError("canonical orientation differs from the panel: " + key)
        if status != "native":
            raise ValueError("reason-coded fallback row needs the scoring-stage fallback: " + key)
        p = float(probability)
        if not 0 <= p <= 1:
            raise ValueError("native probability out of range: " + key)
        if a_id != int(canonical):
            p = 1 - p
            flipped += 1
        if key in mapped:
            raise ValueError("duplicate forecast key: " + key)
        mapped[key] = str(p)
    if set(mapped) != set(membership):
        raise ValueError("forecast keys differ from the frozen target membership")
    source = "native_forecasts_mapped"
    output = mapped
    if args.paired_rows is not None:
        paired = dict(columns(args.paired_rows, ("match_id", "external_p_a")))
        if paired != mapped:
            raise ValueError("accepted paired rows differ from the mapped committed forecasts")
        source = "accepted_paired_rows_external_p_a"
        output = paired
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["match_id", "p_a_wins"])
        for key in sorted(output):
            writer.writerow([key, output[key]])
    receipt = {
        "status": "mapped_no_scores",
        "source": source,
        "orientation": "WTA01 panel a_source_id; p_a_native complemented when A is not canonical",
        "rows": len(output),
        "flipped_rows": flipped,
        "output_sha256": digest(args.output),
        "inputs": {
            str(p): digest(p)
            for p in [forecasts_path, commitment_path, args.membership.resolve(), args.panel]
            + ([args.paired_rows] if args.paired_rows else [])
        },
        "columns_read": {
            "panel": ["match_id", "a_source_id", "b_source_id"],
            "paired_rows": ["match_id", "external_p_a"] if args.paired_rows else [],
        },
    }
    with args.output.with_name(args.output.stem + "_receipt.json").open("x") as handle:
        handle.write(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
