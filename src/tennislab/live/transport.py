"""HTTP transport behind one small interface, with a replay transport for rehearsal.

The live transport is plain ``urllib``: serial requests, a minimum spacing per host, an
honest user agent, no credential, no redirect off the declared host. The replay transport
serves retained or synthetic responses from a directory so every command can rehearse
without a network (design §3). Both return the same :class:`Response`, so the acquisition
code path is identical.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from tennislab.live.common import LiveError, iso_utc, safe_slug, utc_now


@dataclass(frozen=True)
class Response:
    url: str
    status: int | None
    headers: dict[str, str]
    body: bytes
    requested_at_utc: str
    received_at_utc: str
    error_class: str | None = None
    note: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


class Transport:
    """One method: fetch a URL and return a :class:`Response`; never raise on HTTP status."""

    name = "abstract"

    def get(self, url: str) -> Response:  # pragma: no cover - interface
        raise NotImplementedError


class UrllibTransport(Transport):
    name = "urllib"

    def __init__(self, *, user_agent: str, min_interval_seconds: float, allowed_hosts: set[str]):
        if not user_agent.strip():
            raise LiveError("a descriptive user agent is required")
        self.user_agent = user_agent
        self.min_interval = float(min_interval_seconds)
        self.allowed_hosts = set(allowed_hosts)
        self._last: dict[str, float] = {}

    def get(self, url: str) -> Response:
        host = urllib.parse.urlsplit(url).netloc
        if host not in self.allowed_hosts:
            raise LiveError(
                f"host {host!r} is not in the declared allow list {sorted(self.allowed_hosts)}"
            )
        previous = self._last.get(host)
        if previous is not None:
            wait = self.min_interval - (time.monotonic() - previous)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()
        request = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        requested = iso_utc(utc_now())
        try:
            with urllib.request.urlopen(request, timeout=60) as handle:  # noqa: S310
                body = handle.read()
                return Response(
                    url,
                    handle.status,
                    {k.lower(): v for k, v in handle.headers.items()},
                    body,
                    requested,
                    iso_utc(utc_now()),
                )
        except urllib.error.HTTPError as error:
            return Response(
                url,
                error.code,
                {k.lower(): v for k, v in error.headers.items()},
                error.read() or b"",
                requested,
                iso_utc(utc_now()),
                error_class="HTTPError",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return Response(
                url, None, {}, b"", requested, iso_utc(utc_now()), error_class=type(error).__name__
            )


def replay_key(url: str) -> str:
    return safe_slug(urllib.parse.unquote(url).replace("https://", "").replace("http://", ""))


@dataclass
class ReplayTransport(Transport):
    """Serve responses from ``<dir>/<replay_key(url)>.json`` files.

    Each file is ``{"status": 200, "headers": {...}, "body": "<text>"}`` or carries
    ``"body_base64"``. A missing file is a ``ReplayMiss`` error class response, never a
    fabricated success. ``fail_after`` raises after that many requests to rehearse an
    interruption.
    """

    directory: Path
    fail_after: int | None = None
    served: list[str] = field(default_factory=list)
    name: str = "replay"

    def get(self, url: str) -> Response:
        if self.fail_after is not None and len(self.served) >= self.fail_after:
            raise ConnectionError("replay transport interrupted on purpose")
        self.served.append(url)
        requested = iso_utc(utc_now())
        path = self.directory / f"{replay_key(url)}.json"
        if not path.is_file():
            return Response(url, None, {}, b"", requested, requested, error_class="ReplayMiss")
        document = json.loads(path.read_text(encoding="utf-8"))
        if "body_base64" in document:
            import base64

            body = base64.b64decode(document["body_base64"])
        else:
            body = str(document.get("body", "")).encode("utf-8")
        headers = {str(k).lower(): str(v) for k, v in dict(document.get("headers", {})).items()}
        return Response(
            url, int(document.get("status", 200)), headers, body, requested, iso_utc(utc_now())
        )


def write_replay_response(
    directory: Path, url: str, *, status: int, body: str, headers: dict[str, str] | None = None
) -> Path:
    """Helper for tests and for retaining a live response as a future replay fixture."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{replay_key(url)}.json"
    path.write_text(
        json.dumps({"status": status, "headers": headers or {}, "body": body}, sort_keys=True),
        encoding="utf-8",
    )
    return path
