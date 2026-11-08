"""Severity, confidence and involvement rules, and the checklist (pure)."""

import pytest

from app.monitor import checklist, incidents, severity
from tests.monitor_fixtures import SHOPCO, breach


def level(categories, involvement="unconfirmed", confidence="high", hibp=None):
    return severity.severity(categories, involvement=involvement, confidence=confidence, hibp=hibp)[0]


@pytest.mark.parametrize(
    ("categories", "expected"),
    [
        (["password", "email"], "high"),
        (["government_id", "name"], "critical"),
        (["financial"], "critical"),
        (["email", "name"], "medium"),
        (["username", "technical"], "low"),
        ([], "medium"),  # nothing reported yet
        (["name", "birthdate", "address"], "high"),  # enough to impersonate someone
        (["name", "birthdate"], "medium"),
    ],
)
def test_severity_starts_from_the_worst_data(categories, expected):
    assert level(categories) == expected


def test_confirmation_raises_severity_but_its_absence_never_lowers_it():
    assert level(["password", "email"], involvement="confirmed") == "critical"
    assert level(["password", "email"], involvement="unconfirmed") == "high"
    assert level(["password", "email"], involvement="not_found") == "high"
    assert level(["government_id"], involvement="confirmed") == "critical"
    _, reasons = severity.severity(["email"], involvement="confirmed", confidence="high", hibp=None)
    assert reasons[-1] == "Raised to high: your verified email is in this breach."


def test_evidence_limits_apply_last():
    assert level(["government_id"], hibp={"fabricated": True}) == "low"
    assert level(["password"], involvement="confirmed", hibp={"spam_list": True}) == "medium"
    assert level(["financial"], confidence="low") == "high"
    assert level(["password"], confidence="low") == "high"


def test_confidence_comes_from_the_evidence():
    verified = incidents.hibp_facts(breach("A", domain="shopco.example"), SHOPCO, "x")
    assert severity.confidence(verified)[0] == "high"
    unverified = incidents.hibp_facts(breach("B", domain="shopco.example", verified=False, description=""), SHOPCO, "x")
    assert severity.confidence(unverified) == ("medium", "Listed in Have I Been Pwned, but marked unverified there.")
    fabricated = incidents.hibp_facts(breach("C", fabricated=True), None, "x")
    assert severity.confidence(fabricated)[0] == "low"
    one = {"sources": [{"url": "https://news.example/a", "kind": "news", "official": False}], "hibp": None}
    assert severity.confidence(one)[0] == "low"
    two = {"sources": one["sources"] + [{"url": "https://other.example/b", "kind": "web", "official": False}], "hibp": None}
    assert severity.confidence(two)[0] == "medium"
    ag = {"sources": [{"url": "https://ag.example/n", "kind": "ag_notice", "official": True}], "hibp": None}
    assert severity.confidence(ag)[0] == "high"


def _email(status="ok", breaches=(), verified=True):
    return {"display": "j•••e@mail.example", "verified_at": "2026-11-07T00:00:00+00:00" if verified else None,
            "check": {"status": status, "message": "boom", "breaches": list(breaches)}}


def test_involvement_needs_a_verified_email_match():
    facts = incidents.hibp_facts(breach("ShopCo", domain="shopco.example"), SHOPCO, "x")
    assert severity.involvement(facts, [_email(breaches=["ShopCo"])])[0] == "confirmed"
    assert severity.involvement(facts, [_email(breaches=["Other"])])[0] == "not_found"
    status, reason = severity.involvement(facts, [])
    assert status == "unconfirmed" and "doesn't mean your account was in it" in reason
    # An unverified address never confirms anything, whatever its record says.
    assert severity.involvement(facts, [_email(breaches=["ShopCo"], verified=False)])[0] == "unconfirmed"
    status, reason = severity.involvement(facts, [_email(status="not_configured")])
    assert status == "unconfirmed" and "HIBP_API_KEY" in reason
    assert "rate limit" in severity.involvement(facts, [_email(status="rate_limited")])[1]
    assert "boom" in severity.involvement(facts, [_email(status="error")])[1]
    # Partly checked is not "not found".
    assert severity.involvement(facts, [_email(), _email(status="never")])[0] == "unconfirmed"


def test_breaches_hibp_cannot_check_stay_unconfirmed():
    news = {"hibp_name": None, "hibp": None, "sources": []}
    status, reason = severity.involvement(news, [_email()])
    assert status == "unconfirmed" and "doesn't have this breach" in reason
    sensitive = incidents.hibp_facts(breach("S", sensitive=True), None, "x")
    assert severity.involvement(sensitive, [_email()])[0] == "unconfirmed"


def test_checklist_follows_the_exposed_data():
    steps = checklist.steps(["password", "email"], "ShopCo", {}, None)
    ids = [s.id for s in steps]
    assert ids == ["change_password", "unique_passwords", "enable_2fa", "phishing_watch", "monitor_activity"]
    assert steps[0].text == "Change your ShopCo password" and steps[0].why
    assert not any(s.done for s in steps)


def test_checklist_marks_progress_and_puts_the_official_notice_first():
    steps = checklist.steps(["government_id"], "ShopCo", {"credit_freeze": "2026-11-07T10:00:00+00:00"}, "https://shopco.example/notice")
    assert steps[0].id == "read_notice" and steps[0].link == "https://shopco.example/notice"
    freeze = next(s for s in steps if s.id == "credit_freeze")
    assert freeze.done and freeze.done_at and freeze.link.startswith("https://consumer.ftc.gov/")
    unknown = [s.id for s in checklist.steps([], "ShopCo", {}, None)]
    assert unknown == ["change_password", "enable_2fa", "phishing_watch", "monitor_activity"]
    listing = next(s for s in checklist.steps(["address"], "ShopCo", {}, None) if s.id == "remove_listings")
    assert listing.link == "/app"  # the existing exposure scanner


def test_threat_label_and_risks():
    assert checklist.threat_label(["password", "email"]) == "Passwords and email addresses exposed"
    assert checklist.threat_label(["government_id"]) == "Government ID numbers exposed"
    assert checklist.threat_label([]) == "Breach reported; exposed data not yet known"
    assert checklist.risks(["password", "email"])[:2] == ["Account takeover", "Credential stuffing on other sites"]


def test_reference_data_is_consistent():
    from app.monitor import breach_data

    data = breach_data._data()
    for key, cat in data["categories"].items():
        assert cat["tier"] in breach_data.TIERS, key
        assert all(a in data["actions"] for a in cat["actions"]), key
    assert set(data["data_classes"].values()) <= set(data["categories"])
    assert data["default_category"] in data["categories"]
