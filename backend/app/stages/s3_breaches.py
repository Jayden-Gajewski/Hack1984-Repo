"""Stage 3: breach timelines. OWNER: Evidence.

For each company the user picked (ids from data/companies.json), search with the company
name only:
- Tavily news search (topic="news").
- Tavily search restricted to the state AG domains in data/breach_sources.json.
- Exa search with start_published_date.
The local LLM merges the snippets into BreachEvents. Normalize data_types to
models.FIELD_TYPES ("email addresses" is email, not address), label each date's kind and
source, and prefer AG notices.

Reference: `git show 2f13f74:server/stages/3-breaches.js`.
"""

from app.models import BreachEvent


async def breach_timelines(company_ids: list[str]) -> tuple[list[BreachEvent], list[str]]:
    """Return (breach events, errors). One company failing must not fail the others."""
    raise NotImplementedError
