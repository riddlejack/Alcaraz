"""The ordered command sequence for one chain run, with a hash barrier per stage.

Ported from the archive's ``run_chain.py`` (WTA02 revision, which carries the ATP
CONFIRM2026 table, plus TIER01's five tier stages). What changed: stage programs are
package modules run with ``python -m``; the repository root is the workspace; the
interpreter is the running one.

Each stage is a separate process with its own configuration, writes only into
``<run-root>/<stage>/``, and is hashed before the next stage starts. A stage refuses to
begin unless every earlier stage's recorded output hashes still verify, so a chain that
is resumed after an edit fails loudly instead of mixing artifacts. The per-stage records
are chained: each entry in ``chain_ledger.jsonl`` carries the sha256 of the previous
entry, so the ledger cannot be rewritten in the middle without detection.

``run`` stops at ``reporting_config``. ``report`` is a separate command: the only path
that runs the post-barrier stages, ``tennislab.evaluation.report`` (the only module that
scores a target year's labels) and ``sr03_component`` (the SR03 component metrics from
the calibration stage's persisted predictions). ``run --include-report`` is the
unattended end-to-end path and says so.

Decision RB14: every stage runs with an access log (``TENNISLAB_ACCESS_LOG``); the
driver derives the stage's observed outcome access from it, records it in the stage
manifest beside the declaration and fails the stage on an undeclared parse or a receipt
beyond its fold. The ``barrier`` stage scans every earlier stage directory for
metric-shaped content and refuses to freeze a run tree that carries any; ``verify``
repeats both checks.

Usage::

    python -m tennislab.chain.runner --config <chain.json> print
    python -m tennislab.chain.runner --config <chain.json> write-configs
    python -m tennislab.chain.runner --config <chain.json> dry-run
    python -m tennislab.chain.runner --config <chain.json> run [--from A --to B]
    python -m tennislab.chain.runner --config <chain.json> run --include-report
    python -m tennislab.chain.runner --config <chain.json> report
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tennislab.chain import access, barrier_scan, outcome_files
from tennislab.chain.common import (
    ChainError,
    atomic_json,
    canonical_hash,
    canonical_hash_nonempty,
    code_receipt,
    read_config,
    relative_to_root,
    resolve_output_under_root,
    resolve_under_root,
    sha256,
    year_plan,
)

LEDGER = "chain_ledger.jsonl"
STAGE_MANIFEST = "stage_manifest.json"
# Single-threaded BLAS is part of the frozen numerical contract, not a convenience.
ENVIRONMENT = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "PYTHONHASHSEED": "0",
}

# Stage name -> package module. One trunk; the tour decides which table is used.
MODULES = {
    "bridge": "tennislab.sources.bridge",
    "archive_panel": "tennislab.panel.archive_panel",
    "join": "tennislab.panel.join",
    "event_carry_forward": "tennislab.panel.crosswalk_carry",
    "prepare_panel": "tennislab.panel.prepare",
    "format_corrections": "tennislab.panel.format_corrections",
    "rule_mapping": "tennislab.panel.rules",
    "sr02_replay": "tennislab.dynamics.replay",
    "sr03_calibration": "tennislab.dynamics.calibrate",
    "rankings": "tennislab.panel.rankings",
    "edition_index": "tennislab.chronology.edition_index",
    "features": "tennislab.features.base",
    "sidecar": "tennislab.features.sidecar",
    "tier_stream": "tennislab.ratings.tier_stream",
    "tier_elo": "tennislab.ratings.tier_elo",
    "sr02_tier_replay": "tennislab.dynamics.replay",
    "sr02_tier_noqual_replay": "tennislab.dynamics.replay",
    "tier_block": "tennislab.features.tier_block",
    "predictor_config": "tennislab.chain.configs",
    "preflight": "tennislab.models.pipeline",
    "pipeline": "tennislab.models.pipeline",
    "reporting_config": "tennislab.chain.configs",
    "report": "tennislab.evaluation.report",
}
WTA_MODULES = {
    "event_carry_forward": "tennislab.panel.wta_crosswalk_carry",
    "join": "tennislab.panel.wta_join",
    "rule_mapping": "tennislab.panel.wta_rules",
}
SR03_CODE_BINDINGS = (
    "tennislab.dynamics.market",
    "tennislab.dynamics.sr02_runner",
    "tennislab.dynamics.calibrate",
)


OUTCOME_ACCESS_DECLARATIONS = ("none", "history", "fold", "target")
PROJECTION_OPENER = "tennislab.chain.labels:projected_rows"
ACCESSOR_OPENERS = frozenset(
    {"tennislab.chain.labels:selected", "tennislab.chain.labels:projected_rows"}
)


class Stage:
    """One stage: its module, its argv template and whether it has a ``--dry-run``.

    ``outcome_access`` is the stage's *declaration* (RB14): ``none`` (it may not parse
    any outcome-bearing file; hash-only reads are allowed), ``history`` (a state replay
    or panel builder that parses whole outcome files as past history), ``fold`` (a fit
    or selection stage: every parse of an outcome-bearing file must go through an
    accessor in ``chain.labels`` and every receipt must name the fold it serves and a
    ceiling before it) or ``target`` (a post-barrier stage). What the stage actually
    opened is derived from the access log and recorded beside the declaration in its
    manifest; a mismatch fails the stage.
    """

    def __init__(
        self,
        name: str,
        module: str | None,
        argv: Sequence[str],
        *,
        dry_run: bool = True,
        outcome_access: str = "none",
        note: str = "",
        inputs: Sequence[str] = (),
    ):
        if outcome_access not in OUTCOME_ACCESS_DECLARATIONS:
            raise ChainError(f"stage {name}: unknown outcome_access {outcome_access!r}")
        self.name = name
        self.module = module
        self.argv = tuple(argv)
        self.dry_run = dry_run
        self.outcome_access = outcome_access
        self.note = note
        # Chain-config fields this stage consumes as inputs on the command line rather
        # than inside its config (``edition_index``'s ``--source``, the predictor-config
        # inputs), so the declared-input assertion covers them.
        self.inputs = tuple(inputs)


def check_floor_consistency(section: Mapping[str, Any], plan: Any) -> None:
    """The SR02 emission floor and the model's history floor must agree (WTA01 fail-fast)."""
    declared = section.get("selection_year_min")
    if declared is None:
        return
    if int(declared) < int(plan.history_floor_year):
        raise ChainError(
            f"chain selection_year_min {declared} is below year_plan "
            f"history_floor_year {plan.history_floor_year}; the SR02 replay would emit "
            "rows SR03 refuses. Raise the emission floor, or lower the history floor."
        )


def tour_of(section: Mapping[str, Any]) -> str:
    """The configured tour. The only place the chain reads it."""
    value = str(section.get("tour", "ATP")).upper()
    if value not in {"ATP", "WTA"}:
        raise ChainError(f"unknown tour {value!r}; expected ATP or WTA")
    return value


def experiment_of(section: Mapping[str, Any]) -> str:
    """The configured experiment id, stamped on emitted stage configs."""
    value = str(
        section.get("experiment_id", "CONFIRM2026" if tour_of(section) == "ATP" else "WTA01")
    )
    if not value.strip() or any(character in value for character in "/\\ "):
        raise ChainError(f"invalid experiment_id {value!r}")
    return value


def module_for(name: str, tour: str) -> str:
    if tour == "WTA" and name in WTA_MODULES:
        return WTA_MODULES[name]
    return MODULES[name]


def _bridge_stage(tour: str) -> Stage:
    return Stage(
        "bridge",
        module_for("bridge", tour),
        ["--config", "{configs.bridge}", "--allow-reserved-years"],
        outcome_access="history",
        note=f"First outcome-access event: opens the {tour} reserved-season result files.",
    )


def _shared_tail(tour: str) -> list[Stage]:
    """Stages 8 onward, identical for either tour (bar the WTA unordered ranking stream)."""
    edition_argv = ["--source", "{rankings_source}", "--output-dir", "{stage_dir}"]
    if tour == "WTA":
        edition_argv.append("--unordered-source")
    return [
        Stage(
            "sr02_replay",
            module_for("sr02_replay", tour),
            ["--config", "{configs.sr02_replay}"],
            outcome_access="history",
            note="Parses the panel; SOURCE_ROW_FIELDS projects a_won out before any use.",
        ),
        Stage(
            "sr03_calibration",
            module_for("sr03_calibration", tour),
            ["run", "{configs.sr03}", "{stage_dir}"],
            dry_run=False,
            outcome_access="fold",
            note="Forecast-only: one PanelOutcomeHistory read per outer year (ceiling = outer "
            "year - 1); no score is written here (RB14).",
        ),
        Stage(
            "rankings",
            module_for("rankings", tour),
            ["build", "--output-dir", "{stage_dir}", "--config", "{configs.rankings}"],
            dry_run=False,
            outcome_access="history",
            note="Reads the pinned Sackmann archive's result files to qualify the ranking stream.",
        ),
        Stage(
            "edition_index",
            module_for("edition_index", tour),
            edition_argv,
            dry_run=False,
            inputs=("rankings_source",),
            note=""
            if tour == "ATP"
            else "The normalized WTA ranking stream is not in source date order.",
        ),
        Stage(
            "features",
            module_for("features", tour),
            ["--config", "{configs.features}"],
            dry_run=False,
            outcome_access="history",
            note="Reads the panel: past results update the Elo state under D-2; a_won is copied into labels.csv.",
        ),
        Stage(
            "sidecar",
            module_for("sidecar", tour),
            ["--config", "{configs.sidecar}"],
            dry_run=False,
            outcome_access="history",
            note="Traits plus the replayed SR02 block; parses the panel and projects it to "
            "PANEL_MEASUREMENT_FIELDS before use; never opens labels.csv.",
        ),
    ]


def _model_tail(tour: str) -> list[Stage]:
    return [
        Stage(
            "predictor_config",
            module_for("predictor_config", tour),
            [
                "predictor",
                "--year-plan",
                "{configs.year_plan}",
                "--features",
                "{features}",
                "--dictionary",
                "{dictionary}",
                "--sidecar",
                "{sidecar}",
                "--labels",
                "{labels}",
                "--design",
                "{design}",
                "--output",
                "{predictor_config}",
            ],
            dry_run=False,
            inputs=("features", "dictionary", "sidecar", "labels", "design"),
        ),
        Stage(
            "preflight",
            module_for("preflight", tour),
            ["preflight", "--config", "{predictor_config}"],
            dry_run=False,
            inputs=("predictor_config",),
        ),
        Stage(
            "pipeline",
            module_for("pipeline", tour),
            [
                "pipeline",
                "--config",
                "{predictor_config}",
                "--output",
                "{stage_dir}",
                "--execute-frozen-real",
            ],
            dry_run=False,
            outcome_access="fold",
            inputs=("predictor_config",),
            note="labels.csv through LabelHistory per fold (training_fit, "
            "past_selection_calibration, past_market_calibration); ceiling = outer year - 1.",
        ),
        Stage(
            "barrier",
            None,
            [],
            dry_run=False,
            note="No program: hashes and freezes the run tree. Timestamp it here.",
        ),
    ]


def _reporting_config_stage(section: Mapping[str, Any], tour: str) -> Stage:
    argv = [
        "reporting",
        "--predictor-config",
        "{predictor_config}",
        "--selection-complete",
        "{selection_complete}",
    ]
    # The published primary contrast, its secondaries and the bootstrap seed travel in
    # the chain config, so the frozen chain states which difference the report will
    # publish instead of leaving it to a literal inside the reporter (SCAR_TISSUE B6).
    if section.get("reporting_primary_contrast") is not None:
        argv += ["--primary-contrast", "{reporting_primary_contrast}"]
    if section.get("reporting_secondary_contrast") is not None:
        argv += ["--secondary-contrast", "{reporting_secondary_contrast}"]
    if section.get("reporting_bootstrap_seed") is not None:
        argv += ["--bootstrap-seed", "{reporting_bootstrap_seed}"]
    argv += ["--output", "{reporting_config}"]
    return Stage(
        "reporting_config",
        module_for("reporting_config", tour),
        argv,
        dry_run=False,
        inputs=("predictor_config", "selection_complete"),
    )


def _atp_stages(section: Mapping[str, Any]) -> list[Stage]:
    tour = "ATP"
    ablation = bool(section.get("tier_same_event_qualifying_ablation", False))
    tier = bool(section.get("tier_enabled", "tier_stream" in section.get("configs", {})))
    table = [
        _bridge_stage(tour),
        Stage(
            "archive_panel",
            module_for("archive_panel", tour),
            ["--config", "{configs.archive_panel}", "--output-dir", "{stage_dir}"],
            outcome_access="history",
        ),
        Stage(
            "join",
            module_for("join", tour),
            ["build", "{stage_dir}", "--config", "{configs.join}"],
            dry_run=False,
            outcome_access="history",
        ),
        # The declared event-crosswalk carry-forward follows the join (it reads the
        # join's candidates) and precedes prepare_panel (which consults the crosswalk).
        Stage(
            "event_carry_forward",
            module_for("event_carry_forward", tour),
            ["{stage_dir}", "--config", "{configs.event_carry_forward}"],
            outcome_access="history",
        ),
        Stage(
            "prepare_panel",
            module_for("prepare_panel", tour),
            ["{stage_dir}", "--config", "{configs.prepare_panel}"],
            outcome_access="history",
        ),
        Stage(
            "format_corrections",
            module_for("format_corrections", tour),
            ["{stage_dir}", "--config", "{configs.format_corrections}"],
            outcome_access="history",
        ),
        Stage(
            "rule_mapping",
            module_for("rule_mapping", tour),
            ["--config", "{configs.rule_mapping}"],
            outcome_access="history",
            note="Parses the panel for format-rule evidence; a_won is unused.",
        ),
        *_shared_tail(tour),
    ]
    if tier:
        # TIER01: the block is computed beside the JOINT04 chain, never inside it.
        table += [
            Stage(
                "tier_stream",
                module_for("tier_stream", tour),
                ["--config", "{configs.tier_stream}", "--output-dir", "{stage_dir}"],
                outcome_access="history",
                note="Qualifying/Challenger/Futures history from the pinned mirror; "
                "reads no reserved year and no run artifact.",
            ),
            Stage(
                "tier_elo",
                module_for("tier_elo", tour),
                ["--config", "{configs.tier_elo}", "--output-dir", "{stage_dir}"],
                outcome_access="history",
                note="The tier-inclusive pooled Elo and the experience counts. Reads "
                "outcomes as history under the D-2 cursor; no label is written.",
            ),
            Stage(
                "sr02_tier_replay",
                module_for("sr02_tier_replay", tour),
                ["--config", "{configs.sr02_tier_replay}"],
                outcome_access="history",
                note="The same saved SR02 paths replayed with the lower-tier feed enabled.",
            ),
            *(
                [
                    Stage(
                        "sr02_tier_noqual_replay",
                        module_for("sr02_tier_noqual_replay", tour),
                        ["--config", "{configs.sr02_tier_noqual_replay}"],
                        outcome_access="history",
                        note="The tier feed without same-event qualifying rows: the declared "
                        "ablation of the tournament-latent updating channel.",
                    )
                ]
                if ablation
                else []
            ),
            Stage(
                "tier_block",
                module_for("tier_block", tour),
                ["--config", "{configs.tier_block}"],
                dry_run=False,
                note="Appends the tier_ model and provenance columns to a copy of the sidecar.",
            ),
        ]
    table += [*_model_tail(tour), _reporting_config_stage(section, tour)]
    return table


def _wta_stages(section: Mapping[str, Any]) -> list[Stage]:
    tour = "WTA"
    table: list[Stage] = []
    if "bridge_seasons" in section:
        table.append(_bridge_stage(tour))
    table += [
        Stage(
            "archive_panel",
            module_for("archive_panel", tour),
            ["--config", "{configs.archive_panel}", "--output-dir", "{stage_dir}"],
            outcome_access="history",
            note="Reads the WTA results the composed archive (or the mirror) carries.",
        ),
        # The WTA join pairs through the crosswalk, so the carry-forward precedes it.
        Stage(
            "event_carry_forward",
            module_for("event_carry_forward", tour),
            ["{stage_dir}", "--config", "{configs.event_carry_forward}"],
            outcome_access="history",
            note="Declared rule 2: the frozen WTA crosswalk carried past 2024; a no-op below.",
        ),
        Stage(
            "join",
            module_for("join", tour),
            ["{stage_dir}", "--config", "{configs.join}"],
            outcome_access="history",
        ),
        Stage(
            "prepare_panel",
            module_for("prepare_panel", tour),
            ["{stage_dir}", "--config", "{configs.prepare_panel}"],
            outcome_access="history",
        ),
        Stage(
            "format_corrections",
            module_for("format_corrections", tour),
            ["{stage_dir}", "--config", "{configs.format_corrections}"],
            outcome_access="history",
        ),
        Stage(
            "rule_mapping",
            module_for("rule_mapping", tour),
            ["--config", "{configs.rule_mapping}"],
            outcome_access="history",
            note="Parses the panel for format-rule evidence; a_won is unused.",
        ),
        *_shared_tail(tour),
        *_model_tail(tour),
        _reporting_config_stage(section, tour),
    ]
    return table


def stages(section: Mapping[str, Any]) -> list[Stage]:
    """The stage table. ``{key}`` placeholders are filled from the chain config.

    ``skip_stages`` drops named stages (an ATP run that reads no reserved season needs
    no bridge). A skip cannot drop a stage a later stage's declared inputs need, because
    ``missing_stage_inputs`` then fails naming the missing path.
    """
    table = _wta_stages(section) if tour_of(section) == "WTA" else _atp_stages(section)
    skipped = [str(name) for name in section.get("skip_stages", [])]
    unknown = [name for name in skipped if name not in {stage.name for stage in table}]
    if unknown:
        raise ChainError(f"skip_stages names no such stage: {unknown}")
    return [stage for stage in table if stage.name not in skipped]


def report_stage(section: Mapping[str, Any]) -> Stage:
    return Stage(
        "report",
        module_for("report", tour_of(section)),
        ["--config", "{reporting_config}", "--output", "{stage_dir}", "--run"],
        dry_run=False,
        outcome_access="target",
        inputs=("reporting_config",),
        note="The only program that opens a target year's labels.",
    )


def post_barrier_stages(section: Mapping[str, Any]) -> list[Stage]:
    """The report and, when the chain has an SR03 calibration, its component evaluation.

    Both run after the barrier and are the only stages declared ``target``. The
    component stage scores the calibration stage's persisted predictions with the
    arithmetic the archive ran before the barrier (RB14).
    """
    table = [report_stage(section)]
    if "sr03" in section.get("configs", {}) and "sr03_calibration" not in section.get(
        "skip_stages", []
    ):
        table.append(
            Stage(
                "sr03_component",
                module_for("sr03_calibration", tour_of(section)),
                ["evaluate", "{configs.sr03}", "{run_root}/sr03_calibration", "{stage_dir}"],
                dry_run=False,
                outcome_access="target",
                note="SR03 component metrics from the persisted predictions, after the barrier.",
            )
        )
    return table


def _flatten(document: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in document.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{name}."))
        elif isinstance(value, str | int | float):
            flat[name] = str(value)
    return flat


def resolve_argv(stage: Stage, template: Sequence[str], values: Mapping[str, str]) -> list[str]:
    resolved: list[str] = []
    for item in template:
        text = item
        for key, value in values.items():
            text = text.replace("{" + key + "}", value)
        if "{" in text and "}" in text:
            raise ChainError(f"stage {stage.name}: unresolved placeholder in {item!r}")
        resolved.append(text)
    return resolved


def command_for(
    stage: Stage,
    section: Mapping[str, Any],
    run_root: Path,
    overrides: Mapping[str, str] | None = None,
) -> list[str]:
    values = _flatten(section)
    values["stage_dir"] = str(run_root / stage.name)
    values["run_root"] = str(run_root)
    values.update(overrides or {})
    if stage.module is None:
        return []
    return [sys.executable, "-B", "-m", stage.module, *resolve_argv(stage, stage.argv, values)]


def hash_tree(base: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    if not base.exists():
        return entries
    for path in sorted(item for item in base.rglob("*") if item.is_file()):
        relative = path.relative_to(base).as_posix()
        if "__pycache__" in relative or relative.endswith(".pyc") or relative == STAGE_MANIFEST:
            continue
        entries[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    return entries


def verify_earlier(run_root: Path, upto: Sequence[str]) -> list[str]:
    verified: list[str] = []
    for name in upto:
        manifest_path = run_root / name / STAGE_MANIFEST
        if not manifest_path.is_file():
            raise ChainError(
                f"stage {name} has no {STAGE_MANIFEST}; run it before the later stages"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        observed = hash_tree(run_root / name)
        declared = manifest["outputs"]
        if set(observed) != set(declared):
            raise ChainError(
                f"stage {name} output membership changed since it ran: "
                f"{sorted(set(observed) ^ set(declared))}"
            )
        for relative, record in declared.items():
            if observed[relative]["sha256"] != record["sha256"]:
                raise ChainError(f"stage {name} output changed since it ran: {relative}")
        verified.append(name)
    return verified


def append_ledger(run_root: Path, entry: dict[str, Any]) -> str:
    path = run_root / LEDGER
    previous = "genesis"
    if path.is_file():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            previous = canonical_hash(json.loads(lines[-1]))
    record = {**entry, "previous_entry_sha256": previous}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return canonical_hash(record)


def verify_ledger(run_root: Path) -> list[dict[str, Any]]:
    """Every entry's ``previous_entry_sha256`` must be the hash of the entry before it."""
    path = run_root / LEDGER
    if not path.is_file():
        raise ChainError(f"no ledger at {path}")
    entries = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    previous = "genesis"
    for index, entry in enumerate(entries):
        if entry.get("previous_entry_sha256") != previous:
            raise ChainError(
                f"ledger entry {index} ({entry.get('stage')}) does not chain to its predecessor"
            )
        previous = canonical_hash(entry)
    return entries


NAMED_INPUT_KEYS = frozenset(
    {
        "bridge_summary",
        "event_crosswalk",
        "base_event_crosswalk",
        "market_manifest",
        "market_dir",
        "candidates_dir",
        "archive_panel_dir",
        "original_archive",
        "market_event_crosswalk",
        "market_profile_adapter",
        "design",
        "join_dir",
        "event_map_dir",
    }
)


def declared_input_paths(document: Any) -> list[str]:
    """Every input path a stage config declares: ``path``/``*_path`` fields and named keys."""
    found: list[str] = []
    if isinstance(document, Mapping):
        for key, value in document.items():
            if key.startswith("output"):
                continue
            named = key == "path" or key.endswith("_path") or key in NAMED_INPUT_KEYS
            if isinstance(value, str) and named:
                if not value.startswith("PENDING"):
                    found.append(value)
            else:
                found.extend(declared_input_paths(value))
    elif isinstance(document, list):
        for item in document:
            found.extend(declared_input_paths(item))
    return found


def stage_config_keys(stage: Stage) -> list[str]:
    return [
        item[len("{configs.") : -1]
        for item in stage.argv
        if item.startswith("{configs.") and item.endswith("}")
    ]


def stage_config_paths(
    stage: Stage, section: Mapping[str, Any], overrides: Mapping[str, str] | None = None
) -> dict[str, Path]:
    configs = section.get("configs", {})
    resolved: dict[str, Path] = {}
    for key in stage_config_keys(stage):
        value = (overrides or {}).get(f"configs.{key}", configs.get(key))
        if value is None:
            continue
        resolved[key] = resolve_under_root(value, label=f"configs.{key}")
    return resolved


def stage_declared_inputs(
    stage: Stage, section: Mapping[str, Any], overrides: Mapping[str, str] | None = None
) -> list[tuple[str, Path]]:
    declared: list[tuple[str, Path]] = []
    for key, config_path in stage_config_paths(stage, section, overrides).items():
        declared.append((f"configs.{key}", config_path))
        if not config_path.is_file():
            continue
        for item in declared_input_paths(read_config(config_path)):
            declared.append((f"configs.{key} input", resolve_under_root(item, label=key)))
    flat = _flatten(section)
    for name in stage.inputs:
        value = (overrides or {}).get(name, flat.get(name))
        if value is None:
            raise ChainError(f"stage {stage.name}: chain config has no field {name!r}")
        declared.append((f"chain.{name}", resolve_under_root(value, label=name)))
    return declared


def missing_stage_inputs(
    stage: Stage, section: Mapping[str, Any], overrides: Mapping[str, str] | None = None
) -> list[str]:
    return [
        f"{label}: {path}"
        for label, path in stage_declared_inputs(stage, section, overrides)
        if not path.exists()
    ]


# ------------------------------------------------------------------ PENDING hashes


def _stage_manifest_hash(path: Path, run_root: Path) -> str | None:
    try:
        relative = path.relative_to(run_root)
    except ValueError:
        return None
    if not relative.parts:
        return None
    manifest_path = run_root / relative.parts[0] / STAGE_MANIFEST
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = manifest.get("outputs", {}).get(Path(*relative.parts[1:]).as_posix())
    return record["sha256"] if record else None


def bound_hash(path: Path, run_root: Path) -> str:
    """sha256 of ``path``, cross-checked against the producing stage's own manifest."""
    observed = sha256(path)
    recorded = _stage_manifest_hash(path, run_root)
    if recorded is not None and recorded != observed:
        raise ChainError(
            f"{path} changed since the stage that produced it recorded {recorded}; observed {observed}"
        )
    return observed


def csv_data_rows(path: Path) -> int:
    with path.open("rb") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _sr03_binding_files(document: Mapping[str, Any], run_root: Path) -> list[dict[str, str]]:
    """The sr03 binding inventory: the config's data sources plus the code that runs.

    A config in the archive's shape (``bindings.implementation_path``) gets the archive's
    inventory: the two SR02 modules and the implementation hashed by workspace path. A
    config in the package's shape (``bindings.implementation``) gets package receipts
    (module name and file hash). Data entries are the same in both.
    """
    source = document["source"]
    paths = [
        source["design_path"],
        source["primary_config_path"],
        source["point_manifest_path"],
        source["selected_matches_path"],
        source["panel_path"],
        source["rule_mapping_path"],
    ]
    bindings = document.get("bindings", {})
    archive_shape = "implementation_path" in bindings
    if archive_shape:
        paths = [
            source["design_path"],
            "references/SR02_models/market.py",
            "references/SR02_models/runner.py",
            source["primary_config_path"],
            source["point_manifest_path"],
            source["selected_matches_path"],
            source["panel_path"],
            source["rule_mapping_path"],
            bindings["implementation_path"],
        ]
    records: list[dict[str, str]] = []
    for relative in dict.fromkeys(paths):
        path = resolve_under_root(relative, label="sr03 binding")
        if not path.is_file():
            raise ChainError(f"sr03 binding file does not exist: {path}")
        records.append({"path": relative, "sha256": bound_hash(path, run_root)})
    if not archive_shape:
        for module in SR03_CODE_BINDINGS:
            records.append(code_receipt(module))
    return records


def _fill_document(document: Any, run_root: Path) -> Any:
    """Replace every PENDING field whose sibling ``path`` names an existing artifact."""
    if isinstance(document, list):
        return [_fill_document(item, run_root) for item in document]
    if not isinstance(document, Mapping):
        return document
    filled = {key: _fill_document(value, run_root) for key, value in document.items()}
    for key, value in list(filled.items()):
        if not (isinstance(value, str) and value.startswith("PENDING")):
            continue
        if key in ("sha256", "rows"):
            source = filled.get("path")
        elif key.endswith("_sha256"):
            source = filled.get(f"{key[: -len('_sha256')]}_path")
        elif key.endswith("_rows"):
            source = filled.get(f"{key[: -len('_rows')]}_path")
        else:
            continue
        if not isinstance(source, str) or source.startswith("PENDING"):
            continue
        path = resolve_under_root(source, label=key)
        if not path.is_file():
            raise ChainError(f"cannot fill {key}: {path} does not exist yet")
        filled[key] = (
            csv_data_rows(path)
            if key == "rows" or key.endswith("_rows")
            else bound_hash(path, run_root)
        )
    return filled


def fill_pending(
    stage: Stage, section: Mapping[str, Any], run_root: Path
) -> tuple[dict[str, str], dict[str, Any]]:
    """Fill each of this stage's configs' PENDING fields and save ``<name>.filled.json``."""
    overrides: dict[str, str] = {}
    record: dict[str, Any] = {}
    for key, config_path in stage_config_paths(stage, section).items():
        if not config_path.is_file():
            continue
        document = read_config(config_path)
        pending = _pending_fields(document)
        if not pending:
            continue
        filled = _fill_document(document, run_root)
        if (
            isinstance(filled.get("bindings"), Mapping)
            and filled["bindings"].get("files") == "PENDING"
        ):
            filled["bindings"] = {
                **filled["bindings"],
                "files": _sr03_binding_files(filled, run_root),
            }
        remaining = _pending_fields(filled)
        if remaining:
            raise ChainError(
                f"stage {stage.name}: {len(remaining)} field(s) still PENDING after the "
                f"automatic fill; first: {remaining[0]}"
            )
        target = config_path.with_name(f"{config_path.stem}.filled.json")
        digest = guarded_json(target, filled)
        overrides[f"configs.{key}"] = relative_to_root(target)
        record[key] = {
            "template": relative_to_root(config_path),
            "filled": relative_to_root(target),
            "filled_sha256": digest,
            "fields_filled": pending,
        }
    return overrides, record


ACCESS_LOG = "access_log.jsonl"


def observed_outcome_access(
    stage: Stage, stage_dir: Path, workspace_root: Path, panel_end_year: int | None
) -> dict[str, Any]:
    """Derive the stage's outcome access from its access log and check the declaration.

    ``observed`` lists every read-open of an outcome-bearing file (by content) with the
    innermost package function that opened it; ``receipts`` are the accessor receipts;
    ``violations`` names an undeclared parse or a receipt beyond its fold's horizon.
    """
    try:
        opens, receipts = access.read_log(stage_dir / ACCESS_LOG) if stage.module else ([], [])
    except (OSError, ValueError, TypeError) as error:
        return {
            "declared": stage.outcome_access,
            "observed": [],
            "receipts": [],
            "violations": [f"stage {stage.name}: invalid audit evidence: {error}"],
            "basis": "completed audit log required (schema 2)",
        }
    observed: list[dict[str, Any]] = []
    classified: dict[str, dict[str, Any]] = {}
    for entry in opens:
        path = workspace_root / entry["path"]
        if entry["path"] not in classified:
            classified[entry["path"]] = (
                outcome_files.classify(path)
                if path.is_file()
                else {
                    "content": "absent",
                    "outcome_columns": [],
                }
            )
        kind = classified[entry["path"]]
        if kind["content"] not in ("outcome_columns", "container"):
            continue
        observed.append(
            {
                "path": entry["path"],
                "content": kind["content"],
                "outcome_columns": kind["outcome_columns"],
                "opener": entry["opener"],
                "access": outcome_files.access_kind(entry["opener"]),
                "opens": entry["count"],
            }
        )
    violations: list[str] = []
    if stage.outcome_access == "none":
        for item in observed:
            # A projection drops the outcome columns before any row is returned.
            if item["access"] == "parsed" and item["opener"] != PROJECTION_OPENER:
                violations.append(
                    f"stage {stage.name} declares no outcome access but parsed "
                    f"{item['path']} ({item['content']}: {item['outcome_columns']}) "
                    f"in {item['opener'] or 'an unknown frame'}"
                )
    if stage.outcome_access == "fold":
        for item in observed:
            if item["access"] == "parsed" and item["opener"] not in ACCESSOR_OPENERS:
                violations.append(
                    f"stage {stage.name} is a fold reader but parsed {item['path']} "
                    f"({item['content']}: {item['outcome_columns']}) outside the accessors, "
                    f"in {item['opener'] or 'an unknown frame'}"
                )
        if not receipts and any(item["access"] == "parsed" for item in observed):
            violations.append(f"stage {stage.name} parsed outcomes but left no accessor receipt")
        for receipt in receipts:
            if receipt.get("accessor") == "projected_rows":
                continue  # a metadata parse with the outcome columns dropped
            if receipt.get("fold_outer_year") is None:
                violations.append(
                    f"stage {stage.name}: {receipt.get('purpose')} read with ceiling "
                    f"{receipt.get('year_ceiling')} names no fold"
                )
    for receipt in receipts:
        ceiling = receipt.get("year_ceiling")
        fold = receipt.get("fold_outer_year")
        latest = receipt.get("max_season_returned")
        cutoff = receipt.get("cutoff_date")
        latest_date = receipt.get("max_match_date_returned")
        if cutoff is not None and fold is not None:
            last_allowed = (dt.date(int(fold), 1, 1) - dt.timedelta(days=2)).isoformat()
            try:
                valid_cutoff = dt.date.fromisoformat(cutoff).isoformat() <= last_allowed
            except TypeError, ValueError:
                valid_cutoff = False
            if not valid_cutoff:
                violations.append(
                    f"stage {stage.name}: cutoff {cutoff} exceeds fold cutoff {last_allowed}"
                )
        if cutoff is not None and latest_date is not None and latest_date > cutoff:
            violations.append(
                f"stage {stage.name}: returned date {latest_date} beyond cutoff {cutoff}"
            )
        if ceiling is not None and latest is not None and int(latest) > int(ceiling):
            violations.append(
                f"stage {stage.name}: {receipt.get('purpose')} returned season {latest} "
                f"beyond its ceiling {ceiling}"
            )
        if fold is not None and (ceiling is None or int(ceiling) >= int(fold)):
            violations.append(
                f"stage {stage.name}: {receipt.get('purpose')} for fold {fold} used ceiling "
                f"{ceiling}, which does not precede the fold"
            )
        if (
            stage.outcome_access == "history"
            and fold is None
            and ceiling is not None
            and panel_end_year is not None
            and int(ceiling) > int(panel_end_year)
        ):
            violations.append(
                f"stage {stage.name}: {receipt.get('purpose')} ceiling {ceiling} exceeds the "
                f"panel end year {panel_end_year}"
            )
        if stage.outcome_access == "none" and receipt.get("accessor") != "projected_rows":
            violations.append(
                f"stage {stage.name} declares no outcome access but read outcomes for "
                f"{receipt.get('purpose')}"
            )
    return {
        "declared": stage.outcome_access,
        "observed": observed,
        "receipts": receipts,
        "violations": violations,
        "basis": "audit hook on file opens in the stage process; content-classified "
        "(RB14); hash-only opens are allowed under every declaration",
    }


def run_stage(
    stage: Stage,
    section: Mapping[str, Any],
    run_root: Path,
    *,
    earlier: Sequence[str],
    panel_end_year: int | None = None,
) -> dict[str, Any]:
    # Check every runner-owned destination before filling configs or launching code.
    stage_dir = resolve_output_under_root(run_root / stage.name, label="stage output")
    if stage_dir.exists():
        for child in stage_dir.rglob("*"):
            if child.is_symlink():
                resolve_output_under_root(child, label="stage output descendant")
    for name in ("stdout.txt", "stderr.txt", ACCESS_LOG, STAGE_MANIFEST):
        resolve_output_under_root(stage_dir / name, label=f"stage {name}")
    resolve_output_under_root(run_root / LEDGER, label="chain ledger")
    verify_earlier(run_root, earlier)
    if earlier:
        verify_stage_records(run_root, earlier)
    overrides, filled = fill_pending(stage, section, run_root)
    missing = missing_stage_inputs(stage, section, overrides)
    if missing:
        raise ChainError(
            f"stage {stage.name} declares {len(missing)} input(s) that do not exist; first: {missing[0]}"
        )
    stage_dir.mkdir(parents=True, exist_ok=True)
    command = command_for(stage, section, run_root, overrides)
    workspace_root = resolve_under_root(".", label="workspace")
    environment = {
        **os.environ,
        **ENVIRONMENT,
        "TENNISLAB_WORKSPACE": str(workspace_root),
        access.LOG_ENVIRONMENT_VARIABLE: str(stage_dir / ACCESS_LOG),
    }
    started = dt.datetime.now(dt.UTC)
    if command:
        # No previous launch's completed receipt can stand in for this launch.
        (stage_dir / ACCESS_LOG).unlink(missing_ok=True)
        completed = subprocess.run(
            command,
            cwd=workspace_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        (stage_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (stage_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        status = completed.returncode
    else:
        status = 0
    finished = dt.datetime.now(dt.UTC)
    outcome_access = observed_outcome_access(stage, stage_dir, workspace_root, panel_end_year)
    problems = list(outcome_access["violations"])
    content_scan: dict[str, Any] | None = None
    if stage.name == "barrier" or stage.outcome_access == "target":
        recheck = verify_integrity(
            run_root,
            earlier,
            stage_table=[*stages(section), *post_barrier_stages(section)],
            panel_end_year=panel_end_year,
        )
        problems.extend(recheck["problems"])
    if stage.name == "barrier":
        scan = barrier_scan.scan_tree(run_root, list(earlier))
        content_scan = {
            "scanned_files": len(scan["scanned"]),
            "uninspected_files": scan["uninspected"],
            "findings": scan["findings"],
        }
        problems += [
            f"metric-shaped content before the barrier: {item['artifact']} "
            f"{item['metric_locations'][:3]}"
            for item in scan["findings"]
        ]
    outputs = hash_tree(stage_dir)
    manifest: dict[str, Any] = {
        "stage": stage.name,
        "module": stage.module,
        "command": command,
        "environment": ENVIRONMENT,
        "exit_status": status,
        "outcome_access": outcome_access,
        "note": stage.note,
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "wall_clock_seconds": (finished - started).total_seconds(),
        "outputs": outputs,
        "output_count": len(outputs),
        "outputs_sha256": canonical_hash(outputs),
        "configs_filled_from_earlier_stage_outputs": filled,
        "integrity_violations": problems,
    }
    if stage.module is not None:
        manifest["code"] = code_receipt(stage.module)
    if stage.name == "barrier":
        manifest["content_scan"] = content_scan
        run_tree = {name: hash_tree(run_root / name) for name in earlier}
        manifest["run_tree"] = run_tree
        if problems:
            manifest["status"] = "refused"
        else:
            # SCAR_TISSUE B5: a run-tree digest of nothing is refused, never recorded.
            manifest["run_tree_sha256"] = canonical_hash_nonempty(run_tree, label="run_tree_sha256")
            manifest["instruction"] = (
                "Timestamp run_tree_sha256 externally now. Nothing after this point may rerun an earlier stage."
            )
    guarded_json(stage_dir / STAGE_MANIFEST, manifest)
    entry = {
        "stage": stage.name,
        "exit_status": status,
        "outputs_sha256": manifest["outputs_sha256"],
        "finished_utc": manifest["finished_utc"],
        "manifest_sha256": sha256(stage_dir / STAGE_MANIFEST),
    }
    if problems:
        entry["integrity"] = "fail"
    append_ledger(run_root, entry)
    if status != 0:
        raise ChainError(f"stage {stage.name} exited {status}; see {stage_dir / 'stderr.txt'}")
    if problems:
        raise ChainError(f"stage {stage.name} failed the integrity check: {problems[0]}")
    return manifest


def guarded_json(path: Path, value: Any) -> str:
    path = resolve_output_under_root(path, label="runner JSON output")
    resolve_output_under_root(
        path.with_suffix(path.suffix + f".tmp.{os.getpid()}"), label="runner JSON temporary output"
    )
    return atomic_json(path, value)


def verify_stage_records(run_root: Path, names: Sequence[str]) -> None:
    """Bind manifests to ledger entries, and ledger entries to the actual output map."""
    entries = verify_ledger(run_root)
    if [entry.get("stage") for entry in entries] != list(names):
        raise ChainError("ledger stage inventory differs from completed manifests")
    for name, entry in zip(names, entries, strict=True):
        path = run_root / name / STAGE_MANIFEST
        manifest = read_config(path)
        if entry.get("manifest_sha256") != sha256(path):
            raise ChainError(f"stage {name} manifest digest differs from ledger")
        observed = hash_tree(run_root / name)
        if (
            manifest.get("outputs") != observed
            or manifest.get("outputs_sha256") != canonical_hash(observed)
            or entry.get("outputs_sha256") != canonical_hash(observed)
        ):
            raise ChainError(f"stage {name} output digest differs from ledger")
        if (
            manifest.get("stage") != name
            or manifest.get("exit_status") != 0
            or entry.get("exit_status") != 0
        ):
            raise ChainError(f"stage {name} has invalid identity or exit status")
        if entry.get("integrity") == "fail":
            raise ChainError(f"stage {name} failed integrity")


def verify_integrity(
    run_root: Path,
    names: Sequence[str],
    *,
    stage_table: Sequence[Stage] | None = None,
    panel_end_year: int | None = None,
) -> dict[str, Any]:
    """Re-derive completed stage access under configured declarations and rescan artifacts."""
    problems: list[str] = []
    checked: list[str] = []
    table = {
        stage.name: stage for stage in (stage_table or [*stages({}), *post_barrier_stages({})])
    }
    workspace_root = resolve_under_root(".", label="workspace")
    for name in names:
        manifest_path = run_root / name / STAGE_MANIFEST
        if not manifest_path.is_file():
            problems.append(f"stage {name} missing manifest")
            continue
        manifest = read_config(manifest_path)
        checked.append(name)
        if name not in table:
            problems.append(f"stage {name} is not configured")
            continue
        actual = observed_outcome_access(
            table[name], run_root / name, workspace_root, panel_end_year
        )
        problems.extend(actual["violations"])
        if actual != manifest.get("outcome_access"):
            problems.append(
                f"stage {name} recorded outcome access differs from reconstructed access"
            )
        recorded = manifest.get("integrity_violations")
        if recorded is None:
            problems.append(f"stage {name} ran before the access record existed (RB14)")
        else:
            problems.extend(recorded)
        if name == "barrier":
            expected = {prior: hash_tree(run_root / prior) for prior in names[: names.index(name)]}
            if (
                not expected
                or manifest.get("run_tree") != expected
                or manifest.get("run_tree_sha256") != canonical_hash(expected)
            ):
                problems.append("barrier run tree differs from completed stage outputs")
    if "barrier" in checked:
        scan = barrier_scan.scan_tree(run_root, list(names[: names.index("barrier")]))
        problems += [
            f"metric-shaped content before the barrier: {item['artifact']}"
            for item in scan["findings"]
        ]
    return {"stages_checked": checked, "problems": problems}


# ------------------------------------------------------------------ emitted configs


def write_configs(
    document: Mapping[str, Any], section: Mapping[str, Any], plan: Any
) -> dict[str, Any]:
    """Generate every per-stage config from this one chain config.

    The stage configs are not hand-maintained copies: they are emitted, each carrying a
    verbatim copy of the chain's ``year_plan``, and ``dry-run`` re-checks that each one
    still matches. ``stage_config_overrides`` merges per-stage fields in.
    """
    plan_document = plan.as_document()
    inputs = section.get("inputs", {})
    overrides = section.get("stage_config_overrides", {})
    target = resolve_output_under_root(section["configs_dir"], label="configs_dir")
    target.mkdir(parents=True, exist_ok=True)
    emitted: dict[str, Any] = {}
    for name, body in _stage_config_bodies(section, inputs, plan_document).items():
        merged = _deep_merge(body, overrides.get(name, {}))
        path = target / f"{name}.json"
        emitted[name] = {"path": relative_to_root(path), "sha256": guarded_json(path, merged)}
    plan_path = target / "year_plan.json"
    plan_document_out: dict[str, Any] = {"year_plan": plan_document}
    for key in (
        "bundles",
        "blocks",
        "learners",
        "cohort",
        "primary_contrast",
        "bootstrap_seed",
        "bootstrap_unit",
    ):
        if section.get(key) is not None:
            plan_document_out[key] = list(section[key])
    emitted["year_plan"] = {
        "path": relative_to_root(plan_path),
        "sha256": guarded_json(plan_path, plan_document_out),
    }
    return {
        "configs_dir": relative_to_root(target),
        "year_plan": plan_document,
        "emitted": emitted,
        "note": "Every emitted config carries this year_plan verbatim. Point the chain "
        "config's `configs` object at these paths and rerun dry-run.",
    }


def _pending_fields(document: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(document, Mapping):
        for key, value in document.items():
            found.extend(_pending_fields(value, f"{prefix}{key}."))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            found.extend(_pending_fields(value, f"{prefix}{index}."))
    elif isinstance(document, str) and document.startswith("PENDING"):
        found.append(prefix.rstrip("."))
    return sorted(found)


def _deep_merge(base: Mapping[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _stage_config_bodies(
    section: Mapping[str, Any], inputs: Mapping[str, Any], plan_document: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    run_root = str(Path(section["run_root"]))

    def stage_path(stage: str, *parts: str) -> str:
        return Path(run_root, stage, *parts).as_posix()

    shared = _shared_stage_config_bodies(section, inputs, plan_document, stage_path)
    if tour_of(section) == "WTA":
        return _wta_stage_config_bodies(section, inputs, plan_document, shared, stage_path)
    return {**_atp_stage_config_bodies(section, inputs, plan_document, stage_path), **shared}


def _bridge_body(
    section: Mapping[str, Any],
    inputs: Mapping[str, Any],
    plan_document: Mapping[str, Any],
    tour: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "archive": inputs["archive"],
        "tour": tour,
        "seasons": list(section["bridge_seasons"]),
        "carry_forward_years": list(section["bridge_carry_forward_years"]),
        "panel_start_year": section.get("panel_start_year", 2005 if tour == "ATP" else 2007),
        "sources": section["bridge_sources"],
        "output_dir": Path(section["inputs_dir"]).as_posix(),
        "reserved_release_acknowledged": section.get("reserved_release_acknowledged", False),
    }
    if tour == "ATP":
        body["market_event_crosswalk"] = inputs.get(
            "market_event_crosswalk", "work/MULTI01_event_crosswalk/qualified_event_crosswalk.csv"
        )
    else:
        body["unresolved_event_policy"] = section.get("unresolved_event_policy", "quarantine")
    if section.get("infobox_html_dir"):
        body["infobox_html_dir"] = section["infobox_html_dir"]
    return {"year_plan": plan_document, "bridge": body}


def _atp_stage_config_bodies(
    section: Mapping[str, Any],
    inputs: Mapping[str, Any],
    plan_document: Mapping[str, Any],
    stage_path: Any,
) -> dict[str, dict[str, Any]]:
    bodies = _atp_bodies_after_bridge(section, inputs, plan_document, stage_path)
    if "bridge_seasons" not in section:
        return bodies
    return {"bridge": _bridge_body(section, inputs, plan_document, "ATP"), **bodies}


def _join_body(
    section: Mapping[str, Any], plan_document: Mapping[str, Any], stage_path: Any
) -> dict[str, Any]:
    # The manifest is the bridge's merged one, but the market directory stays MULTI01's,
    # because every carried record's `retained_path` is resolved against it.
    return {
        "archive_panel_dir": stage_path("archive_panel"),
        "market_dir": section.get("market_base_dir", "work/MULTI01_market_acquisition"),
        "market_manifest": Path(
            section["inputs_dir"], "market", "acquisition_manifest.json"
        ).as_posix(),
        "market_profile_adapter": "work/MULTI01_market_acquisition/profile_annual.py",
        "panel_start_year": section.get("panel_start_year", 2005),
        "panel_end_year": plan_document["panel_end_year"],
    }


def _sr02_body(
    section: Mapping[str, Any],
    inputs: Mapping[str, Any],
    plan_document: Mapping[str, Any],
    stage_path: Any,
    output_stage: str,
    tier_feed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "primary_config": inputs["sr02_primary_config"],
        "saved_selections": inputs["sr02_saved_selections"],
        "panel": {"path": stage_path("format_corrections", "panel.csv")},
        "rule_mapping": {"path": stage_path("rule_mapping", "rules.csv")},
        "source_year_min": section.get("panel_start_year", 2005),
        "source_year_max": plan_document["panel_end_year"],
        "annual_eligible_floor_year": section.get("annual_eligible_floor_year", 2012),
        "selection_year_min": section.get("selection_year_min", 2011),
    }
    if tier_feed is not None:
        body["tier_feed"] = tier_feed
    body["output_dir"] = stage_path(output_stage)
    return {"year_plan": plan_document, "sr02_replay": body}


def _atp_bodies_after_bridge(
    section: Mapping[str, Any],
    inputs: Mapping[str, Any],
    plan_document: Mapping[str, Any],
    stage_path: Any,
) -> dict[str, dict[str, Any]]:
    join = _join_body(section, plan_document, stage_path)
    bodies: dict[str, dict[str, Any]] = {
        "archive_panel": {
            "year_plan": plan_document,
            "archive_panel": {
                "original_archive": inputs["archive"]["path"],
                "bridge_summary": Path(section["inputs_dir"], "bridge_summary.json").as_posix(),
                "panel_start_year": section.get("panel_start_year", 2005),
                "panel_end_year": plan_document["panel_end_year"],
                "output_dir": stage_path("archive_panel"),
            },
        },
        "join": {"year_plan": plan_document, "join": join},
        "event_carry_forward": {
            "year_plan": plan_document,
            "carry_event_crosswalk": {
                "candidates_dir": stage_path("join"),
                "archive_panel_dir": stage_path("archive_panel"),
                "base_event_crosswalk": inputs.get(
                    "market_event_crosswalk",
                    "work/MULTI01_event_crosswalk/qualified_event_crosswalk.csv",
                ),
            },
        },
        "prepare_panel": {
            "year_plan": plan_document,
            "prepare": {
                "candidates_dir": stage_path("join"),
                "event_crosswalk": stage_path(
                    "event_carry_forward", "extended_event_crosswalk.csv"
                ),
            },
            "join": join,
        },
        "format_corrections": {
            "year_plan": plan_document,
            "format_corrections": {
                "parent_panel": {"path": stage_path("prepare_panel", "panel.csv")},
                "correction_proposals": inputs["correction_proposals"],
            },
        },
        "rule_mapping": {
            "year_plan": plan_document,
            "rule_carry_forward": {
                "base_rules": inputs["base_rules"],
                "base_panel": inputs["base_panel"],
                "rule_config": inputs["rule_config"],
                "extended_panel": {"path": stage_path("format_corrections", "panel.csv")},
                "carry_from_year": section["rule_carry_from_year"],
                "output_dir": stage_path("rule_mapping"),
            },
        },
        "sr02_replay": _sr02_body(section, inputs, plan_document, stage_path, "sr02_replay"),
    }
    if "tier_stream" in section.get("configs", {}) or section.get("tier_enabled"):
        bodies.update(_tier_bodies(section, inputs, plan_document, stage_path))
    return bodies


def _tier_bodies(
    section: Mapping[str, Any],
    inputs: Mapping[str, Any],
    plan_document: Mapping[str, Any],
    stage_path: Any,
) -> dict[str, dict[str, Any]]:
    """TIER01's stage configs. Every year gate is the chain's own year plan and every
    declared constant is the design's; the measured initial-rating offsets are declared
    here and recomputed by ``tier_elo``, which refuses a drift."""
    ablation = bool(section.get("tier_same_event_qualifying_ablation"))

    def feed(exclude_same_event_qualifying: bool) -> dict[str, Any]:
        body: dict[str, Any] = {"enabled": True}
        if exclude_same_event_qualifying:
            body["exclude_same_event_qualifying"] = True
        body.update(
            {
                "path": stage_path("tier_stream", "tier_source_rows.csv.gz"),
                "sha256": "PENDING",
                "source_year_min": section.get("tier_serve_counts_start_year", 2010),
                "source_year_max": plan_document["panel_end_year"],
                "rule_config": inputs["rule_config"],
            }
        )
        return body

    bodies: dict[str, dict[str, Any]] = {
        "tier_stream": {
            "config_id": "TIER01-tier-stream",
            "year_plan": plan_document,
            "tier_stream": {
                "archive": section["inputs"]["archive"],
                "inventory": inputs["archive_inventory"],
                "archive_manifest": inputs["archive_manifest"],
                "last_year": plan_document["panel_end_year"],
                "parameters": {
                    "first_year": section.get("tier_first_year", 1991),
                    "elo_start_year": section.get("panel_start_year", 2005),
                    "experience_start_year": section.get("tier_first_year", 1991),
                    "serve_counts_start_year": section.get("tier_serve_counts_start_year", 2010),
                    "reported_date_offset_days": section.get("tier_reported_date_offset_days", 7),
                    "satellite_circuit_dating": bool(
                        section.get("tier_satellite_circuit_dating", False)
                    ),
                },
                "output_dir": stage_path("tier_stream"),
            },
        },
        "tier_elo": {
            "config_id": "TIER01-tier-elo",
            "year_plan": plan_document,
            "tier_elo": {
                "elo_engine": inputs["elo_engine"],
                "features": {"path": stage_path("features", "features.csv"), "sha256": "PENDING"},
                "labels": {"path": stage_path("features", "labels.csv"), "sha256": "PENDING"},
                "tier_results": {
                    "path": stage_path("tier_stream", "tier_results.csv.gz"),
                    "sha256": "PENDING",
                },
                "include_lower_tier": True,
                "parameters": {
                    "lag_calendar_days": 2,
                    "elo_start_year": section.get("panel_start_year", 2005),
                    "experience_start_year": section.get("tier_first_year", 1991),
                    "offset_measurement_end_year": section.get(
                        "tier_offset_measurement_end_year", 2016
                    ),
                    "prior_match_cap": 300,
                    "prior_title_cap": 20,
                    "k_multipliers": {
                        "tour": 1.0,
                        "challenger": 0.8,
                        "qualifying": 0.8,
                        "futures": 0.6,
                    },
                    "lower_tier_initial_offset": section.get("tier_initial_rating_offset"),
                    "offset_mode": section.get("tier_offset_mode", "single"),
                    "lower_tier_initial_offset_by_year": section.get(
                        "tier_initial_rating_offset_by_year"
                    ),
                },
                "output_dir": stage_path("tier_elo"),
            },
        },
        "sr02_tier_replay": _sr02_body(
            section, inputs, plan_document, stage_path, "sr02_tier_replay", feed(False)
        ),
    }
    if ablation:
        bodies["sr02_tier_noqual_replay"] = _sr02_body(
            section, inputs, plan_document, stage_path, "sr02_tier_noqual_replay", feed(True)
        )
    bodies["tier_block"] = {
        "config_id": "TIER01-tier-block",
        "year_plan": plan_document,
        "tier_block": {
            "panel": {"path": stage_path("format_corrections", "panel.csv"), "sha256": "PENDING"},
            "sidecar": {
                "path": stage_path("sidecar", "trait_latent_sidecar.csv"),
                "sha256": "PENDING",
            },
            "tier_elo_features": {
                "path": stage_path("tier_elo", "tier_elo_features.csv"),
                "sha256": "PENDING",
            },
            "tier_dynamic": {
                "path": stage_path("sr02_tier_replay", "selected_matches.csv"),
                "sha256": "PENDING",
            },
            **(
                {
                    "tier_noqual_dynamic": {
                        "path": stage_path("sr02_tier_noqual_replay", "selected_matches.csv"),
                        "sha256": "PENDING",
                    }
                }
                if ablation
                else {}
            ),
            "base_dictionary": {
                "path": stage_path("features", "column_dictionary.json"),
                "sha256": "PENDING",
            },
            "parameters": {
                "lag_calendar_days": 2,
                "thin_side_prior_match_threshold": section.get("tier_thin_side_threshold", 20),
            },
            "output_dir": stage_path("tier_block"),
        },
    }
    return bodies


def _shared_stage_config_bodies(
    section: Mapping[str, Any],
    inputs: Mapping[str, Any],
    plan_document: Mapping[str, Any],
    stage_path: Any,
) -> dict[str, dict[str, Any]]:
    """The four bodies both tours emit identically (bar the rankings tour switch)."""
    experiment = experiment_of(section)
    tour = tour_of(section)
    return {
        "rankings": {
            "year_plan": plan_document,
            "ranking_year_min": section.get("ranking_year_min", 2000),
            "ranking_year_max": plan_document["panel_end_year"],
            "result_year_min": section.get("panel_start_year", 2005),
            "result_year_max": plan_document["panel_end_year"],
        },
        "sidecar": {
            "config_id": f"{experiment}-trait-latent-sidecar",
            "history_contract": {
                "identity_tier": "primary",
                "latest_source_date": "target reported match date minus 2 calendar days",
                "same_date_values": "equal values collapse; conflicting valid values make that field missing",
                "age": "DOB-derived at target reported match date; no raw source-age fallback",
                "height": "any finite value greater than zero is retained; no plausibility exclusion or clipping",
                "hand": "L and R are valid; all other codes are unknown and audited",
            },
            "year_plan": plan_document,
            "inputs": {
                "base_features": {
                    "path": stage_path("features", "features.csv"),
                    "sha256": "PENDING",
                },
                "base_dictionary": {
                    "path": stage_path("features", "column_dictionary.json"),
                    "sha256": "PENDING",
                },
                "base_manifest": {
                    "path": stage_path("features", "manifest.json"),
                    "sha256": "PENDING",
                },
                "bio_contract": inputs["bio_contract"],
                "bio_players": inputs.get("bio_players", {"path": "PENDING", "sha256": "PENDING"}),
                "sr02_panel": {
                    "path": stage_path("format_corrections", "panel.csv"),
                    "sha256": "PENDING",
                },
                "sr02_selected_matches": {
                    "path": stage_path("sr02_replay", "selected_matches.csv"),
                    "sha256": "PENDING",
                },
                "sr02_run_manifest": {
                    "path": stage_path("sr02_replay", "run_manifest.json"),
                    "sha256": "PENDING",
                },
            },
            "output": {
                "sidecar": stage_path("sidecar", "trait_latent_sidecar.csv"),
                "lineage": stage_path("sidecar", "trait_lineage_groups.csv.gz"),
                "conflicts": stage_path("sidecar", "trait_conflicts.csv"),
            },
        },
        "features": {
            "config_id": f"{experiment}-features",
            "status": section.get(
                "features_status", "fixed_feature_reconstruction_no_new_model_fit"
            ),
            # ARMS01: the entry/level block is emitted only when the chain declares it,
            # so every chain without it still writes the accepted features config.
            **({"entry_level_block": True} if section.get("entry_level_block") is True else {}),
            "year_plan": plan_document,
            "design": inputs["features_design"],
            "output_dir": stage_path("features"),
            "panel": {
                "path": stage_path("format_corrections", "panel.csv"),
                "sha256": "PENDING",
                "rows": "PENDING",
            },
            "panel_manifest": inputs["panel_manifest"],
            "ranking_source": {
                "path": stage_path(
                    "rankings",
                    f"rankings_{section.get('ranking_year_min', 2000)}_{plan_document['panel_end_year']}.csv.gz",
                ),
                "sha256": "PENDING",
            },
            "ranking_index": {
                "path": stage_path("edition_index", "edition_index.json"),
                "sha256": "PENDING",
            },
            "ranking_lookup_module": inputs["ranking_lookup_module"],
            "parameters": {
                "count_half_life_days": 180.0,
                "count_prior_denominator_units": 50.0,
                "elo_initial_rating": 1500.0,
                "elo_k": 32.0,
                "elo_scale": 400.0,
                "initial_return_rate": 0.4,
                "initial_serve_rate": 0.6,
                "lag_calendar_days": 2,
                "primary_history_identity_tier": "primary",
                "ranking_stale_days": 14,
                "rest_days_cap": 90,
                "source_year_max": plan_document["feature_end_year"],
                "source_year_min": section.get("panel_start_year", 2005),
                "workload_windows_days": [7, 28],
            },
        },
        "sr03": {
            "experiment_id": experiment,
            "tour": tour,
            "decision": section.get("decision", "D52"),
            "proposal_status": "frozen_for_real_execution",
            "year_plan": plan_document,
            "bindings": {"implementation": "tennislab.dynamics.calibrate", "files": "PENDING"},
            "annual_eligible_floor_year": section.get("annual_eligible_floor_year", 2012),
            "calibration": {
                "availability_lag_days": 2,
                "families": {
                    "dynamic": "dynamic_match_probability_a",
                    "simple_unadjusted": "simple_unadjusted_match_probability_a",
                    "unadjusted": "unadjusted_match_probability_a",
                },
                "fit_intercept": False,
                "outer_years": sorted(
                    {
                        year - offset
                        for year in plan_document["target_years"]
                        for offset in range(0, plan_document["calibration_years_back"] + 1)
                    }
                ),
                # SCAR_TISSUE B1: the calibration stage scores no outer year at or after
                # the first target year; those fits are persisted and scored by nothing
                # before the report stage.
                "score_years_max": int(min(plan_document["target_years"])) - 1,
                "penalty": None,
                "reliability_bin_edges": [index / 10 for index in range(11)],
                "slope_constraint": "nonnegative",
                "training_calendar_years": plan_document["calibration_years_back"],
            },
            "comparisons": {"bootstrap_repetitions": 2000, "bootstrap_seed": 20260911},
            "source": {
                "panel_binding_authority": (
                    "point_run_manifest"
                    if int(plan_document["panel_end_year"]) > 2024 or tour != "ATP"
                    else "frozen_primary_config"
                ),
                "design_path": "experiments/SR03.design.md",
                "design_sha256": "PENDING",
                "panel_path": stage_path("format_corrections", "panel.csv"),
                "panel_sha256": "PENDING",
                "point_manifest_path": stage_path("sr02_replay", "run_manifest.json"),
                "point_manifest_sha256": "PENDING",
                "primary_config_path": inputs["sr02_primary_config"]["path"],
                "primary_config_sha256": inputs["sr02_primary_config"]["sha256"],
                "rule_mapping_path": stage_path("rule_mapping", "rules.csv"),
                "rule_mapping_sha256": "PENDING",
                "selected_matches_path": stage_path("sr02_replay", "selected_matches.csv"),
                "selected_matches_rows": "PENDING",
                "selected_matches_sha256": "PENDING",
            },
        },
    }


def _wta_stage_config_bodies(
    section: Mapping[str, Any],
    inputs: Mapping[str, Any],
    plan_document: Mapping[str, Any],
    common: Mapping[str, dict[str, Any]],
    stage_path: Any,
) -> dict[str, dict[str, Any]]:
    """The WTA bodies. Everything tour-specific is here and nowhere else."""
    panel_start = section.get("panel_start_year", 2007)
    event_map_dir = section.get("event_map_dir", "references/WTA01_event_map")
    bridged = "bridge_seasons" in section
    market_manifest = (
        {"path": Path(section["inputs_dir"], "market", "acquisition_manifest.json").as_posix()}
        if bridged
        else inputs["wta_market_manifest"]
    )
    bodies: dict[str, dict[str, Any]] = {}
    if bridged:
        bodies["bridge"] = _bridge_body(section, inputs, plan_document, "WTA")
    bodies.update(
        {
            "archive_panel": {
                "year_plan": plan_document,
                "archive_panel": {
                    "tour": "WTA",
                    "original_archive": inputs["archive"]["path"],
                    **(
                        {
                            "bridge_summary": Path(
                                section["inputs_dir"], "bridge_summary.json"
                            ).as_posix()
                        }
                        if bridged
                        else {}
                    ),
                    "panel_start_year": panel_start,
                    "panel_end_year": plan_document["panel_end_year"],
                    "output_dir": stage_path("archive_panel"),
                },
            },
            "event_carry_forward": {
                "year_plan": plan_document,
                "wta_carry_event_crosswalk": {
                    "base_event_crosswalk": {"path": f"{event_map_dir}/wta_event_crosswalk.csv"},
                    "event_map_manifest": inputs["wta_event_map_manifest"],
                    "sources_module": inputs["wta_sources_module"],
                    "market_manifest": market_manifest,
                    "archive_panel_dir": stage_path("archive_panel"),
                },
            },
            "join": {
                "year_plan": plan_document,
                "wta_join": {
                    "archive_panel_dir": stage_path("archive_panel"),
                    "event_map_dir": event_map_dir,
                    "event_map_manifest": inputs["wta_event_map_manifest"],
                    "event_crosswalk": {
                        "path": stage_path(
                            "event_carry_forward", "extended_wta_event_crosswalk.csv"
                        )
                    },
                    "market_manifest": market_manifest,
                    "sources_module": inputs["wta_sources_module"],
                    "panel_start_year": panel_start,
                    "panel_end_year": plan_document["panel_end_year"],
                    "reserved_release_acknowledged": section.get(
                        "reserved_release_acknowledged", False
                    ),
                },
            },
            "prepare_panel": {
                "tour": "WTA",
                "year_plan": plan_document,
                "wta_prepare": {
                    "join_dir": stage_path("join"),
                    "archive_panel_dir": stage_path("archive_panel"),
                },
            },
            "format_corrections": {
                "tour": "WTA",
                "year_plan": plan_document,
                "format_corrections": {
                    "parent_panel": {"path": stage_path("prepare_panel", "panel.csv")}
                },
            },
            "rule_mapping": {
                "tour": "WTA",
                "year_plan": plan_document,
                "wta_rule_rows": {
                    "rule_config": inputs["wta_rule_config"],
                    "panel": {"path": stage_path("format_corrections", "panel.csv")},
                    "rule_inventory": inputs["wta_rule_inventory"],
                    "era_carry_from_year": section.get("rule_carry_from_year"),
                    "output_dir": stage_path("rule_mapping"),
                },
            },
            "sr02_replay": {
                "tour": "WTA",
                "year_plan": plan_document,
                "sr02_replay": {
                    "primary_config": inputs["sr02_primary_config"],
                    "saved_selections": inputs["sr02_saved_selections"],
                    "panel": {"path": stage_path("format_corrections", "panel.csv")},
                    "rule_mapping": {"path": stage_path("rule_mapping", "rules.csv")},
                    "source_year_min": panel_start,
                    "source_year_max": plan_document["panel_end_year"],
                    "annual_eligible_floor_year": section.get("annual_eligible_floor_year", 2016),
                    "selection_year_min": section.get("selection_year_min", 2011),
                    "count_history_from_year": section.get("count_history_from_year", 2016),
                    "relabelled_count_block_statuses": section.get(
                        "relabelled_count_block_statuses",
                        ["quarantined_invalid", "partial_missing"],
                    ),
                    "output_dir": stage_path("sr02_replay"),
                },
            },
            "rankings": {**common["rankings"], "tour": "WTA"},
            "features": common["features"],
            "sidecar": {
                **common["sidecar"],
                "inputs": {
                    **common["sidecar"]["inputs"],
                    "bio_players": section.get(
                        "wta_bio_players",
                        {"path": stage_path("archive_panel", "players.csv"), "sha256": "PENDING"},
                    ),
                },
            },
            "sr03": common["sr03"],
        }
    )
    return bodies


# ------------------------------------------------------------------ dry run and CLI


def dry_run(section: Mapping[str, Any], run_root: Path, plan: Any) -> dict[str, Any]:
    """Validate configs, stage order and input existence. No stage is launched; no
    match file is opened."""
    checks: list[dict[str, Any]] = []
    for name, value in sorted(_flatten(section.get("configs", {})).items()):
        path = resolve_under_root(value, label=f"configs.{name}")
        entry: dict[str, Any] = {"config": f"configs.{name}", "path": relative_to_root(path)}
        if not path.is_file():
            entry["status"] = "MISSING"
        else:
            try:
                document = read_config(path)
            except ChainError as error:
                entry["status"] = f"INVALID: {error}"
            else:
                entry["status"] = "ok"
                entry["sha256"] = sha256(path)
                pending = _pending_fields(document)
                if pending:
                    entry["pending_fields_filled_automatically_at_run_time"] = pending
                if "year_plan" in document:
                    entry["year_plan_matches_chain"] = (
                        year_plan(document).as_document() == plan.as_document()
                    )
        checks.append(entry)

    table = [*stages(section), *post_barrier_stages(section)]
    produced_by = {stage.name: index for index, stage in enumerate(table)}
    inputs_dir = resolve_under_root(section["inputs_dir"], label="inputs_dir")
    produced_paths: dict[Path, int] = {}
    flat_section = _flatten(section)
    for index, stage in enumerate(table):
        for position, item in enumerate(stage.argv):
            if position == 0 or stage.argv[position - 1] not in ("--output", "--output-dir"):
                continue
            if not (item.startswith("{") and item.endswith("}")):
                continue
            field = item[1:-1]
            if field in ("stage_dir", "run_root") or field not in flat_section:
                continue
            produced_paths[resolve_under_root(flat_section[field], label=field)] = index
    sequence: list[dict[str, Any]] = []
    order_problems: list[str] = []
    for index, stage in enumerate(table):
        command = command_for(stage, section, run_root)
        record: dict[str, Any] = {
            "stage": stage.name,
            "position": index + 1,
            "command": " ".join(command) if command else "(no program: hash barrier)",
            "outcome_access": stage.outcome_access,
        }
        pending_now: list[str] = []
        absent: list[str] = []
        for label, path in stage_declared_inputs(stage, section):
            producer: int | None = produced_paths.get(path)
            if producer is not None:
                pass
            elif path.is_relative_to(run_root):
                relative = path.relative_to(run_root)
                if relative.parts:
                    producer = produced_by.get(relative.parts[0])
            elif path.is_relative_to(inputs_dir) or path == inputs_dir:
                producer = produced_by.get("bridge")
            if producer is None:
                if not path.exists():
                    absent.append(f"{label}: {relative_to_root(path)}")
            elif producer >= index:
                order_problems.append(
                    f"stage {stage.name} (position {index + 1}) declares {label} produced "
                    f"by stage {table[producer].name} (position {producer + 1})"
                )
            else:
                pending_now.append(f"{label}: produced by stage {table[producer].name}")
        if absent:
            record["inputs_absent_and_not_produced_by_an_earlier_stage"] = absent
        if pending_now:
            record["inputs_produced_by_earlier_stages"] = len(pending_now)
        sequence.append(record)

    failures = [item for item in checks if item["status"] != "ok"]
    mismatched = [item for item in checks if item.get("year_plan_matches_chain") is False]
    absent_total = [
        item for item in sequence if item.get("inputs_absent_and_not_produced_by_an_earlier_stage")
    ]
    pending_configs = {
        item["config"]: item["pending_fields_filled_automatically_at_run_time"]
        for item in checks
        if "pending_fields_filled_automatically_at_run_time" in item
    }
    return {
        "status": "FAIL" if failures or mismatched or order_problems or absent_total else "PASS",
        "validates": "configs, stage order and input existence only; no stage is launched",
        "opens_no_outcome_file": True,
        "configs_with_pending_fields_filled_automatically": pending_configs,
        "pending_field_count": sum(len(value) for value in pending_configs.values()),
        "stage_order_problems": order_problems,
        "stages_with_absent_inputs": [item["stage"] for item in absent_total],
        "run_root": relative_to_root(run_root),
        "year_plan": plan.as_document(),
        "raw_years": list(plan.raw_years),
        "config_checks": checks,
        "configs_with_a_different_year_plan": [item["config"] for item in mismatched],
        "sequence": sequence,
        "report_runs_only_with_run_--include-report_or_the_report_command": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command", choices=["print", "write-configs", "dry-run", "run", "report", "verify"]
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--from", dest="start", help="first stage to run")
    parser.add_argument("--to", dest="stop", help="last stage to run")
    parser.add_argument(
        "--include-report",
        action="store_true",
        help="run: continue into the report stage in the same invocation, after the barrier. "
        "This is the unattended end-to-end path; it joins target labels.",
    )
    args = parser.parse_args(argv)

    document = read_config(args.config)
    plan = year_plan(document)
    section = document.get("chain")
    if not isinstance(section, dict):
        raise ChainError("configuration has no chain object")
    check_floor_consistency(section, plan)
    run_root = resolve_under_root(section["run_root"], label="run_root")
    table = stages(section)
    names = [stage.name for stage in table]
    after_barrier = post_barrier_stages(section)

    if args.command == "print":
        lines = [
            f"# {experiment_of(section)} chain ({tour_of(section)}), target years "
            f"{list(plan.target_years)} (derived raw years {list(plan.raw_years)})",
            "# Single-threaded BLAS is part of the numerical contract:",
            "export " + " ".join(f"{key}={value}" for key, value in ENVIRONMENT.items()),
            "",
        ]
        for stage in table:
            command = command_for(stage, section, run_root)
            lines.append(f"# {stage.name}" + (f" -- {stage.note}" if stage.note else ""))
            if stage.outcome_access != "none":
                lines.append(
                    f"#   OUTCOME ACCESS ({stage.outcome_access}): log the exposure event before running."
                )
            lines.append(
                " ".join(command)
                if command
                else "#   (hash barrier: run --from barrier --to barrier)"
            )
            lines.append("")
        lines.append("# Stop. Timestamp the barrier's run_tree_sha256 externally.")
        lines.append("# Then, and only then, the separate scoring commands:")
        for stage in after_barrier:
            lines.append(" ".join(command_for(stage, section, run_root)))
        print("\n".join(lines))
        return 0

    if args.command == "write-configs":
        print(json.dumps(write_configs(document, section, plan), indent=2, sort_keys=True))
        return 0

    if args.command == "dry-run":
        report = dry_run(section, run_root, plan)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "PASS" else 1

    if args.command == "verify":
        all_names = [*names, *(stage.name for stage in after_barrier)]
        present = [name for name in all_names if (run_root / name / STAGE_MANIFEST).is_file()]
        verified = verify_earlier(run_root, present)
        entries = verify_ledger(run_root)
        if not present or present != all_names[: len(present)]:
            raise ChainError("completed stages are empty or not a configured prefix")
        verify_stage_records(run_root, present)
        integrity = verify_integrity(
            run_root,
            present,
            stage_table=[*table, *after_barrier],
            panel_end_year=plan.panel_end_year,
        )
        print(
            json.dumps(
                {
                    "stages_verified": verified,
                    "ledger_entries": len(entries),
                    "integrity": integrity,
                },
                sort_keys=True,
            )
        )
        if integrity["problems"]:
            raise ChainError(f"integrity verification failed: {integrity['problems'][0]}")
        return 0

    if args.command == "report":
        verify_earlier(run_root, names)
        completed_names = list(names)
        for stage in after_barrier:
            manifest = run_stage(
                stage,
                section,
                run_root,
                earlier=completed_names,
                panel_end_year=plan.panel_end_year,
            )
            completed_names.append(stage.name)
            print(
                json.dumps(
                    {
                        "stage": stage.name,
                        "exit_status": manifest["exit_status"],
                        "outputs": manifest["output_count"],
                    },
                    sort_keys=True,
                )
            )
        return 0

    start = names.index(args.start) if args.start else 0
    stop = names.index(args.stop) if args.stop else len(names) - 1
    if start > stop:
        raise ChainError(f"--from {args.start} comes after --to {args.stop}")
    results = []
    barrier_digest = None
    for position in range(start, stop + 1):
        stage = table[position]
        manifest = run_stage(
            stage, section, run_root, earlier=names[:position], panel_end_year=plan.panel_end_year
        )
        if stage.name == "barrier":
            barrier_digest = manifest["run_tree_sha256"]
        results.append(
            {
                "stage": stage.name,
                "seconds": manifest["wall_clock_seconds"],
                "outputs": manifest["output_count"],
            }
        )
        print(json.dumps(results[-1], sort_keys=True), flush=True)
    if args.include_report:
        if stop != len(names) - 1:
            raise ChainError("--include-report requires the run to reach the last stage")
        print(
            json.dumps(
                {
                    "notice": "continuing into the report stage in this same invocation; "
                    "target-year labels are joined from here on",
                    "barrier_run_tree_sha256": barrier_digest,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        completed_names = list(names)
        for stage in after_barrier:
            manifest = run_stage(
                stage,
                section,
                run_root,
                earlier=completed_names,
                panel_end_year=plan.panel_end_year,
            )
            completed_names.append(stage.name)
            results.append(
                {
                    "stage": stage.name,
                    "seconds": manifest["wall_clock_seconds"],
                    "outputs": manifest["output_count"],
                }
            )
            print(json.dumps(results[-1], sort_keys=True), flush=True)
    print(
        json.dumps(
            {
                "stages_completed": results,
                "barrier_run_tree_sha256": barrier_digest,
                "report_still_to_run": None
                if args.include_report
                else "python -m tennislab.chain.runner report --config <chain.json>",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
