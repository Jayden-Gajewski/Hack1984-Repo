"""Local accounts, with Postgres replaced by an in-memory fake. Offline."""

import re
import socket
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import pytest

from app import auth, db


class FakeAccounts:
    """The account functions of db.py over dicts, with the same rules: the first account is the
    admin, the last admin can't be demoted or removed, a reset code works once and expires, and a
    password change ends the account's other sessions."""

    def __init__(self):
        self.users: dict[str, dict] = {}  # email -> {id, email, role, created_at, password_hash}
        self.sessions: dict[str, str] = {}  # token -> user id
        self.resets: dict[str, tuple[str, datetime]] = {}  # code -> (user id, expires at)
        self.claimed: list[str] = []

    def _by_id(self, user_id):
        return next((u for u in self.users.values() if u["id"] == user_id), None)

    @staticmethod
    def _public(u):
        return {k: u[k] for k in ("id", "email", "role", "created_at")} if u else None

    def create_user(self, email, password_hash):
        if email in self.users:
            return False
        role = "user" if self.users else "admin"
        created = datetime(2026, 11, 7, tzinfo=timezone.utc) + timedelta(minutes=len(self.users))
        self.users[email] = {
            "id": str(uuid.uuid4()), "email": email, "role": role,
            "created_at": created.isoformat(), "password_hash": password_hash,
        }  # fmt: skip
        return True

    def get_user(self, email):
        u = self.users.get(email)
        return (u["id"], u["password_hash"]) if u else None

    def user_by_id(self, user_id):
        return self._public(self._by_id(user_id))

    def create_session(self, user_id, token):
        self.sessions[token] = user_id

    def session_user(self, token):
        return self.user_by_id(self.sessions.get(token))

    def session_user_id(self, token):
        return self.sessions.get(token)

    def delete_session(self, token):
        self.sessions.pop(token, None)

    def set_password(self, email, password_hash, keep_token=None):
        u = self.users.get(email)
        if not u:
            return False
        u["password_hash"] = password_hash
        self.sessions = {t: i for t, i in self.sessions.items() if i != u["id"] or t == keep_token}
        self.resets = {c: r for c, r in self.resets.items() if r[0] != u["id"]}
        return True

    def claim_unowned_scans(self, user_id):
        self.claimed.append(user_id)
        return 0

    def list_users(self):
        return [self._public(u) for u in self.users.values()]

    def _last_admin(self, user_id):
        admins = [u for u in self.users.values() if u["role"] == "admin"]
        return len(admins) == 1 and admins[0]["id"] == user_id

    def set_role(self, user_id, role):
        if role != "admin" and self._last_admin(user_id):
            raise ValueError(db.LAST_ADMIN)
        u = self._by_id(user_id)
        if u:
            u["role"] = role
        return self._public(u)

    def delete_user(self, user_id):
        if self._last_admin(user_id):
            raise ValueError(db.LAST_ADMIN)
        u = self._by_id(user_id)
        if not u:
            return False
        del self.users[u["email"]]
        self.sessions = {t: i for t, i in self.sessions.items() if i != user_id}
        return True

    def create_reset(self, user_id, code, minutes):
        self.resets = {c: r for c, r in self.resets.items() if r[0] != user_id}
        expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self.resets[code] = (user_id, expires)
        return expires.isoformat()

    def use_reset(self, code, email):
        found = self.resets.get(code)
        u = self.users.get(email)
        if not found or not u or found[0] != u["id"] or found[1] <= datetime.now(timezone.utc):
            return False
        del self.resets[code]
        return True


@pytest.fixture
def accounts(monkeypatch):
    fake = FakeAccounts()
    for name in (
        "create_user", "get_user", "user_by_id", "create_session", "session_user", "session_user_id",
        "delete_session", "set_password", "claim_unowned_scans", "list_users", "set_role", "delete_user",
        "create_reset", "use_reset",
    ):  # fmt: skip
        monkeypatch.setattr(db, name, getattr(fake, name))
    monkeypatch.setattr(auth, "_failures", defaultdict(deque))  # throttling starts fresh
    return fake


SIGNUP = {"email": "Jane@Mail.example", "password": "correct horse"}
SAM = {"email": "sam@mail.example", "password": "battery staple"}


def signup(client, creds):
    res = client.post("/api/auth/signup", json=creds)
    assert res.status_code == 200, res.text
    return res.json()


def login(client, creds):
    return client.post("/api/auth/login", json=creds)


def test_signup_sets_session_and_me_returns_user(client, accounts):
    res = client.post("/api/auth/signup", json=SIGNUP)
    assert res.status_code == 200
    assert "h84_session" in res.cookies
    me = client.get("/api/auth/me").json()
    assert me["email"] == "jane@mail.example"
    assert me["role"] == "admin" and me["id"] and me["created_at"]
    assert accounts.users["jane@mail.example"]["password_hash"].startswith("scrypt$")  # never stored in plain text


def test_first_account_is_admin_and_later_ones_are_users(client, accounts):
    assert signup(client, SIGNUP)["role"] == "admin"
    assert signup(client, SAM)["role"] == "user"
    assert login(client, SIGNUP).json()["role"] == "admin"


def test_signup_offers_old_saved_scans_to_the_new_account(client, accounts):
    client.post("/api/auth/signup", json=SIGNUP)
    assert accounts.claimed == [accounts.users["jane@mail.example"]["id"]]  # db.claim_unowned_scans: first account only


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


def test_repeated_failed_logins_are_throttled(client, accounts):
    signup(client, SIGNUP)
    signup(client, SAM)
    for _ in range(auth.MAX_FAILURES):
        assert login(client, {**SIGNUP, "password": "wrong password"}).status_code == 401
    assert login(client, SIGNUP).status_code == 429  # even the right password waits
    assert login(client, SAM).status_code == 200  # other accounts aren't affected


def test_an_unknown_email_is_checked_like_a_wrong_password(client, accounts, monkeypatch):
    checked = []
    monkeypatch.setattr(auth, "verify_password", lambda password, stored: checked.append(stored) or False)
    assert login(client, {"email": "nobody@mail.example", "password": "whatever1"}).status_code == 401
    assert checked == [auth.DUMMY_HASH]  # same scrypt work, so timing doesn't reveal which emails exist


def test_change_password_ends_other_sessions_but_not_this_one(client, accounts):
    signup(client, SIGNUP)
    other_device = next(t for t in accounts.sessions)
    login(client, SIGNUP)  # this browser's session
    wrong = client.post("/api/auth/password", json={"current_password": "nope nope", "new_password": "new password"})
    assert wrong.status_code == 400
    res = client.post("/api/auth/password", json={"current_password": "correct horse", "new_password": "new password"})
    assert res.status_code == 200
    assert other_device not in accounts.sessions
    assert client.get("/api/auth/me").status_code == 200  # still signed in here
    client.post("/api/auth/logout")
    assert login(client, SIGNUP).status_code == 401
    assert login(client, {**SIGNUP, "password": "new password"}).status_code == 200


def test_change_password_checks_the_new_one_and_needs_a_session(client, accounts):
    signup(client, SIGNUP)
    short = client.post("/api/auth/password", json={"current_password": "correct horse", "new_password": "short"})
    assert short.status_code == 422
    client.cookies.clear()
    res = client.post("/api/auth/password", json={"current_password": "correct horse", "new_password": "new password"})
    assert res.status_code == 401


def test_only_admins_manage_accounts(client, accounts):
    signup(client, SIGNUP)
    sam = signup(client, SAM)  # signed in as sam, a user
    jane_id = accounts.users["jane@mail.example"]["id"]
    assert client.get("/api/admin/users").status_code == 403
    assert client.patch(f"/api/admin/users/{sam['id']}", json={"role": "admin"}).status_code == 403
    assert client.delete(f"/api/admin/users/{jane_id}").status_code == 403
    assert client.post(f"/api/admin/users/{jane_id}/reset-code").status_code == 403

    login(client, SIGNUP)
    users = client.get("/api/admin/users").json()
    assert [u["email"] for u in users] == ["jane@mail.example", "sam@mail.example"]
    assert all("password_hash" not in u for u in users)
    promoted = client.patch(f"/api/admin/users/{sam['id']}", json={"role": "admin"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "admin"


def test_the_last_admin_cant_be_demoted_or_removed(client, accounts):
    jane = signup(client, SIGNUP)
    sam = signup(client, SAM)
    login(client, SIGNUP)
    demote = client.patch(f"/api/admin/users/{jane['id']}", json={"role": "user"})
    assert demote.status_code == 409 and "only admin" in demote.json()["detail"]
    assert client.delete(f"/api/admin/users/{jane['id']}").status_code == 409  # not your own account
    client.patch(f"/api/admin/users/{sam['id']}", json={"role": "admin"})
    assert client.patch(f"/api/admin/users/{jane['id']}", json={"role": "user"}).status_code == 200
    assert client.get("/api/admin/users").status_code == 403  # jane is a user now


def test_removing_an_account_ends_its_sessions(client, accounts):
    signup(client, SIGNUP)
    sam = signup(client, SAM)
    sam_token = next(t for t, i in accounts.sessions.items() if i == sam["id"])
    login(client, SIGNUP)
    assert client.delete(f"/api/admin/users/{sam['id']}").status_code == 200
    assert sam_token not in accounts.sessions
    assert client.delete(f"/api/admin/users/{sam['id']}").status_code == 404
    assert client.delete("/api/admin/users/not-a-uuid").status_code == 404


def test_forgotten_password_reset_with_an_admin_code(client, accounts):
    signup(client, SIGNUP)
    sam = signup(client, SAM)
    sam_token = next(t for t, i in accounts.sessions.items() if i == sam["id"])
    login(client, SIGNUP)
    issued = client.post(f"/api/admin/users/{sam['id']}/reset-code").json()
    assert issued["email"] == "sam@mail.example" and re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}", issued["code"])

    client.cookies.clear()  # sam, signed out, on the login screen
    typed = issued["code"].lower().replace("-", " ")
    wrong_email = client.post("/api/auth/reset", json={"email": SIGNUP["email"], "code": typed, "new_password": "fresh password"})
    assert wrong_email.status_code == 400
    res = client.post("/api/auth/reset", json={"email": "SAM@mail.example", "code": typed, "new_password": "fresh password"})
    assert res.status_code == 200 and res.json()["email"] == "sam@mail.example"
    assert client.get("/api/auth/me").json()["email"] == "sam@mail.example"  # signed in
    assert sam_token not in accounts.sessions  # the old session ended
    again = client.post("/api/auth/reset", json={"email": SAM["email"], "code": typed, "new_password": "other password"})
    assert again.status_code == 400  # a code works once
    assert login(client, {**SAM, "password": "fresh password"}).status_code == 200


def test_reset_codes_replace_earlier_ones_and_expire(client, accounts):
    signup(client, SIGNUP)
    sam = signup(client, SAM)
    login(client, SIGNUP)
    first = client.post(f"/api/admin/users/{sam['id']}/reset-code").json()["code"]
    second = client.post(f"/api/admin/users/{sam['id']}/reset-code").json()["code"]
    body = {"email": SAM["email"], "new_password": "fresh password"}
    assert client.post("/api/auth/reset", json={**body, "code": first}).status_code == 400
    user_id, _ = accounts.resets[second]
    accounts.resets[second] = (user_id, datetime.now(timezone.utc) - timedelta(seconds=1))
    assert client.post("/api/auth/reset", json={**body, "code": second}).status_code == 400


def test_guessing_reset_codes_is_throttled(client, accounts):
    signup(client, SIGNUP)
    body = {"email": SIGNUP["email"], "code": "AAAA-BBBB-CCCC", "new_password": "fresh password"}
    for _ in range(auth.MAX_FAILURES):
        assert client.post("/api/auth/reset", json=body).status_code == 400
    assert client.post("/api/auth/reset", json=body).status_code == 429


def test_reset_code_helpers():
    code = auth.new_reset_code()
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}", code)
    assert not set(code) & set("01OIL")  # nothing that reads like another character
    assert auth.normalize_code(" k7qm 2xrp9htd ") == "K7QM-2XRP-9HTD"


class RecordingConn:
    """Stands in for a psycopg connection and keeps every query's parameters."""

    def __init__(self):
        self.params: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def transaction(self):
        return self

    def execute(self, sql, params=()):
        self.params.append(tuple(params))
        return self

    def fetchone(self):
        return (datetime(2026, 11, 7, tzinfo=timezone.utc),)


def test_the_database_only_ever_sees_hashes_of_tokens_and_codes(monkeypatch):
    conn = RecordingConn()
    monkeypatch.setattr(db, "connect", lambda: conn)
    user_id = str(uuid.uuid4())
    db.create_session(user_id, "raw-session-token")
    db.session_user_id("raw-session-token")
    db.delete_session("raw-session-token")
    db.create_reset(user_id, "K7QM-2XRP-9HTD", 30)
    db.use_reset("K7QM-2XRP-9HTD", "jane@mail.example")
    sent = [str(p) for params in conn.params for p in params]
    assert "raw-session-token" not in sent and "K7QM-2XRP-9HTD" not in sent
    assert auth.token_hash("raw-session-token") in sent
    assert auth.token_hash("K7QM-2XRP-9HTD") in sent


def test_personal_data_routes_need_a_session(client):
    client.cookies.clear()
    for method, path in [
        ("GET", "/api/scans/latest"), ("POST", "/api/scan"), ("GET", "/api/outbound-log"),
        ("DELETE", "/api/outbound-log"), ("GET", "/api/aliases"), ("GET", "/api/companies"),
        ("POST", "/api/accounts"), ("GET", "/api/leads"), ("GET", "/api/inbox/check"), ("GET", "/api/footprint"),
        ("GET", "/api/admin/users"), ("POST", "/api/auth/password"),
    ]:  # fmt: skip
        res = client.request(method, path, json={})
        assert res.status_code == 401, (method, path, res.status_code)
    assert client.get("/api/brokers").status_code == 200  # reference data stays open
    assert client.get("/api/auth/me").status_code == 401  # answers for itself


def test_changes_must_come_from_this_laptop(client):
    other_site = client.delete("/api/outbound-log", headers={"Origin": "https://evil.example"})
    assert other_site.status_code == 403
    assert client.post("/api/auth/login", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/auth/reset", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.delete("/api/outbound-log", headers={"Origin": "http://localhost:3000"}).status_code == 200
    assert client.get("/api/outbound-log", headers={"Origin": "https://evil.example"}).status_code == 200  # reads: SameSite


def test_this_laptops_wifi_address_counts_as_this_laptop(client, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("192.168.0.20", 0))])
    assert client.delete("/api/outbound-log", headers={"Origin": "http://192.168.0.20:3001"}).status_code == 200
    # Another device on the same network is still another site.
    assert client.delete("/api/outbound-log", headers={"Origin": "http://192.168.0.21:3001"}).status_code == 403


def test_saved_scans_are_looked_up_for_the_signed_in_account(client, monkeypatch):
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
