"""Stage 1: find exposures. OWNER: Search & extract.

Full spec: backend/app/stages/CLAUDE.md. What this does:
1. Discover candidate pages, using name + city/state only:
   - Tavily search restricted to the broker domains in data/brokers.json.
   - Tavily search restricted to the public-profile sites in data/public_profiles.json
     (sports results and similar pages that show a name with a school or team).
   - Exa search for the person plus "people search profile" (finds sites we don't list).
   - Exa search for sites like one known-broker hit (company-only query: the broker's
     domain, never the page URL); the new domains it returns get a Tavily search
     restricted to them.
2. Drop candidates whose URL, title and snippet don't mention the last name, and keep at
   most MAX_CANDIDATES (known brokers first): each one costs a local LLM call.
3. Tavily Extract the rest. Blocked or thin pages fall back to the search snippet
   (text_source="snippet"). Extracted pages are cut down to the text around the surname
   (focus_text) before the LLM reads them: menus and other people's listings only slow it down.
   The model loads (ollama.warm_up) while the searches run.
4. The local LLM decides whether the page is this person and which fields it shows
   (prompts.LISTING_FIELDS for brokers, prompts.PROFILE_FIELDS for public profiles). Only
   answers with confidence >= 0.5 and quotes that really appear in the text are kept.
   Pages on unknown domains must also be people-search listings.
5. Fill broker, broker_id, source_kind and opt_out_url from the site lists.

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
FOCUS_WINDOW = 600  # chars kept on each side of a surname mention
FOCUS_MAX_CHARS = 4_000  # the LLM reads ~4x faster than with a full 12k-char page
MAX_ANSWER_TOKENS = 500  # longest valid answer (8 fields, 200-char quotes) is ~400 tokens
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


def known_site(
    url: str, brokers: list[dict[str, Any]], profiles: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str]:
    """(site entry, source kind) for a URL. Unlisted domains count as brokers: the only
    unlisted pages that survive are ones the LLM says are people-search listings."""
    broker = broker_for(url, brokers)
    if broker is not None:
        return broker, "broker"
    profile = broker_for(url, profiles)
    if profile is not None:
        return profile, "public_profile"
    return None, "broker"


def last_name(full_name: str) -> str:
    tokens = [t.strip(".,").lower() for t in full_name.split()]
    tokens = [t for t in tokens if t and t not in _NAME_SUFFIXES]
    return tokens[-1] if tokens else ""


def has_word(text: str, word: str) -> bool:
    """Whole-word, case-insensitive match, so "Li" doesn't match "listing". "-", "_" and
    "/" count as separators (URL slugs like /Jane-Example/)."""
    return bool(word) and re.search(rf"(?<![a-z0-9]){re.escape(word.lower())}(?![a-z0-9])", text.lower()) is not None


def mentions(candidate: Candidate, surname: str) -> bool:
    # Only the URL's path and query count: a surname can also appear in a domain name
    # (e.g. "People" in peoplefinders.com), which says nothing about the page.
    parts = urlsplit(candidate.url)
    return has_word(f"{parts.path} {parts.query} {candidate.title} {candidate.snippet}", surname)


def focus_text(text: str, surname: str) -> str:
    """The parts of a page within FOCUS_WINDOW chars of the surname, merged and joined with
    " … ", at most FOCUS_MAX_CHARS. Earlier mentions win (that's where the listing's header
    and main details usually are). A page that never names the surname is just cut short."""
    if len(text) <= FOCUS_MAX_CHARS:
        return text
    spans: list[list[int]] = []
    if surname:
        pattern = rf"(?<![a-z0-9]){re.escape(surname.lower())}(?![a-z0-9])"
        for match in re.finditer(pattern, text.lower()):
            start, end = max(0, match.start() - FOCUS_WINDOW), match.end() + FOCUS_WINDOW
            if spans and start <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], end)
            else:
                spans.append([start, end])
    if not spans:
        return text[:FOCUS_MAX_CHARS]
    parts: list[str] = []
    used = 0
    for start, end in spans:
        piece = text[start:end]
        room = FOCUS_MAX_CHARS - used
        if room <= 0:
            break
        parts.append(piece[:room])
        used += len(parts[-1])
    return " … ".join(parts)


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
    out: dict[str, Any],
    source_text: str,
    known_broker: bool,
    surname: str = "",
    allowed_fields: tuple[str, ...] = prompts.LISTING_FIELDS,
) -> list[FieldFinding] | None:
    """Validate the local LLM's answer. Returns the grounded fields if the page is this
    person, or None if it isn't (or the answer can't be trusted).

    Page text is untrusted and small models drift, so: booleans and confidence are
    checked, fields are limited to allowed_fields, and every quote must appear
    in the page text. known_broker means the site is in one of our lists (brokers or
    public profiles), so it doesn't also have to be a people-search listing.
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
        if field not in allowed_fields or field in seen or not isinstance(quote, str):
            continue
        quote = " ".join(quote.split())[:MAX_QUOTE_CHARS]
        if not quote or _squash(quote) not in haystack:
            continue  # not in the page: the model made it up
        if field == "address" and not any(ch.isdigit() for ch in quote):
            continue  # just a city or state (what we searched with), not a street address
        if field == "name" and surname and not has_word(quote, surname):
            return None  # the listing names someone else (e.g. "Jane Dosland" for "Jane Example")
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
        snippet=exa.snippet(result),
        via="exa",
        published_date=iso_date(result.get("publishedDate")),
    )


async def _discover(
    req: ScanRequest,
    brokers: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    errors: list[str],
) -> list[Candidate]:
    query = f'"{req.name}" {req.city} {req.state}'
    found: dict[str, Candidate] = {}

    def add(candidate: Candidate | None) -> None:
        if candidate is not None:
            found.setdefault(normalize_url(candidate.url), candidate)

    # Public-profile sites get their own search, so broker pages can't crowd them out of
    # one shared result list.
    tavily_res, profile_res, exa_res = await asyncio.gather(
        tavily.search(
            query,
            purpose="Look for your listings on known people-search sites",
            include_domains=[b["domain"] for b in brokers],
            max_results=20,
        ),
        tavily.search(
            query,
            purpose="Look for public profiles of you, such as sports results pages",
            include_domains=[p["domain"] for p in profiles],
            max_results=10,
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
    if isinstance(profile_res, Exception):
        errors.append(f"Tavily search for public profiles failed: {profile_res}")
    else:
        for result in profile_res.get("results", []):
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
        await _discover_similar(seed, query, brokers + profiles, add, errors)

    def rank(c: Candidate) -> int:  # known brokers first, then public profiles, then the rest
        site, kind = known_site(c.url, brokers, profiles)
        return 2 if site is None else 1 if kind == "public_profile" else 0

    candidates = [c for c in found.values() if mentions(c, surname)]
    candidates.sort(key=rank)
    return candidates[:MAX_CANDIDATES]


async def _discover_similar(
    seed: Candidate, query: str, brokers: list[dict[str, Any]], add, errors: list[str]
) -> None:
    """Find broker sites we don't list yet, then search them for this person. `brokers` is
    every site we already list (brokers and public profiles), so none of them count as new."""
    seed_broker = broker_for(seed.url, brokers)
    try:
        # Company-only query: the seed's domain, never its URL (which has the person's name).
        similar = await exa.search(
            f"people search sites like {seed_broker['domain']}",
            purpose=f"Discover people-search sites similar to {seed_broker['name']}",
            objective="Other people-search or background-check websites, not news or social media.",
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


def _fields_for(
    candidate: Candidate, brokers: list[dict[str, Any]], profiles: list[dict[str, Any]]
) -> tuple[str, ...]:
    _, kind = known_site(candidate.url, brokers, profiles)
    return prompts.PROFILE_FIELDS if kind == "public_profile" else prompts.LISTING_FIELDS


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
    profiles = load_json("public_profiles.json")
    warming = asyncio.create_task(ollama.warm_up())  # load the model during the searches
    try:
        candidates = await _discover(req, brokers, profiles, errors)
        texts = await _extract(candidates, errors) if candidates else {}
    finally:
        await warming
    if not candidates:
        return [], errors

    surname = last_name(req.name)
    jobs: list[tuple[Candidate, str, str]] = []
    for candidate in candidates:
        extracted = texts.get(normalize_url(candidate.url), "")
        if len(extracted) >= MIN_EXTRACT_CHARS and has_word(extracted, surname):
            jobs.append((candidate, focus_text(extracted, surname), "extract"))
        elif candidate.snippet.strip():
            jobs.append((candidate, candidate.snippet, "snippet"))

    answers = await asyncio.gather(
        *(
            ollama.ask_json(
                prompts.field_extraction_prompt(
                    req.name, req.city, req.state, text, fields=_fields_for(c, brokers, profiles)
                ),
                system=prompts.FIELD_EXTRACTION_SYSTEM,
                purpose=f"Check on this laptop whether the {host_of(c.url)} page is you, and what it shows",
                max_tokens=MAX_ANSWER_TOKENS,
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
        site, kind = known_site(candidate.url, brokers, profiles)
        fields = parse_analysis(
            answer,
            text,
            known_broker=site is not None,
            surname=surname,
            allowed_fields=_fields_for(candidate, brokers, profiles),
        )
        if fields is None:
            continue
        exposures.append(
            Exposure(
                id=exposure_id(candidate.url),
                broker=site["name"] if site else host_of(candidate.url),
                broker_id=site["id"] if site else None,
                source_kind=kind,
                url=candidate.url,
                title=candidate.title,
                found_via=candidate.via,
                text_source=text_source,
                fields=fields,
                published_date=candidate.published_date,
                opt_out_url=site.get("opt_out_url") if site else None,
            )
        )
    if unanswered:
        errors.append(
            f"The local LLM didn't answer for {unanswered} of {len(jobs)} pages, so they weren't checked."
        )
    return exposures, errors
