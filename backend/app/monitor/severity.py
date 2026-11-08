"""Rule-based severity, confidence and involvement for an incident. Pure; no LLM.

Three separate questions, three separate answers:

**Severity**: how much harm could this breach do to someone in it? Rules, in order:
1. Start from the most severe kind of data it exposed (tiers in data/breach_data_classes.json).
   No data types reported: medium, until they are.
2. Names + dates of birth + a home address or phone number together: at least high (enough to
   impersonate someone).
3. A verified email of the user's is confirmed in it: one level up.
4. Evidence limits: a breach HIBP flags as fabricated is low; a spam list is at most medium;
   one unofficial source can't make it critical.
Unconfirmed involvement never lowers severity; it's reported on its own.

**Confidence**: how well is the incident itself evidenced? HIBP-verified or an official notice
is high; HIBP-unverified or two independent reports is medium; one unofficial report is low.

**Involvement**: is the user in it? Only a verified email's hashed HIBP match confirms it. A
company announcing a breach never does.
"""

from typing import Any

from app.monitor import breach_data
from app.monitor.incidents import host

LEVELS = breach_data.TIERS  # low, medium, high, critical


def _rank(level: str) -> int:
    return LEVELS.index(level)


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def severity(
    categories: list[str], *, involvement: str, confidence: str, hibp: dict[str, Any] | None
) -> tuple[str, list[str]]:
    """(level, reasons). Reasons are sentences in the order the rules applied."""
    reasons: list[str] = []
    if categories:
        level = max((breach_data.tier(c) for c in categories), key=_rank)
        worst = [breach_data.sentence_label(c) for c in categories if breach_data.tier(c) == level]
        reasons.append(f"Starts at {level}: it exposed {_join(worst)}.")
    else:
        level = "medium"
        reasons.append("Starts at medium: the kinds of data exposed weren't reported.")

    present = set(categories)
    if {"name", "birthdate"} <= present and present & {"address", "phone"} and _rank(level) < _rank("high"):
        level = "high"
        reasons.append("Raised to high: names, dates of birth and contact details together are enough to impersonate someone.")

    if involvement == "confirmed":
        if level != "critical":
            level = LEVELS[_rank(level) + 1]
            reasons.append(f"Raised to {level}: your verified email is in this breach.")
        else:
            reasons.append("Your verified email is in this breach.")

    flags = hibp or {}
    if flags.get("fabricated"):
        level = "low"
        reasons.append("Set to low: Have I Been Pwned flags this breach as likely fabricated.")
    elif flags.get("spam_list") and _rank(level) > _rank("medium"):
        level = "medium"
        reasons.append("Capped at medium: it's a spam list, not a breach of accounts.")
    if confidence == "low" and level == "critical":
        level = "high"
        reasons.append("Capped at high: only one unofficial source reports it so far.")
    return level, reasons


def confidence(facts: dict[str, Any]) -> tuple[str, str]:
    """(level, reason) for how well the incident itself is evidenced."""
    flags = facts.get("hibp")
    sources = facts.get("sources", [])
    if flags and flags.get("fabricated"):
        return "low", "Have I Been Pwned flags it as likely fabricated."
    if flags and flags.get("verified"):
        return "high", "Verified by Have I Been Pwned."
    if any(s.get("official") and s.get("kind") != "hibp" for s in sources):
        return "high", "Reported in an official notice."
    if flags:
        return "medium", "Listed in Have I Been Pwned, but marked unverified there."
    hosts = {host(s["url"]) for s in sources if s.get("url")}
    if len(hosts) >= 2:
        return "medium", f"Reported by {len(hosts)} independent sources."
    return "low", "Reported by only one unofficial source so far."


_CHECK_PROBLEM = {
    "not_configured": "Email checks need an HIBP Pro key (HIBP_API_KEY), so your involvement isn't confirmed.",
    "rate_limited": "HIBP's rate limit stopped the last email check. Refresh again in a minute.",
    "never": "Your verified email hasn't been checked yet. Refresh to check it.",
}


def involvement(facts: dict[str, Any], emails: list[dict[str, Any]]) -> tuple[str, str]:
    """(status, reason): "confirmed", "not_found" or "unconfirmed"."""
    verified = [e for e in emails if e.get("verified_at")]
    name = facts.get("hibp_name")
    if name:
        hits = [e for e in verified if name in (e.get("check", {}).get("breaches") or [])]
        if hits:
            who = _join([e["display"] for e in hits])
            return "confirmed", f"Have I Been Pwned lists your verified address {who} in this breach."
    if not verified:
        return "unconfirmed", (
            "Not confirmed. A breach at a company you use doesn't mean your account was in it. "
            "Verify an email to check."
        )
    if not name:
        return "unconfirmed", (
            "Not confirmed. Have I Been Pwned doesn't have this breach, so your email can't be checked against it."
        )
    if (facts.get("hibp") or {}).get("sensitive"):
        return "unconfirmed", "Not confirmed. HIBP's hashed search doesn't cover breaches it marks as sensitive."
    statuses = [e.get("check", {}).get("status", "never") for e in verified]
    if all(s == "ok" for s in statuses):
        plural = "address" if len(verified) == 1 else "addresses"
        return "not_found", (
            f"Not found for your verified {plural} in Have I Been Pwned. "
            "You may have used a different address with this company."
        )
    problem = next(s for s in statuses if s != "ok")
    if problem == "error":
        message = next(e.get("check", {}).get("message", "") for e in verified if e.get("check", {}).get("status") == "error")
        return "unconfirmed", f"Not confirmed. The last email check failed: {message}".rstrip(": ")
    return "unconfirmed", _CHECK_PROBLEM.get(problem, "Not confirmed.")


def flags(facts: dict[str, Any]) -> list[str]:
    """Caveats shown on the card."""
    f = facts.get("hibp") or {}
    out = []
    if f.get("fabricated"):
        out.append("HIBP flags this breach as likely fabricated")
    if facts.get("hibp") is not None and not f.get("verified") and not f.get("fabricated"):
        out.append("Unverified in HIBP")
    if f.get("spam_list"):
        out.append("Spam list")
    if f.get("malware"):
        out.append("From malware")
    if f.get("stealer_log"):
        out.append("Stealer log")
    if f.get("sensitive"):
        out.append("Sensitive breach")
    if not facts.get("hibp_name"):
        out.append("Not in HIBP")
    return out
