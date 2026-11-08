"""Local accounts, with Postgres replaced by dicts. Offline."""

import pytest

from app import db


class Accounts(dict):
    """email -> (id, password_hash), plus the account ids that claimed old saved scans."""

    claimed: list[str]


@pytest.fixture
def accounts(monkeypatch):
    users = Accounts()
    sessions: dict[str, str] = {}  # token -> email

    def create_user(email, password_hash):
        if email in users:
            return False
        users[email] = (f"id-{len(users)}", password_hash)
        return True

    def create_session(user_id, token):
        sessions[token] = next(e for e, u in users.items() if u[0] == user_id)

    monkeypatch.setattr(db, "create_user", create_user)
    monkeypatch.setattr(db, "get_user", users.get)
    monkeypatch.setattr(db, "create_session", create_session)
    monkeypatch.setattr(db, "session_user", sessions.get)
    monkeypatch.setattr(db, "delete_session", lambda t: sessions.pop(t, None))
    users.claimed = []
    monkeypatch.setattr(db, "claim_unowned_scans", lambda user_id: users.claimed.append(user_id) or 0)
    return users


SIGNUP = {"email": "Jane@Mail.example", "password": "correct horse"}


def test_signup_sets_session_and_me_returns_user(client, accounts):
    res = client.post("/api/auth/signup", json=SIGNUP)
    assert res.status_code == 200
    assert "h84_session" in res.cookies
    assert client.get("/api/auth/me").json() == {"email": "jane@mail.example"}
    assert accounts["jane@mail.example"][1].startswith("scrypt$")  # never stored in plain text


def test_signup_offers_old_saved_scans_to_the_new_account(client, accounts):
    client.post("/api/auth/signup", json=SIGNUP)
    assert accounts.claimed == [accounts["jane@mail.example"][0]]  # db.claim_unowned_scans: first account only


def test_duplicate_signup_is_rejected(client, accounts):
    client.post("/api/auth/signup", json=SIGNUP)
    assert client.post("/api/auth/signup", json=SIGNUP).status_code == 409


def test_login_checks_password(client, accounts):
    client.post("/api/auth/signup", json=SIGNUP)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", json={"email": SIGNUP["email"], "password": "wrong password"})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"email": SIGNUP["email"], "password": "correct horse"})
    assert good.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_personal_data_routes_need_a_session(client):
    client.cookies.clear()
    for method, path in [
        ("GET", "/api/scans/latest"), ("POST", "/api/scan"), ("GET", "/api/outbound-log"),
        ("DELETE", "/api/outbound-log"), ("GET", "/api/aliases"), ("GET", "/api/companies"),
        ("POST", "/api/accounts"), ("GET", "/api/leads"), ("GET", "/api/inbox/check"), ("GET", "/api/footprint"),
    ]:  # fmt: skip
        res = client.request(method, path, json={})
        assert res.status_code == 401, (method, path, res.status_code)
    assert client.get("/api/brokers").status_code == 200  # reference data stays open
    assert client.get("/api/auth/me").status_code == 401  # answers for itself


def test_changes_must_come_from_this_laptop(client):
    other_site = client.delete("/api/outbound-log", headers={"Origin": "https://evil.example"})
    assert other_site.status_code == 403
    assert client.post("/api/auth/login", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.delete("/api/outbound-log", headers={"Origin": "http://localhost:3000"}).status_code == 200
    assert client.get("/api/outbound-log", headers={"Origin": "https://evil.example"}).status_code == 200  # reads: SameSite


def test_saved_scans_are_looked_up_for_the_signed_in_account(client, monkeypatch):
    from app import auth

    from .conftest import TEST_USER

    seen = []
    monkeypatch.setattr(db, "latest_scan", lambda: seen.append(auth.current_user()))  # returns None: no scan
    assert client.get("/api/scans/latest").status_code == 404
    assert seen == [TEST_USER]  # db.find_scan / save_scan / latest_scan filter on it
    assert auth.current_user() is None  # and it doesn't leak past the request


def test_bad_input_gets_a_readable_message(client, accounts):
    res = client.post("/api/auth/signup", json={**SIGNUP, "password": "short"})
    assert res.status_code == 422
    assert "at least 8 characters" in res.text
