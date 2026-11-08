import pytest
from fastapi.testclient import TestClient

from app import db, main

# Personal-data routes need a signed-in account (main.require_session); the test client is one.
TEST_USER = "00000000-0000-4000-8000-0000000000aa"
TEST_SESSION = "test-session"


@pytest.fixture(autouse=True)
def _no_real_gemini_key(monkeypatch):
    """Tests never see the real GEMINI_API_KEY from .env, so nothing can reach Google with it.
    Tests that exercise Gemini set a fake key and answer through a MockTransport."""
    from app.config import get_settings

    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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


@pytest.fixture(autouse=True)
def _monitor_state(tmp_path, monkeypatch):
    """The threat monitor's store lives in a temp dir in tests, never backend/local/, and its
    in-memory caches start empty."""
    from app.models import RefreshStatus
    from app.monitor import service, store

    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "monitor.json")
    monkeypatch.setattr(service, "_catalog", None)
    monkeypatch.setattr(service, "_status", RefreshStatus())
    monkeypatch.setattr(service, "_task", None)
