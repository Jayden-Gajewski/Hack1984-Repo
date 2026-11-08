"""Local scheduled checks. A loop inside the backend process: it runs only while the backend is
running on this laptop. There's no cloud job or background service, and the UI says so.

Every minute it looks at the saved schedule. When checks are on and one is due, it starts the
same refresh as the "Refresh now" button (news searches only if the schedule includes them,
since they spend search credits and Gemini calls).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.monitor import service, store

log = logging.getLogger(__name__)

TICK_SECONDS = 60


def due(schedule: dict, now: datetime) -> bool:
    if not schedule.get("enabled"):
        return False
    last = schedule.get("last_run")
    if not last:
        return True
    try:
        return now - datetime.fromisoformat(last) >= timedelta(hours=schedule.get("interval_hours", 24))
    except ValueError:
        return True


def tick(now: datetime | None = None) -> bool:
    """Start a scheduled refresh if one is due. Returns whether it started one."""
    data = store.load()
    if not due(data["schedule"], now or datetime.now(timezone.utc)):
        return False
    if service.is_running() or not (data["companies"] or any(e.get("verified_at") for e in data["emails"])):
        return False
    service.start_refresh(include_news=bool(data["schedule"].get("include_news")), trigger="scheduled")
    return True


async def run() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            tick()
        except Exception:
            log.exception("Scheduled threat monitor check failed to start")
