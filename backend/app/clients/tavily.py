"""Tavily REST client. Calls the API directly, not through the SDK, so the log shows the exact payload.

Docs: https://docs.tavily.com (check them before relying on a parameter; the API changes).
"""

from typing import Any

from app.config import get_settings
from app.outbound import request

BASE_URL = "https://api.tavily.com"


def _auth_headers() -> dict[str, str]:
    key = get_settings().tavily_api_key
    if not key:
        raise RuntimeError("TAVILY_API_KEY is not set. Add it to .env at the repo root.")
    return {"Authorization": f"Bearer {key}"}


async def search(
    query: str,
    *,
    purpose: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    topic: str = "general",
    days: int | None = None,
) -> dict[str, Any]:
    """Web search. `query` is guarded: name and city only, or a company name."""
    body: dict[str, Any] = {"query": query, "max_results": max_results, "topic": topic}
    if include_domains:
        body["include_domains"] = include_domains
    if days is not None:
        body["days"] = days  # news topic only
    res = await request(
        "tavily",
        "POST",
        f"{BASE_URL}/search",
        purpose=purpose,
        guard=[query],
        headers=_auth_headers(),
        json_body=body,
    )
    res.raise_for_status()
    return res.json()


async def extract(urls: list[str], *, purpose: str, depth: str = "basic") -> dict[str, Any]:
    """Pull the text of up to 20 pages. Returns both `results` and `failed_results`,
    so callers can fall back to search snippets for blocked pages."""
    res = await request(
        "tavily",
        "POST",
        f"{BASE_URL}/extract",
        purpose=purpose,
        headers=_auth_headers(),
        json_body={"urls": urls[:20], "extract_depth": depth},
        timeout=60.0,
    )
    res.raise_for_status()
    return res.json()
