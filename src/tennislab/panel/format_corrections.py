"""Apply the hash-bound format metadata corrections to a derived panel, per tour.

Stage ``format_corrections``, both tours. Base revision:
``references/WTA02_models/apply_format_corrections.py``, a superset of
``references/TIER01_models/apply_format_corrections.py`` -- the ATP branch is identical
between the copies and the WTA02 copy adds the ``tour`` switch and :func:`run_wta`.
Nothing had to be merged back from the TIER01 copy.

``tour = "ATP"`` applies CONFIRM2026's four named 2007/2012 ``best_of`` corrections with
every guard unchanged: SR02's input panel is ``prepare_panel``'s output with four
``best_of`` values corrected from 5 to 3, and ``best_of`` feeds the SR02 match-format
rule key and the ``context_best_of_5`` feature. ``tour = "WTA"`` declares **no**
correction and verifies instead -- the WTA mirror writes ``best_of = 3`` on every
tour-level row -- so the stage copies the panel through and refuses any row that is not
best-of-three rather than correcting one.

``CASE_IDS`` stays a literal: the four corrected rows are named, dated evidence about
four specific matches, not a parameter, and every guard on them is unchanged. A parent
panel that does not contain all four rows, or whose values do not match the asserted
ones, is refused.

What changed from the archive revision: paths resolve through the workspace instead of
a repository root computed from the source file. Nothing is added to the manifest: the
archive recorded no code receipt here and no config field pins a module, so the manifest
is the archive's bytes.

RESERVED WINDOW. Run against an extended panel this program copies 2025/2026 rows
through unchanged; it is downstream of the panel build, which is the exposure event.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_json,
    read_config,
    read_csv_rows,
    relative_to_root,
    require_hash,
    resolve_under_root,
    sha256,
)

DEFAULT_PARENT = "data/raw/MULTI01/prepare/attempt_003/panel.csv"
DEFAULT_PARENT_HASH = "026f95589c5fe891ad67b643efa1184b33a53139ab4860f9b12e2acd41946c47"
DEFAULT_PROPOSALS = "data/raw/SR02/format_cases/correction_proposals.csv"
DEFAULT_PROPOSAL_HASH = "8d0f13cea5c89d1e87d8cdf5d4f6a3a6bbb34c3fae3c157051b0798e5df425d5"
# Four named 2007/2012 matches. Evidence about specific rows, never a parameter.
CASE_IDS = {"2007-496/5", "2007-533/6", "2007-506/533", "2012-319/5"}


def run_wta(output: Path, document: dict[str, Any]) -> dict[str, Any]:
    """No declared correction; verify best-of-three and copy the panel through."""
    section = document.get("format_corrections", document)
    parent_entry = section["parent_panel"]
    parent = resolve_under_root(parent_entry["path"], label="parent_panel")
    parent_hash = require_hash(parent, parent_entry.get("sha256"), label="parent_panel")
    if output.exists() and any(output.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    offending: list[str] = []
    with (
        parent.open(newline="", encoding="utf-8") as handle,
        (output / "panel.csv").open("w", newline="", encoding="utf-8") as target,
    ):
        reader = csv.DictReader(handle)
        writer = csv.DictWriter(target, fieldnames=reader.fieldnames)
        writer.writeheader()
        count = 0
        for row in reader:
            count += 1
            if row["best_of"] != "3":
                offending.append(f"{row['source_key']}:best_of={row['best_of']}")
            writer.writerow(row)
    if offending:
        raise ChainError(
            "WTA panel rows are not best-of-three, which the WTA rule rows assume: "
            f"{offending[:10]}"
        )
    declared = section.get("parent_panel_rows")
    if declared is not None and int(declared) != count:
        raise ChainError(f"parent panel row count differs: {count} != {declared}")
    result = {
        "id": "WTA01-format-corrections",
        "tour": "WTA",
        "status": "no_declared_correction_best_of_three_verified",
        "panel_path": relative_to_root(output / "panel.csv"),
        "panel_sha256": sha256(output / "panel.csv"),
        "rows": count,
        "parent_panel": relative_to_root(parent),
        "verified_parent_sha256": parent_hash,
        "changes": [],
        "verification": "every panel row carries best_of = 3; a row that did not would refuse the stage",
        "limits": [
            "No WTA format-correction evidence exists in this repository and none was invented.",
            "A tennis-data Best of cell disagreeing with the mirror stays a recorded "
            "disagreement (join best_of_agreement), not a panel edit.",
        ],
    }
    atomic_json(output / "manifest.json", result)
    print(
        json.dumps(
            {"rows": count, "corrections": 0, "panel_sha256": result["panel_sha256"]},
            sort_keys=True,
        )
    )
    return result


def run(output: Path, document: dict[str, Any] | None = None) -> dict[str, Any]:
    if str((document or {}).get("tour", "ATP")).upper() == "WTA":
        return run_wta(output, document or {})
    section = (document or {}).get("format_corrections", document or {})
    parent_entry = section.get("parent_panel") or {
        "path": DEFAULT_PARENT,
        "sha256": DEFAULT_PARENT_HASH,
    }
    proposals_entry = section.get("correction_proposals") or {
        "path": DEFAULT_PROPOSALS,
        "sha256": DEFAULT_PROPOSAL_HASH,
    }
    parent = resolve_under_root(parent_entry["path"], label="parent_panel")
    proposals = resolve_under_root(proposals_entry["path"], label="correction_proposals")
    parent_hash = require_hash(parent, parent_entry.get("sha256"), label="parent_panel")
    require_hash(proposals, proposals_entry.get("sha256"), label="correction_proposals")

    _, case_rows = read_csv_rows(proposals)
    if len(case_rows) != 4 or {row["source_key"] for row in case_rows} != CASE_IDS:
        raise ChainError("unexpected correction identities")
    cases = {row["source_key"]: row for row in case_rows}

    if output.exists() and any(output.iterdir()):
        raise ChainError(f"refusing to overwrite a nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    changes: list[dict[str, str]] = []
    seen: set[str] = set()
    with (
        parent.open(newline="", encoding="utf-8") as handle,
        (output / "panel.csv").open("w", newline="", encoding="utf-8") as target,
    ):
        reader = csv.DictReader(handle)
        writer = csv.DictWriter(target, fieldnames=reader.fieldnames)
        writer.writeheader()
        count = 0
        for row in reader:
            count += 1
            key = row["source_key"]
            if key in cases:
                case = cases[key]
                if key in seen:
                    raise ChainError(f"duplicate correction row: {key}")
                checks = (
                    row["best_of"] == case["assert_before_best_of"] == "5",
                    case["replacement_best_of"] == "3",
                    row["source_file_sha256"] == case["panel_source_file_sha256"],
                    row["source_line_number"] == case["panel_source_line_number"],
                    row["match_date"] == case["match_date"],
                    row["round"] == case["round"],
                )
                if not all(checks):
                    raise ChainError(f"correction guard failed: {key}")
                row["best_of"] = "3"
                seen.add(key)
                changes.append(
                    {
                        "source_key": key,
                        "field": "best_of",
                        "before": "5",
                        "after": "3",
                        "evidence": relative_to_root(proposals),
                    }
                )
            writer.writerow(row)
    if seen != CASE_IDS:
        raise ChainError(f"not every correction applied: missing {sorted(CASE_IDS - seen)}")
    declared = section.get("parent_panel_rows")
    if declared is not None and int(declared) != count:
        raise ChainError(f"parent panel row count differs: {count} != {declared}")
    result = {
        "id": "CONFIRM2026-format-corrections",
        "status": "four_guarded_format_metadata_corrections",
        "panel_path": relative_to_root(output / "panel.csv"),
        "panel_sha256": sha256(output / "panel.csv"),
        "rows": count,
        "parent_panel": relative_to_root(parent),
        "verified_parent_sha256": parent_hash,
        "correction_proposals": relative_to_root(proposals),
        "correction_proposals_sha256": sha256(proposals),
        "changes": changes,
        "all_other_fields": (
            "Retained exactly as parent strings; parent metadata field definitions "
            "remain unchanged."
        ),
        "limits": [
            "Derived from explicit Tennis-Data Best of values with official draw identity "
            "corroboration, not pre-match announcement custody.",
            "This is only a data preparation step, not a frozen modeling experiment or a "
            "complete scoring-rule mapping.",
        ],
    }
    atomic_json(output / "manifest.json", result)
    print(
        json.dumps(
            {
                "rows": count,
                "corrections": len(changes),
                "panel_sha256": result["panel_sha256"],
            },
            sort_keys=True,
        )
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    document = read_config(args.config) if args.config else None
    output = resolve_under_root(args.output, label="output")
    if args.dry_run and str((document or {}).get("tour", "ATP")).upper() == "WTA":
        section = (document or {}).get("format_corrections", document or {})
        parent = resolve_under_root(section["parent_panel"]["path"], label="parent_panel")
        require_hash(parent, section["parent_panel"].get("sha256"), label="parent_panel")
        print(
            json.dumps(
                {"status": "dry_run_ok", "tour": "WTA", "parent_panel": relative_to_root(parent)},
                sort_keys=True,
            )
        )
        return 0
    if args.dry_run:
        section = (document or {}).get("format_corrections", document or {})
        parent_entry = section.get("parent_panel") or {
            "path": DEFAULT_PARENT,
            "sha256": DEFAULT_PARENT_HASH,
        }
        proposals_entry = section.get("correction_proposals") or {
            "path": DEFAULT_PROPOSALS,
            "sha256": DEFAULT_PROPOSAL_HASH,
        }
        parent = resolve_under_root(parent_entry["path"], label="parent_panel")
        proposals = resolve_under_root(proposals_entry["path"], label="correction_proposals")
        require_hash(parent, parent_entry.get("sha256"), label="parent_panel")
        require_hash(proposals, proposals_entry.get("sha256"), label="correction_proposals")
        print(
            json.dumps(
                {
                    "status": "dry_run_ok",
                    "parent_panel": relative_to_root(parent),
                    "correction_proposals": relative_to_root(proposals),
                },
                sort_keys=True,
            )
        )
        return 0
    run(output, document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
