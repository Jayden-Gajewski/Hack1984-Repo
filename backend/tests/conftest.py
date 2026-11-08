import pytest
from fastapi.testclient import TestClient

from app import db, main

# Personal-data routes need a signed-in account (main.require_session); the test client is one.
TEST_USER = "00000000-0000-4000-8000-0000000000aa"
TEST_SESSION = "test-session"


@pytest.fixture
def client(monkeypatch):
    """The API with Postgres stubbed out and a fresh in-memory session, signed in as TEST_USER.
    No network access."""
    monkeypatch.setattr(db, "init_schema", lambda: None)
    monkeypatch.setattr(db, "save_scan", lambda *args: None)
    monkeypatch.setattr(db, "find_scan", lambda *args: None)
    monkeypatch.setattr(db, "ping", lambda: False)
    monkeypatch.setattr(db, "save_alias", lambda *args: "2026-11-07")
    monkeypatch.setattr(db, "list_aliases", lambda: [])
    monkeypatch.setattr(db, "session_user_id", lambda token: TEST_USER if token == TEST_SESSION else None)
    monkeypatch.setattr(main, "session", main.Session())
    with TestClient(main.app, base_url="http://localhost") as c:  # TrustedHostMiddleware
        c.cookies.set("h84_session", TEST_SESSION)
        yield c
