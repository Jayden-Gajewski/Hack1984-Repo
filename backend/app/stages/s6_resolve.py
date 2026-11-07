"""Stage 6: resolve. OWNER: Search & extract.

- Broker opt-out URL: data/brokers.json, else a Tavily search restricted to the broker's
  domain for "opt out remove my information".
- Company privacy contact: a Tavily search restricted to the company's domains. Prefer a
  privacy@ style email on that domain, else the request page URL.
- Drafts are fixed templates filled in locally (deterministic for the demo), with name and
  city only, never more.
- Re-scan: re-extract old listing URLs. "removed" means the page loaded and no longer names
  the person, "still_listed" means it does, "unconfirmed" means it was blocked or failed.

Reference (it has draft templates to start from): `git show 2f13f74:server/stages/6-resolve.js`.
"""

from app.models import Draft, Exposure, RescanItem, ScanRequest


async def draft_broker_opt_out(exposure: Exposure, person: ScanRequest) -> Draft:
    """Ask the broker to delete the listing, stop selling or sharing it, and say where it got the data."""
    raise NotImplementedError


async def draft_company_request(company_id: str, person: ScanRequest) -> Draft:
    """Ask the company who it sold or shared the data with, to opt the person out, and to delete it."""
    raise NotImplementedError


async def rescan(
    exposures: list[Exposure], person: ScanRequest
) -> tuple[list[RescanItem], list[str]]:
    """Return (one RescanItem per exposure, errors)."""
    raise NotImplementedError
