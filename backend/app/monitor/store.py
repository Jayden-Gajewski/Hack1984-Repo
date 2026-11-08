"""The threat monitor's saved state: backend/local/monitor.json (gitignored), single user.

Holds the monitored companies and emails, incident facts, which steps the user marked done,
the activity history and the schedule. Writes are atomic (temp file + rename) and go through
edit(), which holds a lock so a scheduled check and a click can't overwrite each other.
"""

import asyncio
import json
import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import LOCAL_DIR

log = logging.getLogger(__name__)

STORE_PATH: Path = LOCAL_DIR / "monitor.json"
MAX_EVENTS = 300
_lock = asyncio.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty() -> dict[str, Any]:
    return {
        "version": 1,
        "companies": [],
        "emails": [],
        "incidents": {},  # id -> facts plus first_seen, last_seen, seen, analysis
        "actions": {},  # incident id -> {action id: ISO time it was marked done}
        "events": [],  # newest first
        "schedule": {"enabled": False, "interval_hours": 24, "include_news": False, "last_run": None},
    }


def load() -> dict[str, Any]:
    path = STORE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty()
    except (OSError, ValueError) as exc:
        backup = path.with_name(f"{path.name}.unreadable-{datetime.now():%Y%m%d%H%M%S}")
        log.warning("Couldn't read %s (%s); moved it to %s and started fresh.", path, exc, backup)
        try:
            path.rename(backup)
        except OSError:
            pass
        return empty()
    base = empty()
    if not isinstance(data, dict):
        return base
    for key, default in base.items():
        if not isinstance(data.get(key), type(default)):
            data[key] = default
    return data


def save(data: dict[str, Any]) -> None:
    path = STORE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


@asynccontextmanager
async def edit() -> AsyncIterator[dict[str, Any]]:
    """Load, let the caller change the dict, then save. Saves only if the block finishes."""
    async with _lock:
        data = load()
        yield data
        save(data)


def add_event(data: dict[str, Any], kind: str, message: str, incident_id: str | None = None) -> None:
    data["events"].insert(
        0, {"id": secrets.token_hex(4), "time": now(), "kind": kind, "message": message, "incident_id": incident_id}
    )
    del data["events"][MAX_EVENTS:]


def find_incident_id(data: dict[str, Any], incident_id: str) -> str | None:
    """The current id for an incident id or one of its old aliases."""
    if incident_id in data["incidents"]:
        return incident_id
    return next((fid for fid, f in data["incidents"].items() if incident_id in f.get("aliases", [])), None)
