"""Threat monitor: known breaches at the companies a user has accounts with, and at the
addresses they've proven they own. Separate from the exposure scanner, but it reuses its
pieces: Stage 3 (news and official notices), the company list, Stage 5's "likely" rule for
linking a breach to listings, the local LLM and the outbound log.

Modules, pure ones first:
- breach_data.py  reference data (data/breach_data_classes.json)
- incidents.py    HIBP and Stage 3 results -> incident facts; matching and de-duplication
- severity.py     rule-based severity, confidence and involvement (no LLM)
- checklist.py    the recommended steps for an incident
- analysis.py     the local LLM's explanation, checked against the evidence
- store.py        backend/local/monitor.json (gitignored)
- emails.py       ownership codes (SMTP) and the hashed HIBP email check
- service.py      refresh, dashboard, steps, schedule
- scheduler.py    local scheduled checks, only while the backend is running
- routes.py       /api/monitor/*

Privacy: HIBP gets either nothing personal (its whole breach list is downloaded and matched
here) or the first 6 characters of an email's SHA-1 hash. Tavily and Exa get company names
only, through Stage 3, and Tavily Extract may get one public URL (a company's official breach
notice) when explaining a breach HIBP doesn't describe. Breach text goes only to the local LLM.
"""
