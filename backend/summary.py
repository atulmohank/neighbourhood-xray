"""Summary and owner-question generation (PLACEHOLDER).

Future: an LLM will write the plain-language summary and owner questions from
the check results. Until then this module only restates what the checks
returned. It must never add facts that are not in the check results.
"""

from __future__ import annotations

from typing import Any

PLACEHOLDER_NOTE = "[Placeholder summary — LLM summaries not implemented yet]"

# Generic questions keyed by check id. They ask about a topic; they do not
# assert anything about the listing.
_TOPIC_QUESTIONS: dict[str, str] = {
    "water_supply": "How often does the water supply stop, and for how long?",
    "power": "How often does the power go out, and is there backup?",
    "flood_risk": "Has the street or building flooded during recent monsoons?",
    "rent_value": "Is the rent negotiable, given comparable listings nearby?",
    "water_source": "Is the water from the municipal line, a borewell or tankers?",
}


def build_summary(checks: list[dict[str, Any]]) -> str:
    usable = [c for c in checks if c["status"] != "could_not_verify"]
    missing = [c["id"] for c in checks if c["status"] == "could_not_verify"]
    parts = [PLACEHOLDER_NOTE]
    if usable:
        parts.append(" ".join(f"{c['headline']}." for c in usable))
    if missing:
        parts.append("Could not verify: " + ", ".join(missing) + ".")
    return " ".join(parts)


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
