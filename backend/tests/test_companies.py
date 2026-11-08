"""Adding any company to the account picker. Offline: Exa is always replaced with a fake."""

import asyncio

import pytest

from app import companies
from app.data import load_json
from app.models import CompanyRequest


@pytest.fixture(autouse=True)
def local_file(tmp_path, monkeypatch):
    """Added companies go to a temp file, never to backend/local/."""
    monkeypatch.setattr(companies, "LOCAL_FILE", tmp_path / "companies.json")


def _fake_exa(monkeypatch, urls=(), fail=False):
    calls = []

    async def search(query, **kwargs):
        calls.append((query, kwargs))
        if fail:
            raise RuntimeError("EXA_API_KEY is not set.")
        return {"results": [{"url": u} for u in urls]}

    monkeypatch.setattr(companies.exa, "search", search)
    return calls


def test_lookup_data_shape():
    data = load_json("website_lookup.json")
    assert set(data) == {"not_a_homepage", "two_level_suffixes"}


def test_registrable_domain():
    assert companies.registrable("www.microsoft.com") == "microsoft.com"
    assert companies.registrable("policies.tinder.com") == "tinder.com"
    assert companies.registrable("news.bbc.co.uk") == "bbc.co.uk"


def test_typed_website_is_recognized():
    assert companies.as_website("tinder.com") == "tinder.com"
    assert companies.as_website("https://www.PlayStation.com/en-us/") == "playstation.com"
    assert companies.as_website("Tinder") is None
    assert companies.as_website("AT&T") is None


def test_pick_domain_prefers_the_company_site_over_directories():
    urls = ["https://en.wikipedia.org/wiki/Tinder_(app)", "https://www.linkedin.com/company/tinder", "https://tinder.com/"]
    assert companies.pick_domain("Tinder", urls) == "tinder.com"


def test_pick_domain_keeps_a_listed_site_when_the_name_matches():
    assert companies.pick_domain("Facebook", ["https://www.facebook.com/"]) == "facebook.com"


def test_pick_domain_skips_directories_when_nothing_matches():
    urls = ["https://en.wikipedia.org/wiki/Example", "https://example-holdings.com/"]
    assert companies.pick_domain("Totally Different", urls) == "example-holdings.com"
    assert companies.pick_domain("Nothing", ["https://en.wikipedia.org/wiki/X"]) is None


def test_listed_company_is_returned_without_a_search(monkeypatch):
    calls = _fake_exa(monkeypatch)
    company = asyncio.run(companies.add_company("linkedin"))
    assert company["id"] == "linkedin" and company["custom"] is False
    assert calls == []


def test_typed_website_is_used_without_a_search(monkeypatch):
    calls = _fake_exa(monkeypatch)
    company = asyncio.run(companies.add_company("playstation.com"))
    assert company["domains"] == ["playstation.com"]
    assert company["domain_source"] == "typed" and company["custom"] is True
    assert calls == []


def test_name_is_matched_with_one_company_search_and_saved(monkeypatch):
    calls = _fake_exa(monkeypatch, ["https://en.wikipedia.org/wiki/Tinder_(app)", "https://tinder.com/"])
    company = asyncio.run(companies.add_company("Tinder"))
    assert company["domains"] == ["tinder.com"] and company["domain_source"] == "search"
    assert len(calls) == 1
    query, kwargs = calls[0]
    assert query == "Tinder" and kwargs["category"] == "company"  # the name only
    assert companies.find_company(company["id"])["name"] == "Tinder"
    # Adding it again returns the saved entry, with no second search.
    assert asyncio.run(companies.add_company("tinder"))["id"] == company["id"]
    assert len(calls) == 1


def test_failed_search_falls_back_to_a_labeled_guess(monkeypatch):
    _fake_exa(monkeypatch, fail=True)
    company = asyncio.run(companies.add_company("Bank of Example"))
    assert company["domains"] == ["bankofexample.com"] and company["domain_source"] == "guessed"


def test_resolved_domain_of_a_listed_company_returns_that_company(monkeypatch):
    _fake_exa(monkeypatch, ["https://www.ticketmaster.com/"])
    company = asyncio.run(companies.add_company("Ticketmaster Entertainment"))
    assert company["id"] == "ticketmaster" and company["custom"] is False


def test_company_request_rejects_contact_details():
    with pytest.raises(ValueError):
        CompanyRequest(name="jane@mail.example")
    with pytest.raises(ValueError):
        CompanyRequest(name="617-555-0123")
    assert CompanyRequest(name="  23andMe ").name == "23andMe"


def test_added_company_can_be_checked(client, monkeypatch):
    _fake_exa(monkeypatch, ["https://tinder.com/"])

    async def no_breaches(ids):
        return [], []

    async def no_policies(ids):
        return [], []

    from app import main

    monkeypatch.setattr(main.s3_breaches, "breach_timelines", no_breaches)
    monkeypatch.setattr(main.s4_policy, "check_policies", no_policies)

    added = client.post("/api/companies", json={"name": "Tinder"}).json()
    assert added["domains"] == ["tinder.com"]
    assert any(c["id"] == added["id"] for c in client.get("/api/companies").json())
    assert client.post("/api/accounts", json={"companies": [added["id"]]}).status_code == 200
    assert client.post("/api/companies", json={"name": "jane@mail.example"}).status_code == 422
