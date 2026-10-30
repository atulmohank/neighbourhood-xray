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
    "Each check has a 'state'. Use its wording exactly: 'verified finding' = report the finding; "
    "'no reports found' = say no reports were found (never call it unverified); "
    "'could not verify' = say it could not be verified (only for those). Do not give advice."
)

STATE_TEXT = {
    "verified": "verified finding",
    "no_reports": "no reports found",
    "could_not_verify": "could not verify",
    "stub": "demo data",
}
UNVERIFIED_WORDS = re.compile(r"could not (be )?verif|couldn.t (be )?verif|not verified|unverified|unconfirmed", re.I)

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
    """Template summary: restates check headlines, worded by state."""
    def names(status: str) -> list[str]:
        return [c["id"].replace("_", " ") for c in checks if c["status"] == status]

    parts = [f"{c['headline']}." for c in checks if c["status"] in {"verified", "stub"}]
    if names("no_reports"):
        parts.append("No reports found: " + ", ".join(names("no_reports")) + ".")
    if names("could_not_verify"):
        parts.append("Could not verify: " + ", ".join(names("could_not_verify")) + ".")
    return " ".join(parts)


def wording_matches_states(text: str, checks: list[dict[str, Any]]) -> bool:
    """'Could not verify' language is only allowed when some check really is could_not_verify."""
    return bool(not UNVERIFIED_WORDS.search(text) or any(c["status"] == "could_not_verify" for c in checks))


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
            {"id": c["id"], "state": STATE_TEXT.get(c["status"], c["status"]), "headline": c["headline"],
             "details": c.get("details", [])[:4]}
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
    if (
        not text
        or len(text.split()) > SUMMARY_MAX_WORDS
        or not numbers_grounded(text, facts_json)
        or not wording_matches_states(text, report.get("checks", []))
    ):
        return fallback, "template"
    return text, "llm"


def build_owner_items(checks: list[dict[str, Any]], area_scores: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Owner questions with where each came from ("From: power check")."""
    by_id = {a["id"]: a for a in area_scores}
    items = []
    for check in checks:
        area = by_id.get(check["id"], {})
        # Ask when the check couldn't verify, scored watch/risk, or found reported cuts/spots.
        if check["status"] == "could_not_verify" or area.get("level") in {"watch", "risk"} or check.get("findings"):
            q = _TOPIC_QUESTIONS.get(check["id"])
            if q:
                label = (area.get("label") or check["id"].replace("_", " ")).lower()
                items.append({"text": q, "from": f"{label} check", "check_id": check["id"]})
    return items


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
