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
    # Performance knobs. Defaults suit a CPU-only 16 GB laptop; raise them on a GPU machine.
    ollama_num_ctx: int = 6144  # tokens of context; less = less RAM per loaded model
    ollama_parallel: int = 1  # LLM calls at once; >1 only helps with a GPU
    ollama_keep_alive: str = "2m"  # unload the model this long after the last call
    scan_max_pages: int = 8  # pages analyzed per scan (known brokers first)


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.getenv(name, default))))
    except ValueError:
        return default


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
        ollama_num_ctx=_int_env("OLLAMA_NUM_CTX", 6144, 2048, 32768),
        ollama_parallel=_int_env("OLLAMA_PARALLEL", 1, 1, 8),
        ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "2m").strip() or "2m",
        scan_max_pages=_int_env("SCAN_MAX_PAGES", 8, 1, 50),
    )
