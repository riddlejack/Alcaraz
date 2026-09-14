"""Wire the tier block onto the trait/latent sidecar.

Stage ``tier_block``. Ported from the archive's ``TIER01_models/tier_block.py``
(revision 2, with the same-event-qualifying ablation columns); there is no WTA02 copy.

This program measures almost nothing. ``ratings.tier_elo`` produced the tier-inclusive
Elo logits and the lower-tier experience counts, the tier SR02 replay produced the
tier-inclusive dynamic probability, and this stage joins them onto a copy of the sidecar,
forms the two signed experience differences, and computes the one quantity neither
upstream stage can: the **prior tour-level match count** behind the design's
prespecified thin-side subgroup. The sidecar keeps every column it had, in its original
order, and the ``tier_`` columns are appended after them.

What lands on the sidecar: five model inputs (``TIER_SIGNED`` and
``TIER_DYNAMIC_PROBABILITY``, the latter transformed into ``tier_dynamic_match_logit`` by
the pipeline) and twenty provenance columns, every one of which is in
``pipeline.FORBIDDEN_MODEL_COLUMNS``; :func:`verify_forbidden` recomputes the pipeline's
model column set from the feature dictionary and refuses if any of them reached it, is
missing from the frozen set, or if this module's column tuples differ from the
pipeline's. With a ``tier_noqual_dynamic`` input the ablation's probability and staleness
columns are appended too.

**The membership contract.** ``tier_dynamic_match_probability_a`` is blank exactly where
``dynamic_match_probability_a`` is blank; the program refuses otherwise, so the
aligned-primary cohort is the same set of matches with and without the tier block.

**The thin-side subgroup.** ``tier_prior_tour_matches_{a,b}`` and ``tier_thin_side`` use
the D-2 information set (prior panel rows with ``match_date <= target - 2``);
``panel_order_thin_side`` in ``summary.json`` replicates the audit's own no-lag
panel-order rule for reconciliation with its 3,883.

What changed in the port: ``runner.py`` is :mod:`tennislab.models.pipeline`, imported by
name; paths resolve through ``resolve_under_root`` and manifests record
``relative_to_root`` strings; the code receipt is ``code_receipt``. Every data output is
byte-identical to the archive's.

    python -m tennislab.features.tier_block --config <configs/tier_block.json> [--output-dir D]
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import io
import json
import os
import tempfile
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    atomic_csv,
    atomic_json,
    code_receipt,
    read_config,
    read_csv_rows,
    relative_to_root,
    require_hash,
    resolve_under_root,
    sha256,
    year_plan,
)
from tennislab.models import pipeline

# Must equal `pipeline.TIER_SIGNED` / `pipeline.TIER_DYNAMIC_SIGNED` /
# `pipeline.TIER_PROVENANCE_ONLY_COLUMNS`; `verify_forbidden` and the tests assert it.
TIER_SIGNED = (
    "tier_elo_overall_logit",
    "tier_elo_surface_logit",
    "tier_prior_matches_diff",
    "tier_prior_titles_diff",
)
TIER_DYNAMIC_SIGNED = ("tier_dynamic_match_logit",)
TIER_DYNAMIC_PROBABILITY = "tier_dynamic_match_probability_a"
TIER_PROVENANCE_ONLY_COLUMNS = (
    "tier_first_tier_a",
    "tier_first_tier_b",
    "tier_initial_offset_applied_a",
    "tier_initial_offset_applied_b",
    "tier_last_lower_match_days_a",
    "tier_last_lower_match_days_b",
    "tier_history_absent_overall_a",
    "tier_history_absent_overall_b",
    "tier_history_absent_surface_a",
    "tier_history_absent_surface_b",
    "tier_prior_matches_raw_a",
    "tier_prior_matches_raw_b",
    "tier_prior_titles_raw_a",
    "tier_prior_titles_raw_b",
    "tier_prior_tour_matches_a",
    "tier_prior_tour_matches_b",
    "tier_thin_side",
    "tier_dynamic_state_stale_days_a",
    "tier_dynamic_state_stale_days_b",
    "tier_dynamic_state_stale_days",
)
SIDECAR_COLUMNS = (*TIER_SIGNED, TIER_DYNAMIC_PROBABILITY, *TIER_PROVENANCE_ONLY_COLUMNS)
# The same-event-qualifying ablation: a second tier-inclusive dynamic logit, fed by a
# replay from which every qualifying row carried under a main draw's own tourney id was
# dropped. Elo and experience are unchanged, so `full_tier_noqual` differs from
# `full_tier` in exactly one column. These columns exist only when the chain runs the
# ablation replay.
TIER_NOQUAL_DYNAMIC_SIGNED = ("tier_noqual_dynamic_match_logit",)
TIER_NOQUAL_DYNAMIC_PROBABILITY = "tier_noqual_dynamic_match_probability_a"
TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS = (
    "tier_noqual_dynamic_state_stale_days_a",
    "tier_noqual_dynamic_state_stale_days_b",
    "tier_noqual_dynamic_state_stale_days",
)
NOQUAL_SIDECAR_COLUMNS = (TIER_NOQUAL_DYNAMIC_PROBABILITY, *TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS)

DEFAULT_PARAMETERS = {
    "lag_calendar_days": 2,
    "thin_side_prior_match_threshold": 20,
}
PRIOR_MATCH_CAP = 300
PRIOR_TITLE_CAP = 20
PANEL_FIELDS_USED = ("match_id", "match_date", "player_a", "player_b", "identity_tier")
REQUIRED_SIDECAR_FIELDS = frozenset(
    {
        "match_id",
        "match_date",
        "player_a",
        "player_b",
        "primary_target",
        "identity_tier",
        "sr02_selected_match_present",
        "dynamic_match_probability_a",
    }
)


class TierBlockError(ChainError):
    """Fail-closed join, membership or provenance error."""


def parse_iso(value: str, label: str) -> dt.date:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as error:
        raise TierBlockError(f"invalid ISO date for {label}: {value!r}") from error
    if parsed.isoformat() != value:
        raise TierBlockError(f"noncanonical ISO date for {label}: {value!r}")
    return parsed


def write_csv_gz(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> str:
    """The archive's writer: ``gzip.compress(..., mtime=0)`` of a ``\\n``-terminated CSV."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    payload = gzip.compress(buffer.getvalue().encode("utf-8"), mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    with os.fdopen(handle, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return sha256(path)


# ------------------------------------------------------------------ prior tour history


def load_panel(path: Path) -> list[dict[str, str]]:
    """Stream the panel and keep only the five fields this stage needs."""
    kept: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = sorted(set(PANEL_FIELDS_USED) - set(reader.fieldnames or ()))
        if missing:
            raise TierBlockError(f"panel header missing fields: {missing}")
        for row in reader:
            kept.append({field: row[field] for field in PANEL_FIELDS_USED})
    if len({row["match_id"] for row in kept}) != len(kept):
        raise TierBlockError("duplicate panel match_id")
    return kept


class TourHistory:
    """Prior panel appearances per player, in reported-date order, queried by bisect."""

    def __init__(self) -> None:
        self.dates: dict[int, list[dt.date]] = collections.defaultdict(list)

    def add(self, player: int, date: dt.date) -> None:
        dates = self.dates[player]
        if dates and date < dates[-1]:
            raise TierBlockError("panel rows arrived out of reported-date order")
        dates.append(date)

    def count_through(self, player: int, cutoff: dt.date) -> int:
        dates = self.dates.get(player)
        if not dates:
            return 0
        return bisect_right(dates, cutoff)


def tour_history(panel_rows: Sequence[Mapping[str, str]]) -> TourHistory:
    history = TourHistory()
    for row in sorted(panel_rows, key=lambda item: (item["match_date"], item["match_id"])):
        date = parse_iso(row["match_date"], row["match_id"])
        for side in ("a", "b"):
            history.add(int(row[f"player_{side}"]), date)
    return history


def panel_order_thin_counts(rows: Sequence[Mapping[str, str]], threshold: int) -> dict[str, Any]:
    """The audit's own rule, replicated for reconciliation: panel order, no lag."""
    ordered = sorted(rows, key=lambda row: row["match_date"])
    prior: collections.Counter[int] = collections.Counter()
    thin_by_year: collections.Counter[int] = collections.Counter()
    rows_by_year: collections.Counter[int] = collections.Counter()
    for row in ordered:
        year = int(row["match_date"][:4])
        a, b = int(row["player_a"]), int(row["player_b"])
        rows_by_year[year] += 1
        if prior[a] < threshold or prior[b] < threshold:
            thin_by_year[year] += 1
        prior[a] += 1
        prior[b] += 1
    return {
        "rule": (
            "work/TIER01_audit/audit_crossfile_linkage.py:186-197 -- every panel row "
            "earlier in (match_date, file order) counts, with no availability lag"
        ),
        "threshold": threshold,
        "rows_by_year": dict(sorted(rows_by_year.items())),
        "thin_by_year": dict(sorted(thin_by_year.items())),
        "thin_2017_2024": sum(
            count for year, count in thin_by_year.items() if 2017 <= year <= 2024
        ),
        "rows_2017_2024": sum(
            count for year, count in rows_by_year.items() if 2017 <= year <= 2024
        ),
    }


# ------------------------------------------------------------------ the forbidden guard


def verify_forbidden(dictionary_path: Path, *, noqual: bool = False) -> dict[str, Any]:
    """Recompute the pipeline's model column set and refuse if a provenance column is in it.

    Installs the tier bundles on :mod:`tennislab.models.pipeline` (module state, as the
    archive's runner did) and also checks that this module's column tuples equal the
    pipeline's, so the program that computes the block and the one that fits it cannot
    drift apart.
    """
    dictionary = json.loads(Path(dictionary_path).read_text(encoding="utf-8"))
    bundles = ["base", "full", "base_tier", "full_tier"]
    if noqual:
        bundles.append("full_tier_noqual")
    pipeline.configure_bundles(bundles, ["hgb"])
    contract = pipeline.FeatureContract.from_dictionary(dictionary)
    model_columns = set(contract.all_columns)
    provenance = tuple(TIER_PROVENANCE_ONLY_COLUMNS)
    if noqual:
        provenance = (*provenance, *TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS)
    leaked = sorted(set(provenance) & model_columns)
    if leaked:
        raise TierBlockError(f"provenance columns reached the model column set: {leaked}")
    missing = sorted(set(provenance) - set(pipeline.FORBIDDEN_MODEL_COLUMNS))
    if missing:
        raise TierBlockError(f"provenance columns absent from FORBIDDEN_MODEL_COLUMNS: {missing}")
    expectations = [
        ("TIER_SIGNED", TIER_SIGNED),
        ("TIER_DYNAMIC_SIGNED", TIER_DYNAMIC_SIGNED),
        ("TIER_PROVENANCE_ONLY_COLUMNS", TIER_PROVENANCE_ONLY_COLUMNS),
        ("TIER_NOQUAL_DYNAMIC_SIGNED", TIER_NOQUAL_DYNAMIC_SIGNED),
        ("TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS", TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS),
    ]
    for name, expected in expectations:
        if tuple(getattr(pipeline, name)) != tuple(expected):
            raise TierBlockError(f"pipeline.{name} differs from tier_block.{name}")
    signed_full, _ = contract.model_columns("hgb", "full_tier")
    signed_base, _ = contract.model_columns("hgb", "base_tier")
    for column in (*TIER_SIGNED, *TIER_DYNAMIC_SIGNED):
        if column not in signed_full:
            raise TierBlockError(f"{column} is not in the full_tier bundle")
    if any(column in signed_base for column in TIER_DYNAMIC_SIGNED):
        raise TierBlockError("the tier dynamic logit reached base_tier, which has no dynamic block")
    report = {
        "model_columns": len(model_columns),
        "full_tier_signed_columns": len(signed_full),
        "base_tier_signed_columns": len(signed_base),
        "provenance_only_columns": list(provenance),
        "in_forbidden_model_columns": True,
        "in_model_column_set": False,
    }
    if noqual:
        signed_noqual, _ = contract.model_columns("hgb", "full_tier_noqual")
        for column in (*TIER_SIGNED, *TIER_NOQUAL_DYNAMIC_SIGNED):
            if column not in signed_noqual:
                raise TierBlockError(f"{column} is not in the full_tier_noqual bundle")
        if any(column in signed_noqual for column in TIER_DYNAMIC_SIGNED):
            raise TierBlockError("the unablated tier dynamic logit reached full_tier_noqual")
        if len(signed_noqual) != len(signed_full):
            raise TierBlockError(
                "full_tier_noqual and full_tier must differ in exactly one column, not "
                f"{len(signed_noqual)} against {len(signed_full)}"
            )
        report["full_tier_noqual_signed_columns"] = len(signed_noqual)
    return report


# ------------------------------------------------------------------ the join


def keyed_rows(path: Path, label: str) -> dict[str, dict[str, str]]:
    _, rows = read_csv_rows(path)
    by_id = {row["match_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise TierBlockError(f"duplicate {label} match_id")
    return by_id


def tier_block_row(
    row: Mapping[str, str],
    elo: Mapping[str, str],
    dynamic: Mapping[str, str] | None,
    ablated: Mapping[str, str] | None,
    *,
    history: TourHistory,
    lag: int,
    threshold: int,
    noqual: bool,
) -> tuple[dict[str, Any], dict[str, int], dict[str, int], dict[str, int], int]:
    """(block, raw_matches, raw_titles, prior_tour, thin) for one sidecar row."""
    key = row["match_id"]
    for field in ("match_date", "player_a", "player_b"):
        if row[field] != elo[field]:
            raise TierBlockError(f"sidecar/tier_elo {field} mismatch at {key}")
    target_date = parse_iso(row["match_date"], key)
    cutoff = target_date - dt.timedelta(days=lag)
    players = {side: int(row[f"player_{side}"]) for side in ("a", "b")}
    if players["a"] >= players["b"]:
        raise TierBlockError(f"non-neutral player orientation at {key}")

    raw_matches = {side: int(elo[f"tier_prior_matches_raw_{side}"]) for side in ("a", "b")}
    raw_titles = {side: int(elo[f"tier_prior_titles_raw_{side}"]) for side in ("a", "b")}
    capped_matches = {side: min(raw_matches[side], PRIOR_MATCH_CAP) for side in ("a", "b")}
    capped_titles = {side: min(raw_titles[side], PRIOR_TITLE_CAP) for side in ("a", "b")}
    for side in ("a", "b"):
        if int(elo[f"tier_prior_matches_{side}"]) != capped_matches[side]:
            raise TierBlockError(f"tier_elo capped match count disagrees at {key}")
        if int(elo[f"tier_prior_titles_{side}"]) != capped_titles[side]:
            raise TierBlockError(f"tier_elo capped title count disagrees at {key}")
    prior_tour = {side: history.count_through(players[side], cutoff) for side in ("a", "b")}
    thin = int(any(prior_tour[side] < threshold for side in ("a", "b")))

    base_probability = row["dynamic_match_probability_a"]
    tier_probability = "" if dynamic is None else dynamic["dynamic_match_probability_a"]
    if (tier_probability == "") != (base_probability == ""):
        raise TierBlockError(
            f"tier and base dynamic membership differ at {key}: base "
            f"{base_probability!r}, tier {tier_probability!r}"
        )
    stale = {
        f"tier_dynamic_state_stale_days_{suffix}": (
            "" if dynamic is None else dynamic[f"dynamic_state_stale_days_{suffix}"]
        )
        for suffix in ("a", "b")
    }
    stale["tier_dynamic_state_stale_days"] = (
        "" if dynamic is None else dynamic["dynamic_state_stale_days"]
    )
    noqual_block: dict[str, Any] = {}
    if noqual:
        noqual_probability = "" if ablated is None else ablated["dynamic_match_probability_a"]
        if (noqual_probability == "") != (base_probability == ""):
            raise TierBlockError(
                f"ablated and base dynamic membership differ at {key}: base "
                f"{base_probability!r}, ablated {noqual_probability!r}"
            )
        noqual_block[TIER_NOQUAL_DYNAMIC_PROBABILITY] = noqual_probability
        for suffix in ("a", "b"):
            noqual_block[f"tier_noqual_dynamic_state_stale_days_{suffix}"] = (
                "" if ablated is None else ablated[f"dynamic_state_stale_days_{suffix}"]
            )
        noqual_block["tier_noqual_dynamic_state_stale_days"] = (
            "" if ablated is None else ablated["dynamic_state_stale_days"]
        )

    block = {
        "tier_elo_overall_logit": elo["tier_elo_overall_logit"],
        "tier_elo_surface_logit": elo["tier_elo_surface_logit"],
        "tier_prior_matches_diff": repr(float(capped_matches["a"] - capped_matches["b"])),
        "tier_prior_titles_diff": repr(float(capped_titles["a"] - capped_titles["b"])),
        TIER_DYNAMIC_PROBABILITY: tier_probability,
        "tier_first_tier_a": elo["tier_first_tier_a"],
        "tier_first_tier_b": elo["tier_first_tier_b"],
        "tier_initial_offset_applied_a": elo["tier_initial_offset_applied_a"],
        "tier_initial_offset_applied_b": elo["tier_initial_offset_applied_b"],
        "tier_last_lower_match_days_a": elo["tier_last_lower_match_days_a"],
        "tier_last_lower_match_days_b": elo["tier_last_lower_match_days_b"],
        "tier_history_absent_overall_a": elo["tier_history_absent_overall_a"],
        "tier_history_absent_overall_b": elo["tier_history_absent_overall_b"],
        "tier_history_absent_surface_a": elo["tier_history_absent_surface_a"],
        "tier_history_absent_surface_b": elo["tier_history_absent_surface_b"],
        "tier_prior_matches_raw_a": raw_matches["a"],
        "tier_prior_matches_raw_b": raw_matches["b"],
        "tier_prior_titles_raw_a": raw_titles["a"],
        "tier_prior_titles_raw_b": raw_titles["b"],
        "tier_prior_tour_matches_a": prior_tour["a"],
        "tier_prior_tour_matches_b": prior_tour["b"],
        "tier_thin_side": thin,
        **stale,
        **noqual_block,
    }
    return block, raw_matches, raw_titles, prior_tour, thin


def run(config: Mapping[str, Any]) -> dict[str, Any]:
    section = config.get("tier_block")
    if not isinstance(section, dict):
        raise TierBlockError("configuration has no tier_block object")
    plan = year_plan(config)
    parameters = dict(DEFAULT_PARAMETERS)
    parameters.update(section.get("parameters", {}))
    lag = int(parameters["lag_calendar_days"])
    threshold = int(parameters["thin_side_prior_match_threshold"])
    if lag != 2:
        raise TierBlockError("TIER01 fixes the availability lag at 2 calendar days")
    if threshold != 20:
        raise TierBlockError("the design fixes the thin-side threshold at 20 prior matches")

    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    names = ["panel", "sidecar", "tier_elo_features", "tier_dynamic", "base_dictionary"]
    # The same-event-qualifying ablation replay, present only when the chain runs it.
    noqual = isinstance(section.get("tier_noqual_dynamic"), dict)
    if noqual:
        names.append("tier_noqual_dynamic")
    for name in names:
        entry = section[name]
        paths[name] = resolve_under_root(entry["path"], label=name)
        hashes[name] = require_hash(paths[name], entry.get("sha256") or None, label=name)
    sidecar_columns = (*SIDECAR_COLUMNS, *NOQUAL_SIDECAR_COLUMNS) if noqual else SIDECAR_COLUMNS

    forbidden = verify_forbidden(paths["base_dictionary"], noqual=noqual)

    panel_rows = load_panel(paths["panel"])
    history = tour_history(panel_rows)
    audit_style = panel_order_thin_counts(panel_rows, threshold)

    elo_by_id = keyed_rows(paths["tier_elo_features"], "tier_elo")
    dynamic_by_id = keyed_rows(paths["tier_dynamic"], "tier dynamic")
    noqual_by_id: dict[str, dict[str, str]] = {}
    if noqual:
        noqual_by_id = keyed_rows(paths["tier_noqual_dynamic"], "tier noqual dynamic")
        if set(noqual_by_id) != set(dynamic_by_id):
            raise TierBlockError(
                "the ablation replay emitted a different target set from the tier replay: "
                f"{len(noqual_by_id)} against {len(dynamic_by_id)}"
            )

    sidecar_header, sidecar_rows = read_csv_rows(paths["sidecar"])
    overlap = sorted(set(sidecar_header) & set(sidecar_columns))
    if overlap:
        raise TierBlockError(f"sidecar already carries tier columns: {overlap}")
    missing = sorted(REQUIRED_SIDECAR_FIELDS - set(sidecar_header))
    if missing:
        raise TierBlockError(f"sidecar header missing fields: {missing}")

    counters: collections.Counter[str] = collections.Counter()
    coverage: dict[int, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    augmented: list[dict[str, str]] = []
    detail: list[dict[str, Any]] = []
    thin_membership: list[dict[str, Any]] = []
    for row in sidecar_rows:
        key = row["match_id"]
        elo = elo_by_id.get(key)
        if elo is None:
            raise TierBlockError(f"sidecar row has no tier_elo row: {key}")
        block, raw_matches, raw_titles, prior_tour, thin = tier_block_row(
            row,
            elo,
            dynamic_by_id.get(key),
            noqual_by_id.get(key),
            history=history,
            lag=lag,
            threshold=threshold,
            noqual=noqual,
        )
        if set(block) != set(sidecar_columns):
            raise TierBlockError(
                "emitted tier columns differ from the declared block: "
                f"{sorted(set(block) ^ set(sidecar_columns))}"
            )
        season = parse_iso(row["match_date"], key).year
        base_probability = row["dynamic_match_probability_a"]
        augmented.append({**row, **{name: str(block[name]) for name in sidecar_columns}})
        detail.append(
            {
                "match_id": key,
                "match_date": row["match_date"],
                "season": season,
                "primary_target": row["primary_target"],
                "identity_tier": row["identity_tier"],
                "aligned_primary_candidate": int(
                    row["primary_target"] == "1"
                    and row["identity_tier"] == "primary"
                    and base_probability != ""
                ),
                **{name: block[name] for name in sidecar_columns},
            }
        )
        counters["rows"] += 1
        counters["thin_side_rows"] += thin
        counters["tier_dynamic_present"] += int(block[TIER_DYNAMIC_PROBABILITY] != "")

        if row["primary_target"] == "1" and row["identity_tier"] == "primary":
            bucket = coverage[season]
            bucket["primary_rows"] += 1
            bucket["any_side_lower_history"] += int(
                any(raw_matches[side] > 0 for side in ("a", "b"))
            )
            bucket["both_sides_lower_history"] += int(
                all(raw_matches[side] > 0 for side in ("a", "b"))
            )
            bucket["any_side_lower_title"] += int(any(raw_titles[side] > 0 for side in ("a", "b")))
            bucket["any_side_offset_applied"] += int(
                any(block[f"tier_initial_offset_applied_{side}"] in (1, "1") for side in ("a", "b"))
            )
            bucket["thin_side_rows"] += thin
            if thin:
                thin_side = "a" if prior_tour["a"] < threshold else "b"
                bucket["thin_side_with_lower_history"] += int(raw_matches[thin_side] > 0)
                thin_membership.append(
                    {
                        "match_id": key,
                        "match_date": row["match_date"],
                        "season": season,
                        "thin_side": thin_side,
                        "prior_tour_matches_a": prior_tour["a"],
                        "prior_tour_matches_b": prior_tour["b"],
                        "thin_side_lower_tier_matches": raw_matches[thin_side],
                        "aligned_primary_candidate": int(base_probability != ""),
                    }
                )
            if base_probability != "":
                bucket["aligned_primary_candidates"] += 1
                bucket["aligned_primary_thin_side"] += thin

    output_dir = resolve_under_root(section["output_dir"], label="output_dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    header = [*sidecar_header, *sidecar_columns]
    outputs = {
        "trait_latent_sidecar.csv": atomic_csv(
            output_dir / "trait_latent_sidecar.csv", header, augmented
        )
    }
    detail_fields = [
        "match_id",
        "match_date",
        "season",
        "primary_target",
        "identity_tier",
        "aligned_primary_candidate",
        *sidecar_columns,
    ]
    outputs["tier_detail.csv.gz"] = write_csv_gz(
        output_dir / "tier_detail.csv.gz", detail_fields, detail
    )
    coverage_fields = (
        "season",
        "primary_rows",
        "any_side_lower_history",
        "any_side_lower_history_share",
        "both_sides_lower_history",
        "any_side_lower_title",
        "any_side_offset_applied",
        "thin_side_rows",
        "thin_side_share",
        "thin_side_with_lower_history",
        "aligned_primary_candidates",
        "aligned_primary_thin_side",
    )

    def share(numerator: int, denominator: int) -> str:
        return repr(round(numerator / denominator, 6)) if denominator else ""

    coverage_rows = []
    for season in sorted(coverage):
        bucket = coverage[season]
        total = bucket["primary_rows"]
        coverage_rows.append(
            {
                "season": season,
                "primary_rows": total,
                "any_side_lower_history": bucket["any_side_lower_history"],
                "any_side_lower_history_share": share(bucket["any_side_lower_history"], total),
                "both_sides_lower_history": bucket["both_sides_lower_history"],
                "any_side_lower_title": bucket["any_side_lower_title"],
                "any_side_offset_applied": bucket["any_side_offset_applied"],
                "thin_side_rows": bucket["thin_side_rows"],
                "thin_side_share": share(bucket["thin_side_rows"], total),
                "thin_side_with_lower_history": bucket["thin_side_with_lower_history"],
                "aligned_primary_candidates": bucket["aligned_primary_candidates"],
                "aligned_primary_thin_side": bucket["aligned_primary_thin_side"],
            }
        )
    outputs["coverage_by_year.csv"] = atomic_csv(
        output_dir / "coverage_by_year.csv", coverage_fields, coverage_rows
    )
    thin_fields = (
        "match_id",
        "match_date",
        "season",
        "thin_side",
        "prior_tour_matches_a",
        "prior_tour_matches_b",
        "thin_side_lower_tier_matches",
        "aligned_primary_candidate",
    )
    outputs["thin_side_membership.csv"] = atomic_csv(
        output_dir / "thin_side_membership.csv", thin_fields, thin_membership
    )

    dictionary = {
        "dictionary_id": "TIER01-tier-block",
        "tier_signed_model_features": list(TIER_SIGNED),
        "tier_dynamic_model_feature": list(TIER_DYNAMIC_SIGNED),
        "tier_dynamic_sidecar_input": TIER_DYNAMIC_PROBABILITY,
        "tier_provenance_only_columns": list(TIER_PROVENANCE_ONLY_COLUMNS),
        "tier_noqual_dynamic_model_feature": list(TIER_NOQUAL_DYNAMIC_SIGNED) if noqual else [],
        "tier_noqual_dynamic_sidecar_input": TIER_NOQUAL_DYNAMIC_PROBABILITY if noqual else None,
        "tier_noqual_provenance_only_columns": (
            list(TIER_NOQUAL_PROVENANCE_ONLY_COLUMNS) if noqual else []
        ),
        "bundles": {
            "base_tier": "JOINT04 base + the four tier signed fields",
            "full_tier": "JOINT04 full + the four tier signed fields + the tier dynamic "
            "logit; both dynamic logits and both Elo pairs are kept",
            **(
                {
                    "full_tier_noqual": "full_tier with the tier dynamic logit replaced by the "
                    "one fed without same-event qualifying rows; Elo and experience unchanged"
                }
                if noqual
                else {}
            ),
        },
        "caps": {
            "prior_lower_tier_matches": PRIOR_MATCH_CAP,
            "prior_lower_tier_titles": PRIOR_TITLE_CAP,
        },
        "parameters": parameters,
        "eligibility": (
            "every tier quantity is state as of target date - 2 calendar days; the "
            "lower-tier rows carry tier_stream's declared reported date"
        ),
        "known_limits": {
            "thin_side_definition": (
                "the emitted indicator uses the D-2 prior panel count; "
                "summary.panel_order_thin_side replicates the audit's no-lag panel-order "
                "rule for reconciliation with its 3,883"
            ),
            "lower_tier_date_basis": (
                "event anchor plus tier_stream's declared offset, not a match clock"
            ),
        },
    }
    outputs["tier_dictionary.json"] = atomic_json(output_dir / "tier_dictionary.json", dictionary)

    in_window = [row for row in coverage_rows if 2017 <= int(row["season"]) <= 2024]
    summary = {
        "id": "TIER01-tier-block",
        "status": "complete",
        "artifact_kind": "sidecar_with_tier_block_no_fit_no_score",
        "year_plan": plan.as_document(),
        "parameters": parameters,
        "inputs": {
            name: {"path": relative_to_root(paths[name], label=name), "sha256": hashes[name]}
            for name in paths
        },
        "code": {
            "tier_block": code_receipt(__name__),
            "runner": code_receipt(pipeline.__name__),
        },
        "rows_written": len(augmented),
        "counters": dict(sorted(counters.items())),
        "model_columns": list(TIER_SIGNED) + list(TIER_DYNAMIC_SIGNED),
        "forbidden_check": forbidden,
        "thin_side_2017_2024": {
            "primary_rows": sum(int(row["primary_rows"]) for row in in_window),
            "thin_side_rows": sum(int(row["thin_side_rows"]) for row in in_window),
            "thin_side_with_lower_history": sum(
                int(row["thin_side_with_lower_history"]) for row in in_window
            ),
            "aligned_primary_candidates": sum(
                int(row["aligned_primary_candidates"]) for row in in_window
            ),
            "aligned_primary_thin_side": sum(
                int(row["aligned_primary_thin_side"]) for row in in_window
            ),
            "rule": "prior panel rows with match_date <= target date - 2, threshold 20",
        },
        "panel_order_thin_side": audit_style,
        "outputs": outputs,
        "limits": [
            "The tier block is appended; nothing is removed. A JOINT04 bundle reads none "
            "of these columns, which is why the reproduction stays byte-exact.",
            "tier_dynamic_match_probability_a is blank exactly where the base dynamic "
            "probability is blank, so the aligned-primary cohort is identical with and "
            "without the block.",
            "The 20 provenance columns are in runner.FORBIDDEN_MODEL_COLUMNS and must "
            "never be fitted.",
        ],
    }
    outputs["summary.json"] = atomic_json(output_dir / "summary.json", summary)
    summary["outputs"] = outputs
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    config = read_config(args.config)
    if args.output_dir is not None:
        config["tier_block"]["output_dir"] = str(args.output_dir)
    summary = run(config)
    print(
        json.dumps(
            {
                "rows_written": summary["rows_written"],
                "counters": summary["counters"],
                "thin_side_2017_2024": summary["thin_side_2017_2024"],
                "panel_order_thin_2017_2024": summary["panel_order_thin_side"]["thin_2017_2024"],
                "sidecar_sha256": summary["outputs"]["trait_latent_sidecar.csv"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
