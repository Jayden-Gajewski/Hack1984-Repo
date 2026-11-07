"""Stage 5: rank likely sources. OWNER: Local LLM & ranking.

Pure function: no network calls, so it's unit-tested with fixtures in backend/tests/.

| Tier     | Rule                                                                              |
|----------|-----------------------------------------------------------------------------------|
| proven   | An alias given only to company X got mail from someone else, and the sender's     |
|          | domain is this listing's site.                                                    |
| likely   | A breach at X falls 0 to 3 years before the listing's public-by date, AND exposed |
|          | at least one field the listing shows. Unknown dates can't support it.             |
| possible | X's privacy policy allows selling or sharing data.                                |

One lead per company at its strongest tier, with every reason (from every tier) as a
sentence that cites dates and their sources. Leads are sorted proven, likely, possible.
Wording: "likely source", never "leaked by" or "who leaked it".
"""

import calendar
from datetime import date
from urllib.parse import urlsplit

from app.models import AliasHit, BreachEvent, Exposure, Lead, PolicyResult

TIER_ORDER = {"proven": 0, "likely": 1, "possible": 2}
LIKELY_YEARS = 3
FIELD_ORDER = ("address", "phone", "email", "relatives", "age", "birthdate", "employer", "ssn",
               "password", "financial", "health")
# A listing that shows an age lines up with a breach that exposed birthdates, and vice versa.
_RELATED = {"age": {"age", "birthdate"}, "birthdate": {"age", "birthdate"}}
_PUBLIC_BY_LABEL = {"wayback": "earliest Wayback snapshot", "published_date": "published date"}
_SOURCE_LABEL = {"ag_notice": "a state attorney general notice", "news": "a news report", "web": "a web page"}
_KIND_LABEL = {"occurred": "happened", "disclosed": "disclosed", "unknown": "reported"}
_CATEGORY_PHRASE = {
    "sale": "selling personal information",
    "data_broker": "sharing personal information with data brokers",
    "sharing": "sharing personal information with other companies",
    "advertising": "using or sharing personal information for targeted ads",
    "affiliates": "sharing personal information with its affiliates",
}


def _period(value: str) -> tuple[date, date] | None:
    """'2021' -> (2021-01-01, 2021-12-31); '2021-03' -> the month; '2021-03-15' -> that day."""
    try:
        parts = [int(p) for p in value.split("-")]
        if len(parts) == 1:
            return date(parts[0], 1, 1), date(parts[0], 12, 31)
        if len(parts) == 2:
            last = calendar.monthrange(parts[0], parts[1])[1]
            return date(parts[0], parts[1], 1), date(parts[0], parts[1], last)
        day = date(*parts[:3])
        return day, day
    except (ValueError, TypeError):
        return None


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # Feb 29
        return day.replace(year=day.year - years, day=28)


def _host_matches(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    domain = domain.lower().removeprefix("www.")
    return bool(domain) and (host == domain or host.endswith("." + domain))


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _listing_fields(exposure: Exposure) -> set[str]:
    fields = {f.field for f in exposure.fields} - {"name"}  # every listing and breach has names
    return set().union(*(_RELATED.get(f, {f}) for f in fields)) if fields else set()


def _rank_one(
    exposure: Exposure,
    breaches: list[BreachEvent],
    policies: list[PolicyResult],
    alias_hits: list[AliasHit],
) -> Exposure:
    leads: dict[str, Lead] = {}

    def add(company: str, tier: str, reason: str, url: str | None) -> None:
        lead = leads.get(company)
        if lead is None:
            leads[company] = Lead(company=company, tier=tier, reasons=[reason], source_urls=[url] if url else [])
            return
        if TIER_ORDER[tier] < TIER_ORDER[lead.tier]:
            lead.tier = tier
            lead.reasons.insert(0, reason)  # the strongest reason reads first
        else:
            lead.reasons.append(reason)
        if url and url not in lead.source_urls:
            lead.source_urls.append(url)

    for hit in alias_hits:
        if _host_matches(exposure.url, hit.from_domain):
            when = f" on {hit.date}" if hit.date else ""
            add(
                hit.company,
                "proven",
                f"Mail sent to the alias you gave only to {hit.company} ({hit.alias}) came from "
                f"{hit.from_domain}, the site with this listing{when}.",
                None,
            )

    public_by = date.fromisoformat(exposure.public_by) if exposure.public_by else None
    fields = _listing_fields(exposure)
    for breach in breaches:
        period = _period(breach.date) if breach.date else None
        if public_by is None or period is None:
            continue
        start, end = period
        if end > public_by or start < _years_before(public_by, LIKELY_YEARS):
            continue
        overlap = sorted(fields & set(breach.data_types), key=FIELD_ORDER.index)
        if not overlap:
            continue
        add(
            breach.company,
            "likely",
            f"A {breach.company} breach {_KIND_LABEL[breach.date_kind]} {breach.date} (per "
            f"{_SOURCE_LABEL[breach.source_kind]}) and exposed {_join(overlap)}, which this listing "
            f"shows. The listing was public by {exposure.public_by} "
            f"({_PUBLIC_BY_LABEL.get(exposure.public_by_source, exposure.public_by_source)}).",
            breach.source_url,
        )

    for policy in policies:
        categories = list(dict.fromkeys(c.category for c in policy.clauses))
        if categories:
            add(
                policy.company,
                "possible",
                f"{policy.company}'s privacy policy allows {_join([_CATEGORY_PHRASE[c] for c in categories])}.",
                policy.policy_url,
            )

    ranked = sorted(leads.values(), key=lambda lead: (TIER_ORDER[lead.tier], lead.company))
    return exposure.model_copy(update={"leads": ranked})


def rank_sources(
    exposures: list[Exposure],
    breaches: list[BreachEvent],
    policies: list[PolicyResult],
    alias_hits: list[AliasHit],
) -> list[Exposure]:
    """Return the exposures with `leads` filled in, strongest first."""
    return [_rank_one(e, breaches, policies, alias_hits) for e in exposures]
