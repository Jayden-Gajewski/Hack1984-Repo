"""Stage 4: policy check. OWNER: Evidence.

Find each company's privacy policy (privacy_url in data/companies.json, else a Tavily search
restricted to its domains), Tavily Extract it with depth="advanced", chunk it (about 10k
chars, at most 6 chunks) and have the local LLM flag sale and sharing clauses. Each quote
must be verbatim: it's the "this wasn't a hack, they sold it" evidence. Sharing with service
providers, or only where the law requires it, doesn't count.

Reference: `git show 2f13f74:server/stages/4-policy.js`.
"""

from app.models import PolicyResult


async def check_policies(company_ids: list[str]) -> tuple[list[PolicyResult], list[str]]:
    """Return (one PolicyResult per company, errors)."""
    raise NotImplementedError
