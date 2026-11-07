"""Tests for the per-exposure write-up (app/explain.py). Pure, offline, fictional data."""

import pytest

from app import db, explain, main
from app.data import load_json
from app.models import Exposure, FieldFinding
from app.prompts import LISTING_FIELDS


def _exposure(*fields: tuple[str, str], **extra) -> Exposure:
    base = {"id": "e1", "broker": "PeopleFinder", "url": "https://peoplefinder.example/jane-example"}
    return Exposure(**{**base, **extra, "fields": [FieldFinding(field=f, quote=q) for f, q in fields]})


def test_every_listing_field_has_an_explanation():
    risks = load_json("field_risks.json")["fields"]
    for field in LISTING_FIELDS:
        info = risks[field]
        assert info["label"] and info["noun"] and info["plural"] and info["why"] and info["protect"]
        assert len(info["misuse"]) >= 2


def test_insights_group_every_value_under_its_field_in_a_fixed_order():
    exposure = _exposure(
        ("name", "Jane Example"), ("phone", "(217) 555-0142"), ("address", "12 Elm St, Springfield, IL"),
        ("phone", "(217) 555-0199"), ("phone", "(217) 555-0142"),
    )
    insights = explain.insights_for(exposure)
    assert [(i.field, i.found) for i in insights] == [
        ("address", ["12 Elm St, Springfield, IL"]),
        ("phone", ["(217) 555-0142", "(217) 555-0199"]),  # the repeat is dropped
        ("name", ["Jane Example"]),
    ]
    assert insights[1].label == "Phone number" and "SIM-swap" in " ".join(insights[1].misuse)


@pytest.mark.parametrize("fields,level", [
    ({"address", "phone"}, "high"),
    ({"address", "relatives"}, "high"),
    ({"phone", "birthdate"}, "high"),
    ({"address"}, "medium"),
    ({"email"}, "medium"),
    ({"relatives"}, "medium"),
    ({"age", "employer", "name"}, "low"),
    (set(), "low"),
])
def test_risk_levels(fields, level):
    assert explain.risk_for(fields)[0] == level


def test_risk_reasons_read_naturally():
    assert explain.risk_for({"address", "phone", "relatives"})[1].startswith(
        "It puts your home address, phone number and relatives in one place."
    )
    assert explain.risk_for({"email"})[1].startswith("Your email address is enough")
    assert explain.risk_for({"relatives"})[1].startswith("Your relatives are enough")


def test_summary_covers_what_when_and_how():
    exposure = _exposure(
        ("address", "12 Elm St"), ("phone", "(217) 555-0142"), ("phone", "(217) 555-0199"),
        ("name", "Jane Example"),
        public_by="2021-03-15", public_by_source="wayback", found_via="tavily", text_source="extract",
        opt_out_url="https://peoplefinder.example/optout",
    )
    summary = explain.explain(exposure).summary
    assert "PeopleFinder has a public page about you that shows your home address and 2 phone numbers." in summary
    assert "public since at least 2021-03-15, according to the Wayback Machine's earliest snapshot" in summary
    assert "Tavily search and read the page itself" in summary
    assert "opt-out page" in summary


def test_summary_is_honest_about_unknown_dates_and_blocked_pages():
    summary = explain.explain(_exposure(("name", "Jane Example"), text_source="snippet")).summary
    assert "couldn't confirm other details" in summary
    assert "We couldn't tell when it first went up." in summary
    assert "search snippet" in summary


def test_explain_fills_every_field_and_never_accuses():
    explained = explain.explain(_exposure(("address", "12 Elm St"), ("relatives", "John Example")))
    assert explained.risk == "high" and explained.risk_reason and len(explained.insights) == 2
    text = " ".join([explained.summary, explained.risk_reason] + [
        " ".join([i.why_it_matters, i.protect, *i.misuse]) for i in explained.insights
    ])
    assert "leak" not in text.lower()


def test_scan_and_saved_scans_carry_the_write_up(client, monkeypatch):
    listing = _exposure(("address", "12 Elm St"), ("phone", "(217) 555-0142"))

    async def find(req):
        return [listing], []

    async def date(items):
        return items, []

    monkeypatch.setattr(main.s1_exposures, "find_exposures", find)
    monkeypatch.setattr(main.s2_dating, "date_exposures", date)
    person = {"name": "Jane Example", "city": "Springfield", "state": "IL", "consent": True}
    [card] = client.post("/api/scan", json=person).json()["exposures"]
    assert card["risk"] == "high" and card["summary"] and len(card["insights"]) == 2

    # A scan saved before this feature existed gets the write-up when it's loaded.
    old = {"scan_id": "00000000-0000-0000-0000-000000000001", "errors": [],
           "exposures": [listing.model_dump(exclude={"summary", "risk", "risk_reason", "insights"})]}
    monkeypatch.setattr(db, "latest_scan", lambda: ({"name": "Jane Example", "city": "Springfield", "state": "IL"}, old))
    [loaded] = client.get("/api/scans/latest").json()["exposures"]
    assert loaded["risk"] == "high" and loaded["insights"][0]["field"] == "address"
