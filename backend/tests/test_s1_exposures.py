"""Stage 1 tests. The end-to-end ones run the real stage, clients and outbound log against a
fake internet (Tavily, Exa and Gemini answered by an httpx MockTransport). Offline, no credits.
The person and every domain are fictional."""

import asyncio
import json

import httpx
import pytest

from app import outbound, prompts
from app.clients import gemini, wayback
from app.config import get_settings
from app.models import FieldFinding
from app.outbound import assert_minimal_query
from app.stages import s1_exposures as s1

PERSON = {"name": "Jane Example", "city": "Springfield", "state": "IL", "consent": True}

BROKERS = [
    {"id": "peoplefinder", "name": "PeopleFinder", "domain": "peoplefinder.example",
     "opt_out_url": "https://peoplefinder.example/optout"},
    {"id": "listingsite", "name": "ListingSite", "domain": "listings.example", "opt_out_url": None},
]
PROFILES = [
    {"id": "meetresults", "name": "MeetResults", "domain": "meetresults.example", "opt_out_url": None},
]
DATA = {"brokers.json": BROKERS, "public_profiles.json": PROFILES}

PEOPLEFINDER_URL = "https://www.peoplefinder.example/jane-example/springfield-il"
LISTINGS_URL = "https://listings.example/p/jane-example"  # blocks extraction
NEWBROKER_URL = "https://newbroker.example/people/jane-example"  # found via find-similar
BLOG_URL = "https://blog.example/jane-example-wins-award"  # about her, but not a listing
OTHER_PERSON_URL = "https://peoplefinder.example/john-smith"  # wrong person
PROFILE_URL = "https://www.meetresults.example/athlete/4417"  # public profile: no name in the URL

FILLER = " More text on this page." * 30
PAGES = {
    PEOPLEFINDER_URL: "PAGE-PF Jane Example, age 34, Springfield, IL. Current address: 12 Elm St, "
    "Springfield, IL. Phone: (217) 555-0142. Relatives: John Example." + FILLER,
    NEWBROKER_URL: "PAGE-NB Jane Example in Springfield. Possible match." + FILLER,
    BLOG_URL: "PAGE-BLOG Jane Example of Springfield won the county award." + FILLER,
    PROFILE_URL: "PAGE-PROF Jane Example. Springfield High School, Class of 2019. 1600m: 5:42.10" + FILLER,
}
LISTINGS_SNIPPET = "PAGE-LS Jane Example, 34, Springfield IL. Relatives: John Example."

# What Gemini answers for each page, keyed by a marker in the page text.
ANSWERS = {
    "PAGE-PF": {"is_same_person": True, "confidence": 0.9, "is_people_search_site": True, "fields": [
        {"field": "address", "quote": "12 Elm St, Springfield, IL"},
        {"field": "phone", "quote": "(217) 555-0142"},
        {"field": "ssn", "quote": "123-45-6789"},  # not a listing field: dropped
        {"field": "email", "quote": "jane@example.com"},  # not on the page: dropped
    ]},
    "PAGE-LS": {"is_same_person": True, "confidence": 0.7,
                "fields": [{"field": "relatives", "quote": "John Example"}]},
    "PAGE-NB": {"is_same_person": True, "confidence": 0.3, "is_people_search_site": True, "fields": []},
    "PAGE-BLOG": {"is_same_person": True, "confidence": 0.95, "is_people_search_site": False,
                  "fields": [{"field": "name", "quote": "Jane Example"}]},
    # Not a people-search site, but it's on our public-profile list, so it counts.
    "PAGE-PROF": {"is_same_person": True, "confidence": 0.8, "is_people_search_site": False, "fields": [
        {"field": "school", "quote": "Springfield High School, Class of 2019"},
        {"field": "phone", "quote": "5:42.10"},  # not a profile field: dropped
    ]},
}


def fake_web(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    body = json.loads(request.content or b"{}")
    if host == "api.tavily.com" and path == "/search":
        domains = body.get("include_domains", [])
        results = []
        if "peoplefinder.example" in domains:
            results = [
                {"url": PEOPLEFINDER_URL, "title": "Jane Example in Springfield, IL | PeopleFinder",
                 "content": "Jane Example, 34, Springfield IL"},
                {"url": LISTINGS_URL, "title": "Jane Example - ListingSite", "content": LISTINGS_SNIPPET},
                {"url": OTHER_PERSON_URL, "title": "John Smith | PeopleFinder", "content": "John Smith, Chicago"},
            ]
        elif domains == ["meetresults.example"]:
            results = [{"url": PROFILE_URL, "title": "Jane Example - Springfield High School Track",
                        "content": "Jane Example, Springfield High School"}]
        elif "newbroker.example" in domains:
            results = [{"url": NEWBROKER_URL, "title": "Jane Example | NewBroker",
                        "content": "Jane Example, Springfield"}]
        return httpx.Response(200, json={"results": results})
    if host == "api.exa.ai" and path == "/search" and body["query"].startswith("people search sites like"):
        return httpx.Response(200, json={"results": [
            {"url": "https://newbroker.example/people/someone-else"},
            {"url": "https://www.peoplefinder.example/other"},  # already known: not "new"
        ]})
    if host == "api.exa.ai" and path == "/search":
        return httpx.Response(200, json={"results": [
            {"url": BLOG_URL, "title": "County award for Jane Example",
             "highlights": ["Jane Example of Springfield..."], "publishedDate": "2024-03-02T00:00:00.000Z"},
            # The same PeopleFinder page Tavily found, spelled differently: must be deduped.
            {"url": "https://peoplefinder.example/jane-example/springfield-il/", "title": "dup", "highlights": ["dup"]},
        ]})
    if host == "api.tavily.com" and path == "/extract":
        urls = body["urls"]
        return httpx.Response(200, json={
            "results": [{"url": u, "raw_content": PAGES[u]} for u in urls if u in PAGES],
            "failed_results": [{"url": u, "error": "blocked"} for u in urls if u not in PAGES],
        })
    if host == "generativelanguage.googleapis.com" and path.endswith(":generateContent"):
        marker = next(m for m in ANSWERS if m in body["contents"][0]["parts"][0]["text"])
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWERS[marker])}]}}]})
    if host == "web.archive.org" and path == "/cdx/search/cdx":
        # Stage 2: only the PeopleFinder listing was ever archived.
        if request.url.params["url"] == PEOPLEFINDER_URL:
            return httpx.Response(200, json=[["timestamp", "original"], [SNAPSHOT, PEOPLEFINDER_URL]])
        return httpx.Response(200, json=[])
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


SNAPSHOT = "20210315120000"


def _use_transport(monkeypatch, handler) -> None:
    monkeypatch.setattr(outbound, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    # Fresh concurrency limits per test: asyncio semaphores bind to one event loop.
    monkeypatch.setattr(gemini, "_generate_slots", asyncio.Semaphore(2))
    monkeypatch.setattr(wayback, "_slots", asyncio.Semaphore(4))
    outbound.clear_log()


@pytest.fixture
def fake_internet(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    get_settings.cache_clear()
    _use_transport(monkeypatch, fake_web)
    monkeypatch.setattr(s1, "load_json", lambda name: DATA[name])
    yield
    get_settings.cache_clear()


# ---------- end to end through POST /api/scan ----------


def test_scan_finds_grounded_exposures(client, fake_internet):
    res = client.post("/api/scan", json=PERSON)

    body = res.json()
    assert res.status_code == 200
    by_broker = {e["broker"]: e for e in body["exposures"]}
    # The wrong person, the news article and the low-confidence match are all dropped,
    # and the page both engines found shows up once.
    assert sorted(by_broker) == ["ListingSite", "MeetResults", "PeopleFinder"]

    found = by_broker["PeopleFinder"]
    assert found["url"] == PEOPLEFINDER_URL
    assert found["text_source"] == "extract"
    assert found["found_via"] == "tavily"
    assert found["opt_out_url"] == "https://peoplefinder.example/optout"
    assert found["source_kind"] == "broker"
    assert found["fields"] == [
        {"field": "address", "quote": "12 Elm St, Springfield, IL"},
        {"field": "phone", "quote": "(217) 555-0142"},
    ]  # the made-up SSN and email are gone

    # Stage 2 dated it from its earliest Wayback snapshot, with the link as evidence.
    assert found["public_by"] == "2021-03-15"
    assert found["public_by_source"] == "wayback"
    assert found["public_by_evidence_url"] == f"https://web.archive.org/web/{SNAPSHOT}/{PEOPLEFINDER_URL}"

    blocked = by_broker["ListingSite"]
    assert blocked["text_source"] == "snippet"  # extraction was blocked
    assert blocked["fields"] == [{"field": "relatives", "quote": "John Example"}]
    # Never archived and no published date: unknown, not a guess.
    assert (blocked["public_by"], blocked["public_by_source"]) == (None, "unknown")

    profile = by_broker["MeetResults"]
    assert profile["source_kind"] == "public_profile"
    assert profile["broker_id"] == "meetresults"
    assert profile["fields"] == [{"field": "school", "quote": "Springfield High School, Class of 2019"}]

    assert body["errors"] == []


def test_scan_sends_only_name_and_city_to_search_and_page_text_only_to_gemini(client, fake_internet):
    client.post("/api/scan", json=PERSON)

    log = outbound.get_log()
    calls = [e for e in log if e.service == "gemini"]
    remote = [e for e in log if e.service != "gemini"]  # the search and archive APIs
    assert {e.service for e in remote} == {"tavily", "exa", "wayback"} and calls
    exa_queries = [e.body["query"] for e in remote if e.service == "exa"]
    assert "people search sites like peoplefinder.example" in exa_queries  # broker discovery ran
    for entry in remote:
        sent = entry.url + json.dumps(entry.body)
        assert "Elm St" not in sent and "555-0142" not in sent  # page text never goes back out
        assert "test-tavily-key" not in json.dumps(entry.headers)
        assert "test-exa-key" not in json.dumps(entry.headers)
        if isinstance(entry.body, dict) and "query" in entry.body:
            assert_minimal_query(entry.body["query"])
            if entry.body["query"].startswith("people search sites like"):
                assert "Example" not in entry.body["query"]  # company-only: no name, no page URL
            else:
                assert "Jane Example" in entry.body["query"]
    assert sum(e.purpose.startswith("Ask the AI whether") for e in calls) == 5  # one per candidate
    for entry in calls:  # the key is redacted in the log, and never in the URL
        assert entry.headers["x-goog-api-key"] == "REDACTED" and "test-gemini-key" not in entry.url



def test_scan_stops_before_searching_when_nothing_is_set_up(client, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("EXA_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()

    def nothing_running(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _use_transport(monkeypatch, nothing_running)
    try:
        body = client.post("/api/scan", json=PERSON).json()
    finally:
        get_settings.cache_clear()

    assert body["exposures"] == []
    assert any("No search API keys" in e for e in body["errors"])
    assert any("AI model isn't set up" in e for e in body["errors"])
    assert not outbound.get_log()  # nothing was sent anywhere


# ---------- pure helpers ----------


def test_parse_analysis_is_conservative():
    text = "Jane Example lives at 12 Elm St. Phone (217) 555-0142."
    ok = {"is_same_person": True, "confidence": 0.8, "fields": [{"field": "address", "quote": "12  Elm St"}]}

    assert s1.parse_analysis(ok, text, known_broker=True) == [FieldFinding(field="address", quote="12 Elm St")]
    assert s1.parse_analysis({**ok, "confidence": 85}, text, True) is not None  # percent
    assert s1.parse_analysis({**ok, "confidence": 0.4}, text, True) is None
    assert s1.parse_analysis({**ok, "confidence": "high"}, text, True) is None
    assert s1.parse_analysis({**ok, "is_same_person": False}, text, True) is None
    assert s1.parse_analysis({}, text, True) is None
    # A page on a site we don't list must say it's a people-search listing.
    assert s1.parse_analysis(ok, text, known_broker=False) is None
    assert s1.parse_analysis({**ok, "is_people_search_site": True}, text, False) is not None
    # Fields outside the listing vocabulary, or quotes not on the page, are dropped.
    assert s1.parse_analysis({**ok, "fields": [{"field": "ssn", "quote": "Jane"}]}, text, True) == []
    assert s1.parse_analysis({**ok, "fields": [{"field": "email", "quote": "jane@x.example"}]}, text, True) == []
    assert s1.parse_analysis({**ok, "fields": "address"}, text, True) == []
    # Public profiles use their own field list.
    school = {**ok, "fields": [{"field": "school", "quote": "Jane Example"}]}
    assert s1.parse_analysis(school, text, True) == []
    assert s1.parse_analysis(school, text, True, allowed_fields=("name", "school")) == [
        FieldFinding(field="school", quote="Jane Example")
    ]
    # A city on its own is what we searched with, not a street address.
    city_only = {**ok, "fields": [{"field": "address", "quote": "Springfield IL"}]}
    assert s1.parse_analysis(city_only, "Jane Example, 34, Springfield IL.", True) == []


def test_url_name_and_date_helpers():
    assert s1.last_name("Jane Q. Example Jr.") == "example"
    # A surname that only appears in the domain doesn't count as a mention.
    wrong_person = s1.Candidate(url="https://peoplefinder.example/john-smith", title="John Smith",
                                snippet="John Smith, Chicago", via="tavily")
    assert not s1.mentions(wrong_person, "example")
    assert s1.normalize_url("https://www.PeopleFinder.example/a/b/#top") == s1.normalize_url(
        "https://peoplefinder.example/a/b"
    )
    assert s1.broker_for("https://people.peoplefinder.example/x", BROKERS)["id"] == "peoplefinder"
    assert s1.broker_for("https://notpeoplefinder.example/x", BROKERS) is None
    assert s1.known_site("https://meetresults.example/a/1", BROKERS, PROFILES)[1] == "public_profile"
    assert s1.known_site("https://peoplefinder.example/x", BROKERS, PROFILES)[1] == "broker"
    assert s1.known_site("https://other.example/x", BROKERS, PROFILES) == (None, "broker")
    # Profile pages are asked for profile fields, broker pages for listing fields.
    profile = s1.Candidate(url=PROFILE_URL, title="", snippet="", via="tavily")
    listing = s1.Candidate(url=PEOPLEFINDER_URL, title="", snippet="", via="tavily")
    assert s1._fields_for(profile, BROKERS, PROFILES) == prompts.PROFILE_FIELDS
    assert s1._fields_for(listing, BROKERS, PROFILES) == prompts.LISTING_FIELDS
    assert '"field": "name|school|age|employer"' in prompts.field_extraction_prompt(
        "Jane Example", "Springfield", "IL", "text", fields=prompts.PROFILE_FIELDS
    )
    assert s1.iso_date("2023-05-01T00:00:00.000Z") == "2023-05-01"
    assert s1.iso_date("last spring") is None


def test_public_profiles_rank_after_brokers_and_before_unknown_sites():
    def cand(url):
        return s1.Candidate(url=url, title="Jane Example", snippet="", via="tavily")

    found = [cand("https://other.example/jane-example"), cand(PROFILE_URL), cand(PEOPLEFINDER_URL)]
    picked = s1.select_candidates(found, "example", BROKERS, 10, PROFILES)
    assert [c.url for c in picked] == [PEOPLEFINDER_URL, PROFILE_URL, "https://other.example/jane-example"]


def test_surname_matches_whole_words_only():
    assert s1.has_word("Jane Li, Springfield", "li")
    assert s1.has_word("/people/Jane-Li/", "li")
    assert s1.has_word("/names/jane_li", "li")
    assert not s1.has_word("Search listings by phone", "li")
    assert not s1.has_word("anything", "")


def test_listing_that_names_someone_else_is_dropped():
    text = "Jane Dosland, 304 Saxon Dr, Springfield IL"
    out = {"is_same_person": True, "confidence": 0.9, "fields": [
        {"field": "name", "quote": "Jane Dosland"}, {"field": "address", "quote": "304 Saxon Dr"}]}
    assert s1.parse_analysis(out, text, True, surname="example") is None
    text_ok = "Jane Example, 12 Elm St, Springfield IL"
    ok = {**out, "fields": [{"field": "name", "quote": "Jane Example"}]}
    assert s1.parse_analysis(ok, text_ok, True, surname="example") == [FieldFinding(field="name", quote="Jane Example")]


def test_window_keeps_the_listing_from_a_long_page():
    page = "menu " * 3000 + "Jane Example, 12 Elm St" + " footer" * 500
    win = s1.window_around(page, "example", size=1000)
    assert len(win) == 1000 and "Jane Example, 12 Elm St" in win
    assert s1.window_around("short page", "example") == "short page"
    assert s1.window_around("x" * 2000, "absent", size=500) == "x" * 500  # no mention: the start


def test_pages_without_city_or_state_skip_the_llm():
    assert s1.mentions_place("Jane Example, Springfield", "Springfield", "IL")
    assert s1.mentions_place("Jane Example, Peoria, IL 61602", "Springfield", "IL")
    assert not s1.mentions_place("Jane Example, Austin, TX", "Springfield", "IL")
    # state codes match only as written, so ordinary words don't count
    assert not s1.mentions_place("Jane lives in a house", "Springfield", "IN")
    assert s1.mentions_place("Jane Example, Gary, IN", "Springfield", "IN")


def test_parse_analysis_keeps_several_values_per_field():
    text = ("Jane Example. Phones: (217) 555-0142, (217) 555-0199. Addresses: 12 Elm St, Springfield IL; "
            "40 Oak Ave, Peoria IL. Relatives: John Example, Mary Example, Sam Example, Ann Example.")
    out = {"is_same_person": True, "confidence": 0.9, "fields": [
        {"field": "phone", "quote": "(217) 555-0142"},
        {"field": "phone", "quote": "(217) 555-0199"},
        {"field": "phone", "quote": "555-0142"},  # part of a value we already have
        {"field": "address", "quote": "12 Elm St, Springfield IL"},
        {"field": "address", "quote": "40 Oak Ave, Peoria IL"},
        {"field": "relatives", "quote": "John Example"},
        {"field": "relatives", "quote": "Mary Example"},
        {"field": "relatives", "quote": "Sam Example"},
        {"field": "relatives", "quote": "Ann Example"},  # over the limit of 3
        {"field": "name", "quote": "Jane Example"},
        {"field": "name", "quote": "Jane Example"},
    ]}
    fields = s1.parse_analysis(out, text, known_broker=True)
    counts = {f: sum(x.field == f for x in fields) for f in ("phone", "address", "relatives", "name")}
    assert counts == {"phone": 2, "address": 2, "relatives": 3, "name": 1}


def test_select_candidates_skips_social_sites_and_caps_each_site():
    brokers = [{"id": "pf", "name": "PeopleFinder", "domain": "peoplefinder.example", "opt_out_url": None}]
    def c(url):
        return s1.Candidate(url=url, title="Jane Example", snippet="Springfield IL", via="tavily")
    found = [c(f"https://www.peoplefinder.example/p/{i}") for i in range(5)] + [
        c("https://www.linkedin.com/in/jane-example"),
        c("https://listings.example/jane-example"),
        s1.Candidate(url="https://other.example/x", title="", snippet="", via="exa"),
    ]
    picked = [x.url for x in s1.select_candidates(found, "example", brokers, max_pages=10)]
    assert sum("peoplefinder" in u for u in picked) == s1.MAX_PER_SITE  # capped per site
    assert picked[0].startswith("https://www.peoplefinder.example")  # known brokers first
    assert "https://listings.example/jane-example" in picked
    assert not any("linkedin" in u for u in picked)  # never a listing: no LLM call
    assert not any("other.example" in u for u in picked)  # doesn't mention the surname
    assert len(s1.select_candidates(found, "example", brokers, max_pages=2)) == 2


# ---------- one card per site ----------


def _card(url, fields, broker_id="peoplefinder", text_source="extract", published=None):
    return s1.Exposure(
        id=s1.exposure_id(url), broker="PeopleFinder", broker_id=broker_id, url=url,
        text_source=text_source, published_date=published,
        fields=[FieldFinding(field=f, quote=q) for f, q in fields],
    )


def test_merge_by_site_makes_one_card_per_site():
    a = _card("https://peoplefinder.example/jane-example", [("name", "Jane Example"), ("age", "Age 34")],
              published="2023-05-01")
    b = _card("https://peoplefinder.example/jane-example/springfield-il",
              [("name", "Jane Example"), ("age", "Age 34"), ("address", "12 Elm St, Springfield IL")],
              published="2021-02-03")
    other = _card("https://listings.example/jane", [("name", "Jane Example")], broker_id="listingsite")
    merged = s1.merge_by_site([a, other, b])
    assert [e.broker_id for e in merged] == ["peoplefinder", "listingsite"]
    card = merged[0]
    assert card.url == b.url  # the page that shows the most
    assert card.id == b.id
    assert card.other_urls == [a.url]
    assert [(f.field, f.quote) for f in card.fields] == [
        ("name", "Jane Example"), ("age", "Age 34"), ("address", "12 Elm St, Springfield IL"),
    ]
    assert card.published_date == "2021-02-03"  # earliest of the pages
    assert merged[1].other_urls == []


def test_merge_by_site_groups_unlisted_sites_by_host_and_keeps_distinct_values():
    a = _card("https://www.newsite.example/p/1", [("address", "1 Oak Ave")], broker_id=None)
    b = _card("https://newsite.example/p/2", [("address", "9 Pine Rd"), ("address", "1 oak  ave")], broker_id=None)
    merged = s1.merge_by_site([a, b])
    assert len(merged) == 1
    assert sorted(" ".join(f.quote.lower().split()) for f in merged[0].fields) == ["1 oak ave", "9 pine rd"]
