"""Check that every number on the README and the benchmark pages comes from a committed JSON.

Each page is registered in ``docs/numbers.json`` in one of two modes:

- **Bindings** (the README and other hand-edited Markdown). The page stays plain Markdown.
  Each binding names a ``context`` (text that identifies exactly one line of the page; with
  ``offset`` n the number is n lines below it), the ``text`` shown on that line, and a ``value``: a placeholder string such as
  ``{{bo25:contrasts/contrast2_arm1_minus_buildoak/difference/match_weighted/log_loss|s4}}``
  that must render to exactly that text from the JSONs named in ``aliases``. Every number on
  the page must be covered by a binding or listed under ``allowed`` with a reason; anything
  else is untraced, reported with the JSON keys whose value would print the same way.
- **Template** (generated benchmark pages). The page is rendered from a template in
  ``docs/templates/`` whose numbers are placeholders; ``--render`` writes it and the check
  requires the page to match the template byte for byte. Numbers typed as literal text in the
  template are untraced unless allowed.

``skip_lines_containing`` lists markers of lines left out on purpose (a slot whose source does
not exist yet); the check prints how many lines it skipped. The placeholder language is
``tennislab.numbers`` (shared with
``tools/build_benchmark_aggregates.py``). A page with ``"strict": false`` reports untraced
numbers without failing (for pages where only some numbers are bound yet).

Usage (from the repository root)::

    uv run python tools/check_readme_numbers.py            # check every registered page
    uv run python tools/check_readme_numbers.py --render   # write templated pages, then check
    uv run python tools/check_readme_numbers.py --page README.md

Exit status 1 on any untraced number (strict pages), mismatch, stale binding or page, or
missing source.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from tennislab.numbers import PLACEHOLDER, TEMPLATE_COMMENT, NumbersError, lookup, render_text

REGISTRY = Path("docs/numbers.json")
SIGNS = "+-−±"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
TOKEN = re.compile(
    r"(?<![\w.\-/#@\u2212])[+\-\u2212±]?\d(?:[\d,]*\d)?(?:\.\d+)?(?:%|k\b)?(?![\w/]|-\d)"
)
SKIP_SPANS = (
    re.compile(r"```.*?```", re.S),  # code blocks
    re.compile(r"`[^`\n]*`"),  # code spans
    re.compile(r"<!--.*?-->", re.S),  # HTML comments
    re.compile(r"\]\([^)]*\)"),  # link and image targets
    re.compile(r"https?://\S+"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?"),  # dates
    re.compile(rf"\b\d{{1,2}} (?:{MONTHS})\b|\b(?:{MONTHS}) \d{{1,2}}\b"),
    re.compile(r"(?m)^\s*(?:#+\s*)?\d+\.\s"),  # list and heading numbering
    re.compile(r"\b[0-9a-f]{7,64}\b"),  # hashes
)
YEAR = re.compile(r"(?:19|20)\d\d")
SEASON_PAIR = re.compile(r"(?:19|20)\d\d[–-]$")


def scan_numbers(text: str, strict_years: bool = False) -> list[tuple[int, int, str]]:
    """(line, column, token) for numbers outside code, comments, links, dates and numbering.
    Bare years are skipped unless ``strict_years``, and so is the "26" of "2025–26"."""
    masked = list(text)
    for pattern in SKIP_SPANS:
        for match in pattern.finditer(text):
            for index in range(match.start(), match.end()):
                if masked[index] != "\n":
                    masked[index] = " "
    found = []
    for number, line in enumerate("".join(masked).split("\n"), 1):
        for match in TOKEN.finditer(line):
            token, bare = match.group(0), match.group(0).lstrip(SIGNS)
            if not strict_years and (
                YEAR.fullmatch(bare)
                or (re.fullmatch(r"\d\d", bare) and SEASON_PAIR.search(line[: match.start()]))
            ):
                continue
            found.append((number, match.start(), token))
    return found


def candidates(token: str, data: dict[str, Any]) -> list[str]:
    """JSON keys whose value, rounded as displayed, equals the token (sign ignored)."""
    bare = token.lstrip(SIGNS).rstrip("%k").replace(",", "")
    try:
        number = float(bare)
    except ValueError:
        return []
    digits = len(bare.split(".")[1]) if "." in bare else 0
    scales = (100.0,) if token.endswith("%") else (1.0, 100.0)
    hits = []

    def walk(node: Any, alias: str, parts: tuple[str, ...]) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int | float):
            if any(round(abs(node) * scale, digits) == number for scale in scales):
                hits.append(f"{alias}:{'/'.join(parts)}")
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, alias, (*parts, str(key)))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, alias, (*parts, str(index)))

    for alias, value in data.items():
        walk(value, alias, ())
    return hits


class Page:
    """One registered page: its sources, allowed constants and problems."""

    def __init__(self, root: Path, entry: dict[str, Any], aliases: dict[str, str]):
        self.root, self.entry, self.aliases = root, entry, aliases
        self.name = entry["page"]
        self.allowed = {item["text"] for item in entry.get("allowed", [])}
        self.problems: list[str] = []
        self.notes: list[str] = []
        self.counts = {"bound": 0, "allowed": 0, "untraced": 0}
        self.cache: dict[str, Any] = {}
        self.missing: set[str] = set()

    def resolve(self, alias: str, path: str) -> Any:
        if alias not in self.aliases:
            raise NumbersError(f"unknown alias {alias!r}")
        if alias not in self.cache:
            source = self.root / self.aliases[alias]
            if not source.is_file():
                self.missing.add(self.aliases[alias])
                raise NumbersError(f"source {self.aliases[alias]} does not exist")
            self.cache[alias] = json.loads(source.read_text(encoding="utf-8"))
        return lookup(self.cache[alias], path)

    def untraced(self, where: str, token: str, hint: str = "") -> None:
        if token in self.allowed or token.lstrip(SIGNS) in self.allowed:
            self.counts["allowed"] += 1
            return
        self.counts["untraced"] += 1
        target = self.problems if self.entry.get("strict", True) else self.notes
        target.append(f"UNTRACED {where}: {token}{hint}")

    def hint(self, token: str) -> str:
        for alias, path in self.aliases.items():
            if alias not in self.cache and (self.root / path).is_file():
                self.cache[alias] = json.loads((self.root / path).read_text(encoding="utf-8"))
        hits = candidates(token, self.cache)
        if not hits:
            return "; no JSON value matches"
        more = f" (+{len(hits) - 3})" if len(hits) > 3 else ""
        return f"; candidates: {', '.join(hits[:3])}{more}"

    def check_template(self, render: bool, strict_years: bool) -> None:
        template = self.entry["template"]
        source_text = (self.root / template).read_text(encoding="utf-8")
        literal = TEMPLATE_COMMENT.sub("", source_text)
        self.counts["bound"] = len(PLACEHOLDER.findall(literal))
        for line, _column, token in scan_numbers(PLACEHOLDER.sub(" ", literal), strict_years):
            self.untraced(f"{template}:{line}", token, " (literal in the template)")
        try:
            rendered = render_text(source_text, self.resolve)
        except NumbersError as exc:
            if self.missing:
                missing = ", ".join(sorted(self.missing))
                self.problems.append(f"PENDING {self.name}: missing source {missing}")
            else:
                self.problems.append(f"ERROR {template}: {exc}")
            return
        page = self.root / self.name
        if render:
            page.write_text(rendered, encoding="utf-8")
        elif not page.is_file():
            self.problems.append(f"STALE {self.name}: not rendered yet (run --render)")
        elif page.read_text(encoding="utf-8") != rendered:
            self.problems.append(f"STALE {self.name}: differs from its template (run --render)")

    def check_bindings(self, strict_years: bool) -> None:
        lines = (self.root / self.name).read_text(encoding="utf-8").split("\n")
        covered: dict[int, list[tuple[int, int]]] = {}
        for binding in self.entry.get("bindings", []):
            context, text = binding["context"], binding["text"]
            hits = [i for i, line in enumerate(lines, 1) if context in line]
            if len(hits) != 1:
                state = "not found" if not hits else f"on {len(hits)} lines {hits[:5]}"
                self.problems.append(f"STALE BINDING {self.name}: context {context!r} {state}")
                continue
            line_no = hits[0] + binding.get("offset", 0)
            spans = [m.span() for m in re.finditer(re.escape(text), lines[line_no - 1])]
            if not spans:
                self.problems.append(
                    f"MISSING {self.name}:{line_no}: {text!r} is not on the line of {context!r}"
                )
                continue
            try:
                value = render_text(binding["value"], self.resolve)
            except NumbersError as exc:
                self.problems.append(f"ERROR {self.name}:{line_no}: {binding['value']}: {exc}")
                continue
            if value != text:
                self.problems.append(
                    f"MISMATCH {self.name}:{line_no}: shows {text!r}, the JSON gives {value!r}"
                )
            covered.setdefault(line_no, []).extend(spans)
        skip = self.entry.get("skip_lines_containing", [])
        skipped = [i for i, line in enumerate(lines, 1) if any(s in line for s in skip)]
        if skipped:
            self.notes.append(f"SKIPPED {self.name} lines {skipped} (markers {skip})")
        text = "\n".join("" if i in skipped else line for i, line in enumerate(lines, 1))
        for line_no, column, token in scan_numbers(text, strict_years):
            end = column + len(token)
            if any(a <= column and end <= b for a, b in covered.get(line_no, [])):
                self.counts["bound"] += 1
            else:
                self.untraced(f"{self.name}:{line_no}", token, self.hint(token))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root")
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--page", action="append", help="check only this page (repeatable)")
    parser.add_argument("--render", action="store_true", help="write templated pages first")
    parser.add_argument("--strict-years", action="store_true", help="also report bare years")
    parser.add_argument("--quiet", action="store_true", help="print the summary only")
    args = parser.parse_args(argv)
    registry = json.loads((args.root / args.registry).read_text(encoding="utf-8"))
    entries = [p for p in registry["pages"] if not args.page or p["page"] in args.page]
    if args.page and len(entries) != len(args.page):
        parser.error(f"unregistered page among {args.page}")
    failed = False
    for entry in entries:
        page = Page(args.root, entry, registry["aliases"])
        if entry.get("template"):
            page.check_template(args.render, args.strict_years)
            kind = "template"
        else:
            page.check_bindings(args.strict_years)
            kind = "bindings"
        failed |= bool(page.problems)
        c = page.counts
        print(
            f"{'FAIL' if page.problems else 'OK'} {page.name} ({kind}): {c['bound']} bound, "
            f"{c['allowed']} allowed constants, {c['untraced']} untraced"
        )
        if not args.quiet:
            for line in page.problems + page.notes:
                print(f"  {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
