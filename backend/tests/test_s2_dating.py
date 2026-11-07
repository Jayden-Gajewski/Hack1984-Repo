"""Stage 2 tests: every public-by fallback, against a fake Wayback Machine. Offline."""

import asyncio

import httpx
import pytest

from app import outbound
from app.clients import wayback
from app.models import Exposure
from app.stages import s2_dating as s2

ARCHIVED = "https://people.example/jane-example"
NEVER_ARCHIVED = "https://people.example/jane-example-2"
EMPTY_BODY = "https://people.example/jane-example-3"
ARCHIVE_DOWN = "https://people.example/jane-example-4"
TIMES_OUT = "https://people.example/jane-example-5"


def fake_archive(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "web.archive.org"
    url = request.url.params["url"]
    if url == ARCHIVED:
        return httpx.Response(200, json=[["timestamp", "original"], ["20190704083000", url]])
    if url == NEVER_ARCHIVED:
        return httpx.Response(200, json=[])
    if url == EMPTY_BODY:
        return httpx.Response(200, content=b"")
    if url == ARCHIVE_DOWN:
        return httpx.Response(503, text="Service Unavailable")
    raise httpx.ReadTimeout("archive.org is slow today")


def _exposure(url: str, published_date: str | None = None) -> Exposure:
    return Exposure(id=url[-4:], broker="ExampleBroker", url=url, published_date=published_date)


def _run(exposures):
    return asyncio.run(s2.date_exposures(exposures))


@pytest.fixture(autouse=True)
def fake_wayback(monkeypatch):
    monkeypatch.setattr(outbound, "_client", httpx.AsyncClient(transport=httpx.MockTransport(fake_archive)))
    monkeypatch.setattr(wayback, "_slots", asyncio.Semaphore(4))
    outbound.clear_log()


def test_earliest_snapshot_is_the_public_by_date_with_its_link():
    [dated], errors = _run([_exposure(ARCHIVED, published_date="2023-01-01")])
    assert dated.public_by == "2019-07-04"  # Wayback wins over the published date
    assert dated.public_by_source == "wayback"
    assert dated.public_by_evidence_url == f"https://web.archive.org/web/20190704083000/{ARCHIVED}"
    assert errors == []


def test_no_snapshot_falls_back_to_published_date_then_unknown():
    dated, errors = _run([
        _exposure(NEVER_ARCHIVED, published_date="2022-05-01"),
        _exposure(EMPTY_BODY),
    ])
    assert (dated[0].public_by, dated[0].public_by_source) == ("2022-05-01", "published_date")
    assert dated[0].public_by_evidence_url is None
    assert (dated[1].public_by, dated[1].public_by_source) == (None, "unknown")
    assert errors == []  # "never archived" is an answer, not a failure


def test_archive_failures_fall_back_and_are_reported():
    dated, errors = _run([
        _exposure(ARCHIVE_DOWN, published_date="2020-02-02"),
        _exposure(TIMES_OUT),
        _exposure(ARCHIVED),
    ])
    assert [d.public_by_source for d in dated] == ["published_date", "unknown", "wayback"]
    assert len(errors) == 1 and "2 of 3 listings" in errors[0]


def test_every_lookup_is_logged_as_a_wayback_request():
    _run([_exposure(ARCHIVED), _exposure(NEVER_ARCHIVED)])
    log = outbound.get_log()
    assert [e.service for e in log] == ["wayback", "wayback"]
    assert all(not e.local and e.url.startswith("https://web.archive.org/cdx/search/cdx?") for e in log)
    assert all("ExampleBroker listing" in e.purpose for e in log)


def test_a_malformed_timestamp_is_not_turned_into_a_date():
    assert s2.date_from(_exposure(ARCHIVED), "2019").public_by_source == "unknown"
    assert s2.date_from(_exposure(ARCHIVED), None).public_by is None
