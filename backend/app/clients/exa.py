"""Exa REST client. Calls the API directly, not through the SDK, so the log shows the exact payload.

Docs: https://exa.ai/docs (check them before relying on a parameter; the API changes).

Request shape follows Exa's guidance: query + type "auto" + contents.highlights, plus an
`objective` when the search is one step of a larger task. Every other field is opt-in and
only sent when a stage actually needs it (a broker allowlist, a breach date window).
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
    objective: str | None = None,
    num_results: int | None = None,
    include_domains: list[str] | None = None,
    category: str | None = None,
    start_published_date: str | None = None,
) -> dict[str, Any]:
    """Semantic search. Results carry `url`, `title`, `publishedDate` and `highlights` (list of str).

    `query` and `objective` are both sent to Exa, so both are guarded: name and city only,
    or a company name. Keep `objective` generic (what kind of page should rank first and
    what to pull from it); never put page text or personal details in it.
    Leave the optional filters unset unless the stage needs them; Exa's defaults are tuned.
    """
    body: dict[str, Any] = {
        "query": query,
        "type": "auto",
        "contents": {"highlights": True},
    }
    if objective:
        body["objective"] = objective
    if num_results is not None:
        body["numResults"] = num_results
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
        guard=[query] + ([objective] if objective else []),
        headers=_auth_headers(),
        json_body=body,
    )
    res.raise_for_status()
    return res.json()


def snippet(result: dict[str, Any]) -> str:
    """The text Exa returned for one search result (its highlights), for the snippet fallback."""
    return "\n".join(result.get("highlights") or [])
