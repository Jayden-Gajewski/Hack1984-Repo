"""Stage 6: resolve. OWNER: Search & extract.

- Broker opt-out URL: the exposure's opt_out_url (from data/brokers.json), else a Tavily
  search restricted to the broker's domain for "opt out remove my information".
- Public profiles (data/public_profiles.json, e.g. sports results pages) get a removal
  request instead of an opt-out: remove or hide the profile, keep it out of search engines.
  Their removal page is searched for the same way, with "remove my profile privacy request".
- Company privacy contact: a Tavily search restricted to the company's domains. A
  privacy@-style email on one of those domains wins; else the privacy page URL.
- Drafts are fixed templates filled in locally, so they're deterministic for the demo, and
  they contain the name and city/state only, never more. Searches send the broker or
  company name only.
- Re-scan re-extracts each listing URL: "still_listed" if the page loads and still names
  the person, "removed" if it loads and doesn't, "unconfirmed" if it's blocked, thin or failed.
"""

import asyncio
import re
from typing import Any

from app.clients import tavily
from app.companies import all_companies
from app.data import load_json
from app.models import Draft, Exposure, RescanItem, ScanRequest
from app.stages.s1_exposures import MIN_EXTRACT_CHARS, has_word, host_of, last_name, normalize_url

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PRIVACY_MAILBOXES = ("privacy", "dataprotection", "data-protection", "dpo", "gdpr", "ccpa", "legal")
_OPT_OUT_HINT = re.compile(r"opt.?out|remov|suppress|delete|do.not.sell|privacy", re.I)


# ---------- templates (pure) ----------


def _who(person: ScanRequest) -> str:
    return f"{person.name}, {person.city}, {person.state}"


def _pages(exposure: Exposure) -> str:
    return "\n".join([exposure.url, *exposure.other_urls])


def broker_letter(exposure: Exposure, person: ScanRequest) -> tuple[str, str]:
    subject = "Please remove my personal information"
    where = "The listings are here" if exposure.other_urls else "The listing is here"
    body = (
        f"Hello {exposure.broker},\n\n"
        f"I'm asking you to remove my personal information from your website. {where}:\n"
        f"{_pages(exposure)}\n\n"
        "Please:\n"
        "1. Delete this listing and any other records you hold about me.\n"
        "2. Stop selling or sharing my personal information.\n"
        "3. Tell me where you got my information.\n\n"
        f"To identify me: {_who(person)}.\n\n"
        "Please confirm in writing when the listing has been removed, and keep it from being listed again.\n\n"
        f"Thank you,\n{person.name}"
    )
    return subject, body


def profile_letter(exposure: Exposure, person: ScanRequest) -> tuple[str, str]:
    subject = "Please remove or hide my public profile"
    body = (
        f"Hello {exposure.broker},\n\n"
        "I'm asking you to remove my public profile from your website, or hide it from public view. "
        f"{'The pages are here' if exposure.other_urls else 'The profile is here'}:\n{_pages(exposure)}\n\n"
        "Please:\n"
        "1. Remove the profile, or make it private, so my name isn't shown with my school, team or results.\n"
        "2. Keep the page out of search engines (for example with a noindex tag) and ask them to drop it.\n"
        "3. Tell me who supplied the information on it.\n\n"
        f"To identify me: {_who(person)}.\n\n"
        "Please confirm in writing when the profile has been removed or hidden.\n\n"
        f"Thank you,\n{person.name}"
    )
    return subject, body


def company_letter(company: str, person: ScanRequest) -> tuple[str, str]:
    subject = "Request about my personal information"
    body = (
        f"Hello {company} privacy team,\n\n"
        "I'm making a request about the personal information you hold about me. Please:\n"
        "1. Tell me which third parties you have sold or shared my personal information with.\n"
        "2. Stop selling or sharing my personal information (opt me out).\n"
        "3. Delete the personal information you hold about me.\n\n"
        f"To identify me: {_who(person)}. I can confirm the email address on my account in a reply.\n\n"
        "Where a privacy law such as the CCPA applies, please respond within the time it requires.\n\n"
        f"Thank you,\n{person.name}"
    )
    return subject, body


def pick_privacy_email(text: str, domains: list[str]) -> str | None:
    """A privacy@-style address on the company's own domains, else any address on them."""
    on_domain = []
    for email in dict.fromkeys(_EMAIL.findall(text)):
        host = email.rsplit("@", 1)[1].lower()
        if any(host == d or host.endswith("." + d) for d in domains):
            on_domain.append(email)
    preferred = [e for e in on_domain if e.split("@")[0].lower().startswith(_PRIVACY_MAILBOXES)]
    return (preferred or on_domain or [None])[0]


def removal_status(text: str, person: ScanRequest) -> str:
    """'still_listed', 'removed' or 'unconfirmed' for one re-extracted listing page."""
    if len(text) < MIN_EXTRACT_CHARS:
        return "unconfirmed"  # blocked, captcha or empty: can't tell
    # Whole words, so a short name like "Li" doesn't match "listing".
    first = person.name.split()[0]
    return "still_listed" if has_word(text, first) and has_word(text, last_name(person.name)) else "removed"


# ---------- searches ----------


async def _find_opt_out_url(exposure: Exposure, errors: list[str]) -> str | None:
    if exposure.opt_out_url:
        return exposure.opt_out_url
    profile = exposure.source_kind == "public_profile"
    sites = load_json("public_profiles.json" if profile else "brokers.json")
    known = next((b for b in sites if b["id"] == exposure.broker_id), None)
    if known and known.get("opt_out_url"):
        return known["opt_out_url"]
    page = "removal page" if profile else "opt-out page"
    ask = "remove my profile privacy request" if profile else "opt out remove my information"
    try:
        data = await tavily.search(
            f"{exposure.broker} {ask}",
            purpose=f"Find {exposure.broker}'s {page}",
            include_domains=[host_of(exposure.url)],
            max_results=5,
        )
    except Exception as exc:
        errors.append(f"Searching for {exposure.broker}'s {page} failed: {exc}")
        return None
    results = [r for r in data.get("results", []) if r.get("url")]
    hit = next((r["url"] for r in results if _OPT_OUT_HINT.search(f"{r['url']} {r.get('title', '')}")), None)
    if hit is None:
        errors.append(f"Couldn't find {exposure.broker}'s {page}; send this from the site's contact page instead.")
    return hit


async def _find_privacy_contact(company: dict[str, Any], errors: list[str]) -> tuple[str | None, str | None]:
    """Return (email, page URL) for the company's privacy requests."""
    try:
        data = await tavily.search(
            f"{company['name']} privacy request contact email",
            purpose=f"Find {company['name']}'s privacy contact",
            include_domains=company["domains"],
            max_results=5,
        )
    except Exception as exc:
        errors.append(f"Searching for {company['name']}'s privacy contact failed: {exc}")
        return None, company.get("privacy_url")
    results = [r for r in data.get("results", []) if r.get("url")]
    text = " ".join(f"{r.get('content') or ''} {r.get('raw_content') or ''}" for r in results)
    email = pick_privacy_email(text, company["domains"])
    page = company.get("privacy_url") or next(
        (r["url"] for r in results if "privacy" in f"{r['url']} {r.get('title', '')}".lower()), None
    )
    if not email and not page:
        errors.append(f"Couldn't find a privacy contact for {company['name']}.")
    return email, page


# ---------- the stage ----------


async def draft_broker_opt_out(exposure: Exposure, person: ScanRequest) -> Draft:
    """Ask the broker to delete the listing, stop selling or sharing it, and say where it got the data.
    For a public profile, ask the site to remove or hide it instead."""
    errors: list[str] = []
    url = await _find_opt_out_url(exposure, errors)
    if exposure.source_kind == "public_profile":
        subject, body = profile_letter(exposure, person)
    else:
        subject, body = broker_letter(exposure, person)
    return Draft(
        kind=exposure.source_kind, recipient=exposure.broker, send_to_url=url, subject=subject, body=body, errors=errors
    )


async def draft_company_request(company_id: str, person: ScanRequest) -> Draft:
    """Ask the company who it sold or shared the data with, to opt the person out, and to delete it."""
    company = next(c for c in all_companies() if c["id"] == company_id)
    errors: list[str] = []
    email, page = await _find_privacy_contact(company, errors)
    subject, body = company_letter(company["name"], person)
    return Draft(
        kind="company", recipient=company["name"], send_to_url=page, send_to_email=email,
        subject=subject, body=body, errors=errors,
    )


async def rescan(exposures: list[Exposure], person: ScanRequest) -> tuple[list[RescanItem], list[str]]:
    """Return (one RescanItem per exposure, errors)."""
    if not exposures:
        return [], []
    errors: list[str] = []
    # A merged card can cover several pages on one site; check them all.
    urls = list(dict.fromkeys(u for e in exposures for u in [e.url, *e.other_urls]))
    batches = [urls[i : i + 20] for i in range(0, len(urls), 20)]
    results = await asyncio.gather(
        *(
            tavily.extract(batch, purpose=f"Re-check whether {len(batch)} of your listing pages are still up")
            for batch in batches
        ),
        return_exceptions=True,
    )
    texts: dict[str, str] = {}
    for result in results:
        if isinstance(result, Exception):
            errors.append(f"Re-checking listings failed, so they're marked unconfirmed: {result}")
            continue
        for item in result.get("results", []):
            if item.get("url"):
                texts[normalize_url(item["url"])] = item.get("raw_content") or ""
    items = [
        RescanItem(
            exposure_id=e.id,
            url=e.url,
            status=combined_status(
                [removal_status(texts.get(normalize_url(u), ""), person) for u in [e.url, *e.other_urls]]
            ),
        )
        for e in exposures
    ]
    return items, errors


def combined_status(statuses: list[str]) -> str:
    """One status for a card's pages: still listed if any page still lists the person,
    removed only if every page is confirmed removed, otherwise unconfirmed."""
    if "still_listed" in statuses:
        return "still_listed"
    if statuses and all(s == "removed" for s in statuses):
        return "removed"
    return "unconfirmed"
