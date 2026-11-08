"""Local accounts, with Postgres replaced by dicts. Offline."""

import pytest

from app import db


@pytest.fixture
def accounts(monkeypatch):
    users: dict[str, tuple[str, str]] = {}  # email -> (id, password_hash)
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
    return users


SIGNUP = {"email": "Jane@Mail.example", "password": "correct horse"}


def test_signup_sets_session_and_me_returns_user(client, accounts):
    res = client.post("/api/auth/signup", json=SIGNUP)
    assert res.status_code == 200
    assert "h84_session" in res.cookies
    assert client.get("/api/auth/me").json() == {"email": "jane@mail.example"}
    assert accounts["jane@mail.example"][1].startswith("scrypt$")  # never stored in plain text


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


def test_bad_input_gets_a_readable_message(client, accounts):
    res = client.post("/api/auth/signup", json={**SIGNUP, "password": "short"})
    assert res.status_code == 422
    assert "at least 8 characters" in res.text
