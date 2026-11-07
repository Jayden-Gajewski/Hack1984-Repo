import pytest

from app.config import get_settings


def test_refuses_a_remote_ollama_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "https://ollama.example.com")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="localhost"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_refuses_a_remote_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com:5432/x")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            get_settings()
    finally:
        get_settings.cache_clear()
