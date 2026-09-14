"""Player identity: exact normalised name against a player master, then aliases.

A name that resolves to more than one master row, or to none, is quarantined with the
candidates listed. No synthetic identity is ever minted; a quarantined row keeps its
source name and is excluded from every downstream table until the alias table is
extended by a person.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from tennislab.live.common import LiveError
from tennislab.ratings.elo import normalize_name

PLAYER_COLUMNS = ("player_id", "name_first", "name_last")
ALIAS_COLUMNS = ("alias", "player_id", "tour", "note")


@dataclass(frozen=True)
class Resolution:
    player_id: str
    status: str  # resolved | ambiguous | unresolved
    candidates: tuple[str, ...]
    basis: str  # master | alias | none


class IdentityTable:
    def __init__(self, players: Path, aliases: Path | None) -> None:
        self.by_name: dict[str, list[str]] = {}
        self.known: set[str] = set()
        with players.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing = [c for c in PLAYER_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise LiveError(f"player master {players} lacks columns {missing}")
            for row in reader:
                pid = row["player_id"].strip()
                if not pid:
                    continue
                self.known.add(pid)
                key = normalize_name(f"{row['name_first']} {row['name_last']}")
                if key:
                    self.by_name.setdefault(key, []).append(pid)
        self.aliases: dict[tuple[str, str], str] = {}
        if aliases is not None and aliases.is_file():
            with aliases.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                missing = [c for c in ALIAS_COLUMNS if c not in (reader.fieldnames or [])]
                if missing:
                    raise LiveError(f"alias table {aliases} lacks columns {missing}")
                for row in reader:
                    pid = row["player_id"].strip()
                    if pid not in self.known:
                        raise LiveError(
                            f"alias {row['alias']!r} names an unknown player id {pid!r}"
                        )
                    key = (row["tour"].strip().upper(), normalize_name(row["alias"]))
                    if key in self.aliases and self.aliases[key] != pid:
                        raise LiveError(f"alias {row['alias']!r} maps to two players")
                    self.aliases[key] = pid

    def resolve(self, name: str, *, tour: str, declared_id: str = "") -> Resolution:
        declared = (declared_id or "").strip()
        if declared:
            if declared in self.known:
                return Resolution(declared, "resolved", (declared,), "declared_id")
            return Resolution("", "unresolved", (), "declared_id_unknown")
        key = normalize_name(name or "")
        if not key:
            return Resolution("", "unresolved", (), "none")
        candidates = tuple(sorted(set(self.by_name.get(key, ()))))
        if len(candidates) == 1:
            return Resolution(candidates[0], "resolved", candidates, "master")
        if len(candidates) > 1:
            return Resolution("", "ambiguous", candidates, "master")
        alias = self.aliases.get((tour.upper(), key)) or self.aliases.get(("", key))
        if alias:
            return Resolution(alias, "resolved", (alias,), "alias")
        return Resolution("", "unresolved", (), "none")
