import pytest

from app.config import get_settings


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

    for name in ("GEMINI_MODEL", "GEMINI_PARALLEL", "SCAN_MAX_PAGES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert (s.gemini_model, s.gemini_parallel, s.scan_max_pages) == ("gemini-3.6-flash", 4, 8)

    monkeypatch.setenv("GEMINI_PARALLEL", "999")
    monkeypatch.setenv("SCAN_MAX_PAGES", "lots")
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.gemini_parallel == 16 and s.scan_max_pages == 8  # clamped / bad value ignored
    config.get_settings.cache_clear()
