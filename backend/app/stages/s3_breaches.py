"""Stage 3: breach timelines. OWNER: Evidence.

For each company the user picked (ids from app.companies: the checked-in list plus added ones). Every query is the company
name only; nothing about the person is sent:
1. Gather sources: Tavily news search (10 years back), Tavily restricted to the state
   attorney general domains in data/breach_sources.json, and Exa with a start date.
2. Drop results that don't mention the company, and keep at most MAX_SOURCES.
3. Gemini merges them into breach events, citing each one by result number (so it
   can't invent a URL).
4. The code checks the answer: the source number must exist, a date is kept only if its
   year appears in that source, and a data type is kept only if that source mentions it
   (normalized to models.FIELD_TYPES; "email addresses" is email, not address).
5. Events are merged per company and year (one incident is usually reported by several
   sources): the AG notice wins, then an "occurred" date, then the most precise date.
   Undated events are only shown for a company with no dated ones; they can't support a
   "Likely" lead, and in testing they were mostly pages that mention the company in passing.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

from app import prompts
from app.clients import exa, gemini, tavily
from app.companies import all_companies
from app.data import load_json
from app.models import BreachEvent

MAX_SOURCES = 10
SNIPPET_CHARS = 500
NEWS_DAYS = 3650  # Tavily news only looks back 7 days unless told otherwise
EXA_START = "2010-01-01T00:00:00.000Z"
EXA_OBJECTIVE = (
    "News reports and official notices about data breaches at this company, with the date "
    "and the kinds of customer data that were exposed."
)
SOURCE_KIND_ORDER = {"ag_notice": 0, "news": 1, "web": 2}
_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")
_BANNED = re.compile(r"leaked by|who leaked", re.I)

# Checked in order, first match wins: "email address" must become email, not address.
_NOT_A_FIELD = ("ip address", "username", "user name", "mac address")
_SYNONYMS = (
    ("e-mail", "email"), ("email", "email"),
    ("social security", "ssn"), ("ssn", "ssn"),
    ("password", "password"), ("credential", "password"),
    ("birth", "birthdate"), ("dob", "birthdate"),
    ("phone", "phone"), ("telephone", "phone"),
    ("credit card", "financial"), ("card number", "financial"), ("payment", "financial"),
    ("bank", "financial"), ("financial", "financial"),
    ("health", "health"), ("medical", "health"), ("genetic", "health"),
    ("address", "address"),
    ("employ", "employer"),
    ("name", "name"),
)


# What a source has to say for a data type to count. "address" must not be an email or IP address.
_EVIDENCE = {
    "name": r"\bnames?\b",
    "email": r"e-?mail",
    "phone": r"phone",
    "address": r"(?<!email )(?<!e-mail )(?<!ip )address",
    "birthdate": r"birth|\bdob\b",
    "ssn": r"social security|\bssns?\b",
    "password": r"password|credential",
    "financial": r"credit card|debit card|card number|payment|bank|financial",
    "health": r"health|medical|genetic",
    "employer": r"employ",
}


@dataclass
class Source:
    url: str
    title: str
    snippet: str
    date: str | None  # YYYY-MM-DD, from the search API
    kind: str  # "ag_notice", "news" or "web"


# ---------- pure helpers (unit-tested) ----------


def normalize_data_type(word: Any) -> str | None:
    if not isinstance(word, str):
        return None
    w = word.strip().lower()
    if w in prompts.BREACH_TYPES:
        return w
    if any(bad in w for bad in _NOT_A_FIELD):
        return None
    return next((field for key, field in _SYNONYMS if key in w), None)


def result_date(value: Any) -> str | None:
    """ISO date from Exa ('2024-06-01T08:32:54.000Z') or Tavily news ('Wed, 12 Nov 2025 ...')."""
    if not isinstance(value, str) or not value.strip():
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def mentions_company(company: dict[str, Any], text: str) -> bool:
    lowered = text.lower()
    compact = re.sub(r"[^a-z0-9]", "", lowered)
    name = company["name"].lower()
    if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", lowered):
        return True
    # "Live Nation" vs "livenation": only for longer names ("att" would match "cyberattack").
    squashed = re.sub(r"[^a-z0-9]", "", name)
    if len(squashed) >= 5 and squashed in compact:
        return True
    # A domain's main label ("livenation" for livenation.com), if it's long enough to be specific.
    labels = [d.split(".")[0] for d in company.get("domains", [])]
    return any(len(label) >= 5 and label in compact for label in labels)


def parse_breaches(out: dict[str, Any], company: dict[str, Any], sources: list[Source]) -> list[BreachEvent]:
    raw = out.get("breaches")
    events: list[BreachEvent] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("source"))
        except (TypeError, ValueError):
            continue
        if not 1 <= index <= len(sources):
            continue
        source = sources[index - 1]

        when = _checked_date(item.get("date"), source)
        kind = item.get("date_kind") if item.get("date_kind") in ("occurred", "disclosed") else "unknown"
        if when is None:
            kind = "unknown"
        elif kind == "unknown":
            kind = "disclosed"  # a dated report with no stated kind is when it became public

        evidence = f"{source.title} {source.snippet}".lower()
        types: list[str] = []
        for word in item.get("data_types") if isinstance(item.get("data_types"), list) else []:
            field = normalize_data_type(word)
            if field and field not in types and re.search(_EVIDENCE[field], evidence):
                types.append(field)

        summary = item.get("summary") if isinstance(item.get("summary"), str) else ""
        summary = " ".join(summary.split())[:240]
        if _BANNED.search(summary):
            summary = ""
        events.append(
            BreachEvent(
                company_id=company["id"],
                company=company["name"],
                date=when,
                date_kind=kind,
                data_types=sorted(types, key=prompts.BREACH_TYPES.index),
                source_url=source.url,
                source_kind=source.kind,
                summary=summary or f"Data breach reported at {company['name']}.",
            )
        )
    return merge_events(events)


def _checked_date(value: Any, source: Source) -> str | None:
    """Keep a date only if it's well formed, plausible, and its year is in the source."""
    if not isinstance(value, str):
        return None
    match = _DATE_RE.match(value.strip())
    if not match:
        return None
    year, month, day = match.groups()
    if not 1995 <= int(year) <= date.today().year:
        return None
    try:
        date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return None
    evidence = f"{source.title} {source.snippet} {source.date or ''}"
    return value.strip() if year in evidence else None


def _best(event: BreachEvent) -> tuple[int, int, int]:
    """Lower is better: official source, then an "occurred" date, then the most precise date."""
    precision = len(event.date or "")
    return (SOURCE_KIND_ORDER[event.source_kind], event.date_kind != "occurred", -precision)


def merge_events(events: list[BreachEvent]) -> list[BreachEvent]:
    """One event per company and year; data types are merged. Undated events only when a
    company has no dated ones."""
    merged: dict[tuple[str, str], BreachEvent] = {}
    for event in events:
        key = (event.company_id, event.date[:4] if event.date else event.source_url)
        current = merged.get(key)
        if current is None:
            merged[key] = event
            continue
        types = sorted(set(current.data_types) | set(event.data_types), key=prompts.BREACH_TYPES.index)
        merged[key] = min(current, event, key=_best).model_copy(update={"data_types": types})
    dated = {e.company_id for e in merged.values() if e.date}
    kept = [e for e in merged.values() if e.date or e.company_id not in dated]
    return sorted(kept, key=lambda e: (e.date is None, e.date or ""))


def format_sources(sources: list[Source]) -> str:
    blocks = []
    for i, s in enumerate(sources, 1):
        label = {"ag_notice": "AG notice", "news": "news", "web": "web page"}[s.kind]
        blocks.append(f"[{i}] ({label}, dated {s.date or 'unknown'}) {s.url}\n{s.title}\n{s.snippet[:SNIPPET_CHARS]}")
    return "\n\n".join(blocks)


# ---------- the stage ----------


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


async def _gather_sources(company: dict[str, Any], errors: list[str]) -> list[Source]:
    name = company["name"]
    ag_domains = [s["domain"] for s in load_json("breach_sources.json")]
    news, ag, web = await asyncio.gather(
        tavily.search(
            f"{name} data breach",
            purpose=f"Find news about data breaches at {name}",
            topic="news",
            days=NEWS_DAYS,
            max_results=6,
        ),
        tavily.search(
            f"{name} data breach notification",
            purpose=f"Look for {name} on state attorney general breach notice sites",
            include_domains=ag_domains,
            max_results=5,
        ),
        exa.search(
            f"{name} data breach",
            purpose=f"Find reports of data breaches at {name}",
            objective=EXA_OBJECTIVE,
            start_published_date=EXA_START,
            num_results=6,
        ),
        return_exceptions=True,
    )

    def is_ag(url: str) -> bool:
        host = _host(url)
        return any(host == d or host.endswith("." + d) for d in ag_domains)

    sources: dict[str, Source] = {}

    def add(url: Any, title: Any, snippet: str, when: Any, kind: str) -> None:
        if not isinstance(url, str) or not url:
            return
        source = Source(url, title or "", snippet or "", result_date(when), "ag_notice" if is_ag(url) else kind)
        # News and web pages must be about the company (title or URL), not just mention it
        # in passing. AG notice pages often have generic titles, so their text counts too.
        about = f"{source.url} {source.title}"
        if source.kind == "ag_notice":
            about += f" {source.snippet}"
        if mentions_company(company, about):
            sources.setdefault(url.rstrip("/"), source)

    for label, result, kind in (("Tavily news search", news, "news"), ("AG notice search", ag, "web"), ("Exa search", web, "web")):
        if isinstance(result, Exception):
            errors.append(f"{name}: {label} failed: {result}")
            continue
        for r in result.get("results", []):
            snippet = r.get("content") if "content" in r else exa.snippet(r)
            add(r.get("url"), r.get("title"), snippet, r.get("published_date") or r.get("publishedDate"), kind)

    ranked = sorted(sources.values(), key=lambda s: SOURCE_KIND_ORDER[s.kind])  # AG notices first
    return ranked[:MAX_SOURCES]


async def _timeline(company: dict[str, Any], errors: list[str]) -> list[BreachEvent]:
    sources = await _gather_sources(company, errors)
    if not sources:
        return []
    answer = await gemini.ask_json(
        prompts.breach_prompt(company["name"], format_sources(sources)),
        system=prompts.BREACH_SYSTEM,
        purpose=f"Ask Gemini to build {company['name']}'s breach timeline",
    )
    if not answer:
        errors.append(f"Gemini didn't answer for {company['name']}, so its breaches weren't summarized.")
        return []
    return parse_breaches(answer, company, sources)


async def breach_timelines(company_ids: list[str]) -> tuple[list[BreachEvent], list[str]]:
    """Return (breach events for every picked company, oldest first, errors)."""
    companies = [c for c in all_companies() if c["id"] in company_ids]
    errors: list[str] = []
    timelines = await asyncio.gather(*(_timeline(c, errors) for c in companies))
    events = [event for timeline in timelines for event in timeline]
    return events, list(dict.fromkeys(errors))  # a missing key would repeat once per company
