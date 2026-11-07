"""Stage 7: aliases and the inbox check. OWNER: Local LLM & ranking.

- Alias format: {company-slug}.{6 random hex}@{ALIAS_DOMAIN}, saved to the `aliases` table
  in Postgres (db.save_alias).
- Inbox check, local only, no search: a message to a known alias whose sender domain isn't
  the company's domain (or a subdomain of it) is an AliasHit with tier proven.
  match_inbox() is the pure core, unit-tested with fixtures.
- The demo reads data/mock_aliases.json and data/mock_inbox.json (fictional companies,
  .example domains). The ShopCo order email is legitimate and must not be flagged.
"""

import asyncio
import logging
import re
import secrets
from typing import Any

from app import db
from app.config import get_settings
from app.data import load_json
from app.models import Alias, AliasHit

log = logging.getLogger(__name__)


def load_mock_aliases() -> list[Alias]:
    return [Alias(**a) for a in load_json("mock_aliases.json")["aliases"]]


def load_mock_inbox() -> list[dict[str, Any]]:
    return load_json("mock_inbox.json")["messages"]


def slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", company.lower())[:20] or "company"


def resolve_company(value: str) -> tuple[str, list[str]]:
    """(name, domains) for a company id or name from companies.json or the demo aliases."""
    wanted = value.strip().lower()
    for company in load_json("companies.json"):
        if wanted in (company["id"], company["name"].lower()):
            return company["name"], company["domains"]
    for alias in load_mock_aliases():
        if wanted == alias.company.lower():
            return alias.company, alias.company_domains
    raise LookupError(f"Unknown company: {value}. Pick one from the account list.")


def match_inbox(aliases: list[Alias], messages: list[dict[str, Any]]) -> list[AliasHit]:
    """Pure: mail to an alias from outside its company's domains is a proven hit."""
    by_address = {a.alias.lower(): a for a in aliases}
    hits = []
    for message in messages:
        alias = by_address.get(str(message.get("to", "")).lower())
        sender = str(message.get("from", ""))
        if alias is None or "@" not in sender or not alias.company_domains:
            continue  # not one of ours, or nothing to compare against
        domain = sender.rsplit("@", 1)[1].lower()
        if any(domain == d or domain.endswith("." + d) for d in alias.company_domains):
            continue  # the company itself: legitimate
        hits.append(
            AliasHit(
                alias=alias.alias,
                company=alias.company,
                from_address=sender,
                from_domain=domain,
                subject=str(message.get("subject", "")),
                date=message.get("date"),
            )
        )
    return hits


async def create_alias(company: str) -> Alias:
    """Make and save a new alias for `company` (an id or name, see resolve_company)."""
    name, domains = resolve_company(company)
    alias = f"{slug(name)}.{secrets.token_hex(3)}@{get_settings().alias_domain}"
    try:
        created = await asyncio.to_thread(db.save_alias, alias, name, domains)
    except Exception as exc:
        raise RuntimeError(
            "Postgres isn't reachable, so the alias couldn't be saved. Start it with `docker compose up -d`."
        ) from exc
    return Alias(alias=alias, company=name, company_domains=domains, created_at=created)


async def list_aliases() -> list[Alias]:
    """The demo aliases plus every alias saved in Postgres (just the demo ones if it's down)."""
    try:
        saved = await asyncio.to_thread(db.list_aliases)
    except Exception as exc:
        log.warning("Couldn't read saved aliases from Postgres: %s", exc)
        saved = []
    return load_mock_aliases() + [Alias(**row) for row in saved]


async def check_inbox() -> list[AliasHit]:
    """Compare the mock inbox against every known alias. Local only, no search."""
    return match_inbox(await list_aliases(), load_mock_inbox())
