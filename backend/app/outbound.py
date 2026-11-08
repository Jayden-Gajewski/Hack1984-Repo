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
- Email goes out through send_mail() here too (smtplib), never smtplib anywhere else. It's
  only used to send an ownership code to an address the user typed into the threat monitor.
"""

import asyncio
import copy
import re
import smtplib
import ssl
import time
import zlib
from collections import deque
from datetime import datetime, timezone
from email.message import EmailMessage
from itertools import count
from typing import Any

import httpx
import truststore
from pydantic import BaseModel

from app import auth
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
    user_id: str | None = None  # the account it was for; the public site shows each account its own


_log: deque[OutboundEntry] = deque(maxlen=MAX_LOG_ENTRIES)
_site_log: deque[OutboundEntry] = deque(maxlen=MAX_SITE_LOG_ENTRIES)
_ids = count(1)
_client: httpx.AsyncClient | None = None
_site_client: httpx.AsyncClient | None = None


def _tls_context() -> ssl.SSLContext:
    # Verify certificates against the OS trust store (Windows/macOS keychain) instead of
    # certifi's bundle, so a locally trusted root (e.g. antivirus HTTPS scanning) works.
    # Verification stays on: never pass verify=False.
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, verify=_tls_context())
    return _client


def _get_site_client() -> httpx.AsyncClient:
    """A separate client for pages read straight from websites (send_cookies=False). Its cookie
    store is emptied after every response, so the sites a user visits leave no cookies behind."""
    global _site_client
    if _site_client is None:
        _site_client = httpx.AsyncClient(headers={"User-Agent": USER_AGENT})
    return _site_client


async def close() -> None:
    """Close the shared HTTP clients. Called on app shutdown and at the end of scripts."""
    global _client, _site_client
    for client in (_client, _site_client):
        if client is not None:
            await client.aclose()
    _client = _site_client = None


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    """At most max_bytes of a streamed body, decoded here with a hard output limit. httpx would
    decode every listed encoding without one, so stacked compression ("gzip, gzip") could expand
    a small download into gigabytes. Only one gzip or deflate layer is accepted."""
    encodings = [
        e.strip().lower() for e in response.headers.get("content-encoding", "").split(",") if e.strip()
    ]
    encodings = [e for e in encodings if e != "identity"]
    if len(encodings) > 1 or (encodings and encodings[0] not in ("gzip", "x-gzip", "deflate")):
        raise ValueError(f"unsupported content encoding: {', '.join(encodings)}")
    if response.is_stream_consumed:  # a response that was built in memory, as in tests
        return response.content[:max_bytes]
    decoder = None
    out = bytearray()
    async for chunk in response.aiter_raw():
        if not encodings:
            out += chunk[: max_bytes - len(out)]
        else:
            if decoder is None:
                zlib_header = len(chunk) >= 2 and (chunk[0] & 0x0F) == 8 and (chunk[0] * 256 + chunk[1]) % 31 == 0
                wbits = 16 + zlib.MAX_WBITS if encodings[0] != "deflate" else (zlib.MAX_WBITS if zlib_header else -zlib.MAX_WBITS)
                decoder = zlib.decompressobj(wbits)
            out += decoder.decompress(chunk, max_bytes - len(out))  # never more than what's left
        if len(out) >= max_bytes:
            break
    return bytes(out[:max_bytes])


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

    client = _get_client() if send_cookies else _get_site_client()
    req = client.build_request(
        method.upper(), url, params=params, headers=headers, json=json_body, timeout=timeout
    )
    if not send_cookies:
        req.headers.pop("cookie", None)
    if max_bytes is not None:
        req.headers["accept-encoding"] = "gzip, deflate"  # the only ones _read_capped decodes
    if local and req.url.host not in LOCAL_HOSTS:
        # local=True hides the call in the log panel by default, so it must really be local.
        raise ValueError(f"local=True but {req.url.host!r} is not this machine")
    body = copy.deepcopy(json_body)
    entry = OutboundEntry(
        id=next(_ids),
        user_id=auth.current_user(),
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
            try:
                content = await _read_capped(response, max_bytes)
            finally:
                await response.aclose()
            response._content = content  # what .text and .json() read
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
        if not send_cookies:
            client.cookies.clear()  # nothing a visited site set is kept


def _smtp_send(host: str, port: int, username: str, password: str, message: EmailMessage, timeout: float) -> None:
    context = _tls_context()
    if port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
    with server:
        if port != 465:
            server.ehlo()
            # A remote server must speak TLS; starttls() raises if it can't. A local test
            # catcher (Mailpit, MailHog) usually doesn't, and the mail never leaves this machine.
            if host not in LOCAL_HOSTS or server.has_extn("starttls"):
                server.starttls(context=context)
                server.ehlo()
        if username:
            server.login(username, password)
        server.send_message(message)


async def send_mail(
    *,
    purpose: str,
    host: str,
    port: int,
    username: str,
    password: str,
    sender: str,
    to: str,
    subject: str,
    text: str,
    secrets: list[str] | None = None,
    timeout: float = 20.0,
) -> None:
    """Send one logged email over SMTP. The log shows the server, sender, recipient, subject
    and text, with each string in `secrets` (a verification code) replaced by REDACTED.
    The SMTP password is never logged."""
    shown = text
    for secret in secrets or []:
        if secret:
            shown = shown.replace(secret, REDACTED)
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, to, subject
    message.set_content(text)
    entry = OutboundEntry(
        id=next(_ids),
        user_id=auth.current_user(),
        time=datetime.now(timezone.utc).isoformat(),
        service="smtp",
        purpose=purpose,
        local=False,
        method="SMTP",
        url=f"smtp://{host}:{port}",
        headers={"From": sender, "To": to, "Subject": subject},
        body={"text": shown},
    )
    _log.append(entry)

    started = time.monotonic()
    try:
        await asyncio.to_thread(_smtp_send, host, port, username, password, message, timeout)
        entry.status = 250  # SMTP "OK"
    except Exception as exc:
        entry.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        entry.ms = int((time.monotonic() - started) * 1000)


def get_log(include_local: bool = True, user_id: str | None = None) -> list[OutboundEntry]:
    """Every entry, or only one account's when user_id is given (the public site)."""
    entries = sorted([*_log, *_site_log], key=lambda e: e.id)
    return [e for e in entries if (include_local or not e.local) and (user_id is None or e.user_id == user_id)]


def clear_log(user_id: str | None = None) -> None:
    """Clear every entry, or only one account's."""
    for entries in (_log, _site_log):
        kept = [e for e in entries if user_id is not None and e.user_id != user_id]
        entries.clear()
        entries.extend(kept)
