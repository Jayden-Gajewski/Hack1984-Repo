import asyncio
import json

import httpx
import pytest

from app import outbound
from app.clients import exa
from app.config import Settings
from app.outbound import MinimalQueryError


def _settings() -> Settings:
    return Settings(
        exa_api_key="test-key",
        tavily_api_key="",
        ollama_url="http://localhost:11434",
        ollama_model="llama3.1:8b",
        alias_domain="alias.local",
        database_url="postgresql://hack:hack@localhost:5432/hack1984",
    )


@pytest.fixture
def sent(monkeypatch):
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"url": "https://a.example", "highlights": ["x", "y"]}]})

    monkeypatch.setattr(exa, "get_settings", _settings)
    monkeypatch.setattr(outbound, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return bodies


def test_default_request_is_query_type_and_highlights_only(sent):
    asyncio.run(exa.search("Jane Doe Boston MA", purpose="test"))
    assert sent == [{"query": "Jane Doe Boston MA", "type": "auto", "contents": {"highlights": True}}]


def test_optional_fields_are_sent_only_when_given(sent):
    asyncio.run(
        exa.search(
            "ShopCo data breach",
            purpose="test",
            objective="News or regulator notices about this company's data breach; pull the date.",
            start_published_date="2020-01-01",
        )
    )
    [body] = sent
    assert body["objective"].startswith("News or regulator")
    assert body["startPublishedDate"] == "2020-01-01"
    assert "numResults" not in body and "includeDomains" not in body and "category" not in body


def test_objective_is_guarded_like_the_query(sent):
    with pytest.raises(MinimalQueryError):
        asyncio.run(exa.search("Jane Doe Boston MA", purpose="test", objective="pages with 617-555-0123"))
    assert sent == []  # nothing left the machine


def test_snippet_joins_highlights():
    assert exa.snippet({"highlights": ["a", "b"]}) == "a\nb"
    assert exa.snippet({}) == ""
