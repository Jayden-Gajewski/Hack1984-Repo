"""Stage 1: find exposures. OWNER: Search & extract.

Full spec: backend/app/stages/CLAUDE.md. In short:
1. Tavily search '"{name}" {city} {state}' restricted to the domains in data/brokers.json,
   plus Exa search and find_similar to discover brokers we don't list yet.
2. Drop candidates whose URL, title and snippet don't mention the last name.
3. Tavily Extract the rest. If a broker blocks it, use the search snippet (text_source="snippet").
4. Ask the local LLM (prompts.field_extraction_prompt + clients.ollama.ask_json) whether it's
   this person and which fields it shows. Keep confidence >= 0.5 and only models.FIELD_TYPES.
5. Fill broker, broker_id and opt_out_url from data/brokers.json.

Reference: the team's earlier JS version, `git show 2f13f74:server/stages/1-exposures.js`.
"""

from app.models import Exposure, ScanRequest


async def find_exposures(req: ScanRequest) -> tuple[list[Exposure], list[str]]:
    """Return (exposures, errors). Catch per-broker failures and report them in errors."""
    raise NotImplementedError
