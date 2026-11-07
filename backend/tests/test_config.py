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


def test_performance_settings_have_safe_defaults_and_bounds(monkeypatch):
    from app import config

    for name in ("OLLAMA_NUM_CTX", "OLLAMA_PARALLEL", "OLLAMA_KEEP_ALIVE", "SCAN_MAX_PAGES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert (s.ollama_num_ctx, s.ollama_parallel, s.ollama_keep_alive, s.scan_max_pages) == (6144, 1, "2m", 8)

    monkeypatch.setenv("OLLAMA_PARALLEL", "999")
    monkeypatch.setenv("SCAN_MAX_PAGES", "lots")
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.ollama_parallel == 8 and s.scan_max_pages == 8  # clamped / bad value ignored
    config.get_settings.cache_clear()
