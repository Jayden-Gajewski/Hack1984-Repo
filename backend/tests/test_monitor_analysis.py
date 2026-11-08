"""Gemini's explanation: every check in monitor/analysis.py, and what the model is sent."""

import asyncio

import pytest

from app.monitor import analysis, incidents
from tests.monitor_fixtures import EMAIL, SHOPCO, breach, use_settings

FACTS = incidents.hibp_facts(breach("ShopCo", domain="shopco.example"), SHOPCO, "hibp_catalog")
EVIDENCE = analysis.evidence_text(FACTS)
REASONS = ["Starts at high: it exposed passwords."]


def check(out, involvement="unconfirmed", facts=FACTS, evidence=EVIDENCE):
    return analysis.validate(
        out, evidence=evidence, facts=facts, level="high", level_reasons=REASONS,
        involvement=involvement, involvement_reason="Not confirmed. Verify an email to check.",
    )


def test_evidence_has_the_facts_and_no_personal_data():
    assert "Accounts in the breach: 120,000 (per Have I Been Pwned)" in EVIDENCE
    assert "Date it happened: 2021-03-04 (source: Have I Been Pwned (breach date))" in EVIDENCE
    assert "Exposed data (as reported): Email addresses, Passwords" in EVIDENCE
    assert "@" not in EVIDENCE


def test_invented_numbers_are_dropped_and_real_ones_kept():
    result = check({"summary": "ShopCo had 120,000 accounts exposed in 2021. About 5 million people were hit."})
    assert result["summary"] == "ShopCo had 120,000 accounts exposed in 2021."
    assert result["removed_sentences"] == 1


def test_claims_about_the_user_need_confirmation():
    claim = "Your password was exposed in this breach. Change it now."
    assert check({"impact": claim})["impact"] == "Change it now."
    assert check({"impact": claim}, involvement="confirmed")["impact"] == claim
    hedged = "If your password was exposed, attackers could try it elsewhere."
    assert check({"impact": hedged})["impact"] == hedged


def test_banned_wording_is_dropped():
    result = check({"summary": "The data was leaked by an insider. It included passwords."})
    assert result["summary"] == "It included passwords."


def test_severity_explanation_cannot_change_the_level():
    assert check({"severity_explanation": "This is critical because passwords leaked."})["severity_explanation"] == REASONS[0]
    kept = "It's high because passwords make account takeover possible."
    assert check({"severity_explanation": kept})["severity_explanation"] == kept


def test_guidance_needs_advice_in_the_evidence():
    assert check({"guidance": "ShopCo advised users to reset their passwords."})["guidance"]
    quiet = dict(FACTS, description="ShopCo had a breach.")
    evidence = analysis.evidence_text(quiet)
    assert check({"guidance": "Reset your password."}, facts=quiet, evidence=evidence)["guidance"] == ""


def test_missing_or_bad_fields_fall_back_to_facts():
    result = check({"summary": 42, "uncertainty": None, "impact": ["x"]})
    assert result["summary"] == (
        "ShopCo is a breach at ShopCo that exposed email addresses and passwords. Source: Have I Been Pwned."
    )
    assert result["uncertainty"] == "Not confirmed. Verify an email to check."
    assert result["impact"] == ""
    long = check({"summary": "Passwords were exposed. " * 60})
    assert len(long["summary"]) <= analysis.FIELD_LIMITS["summary"]


def test_explain_sends_only_the_breach_to_gemini(monkeypatch):
    use_settings(monkeypatch)
    sent = {}

    async def ask_json(prompt, *, system, purpose):
        sent.update(prompt=prompt, purpose=purpose)
        return {"summary": "ShopCo had 120,000 accounts exposed.", "impact": "Passwords can be reused.",
                "guidance": "", "uncertainty": "", "severity_explanation": "High because of passwords."}

    monkeypatch.setattr(analysis.gemini, "ask_json", ask_json)
    result = asyncio.run(
        analysis.explain(FACTS, level="high", level_reasons=REASONS, involvement="confirmed",
                         involvement_reason=f"Have I Been Pwned lists your verified address {EMAIL} in this breach.")
    )
    assert EMAIL not in sent["prompt"] and "@" not in sent["prompt"]
    assert "Severity: high" in sent["prompt"] and "Confirmed" in sent["prompt"]
    assert result["summary"] == "ShopCo had 120,000 accounts exposed." and result["model"]


def test_explain_reports_a_silent_llm(monkeypatch):
    use_settings(monkeypatch)

    async def ask_json(prompt, *, system, purpose):
        return {}

    monkeypatch.setattr(analysis.gemini, "ask_json", ask_json)
    with pytest.raises(RuntimeError, match="The AI didn't answer"):
        asyncio.run(analysis.explain(FACTS, level="high", level_reasons=REASONS, involvement="unconfirmed", involvement_reason="x"))


def test_a_news_only_breach_reads_its_official_notice(monkeypatch):
    use_settings(monkeypatch, tavily_api_key="tvly-test")
    news = {**FACTS, "hibp_name": None, "description": "",
            "sources": [{"url": "https://shopco.example/notice", "kind": "official", "label": "Company notice", "official": True}]}
    asked = []

    async def extract(urls, *, purpose, depth="basic"):
        asked.append(urls)
        return {"results": [{"url": urls[0], "raw_content": "We recommend that customers reset passwords."}]}

    monkeypatch.setattr(analysis.tavily, "extract", extract)
    assert asyncio.run(analysis.fetch_notice(news)) == "We recommend that customers reset passwords."
    assert asked == [["https://shopco.example/notice"]]
    assert asyncio.run(analysis.fetch_notice(FACTS)) == ""  # HIBP already describes it


def test_input_hash_changes_with_the_facts():
    first = analysis.input_hash(FACTS, "high", "unconfirmed")
    assert first == analysis.input_hash(dict(FACTS), "high", "unconfirmed")
    assert first != analysis.input_hash(FACTS, "critical", "confirmed")
    assert first != analysis.input_hash(dict(FACTS, data_classes=["Passwords"]), "high", "unconfirmed")


def test_scaled_counts_must_match_the_evidence():
    facts = dict(FACTS, pwn_count=164611595, description="Data from 17M rows was posted.")
    evidence = analysis.evidence_text(facts)
    kept = "About 164 million accounts were in it. The post had 17M rows."
    assert check({"summary": kept}, facts=facts, evidence=evidence)["summary"] == kept
    assert check({"summary": "About 2 billion accounts were in it."}, facts=facts, evidence=evidence)["removed_sentences"] == 1


def test_an_alleged_breach_stays_alleged():
    facts = dict(FACTS, description="Records allegedly breached from ShopCo were posted. ShopCo denied a breach.")
    evidence = analysis.evidence_text(facts)
    summary = check({"summary": "ShopCo had a data breach."}, facts=facts, evidence=evidence)["summary"]
    assert summary == f"ShopCo had a data breach. {analysis.ALLEGED_NOTE}"
    hedged = "Records allegedly from ShopCo were posted."
    assert check({"summary": hedged}, facts=facts, evidence=evidence)["summary"] == hedged
