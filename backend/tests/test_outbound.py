import asyncio

import httpx
import pytest

from app import outbound
from app.outbound import MinimalQueryError, assert_minimal_query


@pytest.mark.parametrize(
    "query",
    [
        "Jane Doe Boston MA",
        '"Jane Doe" Springfield IL',
        "ShopCo data breach",
        "T-Mobile breach 2021",
        "Experian breach March 2023",
    ],
)
def test_name_city_and_company_queries_pass(query):
    assert assert_minimal_query(query) == query


@pytest.mark.parametrize(
    "query",
    [
        "Jane Doe 617-555-0123",
        "Jane Doe (617) 555 0123",
        "Jane Doe +1 617 555 0123",
        "Jane Doe 6175550123",
        "Jane Doe jane.doe+test@example.com",
        "a.b+c@x.co",
        "Jane Doe 123-45-6789",
        "Jane Doe 04/12/1990",
        "Jane Doe 1990-04-12",
        "Jane Doe born April 12, 1990",
        "Jane Doe 12 April 1990",
    ],
)
def test_personal_identifiers_are_blocked(query):
    with pytest.raises(MinimalQueryError):
        assert_minimal_query(query)


def _fake_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"User-Agent": outbound.USER_AGENT}
    )


def test_log_shows_what_was_sent_with_keys_redacted(monkeypatch):
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["key"] = request.headers["x-api-key"]
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(outbound, "_client", _fake_client(handler))
    outbound.clear_log()

    res = asyncio.run(
        outbound.request(
            "exa",
            "POST",
            "https://api.exa.ai/search",
            purpose="test",
            guard=["Jane Doe Boston MA"],
            headers={"x-api-key": "secret-key"},
            json_body={"query": "Jane Doe Boston MA"},
            params={"api_key": "secret-param"},
        )
    )

    assert res.status_code == 200
    assert sent["key"] == "secret-key"  # the real key was sent...
    [entry] = outbound.get_log()
    assert entry.headers["x-api-key"] == outbound.REDACTED  # ...but never logged
    assert "secret-param" not in entry.url
    assert entry.headers["user-agent"] == outbound.USER_AGENT  # real sent headers, not just ours
    assert entry.body == {"query": "Jane Doe Boston MA"}
    assert entry.status == 200 and entry.ms is not None


def test_blocked_query_is_never_sent_or_logged(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a blocked query must not be sent")

    monkeypatch.setattr(outbound, "_client", _fake_client(handler))
    outbound.clear_log()

    with pytest.raises(MinimalQueryError):
        asyncio.run(
            outbound.request(
                "tavily",
                "POST",
                "https://api.tavily.com/search",
                purpose="test",
                guard=["Jane Doe 617-555-0123"],
            )
        )
    assert outbound.get_log() == []


def test_local_calls_are_marked_and_truncated(monkeypatch):
    monkeypatch.setattr(outbound, "_client", _fake_client(lambda r: httpx.Response(200, json={})))
    outbound.clear_log()

    asyncio.run(
        outbound.request(
            "ollama",
            "POST",
            "http://localhost:11434/api/generate",
            purpose="test",
            local=True,
            json_body={"prompt": "x" * 5000},
        )
    )

    [entry] = outbound.get_log()
    assert entry.local
    assert len(entry.body["prompt"]) <= outbound.LOCAL_BODY_CHARS + 1
    assert outbound.get_log(include_local=False) == []


def test_local_flag_is_refused_for_a_remote_host(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a mislabeled remote call must not be sent")

    monkeypatch.setattr(outbound, "_client", _fake_client(handler))
    outbound.clear_log()

    with pytest.raises(ValueError, match="not this machine"):
        asyncio.run(
            outbound.request(
                "ollama", "POST", "https://ollama.example.com/api/generate",
                purpose="test", local=True,
            )
        )
    assert outbound.get_log() == []
