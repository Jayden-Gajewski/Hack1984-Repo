"""Who the current request is for. Set by auth.require_user; read by main.py (per-user scan
session) and outbound.py (tags each log entry with its user).

A ContextVar follows the request into asyncio.gather tasks, so stage code doesn't need to
pass the user around.
"""

from contextvars import ContextVar

current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)
