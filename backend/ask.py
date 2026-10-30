"""Ask tab: answer a question using ONLY one scan's findings (Groq).

The model sees a numbered list of the scan's sources and its facts, and must
cite sources by number; links come from that list, so it can't invent a URL.
Answers with a number that isn't in the scan, malformed replies and any error
fall back to "Not in this scan" plus a question to ask the owner.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from scoring import AREA_LABELS
from summary import GROQ_CHAT_URL, llm_enabled, numbers_grounded

ASK_TIMEOUT_SECONDS = 10
ASK_MAX_WORDS = 60
NOT_IN_SCAN = "Not in this scan."
LLM_BUSY = "Couldn't answer right now (the answer service is busy or unreachable). Try again in a minute."
MAX_DETAIL_CHARS = 220  # keep each question well under Groq's free-tier tokens-per-minute limit
MAX_FINDINGS_PER_CHECK = 5

SYSTEM_PROMPT = (
    "You answer a renter's question about a Bengaluru neighbourhood using ONLY the scan JSON you are given. "
    f"Reply with JSON only: {{\"in_scan\": true|false, \"answer\": \"<= {ASK_MAX_WORDS} words\", "
    "\"sources\": [source numbers you used], \"owner_question\": \"one question the renter could ask the owner\"}. "
    "If the scan does not answer the question, set in_scan=false and answer=\"\". Do not add facts, numbers, "
    "dates or places that are not in the scan. Base the answer on the relevant check's headline and keep its "
    "counts and time windows (last 30 days / past 12 months) exactly. Name the kind of source for every fact "
    "('news report', 'official notice', 'dataset', 'listing') exactly as the scan labels it; never turn news "
    "reports into official notices. Never claim official notices show nothing when the scan says notices "
    "couldn't be fully read. Checks with status could_not_verify were not verified; no_reports means the "
    "source was read and had nothing for this area. Never say something 'did not occur', 'has not happened' "
    "or 'there have been no ...': say it was 'not reported in this scan' or 'none reported in this scan'."
)

# Topic -> check, used for the answer's state tag when the model cites no source.
TOPIC_CHECKS = [
    (r"water supply|water cut|tanker|no water|water bad|water", "water_cuts"),
    (r"power|electric|outage|backup", "power_cuts"),
    (r"flood|rain|waterlog|monsoon|drain", "flooding"),
    (r"rent|price|deposit|negotia|fair|cheap|expensive", "rent_compare"),
    (r"borewell|cauvery|corporation|source of water|water source", "water_source"),
]

# "No power cuts have occurred" overstates what a scan can know; say what was (not) reported.
_OVERCLAIMS = [
    (re.compile(r"\b(no|zero) ([\w-]+(?: [\w-]+){0,3}) (?:have|has|had) (?:occurred|happened|taken place)", re.I),
     r"\1 \2 were reported in this scan"),
    (re.compile(r"\b(no|zero) ([\w-]+(?: [\w-]+){0,3}) (?:have|has) been (?:reported|recorded|seen)", re.I),
     r"\1 \2 were reported in this scan"),
    (re.compile(r"\bthere (?:have|has) been no\b", re.I), "this scan found no reports of"),
    (re.compile(r"\b(?:did|has|have) not (?:occur|occurred|happen|happened)\b", re.I), "was not reported in this scan"),
]


def soften_overclaims(text: str) -> str:
    for rx, repl in _OVERCLAIMS:
        text = rx.sub(repl, text)
    # Re-capitalise sentence starts the replacements may have lowered.
    return re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)


def check_states_for(report: dict[str, Any], used: list[dict[str, str]], question: str) -> list[dict[str, str]]:
    """State tag(s) for an answer: the checks behind its cited sources, else the question's topic."""
    by_id = {c["id"]: c for c in report.get("checks", [])}
    ids = [s["check_id"] for s in used if s.get("check_id") in by_id]
    if not ids:
        ids = [cid for rx, cid in TOPIC_CHECKS if re.search(rx, question, re.I) and cid in by_id][:1]
    out = []
    for cid in dict.fromkeys(ids):
        out.append({"check_id": cid, "label": AREA_LABELS.get(cid, cid), "status": by_id[cid]["status"]})
    return out

TOPIC_OWNER_QUESTIONS = [
    (r"water|tanker|borewell|cauvery", "How often does the water supply stop, and does the building use tankers?"),
    (r"power|electric|outage|backup", "How often does the power go out, and is there power backup?"),
    (r"flood|rain|waterlog|monsoon", "Has the street or building flooded in recent monsoons?"),
    (r"rent|price|deposit|negotia|fair", "Is the rent negotiable, given similar flats nearby?"),
    (r"safe|night|crime|police", "How safe is the area at night, according to current tenants?"),
    (r"commute|metro|bus|traffic|orr", "What is the peak-hour commute from here to your workplace?"),
]


def owner_question_for(question: str) -> str:
    for pattern, q in TOPIC_OWNER_QUESTIONS:
        if re.search(pattern, question, re.I):
            return q
    return f"Could you tell me more about this: {question.strip().rstrip('?')}?"


def scan_context(report: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """(facts for the model, numbered sources). Sources are deduplicated by URL."""
    sources: list[dict[str, str]] = []

    def source_no(url: str | None, label: str, check_id: str) -> int | None:
        if not url or not url.startswith("http"):
            return None
        for i, s in enumerate(sources, 1):
            if s["url"] == url:
                return i
        sources.append({"label": label, "url": url, "check_id": check_id})
        return len(sources)

    checks = []
    for c in report.get("checks", []):
        # Findings are passed separately below, so details only need the non-finding lines.
        details = [d[:MAX_DETAIL_CHARS] for d in c.get("details", []) if not d.startswith(("News report", "Official"))]
        item = {"id": c["id"], "status": c["status"], "headline": c["headline"], "details": details[:4]}
        n = source_no(c.get("source_url"), AREA_LABELS.get(c["id"], c["id"]), c["id"])
        if n:
            item["source"] = n
        findings = []
        for f in (c.get("findings", []) or [])[:MAX_FINDINGS_PER_CHECK]:
            fn = source_no(f.get("source_url"), f.get("label") or c["id"], c["id"])
            findings.append({"label": f.get("label"), "date": f.get("date"), "title": f.get("title"), "source": fn})
        if findings:
            item["findings"] = findings
        checks.append(item)
    rc = report.get("rent_compare") or {}
    facts = {
        "listing": {k: report.get("listing", {}).get(k) for k in ("locality", "rent", "bhk")},
        "score": report.get("score"),
        "verdict": report.get("verdict"),
        "checks": checks,
        "rent_compare": {k: rc.get(k) for k in ("status", "median", "fair_range", "premium_percent", "portals")}
        if rc.get("status") == "verified" else {"status": rc.get("status")},
        "questions_for_owner": report.get("questions_for_owner", []),
    }
    return facts, sources


def not_in_scan(question: str, sources_used: list | None = None) -> dict[str, Any]:
    return {"in_scan": False, "answer": NOT_IN_SCAN, "sources": [], "owner_question": owner_question_for(question),
            "method": "fallback" if sources_used is None else "llm"}


async def answer(report: dict[str, Any], question: str) -> dict[str, Any]:
    facts, sources = scan_context(report)
    if not llm_enabled():
        return not_in_scan(question)
    facts_json = json.dumps({"facts": facts, "sources": {i: s["label"] for i, s in enumerate(sources, 1)}},
                            ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=ASK_TIMEOUT_SECONDS) as client:
            r = await client.post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
                json={
                    "model": os.environ["LLM_MODEL"],
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"SCAN: {facts_json}\n\nQUESTION: {question}"},
                    ],
                    "temperature": 0.1,
                    "max_completion_tokens": 800,
                    "reasoning_effort": "low",
                },
            )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content") or ""
        m = re.search(r"\{.*\}", content, re.S)
        reply = json.loads(m.group(0)) if m else {}
    except Exception:
        # An error is not an answer: never present it as "Not in this scan".
        return {"in_scan": False, "answer": LLM_BUSY, "sources": [], "owner_question": owner_question_for(question),
                "method": "error"}

    owner_q = str(reply.get("owner_question") or "").strip() or owner_question_for(question)
    text = soften_overclaims(" ".join(str(reply.get("answer") or "").split()))
    if not reply.get("in_scan") or not text:
        return {**not_in_scan(question, []), "owner_question": owner_q}
    if len(text.split()) > ASK_MAX_WORDS + 15 or not numbers_grounded(text, facts_json):
        return not_in_scan(question)
    used = []
    for n in reply.get("sources") or []:
        try:
            i = int(n)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(sources) and sources[i - 1] not in used:
            used.append(sources[i - 1])
    # The model's owner question can drift off-topic when it did answer; use the topic list then.
    return {"in_scan": True, "answer": text, "sources": used, "owner_question": owner_question_for(question),
            "check_states": check_states_for(report, used, question), "method": "llm"}
