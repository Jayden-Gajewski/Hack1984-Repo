import pytest
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def client(monkeypatch):
    """The API with Postgres stubbed out and a fresh in-memory session. No network access."""
    monkeypatch.setattr(db, "init_schema", lambda: None)
    monkeypatch.setattr(db, "save_scan", lambda *args: None)
    monkeypatch.setattr(db, "ping", lambda: False)
    monkeypatch.setattr(main, "session", main.Session())
    with TestClient(main.app, base_url="http://localhost") as c:  # TrustedHostMiddleware
        yield c
