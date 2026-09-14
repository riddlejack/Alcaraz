#!/usr/bin/env python3
"""Stage-by-stage equivalence of the ported chain against an accepted archive run.

The archive run wrote, per stage, a ``stage_manifest.json`` recording the exact command
and the sha256 of every output file. This tool builds a scratch *workspace* whose
read-only parts are symbolic links into the archive and whose stage-under-test directory
is real, runs the ported module with the archive's own argv, and compares every output
by hash.

    export TENNISLAB_ARCHIVE=/path/to/the/research/archive
    uv run python tools/equivalence.py run --run TIER01/attempt_002 --stage archive_panel
    uv run python tools/equivalence.py compare --run TIER01/attempt_002 --stage archive_panel

``run`` prepares the workspace, executes the stage and compares. Results are written to
``docs/equivalence/<run>/<stage>.json`` and summarised on stdout. Nothing is written
inside the archive. The tracked record replaces host prefixes (archive root, repository
root, site-packages) with placeholders; the original goes to ``local/evidence/`` (see
``tennislab.evidence``).
"""

from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tennislab.evidence import host_placeholders, write_evidence

REPO = Path(__file__).resolve().parents[1]
STAGE_MANIFEST = "stage_manifest.json"
THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


@dataclass(frozen=True)
class RunSpec:
    name: str
    work_dir: str  # the archive's live run directory (paths inside configs)
    frozen_dir: str  # the archive's preserved copy with stage manifests
    stages: tuple[str, ...]
    modules: dict[str, str]  # stage -> ported module (python -m)
    inputs_stage: str = "bridge"  # the stage that writes <work_dir>/inputs
    side_dirs: tuple[str, ...] = ("predictor_config", "reporting_config")


ATP_STAGES = (
    "bridge",
    "archive_panel",
    "join",
    "event_carry_forward",
    "prepare_panel",
    "format_corrections",
    "rule_mapping",
    "sr02_replay",
    "sr03_calibration",
    "rankings",
    "edition_index",
    "features",
    "sidecar",
    "tier_stream",
    "tier_elo",
    "sr02_tier_replay",
    "sr02_tier_noqual_replay",
    "tier_block",
    "predictor_config",
    "preflight",
    "pipeline",
    "barrier",
    "reporting_config",
    "report",
)
WTA_STAGES = (
    "bridge",
    "archive_panel",
    "event_carry_forward",
    "join",
    "prepare_panel",
    "format_corrections",
    "rule_mapping",
    "sr02_replay",
    "sr03_calibration",
    "rankings",
    "edition_index",
    "features",
    "sidecar",
    "predictor_config",
    "preflight",
    "pipeline",
    "barrier",
    "reporting_config",
    "report",
)

# Stage -> ported module. A stage absent here has not been ported yet.
MODULES: dict[str, str] = {
    "bridge": "tennislab.sources.bridge",
    "archive_panel": "tennislab.panel.archive_panel",
    "join": "tennislab.panel.join",
    "event_carry_forward": "tennislab.panel.crosswalk_carry",
    "prepare_panel": "tennislab.panel.prepare",
    "format_corrections": "tennislab.panel.format_corrections",
    "rule_mapping": "tennislab.panel.rules",
    "sr02_replay": "tennislab.dynamics.replay",
    "sr02_tier_replay": "tennislab.dynamics.replay",
    "sr02_tier_noqual_replay": "tennislab.dynamics.replay",
    "sr03_calibration": "tennislab.dynamics.calibrate",
    "rankings": "tennislab.panel.rankings",
    "edition_index": "tennislab.chronology.edition_index",
    "features": "tennislab.features.base",
    "sidecar": "tennislab.features.sidecar",
    "tier_stream": "tennislab.ratings.tier_stream",
    "tier_elo": "tennislab.ratings.tier_elo",
    "tier_block": "tennislab.features.tier_block",
    "predictor_config": "tennislab.chain.configs",
    "preflight": "tennislab.models.pipeline",
    "pipeline": "tennislab.models.pipeline",
    "reporting_config": "tennislab.chain.configs",
    "report": "tennislab.evaluation.report",
}
WTA_MODULES = {
    **MODULES,
    "event_carry_forward": "tennislab.panel.wta_crosswalk_carry",
    "join": "tennislab.panel.wta_join",
    "rule_mapping": "tennislab.panel.wta_rules",
}

RUNS = {
    "TIER01/attempt_002": RunSpec(
        "TIER01/attempt_002",
        "work/TIER01/run_002",
        "experiments/runs/TIER01/attempt_002",
        ATP_STAGES,
        MODULES,
    ),
    "WTA02/attempt_002": RunSpec(
        "WTA02/attempt_002",
        "work/WTA02/run_002",
        "experiments/runs/WTA02/attempt_002",
        WTA_STAGES,
        WTA_MODULES,
    ),
}


def archive_root() -> Path:
    value = os.environ.get("TENNISLAB_ARCHIVE")
    if not value:
        sys.exit("set TENNISLAB_ARCHIVE to the research archive's root directory")
    root = Path(value)
    if not (root / "experiments" / "runs").is_dir():
        sys.exit(f"TENNISLAB_ARCHIVE does not look like the archive: {root}")
    return root


def workspace_root(spec: RunSpec, stage: str) -> Path:
    """One scratch workspace per run *and* stage, so stages can be checked in parallel."""
    return REPO / "data" / "runs" / "equivalence" / spec.name.replace("/", "_") / stage


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_tree(base: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not base.exists():
        return entries
    for path in sorted(item for item in base.rglob("*") if item.is_file()):
        relative = path.relative_to(base).as_posix()
        if "__pycache__" in relative or relative.endswith(".pyc") or relative == STAGE_MANIFEST:
            continue
        entries[relative] = sha256(path)
    return entries


def link(target: Path, name: Path) -> None:
    if name.is_symlink() or name.exists():
        if name.is_symlink() or name.is_file():
            name.unlink()
        else:
            shutil.rmtree(name)
    name.symlink_to(target)


def fresh_dir(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def prepare(spec: RunSpec, stage: str, archive: Path) -> Path:
    """Build the scratch workspace: links into the archive, a real dir for ``stage``."""
    ws = workspace_root(spec, stage)
    ws.mkdir(parents=True, exist_ok=True)
    for top in ("data", "references", "experiments"):
        link(archive / top, ws / top)
    work = ws / "work"
    work.mkdir(exist_ok=True)
    run_top = Path(spec.work_dir).parts[1]  # e.g. TIER01
    for child in sorted((archive / "work").iterdir()):
        if child.name != run_top:
            link(child, work / child.name)
    live = ws / spec.work_dir
    live.mkdir(parents=True, exist_ok=True)
    for child in sorted((archive / Path(spec.work_dir).parent).iterdir()):
        if child.name != Path(spec.work_dir).name:
            link(child, live.parent / child.name)
    frozen = archive / spec.frozen_dir
    link(frozen / "configs", live / "configs")
    if stage == spec.inputs_stage:
        fresh_dir(live / "inputs")
    else:
        link(frozen / "inputs", live / "inputs")
    for side in spec.side_dirs:
        if stage == side:
            fresh_dir(live / side)
        elif (frozen / side).exists():
            link(frozen / side, live / side)
    run = live / "run"
    run.mkdir(exist_ok=True)
    for name in run.iterdir():
        if name.is_symlink():
            name.unlink()
        elif name.is_dir():
            shutil.rmtree(name)
        else:
            name.unlink()
    for earlier in spec.stages[: spec.stages.index(stage)]:
        if (frozen / "run" / earlier).exists():
            link(frozen / "run" / earlier, run / earlier)
    fresh_dir(run / stage)
    ledger = frozen / "run" / "chain_ledger.jsonl"
    if ledger.exists():
        shutil.copyfile(ledger, run / "chain_ledger.jsonl")
    return ws


def archive_argv(spec: RunSpec, stage: str, archive: Path) -> list[str]:
    manifest = json.loads((archive / spec.frozen_dir / "run" / stage / STAGE_MANIFEST).read_text())
    command: list[str] = list(manifest["command"])
    if not command:
        return []
    # [python, -B, program, *args] or [python, -B, <program-as-arg>, *args] for `sidecar`
    args = command[3:]
    prefix = str(archive) + "/"
    return [item.replace(prefix, "") if item.startswith(prefix) else item for item in args]


def run_stage(spec: RunSpec, stage: str, archive: Path, module: str | None) -> int:
    ws = prepare(spec, stage, archive)
    module = module or spec.modules.get(stage)
    argv = archive_argv(spec, stage, archive)
    stage_dir = ws / spec.work_dir / "run" / stage
    if not argv:
        print(f"{stage}: no program (barrier); nothing to run")
        return 0
    if module is None:
        sys.exit(f"{stage}: no ported module declared in MODULES")
    command = [sys.executable, "-B", "-m", module, *argv]
    env = {**os.environ, **THREADS, "TENNISLAB_WORKSPACE": str(ws), "PYTHONHASHSEED": "0"}
    print("+", " ".join(command))
    completed = subprocess.run(
        command, cwd=ws, env=env, capture_output=True, text=True, check=False
    )
    (stage_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (stage_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        print(completed.stderr[-4000:])
        print(f"{stage}: exited {completed.returncode}")
    return completed.returncode


def _load_text(path: Path) -> str | None:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return handle.read()
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError, OSError:
        return None


def _json_leaf_diff(a: Any, b: Any, prefix: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            out.extend(
                _json_leaf_diff(a.get(key, "<absent>"), b.get(key, "<absent>"), f"{prefix}{key}.")
            )
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            out.extend(_json_leaf_diff(x, y, f"{prefix}{index}."))
    elif a != b:
        out.append(f"{prefix.rstrip('.')}: {json.dumps(a)[:120]} -> {json.dumps(b)[:120]}")
    return out


def describe_difference(expected: Path, observed: Path) -> dict[str, Any]:
    text_e, text_o = _load_text(expected), _load_text(observed)
    if text_e is None or text_o is None:
        return {"kind": "binary"}
    if expected.name.endswith(".json"):
        try:
            leaves = _json_leaf_diff(json.loads(text_e), json.loads(text_o))
            return {"kind": "json", "changed_leaves": len(leaves), "first": leaves[:40]}
        except json.JSONDecodeError:
            pass
    lines_e, lines_o = text_e.splitlines(), text_o.splitlines()
    diff = list(difflib.unified_diff(lines_e, lines_o, "archive", "ported", n=0, lineterm=""))
    changed = sum(1 for line in diff if line[:1] in "+-" and line[:3] not in ("+++", "---"))
    return {
        "kind": "text",
        "lines_archive": len(lines_e),
        "lines_ported": len(lines_o),
        "changed_lines": changed,
        "first": diff[2:42],
    }


def compare(spec: RunSpec, stage: str, archive: Path) -> dict[str, Any]:
    ws = workspace_root(spec, stage)
    frozen_stage = archive / spec.frozen_dir / "run" / stage
    manifest = json.loads((frozen_stage / STAGE_MANIFEST).read_text())
    expected = {name: rec["sha256"] for name, rec in manifest["outputs"].items()}
    observed = hash_tree(ws / spec.work_dir / "run" / stage)
    result: dict[str, Any] = {
        "run": spec.name,
        "stage": stage,
        "identical": [],
        "different": {},
        "missing": [],
        "extra": [],
    }
    for name, digest in expected.items():
        if name not in observed:
            result["missing"].append(name)
        elif observed[name] == digest:
            result["identical"].append(name)
        else:
            result["different"][name] = describe_difference(
                frozen_stage / name, ws / spec.work_dir / "run" / stage / name
            )
    result["extra"] = sorted(set(observed) - set(expected))
    if stage == spec.inputs_stage:
        exp_inputs = hash_tree(archive / spec.frozen_dir / "inputs")
        obs_inputs = hash_tree(ws / spec.work_dir / "inputs")
        result["inputs_tree"] = {
            "identical": sorted(k for k in exp_inputs if obs_inputs.get(k) == exp_inputs[k]),
            "different": sorted(
                k for k in exp_inputs if k in obs_inputs and obs_inputs[k] != exp_inputs[k]
            ),
            "missing": sorted(set(exp_inputs) - set(obs_inputs)),
            "extra": sorted(set(obs_inputs) - set(exp_inputs)),
        }
    for side in spec.side_dirs:
        if stage == side:
            exp_side = hash_tree(archive / spec.frozen_dir / side)
            obs_side = hash_tree(ws / spec.work_dir / side)
            result["side_tree"] = {
                "identical": sorted(k for k in exp_side if obs_side.get(k) == exp_side[k]),
                "different": {
                    k: describe_difference(
                        archive / spec.frozen_dir / side / k, ws / spec.work_dir / side / k
                    )
                    for k in sorted(exp_side)
                    if k in obs_side and obs_side[k] != exp_side[k]
                },
                "missing": sorted(set(exp_side) - set(obs_side)),
                "extra": sorted(set(obs_side) - set(exp_side)),
            }
    write_record(archive, spec, f"{stage}.json", result)
    return result


def write_record(archive: Path, spec: RunSpec, name: str, record: dict[str, Any]) -> None:
    """The tracked placeholder representation under ``docs/equivalence/<run>/`` and the
    original under ``local/evidence/``."""
    relative = Path("docs") / "equivalence" / spec.name.replace("/", "_") / name
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    write_evidence(REPO, relative, text, host_placeholders(repo_root=REPO, archive_root=archive))


def summarize(result: dict[str, Any]) -> None:
    print(f"== {result['run']} / {result['stage']}")
    print(
        f"identical: {len(result['identical'])}  different: {len(result['different'])}  "
        f"missing: {len(result['missing'])}  extra: {len(result['extra'])}"
    )
    for name, info in result["different"].items():
        head = info.get("first", [])
        print(
            f"  ~ {name}: {info['kind']}"
            + (f" changed_leaves={info['changed_leaves']}" if "changed_leaves" in info else "")
            + (f" changed_lines={info['changed_lines']}" if "changed_lines" in info else "")
        )
        for line in head[:8]:
            print(f"      {line}")
    for name in result["missing"]:
        print(f"  - missing {name}")
    for name in result["extra"]:
        print(f"  + extra {name}")
    for key in ("inputs_tree", "side_tree"):
        if key in result:
            tree = result[key]
            print(
                f"  {key}: identical={len(tree['identical'])} different={len(tree['different'])} "
                f"missing={len(tree['missing'])} extra={len(tree['extra'])}"
            )
            for name in list(tree["different"])[:10]:
                print(f"      ~ {name}")


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "chain":
        return chain_main(raw[1:])
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--run", required=True, choices=sorted(RUNS))
        p.add_argument("--stage", required=True)
        p.add_argument("--module", help="override the ported module for this stage")
    args = parser.parse_args(argv)
    spec = RUNS[args.run]
    if args.stage not in spec.stages:
        sys.exit(f"unknown stage {args.stage!r}; stages: {', '.join(spec.stages)}")
    archive = archive_root()
    if args.command == "prepare":
        print(prepare(spec, args.stage, archive))
        return 0
    if args.command == "run":
        status = run_stage(spec, args.stage, archive, args.module)
        summarize(compare(spec, args.stage, archive))
        return status
    summarize(compare(spec, args.stage, archive))
    return 0


# ------------------------------------------------------------------ full chain runs


def prepare_chain_workspace(spec: RunSpec, archive: Path) -> Path:
    """A workspace with every archive input linked and an empty live run directory.

    The frozen stage configs are *copied* (the driver writes ``<name>.filled.json``
    beside them); nothing under the archive is written.
    """
    ws = REPO / "data" / "runs" / "equivalence" / spec.name.replace("/", "_") / "_chain"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    for top in ("data", "references", "experiments"):
        link(archive / top, ws / top)
    work = ws / "work"
    work.mkdir()
    run_top = Path(spec.work_dir).parts[1]
    for child in sorted((archive / "work").iterdir()):
        if child.name != run_top:
            link(child, work / child.name)
    live = ws / spec.work_dir
    live.mkdir(parents=True)
    for child in sorted((archive / Path(spec.work_dir).parent).iterdir()):
        if child.name != Path(spec.work_dir).name:
            link(child, live.parent / child.name)
    frozen = archive / spec.frozen_dir
    shutil.copytree(frozen / "configs", live / "configs")
    for stale in (live / "configs").glob("*.filled.json"):
        stale.unlink()
    return ws


def run_chain(spec: RunSpec, archive: Path, chain_config: Path, start: str | None = None) -> int:
    ws = REPO / "data" / "runs" / "equivalence" / spec.name.replace("/", "_") / "_chain"
    if start is None:
        ws = prepare_chain_workspace(spec, archive)
    env = {**os.environ, **THREADS, "TENNISLAB_WORKSPACE": str(ws), "PYTHONHASHSEED": "0"}
    command = [
        sys.executable,
        "-B",
        "-m",
        "tennislab.chain.runner",
        "run",
        "--include-report",
        "--config",
        str(chain_config),
    ]
    if start:
        command += ["--from", start]
    print("+", " ".join(command), f"(workspace {ws})")
    completed = subprocess.run(command, cwd=ws, env=env, check=False)
    return completed.returncode


def compare_chain(spec: RunSpec, archive: Path) -> dict[str, Any]:
    """Compare every stage of the live chain run against the frozen run, plus the side trees."""
    ws = REPO / "data" / "runs" / "equivalence" / spec.name.replace("/", "_") / "_chain"
    frozen = archive / spec.frozen_dir
    summary: dict[str, Any] = {"run": spec.name, "stages": {}}
    for stage in spec.stages:
        manifest_path = frozen / "run" / stage / STAGE_MANIFEST
        if not manifest_path.exists():
            continue
        expected = {
            k: v["sha256"] for k, v in json.loads(manifest_path.read_text())["outputs"].items()
        }
        observed = hash_tree(ws / spec.work_dir / "run" / stage)
        different = {
            name: describe_difference(
                frozen / "run" / stage / name, ws / spec.work_dir / "run" / stage / name
            )
            for name in expected
            if name in observed and observed[name] != expected[name]
        }
        summary["stages"][stage] = {
            "identical": sorted(k for k in expected if observed.get(k) == expected[k]),
            "different": different,
            "missing": sorted(set(expected) - set(observed)),
            "extra": sorted(set(observed) - set(expected)),
        }
    for side in ("inputs", *spec.side_dirs):
        exp = hash_tree(frozen / side)
        obs = hash_tree(ws / spec.work_dir / side)
        summary[side] = {
            "identical": sorted(k for k in exp if obs.get(k) == exp[k]),
            "different": sorted(k for k in exp if k in obs and obs[k] != exp[k]),
            "missing": sorted(set(exp) - set(obs)),
            "extra": sorted(set(obs) - set(exp)),
        }
    write_record(archive, spec, "_chain.json", summary)
    for stage, block in summary["stages"].items():
        print(
            f"{stage:26s} identical={len(block['identical']):4d} different={len(block['different']):3d} "
            f"missing={len(block['missing'])} extra={len(block['extra'])}"
            + ("" if not block["different"] else "  ~ " + ", ".join(list(block["different"])[:6]))
        )
    for side in ("inputs", *spec.side_dirs):
        b = summary[side]
        print(
            f"{side:26s} identical={len(b['identical'])} different={b['different']} missing={b['missing']} extra={b['extra']}"
        )
    return summary


def chain_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="equivalence.py chain")
    parser.add_argument("--run", required=True, choices=sorted(RUNS))
    parser.add_argument(
        "--chain-config",
        type=Path,
        required=True,
        help="the archive chain config (paths relative to the workspace)",
    )
    parser.add_argument("--compare-only", action="store_true")
    parser.add_argument(
        "--from", dest="start", help="resume an existing chain workspace from this stage"
    )
    args = parser.parse_args(argv)
    spec = RUNS[args.run]
    archive = archive_root()
    status = 0
    if not args.compare_only:
        status = run_chain(spec, archive, args.chain_config, args.start)
    compare_chain(spec, archive)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
