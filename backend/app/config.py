"""Loads settings from the repo-root .env file.

Refuses to start if OLLAMA_URL or DATABASE_URL is not on this machine. Page text is
sent to the local LLM and scans are saved in Postgres, so neither may point at a
remote host. Don't remove these checks.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
LOCAL_DIR = BACKEND_DIR / "local"  # gitignored: aliases, reports, anything with user data
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class Settings:
    exa_api_key: str
    tavily_api_key: str
    ollama_url: str
    ollama_model: str
    alias_domain: str
    database_url: str


def _require_local(name: str, url: str, why: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS:
        raise RuntimeError(f"{name} must point at localhost, got {host!r}. {why}")


@lru_cache
def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")

    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    _require_local("OLLAMA_URL", ollama_url, "Page text must never leave this machine.")
    database_url = os.getenv(
        "DATABASE_URL", "postgresql://hack:hack@localhost:5432/hack1984"
    )
    _require_local("DATABASE_URL", database_url, "Saved scans must stay on this machine.")

    return Settings(
        exa_api_key=os.getenv("EXA_API_KEY", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        ollama_url=ollama_url,
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        alias_domain=os.getenv("ALIAS_DOMAIN", "alias.local"),
        database_url=database_url,
    )
