"""Local LLM client (Ollama). Page text goes only to localhost.

Every call is logged with local=True, so the outbound panel can show it stayed on this machine.
"""

import asyncio
import json
import logging
from typing import Any

from app.config import get_settings
from app.outbound import request

log = logging.getLogger(__name__)

# Small local models slow down fast under load, so at most 2 generate calls run at once.
_generate_slots = asyncio.Semaphore(2)


async def status() -> tuple[bool, bool]:
    """Return (running, model_pulled) for the configured OLLAMA_MODEL."""
    settings = get_settings()
    try:
        res = await request(
            "ollama",
            "GET",
            f"{settings.ollama_url}/api/tags",
            purpose="Check that the local LLM is running",
            local=True,
            timeout=3.0,
        )
        res.raise_for_status()
        names = {m.get("name", "") for m in res.json().get("models", [])}
    except Exception:
        return False, False
    model = settings.ollama_model
    # An untagged model name means ":latest" to Ollama.
    return True, model in names or f"{model}:latest" in names


async def ask_json(prompt: str, *, system: str, purpose: str) -> dict[str, Any]:
    """Ask the local model for a JSON object. Returns {} on any failure; never raises on model output."""
    settings = get_settings()
    async with _generate_slots:
        try:
            res = await request(
                "ollama",
                "POST",
                f"{settings.ollama_url}/api/generate",
                purpose=purpose,
                local=True,
                json_body={
                    "model": settings.ollama_model,
                    "prompt": prompt,
                    "system": system,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0, "num_ctx": 8192},
                },
                timeout=180.0,
            )
            res.raise_for_status()
            parsed = json.loads(res.json().get("response", ""))
        except Exception as exc:
            log.warning("Local LLM call failed (%s): %s", purpose, exc)
            return {}
    return parsed if isinstance(parsed, dict) else {}
