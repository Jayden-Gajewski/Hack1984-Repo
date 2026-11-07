"""Companies for the account check: the checked-in list plus any company the user types.

data/companies.json is reviewed by hand: each entry has the company's own domains and, where
known, its privacy-policy URL. Any other company the user types is added here:

- A website ("tinder.com") is used as typed. Nothing is searched.
- A name ("Tinder") is matched to its official website with one Exa company search. Only the
  company name is sent, and the request appears in the outbound log. If the search fails or
  finds nothing usable, the domain is a guess from the name ("tinder.com"), labeled as a guess.

Stages 3, 4, 6 and 7 rely on the domains: privacy policies and contacts are only searched on
the company's own site, and alias mail is checked against them. Added companies are saved to
backend/local/companies.json, which is gitignored: which accounts a user has stays on this laptop.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.clients import exa
from app.data import load_json

log = logging.getLogger(__name__)

LOCAL_FILE = Path(__file__).resolve().parents[1] / "local" / "companies.json"

WEBSITE = re.compile(r"^(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})(?:[/:?#].*)?$", re.IGNORECASE)


def _lookup_data() -> dict[str, list[str]]:
    """data/website_lookup.json: `two_level_suffixes` (bbc.co.uk keeps three labels) and
    `not_a_homepage`, sites that describe or list companies rather than being them."""
    return load_json("website_lookup.json")


def registrable(host: str) -> str:
    """The domain a company owns for a hostname: www.microsoft.com -> microsoft.com."""
    host = host.lower().strip(".")
    host = host.removeprefix("www.")
    parts = host.split(".")
    keep = 3 if ".".join(parts[-2:]) in _lookup_data()["two_level_suffixes"] else 2
    return ".".join(parts[-keep:])


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def as_website(text: str) -> str | None:
    """The domain if the user typed a website ("tinder.com", "https://www.tinder.com/about")."""
    match = WEBSITE.match(text.strip())
    return registrable(match.group(1)) if match else None


def pick_domain(name: str, urls: list[str]) -> str | None:
    """The company's own website among search results: one whose domain matches the name,
    else the first that isn't a directory or social site. None when nothing fits.
    A name match wins even on a listed site, so adding "Facebook" still finds facebook.com."""
    squashed = _squash(name)
    skip = set(_lookup_data()["not_a_homepage"])
    domains: list[str] = []
    for url in urls:
        host = urlsplit(url).hostname
        if host and registrable(host) not in domains:
            domains.append(registrable(host))
    for domain in domains:
        label = _squash(domain.split(".")[0])
        if (len(label) >= 3 and label in squashed) or (len(squashed) >= 3 and squashed in label):
            return domain
    return next((d for d in domains if d not in skip), None)


def guess_domain(name: str) -> str:
    return f"{_squash(name) or 'company'}.com"


def _load_custom() -> list[dict[str, Any]]:
    try:
        return json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.warning("Couldn't read %s: %s", LOCAL_FILE, exc)
        return []


def _save_custom(items: list[dict[str, Any]]) -> None:
    LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def all_companies() -> list[dict[str, Any]]:
    """The checked-in list first, then companies the user added. Every entry has id, name,
    domains, privacy_url, custom and domain_source ("list", "typed", "search" or "guessed")."""
    listed = [{**c, "custom": False, "domain_source": "list"} for c in load_json("companies.json")]
    return listed + _load_custom()


def find_company(value: str) -> dict[str, Any] | None:
    """A known company by id, name or domain, case-insensitively."""
    wanted = value.strip().lower()
    for company in all_companies():
        if wanted in (company["id"], company["name"].lower()) or wanted in company["domains"]:
            return company
    return None


async def _find_website(name: str) -> tuple[str, str]:
    """(domain, how it was found). One Exa company search with the name only."""
    try:
        data = await exa.search(
            name, purpose=f"Find {name}'s official website", category="company", num_results=5
        )
        domain = pick_domain(name, [r.get("url", "") for r in data.get("results", [])])
        if domain:
            return domain, "search"
    except Exception as exc:  # no key, offline, or the search failed: fall back to a labeled guess
        log.warning("Couldn't look up %s's website: %s", name, exc)
    return guess_domain(name), "guessed"


async def add_company(text: str) -> dict[str, Any]:
    """Add a company the user typed (a name or a website) and return it. Typing one that's
    already known, by name, id or domain, returns the existing entry instead of a duplicate."""
    text = " ".join(text.split())
    website = as_website(text)
    existing = find_company(website or text)
    if existing:
        return existing
    if website:
        name, domain, source = website, website, "typed"
    else:
        name = text
        domain, source = await _find_website(text)
        existing = find_company(domain)  # "Ticketmaster Entertainment" -> the listed Ticketmaster
        if existing:
            return existing

    items = _load_custom()
    taken = {c["id"] for c in all_companies()}
    base = f"custom-{_squash(name)[:30] or 'company'}"
    company_id, n = base, 2
    while company_id in taken:
        company_id, n = f"{base}-{n}", n + 1
    company = {
        "id": company_id,
        "name": name,
        "domains": [domain],
        "privacy_url": None,
        "custom": True,
        "domain_source": source,
    }
    _save_custom(items + [company])
    return company
