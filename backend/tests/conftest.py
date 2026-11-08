import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app import auth, db, main
from app.context import current_user_id

TEST_USER = {"id": 1, "username": "tester", "role": "user", "created_at": "2026-11-07T00:00:00+00:00"}


async def _logged_in(request: Request):
    """Stands in for auth.require_user: every request is from TEST_USER."""
    if request.url.path in auth.PUBLIC_PATHS:
        return None
    request.state.user = TEST_USER
    current_user_id.set(TEST_USER["id"])
    return TEST_USER


@pytest.fixture
def client(monkeypatch):
    """The API with Postgres stubbed out, a fresh in-memory session and a logged-in test
    user (tests/test_auth.py checks the real login). No network access."""
    monkeypatch.setattr(db, "init_schema", lambda: None)
    monkeypatch.setattr(db, "save_scan", lambda *args: None)
    monkeypatch.setattr(db, "find_scan", lambda *args: None)
    monkeypatch.setattr(db, "ping", lambda: False)
    monkeypatch.setattr(db, "save_alias", lambda *args: "2026-11-07")
    monkeypatch.setattr(db, "list_aliases", lambda: [])
    monkeypatch.setattr(main, "session", main.Session())
    main.app.dependency_overrides[auth.require_user] = _logged_in
    try:
        with TestClient(main.app, base_url="http://localhost") as c:  # TrustedHostMiddleware
            yield c
    finally:
        main.app.dependency_overrides.pop(auth.require_user, None)
