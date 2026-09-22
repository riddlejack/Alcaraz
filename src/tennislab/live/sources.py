"""Source adapters behind one interface: acquire → retain → normalize.

Every adapter returns plain dictionaries with the same result or serve-state vocabulary
(design §3–§4) plus a ``receipt_id`` naming the attempt the bytes came from. A source is
used only for the fields its config status qualifies; the config is the only place that
qualification lives, so a candidate source (TennisMyLife, R22) is refused here by
status, not by a missing branch.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import urllib.parse
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tennislab.chain.common import sha256
from tennislab.live import wikitext
from tennislab.live.common import LiveConfig, LiveError, parse_date, read_json, relative_in
from tennislab.live.receipts import Attempt
from tennislab.live.transport import Transport

EVENT_FIELDS = (
    "event_id",
    "tour",
    "name",
    "level",
    "surface",
    "best_of",
    "draw_size",
    "wikipedia_title",
    "draw_scope",
    "window_start",
    "window_end",
)
DRAW_SCOPES = {"main", "qualifying"}
TA_SERVE_FIELDS = (
    "p_ace",
    "p_df",
    "p_svpt",
    "p_1stIn",
    "p_1stWon",
    "p_2ndWon",
    "p_SvGms",
    "p_bpSaved",
    "p_bpFaced",
    "o_ace",
    "o_df",
    "o_svpt",
    "o_1stIn",
    "o_1stWon",
    "o_2ndWon",
    "o_SvGms",
    "o_bpSaved",
    "o_bpFaced",
)


def read_events(path: Path) -> list[dict[str, Any]]:
    """The user-declared population of events to refresh (never inferred)."""
    document = read_json(path)
    events = document.get("events") if isinstance(document, dict) else document
    if not isinstance(events, list) or not events:
        raise LiveError(f"events file {path} has no events list")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        missing = [f for f in ("event_id", "tour", "name", "wikipedia_title") if not event.get(f)]
        if missing:
            raise LiveError(f"event {index} lacks {missing}")
        if event["event_id"] in seen:
            raise LiveError(f"duplicate event_id {event['event_id']!r}")
        seen.add(event["event_id"])
        record = {field: event.get(field, "") for field in EVENT_FIELDS}
        record["tour"] = str(record["tour"]).upper()
        if record["tour"] not in {"ATP", "WTA"}:
            raise LiveError(f"event {event['event_id']}: tour must be ATP or WTA")
        scope = str(event.get("draw_scope") or "").strip().lower()
        qualifying_identity = bool(
            re.search(r"(?:^|[-_/])q(?:$|[-_/])", str(record["event_id"]), re.IGNORECASE)
            or re.search(
                r"\bqualif(?:y|ying|ier|iers|ication)\w*\b", str(record["name"]), re.IGNORECASE
            )
        )
        if not scope:
            if qualifying_identity:
                raise LiveError(
                    f"event {event['event_id']}: qualifying event metadata requires explicit "
                    "draw_scope='qualifying'; omitted draw_scope is legacy main-draw behavior"
                )
            scope = "main"
        if scope not in DRAW_SCOPES:
            raise LiveError(
                f"event {event['event_id']}: draw_scope must be one of {sorted(DRAW_SCOPES)}, "
                f"got {scope!r}"
            )
        if scope == "main" and qualifying_identity:
            raise LiveError(
                f"event {event['event_id']}: draw_scope='main' conflicts with qualifying event "
                "metadata"
            )
        record["draw_scope"] = scope
        for field in ("window_start", "window_end"):
            if record[field]:
                parse_date(str(record[field]), label=f"event {event['event_id']} {field}")
        if record["window_start"] and record["window_end"]:
            if parse_date(record["window_end"], label="window_end") < parse_date(
                record["window_start"], label="window_start"
            ):
                raise LiveError(f"event {event['event_id']}: window_end precedes window_start")
        record["byes"] = int(event.get("byes", 0) or 0)
        out.append(record)
    return out


# --- Wikipedia results ----------------------------------------------------------------


def wikipedia_url(endpoint: str, title: str) -> str:
    return endpoint.format(title=urllib.parse.quote(title.replace(" ", "_"), safe=""))


def acquire_wikipedia(
    config: LiveConfig, attempt: Attempt, transport: Transport, events: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Fetch each event's draw page through the core REST API; retain bytes; parse."""
    source = config.require_source_fields(
        "wikipedia_results",
        statuses=("qualified",),
        fields={
            "winner",
            "score",
            "round",
            "status",
            "source_revision",
            "publication_upper_bound_utc",
        },
    )
    endpoint = str(source["endpoint"])
    for forbidden in source.get("never_request", []):
        if endpoint.startswith(str(forbidden)):
            raise LiveError(f"endpoint {endpoint} is on the never-request list")
    qualification = {
        "source_id": "wikipedia_results",
        "status": source["status"],
        "qualified_fields": list(source["qualified_fields"]),
        "terms_reference": source["terms_reference"],
    }
    captures: list[dict[str, Any]] = []
    for event in events:
        url = wikipedia_url(endpoint, str(event["wikipedia_title"]))
        response = transport.get(url)
        name = f"{event['tour']}_{event['event_id']}.json".replace("/", "_")
        record = attempt.retain(response, name=name, qualification=qualification)
        if record["retained_path"] is None:
            captures.append({"event": dict(event), "request": record, "error": "no body retained"})
            continue
        try:
            envelope = json.loads(response.body.decode("utf-8"))
            revision = envelope["latest"]
            source_text = envelope["source"]
        except (ValueError, KeyError, UnicodeDecodeError) as error:
            captures.append(
                {"event": dict(event), "request": record, "error": f"envelope: {error}"}
            )
            continue
        captures.append(
            {
                "event": dict(event),
                "request": record,
                "revision_id": str(revision.get("id")),
                "revision_timestamp_utc": str(revision.get("timestamp")),
                "page_title": str(envelope.get("title", event["wikipedia_title"])),
                "source": source_text,
            }
        )
    return captures


def structural_probe(captures: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Outcome-free structure per capture: headings, templates, round labels, shape counts."""
    out = []
    for capture in captures:
        if "source" not in capture:
            out.append({"event_id": capture["event"]["event_id"], "error": capture.get("error")})
            continue
        draw_scope = str(capture["event"].get("draw_scope") or "main")
        try:
            probe = wikitext.structure(capture["source"], draw_scope=draw_scope)
        except LiveError as error:
            out.append(
                {
                    "event_id": capture["event"]["event_id"],
                    "revision_id": capture["revision_id"],
                    "draw_scope": draw_scope,
                    "error": str(error),
                }
            )
            continue
        out.append(
            {
                "event_id": capture["event"]["event_id"],
                "revision_id": capture["revision_id"],
                "draw_scope": probe.draw_scope,
                "headings": probe.headings,
                "templates": probe.templates,
                "round_labels": probe.round_labels,
                "slots_per_template": probe.slots_per_template,
                "parameter_shapes": probe.parameter_shapes,
            }
        )
    return out


# --- Tennis Abstract serve-state feed ----------------------------------------------------


def ingest_serve_feed(config: LiveConfig, attempt: Attempt, feed_dir: Path) -> list[dict[str, Any]]:
    """Copy a parsed TAPLAYER01-layout directory into the attempt, hash every file, and
    return the rows with their per-field presence. ``date_basis`` stays ``event_anchor``."""
    source = config.require_source_fields(
        "tennisabstract_serve",
        statuses=("qualified_serve_state",),
        fields=set(TA_SERVE_FIELDS),
    )
    if not source.get("permission_id"):
        raise LiveError("serve feed has no permission_id; refusing")
    files = sorted(p for p in feed_dir.glob("*.csv") if p.is_file())
    if not files:
        raise LiveError(f"no parsed CSV files under {feed_dir}")
    rows: list[dict[str, Any]] = []
    attempt.raw_dir.mkdir(parents=True, exist_ok=True)
    for path in files:
        target = attempt.raw_dir / path.name
        target.write_bytes(path.read_bytes())
        digest = sha256(target)
        attempt.requests.append(
            {
                "requested_url": None,
                "local_source": path.name,
                "status": None,
                "bytes": target.stat().st_size,
                "sha256": digest,
                "retained_path": relative_in(attempt.directory, target),
                "qualification": {
                    "source_id": "tennisabstract_serve",
                    "status": source["status"],
                    "permission_id": source["permission_id"],
                    "attribution": source["attribution"],
                    "date_basis": source["date_basis"],
                },
            }
        )
        with target.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            for needed in (
                "tour",
                "player_id",
                "date",
                "date_basis",
                "tournament_name",
                "match_id",
            ):
                if needed not in header:
                    raise LiveError(f"{path.name}: serve feed lacks column {needed!r}")
            for row in reader:
                if row.get("date_basis") != "event_anchor":
                    raise LiveError(f"{path.name}: unexpected date_basis {row.get('date_basis')!r}")
                present = [
                    f for f in TA_SERVE_FIELDS if f in header and (row.get(f) or "").strip() != ""
                ]
                rows.append(
                    {
                        "tour": row["tour"].upper(),
                        "player_id": row["player_id"].strip(),
                        "opponent_id": (row.get("opponent_id") or "").strip(),
                        "event_anchor": _yyyymmdd(row["date"]),
                        "date_basis": "event_anchor",
                        "tournament_name": row["tournament_name"],
                        "match_id": row["match_id"],
                        "fields_present": present,
                        "fields_missing": [f for f in TA_SERVE_FIELDS if f not in present],
                        "serve_block_valid": (row.get("serve_block_valid") or "").lower() == "true",
                        "retained_file": path.name,
                        "retained_sha256": digest,
                    }
                )
    return rows


def _yyyymmdd(value: str) -> str:
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return dt.date.fromisoformat(text).isoformat()


# --- Rankings feed ------------------------------------------------------------------------


def ingest_rankings(
    config: LiveConfig, attempt: Attempt, path: Path, *, tour: str
) -> list[dict[str, str]]:
    source = config.require_source_fields(
        "rankings_feed", statuses=("qualified_last_known",), fields={"rank", "points"}
    )
    attempt.raw_dir.mkdir(parents=True, exist_ok=True)
    target = attempt.raw_dir / f"{tour}_{path.name}"
    target.write_bytes(path.read_bytes())
    digest = sha256(target)
    attempt.requests.append(
        {
            "requested_url": None,
            "local_source": path.name,
            "status": None,
            "bytes": target.stat().st_size,
            "sha256": digest,
            "retained_path": relative_in(attempt.directory, target),
            "qualification": {
                "source_id": "rankings_feed",
                "status": source["status"],
                "publication_basis": source["publication_basis"],
            },
        }
    )
    rows: list[dict[str, str]] = []
    with target.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for needed in ("ranking_date", "rank", "player", "points"):
            if needed not in (reader.fieldnames or []):
                raise LiveError(f"rankings file lacks column {needed!r}")
        for row in reader:
            rows.append(
                {
                    "tour": tour,
                    "player_id": row["player"].strip(),
                    "ranking_date": _yyyymmdd(row["ranking_date"]),
                    "rank": row["rank"].strip(),
                    "points": row["points"].strip(),
                    "publication_basis": source["publication_basis"],
                }
            )
    return rows
