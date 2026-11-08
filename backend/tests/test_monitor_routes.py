"""The /api/monitor routes end to end, with HIBP, SMTP and Gemini faked."""

import time

import pytest

from app.clients import hibp
from app.monitor import routes, service
from tests.monitor_fixtures import CATALOG, EMAIL, SHOPCO, use_settings


@pytest.fixture
def api(client, monkeypatch):
    use_settings(monkeypatch)

    async def breaches():
        return CATALOG

    async def add_any(name):
        if name.lower() != "shopco":
            raise LookupError("unknown")
        return SHOPCO

    async def ready():
        return False

    monkeypatch.setattr(hibp, "breaches", breaches)
    monkeypatch.setattr(routes, "add_any_company", add_any)
    monkeypatch.setattr(service, "_local_llm_ready", ready)
    return client


def wait_for_refresh(api):
    for _ in range(100):
        status = api.get("/api/monitor/refresh").json()
        if not status["running"]:
            return status
        time.sleep(0.02)
    raise AssertionError("refresh never finished")


def test_empty_dashboard_shows_configuration_state(api):
    board = api.get("/api/monitor").json()
    assert board["summary"]["monitored_companies"] == 0 and board["incidents"] == []
    assert board["config"] == {"hibp_email_key": False, "smtp": False, "news_search": False,
                               "local_llm": False, "local_llm_model": board["config"]["local_llm_model"]}
    assert board["schedule"]["enabled"] is False


def test_add_company_refresh_and_toggle_a_step(api):
    assert api.post("/api/monitor/companies", json={"name": "ShopCo"}).json()["id"] == "shopco"
    assert api.post("/api/monitor/companies", json={"name": "jane@mail.example"}).status_code == 422  # guard
    started = api.post("/api/monitor/refresh", json={})
    assert started.status_code == 202 and started.json()["running"]
    status = wait_for_refresh(api)
    assert status["new_incidents"] == 2 and status["errors"] == []

    board = api.get("/api/monitor").json()
    # Both are high (2023: names + birthdates + addresses), so the newer one comes first.
    assert [i["id"] for i in board["incidents"]] == ["hibp-shopco2023", "hibp-shopco"]
    incident = board["incidents"][1]
    assert incident["severity"] == "high" and incident["involvement"] == "unconfirmed" and incident["new"]
    assert incident["sources"][0]["label"] == "Have I Been Pwned"

    step = incident["actions"][0]["id"]
    updated = api.post(f"/api/monitor/incidents/hibp-shopco/actions/{step}", json={"done": True}).json()
    assert updated["actions"][0]["done"] is True
    assert api.post("/api/monitor/incidents/hibp-shopco/actions/nope", json={"done": True}).status_code == 404
    assert api.post("/api/monitor/seen", json={}).json() == {"marked": 2}

    assert api.delete("/api/monitor/companies/shopco").json() == {"removed": True}
    assert api.get("/api/monitor").json()["incidents"] == []


def test_email_without_smtp_is_added_but_cannot_be_verified(api):
    added = api.post("/api/monitor/emails", json={"address": EMAIL.upper()})
    assert added.status_code == 200 and added.json()["display"] == EMAIL and not added.json()["verified"]
    email_id = added.json()["id"]
    res = api.post(f"/api/monitor/emails/{email_id}/code")
    assert res.status_code == 503 and "SMTP" in res.json()["detail"]
    assert api.post(f"/api/monitor/emails/{email_id}/verify", json={"code": "123456"}).status_code == 400
    assert api.post(f"/api/monitor/emails/{email_id}/verify", json={"code": "12ab"}).status_code == 422
    assert api.post("/api/monitor/emails", json={"address": "not an email"}).status_code == 422
    assert api.post("/api/monitor/emails", json={"address": EMAIL}).status_code == 400  # duplicate
    assert api.delete(f"/api/monitor/emails/{email_id}").status_code == 200
    assert api.delete(f"/api/monitor/emails/{email_id}").status_code == 404


def test_analyze_needs_gemini(api, monkeypatch):
    api.post("/api/monitor/companies", json={"name": "ShopCo"})
    api.post("/api/monitor/refresh", json={})
    wait_for_refresh(api)

    monkeypatch.setattr(service.gemini, "ready", lambda: False)
    res = api.post("/api/monitor/incidents/hibp-shopco/analyze")
    assert res.status_code == 503 and "GEMINI_API_KEY" in res.json()["detail"]

    async def ask_json(prompt, *, system, purpose):
        return {"summary": "ShopCo had 120,000 accounts exposed in 2021.", "impact": "Reused passwords are at risk.",
                "guidance": "Reset passwords.", "uncertainty": "", "severity_explanation": "High: passwords."}

    monkeypatch.setattr(service.gemini, "ready", lambda: True)
    monkeypatch.setattr(service.analysis.gemini, "ask_json", ask_json)
    explained = api.post("/api/monitor/incidents/hibp-shopco/analyze").json()["analysis"]
    assert explained["summary"].startswith("ShopCo had 120,000") and explained["stale"] is False
    assert api.post("/api/monitor/incidents/nope/analyze").status_code == 404


def test_schedule_route(api):
    saved = api.post("/api/monitor/schedule", json={"enabled": True, "interval_hours": 24, "include_news": False}).json()
    assert saved["enabled"] and saved["next_run"]
    assert api.post("/api/monitor/schedule", json={"enabled": True, "interval_hours": 5}).status_code == 422
