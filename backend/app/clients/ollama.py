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

# One generate call at a time. On an 8 GB laptop a second concurrent call pushes the machine into
# swap, and the model shares one GPU anyway, so running two at once isn't faster.
_generate_slots = asyncio.Semaphore(1)

# Context window in tokens. The longest prompt is about 12k chars of page text (prompts.MAX_PAGE_CHARS,
# ~3k tokens) plus instructions and the JSON answer, so 6144 fits without Ollama truncating the page.
# 8192 cost ~0.25 GB more memory for headroom no prompt used.
NUM_CTX = 6144

# How long Ollama keeps the model in memory after a call. Long enough that back-to-back scans
# don't reload it (a 20-40 s load from disk); short enough to give the ~5 GB back afterwards.
KEEP_ALIVE = "10m"


def _options(max_tokens: int | None = None) -> dict[str, Any]:
    # num_ctx must match on every call, warm-up included: a different value makes Ollama reload the model.
    options: dict[str, Any] = {"temperature": 0, "num_ctx": NUM_CTX}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    return options


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
            # /api/tags can take a few seconds while Ollama is busy or loading a model. A short
            # timeout made Stage 1 report "not running" and cancel the scan. A stopped Ollama
            # still fails instantly (connection refused), so the longer wait costs nothing then.
            timeout=10.0,
        )
        res.raise_for_status()
        names = {m.get("name", "") for m in res.json().get("models", [])}
    except Exception:
        return False, False
    model = settings.ollama_model
    # An untagged model name means ":latest" to Ollama.
    return True, model in names or f"{model}:latest" in names


async def warm_up() -> None:
    """Load the model into memory without generating anything, so the load overlaps with the
    web searches instead of delaying the first real call. Never raises."""
    settings = get_settings()
    try:
        await request(
            "ollama",
            "POST",
            f"{settings.ollama_url}/api/generate",
            purpose="Load the local LLM while the searches run",
            local=True,
            json_body={
                "model": settings.ollama_model,
                "prompt": "",
                "stream": False,
                "keep_alive": KEEP_ALIVE,
                "options": _options(),
            },
            timeout=180.0,
        )
    except Exception as exc:
        log.warning("Local LLM warm-up failed: %s", exc)


async def ask_json(
    prompt: str, *, system: str, purpose: str, max_tokens: int | None = None
) -> dict[str, Any]:
    """Ask the local model for a JSON object. Returns {} on any failure; never raises on model output.

    max_tokens caps the answer's length. An answer cut off by the cap isn't valid JSON, so it
    comes back as {}: set it well above the longest answer the prompt allows."""
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
                    "keep_alive": KEEP_ALIVE,
                    "options": _options(max_tokens),
                },
                timeout=180.0,
            )
            res.raise_for_status()
            parsed = json.loads(res.json().get("response", ""))
        except Exception as exc:
            log.warning("Local LLM call failed (%s): %s", purpose, exc)
            return {}
    return parsed if isinstance(parsed, dict) else {}
