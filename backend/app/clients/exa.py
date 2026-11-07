"""Exa REST client. Calls the API directly, not through the SDK, so the log shows the exact payload.

Docs: https://docs.exa.ai (check them before relying on a parameter; the API changes).
"""

from typing import Any

from app.config import get_settings
from app.outbound import request

BASE_URL = "https://api.exa.ai"


def _auth_headers() -> dict[str, str]:
    key = get_settings().exa_api_key
    if not key:
        raise RuntimeError("EXA_API_KEY is not set. Add it to .env at the repo root.")
    return {"x-api-key": key}


async def search(
    query: str,
    *,
    purpose: str,
    num_results: int = 5,
    include_domains: list[str] | None = None,
    category: str | None = None,
    start_published_date: str | None = None,
) -> dict[str, Any]:
    """Semantic search. `query` is guarded: name and city only, or a company name."""
    body: dict[str, Any] = {
        "query": query,
        "type": "auto",
        "numResults": num_results,
        "contents": {"text": {"maxCharacters": 2000}},
    }
    if include_domains:
        body["includeDomains"] = include_domains
    if category:
        body["category"] = category
    if start_published_date:
        body["startPublishedDate"] = start_published_date
    res = await request(
        "exa",
        "POST",
        f"{BASE_URL}/search",
        purpose=purpose,
        guard=[query],
        headers=_auth_headers(),
        json_body=body,
    )
    res.raise_for_status()
    return res.json()


async def find_similar(url: str, *, purpose: str, num_results: int = 10) -> dict[str, Any]:
    """Pages similar to `url`. Stage 1 uses it to discover broker sites we don't list yet."""
    res = await request(
        "exa",
        "POST",
        f"{BASE_URL}/findSimilar",
        purpose=purpose,
        headers=_auth_headers(),
        json_body={"url": url, "numResults": num_results, "excludeSourceDomain": True},
    )
    res.raise_for_status()
    return res.json()
