"""Stage 6 tests: draft letters, opt-out and contact lookups, and re-scan. Offline."""

import asyncio
import json

import httpx
import pytest

from app import outbound
from app.models import Exposure, ScanRequest
from app.stages import s6_resolve as s6

PERSON = ScanRequest(name="Jane Example", city="Springfield", state="IL")
KNOWN = Exposure(id="e1", broker="PeopleFinder", broker_id="peoplefinder",
                 url="https://www.peoplefinder.example/jane-example", opt_out_url="https://peoplefinder.example/optout")
UNKNOWN = Exposure(id="e2", broker="newbroker.example", url="https://newbroker.example/p/jane-example")
GONE = Exposure(id="e3", broker="ListingSite", url="https://listings.example/p/jane-example")
PROFILE = Exposure(id="e4", broker="MeetResults", broker_id="meetresults", source_kind="public_profile",
                   url="https://meetresults.example/athlete/4417")
FILLER = " More text on this page." * 30
SHOPCO = {"id": "shopco", "name": "ShopCo", "domains": ["shopco.example"], "privacy_url": None}


def fake_web(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    body = json.loads(request.content or b"{}")
    if host == "api.tavily.com" and path == "/search" and body["include_domains"] == ["meetresults.example"]:
        return httpx.Response(200, json={"results": [
            {"url": "https://meetresults.example/privacy-request", "title": "Privacy request: hide my profile"},
        ]})
    if host == "api.tavily.com" and path == "/search" and body["include_domains"] == ["newbroker.example"]:
        return httpx.Response(200, json={"results": [
            {"url": "https://newbroker.example/about", "title": "About us"},
            {"url": "https://newbroker.example/remove-my-info", "title": "Remove my information"},
        ]})
    if host == "api.tavily.com" and path == "/search":
        return httpx.Response(200, json={"results": [{
            "url": "https://www.shopco.example/privacy", "title": "Privacy at ShopCo",
            "content": "Press: press@shopco.example. Requests: privacy@shopco.example. Not us: privacy@evil.example",
        }]})
    if host == "api.tavily.com" and path == "/extract":
        return httpx.Response(200, json={
            "results": [
                {"url": KNOWN.url, "raw_content": "Jane Example, 34, Springfield." + FILLER},
                {"url": GONE.url, "raw_content": "This profile is no longer available." + FILLER},
                {"url": UNKNOWN.url, "raw_content": "Access denied"},
            ],
            "failed_results": [],
        })
    raise AssertionError(f"unexpected request: {request.url}")


@pytest.fixture(autouse=True)
def fake_internet(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(outbound, "_client", httpx.AsyncClient(transport=httpx.MockTransport(fake_web)))
    monkeypatch.setattr(s6, "load_json", lambda name: {"brokers.json": [], "public_profiles.json": []}[name])
    monkeypatch.setattr(s6, "all_companies", lambda: [SHOPCO])
    outbound.clear_log()
    yield
    get_settings.cache_clear()


def test_broker_draft_uses_the_known_opt_out_page_without_searching():
    draft = asyncio.run(s6.draft_broker_opt_out(KNOWN, PERSON))
    assert draft.kind == "broker" and draft.send_to_url == "https://peoplefinder.example/optout"
    assert KNOWN.url in draft.body and "Jane Example, Springfield, IL" in draft.body
    assert "Tell me where you got my information" in draft.body
    assert outbound.get_log() == []


def test_unknown_broker_opt_out_page_is_searched_by_broker_name_only():
    draft = asyncio.run(s6.draft_broker_opt_out(UNKNOWN, PERSON))
    assert draft.send_to_url == "https://newbroker.example/remove-my-info"
    [search] = outbound.get_log()
    assert search.body["query"] == "newbroker.example opt out remove my information"
    assert "Jane" not in json.dumps(search.body)


def test_public_profile_gets_a_removal_request_not_a_broker_opt_out():
    draft = asyncio.run(s6.draft_broker_opt_out(PROFILE, PERSON))
    assert draft.kind == "public_profile" and draft.recipient == "MeetResults"
    assert draft.send_to_url == "https://meetresults.example/privacy-request"
    assert "remove my public profile" in draft.body and PROFILE.url in draft.body
    assert "Stop selling" not in draft.body
    [search] = outbound.get_log()
    assert search.body["query"] == "MeetResults remove my profile privacy request"
    assert "Jane" not in json.dumps(search.body)


def test_company_draft_prefers_a_privacy_mailbox_on_the_companys_domain():
    draft = asyncio.run(s6.draft_company_request("shopco", PERSON))
    assert draft.send_to_email == "privacy@shopco.example"
    assert draft.send_to_url == "https://www.shopco.example/privacy"
    assert "which third parties you have sold or shared" in draft.body
    assert "Jane" not in json.dumps(outbound.get_log()[0].body)


def test_letters_hold_name_and_city_only():
    from app.outbound import assert_minimal_query
    letters = (s6.broker_letter(KNOWN, PERSON), s6.profile_letter(PROFILE, PERSON), s6.company_letter("ShopCo", PERSON))
    for _, body in letters:
        assert "Jane Example, Springfield, IL" in body
        assert_minimal_query(body.replace(KNOWN.url, "").replace(PROFILE.url, ""))  # no email, phone, SSN or birthdate


def test_pick_privacy_email():
    assert s6.pick_privacy_email("a@x.example privacy@shop.example", ["shop.example"]) == "privacy@shop.example"
    assert s6.pick_privacy_email("help@eu.shop.example", ["shop.example"]) == "help@eu.shop.example"
    assert s6.pick_privacy_email("privacy@other.example", ["shop.example"]) is None


def test_rescan_reports_each_listing():
    items, errors = asyncio.run(s6.rescan([KNOWN, GONE, UNKNOWN], PERSON))
    assert errors == []
    assert {i.exposure_id: i.status for i in items} == {"e1": "still_listed", "e3": "removed", "e2": "unconfirmed"}


def test_removal_status_matches_whole_words_only():
    person = ScanRequest(name="Ana Li", city="Springfield", state="IL")
    filler = "Search public records and listings for anyone in Illinois. " * 20
    assert s6.removal_status(filler, person) == "removed"  # "li" inside "listings" doesn't count
    assert s6.removal_status(filler + " Ana Li, age 34", person) == "still_listed"
    assert s6.removal_status("too short", person) == "unconfirmed"


def test_combined_status_for_a_card_with_several_pages():
    assert s6.combined_status(["removed", "still_listed"]) == "still_listed"
    assert s6.combined_status(["removed", "removed"]) == "removed"
    assert s6.combined_status(["removed", "unconfirmed"]) == "unconfirmed"


def test_broker_letter_lists_every_merged_page():
    e = Exposure(id="x", broker="PeopleFinder", url="https://peoplefinder.example/a",
                 other_urls=["https://peoplefinder.example/b"])
    person = ScanRequest(name="Jane Example", city="Springfield", state="IL")
    _, body = s6.broker_letter(e, person)
    assert "The listings are here:\nhttps://peoplefinder.example/a\nhttps://peoplefinder.example/b" in body
