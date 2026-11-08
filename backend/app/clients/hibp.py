"""Have I Been Pwned (HIBP) API v3. https://haveibeenpwned.com/API/v3

Two endpoints, both through outbound.request so they appear in the log:

- GET /breaches: HIBP's whole public breach catalog. No key, and nothing personal is sent.
  The threat monitor downloads all of it and matches companies on this laptop, so HIBP never
  learns which companies the user has accounts with.
- GET /breachedaccount/range/{prefix}: the k-anonymity email search (Pro and High RPM plans,
  key required). Only the first 6 characters of the address's SHA-1 hash are sent. HIBP answers
  with every hash suffix under that prefix; the caller keeps the one that matches and must
  discard the rest immediately (HIBP's terms). This module never sees an email address.

HIBP needs a user agent on every request (outbound sets one). Its breach data is licensed
CC BY 4.0: the UI shows "Have I Been Pwned" as the source, with a link.
"""

import re
from typing import Any

from app.config import get_settings
from app.outbound import request

BASE_URL = "https://haveibeenpwned.com/api/v3"
SITE_URL = "https://haveibeenpwned.com"
_PREFIX_RE = re.compile(r"^[0-9A-F]{6}$")

_STATUS_MESSAGES = {
    400: "HIBP rejected the request as malformed.",
    401: "HIBP rejected the API key. Check HIBP_API_KEY in .env.",
    403: "HIBP refused the request. The hashed email search needs a Pro or High RPM plan.",
    429: "HIBP's rate limit was reached.",
    503: "HIBP is unavailable right now.",
}


class HibpError(RuntimeError):
    """A failed HIBP call. `status` is the HTTP status (None when nothing was sent)."""

    def __init__(self, message: str, status: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _check(res: Any) -> Any:
    if res.status_code == 200:
        return res.json()
    retry = res.headers.get("retry-after", "")
    retry_after = int(retry) if retry.isdigit() else None
    message = _STATUS_MESSAGES.get(res.status_code, f"HIBP answered with status {res.status_code}.")
    if res.status_code == 429 and retry_after is not None:
        message += f" Try again in {retry_after} s."
    raise HibpError(message, res.status_code, retry_after)


async def breaches() -> list[dict[str, Any]]:
    """Every breach in HIBP's public catalog (about 1 MB). No key needed."""
    res = await request(
        "hibp",
        "GET",
        f"{BASE_URL}/breaches",
        purpose="Download Have I Been Pwned's full breach list (all of it, so it can't tell which companies you use)",
        timeout=30.0,
    )
    data = _check(res)
    if not isinstance(data, list):
        raise HibpError("HIBP's breach list came back in an unexpected format.")
    return [b for b in data if isinstance(b, dict)]


async def range_search(prefix: str) -> list[dict[str, Any]]:
    """[{hashSuffix, websites}] for every address whose SHA-1 hash starts with `prefix`."""
    key = get_settings().hibp_api_key
    if not key:
        raise HibpError("HIBP_API_KEY isn't set, so verified emails can't be checked.")
    prefix = prefix.upper()
    if not _PREFIX_RE.match(prefix):
        # Defense in depth: only a 6-character hash prefix may ever reach this endpoint.
        raise ValueError("The range search takes the first 6 hex characters of a SHA-1 hash, never an address.")
    res = await request(
        "hibp",
        "GET",
        f"{BASE_URL}/breachedaccount/range/{prefix}",
        purpose="Check a verified email with Have I Been Pwned (only the first 6 characters of its SHA-1 hash are sent)",
        guard=[prefix],
        headers={"hibp-api-key": key},
        timeout=20.0,
    )
    data = _check(res)
    if not isinstance(data, list):
        raise HibpError("HIBP's range search came back in an unexpected format.")
    return [item for item in data if isinstance(item, dict)]
