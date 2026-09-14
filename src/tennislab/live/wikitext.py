"""Parse MediaWiki tennis bracket templates (wikitext) into match rows.

Structural probe (archive ``acquisition/probes/WIKI.md`` §3, §10; redacted re-check on
2026-09-14): the whole vocabulary of a draw page is ``{{<n>TeamBracket…}}`` templates whose
parameters are ``RD<r>=<round label>``, ``RD<r>-seed<k>``, ``RD<r>-team<k>`` and
``RD<r>-score<k>-<set>``. The winner is presentational (``'''bold'''`` on the team cell),
a tiebreak is ``7<sup>9</sup>``, a retirement is ``<sup>r</sup>`` on the loser's last set,
a walkover is ``<small>w/o</small>`` in a score cell, and a ``-Byes`` template omits the
slots that receive a bye. No date, time, statistic or identifier exists in the template.

Only templates under the ``Draw`` heading are read; the qualifying draw is never parsed.
Nothing here resolves an identity: the emitted rows carry the linked article title and the
display form, and identity resolution happens elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tennislab.live.common import LiveError

PARSER_VERSION = "tennislab-wikitext-1.0.0"

ROUND_LABELS = {
    "first round": "R1",
    "second round": "R2",
    "third round": "R3",
    "fourth round": "R4",
    "round of 128": "R1",
    "round of 64": "R2",
    "round of 32": "R3",
    "round of 16": "R4",
    "quarterfinals": "QF",
    "quarterfinal": "QF",
    "semifinals": "SF",
    "semifinal": "SF",
    "final": "F",
    "finals": "F",
}
ROUND_ORDER = ("R1", "R2", "R3", "R4", "QF", "SF", "F")
QUALIFYING_LABELS = {"qualifying competition", "qualifying", "qualifier"}
ENTRY_TOKENS = {"Q", "WC", "LL", "PR", "ALT", "SE", "JE", "ITF", "SR"}

_TEMPLATE = re.compile(r"\{\{\s*(\d+TeamBracket[^|\n}]*)", re.IGNORECASE)
_PARAM = re.compile(r"^\s*\|\s*(RD\d+(?:-(?:seed|team|score)\d+(?:-\d+)?)?)\s*=(.*)$")
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
_TAG = re.compile(r"<[^>]+>")
_SUP = re.compile(r"<sup>(.*?)</sup>", re.IGNORECASE)
_HEADING = re.compile(r"^(=+)\s*(.*?)\s*=+\s*$")


@dataclass(frozen=True)
class Slot:
    round_label: str
    position: int
    seed: str
    entry: str
    title: str
    display: str
    bold: bool
    scores: tuple[str, ...]
    bye: bool


@dataclass(frozen=True)
class BracketMatch:
    round: str
    template_index: int
    a_title: str
    a_display: str
    a_seed: str
    a_entry: str
    b_title: str
    b_display: str
    b_seed: str
    b_entry: str
    winner: str  # "a", "b", "" (pending) or "conflict"
    score: str  # from the winner's perspective, e.g. "6-4 7-6(7)"
    sets: int
    status: str  # completed | retired | walkover | default | pending


@dataclass
class PageStructure:
    """The outcome-free structural probe of a page."""

    templates: list[str] = field(default_factory=list)
    round_labels: list[str] = field(default_factory=list)
    slots_per_template: list[int] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    parameter_shapes: dict[str, int] = field(default_factory=dict)


def strip_markup(text: str) -> str:
    text = _SUP.sub("", text)
    text = _TAG.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)  # flagicon and friends
    return re.sub(r"\s+", " ", text.replace("&nbsp;", " ")).strip()


def _clean_title(title: str) -> str:
    title = title.strip()
    title = re.sub(r"\s*\((?:tennis|tennis player)\)$", "", title, flags=re.IGNORECASE)
    return title.replace("_", " ")


def parse_team_cell(raw: str) -> tuple[str, str, bool, bool]:
    """Return (article title, display, bold, bye)."""
    text = raw.strip()
    bold = "'''" in text
    match = _LINK.search(text)
    if match:
        title = _clean_title(match.group(1))
        display = strip_markup(match.group(2) or match.group(1))
        return title, display, bold, False
    plain = strip_markup(text)
    if plain.lower() in {"bye", "—", "-", ""}:
        return "", plain, False, plain.lower() == "bye"
    return plain, plain, bold, False


def parse_seed_cell(raw: str) -> tuple[str, str]:
    """``<small>30/WC</small>`` → seed 30, entry WC; ``Q`` → seed "", entry Q."""
    text = strip_markup(raw).strip("[]").strip()
    if not text:
        return "", ""
    parts = [part.strip() for part in text.split("/")]
    seed = ""
    entry = ""
    for part in parts:
        upper = part.upper()
        if part.isdigit():
            seed = part
        elif upper in ENTRY_TOKENS:
            entry = upper
    return seed, entry


def _draw_section(source: str) -> str:
    """The wikitext between the ``Draw`` heading and the next same-level heading."""
    lines = source.splitlines()
    start = None
    level = 0
    for index, line in enumerate(lines):
        heading = _HEADING.match(line)
        if not heading:
            continue
        depth = len(heading.group(1))
        title = heading.group(2).strip().lower()
        if start is None and title == "draw":
            start = index
            level = depth
        elif start is not None and depth <= level:
            return "\n".join(lines[start:index])
    if start is None:
        return ""
    return "\n".join(lines[start:])


def _templates(section: str) -> list[tuple[str, dict[str, str]]]:
    """Every bracket template in the section with its raw parameters."""
    found: list[tuple[str, dict[str, str]]] = []
    positions = [(m.start(), m.group(1).strip()) for m in _TEMPLATE.finditer(section)]
    for index, (start, name) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(section)
        params: dict[str, str] = {}
        for line in section[start:end].splitlines():
            match = _PARAM.match(line)
            if match:
                key = match.group(1)
                value = match.group(2)
                # a template closes on the same line as its last parameter
                value = re.split(r"\}\}\s*(?:<section end=[^>]*/>)?\s*$", value)[0]
                params[key] = value
        found.append((name, params))
    return found


def structure(source: str) -> PageStructure:
    """Headers, template names, round labels and parameter-shape counts; no names, no scores."""
    probe = PageStructure()
    for line in source.splitlines():
        heading = _HEADING.match(line)
        if heading:
            probe.headings.append(heading.group(2).strip())
    for name, params in _templates(_draw_section(source)):
        probe.templates.append(name)
        probe.slots_per_template.append(sum(1 for key in params if "-team" in key))
        for key in params:
            shape = re.sub(r"\d+", "N", key)
            probe.parameter_shapes[shape] = probe.parameter_shapes.get(shape, 0) + 1
            if "-" not in key:
                probe.round_labels.append(strip_markup(params[key]))
    return probe


def _slots(params: dict[str, str]) -> dict[str, dict[int, Slot]]:
    labels = {
        key: strip_markup(value).lower().rstrip(":")
        for key, value in params.items()
        if "-" not in key
    }
    rounds: dict[str, dict[int, Slot]] = {}
    for key, value in params.items():
        team = re.match(r"^(RD\d+)-team(\d+)$", key)
        if not team:
            continue
        rd, position = team.group(1), int(team.group(2))
        label = labels.get(rd, "")
        if label in QUALIFYING_LABELS:
            continue
        round_code = ROUND_LABELS.get(label)
        if round_code is None:
            round_code = f"unresolved:{label or rd}"
        title, display, bold, bye = parse_team_cell(value)
        seed, entry = parse_seed_cell(
            params.get(f"{rd}-seed{position:02d}", params.get(f"{rd}-seed{position}", ""))
        )
        scores: list[str] = []
        for set_index in range(1, 6):
            cell = params.get(
                f"{rd}-score{position:02d}-{set_index}",
                params.get(f"{rd}-score{position}-{set_index}"),
            )
            if cell is None:
                break
            scores.append(cell.strip())
        rounds.setdefault(rd, {})[position] = Slot(
            round_code, position, seed, entry, title, display, bold, tuple(scores), bye
        )
    return rounds


def _set_cell(cell: str) -> tuple[str, str, bool, bool]:
    """(games, tiebreak, retired marker, walkover marker) from one score cell."""
    text = cell.strip()
    lower = strip_markup(text).lower()
    if "w/o" in lower or lower in {"wo", "walkover"}:
        return "", "", False, True
    retired = bool(re.search(r"<sup>\s*(r|ret\.?)\s*</sup>", text, re.IGNORECASE)) or lower in {
        "r",
        "ret",
        "ret.",
    }
    sup = _SUP.search(text)
    tiebreak = sup.group(1).strip() if sup and sup.group(1).strip().isdigit() else ""
    games = strip_markup(text)
    games = re.sub(r"[^0-9]", "", games)
    return games, tiebreak, retired, False


def _complete_set(a: int, b: int) -> bool:
    high, low = max(a, b), min(a, b)
    if high == 6 and low <= 4:
        return True
    if high == 7 and low in (5, 6):
        return True
    if high >= 10 and high - low >= 2:  # match tiebreak or long final set
        return True
    return high > 7 and high - low == 2


def _pair(slot_a: Slot, slot_b: Slot, template_index: int) -> BracketMatch:
    a_won, b_won = slot_a.bold, slot_b.bold
    winner = (
        "a"
        if a_won and not b_won
        else "b"
        if b_won and not a_won
        else "conflict"
        if a_won and b_won
        else ""
    )
    retired = walkover = False
    sets: list[str] = []
    complete_all = True
    for cell_a, cell_b in zip(slot_a.scores, slot_b.scores, strict=False):
        games_a, tb_a, ret_a, wo_a = _set_cell(cell_a)
        games_b, tb_b, ret_b, wo_b = _set_cell(cell_b)
        walkover = walkover or wo_a or wo_b
        retired = retired or ret_a or ret_b
        if not games_a and not games_b:
            continue
        if not games_a or not games_b:
            complete_all = False
            continue
        first, second = (games_a, games_b) if winner != "b" else (games_b, games_a)
        tb = tb_b if winner != "b" else tb_a
        if tb:
            tb = f"({tb})"
        sets.append(f"{first}-{second}{tb}")
        if not _complete_set(int(games_a), int(games_b)):
            complete_all = False
    if walkover:
        status = "walkover"
        sets = []
    elif winner == "":
        status = "pending"
    elif retired or not complete_all:
        status = "retired"
    else:
        status = "completed"
    return BracketMatch(
        round=slot_a.round_label,
        template_index=template_index,
        a_title=slot_a.title,
        a_display=slot_a.display,
        a_seed=slot_a.seed,
        a_entry=slot_a.entry,
        b_title=slot_b.title,
        b_display=slot_b.display,
        b_seed=slot_b.seed,
        b_entry=slot_b.entry,
        winner=winner,
        score=" ".join(sets),
        sets=len(sets),
        status=status,
    )


def parse_draw(source: str) -> tuple[list[BracketMatch], list[dict[str, str]]]:
    """Matches from the main draw plus structural notes (byes, unresolved rounds)."""
    section = _draw_section(source)
    if not section:
        raise LiveError("page has no Draw section")
    matches: list[BracketMatch] = []
    notes: list[dict[str, str]] = []
    for template_index, (name, params) in enumerate(_templates(section)):
        for slots in _slots(params).values():
            positions = sorted(slots)
            for position in positions:
                if position % 2 == 0:
                    continue
                slot_a = slots[position]
                slot_b = slots.get(position + 1)
                if (
                    slot_b is None
                    or slot_a.bye
                    or slot_b.bye
                    or not slot_a.title
                    or not slot_b.title
                ):
                    notes.append(
                        {
                            "template": name,
                            "round": slot_a.round_label,
                            "position": str(position),
                            "note": "bye_or_empty_slot",
                        }
                    )
                    continue
                matches.append(_pair(slot_a, slot_b, template_index))
            for position in positions:
                if position % 2 == 0 and (position - 1) not in slots:
                    notes.append(
                        {
                            "template": name,
                            "round": slots[position].round_label,
                            "position": str(position),
                            "note": "bye_or_empty_slot",
                        }
                    )
    return matches, notes
