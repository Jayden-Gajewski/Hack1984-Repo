"""Stage 7: aliases and the inbox check. OWNER: Local LLM & ranking.

- Alias format: {company-slug}.{6 random hex}@{ALIAS_DOMAIN}. Save new aliases to
  backend/local/aliases.json (ALIASES_PATH; create the folder if it's missing).
- Inbox check, local only, no search: a message to a known alias whose sender domain isn't
  the company's domain (or a subdomain of it) is an AliasHit with tier proven.
- The demo reads data/mock_aliases.json and data/mock_inbox.json (fictional companies,
  .example domains). The ShopCo order email is legitimate and must not be flagged.

Reference: `git show 2f13f74:server/stages/7-alias.js`.
"""

from typing import Any

from app.config import LOCAL_DIR
from app.data import load_json
from app.models import Alias, AliasHit

ALIASES_PATH = LOCAL_DIR / "aliases.json"


def load_mock_aliases() -> list[Alias]:
    return [Alias(**a) for a in load_json("mock_aliases.json")["aliases"]]


def load_mock_inbox() -> list[dict[str, Any]]:
    return load_json("mock_inbox.json")["messages"]


def create_alias(company: str) -> Alias:
    """Make a new alias for `company` (an id from data/companies.json or a demo company name)."""
    raise NotImplementedError


def list_aliases() -> list[Alias]:
    """The demo aliases plus any saved in ALIASES_PATH."""
    raise NotImplementedError


def check_inbox() -> list[AliasHit]:
    """Pure and local: compare the mock inbox against the known aliases."""
    raise NotImplementedError
