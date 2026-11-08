"""The public site (SITE_URL set): each account's own data, its own origin, daily limits, and the
parts that stay in the local app. Offline: Postgres and the internet are faked."""

import asyncio

import httpx
import pytest

from app import auth, companies, db, main, outbound
from app.config import get_settings

SITE = "https://dossier.example"
ME, MY_SESSION = "00000000-0000-4000-8000-0000000000aa", "test-session"  # conftest's signed-in account
OTHER, OTHER_SESSION = "00000000-0000-4000-8000-0000000000bb", "other-session"
PERSON = {"name": "Jane Example", "city": "Springfield", "state": "IL"}
SAVED = (
    {"name": "Jane Example", "city": "Springfield", "state": "IL"},
    {"scan_id": "s1", "errors": [], "exposures": [{"id": "e1", "broker": "ExampleBroker", "url": "https://people.example/jane"}]},
)


@pytest.fixture
def public(client, monkeypatch):
    """The signed-in test client, with the backend running as the public site and two accounts."""
    monkeypatch.setenv("SITE_URL", SITE)
    get_settings.cache_clear()
    monkeypatch.setattr(db, "session_user_id", lambda token: {MY_SESSION: ME, OTHER_SESSION: OTHER}.get(token))
    yield client
    get_settings.cache_clear()


def as_account(client, session: str) -> None:
    client.cookies.set("h84_session", session)


def test_each_account_has_its_own_current_scan(public, monkeypatch):
    monkeypatch.setattr(db, "latest_scan", lambda: SAVED if auth.current_user() == ME else None)
    assert public.get("/api/scans/latest").status_code == 200

    as_account(public, OTHER_SESSION)
    res = public.post("/api/optout", json={"exposure_id": "e1"}, headers={"Origin": SITE})
    assert res.status_code == 409  # nothing loaded for this account: it can't reach the first one's listings
    assert public.get("/api/leads").json()["exposures"] == []

    as_account(public, MY_SESSION)
    assert [e["id"] for e in public.get("/api/leads").json()["exposures"]] == ["e1"]


def test_each_account_sees_only_its_own_outbound_requests(public, monkeypatch):
    fake = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    monkeypatch.setattr(outbound, "_client", fake)
    outbound.clear_log()
    for account in (ME, OTHER):
        signed_in = auth.CURRENT_USER.set(account)
        try:
            asyncio.run(outbound.request("tavily", "POST", "https://api.tavily.com/search", purpose=f"search for {account}",
                                         json_body={"query": "Jane Example Springfield IL"}))
        finally:
            auth.CURRENT_USER.reset(signed_in)

    assert [e["purpose"] for e in public.get("/api/outbound-log").json()] == [f"search for {ME}"]
    as_account(public, OTHER_SESSION)
    assert [e["purpose"] for e in public.get("/api/outbound-log").json()] == [f"search for {OTHER}"]
    assert public.delete("/api/outbound-log", headers={"Origin": SITE}).status_code == 200  # clears only its own
    as_account(public, MY_SESSION)
    assert len(public.get("/api/outbound-log").json()) == 1


def test_the_public_site_takes_changes_only_from_its_own_pages(public):
    assert public.delete("/api/outbound-log", headers={"Origin": SITE}).status_code == 200
    for other in ("http://localhost:3000", "https://evil.example", "https://dossier.example.evil.example"):
        assert public.delete("/api/outbound-log", headers={"Origin": other}).status_code == 403, other


def test_paid_searches_stop_at_the_daily_limit(public, monkeypatch):
    asked = []
    monkeypatch.setattr(db, "take_search", lambda per_account, total: asked.append((per_account, total)) or False)
    res = public.post("/api/scan", json={**PERSON, "refresh": True}, headers={"Origin": SITE})
    assert res.status_code == 429 and "Try again tomorrow" in res.json()["detail"]
    assert asked == [(20, 500)]  # the default limits, per account and for everyone
    for path, body in (("/api/accounts", {"companies": []}), ("/api/companies", {"name": "ShopCo"})):
        assert public.post(path, json=body, headers={"Origin": SITE}).status_code == 429, path


def test_this_laptop_has_no_daily_limit(client, monkeypatch):
    def must_not_count(*args):
        raise AssertionError("counted a search on this laptop")

    async def find(req):
        return [], []

    monkeypatch.setattr(db, "take_search", must_not_count)
    monkeypatch.setattr(main.s1_exposures, "find_exposures", find)
    assert client.post("/api/scan", json={**PERSON, "refresh": True}).status_code == 200


def test_the_session_cookie_is_https_only_on_the_public_site(public, monkeypatch):
    user = "00000000-0000-4000-8000-0000000000cc"
    monkeypatch.setattr(db, "get_user", lambda email: (user, auth.hash_password("correct-horse-9")))
    monkeypatch.setattr(db, "create_session", lambda user_id, token: None)
    monkeypatch.setattr(db, "user_by_id", lambda user_id: {
        "id": user, "email": "jane@mail.example", "role": "user", "created_at": "2026-11-08T00:00:00+00:00"})
    res = public.post("/api/auth/login", json={"email": "jane@mail.example", "password": "correct-horse-9"},
                      headers={"Origin": SITE})
    assert res.status_code == 200, res.text
    assert "secure" in res.headers["set-cookie"].lower() and "httponly" in res.headers["set-cookie"].lower()


def test_added_companies_belong_to_their_account_on_the_public_site(public, monkeypatch):
    store: dict[str | None, list] = {}
    monkeypatch.setattr(db, "custom_companies", lambda: list(store.get(auth.current_user(), [])))
    monkeypatch.setattr(db, "add_custom_company", lambda company: store.setdefault(auth.current_user(), []).append(company))
    monkeypatch.setattr(db, "take_search", lambda per_account, total: True)

    async def website(name):
        return "shopco-example.com", "search"

    monkeypatch.setattr(companies, "_find_website", website)
    added = public.post("/api/companies", json={"name": "ShopCo Example"}, headers={"Origin": SITE}).json()
    assert added["custom"] and added["id"] in [c["id"] for c in public.get("/api/companies").json()]
    as_account(public, OTHER_SESSION)
    assert not [c for c in public.get("/api/companies").json() if c["custom"]]


def test_threat_monitor_stays_in_the_local_app(public):
    res = public.get("/api/monitor")
    assert res.status_code == 404 and "Threat Monitor" in res.json()["detail"]
    assert public.get("/api/status").json()["public"] is True


def test_the_extension_checks_sites_with_its_users_session_on_the_public_site(public):
    # The automatic check (read_policy false) contacts no site, so nothing here touches the network.
    body = {"origin": "https://www.shopco.example", "read_policy": False, "third_party_hosts": ["connect.facebook.net"]}
    extension = {"Origin": "chrome-extension://abcdef"}
    res = public.post("/api/site-policy", json=body, headers=extension)
    assert res.status_code == 200 and res.json()["status"] == "not_read"
    # Web pages are still refused, the public site's own pages included.
    assert public.post("/api/site-policy", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert public.post("/api/site-policy", json=body, headers={"Origin": SITE}).status_code == 403
    # Signed out, it's refused: the extension's copy from the public site works with an account.
    public.cookies.clear()
    assert public.post("/api/site-policy", json=body, headers=extension).status_code == 401
    assert public.delete("/api/site-policy", headers=extension).status_code == 401


def test_site_url_must_be_https_and_a_hosted_database_needs_tls(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://hack:hack@localhost:5433/hack1984")
    for url in ("http://dossier.example", "dossier.example"):
        monkeypatch.setenv("SITE_URL", url)
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="https"):
            get_settings()

    monkeypatch.setenv("SITE_URL", SITE)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com/dossier")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="sslmode=require"):
        get_settings()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com/dossier?sslmode=require")
    get_settings.cache_clear()
    assert get_settings().public

    monkeypatch.delenv("SITE_URL")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="localhost"):
        get_settings()  # this laptop never uses a hosted database
