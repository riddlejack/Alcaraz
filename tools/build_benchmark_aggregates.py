"""Build the product benchmark JSONs from archive result files; no number is typed by hand.

``docs/benchmarks/sources.json`` lists each output with its sources: a path relative to a
named root (default ``archive``, the research archive) and the sha256 the file must have.
Every source is hashed before it is read; a mismatch stops the build. An output is either a
byte copy of one source (``copy``) or a template (``template``): a JSON document whose values
are literal text or directives that read the sources.

Directives (string values; a key starting with ``@`` splices a directive's object in place):

- ``@value SRC:PATH`` copies a value; ``@name SRC:PATH`` copies an arm name, renamed by the
  output's ``arm_names``.
- ``@contrast SRC:PATH`` reshapes a scorer contrast (``references/ARMS01/score_arms01.py``)
  into the product layout: match-weighted scores, difference, intervals and draws per block,
  bootstrap grid, equal-year interval, variance diagnostics. ``@contrast_detailed`` also keeps
  the log-loss draw hash per block and the equal-year bootstrap SD.
- ``@file SRC`` gives ``{archive_relative_path, sha256}`` of a source; ``@binding SRC:PATH``
  converts a scorer binding ``{path, sha256}`` to that form; ``@forecast_files SRC`` does so
  for every arm's forecast files; ``@per_arm SRC FIELD`` collects one field per arm.
- ``{{alias:path|pipe}}`` inside a text value is filled with ``tennislab.numbers`` (the language
  of the pages); aliases are the source names and ``out`` (the output being built).
- ``@@`` at the start of a string is a literal ``@``.

``checks`` in an output's entry lists reference pairs that must hold equal values before
anything is written (``{each}`` in a reference is replaced by every item of ``each``).

A tracked output names no host: the archive and repository root prefixes are replaced by the
placeholders of ``tennislab.evidence`` (``<ARCHIVE_ROOT>``, ``<PRODUCT_ROOT>``), and the original
bytes are kept in the ignored ``local/evidence/`` store. Every other byte of a copy is unchanged.

Statuses: ``accepted`` outputs are committed results and are never written, only checked
byte for byte; ``extension`` outputs are written; ``pending`` outputs have a source whose hash
is not frozen yet and are skipped (``--source NAME=PATH`` builds one from a named file for a
dry run into ``--out-dir``, without the hash check).

Usage (from the repository root; standard library and ``tennislab.numbers`` only)::

    uv run python tools/build_benchmark_aggregates.py --archive-root "$TENNISLAB_ARCHIVE"          # write
    uv run python tools/build_benchmark_aggregates.py --archive-root "$TENNISLAB_ARCHIVE" --check  # verify
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from tennislab.evidence import host_placeholders, portable_text, write_evidence
from tennislab.numbers import NumbersError, lookup, render_text

SOURCES = Path("docs/benchmarks/sources.json")
METRICS = ("log_loss", "brier", "accuracy")
EQUAL_YEAR = (
    "mean_block_weeks",
    "percentile_95",
    "draws_attempted",
    "empty_draws_skipped",
    "draw_sha256",
)
EQUAL_YEAR_DETAILED = (
    "draws_attempted",
    "empty_draws_skipped",
    "mean_block_weeks",
    "percentile_95",
    "bootstrap_sd",
    "draw_sha256",
)


class BuildError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def contrast_block(
    contrast: dict[str, Any], rename: dict[str, str], detailed: bool = False
) -> dict[str, Any]:
    """The product layout of a scorer contrast; ``detailed`` adds the log-loss draw hash per
    block and the equal-year bootstrap SD (the layout of the WTA product JSON)."""
    uncertainty = contrast["uncertainty"]
    results = uncertainty["results"]
    blocks = sorted(results, key=int)
    equal_year = contrast["equal_year_interval_log_loss"]
    return {
        "left": rename.get(contrast["left"], contrast["left"]),
        "right": rename.get(contrast["right"], contrast["right"]),
        "years": contrast["years"],
        "n": contrast["n"],
        "left_match_weighted": contrast["left_scores"]["match_weighted"],
        "right_match_weighted": contrast["right_scores"]["match_weighted"],
        "difference": contrast["difference"],
        "primary_interval_log_loss": contrast["primary_interval_log_loss"],
        "intervals_95": {m: {b: results[b][m]["percentile_95"] for b in blocks} for m in METRICS},
        "bootstrap_sd_log_loss": {b: results[b]["log_loss"]["bootstrap_sd"] for b in blocks},
        "draws": {
            b: {
                "draws_attempted": results[b]["draws_attempted"],
                "empty_draws_skipped": results[b]["empty_draws_skipped"],
                **(
                    {"log_loss_draw_sha256": results[b]["log_loss"]["draw_sha256"]}
                    if detailed
                    else {}
                ),
                "joint_draw_sha256": results[b]["joint_draw_sha256"],
            }
            for b in blocks
        },
        "grid": {
            "first_monday": uncertainty["grid_first_monday"],
            "last_monday": uncertainty["grid_last_monday"],
            "weeks_including_empty": uncertainty["grid_weeks"],
            "nonempty_weeks": uncertainty["nonempty_weeks"],
        },
        "equal_year_interval_log_loss": {
            key: equal_year[key] for key in (EQUAL_YEAR_DETAILED if detailed else EQUAL_YEAR)
        },
        "variance_diagnostics": contrast["variance_diagnostics"],
        "orientation_control_max_error": contrast["orientation_control_max_error"],
    }


class Builder:
    def __init__(
        self,
        target: dict[str, Any],
        files: dict[str, Path],
        sources: dict[str, Any],
        archive_root: Path,
    ):
        self.target = target
        self.files = files  # source name -> absolute path
        self.sources = sources  # source name -> parsed JSON (JSON sources only)
        self.rename: dict[str, str] = target.get("arm_names", {})
        self.archive_root = archive_root

    def data(self, name: str) -> Any:
        if name not in self.sources:
            raise BuildError(f"{self.target['output']}: unknown or non-JSON source {name!r}")
        return self.sources[name]

    def ref(self, argument: str) -> Any:
        name, sep, path = argument.partition(":")
        if not sep:
            raise BuildError(f"expected SRC:PATH, got {argument!r}")
        try:
            return copy.deepcopy(lookup(self.data(name), path))
        except NumbersError as exc:
            raise BuildError(f"{self.target['output']}: {exc}") from None

    def relative(self, recorded: str) -> str:
        path = Path(recorded)
        try:
            return path.relative_to(self.archive_root).as_posix()
        except ValueError:
            raise BuildError(f"binding {recorded} is outside the archive root") from None

    def binding(self, value: dict[str, Any]) -> dict[str, Any]:
        out = {"archive_relative_path": self.relative(value["path"]), "sha256": value["sha256"]}
        if "column" in value:
            out["column"] = value["column"]
        return out

    def directive(self, text: str) -> Any:
        op, _, argument = text[1:].partition(" ")
        if op == "value":
            return self.ref(argument)
        if op == "name":
            name = self.ref(argument)
            return self.rename.get(name, name)
        if op in ("contrast", "contrast_detailed"):
            return contrast_block(self.ref(argument), self.rename, op == "contrast_detailed")
        if op == "file":
            spec = self.target["sources"][argument]
            return {"archive_relative_path": spec["path"], "sha256": sha256(self.files[argument])}
        if op == "binding":
            return self.binding(self.ref(argument))
        if op == "forecast_files":
            arms = self.data(argument)["arms"]
            return {
                self.rename.get(arm, arm): {
                    year: self.binding(binding) for year, binding in report["bindings"].items()
                }
                for arm, report in arms.items()
            }
        if op == "per_arm":
            name, _, field = argument.partition(" ")
            arms = self.data(name)["arms"]
            return {self.rename.get(arm, arm): report[field] for arm, report in arms.items()}
        raise BuildError(f"{self.target['output']}: unknown directive {text!r}")

    def expand(self, node: Any) -> Any:
        if isinstance(node, str):
            if node.startswith("@@"):
                return node[1:]
            return self.directive(node) if node.startswith("@") else node
        if isinstance(node, list):
            return [self.expand(item) for item in node]
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for key, value in node.items():
                if key.startswith("@"):
                    spliced = self.expand(value)
                    if not isinstance(spliced, dict):
                        raise BuildError(f"splice {key} did not yield an object")
                    clash = set(spliced) & set(out)
                    if clash:
                        raise BuildError(f"splice {key} repeats keys {sorted(clash)}")
                    out.update(spliced)
                else:
                    out[key] = self.expand(value)
            return out
        return node

    def fill_text(self, node: Any, built: Any) -> Any:
        def resolve(alias: str, path: str) -> Any:
            return lookup(built if alias == "out" else self.data(alias), path)

        if isinstance(node, str) and "{{" in node:
            try:
                return render_text(node, resolve)
            except NumbersError as exc:
                raise BuildError(f"{self.target['output']}: {exc}") from None
        if isinstance(node, list):
            return [self.fill_text(item, built) for item in node]
        if isinstance(node, dict):
            return {key: self.fill_text(value, built) for key, value in node.items()}
        return node

    def build(self, template: Any) -> Any:
        failures = self.run_checks()
        if failures:
            raise BuildError(
                f"{self.target['output']}: {len(failures)} check(s) failed: " + "; ".join(failures)
            )
        built = self.expand(template)
        return self.fill_text(built, built)

    def run_checks(self) -> list[str]:
        """``checks``: pairs of references that must hold equal values, for example the
        accepted seasons of an extended result against the accepted result; a right-hand
        side of ``=value`` compares with the check's literal ``value``."""
        failures = []
        self.checked = 0
        for check in self.target.get("checks", []):
            for item in check.get("each", [None]):
                left, right = (
                    ref if item is None else ref.replace("{each}", str(item))
                    for ref in check["equal"]
                )
                a = self.ref(left)
                b = check["value"] if right == "=value" else self.ref(right)
                self.checked += 1
                if a != b:
                    failures.append(f"{left} = {a!r:.60} differs from {right} = {b!r:.60}")
        return failures


def resolve_sources(
    target: dict[str, Any], roots: dict[str, Path], overrides: dict[str, Path]
) -> tuple[dict[str, Path], list[str]]:
    """Absolute source paths, verified by hash; problems instead of paths when unavailable."""
    files: dict[str, Path] = {}
    problems: list[str] = []
    for name, spec in target["sources"].items():
        if name in overrides:
            files[name] = overrides[name]
            continue
        root_name = spec.get("root", "archive")
        if root_name not in roots:
            problems.append(
                f"source {name}: root {root_name!r} not given (--root {root_name}=PATH)"
            )
            continue
        path = roots[root_name] / spec["path"]
        if spec.get("sha256") is None:
            problems.append(f"source {name}: {spec['path']} has no frozen sha256 yet")
            continue
        if not path.is_file():
            problems.append(f"source {name}: {spec['path']} does not exist")
            continue
        digest = sha256(path)
        if digest != spec["sha256"]:
            raise BuildError(
                f"{target['output']}: source {name} {spec['path']} has sha256 {digest}, "
                f"sources.json binds {spec['sha256']}"
            )
        files[name] = path
    return files, problems


def build_target(
    repo: Path, target: dict[str, Any], roots: dict[str, Path], overrides: dict[str, Path]
) -> tuple[str | None, list[str]]:
    files, problems = resolve_sources(target, roots, overrides)
    if problems:
        return None, problems
    if "copy" in target:
        return files[target["copy"]].read_text(encoding="utf-8"), []
    sources = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in files.items()
        if path.suffix == ".json"
    }
    template = json.loads((repo / target["template"]).read_text(encoding="utf-8"))
    builder = Builder(target, files, sources, roots["archive"])
    text = dump(builder.build(template))
    return text, [f"{builder.checked} checks passed"] if builder.checked else []


def json_differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Leaf-level differences, and key-order differences, between two JSON documents."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for key in expected.keys() - actual.keys():
            out.append(f"{path}/{key}: missing from the build")
        for key in actual.keys() - expected.keys():
            out.append(f"{path}/{key}: only in the build")
        for key in expected.keys() & actual.keys():
            out += json_differences(expected[key], actual[key], f"{path}/{key}")
        if not out and list(expected) != list(actual):
            out.append(f"{path}: same keys, different order")
        return out
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        return [
            d
            for i, (e, a) in enumerate(zip(expected, actual, strict=True))
            for d in json_differences(e, a, f"{path}/{i}")
        ]
    if type(expected) is not type(actual) or expected != actual:
        return [f"{path}: committed {expected!r:.80} != built {actual!r:.80}"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path("."), help="product repository root")
    parser.add_argument("--sources", type=Path, default=SOURCES)
    parser.add_argument("--archive-root", type=Path, default=os.environ.get("TENNISLAB_ARCHIVE"))
    parser.add_argument("--root", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--only", action="append", help="build only this output (repeatable)")
    parser.add_argument("--check", action="store_true", help="compare builds with committed files")
    parser.add_argument("--out-dir", type=Path, help="write outputs here instead of the repository")
    parser.add_argument(
        "--source", action="append", default=[], metavar="NAME=PATH", help="dry-run override"
    )
    args = parser.parse_args(argv)
    if args.archive_root is None:
        parser.error("--archive-root or TENNISLAB_ARCHIVE is required")
    roots = {"archive": args.archive_root.resolve()}
    for item in args.root:
        name, _, path = item.partition("=")
        roots[name] = Path(path).resolve()
    overrides = {k: Path(v).resolve() for k, _, v in (s.partition("=") for s in args.source)}
    if overrides and not (args.out_dir and args.only):
        parser.error(
            "--source needs --only and --out-dir (an override is never written to the repository)"
        )
    registry = json.loads((args.repo / args.sources).read_text(encoding="utf-8"))
    targets = [t for t in registry["targets"] if not args.only or t["output"] in args.only]
    placeholders = host_placeholders(repo_root=args.repo.resolve(), archive_root=roots["archive"])
    failed = False
    for target in targets:
        output = target["output"]
        committed = args.repo / output
        try:
            text, problems = build_target(args.repo, target, roots, overrides)
        except (BuildError, KeyError) as exc:
            print(f"ERROR {output}: {exc}")
            failed = True
            continue
        if text is None:
            print(f"PENDING {output}: " + "; ".join(problems))
            failed |= target["status"] != "pending"
            continue
        # A tracked file names no host: host prefixes become placeholders (tennislab.evidence),
        # and the original is kept in the ignored local evidence store.
        portable = portable_text(text, placeholders)
        same = committed.is_file() and committed.read_text(encoding="utf-8") == portable
        if args.check or target["status"] == "accepted":
            if same:
                done = f" ({problems[0]})" if problems else ""
                print(f"OK {output}: build is byte-identical to the file in the repository{done}")
                continue
            failed = True
            if not committed.is_file():
                print(f"MISSING {output}: not in the repository (build without --check)")
                continue
            print(f"DIFFERS {output}:")
            expected = json.loads(committed.read_text(encoding="utf-8"))
            for line in json_differences(expected, json.loads(portable)) or ["formatting only"]:
                print(f"  {line}")
            continue
        destination = (args.out_dir / Path(output).name) if args.out_dir else committed
        if portable != text and not args.out_dir:
            write_evidence(args.repo, output, text, placeholders)
            problems = [
                *problems,
                "host paths replaced by placeholders; original in local/evidence",
            ]
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(portable, encoding="utf-8")
        notes = [*problems, *(["unchanged"] if same and not args.out_dir else [])]
        print(f"WROTE {destination}" + (f" ({'; '.join(notes)})" if notes else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
