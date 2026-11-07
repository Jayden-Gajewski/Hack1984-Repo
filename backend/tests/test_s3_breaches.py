"""Stage 3 tests: grounding, normalization and merging, plus the whole stage against a fake
internet. Fictional company and .example domains only (plus a real AG domain shape)."""

import asyncio
import json

import httpx
import pytest

from app import outbound
from app.clients import ollama
from app.models import BreachEvent
from app.stages import s3_breaches as s3

SHOPCO = {"id": "shopco", "name": "ShopCo", "domains": ["shopco.example"], "privacy_url": None}
AG_URL = "https://oag.ca.gov/ecrime/databreach/reports/sb23-0001"
NEWS_URL = "https://news.example/shopco-confirms-breach"
BLOG_URL = "https://blog.example/the-shopco-hack"

LLM_ANSWER = {"breaches": [
    # [1] AG notice. "ssn" isn't in that notice, so it must be dropped.
    {"source": 1, "date": "2023-03-03", "date_kind": "occurred", "data_types": ["name", "mailing address", "email addresses", "ssn"],
     "summary": "ShopCo says an unauthorized party accessed customer records."},
    # [2] news about the same incident: merged into the AG event; adds phone.
    {"source": 2, "date": "2023-04", "date_kind": "disclosed", "data_types": ["email", "phone numbers"], "summary": "x"},
    # [3] a year that isn't in the source: the date is dropped, then the undated event too.
    {"source": 3, "date": "2019", "date_kind": "occurred", "data_types": ["email"], "summary": "x"},
    {"source": 9, "date": "2023", "data_types": ["email"]},  # no such source
]}


def fake_web(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    body = json.loads(request.content or b"{}")
    if host == "api.tavily.com" and path == "/search" and body.get("topic") == "news":
        return httpx.Response(200, json={"results": [
            {"url": NEWS_URL, "title": "ShopCo confirms data breach",
             "content": "ShopCo said hackers took names, email addresses and phone numbers in March 2023.",
             "published_date": "Tue, 04 Apr 2023 10:00:00 GMT"},
            {"url": "https://news.example/otherco-outage", "title": "OtherCo outage",
             "content": "OtherCo was down. Analysts compared it to ShopCo."},  # passing mention: dropped
        ]})
    if host == "api.tavily.com" and path == "/search":
        return httpx.Response(200, json={"results": [
            {"url": AG_URL, "title": "Submitted Breach Notification Sample",
             "content": "ShopCo Inc. notice: on March 3, 2023 an unauthorized party accessed names, "
                        "mailing addresses and email addresses."},
        ]})
    if host == "api.exa.ai" and path == "/search":
        return httpx.Response(200, json={"results": [
            {"url": BLOG_URL, "title": "The ShopCo hack", "highlights": ["In 2023 ShopCo exposed customer emails."],
             "publishedDate": "2023-04-05T00:00:00.000Z"},
        ]})
    if host == "localhost" and path == "/api/generate":
        return httpx.Response(200, json={"response": json.dumps(LLM_ANSWER)})
    raise AssertionError(f"unexpected request: {request.url}")


@pytest.fixture
def fake_internet(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(outbound, "_client", httpx.AsyncClient(transport=httpx.MockTransport(fake_web)))
    monkeypatch.setattr(ollama, "_generate_slots", asyncio.Semaphore(2))
    data = {"companies.json": [SHOPCO], "breach_sources.json": [{"state": "CA", "name": "CA AG", "domain": "oag.ca.gov"}]}
    monkeypatch.setattr(s3, "load_json", lambda name: data[name])
    monkeypatch.setattr(s3, "all_companies", lambda: data["companies.json"])
    outbound.clear_log()
    yield
    get_settings.cache_clear()


def test_stage_builds_one_grounded_event_per_incident(fake_internet):
    events, errors = asyncio.run(s3.breach_timelines(["shopco"]))

    assert errors == []
    assert len(events) == 1
    [event] = events
    assert event.source_url == AG_URL and event.source_kind == "ag_notice"  # the AG notice wins
    assert (event.date, event.date_kind) == ("2023-03-03", "occurred")
    assert event.data_types == ["name", "email", "phone", "address"]  # ssn dropped, phone merged in


def test_stage_sends_the_company_name_only(fake_internet):
    asyncio.run(s3.breach_timelines(["shopco"]))
    remote = [e for e in outbound.get_log() if not e.local]
    assert {e.service for e in remote} == {"tavily", "exa"}
    for entry in remote:
        assert "ShopCo" in entry.body["query"]
        assert "unauthorized party" not in json.dumps(entry.body)  # result text never goes back out


def test_normalize_data_type():
    assert s3.normalize_data_type("email addresses") == "email"  # not "address"
    assert s3.normalize_data_type("Home Address") == "address"
    assert s3.normalize_data_type("IP address") is None
    assert s3.normalize_data_type("usernames") is None
    assert s3.normalize_data_type("Social Security numbers") == "ssn"
    assert s3.normalize_data_type("dates of birth") == "birthdate"
    assert s3.normalize_data_type("payment card numbers") == "financial"
    assert s3.normalize_data_type(42) is None


def test_result_date_reads_both_apis():
    assert s3.result_date("2024-06-01T08:32:54.000Z") == "2024-06-01"
    assert s3.result_date("Wed, 12 Nov 2025 00:00:00 GMT") == "2025-11-12"
    assert s3.result_date("last spring") is None
    assert s3.result_date(None) is None


def test_mentions_company():
    ticketmaster = {"name": "Ticketmaster", "domains": ["ticketmaster.com", "livenation.com"]}
    assert s3.mentions_company(ticketmaster, "Live Nation confirms breach")  # via the domain label
    assert s3.mentions_company({"name": "AT&T", "domains": ["att.com"]}, "AT&T notifies customers")
    assert not s3.mentions_company({"name": "AT&T", "domains": ["att.com"]}, "a cyberattack elsewhere")


def _event(date, kind="news", types=("email",), company="shopco", url=None):
    return BreachEvent(company_id=company, company="ShopCo", date=date, date_kind="disclosed" if date else "unknown",
                       data_types=list(types), source_url=url or f"https://x.example/{date}-{kind}", source_kind=kind)


def test_merge_keeps_undated_events_only_without_dated_ones():
    merged = s3.merge_events([_event("2021-05"), _event(None), _event("2023-01-02", kind="ag_notice")])
    assert [e.date for e in merged] == ["2021-05", "2023-01-02"]
    assert s3.merge_events([_event(None)])[0].date is None  # nothing dated: keep it


def test_merge_prefers_ag_notices_and_unions_data_types():
    [merged] = s3.merge_events([_event("2023-04", types=("phone",)), _event("2023-03-03", kind="ag_notice")])
    assert merged.source_kind == "ag_notice" and merged.date == "2023-03-03"
    assert merged.data_types == ["email", "phone"]
