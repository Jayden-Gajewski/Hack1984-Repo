"""Incident facts: one breach at one company, from HIBP's breach list, a verified email's HIBP
match, or Stage 3's news and official-notice search. Pure functions over plain dicts (the
shape stored in backend/local/monitor.json).

Ids are stable, so a re-check never alerts twice:
- "hibp-<name>" for an HIBP breach,
- "news-<company id>-<year>" for a Stage 3 event (Stage 3 already merges per company and year).

A news incident that describes an HIBP breach (same company, compatible year) is folded into
it, and its id goes into `aliases`, so its state (first seen, steps done) carries over and no
second alert fires. A company announcement never says that a particular user was affected;
only a verified email's HIBP match does that (see severity.involvement).
"""

import hashlib
import html
import re
from datetime import date
from typing import Any
from urllib.parse import quote, urlsplit

from app.clients import hibp
from app.companies import registrable
from app.models import BreachEvent
from app.monitor import breach_data

HIBP_LABEL = "Have I Been Pwned"
SOURCE_LABEL = {"ag_notice": "State attorney general notice", "news": "News report", "web": "Web page"}
# Stage 3's data types as they read in a list of exposed data.
FIELD_LABEL = {
    "name": "Names", "email": "Email addresses", "phone": "Phone numbers", "address": "Physical addresses",
    "birthdate": "Dates of birth", "ssn": "Social security numbers", "password": "Passwords",
    "financial": "Financial information", "health": "Health information", "employer": "Employers",
}
MAX_DESCRIPTION = 1500
MAX_LINKS = 3

_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r"""<a\s[^>]*?href\s*=\s*["'](https?://[^"'\s]+)["']""", re.I)
_DATE_RE = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")


# ---------- small helpers ----------


def plain_text(markup: str | None) -> str:
    """HIBP descriptions contain HTML. The UI only ever renders text, so strip it here."""
    return " ".join(html.unescape(_TAG_RE.sub(" ", markup or "")).split())


def description_links(markup: str | None) -> list[str]:
    return list(dict.fromkeys(_HREF_RE.findall(markup or "")))[:MAX_LINKS]


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "breach"


def hibp_id(name: str) -> str:
    return f"hibp-{_slug(name)}"


def is_official_host(url: str, company_domains: list[str]) -> bool:
    """A government site, or the company's own site."""
    h = host(url)
    if not h:
        return False
    if h == "gov" or h.endswith(".gov") or ".gov." in h:
        return True
    try:
        return registrable(h) in {registrable(d) for d in company_domains}
    except Exception:
        return False


def _valid_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()[:10]
    if not _DATE_RE.match(value):
        return None
    year = int(value[:4])
    return value if 1990 <= year <= date.today().year else None


# ---------- matching HIBP breaches to a company ----------


def _name_matches(name: str, title: str) -> bool:
    """"AT&T" == "AT&T"; "Experian" matches "Experian (South Africa)". Prefixes only count for
    names of 4+ characters, so a short name can't match an unrelated breach."""
    n, t = name.strip().lower(), title.strip().lower()
    if not n or not t:
        return False
    if _squash(n) == _squash(t):
        return True
    if len(_squash(n)) < 4:
        return False
    return re.match(rf"{re.escape(n)}(?![a-z0-9.])", t) is not None


def matches_company(breach: dict[str, Any], company: dict[str, Any]) -> bool:
    """Does this HIBP breach belong to this company? A breach with a domain must be on one of
    the company's domains: "Discord.io" (discord.io) is not Discord (discord.com). A breach
    without one must carry the company's name."""
    domains = {registrable(d) for d in company.get("domains", []) if d}
    breach_domain = (breach.get("Domain") or "").strip().lower()
    if breach_domain:
        try:
            return registrable(breach_domain) in domains
        except Exception:
            return False
    return _name_matches(company["name"], str(breach.get("Title") or breach.get("Name") or ""))


# ---------- facts ----------


def hibp_facts(breach: dict[str, Any], company: dict[str, Any] | None, origin: str) -> dict[str, Any] | None:
    """Incident facts for one HIBP breach. None for a retired breach (HIBP removed it)."""
    name = breach.get("Name")
    if not isinstance(name, str) or not name or breach.get("IsRetired"):
        return None
    title = str(breach.get("Title") or name)
    page = f"{hibp.SITE_URL}/Breach/{quote(name)}"
    domains = list(company.get("domains", [])) if company else []
    if breach.get("Domain"):
        domains.append(str(breach["Domain"]))
    markup = breach.get("Description") if isinstance(breach.get("Description"), str) else ""

    sources = [{"url": page, "kind": "hibp", "label": HIBP_LABEL, "official": bool(breach.get("IsVerified"))}]
    disclosure = breach.get("DisclosureUrl")
    if isinstance(disclosure, str) and disclosure.startswith(("https://", "http://")):
        sources.append({"url": disclosure, "kind": "official", "label": "Disclosure notice", "official": True})
    for link in description_links(markup):
        official = is_official_host(link, domains)
        sources.append({
            "url": link,
            "kind": "official" if official else "web",
            "label": f"Linked from {HIBP_LABEL} ({host(link)})",
            "official": official,
        })

    dates = []
    breach_date = _valid_date(breach.get("BreachDate"))
    if breach_date:
        dates.append({"kind": "occurred", "date": breach_date, "source": f"{HIBP_LABEL} (breach date)", "source_url": page})
    added = _valid_date(breach.get("AddedDate"))
    if added:
        dates.append({"kind": "added_to_hibp", "date": added, "source": f"{HIBP_LABEL} (date added)", "source_url": page})

    classes = [c for c in breach.get("DataClasses") or [] if isinstance(c, str)]
    count = breach.get("PwnCount")
    return {
        "id": hibp_id(name),
        "aliases": [],
        "hibp_name": name,
        "company_id": company["id"] if company else None,
        "company": company["name"] if company else title,
        "title": title,
        "domain": breach.get("Domain") or None,
        "description": plain_text(markup)[:MAX_DESCRIPTION],
        "data_classes": classes,
        "categories": breach_data.categories_for_classes(classes),
        "pwn_count": count if isinstance(count, int) and count >= 0 else None,
        "dates": dates,
        "sources": sources,
        "reports": [],
        "hibp": {
            "verified": bool(breach.get("IsVerified")),
            "fabricated": bool(breach.get("IsFabricated")),
            "sensitive": bool(breach.get("IsSensitive")),
            "spam_list": bool(breach.get("IsSpamList")),
            "malware": bool(breach.get("IsMalware")),
            "stealer_log": bool(breach.get("IsStealerLog")),
        },
        "origin": [origin],
    }


def minimal_hibp_facts(name: str) -> dict[str, Any]:
    """Facts for a breach an email matched when HIBP's breach list couldn't be downloaded.
    Only the name is known; nothing else is filled in or guessed."""
    page = f"{hibp.SITE_URL}/Breach/{quote(name)}"
    return {
        "id": hibp_id(name), "aliases": [], "hibp_name": name, "company_id": None, "company": name,
        "title": name, "domain": None, "description": "", "data_classes": [], "categories": [],
        "pwn_count": None, "dates": [], "reports": [],
        "sources": [{"url": page, "kind": "hibp", "label": HIBP_LABEL, "official": False}],
        "hibp": {"verified": False, "fabricated": False, "sensitive": False, "spam_list": False,
                 "malware": False, "stealer_log": False},
        "origin": ["hibp_email"],
    }


def news_id(event: BreachEvent, company_id: str) -> str:
    if event.date:
        return f"news-{company_id}-{event.date[:4]}"
    return f"news-{company_id}-{hashlib.sha1(event.source_url.encode()).hexdigest()[:8]}"


def news_facts(event: BreachEvent, company: dict[str, Any]) -> dict[str, Any]:
    """Incident facts for one Stage 3 event (already merged per company and year)."""
    official = event.source_kind == "ag_notice" or is_official_host(event.source_url, company.get("domains", []))
    kind = "ag_notice" if event.source_kind == "ag_notice" else ("official" if official else event.source_kind)
    label = SOURCE_LABEL[event.source_kind] if not (official and event.source_kind != "ag_notice") else "Company notice"
    dates = []
    if event.date:
        dates.append({
            "kind": event.date_kind if event.date_kind in ("occurred", "disclosed") else "disclosed",
            "date": event.date,
            "source": label,
            "source_url": event.source_url,
        })
    return {
        "id": news_id(event, company["id"]),
        "aliases": [],
        "hibp_name": None,
        "company_id": company["id"],
        "company": company["name"],
        "title": f"{company['name']} breach" + (f" ({event.date[:4]})" if event.date else ""),
        "domain": (company.get("domains") or [None])[0],
        "description": event.summary,
        "data_classes": [FIELD_LABEL[t] for t in event.data_types if t in FIELD_LABEL],
        "categories": breach_data.categories_for_fields(list(event.data_types)),
        "pwn_count": None,
        "dates": dates,
        "sources": [{"url": event.source_url, "kind": kind, "label": label, "official": official}],
        "reports": [{"label": label, "url": event.source_url, "summary": event.summary}],
        "hibp": None,
        "origin": ["news"],
    }


# ---------- de-duplication ----------


def _year_of(facts: dict[str, Any], kind: str) -> int | None:
    return next((int(d["date"][:4]) for d in facts.get("dates", []) if d["kind"] == kind), None)


def distance(hibp: dict[str, Any], news: dict[str, Any]) -> int | None:
    """How far apart a news incident is from an HIBP breach, in years, or None if they can't
    be the same incident. An announcement can trail the breach by up to two years."""
    breach_year = _year_of(hibp, "occurred")
    if breach_year is None:
        return None
    occurred, disclosed = _year_of(news, "occurred"), _year_of(news, "disclosed")
    if occurred is not None:
        return 0 if occurred == breach_year else None
    if disclosed is not None and breach_year <= disclosed <= breach_year + 2:
        return disclosed - breach_year
    return None


def _union(items: list[Any], more: list[Any], key=lambda x: x) -> list[Any]:
    seen = {key(x) for x in items}
    out = list(items)
    for x in more:
        if key(x) not in seen:
            seen.add(key(x))
            out.append(x)
    return out


def absorb(target: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Fold `other` into `target` (same incident). Target keeps its id, title and description;
    sources, dates, reports and data types are combined."""
    merged = dict(target)
    merged["aliases"] = _union(target.get("aliases", []), [other["id"], *other.get("aliases", [])])
    merged["aliases"] = [a for a in merged["aliases"] if a != target["id"]]
    merged["sources"] = _union(target.get("sources", []), other.get("sources", []), key=lambda s: s["url"])
    merged["dates"] = _union(target.get("dates", []), other.get("dates", []), key=lambda d: (d["kind"], d["date"], d["source"]))
    merged["reports"] = _union(target.get("reports", []), other.get("reports", []), key=lambda r: r["url"])
    merged["data_classes"] = _union(target.get("data_classes", []), other.get("data_classes", []), key=str.lower)
    merged["categories"] = breach_data.sort_categories(target.get("categories", []) + other.get("categories", []))
    merged["origin"] = _union(target.get("origin", []), other.get("origin", []))
    if not merged.get("description"):
        merged["description"] = other.get("description", "")
    if merged.get("pwn_count") is None:
        merged["pwn_count"] = other.get("pwn_count")
    return merged


def merge_news(hibp_facts_list: list[dict[str, Any]], news: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """HIBP incidents with each news incident folded into the one it describes (same company,
    compatible year, closest first), followed by the news incidents HIBP doesn't have."""
    out = {f["id"]: dict(f) for f in hibp_facts_list}
    extra: list[dict[str, Any]] = []
    for item in news:
        candidates = [
            (dist, fid)
            for fid, f in out.items()
            if f.get("company_id") == item.get("company_id") and (dist := distance(f, item)) is not None
        ]
        if candidates:
            _, fid = min(candidates)
            out[fid] = absorb(out[fid], item)
        else:
            extra.append(item)
    return [*out.values(), *extra]
