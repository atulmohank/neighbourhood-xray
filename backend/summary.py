"""Report summary (LLM, with template fallback) and owner questions.

The LLM (Groq, OpenAI-compatible chat API) only sees the report's own check
results and is told to use nothing else. Any error, a timeout, an empty reply
or a reply containing a number that isn't in the report falls back to the
template, so the summary never adds findings.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
LLM_TIMEOUT_SECONDS = 10
SUMMARY_TARGET_WORDS = 60

SUMMARY_MAX_WORDS = 90  # longer replies fall back to the template

SYSTEM_PROMPT = (
    "You summarise a neighbourhood check for someone about to rent a flat in Bengaluru. "
    f"Write {SUMMARY_TARGET_WORDS} words or fewer of plain prose in 2-3 sentences, no lists or markdown. "
    "Use ONLY the facts in the JSON you are given: do not add places, numbers, dates, sources or claims. "
    "Only call something an official notice, a news report or a dataset if the fact text itself says so; "
    "otherwise do not name a source type. Keep numbers exactly as given (digits). "
    "Say briefly which checks could not be verified. Do not give advice."
)

# Generic questions keyed by check id. They ask about a topic; they do not
# assert anything about the listing.
_TOPIC_QUESTIONS: dict[str, str] = {
    "water_cuts": "How often does the water supply stop, and for how long?",
    "power_cuts": "How often does the power go out, and is there backup?",
    "flooding": "Has the street or building flooded during recent monsoons?",
    "rent_compare": "Is the rent negotiable, given comparable listings nearby?",
    "water_source": "Is the water from the municipal line, a borewell or tankers?",
}


def build_summary(checks: list[dict[str, Any]]) -> str:
    """Template summary: restates check headlines only."""
    usable = [c for c in checks if c["status"] != "could_not_verify"]
    missing = [c["id"].replace("_", " ") for c in checks if c["status"] == "could_not_verify"]
    parts = []
    if usable:
        parts.append(" ".join(f"{c['headline']}." for c in usable))
    if missing:
        parts.append("Could not verify: " + ", ".join(missing) + ".")
    return " ".join(parts)


def llm_enabled() -> bool:
    return os.getenv("LLM_PROVIDER", "").lower() == "groq" and bool(os.getenv("LLM_API_KEY")) and bool(
        os.getenv("LLM_MODEL")
    )


def summary_facts(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "locality": report.get("listing", {}).get("locality"),
        "score": report.get("score"),
        "verdict": report.get("verdict"),
        "checks": [
            {"id": c["id"], "status": c["status"], "headline": c["headline"], "details": c.get("details", [])[:4]}
            for c in report.get("checks", [])
        ],
    }


def numbers_grounded(text: str, facts_json: str) -> bool:
    return all(n in facts_json for n in re.findall(r"\d+(?:[.,]\d+)?", text))


async def generate_summary(report: dict[str, Any]) -> tuple[str, str]:
    """Returns (summary, method) where method is "llm" or "template"."""
    fallback = build_summary(report.get("checks", []))
    if not llm_enabled():
        return fallback, "template"
    facts_json = json.dumps(summary_facts(report), ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            r = await client.post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
                json={
                    "model": os.environ["LLM_MODEL"],
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": facts_json},
                    ],
                    "temperature": 0.2,
                    "max_completion_tokens": 800,
                    "reasoning_effort": "low",
                },
            )
        r.raise_for_status()
        text = " ".join((r.json()["choices"][0]["message"].get("content") or "").split())
    except Exception:  # timeout, HTTP error, bad JSON: never block the report on the LLM
        return fallback, "template"
    if not text or len(text.split()) > SUMMARY_MAX_WORDS or not numbers_grounded(text, facts_json):
        return fallback, "template"
    return text, "llm"


def build_owner_questions(checks: list[dict[str, Any]], area_scores: list[dict[str, Any]]) -> list[str]:
    """Ask about areas that scored below 'good' or could not be verified."""
    by_id = {a["id"]: a for a in area_scores}
    questions = []
    for check in checks:
        area = by_id.get(check["id"], {})
        if check["status"] == "could_not_verify" or area.get("level") in {"watch", "risk"}:
            q = _TOPIC_QUESTIONS.get(check["id"])
            if q:
                questions.append(q)
    return questions
