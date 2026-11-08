"""LLM client: Google's Gemini API (generateContent with JSON output).

Page text, policy sentences and breach evidence are sent to Google here. Every call goes through
outbound.request like any other request, so the log panel shows exactly what was sent; the API key
travels in a header, which the log redacts.
"""

import asyncio
import json
import logging
from typing import Any

from app.config import get_settings
from app.outbound import request

log = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_OUTPUT_TOKENS = 8192  # thinking counts toward this; the JSON answers themselves are short
RETRY_WAITS = (5.0, 15.0)  # seconds before retrying a rate-limited (429) or overloaded (503) call

# How many calls run at once (GEMINI_PARALLEL, default 4). The free tier allows few per minute.
_generate_slots: asyncio.Semaphore | None = None


def _slots() -> asyncio.Semaphore:
    global _generate_slots
    if _generate_slots is None:
        _generate_slots = asyncio.Semaphore(get_settings().gemini_parallel)
    return _generate_slots


def ready() -> bool:
    """GEMINI_API_KEY is set. Contacts nothing: a wrong key shows up as failed calls in the log."""
    return bool(get_settings().gemini_api_key)


async def ask_json(prompt: str, *, system: str, purpose: str) -> dict[str, Any]:
    """Ask Gemini for a JSON object. Returns {} on any failure; never raises on model output."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return {}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "thinkingConfig": {"thinkingLevel": "LOW"},  # short extraction tasks: keep it fast
        },
    }
    async with _slots():
        try:
            for wait in (*RETRY_WAITS, None):
                res = await request(
                    "gemini",
                    "POST",
                    f"{API_URL}/{settings.gemini_model}:generateContent",
                    purpose=purpose,
                    headers={"x-goog-api-key": settings.gemini_api_key},
                    json_body=body,
                    timeout=120.0,
                )
                if wait is None or res.status_code not in (429, 503):
                    break
                await asyncio.sleep(wait)
            res.raise_for_status()
            parts = res.json()["candidates"][0]["content"]["parts"]
            parsed = json.loads("".join(p.get("text", "") for p in parts if not p.get("thought")))
        except Exception as exc:
            log.warning("Gemini call failed (%s): %s", purpose, exc)
            return {}
    return parsed if isinstance(parsed, dict) else {}
