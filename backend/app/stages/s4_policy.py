"""Stage 4: policy check. OWNER: Evidence.

For each company the user picked (ids from app.companies: the checked-in list plus added ones):
1. Policy URL: privacy_url from companies.json, else a Tavily search restricted to the
   company's domains (company name only).
2. Tavily Extract with depth="advanced". The policy text stays here: it goes only to the
   local LLM.
3. Pull out the sentences that mention selling, sharing, disclosing, third parties,
   affiliates, advertising or brokers, number them, and pack them into batches (at most
   MAX_BATCHES of about 6k chars). The rest of the policy (cookies, security...) never
   reaches the model, which keeps it fast.
4. The local LLM picks which numbered sentences say the company sells or shares personal
   data. The quote is the sentence itself, so it's verbatim by construction: this is the
   "this wasn't a hack, they sold it" evidence.
5. The code double-checks each pick: a "sale" must say sell/sold/sale, data categories
   must mention personal data or information, and sentences that deny selling or sharing
   ("we do not sell..."), are merger boilerplate ("if our business is sold...") or are
   legal definitions ("'sell' means...") or describe the user's rights ("you have the
   right to opt out of sale") are dropped, the sentence must be in the company's voice, and "sharing" must say who it's shared with. In testing, llama3.1:8b flagged
   all of these without the checks.
6. The model isn't consistent from run to run, so the code also keeps sentences that match
   a strict pattern (the company's own voice + sell/share/disclose + to/with + third
   parties, partners, advertisers, brokers or affiliates) that pass the same checks. That
   makes the demo's "they sold it" flag deterministic, and it still runs on this laptop.
7. If the site blocks extraction, fall back to search snippets from the company's own
   domains, like Stage 1 does, and say so in the errors.
"""

import asyncio
import re
from typing import Any

from app import prompts
from app.clients import ollama, tavily
from app.companies import all_companies
from app.models import PolicyClause, PolicyResult

BATCH_CHARS = 6_000
MAX_BATCHES = 4
MAX_SENTENCES = 80
MIN_SENTENCE_CHARS = 40
MIN_WORDS = 8  # shorter lines are almost always headings
MAX_QUOTE_CHARS = 500
MAX_CLAUSES = 8
MAX_PER_CATEGORY = 3

_CANDIDATE = re.compile(
    r"\bsell|\bsold\b|\bsale\b|\bshar(e|es|ed|ing)\b|disclos|third[- ]part|affiliat|advertis|broker", re.I
)
_CATEGORY_EVIDENCE = {
    "sale": re.compile(r"\bsell|\bsold\b|\bsale\b", re.I),
    # Sharing has to say who receives it ("share ... with", "disclose ... to").
    "sharing": re.compile(r"\b(shar(e|es|ed|ing)|disclos(e|es|ed|ing))\b[^.]{0,150}\b(with|to)\b", re.I),
    "advertising": re.compile(r"advertis|\bads\b|marketing", re.I),
    "affiliates": re.compile(r"affiliat", re.I),
    "data_broker": re.compile(r"broker", re.I),
}
_ABOUT_DATA = re.compile(r"personal|\bdata\b|information", re.I)
_DENIAL = re.compile(
    r"\b(do|does|will|shall|did) not (sell|share|disclose|rent)|\bdon'?t (sell|share)|\bnever (sell|share)", re.I
)
# Standard clauses about the company itself being bought or merged: not selling your data.
_CORPORATE_DEAL = re.compile(
    r"merger|acquisition|acquired|change (in|of) control|bankruptcy|reorgani[sz]ation|corporate transaction|"
    r"business is sold|sale of (all|substantially|our business|the business|assets|a business)",
    re.I,
)
# Legal definitions ("'sell' means ...", "for the purposes of this section") describe a term,
# they don't say the company does it.
_DEFINITION = re.compile(r"for the purposes? of|\bis defined\b|[\"“'‘](sell|sale|share|sharing)[\"”'’]", re.I)
# Statements of the user's rights and choices ("you have the right to opt out of sale")
# describe what you can ask for, not what the company does.
_USER_RIGHTS = re.compile(
    r"\byou (have|may have|can|may) (also )?(the )?right|\bright to\b|\byour (choices|rights)\b|"
    r"\bopt[- ]?out\b|\byou (can|may) (choose|ask|request|manage|control|limit)",
    re.I,
)
# A sentence that plainly says the company sells or shares data with outsiders.
_STRONG = re.compile(
    r"\b(sell|sells|sold|shar(e|es|ing)|disclos(e|es|ing))\b[^.]{0,150}\b(to|with)\b[^.]{0,150}"
    r"(third[- ]part|partner|advertis|marketing|broker|affiliat|other compan)",
    re.I,
)
# Service providers working on the company's behalf don't count (spec), unless the sentence
# also names partners, advertisers, brokers, affiliates or "other third parties".
_SERVICE_PROVIDER = re.compile(r"service providers?|vendors?|on (our|its) behalf|support services|perform(s)? (services|functions)", re.I)
_OUTSIDERS = re.compile(r"partner|advertis|marketing|broker|affiliat|other third[- ]part", re.I)
# Bounded, so a page full of "[" can't make this take minutes (each try stops within a few hundred characters).
_MD_LINK = re.compile(r"\[([^\[\]\n]{1,300})\]\([^()\s]{0,500}\)")
_LIGATURE = re.compile(r"(?<=[a-z]) (ffi|ffl|fi|fl|ff) (?=[a-z])")
SAME_OPENING_CHARS = 80  # quotes that start the same are one clause (snippets repeat and truncate)
_BANNED = re.compile(r"leak", re.I)
CATEGORY_ORDER = {c: i for i, c in enumerate(("sale", "data_broker", "sharing", "advertising", "affiliates"))}
DEFAULT_EXPLANATION = {
    "sale": "The policy says the company may sell your personal information.",
    "data_broker": "The policy says the company shares your information with data brokers.",
    "sharing": "The policy says the company shares your personal information with other companies.",
    "advertising": "The policy says your information is used or shared for targeted ads.",
    "affiliates": "The policy says your information is shared across the company's affiliates.",
}


# ---------- pure helpers (unit-tested) ----------


def is_heading(line: str) -> bool:
    """'Who We Share Your Information With & Why': no closing punctuation, mostly capitalized."""
    words = re.findall(r"[A-Za-z][A-Za-z'’]*", line)
    if not words or line.rstrip().endswith((".", "!", "?", ";", ":")):
        return False
    return sum(w[0].isupper() for w in words) / len(words) >= 0.6


def candidate_sentences(text: str) -> list[str]:
    """Sentences (or bullet lines) that mention selling or sharing, cleaned of markdown markers."""
    text = _LIGATURE.sub(r"\1", text)  # PDF-style splits: "identi fi es" -> "identifies"
    pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])|\n+", text)
    sentences: list[str] = []
    for piece in pieces:
        sentence = _MD_LINK.sub(r"\1", " ".join(piece.split())).replace("**", "").lstrip("-*•#>+ ").strip()
        if (
            MIN_SENTENCE_CHARS <= len(sentence) <= MAX_QUOTE_CHARS
            and len(sentence.split()) >= MIN_WORDS
            and _CANDIDATE.search(sentence)
            and "|" not in sentence  # markdown table rows
            and not is_heading(sentence)
            and sentence not in sentences
        ):
            sentences.append(sentence)
    return sentences[:MAX_SENTENCES]


def batches(sentences: list[str]) -> list[list[str]]:
    groups: list[list[str]] = [[]]
    size = 0
    for sentence in sentences:
        if groups[-1] and size + len(sentence) > BATCH_CHARS:
            groups.append([])
            size = 0
        groups[-1].append(sentence)
        size += len(sentence) + 8
    return [g for g in groups if g][:MAX_BATCHES]


def numbered(sentences: list[str]) -> str:
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))


def passes_checks(quote: str, category: str, company: str = "") -> bool:
    """True if `quote` really says the company does `category` (see the module docstring)."""
    voice = re.compile(r"\b(we|our|us)\b" + (rf"|{re.escape(company)}" if company else ""), re.I)
    if not _CATEGORY_EVIDENCE[category].search(quote):
        return False
    if category != "advertising" and not _ABOUT_DATA.search(quote):
        return False
    if _DENIAL.search(quote) or _CORPORATE_DEAL.search(quote) or _DEFINITION.search(quote):
        return False
    if _SERVICE_PROVIDER.search(quote) and not _OUTSIDERS.search(quote):
        return False
    return not _USER_RIGHTS.search(quote) and bool(voice.search(quote))


def pattern_clauses(sentences: list[str], company: str = "") -> list[PolicyClause]:
    """Deterministic flags for sentences that plainly say the company sells or shares data."""
    clauses = []
    for quote in sentences:
        if not _STRONG.search(quote):
            continue
        lowered = quote.lower()
        if "broker" in lowered:
            category = "data_broker"
        elif re.search(r"\bsell|\bsold\b|considered a sale|\bsale of (your |personal )?(information|data)", lowered):
            category = "sale"
        elif re.search(r"advertis|marketing", lowered):
            category = "advertising"
        elif "affiliat" in lowered and not re.search(r"third[- ]part|partner", lowered):
            category = "affiliates"
        else:
            category = "sharing"
        if passes_checks(quote, category, company):
            clauses.append(PolicyClause(category=category, quote=quote, explanation=DEFAULT_EXPLANATION[category]))
    return clauses


def parse_clauses(out: dict[str, Any], sentences: list[str], company: str = "") -> list[PolicyClause]:
    raw = out.get("clauses")
    clauses = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        try:
            index = int(item.get("sentence"))
        except (TypeError, ValueError):
            continue
        if category not in prompts.POLICY_CATEGORIES or not 1 <= index <= len(sentences):
            continue
        quote = sentences[index - 1]
        if not passes_checks(quote, category, company):
            continue
        explanation = item.get("explanation") if isinstance(item.get("explanation"), str) else ""
        explanation = " ".join(explanation.split())[:200]
        if not explanation or _BANNED.search(explanation):
            explanation = DEFAULT_EXPLANATION[category]
        clauses.append(PolicyClause(category=category, quote=quote, explanation=explanation))
    return clauses


def merge_clauses(clauses: list[PolicyClause]) -> list[PolicyClause]:
    """Drop repeats (the same sentence, or a truncated copy of it, keeping the fuller one),
    then cap each category."""
    unique: list[tuple[str, PolicyClause]] = []
    for clause in clauses:
        key = re.sub(r"[^a-z0-9]", "", clause.quote.lower())
        for i, (other, _) in enumerate(unique):
            if key.startswith(other) or other.startswith(key) or key[:SAME_OPENING_CHARS] == other[:SAME_OPENING_CHARS]:
                if len(key) > len(other):
                    unique[i] = (key, clause)
                break
        else:
            unique.append((key, clause))
    kept, per_category = [], {}
    for clause in sorted((c for _, c in unique), key=lambda c: CATEGORY_ORDER[c.category]):
        per_category[clause.category] = per_category.get(clause.category, 0) + 1
        if per_category[clause.category] <= MAX_PER_CATEGORY:
            kept.append(clause)
    return kept[:MAX_CLAUSES]


# ---------- the stage ----------


async def _policy_url(company: dict[str, Any], errors: list[str]) -> str | None:
    if company.get("privacy_url"):
        return company["privacy_url"]
    try:
        data = await tavily.search(
            f"{company['name']} privacy policy",
            purpose=f"Find {company['name']}'s privacy policy",
            include_domains=company["domains"],
            max_results=5,
        )
    except Exception as exc:
        errors.append(f"{company['name']}: finding the privacy policy failed: {exc}")
        return None
    results = [r for r in data.get("results", []) if r.get("url")]
    privacy = [r for r in results if "privacy" in f"{r['url']} {r.get('title', '')}".lower()]
    return (privacy or results or [{}])[0].get("url")


async def _snippet_fallback(company: dict[str, Any], errors: list[str]) -> str:
    """Policy excerpts from search results on the company's own domains (company name only)."""
    try:
        data = await tavily.search(
            f"{company['name']} privacy policy sell share personal information",
            purpose=f"Find excerpts of {company['name']}'s privacy policy (the full page was blocked)",
            include_domains=company["domains"],
            max_results=5,
        )
    except Exception as exc:
        errors.append(f"{company['name']}: searching the privacy policy failed: {exc}")
        return ""
    return "\n".join(r.get("content") or "" for r in data.get("results", []))


async def _check(company: dict[str, Any], errors: list[str]) -> PolicyResult:
    name = company["name"]
    url = await _policy_url(company, errors)
    result = PolicyResult(company_id=company["id"], company=name, policy_url=url)
    if not url:
        errors.append(f"Couldn't find {name}'s privacy policy.")
        return result
    try:
        data = await tavily.extract([url], purpose=f"Read {name}'s privacy policy", depth="advanced")
    except Exception as exc:
        errors.append(f"{name}: reading the privacy policy failed: {exc}")
        return result
    text = next((r.get("raw_content") for r in data.get("results", []) if r.get("raw_content")), "")
    if not text:
        text = await _snippet_fallback(company, errors)
        if not text:
            errors.append(f"Couldn't read {name}'s privacy policy (the site blocked it).")
            return result
        errors.append(f"{name}'s site blocked reading the full policy, so it was checked from search snippets.")

    groups = batches(candidate_sentences(text))
    answers = await asyncio.gather(
        *(
            ollama.ask_json(
                prompts.policy_prompt(name, numbered(group)),
                system=prompts.POLICY_SYSTEM,
                purpose=f"Flag sale and sharing clauses in {name}'s policy on this laptop (part {i} of {len(groups)})",
            )
            for i, group in enumerate(groups, 1)
        )
    )
    if groups and not any(answers):
        errors.append(f"The local LLM didn't answer for {name}'s policy, so it wasn't checked.")
    clauses = [c for group, answer in zip(groups, answers) if answer for c in parse_clauses(answer, group, name)]
    clauses += pattern_clauses([s for group in groups for s in group], name)  # model's picks win on ties
    return result.model_copy(update={"clauses": merge_clauses(clauses)})


async def check_policies(company_ids: list[str]) -> tuple[list[PolicyResult], list[str]]:
    """Return (one PolicyResult per company, errors)."""
    companies = [c for c in all_companies() if c["id"] in company_ids]
    errors: list[str] = []
    results = await asyncio.gather(*(_check(c, errors) for c in companies))
    return list(results), list(dict.fromkeys(errors))
