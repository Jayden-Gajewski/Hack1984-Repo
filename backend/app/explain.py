"""The plain-English write-up for each exposure: summary, risk level, and per-field details.

Built only from what the scan found (each field and the exact text the page shows, the
public-by date and its source, how the page was found and read) plus the explanations in
data/field_risks.json. No LLM call, so it can't invent anything and adds no time to a scan.
Pure, so it's unit-tested in tests/test_explain.py.

main.py runs it after Stage 2, and again when a saved scan is loaded (older scans don't
have it yet). Wording: never say a company "leaked" anything.
"""

from typing import Any

from app.data import load_json
from app.models import Exposure, FieldInsight

FIELD_ORDER = ("address", "phone", "email", "relatives", "birthdate", "age", "employer", "name")
_LOCATORS = {"address", "phone"}  # how someone reaches you
_IDENTITY = {"relatives", "birthdate"}  # what identity checks and scams lean on
_CONTACT = {"address", "phone", "email", "relatives", "birthdate"}
_DATE_SOURCE = {"wayback": "the Wayback Machine's earliest snapshot", "published_date": "the page's published date"}
_FOUND_VIA = {"tavily": "a Tavily search", "exa": "an Exa search"}


def _info(field: str) -> dict[str, Any]:
    known = load_json("field_risks.json")["fields"].get(field)
    return known or {
        "label": field.title(), "noun": field, "plural": field,
        "why": "It's personal information that helps someone build a profile of you.",
        "misuse": ["Combine it with other details to target you"],
        "protect": "Request removal so this page stops showing it.",
    }


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _order(fields: set[str]) -> list[str]:
    return sorted(fields, key=lambda f: FIELD_ORDER.index(f) if f in FIELD_ORDER else len(FIELD_ORDER))


def insights_for(exposure: Exposure) -> list[FieldInsight]:
    """One entry per kind of information, with every value the page shows for it."""
    found: dict[str, list[str]] = {}
    for finding in exposure.fields:
        values = found.setdefault(finding.field, [])
        if finding.quote not in values:
            values.append(finding.quote)
    insights = []
    for field in _order(set(found)):
        info = _info(field)
        insights.append(
            FieldInsight(
                field=field,
                label=info["label"],
                found=found[field],
                why_it_matters=info["why"],
                misuse=list(info["misuse"]),
                protect=info["protect"],
            )
        )
    return insights


def risk_for(fields: set[str]) -> tuple[str, str]:
    """(level, one-sentence reason) for the combination of fields a listing shows."""
    if fields & _LOCATORS and (fields & _IDENTITY or _LOCATORS <= fields):
        shown = [_info(f)["noun"] for f in _order(fields & (_LOCATORS | _IDENTITY))]
        return (
            "high",
            f"It puts your {_join(shown)} in one place. Together that's enough to find you, and to "
            "convincingly pretend to be you or your family.",
        )
    contact = _order(fields & _CONTACT)
    if contact:
        plural = len(contact) > 1 or contact == ["relatives"]
        return (
            "medium",
            f"Your {_join([_info(f)['noun'] for f in contact])} {'are' if plural else 'is'} enough to "
            "contact you directly or aim scams at you.",
        )
    return "low", "It mostly shows general details. That's lower risk on its own, but it helps people find more about you."


def _amount(insight: FieldInsight) -> str:
    info = _info(insight.field)
    return f"{len(insight.found)} {info['plural']}" if len(insight.found) > 1 else f"your {info['noun']}"


def summary_for(exposure: Exposure, insights: list[FieldInsight]) -> str:
    sentences = []
    details = [i for i in insights if i.field != "name"]
    if details:
        sentences.append(f"{exposure.broker} has a public page about you that shows {_join([_amount(i) for i in details])}.")
    else:
        sentences.append(
            f"{exposure.broker} has a public page about you. It names you, but we couldn't confirm "
            "other details in the text we could read."
        )
    if exposure.public_by:
        source = _DATE_SOURCE.get(exposure.public_by_source, exposure.public_by_source)
        sentences.append(f"It has been public since at least {exposure.public_by}, according to {source}.")
    else:
        sentences.append("We couldn't tell when it first went up.")
    via = _FOUND_VIA.get(exposure.found_via or "", "a web search")
    if exposure.text_source == "extract":
        sentences.append(f"We found it with {via} and read the page itself; the analysis ran on this laptop.")
    else:
        sentences.append(
            f"We found it with {via}, but the site blocked reading the page, so this is based on the "
            "search snippet; the analysis ran on this laptop."
        )
    if exposure.opt_out_url:
        sentences.append(f"{exposure.broker} has an opt-out page, so you can ask for it to be removed.")
    return " ".join(sentences)


def explain(exposure: Exposure) -> Exposure:
    """The exposure with summary, risk, risk_reason and insights filled in."""
    insights = insights_for(exposure)
    level, reason = risk_for({i.field for i in insights})
    return exposure.model_copy(
        update={
            "summary": summary_for(exposure, insights),
            "risk": level,
            "risk_reason": reason,
            "insights": insights,
        }
    )
