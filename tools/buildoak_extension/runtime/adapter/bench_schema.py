"""Trusted stdlib-only target projection, callable before the container boundary."""

FIXTURE_PLAYER_FIELDS = (
    "id",
    "name",
    "age",
    "ht",
    "seed",
    "rank",
    "rank_points",
    "entry",
    "hand",
    "ioc",
)
FIXTURE_CONTEXT = (
    "tourney_id",
    "match_num",
    "match_date",
    "tourney_name",
    "tourney_level",
    "surface",
    "round",
    "draw_size",
    "best_of",
)
FIXTURE_FIELDS = (
    set(FIXTURE_CONTEXT)
    | {"score"}
    | {role + "_" + field for role in ["winner", "loser"] for field in FIXTURE_PLAYER_FIELDS}
)


def source_id(row):
    if row.get("_transport_id"):
        return str(row["_transport_id"])
    return str(row["tourney_id"]) + "/" + str(int(row["match_num"]))


def neutral_fixture(row):
    """Here winner/loser become schema aliases for smaller/larger source ID."""
    first = "winner" if int(row["winner_id"]) < int(row["loser_id"]) else "loser"
    second = "loser" if first == "winner" else "winner"
    out = {k: row[k] for k in FIXTURE_CONTEXT}
    if row.get("_transport_id"):
        out["_transport_id"] = str(row["_transport_id"])
    for dst, src in [("winner", first), ("loser", second)]:
        for field in FIXTURE_PLAYER_FIELDS:
            out[dst + "_" + field] = row.get(src + "_" + field)
        # The released ranking stream is the sole target-rank source.
        out[dst + "_rank"] = None
        out[dst + "_rank_points"] = None
    out["score"] = ""
    return out


def validate_fixture(row):
    expected = FIXTURE_FIELDS | ({"_transport_id"} if row.get("_transport_id") else set())
    if set(row) != expected or row["score"] != "":
        raise ValueError("target payload must be the exact neutral metadata projection")
    if int(row["winner_id"]) >= int(row["loser_id"]):
        raise ValueError("target schema aliases must encode canonical ID order")
    if any(
        row[role + "_" + field] is not None
        for role in ["winner", "loser"]
        for field in ["rank", "rank_points"]
    ):
        raise ValueError("target ranks must come only from the released ranking stream")
