import pytest
"""Route tests. Every stage is replaced with a fake, so these stay offline and keep passing
as the real stages get built."""

from app import main
from app.clients import ollama
from app.models import Exposure

PERSON = {"name": "Jane Example", "city": "Springfield", "state": "il", "consent": True}


def _fake_stages(monkeypatch, exposures):
    async def find(req):
        return exposures, []

    async def date(items):
        return items, []

    monkeypatch.setattr(main.s1_exposures, "find_exposures", find)
    monkeypatch.setattr(main.s2_dating, "date_exposures", date)


def test_scan_requires_consent(client):
    res = client.post("/api/scan", json={**PERSON, "consent": False})
    assert res.status_code == 400


def test_scan_rejects_contact_details_typed_into_fields(client):
    res = client.post("/api/scan", json={**PERSON, "name": "Jane 617-555-0123"})
    assert res.status_code == 422
    assert "phone number" in res.text


def test_scan_returns_the_contract_shape(client, monkeypatch):
    exposure = Exposure(id="e1", broker="ExampleBroker", url="https://people.example/jane")
    _fake_stages(monkeypatch, [exposure])

    res = client.post("/api/scan", json=PERSON)

    body = res.json()
    assert res.status_code == 200
    assert set(body) == {"scan_id", "exposures", "errors", "saved_at"}
    assert body["saved_at"] is None  # a fresh scan
    assert body["exposures"][0]["public_by_source"] == "unknown"
    assert main.session.person.state == "IL"
    assert main.session.exposures[0].id == "e1"


def _saved(monkeypatch, calls):
    saved = {"scan_id": "old-scan", "errors": [],
             "exposures": [{"id": "s1", "broker": "ExampleBroker", "url": "https://people.example/jane"}]}

    def find_scan(name, city, state):
        calls.append((name, city, state))
        return "2026-11-06T18:30:00+00:00", saved

    monkeypatch.setattr(main.db, "find_scan", find_scan)


def test_a_person_scanned_before_gets_the_saved_scan_without_searching(client, monkeypatch):
    calls = []
    _saved(monkeypatch, calls)

    async def must_not_run(req):
        raise AssertionError("searched although a saved scan exists")

    monkeypatch.setattr(main.s1_exposures, "find_exposures", must_not_run)
    res = client.post("/api/scan", json=PERSON)

    body = res.json()
    assert res.status_code == 200
    assert body["scan_id"] == "old-scan" and body["saved_at"] == "2026-11-06T18:30:00+00:00"
    assert calls == [("Jane Example", "Springfield", "IL")]
    assert main.session.exposures[0].id == "s1"  # opt-outs and re-scan work on the loaded scan


def test_refresh_runs_a_fresh_scan_even_when_one_is_saved(client, monkeypatch):
    calls = []
    _saved(monkeypatch, calls)
    _fake_stages(monkeypatch, [Exposure(id="e1", broker="ExampleBroker", url="https://people.example/jane")])

    body = client.post("/api/scan", json={**PERSON, "refresh": True}).json()
    assert calls == [] and body["saved_at"] is None and body["exposures"][0]["id"] == "e1"


def test_saved_scans_still_need_consent(client, monkeypatch):
    _saved(monkeypatch, [])
    assert client.post("/api/scan", json={**PERSON, "consent": False}).status_code == 400


def test_postgres_down_means_a_fresh_scan(client, monkeypatch):
    def down(*args):
        raise OSError("connection refused")

    monkeypatch.setattr(main.db, "find_scan", down)
    _fake_stages(monkeypatch, [Exposure(id="e1", broker="ExampleBroker", url="https://people.example/jane")])
    body = client.post("/api/scan", json=PERSON).json()
    assert body["saved_at"] is None and body["exposures"][0]["id"] == "e1"


def test_a_missing_or_broken_stage_becomes_an_error_string(client, monkeypatch):
    async def not_built(req):
        raise NotImplementedError

    async def broken(req):
        raise RuntimeError("boom")

    monkeypatch.setattr(main.s1_exposures, "find_exposures", not_built)
    res = client.post("/api/scan", json=PERSON)
    assert res.status_code == 200
    assert res.json()["errors"] == ["Stage 1 (find exposures) is not implemented yet."]

    monkeypatch.setattr(main.s1_exposures, "find_exposures", broken)
    res = client.post("/api/scan", json=PERSON)
    assert res.json()["errors"] == ["Stage 1 (find exposures) failed: boom"]


def test_status_shows_key_presence_not_values(client, monkeypatch):
    async def fake_status():
        return True, False

    monkeypatch.setattr(ollama, "status", fake_status)
    body = client.get("/api/status").json()
    assert body["ollama_running"] is True
    assert body["model_pulled"] is False
    assert body["database"] is False
    assert set(body["keys"]) == {"exa", "tavily"}
    assert all(isinstance(v, bool) for v in body["keys"].values())


def test_optout_needs_a_scan_first(client):
    assert client.post("/api/optout", json={"exposure_id": "e1"}).status_code == 409


def test_accounts_rejects_unknown_companies(client):
    assert client.post("/api/accounts", json={"companies": ["nope"]}).status_code == 400


def test_outbound_log_endpoint(client):
    res = client.get("/api/outbound-log?include_local=false")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


@pytest.mark.parametrize(
    "person",
    [
        {"city": "12 Elm St Springfield"},  # street address
        {"city": "Springfield 62701"},  # ZIP code
        {"name": "Jane Example 2"},
        {"state": "1L"},
    ],
)
def test_scan_rejects_digits_and_bad_state(client, person):
    body = {"name": "Jane Example", "city": "Springfield", "state": "IL", "consent": True, **person}
    assert client.post("/api/scan", json=body).status_code == 422


def test_requests_for_other_hosts_are_refused(client):
    assert client.get("/api/status", headers={"Host": "attacker.example"}).status_code == 400
