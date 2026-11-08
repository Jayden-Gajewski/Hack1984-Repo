"""Gemini's explanation of one incident, checked against the evidence before it's kept.

The model gets the evidence (HIBP's description, the reported data, dates with their sources,
report summaries, and for a breach HIBP doesn't describe, the text of its official notice) plus
the facts the rules already set. About the user it only learns whether they're confirmed.

Checks in code, sentence by sentence:
- a number with 2+ digits that isn't in the evidence is dropped (no invented counts or dates);
- "your data was exposed" style claims are dropped unless involvement is confirmed;
- "leaked by" / "who leaked" is dropped;
- a severity explanation that names another level is replaced with the rules' own reasons;
- guidance is emptied when the evidence contains no advice at all;
- if the evidence calls the breach alleged or disputed and the summary doesn't, a note is added.
If the summary doesn't survive, a summary built only from the facts is used instead.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app import prompts
from app.clients import gemini, tavily
from app.config import get_settings
from app.monitor import severity

log = logging.getLogger(__name__)

FIELD_LIMITS = {"summary": 600, "impact": 400, "guidance": 500, "uncertainty": 300, "severity_explanation": 300}
NOTICE_CHARS = 4000
DATE_KIND = {"occurred": "it happened", "disclosed": "it was disclosed", "added_to_hibp": "added to Have I Been Pwned"}
# What the model is told about the person. No address, masked or not.
INVOLVEMENT_FOR_MODEL = {
    "confirmed": "Confirmed: the reader's verified email is listed in this breach by Have I Been Pwned.",
    "not_found": "Not found: the reader's verified email isn't listed in this breach, but they may have used another address.",
    "unconfirmed": "Not confirmed: nobody knows whether the reader's account was in this breach.",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SCALED = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|bn|k|m)\b", re.I)
_SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9}
_BANNED = re.compile(r"leaked by|who leaked", re.I)
_CLAIM = re.compile(
    r"\b(you|your)\b.*\b(was|were|has been|have been|is|are)\s+"
    r"(exposed|compromised|affected|leaked|stolen|breached|included|impacted|involved)\b",
    re.I,
)
_HEDGE = re.compile(
    r"\b(if|may|might|could|whether|possibly|potentially|unconfirmed|unknown)\b|not (been )?confirmed|isn't known|not known",
    re.I,
)
_ALLEGED = re.compile(r"\balleg|\bdenied\b|\bdenies\b|\bunconfirmed breach", re.I)
ALLEGED_NOTE = "The sources describe this breach as alleged or disputed."
_LEVEL_WORD = re.compile(r"\b(critical|high|medium|low)\b", re.I)
_ADVICE = re.compile(r"recommend|advis|\burg(e|ed|es|ing)\b|encourag|should|reset|change (your|their)|enable|turn on|freeze", re.I)


def evidence_text(facts: dict[str, Any], notice_text: str = "") -> str:
    lines = [f"Company: {facts['company']}", f"Breach: {facts['title']}"]
    for d in facts.get("dates", []):
        lines.append(f"Date {DATE_KIND.get(d['kind'], d['kind'])}: {d['date']} (source: {d['source']})")
    if facts.get("data_classes"):
        lines.append("Exposed data (as reported): " + ", ".join(facts["data_classes"]))
    else:
        lines.append("Exposed data: not reported")
    if facts.get("pwn_count") is not None:
        lines.append(f"Accounts in the breach: {facts['pwn_count']:,} (per Have I Been Pwned)")
    caveats = severity.flags(facts)
    if caveats:
        lines.append("Caveats: " + "; ".join(caveats))
    if facts.get("hibp_name") and facts.get("description"):
        lines.append(f"Description (Have I Been Pwned): {facts['description']}")
    for report in facts.get("reports", []):
        lines.append(f"Report ({report['label']}, {report['url']}): {report['summary']}")
    if notice_text:
        lines.append(f"Official notice text: {notice_text[:NOTICE_CHARS]}")
    return "\n".join(lines)


def input_hash(facts: dict[str, Any], level: str, involvement: str) -> str:
    """Changes whenever the evidence or the rules' answers change, which makes a saved
    explanation stale."""
    payload = json.dumps([evidence_text(facts), level, involvement], sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()


# ---------- checks (pure) ----------


def _values(text: str) -> list[float]:
    """Every number in the text as a value: "120,000" -> 120000, "164 million" and "6.2M" scaled."""
    values = []
    for match in _SCALED.finditer(text):
        values.append(float(match.group(1).replace(",", "")) * _SCALE[match.group(2).lower()])
    for token in _NUMBER.findall(_SCALED.sub(" ", text)):
        try:
            values.append(float(token.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return values


def _grounded(sentence: str, evidence_digits: str, evidence_values: list[float]) -> bool:
    """A count like "5 million" must be within 15% of a number in the evidence; any other number
    with 2+ digits must appear in it as written."""
    for match in _SCALED.finditer(sentence):
        value = float(match.group(1).replace(",", "")) * _SCALE[match.group(2).lower()]
        if not any(abs(v - value) <= 0.15 * value for v in evidence_values):
            return False
    for token in _NUMBER.findall(_SCALED.sub(" ", sentence)):
        digits = token.replace(",", "").rstrip(".")
        if sum(ch.isdigit() for ch in digits) >= 2 and digits not in evidence_digits:
            return False
    return True


def _clean(text: Any, *, evidence_digits: str, evidence_values: list[float], confirmed: bool) -> tuple[str, int]:
    if not isinstance(text, str):
        return "", 0
    text = " ".join(text.split())
    if not text:
        return "", 0
    kept, removed = [], 0
    for sentence in _SENTENCE_SPLIT.split(text):
        claims = not confirmed and _CLAIM.search(sentence) and not _HEDGE.search(sentence)
        if _BANNED.search(sentence) or claims or not _grounded(sentence, evidence_digits, evidence_values):
            removed += 1
            continue
        kept.append(sentence)
    return " ".join(kept), removed


def _limit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    return cut[: end + 1] if end > limit // 2 else cut.rstrip() + "…"


def fallback_summary(facts: dict[str, Any]) -> str:
    """A summary built only from the facts, for when the model's doesn't pass the checks."""
    text = f"{facts['title']} is a breach at {facts['company']}"
    classes = [c[0].lower() + c[1:] if len(c) > 1 and c[1].islower() else c for c in facts.get("data_classes", [])[:5]]
    if classes:
        text += " that exposed " + (", ".join(classes[:-1]) + " and " + classes[-1] if len(classes) > 1 else classes[0])
    source = next((s["label"] for s in facts.get("sources", [])), None)
    return text + "." + (f" Source: {source}." if source else "")


def validate(
    out: dict[str, Any],
    *,
    evidence: str,
    facts: dict[str, Any],
    level: str,
    level_reasons: list[str],
    involvement: str,
    involvement_reason: str,
) -> dict[str, Any]:
    """The model's answer with every check applied. Never raises on model output."""
    digits = evidence.replace(",", "")
    values = _values(evidence)
    confirmed = involvement == "confirmed"
    result: dict[str, Any] = {}
    removed = 0
    for field, limit in FIELD_LIMITS.items():
        text, dropped = _clean(out.get(field), evidence_digits=digits, evidence_values=values, confirmed=confirmed)
        result[field] = _limit(text, limit)
        removed += dropped
    named = {w.lower() for w in _LEVEL_WORD.findall(result["severity_explanation"])}
    if not result["severity_explanation"] or named - {level}:
        result["severity_explanation"] = " ".join(level_reasons)
    if not _ADVICE.search(evidence):
        result["guidance"] = ""  # nothing in the sources to summarize
    if not confirmed and not result["uncertainty"]:
        result["uncertainty"] = involvement_reason
    if not result["summary"]:
        result["summary"] = fallback_summary(facts)
    if _ALLEGED.search(evidence) and not _ALLEGED.search(result["summary"]):
        result["summary"] += " " + ALLEGED_NOTE  # the model dropped the source's caveat
    result["removed_sentences"] = removed
    return result


# ---------- the call ----------


async def fetch_notice(facts: dict[str, Any]) -> str:
    """The text of the official notice for a breach HIBP doesn't describe: one Tavily Extract
    of a public URL (no personal data). Empty when there's none or it can't be read."""
    if facts.get("hibp_name") and facts.get("description"):
        return ""
    url = next((s["url"] for s in facts.get("sources", []) if s.get("official") and s.get("kind") != "hibp"), None)
    if not url or not get_settings().tavily_api_key:
        return ""
    try:
        data = await tavily.extract(
            [url], purpose=f"Read {facts['company']}'s breach notice so the AI can summarize it"
        )
        results = data.get("results") or []
        text = results[0].get("raw_content") or "" if results else ""
    except Exception as exc:
        log.warning("Couldn't read the notice for %s: %s", facts["id"], exc)
        return ""
    return " ".join(str(text).split())[:NOTICE_CHARS]


async def explain(
    facts: dict[str, Any], *, level: str, level_reasons: list[str], involvement: str, involvement_reason: str
) -> dict[str, Any]:
    """A checked explanation, ready to store. Raises RuntimeError if Gemini doesn't answer."""
    evidence = evidence_text(facts, await fetch_notice(facts))
    out = await gemini.ask_json(
        prompts.threat_prompt(evidence, level, " ".join(level_reasons), INVOLVEMENT_FOR_MODEL[involvement]),
        system=prompts.THREAT_SYSTEM,
        purpose=f"Ask the AI to explain the {facts['title']} breach",
    )
    if not out:
        raise RuntimeError("The AI didn't answer. Check its API key in .env, then try again.")
    result = validate(
        out,
        evidence=evidence,
        facts=facts,
        level=level,
        level_reasons=level_reasons,
        involvement=involvement,
        involvement_reason=involvement_reason,
    )
    result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    result["model"] = get_settings().gemini_model
    return result
