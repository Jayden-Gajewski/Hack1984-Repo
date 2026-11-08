"""Stage 7: aliases and the inbox check. OWNER: Local LLM & ranking.

- Alias format: {company-slug}.{6 random hex}@{ALIAS_DOMAIN}, saved to the `aliases` table
  in Postgres (db.save_alias).
- Inbox check, local only, no search: a message to a known alias whose sender domain isn't
  the company's domain (or a subdomain of it) is an AliasHit with tier proven.
  match_inbox() is the pure core, unit-tested with fixtures.
- The demo reads data/mock_aliases.json and data/mock_inbox.json (fictional companies,
  .example domains). The ShopCo order email is legitimate and must not be flagged.
- Identity manager: an alias can be made for a website (one per signup), belongs to the
  signed-in account, and can be disabled with a note. Messages per alias come from the mock
  inbox (alias_messages, pure). Nothing here receives real mail or leaves the laptop.
- Investigate: rules (investigation_facts, pure) set the facts and the Proven tier; the local
  LLM only explains them, and clean_explanation drops sentences that fail the checks. The
  model sees the company, sender domains, dates and subjects, never the alias or a full address.
"""

import asyncio
import logging
import re
import secrets
from datetime import date
from typing import Any

from app import db, prompts
from app.clients import ollama
from app.companies import all_companies
from app.config import get_settings
from app.data import load_json
from app.models import Alias, AliasHit, AliasInvestigation, AliasMessage, SenderFact

log = logging.getLogger(__name__)

DB_DOWN = "Postgres isn't reachable, so the alias couldn't be saved. Start it with `docker compose up -d`."


def load_mock_aliases() -> list[Alias]:
    return [Alias(**a, demo=True) for a in load_json("mock_aliases.json")["aliases"]]


def load_mock_inbox() -> list[dict[str, Any]]:
    return load_json("mock_inbox.json")["messages"]


def slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", company.lower())[:20] or "company"


def resolve_company(value: str) -> tuple[str, list[str]]:
    """(name, domains) for a company id or name from the company list or the demo aliases."""
    wanted = value.strip().lower()
    for company in all_companies():
        if wanted in (company["id"], company["name"].lower()):
            return company["name"], company["domains"]
    for alias in load_mock_aliases():
        if wanted == alias.company.lower():
            return alias.company, alias.company_domains
    raise LookupError(f"Unknown company: {value}. Pick one from the account list.")


def site_word(site: str) -> str:
    """The name part of a hostname for the alias prefix: shop.example -> shop,
    mail.shop.co.uk -> shop."""
    labels = site.split(".")[:-1] or [site]
    if len(labels) > 1 and labels[-1] in {"co", "com", "org", "net", "ac", "gov", "edu"}:
        labels = labels[:-1]
    return labels[-1]


def resolve_site(site: str) -> tuple[str, list[str]]:
    """(name, expected sender domains) for a website: the company from the list if one owns
    that domain, otherwise the site itself. Local only, no lookup."""
    for company in all_companies():
        if any(site == d or site.endswith("." + d) for d in company["domains"]):
            return company["name"], company["domains"]
    return site, [site]


def _is_expected(domain: str, company_domains: list[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in company_domains)


def alias_messages(alias: Alias, messages: list[dict[str, Any]]) -> list[AliasMessage]:
    """Pure: the messages sent to one alias, newest first, each marked expected or not and
    blocked when the alias was disabled on or before that day."""
    found = []
    for message in messages:
        sender = str(message.get("from", ""))
        if str(message.get("to", "")).lower() != alias.alias.lower() or "@" not in sender:
            continue
        domain = sender.rsplit("@", 1)[1].lower()
        day = message.get("date")
        found.append(
            AliasMessage(
                alias=alias.alias,
                from_address=sender,
                from_domain=domain,
                subject=str(message.get("subject", "")),
                date=day,
                expected=_is_expected(domain, alias.company_domains),
                blocked=bool(alias.disabled_at and day and str(day)[:10] >= alias.disabled_at),
            )
        )
    return sorted(found, key=lambda m: m.date or "", reverse=True)


def with_inbox_counts(alias: Alias, messages: list[dict[str, Any]]) -> Alias:
    mine = alias_messages(alias, messages)
    return alias.model_copy(
        update={
            "message_count": len(mine),
            "unexpected_count": sum(not m.expected for m in mine),
            "last_message_at": next((m.date for m in mine if m.date), None),
        }
    )


def match_inbox(aliases: list[Alias], messages: list[dict[str, Any]]) -> list[AliasHit]:
    """Pure: mail to an alias from outside its company's domains is a proven hit. A disabled
    alias still counts: the mail is evidence whether or not it was delivered."""
    by_address = {a.alias.lower(): a for a in aliases}
    hits = []
    for message in messages:
        alias = by_address.get(str(message.get("to", "")).lower())
        sender = str(message.get("from", ""))
        if alias is None or "@" not in sender or not alias.company_domains:
            continue  # not one of ours, or nothing to compare against
        domain = sender.rsplit("@", 1)[1].lower()
        if _is_expected(domain, alias.company_domains):
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


async def create_alias(company: str | None = None, site: str | None = None, label: str = "") -> Alias:
    """Make and save a new alias, for a company (an id or name, see resolve_company) or for a
    website (already normalized by models.AliasRequest). Every call makes a fresh address."""
    if site:
        name, domains = resolve_site(site)
        prefix = slug(site_word(site))
    else:
        name, domains = resolve_company(company or "")
        prefix = slug(name)
    alias = f"{prefix}.{secrets.token_hex(3)}@{get_settings().alias_domain}"
    try:
        created = await asyncio.to_thread(db.save_alias, alias, name, domains, site or "", label.strip())
    except Exception as exc:
        raise RuntimeError(DB_DOWN) from exc
    return with_inbox_counts(
        Alias(alias=alias, company=name, company_domains=domains, created_at=created, site=site or "", label=label.strip()),
        load_mock_inbox(),
    )


async def _states() -> dict[str, dict[str, Any]]:
    try:
        return await asyncio.to_thread(db.alias_states)
    except Exception as exc:
        log.warning("Couldn't read alias settings from Postgres: %s", exc)
        return {}


async def list_aliases() -> list[Alias]:
    """The demo aliases plus this account's saved ones (just the demo ones if Postgres is
    down), each with its status, note and mock-inbox counts."""
    try:
        saved = await asyncio.to_thread(db.list_aliases)
    except Exception as exc:
        log.warning("Couldn't read saved aliases from Postgres: %s", exc)
        saved = []
    states = await _states()
    inbox = load_mock_inbox()
    return [
        with_inbox_counts(a.model_copy(update=states.get(a.alias.lower(), {})), inbox)
        for a in load_mock_aliases() + [Alias(**row) for row in saved]
    ]


async def get_alias(address: str) -> Alias:
    wanted = address.strip().lower()
    for alias in await list_aliases():
        if alias.alias.lower() == wanted:
            return alias
    raise LookupError("That alias isn't one of yours.")


async def update_alias(address: str, status: str | None, note: str | None) -> Alias:
    """Disable or re-enable an alias, or change its note."""
    alias = await get_alias(address)
    if status is None and note is None:
        return alias
    try:
        state = await asyncio.to_thread(db.set_alias_state, alias.alias, status, note.strip() if note else note)
    except Exception as exc:
        raise RuntimeError(DB_DOWN.replace("the alias couldn't be saved", "the change couldn't be saved")) from exc
    return with_inbox_counts(alias.model_copy(update=state), load_mock_inbox())


async def messages_for(address: str) -> list[AliasMessage]:
    """One alias's mail from the mock inbox. Local only."""
    return alias_messages(await get_alias(address), load_mock_inbox())


# ---------- investigate one alias (Phase 2) ----------

_BANNED = re.compile(r"leaked by|who leaked", re.I)
_CERTAIN = re.compile(r"\b(sold|leaked|gave away|handed over|shared)\b", re.I)
_HEDGE = re.compile(r"\b(likely|may|might|could|possibl\w*|probabl\w*|suggests?|appears?|seems?|if)\b", re.I)
_NUMBER = re.compile(r"\d+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
MAX_EXPLANATION_CHARS = 600


def _sender_kind(domain: str) -> tuple[str, str]:
    """(kind, name) for a sender domain, from the checked-in lists only."""
    for broker in load_json("brokers.json"):
        if domain == broker["domain"] or domain.endswith("." + broker["domain"]):
            return "data_broker", broker["name"]
    for company in all_companies():
        if _is_expected(domain, company["domains"]):
            return "known_company", company["name"]
    return "unknown", ""


def _days_between(start: str | None, end: str | None) -> int | None:
    try:
        return (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days
    except (TypeError, ValueError):
        return None


def investigation_facts(alias: Alias, messages: list[AliasMessage]) -> AliasInvestigation:
    """Pure: the rule-based half of an investigation. Every date says where it came from."""
    unexpected = [m for m in messages if not m.expected]
    facts = [f"You made this alias for {alias.company} on {alias.created_at} (date saved in this app)."]
    if alias.demo:
        facts[0] = f"This demo alias was made for {alias.company} on {alias.created_at} (date in the demo data)."
    senders: list[SenderFact] = []
    for domain in dict.fromkeys(m.from_domain for m in sorted(unexpected, key=lambda m: m.date or "")):
        mine = [m for m in unexpected if m.from_domain == domain]
        first = min((m.date for m in mine if m.date), default=None)
        kind, name = _sender_kind(domain)
        senders.append(SenderFact(domain=domain, kind=kind, name=name, count=len(mine), first_seen=first))
        times = "once" if len(mine) == 1 else f"{len(mine)} times"
        when = f", first on {first} (date on the message)" if first else ", date unknown"
        facts.append(f"{domain}, which isn't {alias.company}, wrote {times}{when}.")
        if kind == "data_broker":
            facts.append(f"{domain} is {name}, a people-search site on our broker list.")
        elif kind == "known_company":
            facts.append(f"{domain} belongs to {name}, a different company on our list.")
    first_unexpected = min((s.first_seen for s in senders if s.first_seen), default=None)
    days = _days_between(alias.created_at, first_unexpected)
    if days is not None and days >= 0:
        facts.append(f"The first unexpected message came {days} days after the alias was made.")
    if not unexpected:
        facts.append(
            f"All {len(messages)} messages came from {alias.company}'s own domains."
            if messages else "This alias hasn't received any mail in the mock inbox."
        )
    if alias.status == "disabled" and alias.disabled_at:
        facts.append(f"You turned this alias off on {alias.disabled_at}. Mail from that day on is marked blocked.")
    return AliasInvestigation(
        alias=alias.alias,
        company=alias.company,
        tier="proven" if unexpected else None,
        facts=facts,
        senders=senders,
        days_to_first_unexpected=days if days is not None and days >= 0 else None,
        category="legit" if messages and not unexpected else "unknown",
    )


def clean_explanation(text: Any, facts: list[str]) -> str:
    """Keep only sentences that pass the checks: no banned wording, no sale or leak stated as
    certain, and no number (2+ digits) that the facts don't contain."""
    if not isinstance(text, str):
        return ""
    evidence = " ".join(facts)
    kept = []
    for sentence in _SENTENCE.split(" ".join(text.split())):
        if not sentence or _BANNED.search(sentence):
            continue
        if _CERTAIN.search(sentence) and not _HEDGE.search(sentence):
            continue
        if any(len(n) >= 2 and n not in evidence for n in _NUMBER.findall(sentence)):
            continue
        kept.append(sentence)
    out = " ".join(kept)
    if len(out) > MAX_EXPLANATION_CHARS:
        cut = out[:MAX_EXPLANATION_CHARS]
        out = cut[: cut.rfind(". ") + 1] or cut.rstrip() + "…"
    return out


async def investigate(address: str) -> AliasInvestigation:
    """Rules first, then a local LLM explanation when there's unexpected mail to explain."""
    alias = await get_alias(address)
    messages = alias_messages(alias, load_mock_inbox())
    result = investigation_facts(alias, messages)
    if result.tier is None:
        return result  # nothing unexpected: the facts say it all, no model call needed
    answer = await ollama.ask_json(
        prompts.alias_prompt(
            alias.company, alias.company_domains, result.facts,
            [(m.date or "", m.from_domain, m.subject) for m in messages],
        ),
        system=prompts.ALIAS_SYSTEM,
        purpose=f"Explain on this laptop the unexpected mail to your {alias.company} alias",
    )
    if not answer:
        result.errors.append("The local LLM didn't answer, so only the facts are shown. Is Ollama running?")
        return result
    category = answer.get("category")
    if category in prompts.ALIAS_CATEGORIES and category != "legit":  # rules already ruled out legit
        result.category = category
    result.explanation = clean_explanation(answer.get("explanation"), result.facts)
    result.explained_locally = bool(result.explanation)
    return result


async def check_inbox() -> list[AliasHit]:
    """Compare the mock inbox against every known alias. Local only, no search."""
    return match_inbox(await list_aliases(), load_mock_inbox())
