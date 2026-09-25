"""The number language of the public pages: placeholders and formats.

Shared by ``tools/check_readme_numbers.py`` (pages rendered from templates) and
``tools/build_benchmark_aggregates.py`` (text fields of the benchmark JSONs), so a number on a
page and the same number in a JSON sentence are formatted by one function. Standard library
only; nothing here reads a file.

- ``{{alias:path|pipe|...}}`` reads a JSON value through a resolver. ``path`` is
  ``/``-separated; a list element is chosen by index (``years/0``) or by field
  (``comparisons/[id=uts]``), and a bracket may hold spaces, slashes and colons; a key
  that contains a slash is quoted: ``file_sha256/'experiments/EXT2025.design.md'``.
- References and numbers may be joined by `` + ``, `` - ``, `` * ``, `` / `` (spaces
  required, evaluated left to right): ``{{bo:cohort/n - bo:cohort/priced_subset/n|int}}``.
- Pipes transform (``len``, ``values``, ``first``, ``last``, ``abs``, ``neg``, ``x100``,
  ``min``, ``max``, ``round`` to an integer, ``inv`` for 1/x, ``negatives`` counting values below zero) and format (``f4`` fixed, ``s4`` signed, ``abs4``, ``ci4`` interval,
  ``pct1`` percent, ``e0`` scientific, ``int`` thousands separator, ``d`` plain integer, ``word``/``Word``
  spelled 0-99, ``span`` for years as first–last, ``raw``). A placeholder must end in a
  format. Negative numbers use the minus sign U+2212.
- ``{{# ... #}}`` is a template comment, removed before rendering.
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable
from typing import Any

MINUS = "\u2212"
PLACEHOLDER = re.compile(r"\{\{(?!#)(.+?)\}\}", re.S)
TEMPLATE_COMMENT = re.compile(r"\{\{#.*?#\}\}", re.S)
REF = re.compile(r"^([A-Za-z_][\w-]*):(.+)$")
WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()

Resolver = Callable[[str, str], Any]


class NumbersError(ValueError):
    """A placeholder, path or format that cannot be resolved."""


def split_path(path: str) -> list[str]:
    """Split on ``/`` outside brackets and quotes; ``'a/b.md'`` is one literal key."""
    parts, depth, quoted, current = [], 0, False, []
    for char in path:
        if char == "'" and depth == 0:
            quoted = not quoted
            continue
        if not quoted and char == "[":
            depth += 1
        elif not quoted and char == "]":
            depth -= 1
        if char == "/" and depth == 0 and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    if depth != 0 or quoted or any(part == "" for part in parts):
        raise NumbersError(f"malformed path {path!r}")
    return parts


def lookup(data: Any, path: str) -> Any:
    node = data
    for part in split_path(path):
        try:
            if part.startswith("[") and part.endswith("]"):
                field, sep, value = part[1:-1].partition("=")
                if sep:
                    matches = [item for item in node if str(item.get(field)) == value]
                    if len(matches) != 1:
                        raise NumbersError(f"{len(matches)} list items match {part} in {path!r}")
                    node = matches[0]
                else:
                    node = node[int(field)]
            elif isinstance(node, list):
                node = node[int(part)]
            else:
                node = node[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise NumbersError(f"cannot resolve {part!r} in {path!r}: {exc!r}") from None
    return node


def _signed(value: float, digits: int) -> str:
    return f"{value:+.{digits}f}".replace("-", MINUS)


def _plain(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace("-", MINUS)


def _word(value: Any) -> str:
    number = int(value)
    if number != value or not 0 <= number < 100:
        raise NumbersError(f"word format needs an integer 0-99, got {value!r}")
    if number < 20:
        return WORDS[number]
    tens, units = divmod(number, 10)
    return TENS[tens - 2] + (f"-{WORDS[units]}" if units else "")


TRANSFORMS: dict[str, Callable[[Any], Any]] = {
    "len": len,
    "round": lambda v: int(round(v)),
    "inv": lambda v: 1 / v,
    "negatives": lambda v: sum(1 for x in v if x < 0),
    "values": lambda v: list(v.values()),
    "first": lambda v: v[0],
    "last": lambda v: v[-1],
    "abs": abs,
    "neg": operator.neg,
    "x100": lambda v: 100 * v,
    "min": min,
    "max": max,
}
FIXED_FORMATS: dict[str, Callable[[Any], str]] = {
    "int": lambda v: f"{int(v):,}".replace("-", MINUS),
    "d": lambda v: str(int(v)).replace("-", MINUS),
    "word": _word,
    "Word": lambda v: _word(v).capitalize(),
    "raw": str,
    "span": lambda v: (
        f"{int(v[0])}\u2013{int(v[-1])}" if int(v[0]) != int(v[-1]) else str(int(v[0]))
    ),
}
DIGIT_FORMATS: dict[str, Callable[[Any, int], str]] = {
    "f": lambda v, d: _plain(float(v), d),
    "s": lambda v, d: _signed(float(v), d),
    "abs": lambda v, d: _plain(abs(float(v)), d),
    "ci": lambda v, d: f"[{_signed(float(v[0]), d)}, {_signed(float(v[1]), d)}]",
    "pct": lambda v, d: f"{_plain(100 * float(v), d)}%",
    "e": lambda v, d: f"{float(v):.{d}e}",
}


def apply_pipe(value: Any, name: str) -> Any:
    if name in TRANSFORMS:
        return TRANSFORMS[name](value)
    if name in FIXED_FORMATS:
        return FIXED_FORMATS[name](value)
    match = re.fullmatch(r"([a-z]+)(\d)", name)
    if match and match.group(1) in DIGIT_FORMATS:
        return DIGIT_FORMATS[match.group(1)](value, int(match.group(2)))
    raise NumbersError(f"unknown pipe {name!r}")


OPERATORS = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}


def evaluate(expression: str, resolve: Resolver) -> Any:
    """A reference, a number, or references and numbers joined by spaced operators."""
    tokens, depth, current, i = [], 0, [], 0
    text = expression.strip()
    while i < len(text):
        char = text[i]
        depth += char == "["
        depth -= char == "]"
        if depth == 0 and text[i : i + 3] in (" + ", " - ", " * ", " / "):
            tokens += ["".join(current).strip(), text[i + 1]]
            current, i = [], i + 3
            continue
        current.append(char)
        i += 1
    tokens.append("".join(current).strip())
    values = []
    for index, token in enumerate(tokens):
        if index % 2:
            values.append(token)
            continue
        ref = REF.match(token)
        if ref:
            values.append(resolve(ref.group(1), ref.group(2)))
        else:
            try:
                values.append(ast.literal_eval(token))
            except ValueError, SyntaxError:
                raise NumbersError(f"not a reference or number: {token!r}") from None
    result = values[0]
    for op, operand in zip(values[1::2], values[2::2], strict=True):
        result = OPERATORS[op](result, operand)
    return result


def render_placeholder(body: str, resolve: Resolver) -> str:
    expression, *pipes = [part.strip() for part in body.split("|")]
    value = evaluate(expression, resolve)
    for name in pipes:
        value = apply_pipe(value, name)
    if not isinstance(value, str):
        raise NumbersError(f"{{{{{body}}}}} does not end in a format (got {value!r})")
    return value


def render_text(text: str, resolve: Resolver) -> str:
    text = TEMPLATE_COMMENT.sub("", text)
    return PLACEHOLDER.sub(lambda match: render_placeholder(match.group(1), resolve), text)
