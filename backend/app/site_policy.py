"""Privacy check for the site you're visiting: the backend of the browser extension (extension/).

The extension sends the site's origin ("https://www.example.com", never the full page URL), the
privacy-policy links it found on the page, and any "Do Not Sell or Share" link. Then:

1. Read the policy straight from the site you're visiting (clients/website.py): one logged GET
   per hop and no search API. Only that site is contacted: a policy link to another site, or a
   redirect to one, isn't followed automatically. The user can open such a policy and choose
   "Check this page". With no link, try FALLBACK_PATHS on the site. If the site blocks that or
   needs JavaScript, the extension can send the text of the policy page open in the browser
   (`page_text`), and then nothing leaves this laptop at all.
2. Quick pass, instant and without the LLM: what the policy says the company collects
   (CATEGORIES, each backed by a verbatim line), Stage 4's strict sale/sharing pattern, any "we
   do not sell" statement, and risks built from those by fixed rules (risks_for).
3. Deep pass (`deep: true`, sent when the popup opens): read the site's ads.txt (one more GET to
   the same site, same rules) and run Stage 4's Gemini pass over the same sentences. It runs in
   the background because the LLM can take a minute on a CPU. The response says "running" in
   `llm` and `ad_sellers.status`, and the extension asks again until both are done.
4. What the page itself does (page_risks), from what the extension saw in the browser: trackers it
   loaded (hostnames only, matched against data/trackers.json), the kinds of personal data its
   form fields ask for (fixed words, never what's typed), whether the site is a people-search site
   (data/brokers.json), and, when no policy was found, that it collects data without one. None of
   this sends anything anywhere.

The automatic check on each visit (`read_policy: false`) contacts no site at all: it reuses a result
the user already asked for, or judges only what the browser saw. Reading a policy is a request from
this computer's own connection, so it happens when the user opens the popup.

Results stay in memory, per hostname, for CACHE_SECONDS. Of a policy's text only its sale and sharing
sentences are kept, and only until the LLM pass. The page's trackers and form fields aren't kept at
all: they're judged on each request. The sites you visit are browsing history, so nothing here is
written to disk or Postgres, or named in the console log.
"""

import asyncio
import hashlib
import logging
import re
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import urljoin, urlsplit

from app import prompts
from app.clients import gemini, website
from app.companies import registrable as _list_registrable
from app.data import load_json
from app.models import (
    AdSellers,
    BrokerMatch,
    DataCollected,
    PolicyClause,
    SitePolicyRequest,
    SitePolicyResponse,
    SiteRisk,
    TrackerFound,
)
from app.stages import s4_policy as s4

log = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
MAX_SITES = 200
MAX_LINKS = 3
MIN_POLICY_CHARS = 1_500
FALLBACK_PATHS = ("/privacy-policy", "/privacy")
SECTION_LINES = 80  # lines under a "what we collect" heading or lead-in that count as collected
MANY_KINDS = 8

# (category, label, sensitive, pattern): what a policy can say the company collects. The ids
# are models.DataCategory. "Sensitive" follows the kinds of data privacy laws protect most.
CATEGORIES = tuple(
    (cat, label, sensitive, re.compile(pattern, re.I))
    for cat, label, sensitive, pattern in (
        ("contact", "Contact details", False,
         r"e-?mail address|phone number|telephone number|mobile number|mailing address|postal address|"
         r"home address|contact (details|information)"),
        ("identifiers", "Device and online identifiers", False,
         r"\bIP address|device (ID|identifier|information|data)|advertising (ID|identifier)|unique identifier|"
         r"cookie (ID|identifier)|\bIDFA\b|\bMAC address|browser type"),
        ("tracking", "Cookies and tracking pixels", False,
         r"\bcookies\b|web beacons?|tracking (pixels?|technolog)|\bpixels?\b|clear GIFs|\bSDKs?\b"),
        ("precise_location", "Precise location", True, r"precise (geo-?)?location|\bGPS\b"),
        ("location", "Location", False,
         r"(?<!precise )(geo-?location|location (data|information))|your location|approximate location"),
        ("activity", "Browsing and app activity", False,
         r"browsing (history|activity|behavio)|search (history|queries|terms)|pages? (you )?(visit|view)|"
         r"clickstream|usage (data|information)|interactions? with (our|the|these) (services?|sites?|websites?|apps?)"),
        ("purchases", "Purchase history", False,
         r"purchase (history|records|information)|transaction (history|information|details)|products? (you )?(buy|bought|purchase)"),
        ("financial", "Payment and financial details", False,
         r"payment (card|information|details|method)|credit (card|history|score|report)|debit card|"
         r"bank account|financial information|card number"),
        ("government_id", "Government ID numbers", True,
         r"social security|\bSSN\b|driver['’]?s licen[cs]e|passport|government[- ]issued|"
         r"national (ID|identification)|tax (ID|identification)"),
        ("health", "Health information", True,
         r"health (information|data|conditions?|records?|status)|medical|heart rate|prescriptions?|disabilit"),
        ("biometric", "Biometric data", True,
         r"biometric|face ?prints?|facial (recognition|geometry|scan)|fingerprints?|voice ?prints?|retina|iris scan"),
        ("sensitive_traits", "Race, religion, sexuality or similar", True,
         r"racial|ethnic origin|religio|sexual orientation|sex life|political (opinion|affiliation)|"
         r"union membership|immigration status|citizenship"),
        ("contacts", "Your contacts", False, r"address book|contact lists?|your contacts|phone contacts"),
        ("media", "Photos, audio and video", False,
         r"\b(your|profile) (photos?|pictures?|images?|videos?)|\bphotos?(,| and| or) videos?|photographs|"
         r"audio recordings?|voice (recordings?|data|commands?|input)|microphone|\bcamera\b"),
        ("demographics", "Age, gender and demographics", False, r"date of birth|birth ?date|\bage\b|gender|demographic"),
        ("inferences", "Inferences and profiles about you", False,
         r"inferences?|profiles? (about|of) you|predictions? about you|preferences and characteristics"),
        ("from_others", "Data from other companies", False,
         r"\bfrom (other )?(third[- ]part(y|ies)|data brokers?|other (companies|businesses|sources)|"
         r"(our )?(business |marketing |advertising )?partners|public(ly available)? (sources|records|databases)|"
         r"social (media|networks?))"),
    )
)
# "We use your IP address" counts too: a company can only use what it holds.
_COLLECT = re.compile(
    r"\b(collect(s|ed|ing)?|gather(s|ed|ing)?|obtain(s|ed|ing)?|receiv(e|es|ed|ing)|record(s|ed|ing)?|"
    r"stor(e|es|ed|ing)|process(es|ed|ing)?|captur(e|es|ed|ing)|track(s|ed|ing)?|log(s|ged|ging)?|"
    r"us(e|es|ed|ing))\b(?!\s+in(to)?\b)",
    re.I,
)
_NOT_COLLECTED = re.compile(
    r"\b(do|does|will|shall|did) not (knowingly |intentionally )?"
    r"(collect|gather|obtain|receive|store|process|record|track|capture|use)|"
    r"\bdon['’]?t (collect|store|track|use)|\bnever (collect|gather|store|track|record|use)|"
    r"\bnot (collected|stored|tracked|used)\b",
    re.I,
)
# A heading that starts a "what we collect" section: "Information we collect", "Data Collection",
# "Data We Receive From Partners". A lead-in ("We may collect the following:") needs a collection
# verb in the company's voice instead.
_SECTION_START = re.compile(r"^(?=.*\b(collect|gather|obtain|receiv)).*\b(information|data|we|you)\b", re.I)
# Instructions for avoiding collection ("Follow these steps to prevent data collection:") aren't
# a list of what's collected.
_CONTROL = re.compile(r"\b(prevent|opt[- ]?out|turn off|disable|block)\b", re.I)
# A heading that starts a section about something else. Only these end a collection section:
# short bullets ("Device information") look like headings too, so a looser rule cut lists short.
_SECTION_END = re.compile(
    r"^(\d+[.)]?\s*)?(how (we|do we|does|is|are|long)|why we|who we|with whom|when we|"
    r"your (rights|choices|options|privacy (rights|choices))|children|cookies$|cookie policy|security$|"
    r"data (retention|security)|retention|contact us|contacting us|how to contact|changes to|international|"
    r"sharing|disclosure|uses? of (your |personal |the )?(information|data)|sale of|do not sell|"
    r"(categories of )?(personal )?(information|data) we (share|disclose|sell)|third[- ]party (links|sites|services))",
    re.I,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")
_NO_SALE = re.compile(
    r"\b(do|does|will|shall) not (sell|rent)|\bdon['’]?t (sell|rent)|\bnever (sell|rent)|\b(have|has) not sold\b", re.I
)
_ABOUT_DATA = re.compile(r"personal|\bdata\b|information", re.I)
# Disclosure the law requires ("to comply with a request from courts ... or other authorized third
# parties") isn't selling or sharing (the Stage 4 spec), unless the sentence also names marketers.
_LEGAL = re.compile(
    r"\b(comply|complying|compliance) with|required by law|legal (obligations?|process|requirements?|requests?|proceedings?)|"
    r"law enforcement|court orders?|subpoenas?|\bcourts?\b|government (agencies|authorities|requests?)|"
    r"public authorities|regulators?|litigation",
    re.I,
)
_MARKETERS = re.compile(r"advertis|marketing|broker|partner", re.I)
_BROKER = re.compile(r"broker", re.I)
_POLICY_WORDS = re.compile(r"privacy|personal (information|data)", re.I)
_POLICY_SENTENCE = re.compile(r"\b(collect|share[sd]?|sharing|disclos|sell|third[- ]part)", re.I)
MIN_POLICY_SENTENCES = 3
_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
SELLS_OR_SHARES = ("sale", "data_broker", "sharing", "advertising")


# ---------- pure helpers (unit-tested) ----------

# Generic second-level labels under a country code (gov.au, com.cn, co.il): the domain a site owns
# is one label longer. companies.registrable() knows only a short list of these, and a domain
# guessed too short would send requests to, and credit results from, someone else's site.
_GENERIC_SLD = re.compile(r"^(ac|co|com|edu|go|gob|gouv|gov|govt|k12|ltd|mil|ne|net|nic|nhs|or|org|plc|sch)\.[a-z]{2}$")


def registrable(host: str) -> str:
    """The domain a site owns: www.ato.gov.au -> ato.gov.au, shop.example.com -> example.com."""
    domain = _list_registrable(host)
    labels = host.lower().strip(".").removeprefix("www.").split(".")
    if _GENERIC_SLD.match(domain) and len(labels) > 2:
        return ".".join(labels[-3:])
    return domain


def _voice(company: str) -> re.Pattern[str]:
    return re.compile(r"\b(we|us|our)\b" + (rf"|{re.escape(company)}" if company else ""), re.I)


def _sentences(line: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(line) if s.strip()]


def collected_data(text: str, company: str = "") -> list[DataCollected]:
    """What the policy says the company collects, one entry per category with the first line that
    shows it. A line counts if it's a sentence in the company's own voice with a collection verb
    ("we collect your IP address"), or if it sits under a heading or lead-in about collection
    ("Information We Collect", "We collect the following:"), like a bullet saying "Precise
    location". Denials ("we do not collect biometric data") never count."""
    voice = _voice(company)
    found: dict[str, DataCollected] = {}
    section, left = "", 0
    for raw in text.splitlines():
        line = " ".join(raw.split()).lstrip("-*•#>+ ").strip()
        if not line:
            continue
        # Headings sit on their own line: short, with no closing punctuation (or Title Case).
        heading = (len(line.split()) <= 10 and not line.endswith((".", "!", "?", ";", ","))) or (
            len(line) <= 120 and s4.is_heading(line)
        )
        lead_in = len(line) <= 200 and line.endswith(":")
        if heading or lead_in:
            if _NOT_COLLECTED.search(line) or _CONTROL.search(line):
                section, left = "", 0
            elif (heading and _SECTION_START.search(line)) or (lead_in and _COLLECT.search(line) and voice.search(line)):
                section, left = line.rstrip(":"), SECTION_LINES
            elif heading and _SECTION_END.search(line):
                section, left = "", 0
        if left > 0:
            candidates = _sentences(line)
        else:
            candidates = [s for s in _sentences(line) if _COLLECT.search(s) and voice.search(s)]
        for sentence in candidates:
            if len(sentence) > s4.MAX_QUOTE_CHARS or _NOT_COLLECTED.search(sentence):
                continue
            for cat, label, sensitive, pattern in CATEGORIES:
                if cat not in found and pattern.search(sentence):
                    found[cat] = DataCollected(
                        category=cat, label=label, sensitive=sensitive, quote=sentence,
                        section=section if left > 0 and sentence.rstrip(":") != section else "",
                    )
        left = max(0, left - 1)
    return [found[cat] for cat, *_ in CATEGORIES if cat in found]


def not_legal_only(clauses: list[PolicyClause]) -> list[PolicyClause]:
    """Drop clauses about disclosure the law requires (courts, law enforcement, regulators)."""
    return [c for c in clauses if not (_LEGAL.search(c.quote) and not _MARKETERS.search(c.quote))]


def no_sale_quote(sentences: list[str], company: str = "") -> str | None:
    """The policy's own "we do not sell your personal information", if it says so."""
    voice = _voice(company)
    return next(
        (s for s in sentences if _NO_SALE.search(s) and _ABOUT_DATA.search(s) and voice.search(s)), None
    )


def risks_for(
    collected: list[DataCollected], clauses: list[PolicyClause], opt_out_url: str | None
) -> list[SiteRisk]:
    """Fixed rules from the evidence to a list of risks, strongest first. Each one cites its quote."""
    first = {}
    for clause in clauses:
        first.setdefault(clause.category, clause)
    by_cat = {c.category: c for c in collected}
    shares = any(cat in first for cat in SELLS_OR_SHARES)
    risks: list[SiteRisk] = []

    if "sale" in first:
        risks.append(SiteRisk(
            level="high", title="It may sell your personal information",
            detail="The policy says it sells personal information, or shares it in a way the law treats as a sale.",
            quote=first["sale"].quote,
        ))
    if "data_broker" in first:
        risks.append(SiteRisk(
            level="high", title="It shares data with data brokers",
            detail="Data brokers resell personal information, including to people-search sites.",
            quote=first["data_broker"].quote,
        ))
    sensitive = [c for c in collected if c.sensitive]
    if sensitive:
        kinds = ", ".join(c.label[0].lower() + c.label[1:] for c in sensitive)
        risks.append(SiteRisk(
            level="high" if shares else "medium", title="It collects sensitive data",
            detail=f"The policy mentions {kinds}."
            + (" It also sells or shares data, so this could reach other companies." if shares else ""),
            quote=sensitive[0].quote,
        ))
    if "sharing" in first:
        risks.append(SiteRisk(
            level="medium", title="It shares your data with other companies",
            detail="The policy says other companies get your data for their own purposes, not just to run the service.",
            quote=first["sharing"].quote,
        ))
    if "advertising" in first:
        risks.append(SiteRisk(
            level="medium", title="It uses your data for targeted ads",
            detail="Ad partners can use what you do here to follow you across other sites and apps.",
            quote=first["advertising"].quote,
        ))
    if "from_others" in by_cat:
        quote = by_cat["from_others"].quote
        risks.append(SiteRisk(
            level="high" if _BROKER.search(quote) else "medium",
            title="It gets data about you from other companies",
            detail="It adds information from outside sources, such as partners or data brokers, to what you give it.",
            quote=quote,
        ))
    if opt_out_url:
        risks.append(SiteRisk(
            level="medium", title="It shows a “Do Not Sell or Share” link",
            detail="California requires that link from businesses that sell personal information or share it "
            "for targeted ads. You can use it to opt out.",
        ))
    if "affiliates" in first:
        risks.append(SiteRisk(
            level="low", title="It shares data within its corporate family",
            detail="Other companies it owns, or that own it, can use your information.",
            quote=first["affiliates"].quote,
        ))
    if len(collected) >= MANY_KINDS:
        risks.append(SiteRisk(
            level="low", title=f"It collects many kinds of data ({len(collected)})",
            detail="The more it holds, the more there is to sell, share or expose in a breach.",
        ))
    return sorted(risks, key=lambda r: _RISK_ORDER[r.level])


def summary_line(status: str, risks: list[SiteRisk], collected: list[DataCollected]) -> str:
    main = next((r for r in risks if r.title != NO_POLICY_TITLE), None)
    main_risk = f" Main risk: {main.title[0].lower()}{main.title[1:]}." if main else ""
    if status == "no_policy":
        return f"Couldn't find this site's privacy policy.{main_risk}"
    if status == "not_read":
        return f"Open Dossier to read this site's privacy policy.{main_risk}"
    if status == "unreadable":
        return f"Found the privacy policy but couldn't read it.{main_risk}"
    kinds = f" It says it collects {len(collected)} kinds of data." if collected else ""
    if risks:
        return f"Main risk: {risks[0].title[0].lower()}{risks[0].title[1:]}.{kinds}"
    return f"Found nothing in the policy about selling or sharing your data.{kinds}"


def looks_like_policy(text: str) -> bool:
    """Long enough, about personal data, and with a few sentences on collecting or sharing it. A
    home page or a "not found" page that only links to the policy has none of those sentences."""
    if len(text) < MIN_POLICY_CHARS or not _POLICY_WORDS.search(text):
        return False
    sentences = (s for line in text.splitlines() for s in _sentences(line))
    return sum(1 for s in sentences if _POLICY_SENTENCE.search(s) and _ABOUT_DATA.search(s)) >= MIN_POLICY_SENTENCES


def _link(url: str | None) -> str | None:
    """A link from the page, for display only: plain http(s) or nothing."""
    try:
        return url if url and urlsplit(url).scheme in ("http", "https") and urlsplit(url).hostname else None
    except ValueError:
        return None


# ---------- what the page itself does (seen in the browser; nothing is sent anywhere) ----------

TRACKER_ORDER = {
    c: i for i, c in enumerate(("session_recording", "data_broker", "advertising", "social", "analytics", "tag_manager"))
}
FIELD_LABEL = {
    "email": "email address",
    "phone": "phone number",
    "address": "street address",
    "birthdate": "date of birth",
    "password": "password",
    "card": "card number",
    "bank_account": "bank account number",
    "ssn": "Social Security number",
    "government_id": "government ID number",
}
SENSITIVE_FIELDS = ("password", "card", "bank_account", "ssn", "government_id")
VERY_SENSITIVE_FIELDS = ("bank_account", "ssn", "government_id")
# Personal information that California's online privacy law (CalOPPA) covers.
CALOPPA_FIELDS = ("email", "phone", "address", "birthdate", "card", "bank_account", "ssn", "government_id")
NO_POLICY_TITLE = "Couldn't find a privacy policy"
MAX_ADS_LINES = 20_000
# An ads.txt record: "adsystem.com, account id, DIRECT|RESELLER[, certification id]".
_ADS_RECORD = re.compile(r"^\s*([a-z0-9][a-z0-9.-]*\.[a-z]{2,})\s*,\s*[^,\s][^,]*,\s*(direct|reseller)\b", re.I)


@lru_cache
def _tracker_data() -> dict[str, Any]:
    return load_json("trackers.json")


def match_trackers(hosts: list[str], domain: str) -> list[TrackerFound]:
    """Known trackers among the hostnames a page loaded, strongest category first. A company's own
    sites don't count: facebook.net resources on facebook.com, or Google's on youtube.com."""
    owners = _tracker_data()["owners"]
    found: dict[str, TrackerFound] = {}
    for host in hosts:
        for tracker in _tracker_data()["trackers"]:
            if any(host == d or host.endswith("." + d) for d in tracker["domains"]):
                if registrable(host) == domain or domain in owners.get(tracker["company"], []):
                    break  # the site's own host, or one of the tracker company's own sites
                hit = found.setdefault(
                    tracker["id"],
                    TrackerFound(name=tracker["name"], company=tracker["company"], category=tracker["category"], hosts=[]),
                )
                if host not in hit.hosts and len(hit.hosts) < 5:
                    hit.hosts.append(host)
                break
    return sorted(found.values(), key=lambda t: TRACKER_ORDER[t.category])


def broker_for(domain: str) -> BrokerMatch | None:
    """The people-search site in data/brokers.json that this domain belongs to, if any."""
    for broker in load_json("brokers.json"):
        if domain == broker["domain"] or domain.endswith("." + broker["domain"]):
            return BrokerMatch(name=broker["name"], opt_out_url=broker["opt_out_url"])
    return None


def ad_sellers(text: str) -> tuple[int, list[str]]:
    """(how many ad companies an ads.txt lets sell the site's ads, the ones it lists most). Only
    well-formed records count, and the file is only ever parsed, never followed."""
    names = _tracker_data()["ad_systems"]
    systems: Counter[str] = Counter()
    for line in text.splitlines()[:MAX_ADS_LINES]:
        match = _ADS_RECORD.match(line.split("#", 1)[0])
        if match:
            systems[match.group(1).lower().removeprefix("www.")] += 1
    companies: Counter[str] = Counter()
    for system, records in systems.items():  # once per ad system, not per line
        companies[names.get(system) or names.get(registrable(system)) or system] += records
    return len(companies), [name for name, _ in companies.most_common(5)]


def _names(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def page_risks(
    status: str,
    trackers: list[TrackerFound],
    asks_for: list[str],
    insecure: list[str],
    broker: BrokerMatch | None,
    ads: AdSellers | None,
) -> list[SiteRisk]:
    """Fixed rules from what the page does to risks. Each risk names what was seen as evidence."""
    by_cat: dict[str, list[TrackerFound]] = {}
    for tracker in trackers:
        by_cat.setdefault(tracker.category, []).append(tracker)

    def seen(category: str) -> list[str]:
        return [host for t in by_cat[category] for host in t.hosts]

    def named(category: str) -> str:
        return _names([t.name for t in by_cat[category]])

    fields = lambda kinds: [f"{FIELD_LABEL[k]} field" for k in kinds]  # noqa: E731
    very = [f for f in asks_for if f in VERY_SENSITIVE_FIELDS]
    risks: list[SiteRisk] = []

    if broker:
        risks.append(SiteRisk(
            level="high", title="It publishes profiles of people",
            detail=f"{broker.name} is a people-search site. Sites like this publish profiles of people, often with "
            "home addresses, phone numbers and relatives. Check whether it lists you.",
            evidence=["On Dossier's list of people-search sites"],
        ))
    if insecure:
        risks.append(SiteRisk(
            level="high" if any(f in SENSITIVE_FIELDS for f in insecure) else "medium",
            title=f"It asks for your {_names([FIELD_LABEL[f] for f in insecure])} without encryption",
            detail="This page or its form doesn't use https, so what you type here can be read by others on "
            "your network or Wi-Fi.",
            evidence=fields(insecure),
        ))
    if "session_recording" in by_cat:
        risks.append(SiteRisk(
            level="high", title="It loads a session-recording tool",
            detail=f"{named('session_recording')} can record clicks, scrolling and typing on this page, depending "
            "on how the site set it up.",
            evidence=seen("session_recording"),
        ))
    if "data_broker" in by_cat:
        risks.append(SiteRisk(
            level="high", title="It shares your visit with data brokers",
            detail=f"{named('data_broker')} link visits to profiles that other companies buy.",
            evidence=seen("data_broker"),
        ))
    if "advertising" in by_cat:
        risks.append(SiteRisk(
            level="medium", title="It sends your visit to ad companies",
            detail=f"{named('advertising')} can add this visit to an ad profile and follow you across sites.",
            evidence=seen("advertising"),
        ))
    if very and status == "ok":
        risks.append(SiteRisk(
            level="medium", title=f"It asks for your {_names([FIELD_LABEL[f] for f in very])}",
            detail="Only give it if you know why this site needs it.",
            evidence=fields(very),
        ))
    if status == "no_policy":
        tracked = [t for t in trackers if t.category != "tag_manager"]
        what = []
        if asks_for:
            what.append(f"asks for your {_names([FIELD_LABEL[f] for f in asks_for])}")
        if tracked:
            what.append(f"sends your visit to {_names([t.company for t in tracked])}")
        if what:
            law = (
                " California requires commercial websites that collect personal information like this from "
                "Californians to post one."
                if any(f in CALOPPA_FIELDS for f in asks_for)
                else ""
            )
            risks.append(SiteRisk(
                level="high" if very or "card" in asks_for else "medium", title=NO_POLICY_TITLE,
                detail=f"This page {' and '.join(what)}, but no privacy policy was found saying how that's used.{law}",
                evidence=fields(asks_for) + [host for t in tracked for host in t.hosts],
            ))
    if ads and ads.status == "done" and ads.count:
        companies = f"{ads.count} ad compan{'y' if ads.count == 1 else 'ies'}"
        risks.append(SiteRisk(
            level="medium",
            title=f"{companies[0].upper()}{companies[1:]} {'is' if ads.count == 1 else 'are'} allowed to sell its ad space",
            detail=f"Its ads.txt file names {companies} that may sell its ads, such as {_names(ads.companies[:3])}. "
            "Ad auctions can pass details about your device, rough location and this visit to many of them.",
            evidence=[ads.url] if ads.url else [],
        ))
    if "social" in by_cat:
        risks.append(SiteRisk(
            level="low", title="Social networks can see this visit",
            detail=f"{named('social')} learn you were here, even if you don't click anything.",
            evidence=seen("social"),
        ))
    return risks


# ---------- the check ----------


@dataclass
class _Site:
    site: str  # the hostname without "www.": the cache key, so sites on a shared host never mix
    domain: str  # the registrable domain: policy links and redirects must stay on it
    company: str  # how the policy may name the company, for Stage 4's "company's voice" check
    status: str
    policy_url: str | None
    read_from: str | None
    sentences: list[str]  # the policy's sale and sharing sentences, kept for the LLM pass, then dropped
    text_hash: str | None  # set when the text came from the browser
    links: tuple[str, ...]  # the page's policy links this result considered
    collected: list[DataCollected]
    clauses: list[PolicyClause]
    no_sale_quote: str | None
    errors: list[str]
    checked_at: str
    created: float = field(default_factory=time.monotonic)
    llm: str = "off"
    ads: AdSellers | None = None  # read from the site's ads.txt when the popup opens
    deep_started: bool = False
    task: asyncio.Task | None = None


_cache: OrderedDict[str, _Site] = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}


def reset() -> None:
    """Forget every result (tests use this)."""
    for entry in _cache.values():
        if entry.task and not entry.task.done():
            entry.task.cancel()
    _cache.clear()
    _locks.clear()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _host(url: str | None) -> str:
    try:
        return (urlsplit(url).hostname or "") if url else ""
    except ValueError:
        return ""


def _page_links(req: SitePolicyRequest) -> list[str]:
    return list(dict.fromkeys(u for u in (website.public_https(u) for u in req.policy_urls) if u))[:MAX_LINKS]


def _cached(site: str, req: SitePolicyRequest) -> _Site | None:
    entry = _cache.get(site)
    if entry is None or req.refresh or time.monotonic() - entry.created > CACHE_SECONDS:
        return None
    if req.page_text is not None:
        return entry if entry.text_hash == _hash(req.page_text) else None
    if entry.status != "ok" and any(u not in entry.links for u in _page_links(req)):
        return None  # this page has a policy link the last attempt didn't consider
    return entry


async def _fetch_policy(
    site: str, domain: str, req: SitePolicyRequest, errors: list[str]
) -> tuple[str, str | None, tuple[str, ...]]:
    """(policy text, its URL, the links considered). Text is "" when nothing readable was found.
    Only pages on the visited site are fetched: a link or redirect to another site would tell
    that site where you are, and it would be that site's policy anyway."""
    links = _page_links(req)
    on_site = lambda host: registrable(host) == domain  # noqa: E731
    own = [u for u in links if on_site(_host(u))]
    other = [u for u in links if u not in own]
    origin = website.public_https(req.origin)
    guesses = [urljoin(origin, path) for path in FALLBACK_PATHS] if origin and not own else []
    for url in own or guesses:
        purpose = (
            f"Browser extension: read {site}'s privacy policy, straight from {site}"
            if own
            else f"Browser extension: look for {site}'s privacy policy at {urlsplit(url).path}"
        )
        try:
            final_url, text = await website.read_page(url, purpose=purpose, stay_within=on_site)
        except website.PageError as exc:
            if own:
                errors.append(str(exc))
            continue
        if urlsplit(final_url).path in ("", "/"):
            if own:
                errors.append(f"{url} led to the home page, not a privacy policy.")
            continue
        if looks_like_policy(text):
            return text, final_url, tuple(links)
        if own:
            errors.append(f"{final_url} didn't look like a privacy policy (it may need JavaScript to show).")
    if other:
        errors.append(
            f"The policy link goes to another site ({_host(other[0])}), so it wasn't opened automatically. "
            "Open it and choose “Check this page”."
        )
    return "", (own or other or [None])[0], tuple(links)


async def _read_and_check(site: str, domain: str, req: SitePolicyRequest) -> _Site:
    errors: list[str] = []
    company = domain.split(".")[0]
    if req.page_text is not None:
        text = req.page_text if looks_like_policy(req.page_text) else ""
        policy_url = _link(req.policy_urls[0])  # check_site made sure it's this site's page
        read_from, links, text_hash = "browser", (), _hash(req.page_text)
        if not text:
            errors.append("This page doesn't look like a privacy policy.")
    else:
        text, policy_url, links = await _fetch_policy(site, domain, req, errors)
        read_from, text_hash = "site", None

    found = dict(site=site, domain=domain, company=company, policy_url=policy_url, text_hash=text_hash, links=links)
    if not text:
        status = "unreadable" if links or req.page_text is not None else "no_policy"
        if status == "no_policy":
            errors.append("No privacy-policy link was found on this page, and the site has none at /privacy-policy or /privacy.")
        return _not_read(**found, status=status, errors=errors)

    # Off the event loop: a long or hostile page mustn't stall every other request while it's read.
    sentences, collected, clauses, no_sale = await asyncio.to_thread(_analyze, text, company)
    return _Site(
        **found, status="ok", read_from=read_from, sentences=sentences, collected=collected, clauses=clauses,
        no_sale_quote=no_sale, errors=errors, checked_at=datetime.now(timezone.utc).isoformat(),
    )


def _analyze(text: str, company: str) -> tuple[list[str], list[DataCollected], list[PolicyClause], str | None]:
    """The quick pass over a policy's text. Only its sale and sharing sentences are kept afterwards."""
    sentences = s4.candidate_sentences(text)
    clauses = s4.merge_clauses(not_legal_only(s4.pattern_clauses(sentences, company)))
    return sentences, collected_data(text, company), clauses, no_sale_quote(sentences, company)


def _not_read(**found: Any) -> _Site:
    """A result with no policy in it: not found, unreadable, or not read yet."""
    defaults = dict(
        policy_url=None, read_from=None, sentences=[], text_hash=None, links=(), collected=[], clauses=[],
        no_sale_quote=None, errors=[], checked_at=datetime.now(timezone.utc).isoformat(),
    )
    return _Site(**{**defaults, **found})


async def _deep_pass(entry: _Site, read_ads: bool) -> None:
    """Started when the popup opens: the site's ads.txt (unless it was already read), then the
    Gemini pass."""
    if read_ads:
        await _ads_pass(entry)
    if entry.status == "ok":
        await _llm_pass(entry)


async def _ads_pass(entry: _Site) -> None:
    """Read https://<site's domain>/ads.txt, the public list of companies allowed to sell its ads:
    one GET to the site being visited, with the same rules as the policy fetch (logged, no cookies,
    capped, redirects can't leave the site)."""
    try:
        final_url, text = await website.read_page(
            f"https://{entry.domain}/ads.txt",
            purpose=f"Browser extension: read {entry.domain}'s ads.txt (who may sell its ads), straight from {entry.domain}",
            stay_within=lambda host: registrable(host) == entry.domain,
        )
    except website.PageError as exc:
        entry.ads = AdSellers(status="none" if exc.status in (404, 410) else "failed")
        return
    except Exception:
        log.exception("An ads.txt check failed")  # no site name, as below
        entry.ads = AdSellers(status="failed")
        return
    count, companies = ad_sellers(text)
    entry.ads = AdSellers(status="done" if count else "none", url=final_url, count=count, companies=companies)


async def _llm_pass(entry: _Site) -> None:
    """Stage 4's Gemini pass over the policy's sale and sharing sentences. The model only picks
    sentence numbers and every pick passes Stage 4's checks, so quotes stay verbatim."""
    try:
        groups = s4.batches(entry.sentences)
        answers = await asyncio.gather(
            *(
                gemini.ask_json(
                    prompts.policy_prompt(entry.site, s4.numbered(group)),
                    system=prompts.POLICY_SYSTEM,
                    # No site name here: a failed call's purpose is printed to the console.
                    purpose=f"Browser extension: ask Gemini to flag sale and sharing clauses in a site's policy "
                    f"(part {i} of {len(groups)})",
                )
                for i, group in enumerate(groups, 1)
            )
        )
        if groups and not any(answers):
            entry.errors.append("Gemini didn't answer, so only the quick check ran.")
            entry.llm = "failed"
            return
        picked = [
            # The model has just read the site's own text, so its free-text explanation isn't shown:
            # a hostile policy could make a sale sound harmless. Each category's fixed wording is.
            clause.model_copy(update={"explanation": s4.DEFAULT_EXPLANATION[clause.category]})
            for group, answer in zip(groups, answers)
            if answer
            for clause in s4.parse_clauses(answer, group, entry.company)
        ]
        # The model can add clauses but never weaken one: for a sentence flagged twice, the more
        # serious category comes first and is the one kept.
        merged = sorted(not_legal_only(picked) + entry.clauses, key=lambda c: s4.CATEGORY_ORDER[c.category])
        entry.clauses = s4.merge_clauses(merged)
        entry.llm = "done"
    except Exception as exc:
        log.exception("A site policy LLM pass failed")  # no site name: the console isn't for browsing history
        entry.errors.append(f"The Gemini check failed: {exc}")
        entry.llm = "failed"
    finally:
        entry.sentences = []  # only this pass needed them


def _response(entry: _Site, req: SitePolicyRequest) -> SitePolicyResponse:
    opt_out = _link(req.opt_out_url)
    # Only the site's own "Do Not Sell or Share" link is evidence. Another site's is just a link,
    # and could have been planted in a comment.
    own_opt_out = opt_out if registrable(_host(opt_out)) == entry.domain else None
    # What the page does comes with each request and is judged fresh: it's never stored here.
    trackers = match_trackers(req.third_party_hosts, entry.domain)
    asks_for = list(dict.fromkeys(req.asks_for))
    insecure = list(dict.fromkeys(req.insecure_fields))
    broker = broker_for(entry.domain)
    risks = sorted(
        risks_for(entry.collected, entry.clauses, own_opt_out)
        + page_risks(entry.status, trackers, asks_for, insecure, broker, entry.ads),
        key=lambda r: _RISK_ORDER[r.level],
    )
    overall = risks[0].level if risks else ("low" if entry.status == "ok" else None)
    return SitePolicyResponse(
        site=entry.site, status=entry.status, policy_url=entry.policy_url, read_from=entry.read_from,
        collected=entry.collected, clauses=entry.clauses, no_sale_quote=entry.no_sale_quote,
        risks=risks, risk=overall, summary=summary_line(entry.status, risks, entry.collected),
        opt_out_url=own_opt_out, llm=entry.llm, checked_at=entry.checked_at, errors=list(dict.fromkeys(entry.errors)),
        trackers=trackers, asks_for=asks_for, insecure_fields=insecure, broker=broker, ad_sellers=entry.ads,
    )


class CantCheck(Exception):
    """The site is this computer or the local network, or the page text came from another site.
    The message is shown to the user."""


async def check_site(req: SitePolicyRequest) -> SitePolicyResponse:
    """The extension's one call. Raises CantCheck for a request it won't check."""
    host = (urlsplit(req.origin).hostname or "").rstrip(".").lower()
    if not website.public_host(host):
        raise CantCheck("Only public websites can be checked, not this computer or your local network.")
    if req.page_text is not None and (not req.policy_urls or _host(req.policy_urls[0]) != host):
        raise CantCheck("The page text has to come from the site being checked.")
    site = host.removeprefix("www.")
    if not req.read_policy and req.page_text is None:
        # The automatic check on each visit contacts no site: it reuses a result the user already
        # asked for, or judges only what the browser saw on the page.
        entry = _cache.get(site)
        if entry is None or time.monotonic() - entry.created > CACHE_SECONDS:
            domain = registrable(host)
            entry = _not_read(site=site, domain=domain, company=domain.split(".")[0], status="not_read")
        return _response(entry, req)
    async with _locks.setdefault(site, asyncio.Lock()):  # two tabs on one site read its policy once
        entry = _cached(site, req)
        if entry is None:
            previous = _cache.get(site)
            entry = await _read_and_check(site, registrable(host), req)
            # A site's ads.txt doesn't change with the page, so a new result keeps what was read
            # (unless the user asked to re-check): the site gets one request, not one per result.
            if (
                previous and previous.ads and previous.ads.status != "running" and not req.refresh
                and time.monotonic() - previous.created <= CACHE_SECONDS
            ):
                entry.ads = previous.ads
            if entry.status == "ok" or req.page_text is None:  # a page that isn't a policy keeps the site's result
                _cache[site] = entry
                _cache.move_to_end(site)
                while len(_cache) > MAX_SITES:
                    old, _ = _cache.popitem(last=False)
                    _locks.pop(old, None)
    if req.deep and not entry.deep_started:
        entry.deep_started = True
        read_ads = entry.ads is None
        if read_ads:
            entry.ads = AdSellers(status="running")
        if entry.status == "ok":
            entry.llm = "running"
        if read_ads or entry.status == "ok":
            entry.task = asyncio.create_task(_deep_pass(entry, read_ads))
    return _response(entry, req)
