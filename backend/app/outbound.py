"""The one door out. Every network request in the backend goes through request() here.

Shared file: keep changes additive, and call them out in the commit message.

Each call is recorded in an in-memory log with exactly what was sent: the final URL, the
headers httpx actually sent (API keys redacted), the body, the status and the duration.
The outbound log panel in the UI reads it from GET /api/outbound-log.

Rules:
- Pass every search query string as guard=[...]. Anything that looks like an email,
  phone number, SSN or birthdate raises MinimalQueryError before anything is sent.
  Don't weaken that check.
- Local LLM calls use local=True. They're logged with long text truncated, and marked
  as staying on this machine.
- Don't import httpx or requests anywhere else in backend/app or backend/scripts.
- Pages the browser extension reads straight from websites (service "website") are kept in a
  separate, smaller log, so a day of browsing can't push a scan's requests out of the main one.
"""

import asyncio
import copy
import re
import time
from collections import deque
from datetime import datetime, timezone
from itertools import count
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import LOCAL_HOSTS

MAX_LOG_ENTRIES = 500
MAX_SITE_LOG_ENTRIES = 200  # service "website": the browser extension's policy fetches
LOCAL_BODY_CHARS = 300
REDACTED = "REDACTED"
USER_AGENT = "hack1984/0.1 (local privacy scanner)"

_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_SSN_RE = re.compile(r"\b\d{3}[\s-]?\d{2}[\s-]?\d{4}\b")
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_RES = (
    re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b"),  # 4/12/1990, 04-12-90
    re.compile(r"\b\d{4}[/.-]\d{1,2}[/.-]\d{1,2}\b"),  # 1990-04-12
    re.compile(rf"\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.I),  # April 12, 1990
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH},?\s+\d{{4}}\b", re.I),  # 12 April 1990
)
_SECRET_NAME_RE = re.compile(r"key|auth|token|secret|cookie", re.I)


class MinimalQueryError(ValueError):
    """Raised when a search query contains personal identifiers we never send."""


def assert_minimal_query(text: str) -> str:
    """Return `text` unchanged, or raise if it contains an email, phone, SSN or birthdate."""
    if _EMAIL_RE.search(text):
        raise MinimalQueryError("Blocked query: it contains an email address.")
    if _PHONE_RE.search(text):
        raise MinimalQueryError("Blocked query: it contains a phone number.")
    if _SSN_RE.search(text):
        raise MinimalQueryError("Blocked query: it looks like it contains an SSN.")
    if any(r.search(text) for r in _DATE_RES):
        raise MinimalQueryError("Blocked query: it looks like it contains a birthdate.")
    return text


class OutboundEntry(BaseModel):
    id: int
    time: str
    service: str
    purpose: str
    local: bool
    method: str
    url: str
    headers: dict[str, str]
    body: Any = None
    status: int | None = None
    ms: int | None = None
    error: str | None = None


_log: deque[OutboundEntry] = deque(maxlen=MAX_LOG_ENTRIES)
_site_log: deque[OutboundEntry] = deque(maxlen=MAX_SITE_LOG_ENTRIES)
_ids = count(1)
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(headers={"User-Agent": USER_AGENT})
    return _client


async def close() -> None:
    """Close the shared HTTP client. Called on app shutdown and at the end of scripts."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _redact_headers(headers: httpx.Headers) -> dict[str, str]:
    return {k: REDACTED if _SECRET_NAME_RE.search(k) else v for k, v in headers.items()}


def _redact_url(url: httpx.URL) -> str:
    params = url.params.multi_items()
    if not any(_SECRET_NAME_RE.search(k) for k, _ in params):
        return str(url)
    return str(url.copy_with(params=[(k, REDACTED if _SECRET_NAME_RE.search(k) else v) for k, v in params]))


def _truncate(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= LOCAL_BODY_CHARS else value[:LOCAL_BODY_CHARS] + "…"
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    return value


async def request(
    service: str,
    method: str,
    url: str,
    *,
    purpose: str,
    guard: list[str] | None = None,
    local: bool = False,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
    timeout: float = 20.0,
    send_cookies: bool = True,
    max_bytes: int | None = None,
) -> httpx.Response:
    """Send one logged HTTP request. `purpose` is shown to the user in the log panel.

    send_cookies=False sends no stored cookies (the browser extension's fetches from websites).
    max_bytes reads at most that much of the body, decompressed, and never downloads the rest,
    so a huge page or a compression bomb can't fill memory."""
    for query in guard or []:
        assert_minimal_query(query)

    client = _get_client()
    req = client.build_request(
        method.upper(), url, params=params, headers=headers, json=json_body, timeout=timeout
    )
    if not send_cookies:
        req.headers.pop("cookie", None)
    if local and req.url.host not in LOCAL_HOSTS:
        # local=True hides the call in the log panel by default, so it must really be local.
        raise ValueError(f"local=True but {req.url.host!r} is not this machine")
    body = copy.deepcopy(json_body)
    entry = OutboundEntry(
        id=next(_ids),
        time=datetime.now(timezone.utc).isoformat(),
        service=service,
        purpose=purpose,
        local=local,
        method=req.method,
        url=_redact_url(req.url),
        headers=_redact_headers(req.headers),
        body=_truncate(body) if local else body,
    )
    (_site_log if service == "website" else _log).append(entry)

    started = time.monotonic()
    try:
        if max_bytes is None:
            response = await client.send(req)
        else:
            response = await client.send(req, stream=True)
            content = bytearray()
            try:
                async for chunk in response.aiter_bytes():
                    content += chunk
                    if len(content) >= max_bytes:
                        break
            finally:
                await response.aclose()
            response._content = bytes(content[:max_bytes])  # what .text and .json() read
        entry.status = response.status_code
        return response
    except asyncio.CancelledError:  # e.g. the caller's time limit ran out
        entry.error = "Cancelled: it took too long."
        raise
    except Exception as exc:
        entry.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        entry.ms = int((time.monotonic() - started) * 1000)


def get_log(include_local: bool = True) -> list[OutboundEntry]:
    entries = sorted([*_log, *_site_log], key=lambda e: e.id)
    return [e for e in entries if include_local or not e.local]


def clear_log() -> None:
    _log.clear()
    _site_log.clear()
