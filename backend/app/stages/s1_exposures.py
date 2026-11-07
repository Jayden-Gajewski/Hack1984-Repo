"""Stage 1: find exposures. OWNER: Search & extract.

Full spec: backend/app/stages/CLAUDE.md. What this does:
1. Discover candidate pages, using name + city/state only:
   - Tavily search restricted to the broker domains in data/brokers.json.
   - Exa search for the person plus "people search profile" (finds sites we don't list).
   - Exa find_similar on one known-broker hit; the new domains it returns get a Tavily
     search restricted to them.
2. Drop candidates whose URL, title and snippet don't mention the last name, and keep at
   most MAX_CANDIDATES (known brokers first): each one costs a local LLM call.
3. Tavily Extract the rest. Blocked or thin pages fall back to the search snippet
   (text_source="snippet").
4. The local LLM decides whether the page is this person and which fields it shows. Only
   answers with confidence >= 0.5 and quotes that really appear in the text are kept.
   Pages on unknown domains must also be people-search listings.
5. Fill broker, broker_id and opt_out_url from data/brokers.json.

Before searching anything, it checks that there's a search key and that the local LLM is
ready, so a scan never spends API credits on pages it can't analyze.
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app import prompts
from app.clients import exa, ollama, tavily
from app.config import get_settings
from app.data import load_json
from app.models import Exposure, FieldFinding, ScanRequest

MAX_CANDIDATES = 20  # pages extracted and analyzed per scan; each one is a local LLM call
MIN_CONFIDENCE = 0.5
MIN_EXTRACT_CHARS = 500  # extracted text shorter than this is almost always a block page
MAX_QUOTE_CHARS = 200
MAX_NEW_DOMAINS = 10
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@dataclass
class Candidate:
    url: str
    title: str
    snippet: str
    via: str  # "tavily" or "exa"
    published_date: str | None = None


# ---------- small pure helpers (unit-tested) ----------


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def normalize_url(url: str) -> str:
    """Dedupe key: lowercase host without www., no fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host_of(url), path, parts.query, ""))


def broker_for(url: str, brokers: list[dict[str, Any]]) -> dict[str, Any] | None:
    host = host_of(url)
    for broker in brokers:
        if host == broker["domain"] or host.endswith("." + broker["domain"]):
            return broker
    return None


def last_name(full_name: str) -> str:
    tokens = [t.strip(".,").lower() for t in full_name.split()]
    tokens = [t for t in tokens if t and t not in _NAME_SUFFIXES]
    return tokens[-1] if tokens else ""


def mentions(candidate: Candidate, surname: str) -> bool:
    # Only the URL's path and query count: a surname can also appear in a domain name
    # (e.g. "People" in peoplefinders.com), which says nothing about the page.
    parts = urlsplit(candidate.url)
    return surname in f"{parts.path} {parts.query} {candidate.title} {candidate.snippet}".lower()


def iso_date(value: Any) -> str | None:
    """'2023-05-01T00:00:00.000Z' -> '2023-05-01'. Anything else is unknown, never a guess."""
    if isinstance(value, str) and _ISO_DATE_RE.match(value):
        return value[:10]
    return None


def _squash(text: str) -> str:
    return " ".join(text.split()).lower()


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def parse_analysis(
    out: dict[str, Any], source_text: str, known_broker: bool
) -> list[FieldFinding] | None:
    """Validate the local LLM's answer. Returns the grounded fields if the page is this
    person, or None if it isn't (or the answer can't be trusted).

    Page text is untrusted and small models drift, so: booleans and confidence are
    checked, fields are limited to prompts.LISTING_FIELDS, and every quote must appear
    in the page text.
    """
    if not _truthy(out.get("is_same_person")):
        return None
    try:
        confidence = float(out.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if confidence > 1:  # some models answer in percent
        confidence /= 100
    if confidence < MIN_CONFIDENCE:
        return None
    if not known_broker and not _truthy(out.get("is_people_search_site")):
        return None

    haystack = _squash(source_text)
    raw_fields = out.get("fields")
    fields: list[FieldFinding] = []
    seen: set[str] = set()
    for item in raw_fields if isinstance(raw_fields, list) else []:
        if not isinstance(item, dict):
            continue
        field, quote = item.get("field"), item.get("quote")
        if field not in prompts.LISTING_FIELDS or field in seen or not isinstance(quote, str):
            continue
        quote = " ".join(quote.split())[:MAX_QUOTE_CHARS]
        if not quote or _squash(quote) not in haystack:
            continue  # not in the page: the model made it up
        if field == "address" and not any(ch.isdigit() for ch in quote):
            continue  # just a city or state (what we searched with), not a street address
        seen.add(field)
        fields.append(FieldFinding(field=field, quote=quote))
    return fields


def exposure_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:12]


# ---------- the stage ----------


def _from_tavily(result: dict[str, Any]) -> Candidate | None:
    if not result.get("url"):
        return None
    return Candidate(
        url=result["url"],
        title=result.get("title") or "",
        snippet=result.get("content") or "",
        via="tavily",
        published_date=iso_date(result.get("published_date")),
    )


def _from_exa(result: dict[str, Any]) -> Candidate | None:
    if not result.get("url"):
        return None
    return Candidate(
        url=result["url"],
        title=result.get("title") or "",
        snippet=result.get("text") or "",
        via="exa",
        published_date=iso_date(result.get("publishedDate")),
    )


async def _discover(
    req: ScanRequest, brokers: list[dict[str, Any]], errors: list[str]
) -> list[Candidate]:
    query = f'"{req.name}" {req.city} {req.state}'
    found: dict[str, Candidate] = {}

    def add(candidate: Candidate | None) -> None:
        if candidate is not None:
            found.setdefault(normalize_url(candidate.url), candidate)

    tavily_res, exa_res = await asyncio.gather(
        tavily.search(
            query,
            purpose="Look for your listings on known people-search sites",
            include_domains=[b["domain"] for b in brokers],
            max_results=20,
        ),
        exa.search(
            f"{req.name} {req.city} {req.state} people search profile",
            purpose="Find people-search pages about you, including sites we don't list yet",
            num_results=10,
        ),
        return_exceptions=True,
    )
    if isinstance(tavily_res, Exception):
        errors.append(f"Tavily search failed: {tavily_res}")
    else:
        for result in tavily_res.get("results", []):
            add(_from_tavily(result))
    if isinstance(exa_res, Exception):
        errors.append(f"Exa search failed: {exa_res}")
    else:
        for result in exa_res.get("results", []):
            add(_from_exa(result))

    surname = last_name(req.name)
    seed = next(
        (c for c in found.values() if broker_for(c.url, brokers) and mentions(c, surname)),
        None,
    )
    if seed is not None:
        await _discover_similar(seed, query, brokers, add, errors)

    candidates = [c for c in found.values() if mentions(c, surname)]
    candidates.sort(key=lambda c: broker_for(c.url, brokers) is None)  # known brokers first
    return candidates[:MAX_CANDIDATES]


async def _discover_similar(
    seed: Candidate, query: str, brokers: list[dict[str, Any]], add, errors: list[str]
) -> None:
    """Find broker sites we don't list yet, then search them for this person."""
    seed_broker = broker_for(seed.url, brokers)
    try:
        similar = await exa.find_similar(
            seed.url,
            purpose=f"Discover people-search sites similar to {seed_broker['name']}",
            num_results=10,
        )
        new_domains = sorted(
            {host_of(r["url"]) for r in similar.get("results", []) if r.get("url")}
            - {""}
            - {host_of(seed.url)}
        )
        new_domains = [d for d in new_domains if broker_for(f"https://{d}/", brokers) is None]
        if not new_domains:
            return
        more = await tavily.search(
            query,
            purpose="Look for your listings on newly discovered people-search sites",
            include_domains=new_domains[:MAX_NEW_DOMAINS],
            max_results=10,
        )
        for result in more.get("results", []):
            add(_from_tavily(result))
    except Exception as exc:
        errors.append(f"Finding similar people-search sites failed: {exc}")


async def _extract(candidates: list[Candidate], errors: list[str]) -> dict[str, str]:
    """Page text by normalized URL. Pages that fail or are blocked are simply missing."""
    texts: dict[str, str] = {}
    batches = [candidates[i : i + 20] for i in range(0, len(candidates), 20)]
    results = await asyncio.gather(
        *(
            tavily.extract([c.url for c in batch], purpose=f"Read the text of {len(batch)} listing pages")
            for batch in batches
        ),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            errors.append(f"Tavily Extract failed, so these cards use search snippets: {result}")
            continue
        for item in result.get("results", []):
            if item.get("url") and item.get("raw_content"):
                texts[normalize_url(item["url"])] = item["raw_content"]
    return texts


async def _preflight() -> list[str]:
    """Problems that would make the whole scan pointless. Checked before any search."""
    settings = get_settings()
    problems = []
    if not settings.tavily_api_key and not settings.exa_api_key:
        problems.append(
            "No search API keys are set. Add TAVILY_API_KEY and EXA_API_KEY to .env at the repo root."
        )
    running, pulled = await ollama.status()
    if not running:
        problems.append(
            "The local LLM isn't running, so nothing was searched. Start Ollama, then try again."
        )
    elif not pulled:
        problems.append(
            f"The local LLM model isn't downloaded yet. Run: ollama pull {settings.ollama_model}"
        )
    return problems


async def find_exposures(req: ScanRequest) -> tuple[list[Exposure], list[str]]:
    """Return (exposures, errors). Per-source failures go in errors; this never raises."""
    errors = await _preflight()
    if errors:
        return [], errors

    brokers = load_json("brokers.json")
    candidates = await _discover(req, brokers, errors)
    if not candidates:
        return [], errors

    texts = await _extract(candidates, errors)
    surname = last_name(req.name)
    jobs: list[tuple[Candidate, str, str]] = []
    for candidate in candidates:
        extracted = texts.get(normalize_url(candidate.url), "")
        if len(extracted) >= MIN_EXTRACT_CHARS and surname in extracted.lower():
            jobs.append((candidate, extracted, "extract"))
        elif candidate.snippet.strip():
            jobs.append((candidate, candidate.snippet, "snippet"))

    answers = await asyncio.gather(
        *(
            ollama.ask_json(
                prompts.field_extraction_prompt(req.name, req.city, req.state, text),
                system=prompts.FIELD_EXTRACTION_SYSTEM,
                purpose=f"Check on this laptop whether the {host_of(c.url)} page is you, and what it shows",
            )
            for c, text, _ in jobs
        )
    )

    exposures: list[Exposure] = []
    unanswered = 0
    for (candidate, text, text_source), answer in zip(jobs, answers):
        if not answer:
            unanswered += 1
            continue
        broker = broker_for(candidate.url, brokers)
        fields = parse_analysis(answer, text, known_broker=broker is not None)
        if fields is None:
            continue
        exposures.append(
            Exposure(
                id=exposure_id(candidate.url),
                broker=broker["name"] if broker else host_of(candidate.url),
                broker_id=broker["id"] if broker else None,
                url=candidate.url,
                title=candidate.title,
                found_via=candidate.via,
                text_source=text_source,
                fields=fields,
                published_date=candidate.published_date,
                opt_out_url=broker.get("opt_out_url") if broker else None,
            )
        )
    if unanswered:
        errors.append(
            f"The local LLM didn't answer for {unanswered} of {len(jobs)} pages, so they weren't checked."
        )
    return exposures, errors
