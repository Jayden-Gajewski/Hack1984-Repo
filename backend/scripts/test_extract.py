"""FIRST-HOUR EXPERIMENT: does Tavily Extract work on broker pages?

Usage (from backend/):
    python -m scripts.test_extract --name "First Last" --city "Boston" --state "MA"

Only run this on yourself or a teammate who agreed to it. The report goes to
backend/local/extract-report.json, which is gitignored because it holds real data.
"""

import argparse
import asyncio
import json
import sys

from app import outbound
from app.clients import tavily
from app.config import LOCAL_DIR, get_settings
from app.data import load_json
from app.outbound import MinimalQueryError, assert_minimal_query

REPORT_PATH = LOCAL_DIR / "extract-report.json"


async def check_broker(broker: dict, name: str, city: str, state: str) -> dict:
    row = {"broker": broker["name"], "url": None, "search": "no result", "extract": "-", "chars": 0}
    try:
        data = await tavily.search(
            f'"{name}" {city} {state}'.strip(),
            purpose=f"Look for the listing on {broker['name']}",
            include_domains=[broker["domain"]],
            max_results=3,
        )
        hits = data.get("results", [])
        if not hits:
            return row
        hit = hits[0]
        row.update(url=hit["url"], search="found")
        extracted = await tavily.extract([hit["url"]], purpose=f"Read the {broker['name']} listing")
        results = extracted.get("results", [])
        text = (results[0].get("raw_content") or "") if results else ""
        row["chars"] = len(text)
        last_name = name.split()[-1].lower()
        if not text:
            row["extract"] = "BLOCKED"
        elif len(text) < 500 or last_name not in text.lower():
            row["extract"] = "thin"
        else:
            row["extract"] = "OK"
    except Exception as exc:
        row["search"] = f"error: {str(exc)[:60]}"
    return row


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--state", default="")
    args = parser.parse_args()

    try:
        assert_minimal_query(f"{args.name} {args.city} {args.state}")
    except MinimalQueryError as exc:
        print(f"{exc} Use a name and city only.", file=sys.stderr)
        return 1
    if not get_settings().tavily_api_key:
        print("TAVILY_API_KEY is not set. Add it to .env at the repo root.", file=sys.stderr)
        return 1

    try:
        rows = await asyncio.gather(
            *(check_broker(b, args.name, args.city, args.state) for b in load_json("brokers.json"))
        )
    finally:
        await outbound.close()

    for r in rows:
        print(f"{r['broker']:<18} {r['search']:<12} extract={r['extract']:<8} chars={r['chars']}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps({"report": rows, "outbound": [e.model_dump() for e in outbound.get_log()]}, indent=2),
        encoding="utf-8",
    )
    print(f"\nFull report: {REPORT_PATH}")
    print("Decision: OK brokers use Extract; BLOCKED or thin ones fall back to search snippets.")
    print("Record the result in backend/app/stages/CLAUDE.md (Stage 1).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
