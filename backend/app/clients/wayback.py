"""Wayback Machine CDX client. No key needed, but archive.org is slow and flaky, so this
uses short timeouts and at most 4 requests at once.

The broker URL (which can include the person's name) goes to archive.org. That's expected,
and it shows in the outbound log.
"""

import asyncio

from app.outbound import request

CDX_URL = "https://web.archive.org/cdx/search/cdx"
_slots = asyncio.Semaphore(4)


async def earliest_snapshot(url: str, *, purpose: str) -> str | None:
    """Return the earliest archived timestamp (YYYYMMDDhhmmss) with HTTP 200, or None."""
    async with _slots:
        res = await request(
            "wayback",
            "GET",
            CDX_URL,
            purpose=purpose,
            params={
                "url": url,
                "output": "json",
                "fl": "timestamp,original",
                "filter": "statuscode:200",
                "limit": 1,
            },
            timeout=10.0,
        )
    res.raise_for_status()
    if not res.text.strip():
        return None
    rows = res.json()
    # The first row is a header. A second row, if present, is the earliest snapshot.
    return rows[1][0] if len(rows) > 1 else None


def snapshot_url(timestamp: str, url: str) -> str:
    """Link to the archived page, for the evidence link on a card."""
    return f"https://web.archive.org/web/{timestamp}/{url}"


def timestamp_to_date(timestamp: str) -> str:
    """'20210315120000' -> '2021-03-15'."""
    return f"{timestamp[0:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
