"""Accounts: sign-up, login, roles and per-user data. Offline: Postgres is replaced by an
in-memory FakeDB with the same functions, and the real auth.require_user runs."""

import itertools

import pytest
from fastapi.testclient import TestClient

from app import auth, db, main, outbound
from app.context import current_user_id
from app.models import Exposure, ScanRequest


class FakeDB:
    def __init__(self):
        self.users: dict[int, dict] = {}
        self.hashes: dict[int, str] = {}
        self.sessions: dict[str, int] = {}
        self.resets: dict[str, tuple[int, bool]] = {}  # code hash -> (user id, expired)
        self.ids = itertools.count(1)

    def create_user(self, username, password_hash):
        if any(u["username"] == username for u in self.users.values()):
            return None
        uid = next(self.ids)
        role = "user" if self.users else "admin"
        self.users[uid] = {"id": uid, "username": username, "role": role, "created_at": "2026-11-07T00:00:00+00:00"}
        self.hashes[uid] = password_hash
        return dict(self.users[uid])

    def user_with_hash(self, username):
        user = next((u for u in self.users.values() if u["username"] == username), None)
        return (dict(user), self.hashes[user["id"]]) if user else None

    def create_session(self, token_hash, user_id, days):
        self.sessions[token_hash] = user_id

    def user_for_session(self, token_hash):
        uid = self.sessions.get(token_hash)
        return dict(self.users[uid]) if uid in self.users else None

    def delete_session(self, token_hash):
        self.sessions.pop(token_hash, None)

    def list_users(self):
        return [dict(u) for u in self.users.values()]

    def _last_admin(self, uid):
        admins = [u for u in self.users.values() if u["role"] == "admin"]
        return len(admins) == 1 and admins[0]["id"] == uid

    def set_role(self, uid, role):
        if uid not in self.users:
            return None
        if role != "admin" and self._last_admin(uid):
            raise ValueError("That's the only admin. Make someone else an admin first.")
        self.users[uid]["role"] = role
        return dict(self.users[uid])

    def password_hash_for(self, uid):
        return self.hashes.get(uid)

    def set_password(self, uid, password_hash, keep_session=None):
        self.hashes[uid] = password_hash
        self.sessions = {t: u for t, u in self.sessions.items() if u != uid or t == keep_session}
        self.resets = {c: r for c, r in self.resets.items() if r[0] != uid}

    def create_reset(self, code_hash, uid, minutes):
        self.resets = {c: r for c, r in self.resets.items() if r[0] != uid}
        self.resets[code_hash] = (uid, False)
        return "2026-11-07T23:59:00+00:00"

    def use_reset(self, code_hash, username):
        found = self.resets.get(code_hash)
        if not found or found[1] or self.users.get(found[0], {}).get("username") != username:
            return None
        del self.resets[code_hash]
        return found[0]

    def delete_user(self, uid):
        if self._last_admin(uid):
            raise ValueError("That's the only admin. Make someone else an admin first.")
        return self.users.pop(uid, None) is not None


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    for name in ("create_user", "user_with_hash", "create_session", "user_for_session",
                 "delete_session", "list_users", "set_role", "delete_user",
                 "password_hash_for", "set_password", "create_reset", "use_reset"):
        monkeypatch.setattr(db, name, getattr(fake, name))
    monkeypatch.setattr(db, "init_schema", lambda: None)
    monkeypatch.setattr(db, "save_scan", lambda *args: None)
    monkeypatch.setattr(db, "find_scan", lambda *args: None)
    monkeypatch.setattr(db, "ping", lambda: False)
    monkeypatch.setattr(main, "session", main._UserSessions())  # the real per-user sessions
    main._sessions.clear()
    auth._failures.clear()
    main.app.dependency_overrides.pop(auth.require_user, None)
    outbound.clear_log()
    return fake


def new_client():
    return TestClient(main.app, base_url="http://localhost")


def signup(client, username, password="correct horse"):
    return client.post("/api/auth/signup", json={"username": username, "password": password})


# ---------- sign-up and login ----------


def test_first_account_is_admin_and_later_ones_are_users(fake_db):
    with new_client() as a, new_client() as b:
        first = signup(a, "Alice")
        assert first.status_code == 200
        assert first.json()["role"] == "admin" and first.json()["username"] == "alice"
        assert signup(b, "bob").json()["role"] == "user"
        assert a.get("/api/auth/me").json()["username"] == "alice"  # the cookie logs you in
        assert b.get("/api/auth/me").json()["username"] == "bob"


def test_signup_rules(fake_db):
    with new_client() as c:
        assert signup(c, "alice").status_code == 200
        assert signup(c, "ALICE").status_code == 409  # usernames are case-insensitive
        assert signup(c, "carol", password="short").status_code == 422
        assert signup(c, "carol@example.com").status_code == 422  # a username, not an email


def test_cookie_is_httponly_and_only_a_token_hash_is_stored(fake_db):
    with new_client() as c:
        res = signup(c, "alice")
        cookie = res.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        token = c.cookies.get(auth.COOKIE)
        assert token and token not in fake_db.sessions
        assert auth.token_hash(token) in fake_db.sessions
        assert "correct horse" not in fake_db.hashes[1]


def test_login_logout_and_wrong_password(fake_db):
    with new_client() as c:
        signup(c, "alice")
        c.post("/api/auth/logout")
        assert c.get("/api/auth/me").status_code == 401
        assert c.get("/api/leads").status_code == 401
        assert c.post("/api/auth/login", json={"username": "alice", "password": "wrong password"}).status_code == 401
        assert c.post("/api/auth/login", json={"username": "nobody1", "password": "whatever1"}).status_code == 401
        assert c.post("/api/auth/login", json={"username": "Alice", "password": "correct horse"}).status_code == 200
        assert c.get("/api/auth/me").json()["username"] == "alice"


def test_repeated_failed_logins_are_throttled(fake_db):
    with new_client() as c:
        signup(c, "alice")
        for _ in range(auth.MAX_FAILURES):
            c.post("/api/auth/login", json={"username": "alice", "password": "wrong password"})
        res = c.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
        assert res.status_code == 429


def test_password_hashing():
    stored = auth.hash_password("correct horse")
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert auth.verify_password("correct horse", stored)
    assert not auth.verify_password("Correct horse", stored)
    assert not auth.verify_password("x", "garbage")
    assert auth.hash_password("same") != auth.hash_password("same")  # salted


# ---------- what needs a login ----------


def test_everything_but_status_and_auth_needs_a_login(fake_db):
    with new_client() as c:
        assert c.get("/api/status").status_code == 200
        for method, path in [("GET", "/api/leads"), ("GET", "/api/outbound-log"), ("GET", "/api/scans/latest"),
                             ("GET", "/api/companies"), ("GET", "/api/admin/users")]:
            assert c.request(method, path).status_code == 401, path
        res = c.post("/api/scan", json={"name": "Jane Example", "city": "Springfield", "state": "IL", "consent": True})
        assert res.status_code == 401


# ---------- roles ----------


def test_only_admins_manage_users(fake_db):
    with new_client() as admin, new_client() as user:
        signup(admin, "alice")
        signup(user, "bob")
        assert user.get("/api/admin/users").status_code == 403
        assert user.patch("/api/admin/users/2", json={"role": "admin"}).status_code == 403
        assert [u["username"] for u in admin.get("/api/admin/users").json()] == ["alice", "bob"]
        assert admin.patch("/api/admin/users/2", json={"role": "admin"}).json()["role"] == "admin"
        assert user.get("/api/admin/users").status_code == 200  # bob is an admin now
        assert admin.patch("/api/admin/users/2", json={"role": "owner"}).status_code == 422


def test_the_last_admin_cant_be_demoted_or_deleted(fake_db):
    with new_client() as admin, new_client() as user:
        signup(admin, "alice")
        signup(user, "bob")
        assert admin.patch("/api/admin/users/1", json={"role": "user"}).status_code == 409
        assert admin.delete("/api/admin/users/1").status_code == 409  # can't delete yourself
        assert admin.delete("/api/admin/users/2").json() == {"deleted": True}
        assert user.get("/api/auth/me").status_code == 401  # deleted users are logged out
        assert admin.delete("/api/admin/users/99").status_code == 404


# ---------- per-user data ----------


def test_each_user_has_their_own_scan_session(fake_db, monkeypatch):
    async def find(req):
        return [Exposure(id=f"e-{req.name.split()[0].lower()}", broker="ExampleBroker",
                         url="https://people.example/x")], []

    async def date(items):
        return items, []

    monkeypatch.setattr(main.s1_exposures, "find_exposures", find)
    monkeypatch.setattr(main.s2_dating, "date_exposures", date)
    with new_client() as a, new_client() as b:
        signup(a, "alice")
        signup(b, "bob")
        a.post("/api/scan", json={"name": "Jane Example", "city": "Springfield", "state": "IL", "consent": True})
        assert b.post("/api/rescan").status_code == 409  # bob hasn't scanned: alice's scan isn't his
        assert b.post("/api/optout", json={"exposure_id": "e-jane"}).status_code == 409
        b.post("/api/scan", json={"name": "Sam Sample", "city": "Dayton", "state": "OH", "consent": True})
        assert [e["id"] for e in a.get("/api/leads").json()["exposures"]] == ["e-jane"]
        assert [e["id"] for e in b.get("/api/leads").json()["exposures"]] == ["e-sam"]
        a.post("/api/auth/logout")
        assert 1 not in main._sessions  # logging out forgets the in-memory scan


def test_users_see_only_their_own_outbound_log(fake_db):
    with new_client() as admin, new_client() as user:
        signup(admin, "alice")
        signup(user, "bob")
        for uid, purpose in [(1, "alice's search"), (2, "bob's search")]:
            token = current_user_id.set(uid)
            outbound._log.append(outbound.OutboundEntry(
                id=uid, time="t", service="tavily", purpose=purpose, local=False, method="POST",
                url="https://api.tavily.com/search", headers={}, user_id=current_user_id.get()))
            current_user_id.reset(token)
        assert [e["purpose"] for e in user.get("/api/outbound-log").json()] == ["bob's search"]
        assert len(admin.get("/api/outbound-log").json()) == 2
        user.delete("/api/outbound-log")
        assert [e["purpose"] for e in admin.get("/api/outbound-log").json()] == ["alice's search"]


# ---------- passwords ----------


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_change_password_logs_out_other_sessions_but_not_this_one(fake_db):
    with new_client() as laptop, new_client() as phone:
        signup(laptop, "alice")
        login(phone, "alice", "correct horse")
        bad = laptop.post("/api/auth/password", json={"current_password": "wrong", "new_password": "new password 1"})
        assert bad.status_code == 401
        short = laptop.post("/api/auth/password", json={"current_password": "correct horse", "new_password": "short"})
        assert short.status_code == 422
        ok = laptop.post("/api/auth/password", json={"current_password": "correct horse", "new_password": "new password 1"})
        assert ok.json() == {"changed": True}
        assert laptop.get("/api/auth/me").status_code == 200  # the login that changed it stays
        assert phone.get("/api/auth/me").status_code == 401  # every other login is logged out
        assert login(phone, "alice", "correct horse").status_code == 401
        assert login(phone, "alice", "new password 1").status_code == 200


def test_change_password_needs_a_login(fake_db):
    with new_client() as c:
        res = c.post("/api/auth/password", json={"current_password": "x", "new_password": "new password 1"})
        assert res.status_code == 401


def test_forgotten_password_reset_with_an_admin_code(fake_db):
    with new_client() as admin, new_client() as bob:
        signup(admin, "alice")
        signup(bob, "bob")
        bob.post("/api/auth/logout")
        issued = admin.post("/api/admin/users/2/reset-code")
        assert issued.status_code == 200
        code = issued.json()["code"]
        assert issued.json()["username"] == "bob" and len(code) == 14 and code.count("-") == 2
        assert code not in fake_db.resets and auth.token_hash(code) in fake_db.resets  # stored hashed

        # Wrong username for the code: refused, and the code still works afterwards.
        wrong = bob.post("/api/auth/reset", json={"username": "alice", "code": code, "new_password": "bobs new pw"})
        assert wrong.status_code == 400
        # Typed in lower case without dashes: still accepted. Logs bob in.
        typed = code.replace("-", "").lower()
        done = bob.post("/api/auth/reset", json={"username": "Bob", "code": typed, "new_password": "bobs new pw"})
        assert done.status_code == 200 and done.json()["username"] == "bob"
        assert bob.get("/api/auth/me").json()["username"] == "bob"
        # One use only.
        again = bob.post("/api/auth/reset", json={"username": "bob", "code": code, "new_password": "another pw"})
        assert again.status_code == 400
        assert login(bob, "bob", "correct horse").status_code == 401
        assert login(bob, "bob", "bobs new pw").status_code == 200


def test_reset_codes_are_admin_only_replace_earlier_ones_and_expire(fake_db):
    with new_client() as admin, new_client() as bob:
        signup(admin, "alice")
        signup(bob, "bob")
        assert bob.post("/api/admin/users/1/reset-code").status_code == 403
        assert admin.post("/api/admin/users/99/reset-code").status_code == 404
        first = admin.post("/api/admin/users/2/reset-code").json()["code"]
        second = admin.post("/api/admin/users/2/reset-code").json()["code"]
        reset = {"username": "bob", "new_password": "bobs new pw"}
        assert bob.post("/api/auth/reset", json={**reset, "code": first}).status_code == 400  # replaced
        fake_db.resets[auth.token_hash(second)] = (2, True)  # pretend it expired
        assert bob.post("/api/auth/reset", json={**reset, "code": second}).status_code == 400


def test_guessing_reset_codes_is_throttled(fake_db):
    with new_client() as admin, new_client() as bob:
        signup(admin, "alice")
        signup(bob, "bob")
        code = admin.post("/api/admin/users/2/reset-code").json()["code"]
        for _ in range(auth.MAX_FAILURES):
            bob.post("/api/auth/reset", json={"username": "bob", "code": "AAAA-BBBB-CCCC", "new_password": "bobs new pw"})
        res = bob.post("/api/auth/reset", json={"username": "bob", "code": code, "new_password": "bobs new pw"})
        assert res.status_code == 429


def test_reset_code_helpers():
    code = auth.new_reset_code()
    assert len(code) == 14 and not set(code) & set("01OIL")
    assert auth.normalize_code(" k7qm 2xrp-9htd ") == "K7QM-2XRP-9HTD"
