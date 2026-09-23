ROUND_ORDER: dict[str, int] = {
    "RR": 0,   # Round robin (group stage), before knockouts
    "BR": 0,   # Bronze medal match — concurrent with final
    "ER": 0,   # Early rounds / qualifying overflow
    "R128": 1,
    "R64": 2,
    "R32": 3,
    "R16": 4,
    "R4": 5,   # 4th round in WTA 1000 64-draws (between R16 and QF)
    "QF": 6,
    "SF": 7,
    "F": 8,
}
