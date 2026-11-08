"""Loads settings from the repo-root .env file.

On this laptop (no SITE_URL) it refuses a DATABASE_URL that isn't on this machine. The public
server (SITE_URL set, docs/DEPLOY.md) may use a hosted Postgres, but only over TLS. Don't remove
these checks. Page text and policy text go to Google's Gemini API (clients/gemini.py), through
outbound.request like every other request.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
LOCAL_DIR = BACKEND_DIR / "local"  # gitignored: aliases, reports, anything with user data
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class Settings:
    exa_api_key: str
    tavily_api_key: str
    gemini_api_key: str
    gemini_model: str
    alias_domain: str
    database_url: str
    gemini_parallel: int = 4  # Gemini calls at once; lower it if the free tier rate-limits you
    site_url: str = ""  # SITE_URL: the public site (https://...). Empty: Dossier on this laptop only.
    searches_per_day: int = 20  # public site: paid searches (Exa, Tavily, Gemini) per account per day
    searches_per_day_total: int = 500  # public site: the same, across every account
    scan_max_pages: int = 8  # pages analyzed per scan (known brokers first)
    # Threat monitor (all optional). HIBP_API_KEY enables the hashed email check, which needs
    # an HIBP Pro or High RPM plan. Company breach matching needs no key.
    hibp_api_key: str = ""
    # SMTP server for email ownership codes. Unset: emails can be added but are never verified
    # or checked. A server that isn't on this machine must use TLS (port 465 or STARTTLS).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def public(self) -> bool:
        """Running as the public site: data per account, a hosted Postgres allowed, daily limits on."""
        return bool(self.site_url)


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.getenv(name, default))))
    except ValueError:
        return default


def _require_local(name: str, url: str, why: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS:
        raise RuntimeError(f"{name} must point at localhost, got {host!r}. {why}")


def _check_site_url(url: str) -> None:
    parts = urlparse(url)
    if parts.scheme != "https" and not (parts.scheme == "http" and (parts.hostname or "") in LOCAL_HOSTS):
        raise RuntimeError(f"SITE_URL must be the site's https address, got {url!r}.")


def _require_tls(name: str, url: str) -> None:
    """A database that isn't on this machine must be reached over TLS."""
    parts = urlparse(url)
    if (parts.hostname or "") in LOCAL_HOSTS:
        return
    if parse_qs(parts.query).get("sslmode", [""])[0] not in ("require", "verify-ca", "verify-full"):
        raise RuntimeError(f"{name} isn't on this machine, so it must use TLS: add ?sslmode=require.")


@lru_cache
def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")

    site_url = os.getenv("SITE_URL", "").strip().rstrip("/")
    if site_url:
        _check_site_url(site_url)
    database_url = os.getenv(
        "DATABASE_URL", "postgresql://hack:hack@localhost:5432/hack1984"
    )
    if site_url:
        _require_tls("DATABASE_URL", database_url)
    else:
        _require_local("DATABASE_URL", database_url, "Saved scans must stay on this machine.")

    return Settings(
        exa_api_key=os.getenv("EXA_API_KEY", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.6-flash",
        alias_domain=os.getenv("ALIAS_DOMAIN", "alias.local"),
        database_url=database_url,
        gemini_parallel=_int_env("GEMINI_PARALLEL", 4, 1, 16),
        site_url=site_url,
        searches_per_day=_int_env("SEARCHES_PER_DAY", 20, 1, 10_000),
        searches_per_day_total=_int_env("SEARCHES_PER_DAY_TOTAL", 500, 1, 1_000_000),
        scan_max_pages=_int_env("SCAN_MAX_PAGES", 8, 1, 50),
        hibp_api_key=os.getenv("HIBP_API_KEY", "").strip(),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=_int_env("SMTP_PORT", 587, 1, 65535),
        smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USERNAME", "").strip(),
    )
