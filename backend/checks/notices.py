"""Shared logic for the power_cuts and water_cuts live checks.

Two kinds of evidence, always labelled separately:

1. Official notices (BESCOM / BWSSB pages) read by a TinyFish agent run with an
   Indian proxy. The page is the same for every locality, so one agent run is
   cached for OFFICIAL_TTL_SECONDS and filtered locally per locality.
2. News reports found with TinyFish Search, then fetched with TinyFish Fetch.
   A report counts only if the fetched article's own published date is within
   the window, its text names the locality, and its title is about the topic.
   News is shown as "News report", never as an official notice.

Nothing found in either -> could_not_verify (no deduction).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import tinyfish_client as tf
from checks import datasets as ds
from checks.base import could_not_verify, now_iso

WINDOW_DAYS = 30
OFFICIAL_TTL_SECONDS = 6 * 3600
OFFICIAL_AGENT_MAX_SECONDS = 240  # smoke test runs on these sites took ~250 s
OFFICIAL_BUDGET_SECONDS = 270
NEWS_BUDGET_SECONDS = 90
MAX_NEWS_ARTICLES = 10

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"

OFFICIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "page_loaded": {"type": "boolean"},
        "latest_notice_date": {"type": "string"},
        "notices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "areas": {"type": "array", "items": {"type": "string"}},
                    "url": {"type": "string"},
                },
                "required": ["title", "date", "url"],
            },
        },
    },
    "required": ["page_loaded", "notices"],
}

SOURCES: dict[str, dict[str, Any]] = {
    "bescom": {
        "label": "BESCOM",
        "url": "https://bescom.karnataka.gov.in/421/Contingency-Power-Outages/en",
        "what": "power outage",
        # The title must describe an actual outage, not just mention BESCOM.
        "topic_re": re.compile(
            r"power cuts?\b|power outages?|\boutages?\b|no power|power (supply )?(disruption|interruption|shutdown)"
            r"|load.?shedding",
            re.I,
        ),
        "queries": ["BESCOM power cut {place}", "power outage {place} Bengaluru"],
    },
    "bwssb": {
        "label": "BWSSB",
        "url": "https://bwssb.karnataka.gov.in/109/Press-Release/en",
        "what": "water supply shutdown/disruption",
        "topic_re": re.compile(
            r"water (supply )?(cuts?|disruption|interruption|shutdown|shut ?down|outage)|no water"
            r"|water supply (hit|affected|disrupted|suspended|stopped)|without water",
            re.I,
        ),
        "queries": ["BWSSB water supply {place}", "water supply disruption {place} Bengaluru"],
    },
}

_locks: dict[str, asyncio.Lock] = {}


def official_goal(source: dict[str, Any], cutoff: date) -> str:
    return (
        f"This {source['label']} page lists {source['what']} notices, often as linked PDF or image files. "
        f"List every notice dated {cutoff.isoformat()} or later. For each give the title, the date as YYYY-MM-DD, "
        "the affected localities/areas exactly as written on the page or in the linked notice, and the URL of the "
        "notice or document. Do not guess: if a linked document cannot be opened, leave its areas empty. Also give "
        "the date of the most recent notice on the page, and say whether the page loaded."
    )


def parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(v[:10], fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def place_words(locality: str) -> list[str]:
    """Words of the broadest named area: localities run small to large
    ("Rajiv Gandhi Nagar, HSR Layout Sector 7, Bengaluru" -> ["hsr"]), and news
    names the larger area; small names like "Rajiv Gandhi" recur across the city."""
    parts = [ds.place_words(p) for p in locality.split(",")]
    named = [p for p in parts if p]
    return named[-1] if named else []


def names_place(text: str, words: list[str]) -> bool:
    t = f" {ds.norm(text)} "
    return bool(words) and all(f" {w} " in t for w in words)


async def official_notices(source_id: str, today: date) -> dict[str, Any]:
    """Agent-extracted notice list for one official page, cached on disk."""
    source = SOURCES[source_id]
    path = CACHE_DIR / f"official_{source_id}.json"
    async with _locks.setdefault(source_id, asyncio.Lock()):
        if path.is_file():
            cached = json.loads(path.read_text(encoding="utf-8"))
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))
            if age.total_seconds() < OFFICIAL_TTL_SECONDS:
                return cached
        cutoff = today - timedelta(days=WINDOW_DAYS)
        run = await tf.run_agent(
            source["url"],
            official_goal(source, cutoff),
            OFFICIAL_SCHEMA,
            max_duration_seconds=OFFICIAL_AGENT_MAX_SECONDS,
        )
        result = run["result"] if isinstance(run["result"], dict) else {}
        data = {
            "source_id": source_id,
            "url": source["url"],
            "run_id": run["run_id"],
            "fetched_at": now_iso(),
            "page_loaded": bool(result.get("page_loaded")),
            "latest_notice_date": result.get("latest_notice_date"),
            "notices": result.get("notices") or [],
            "raw": run["result"],
        }
        CACHE_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data


def official_hits(data: dict[str, Any], words: list[str], cutoff: date) -> list[dict[str, Any]]:
    hits = []
    for n in data.get("notices", []):
        d = parse_date(n.get("date"))
        url = n.get("url") or ""
        if not d or d < cutoff or not url.startswith("http"):
            continue
        if names_place(" ".join([n.get("title", "")] + list(n.get("areas") or [])), words):
            hits.append({"kind": "official", "title": n.get("title", ""), "date": d.isoformat(), "source_url": url})
    return hits


async def news_hits(source: dict[str, Any], locality: str, cutoff: date) -> tuple[list[dict[str, Any]], int]:
    """Returns (hits, articles_checked)."""
    words = place_words(locality)
    place = " ".join(words) or locality
    seen: dict[str, dict[str, Any]] = {}
    for q in source["queries"]:
        results = await tf.search(
            q.format(place=place), location="IN", language="en", domain_type="news", after_date=cutoff.isoformat()
        )
        for r in results:
            url = r.get("url") or ""
            if url.startswith("http") and url not in seen and source["topic_re"].search(r.get("title") or ""):
                seen[url] = r
    urls = list(seen)[:MAX_NEWS_ARTICLES]
    if not urls:
        return [], 0
    results, _errors = await tf.fetch(urls, format="markdown", per_url_timeout_ms=30000)
    hits = []
    for a in results:
        d = parse_date(a.get("published_date"))
        text = a.get("text") if isinstance(a.get("text"), str) else ""
        title = a.get("title") or seen.get(a.get("url"), {}).get("title") or ""
        if not d or d < cutoff or not names_place(f"{title} {text}", words):
            continue
        if not source["topic_re"].search(title):
            continue
        meta = seen.get(a.get("url"), {})
        hits.append({
            "kind": "news",
            "title": title.strip(),
            "date": d.isoformat(),
            "publisher": meta.get("publisher") or meta.get("site_name") or "",
            "source_url": a.get("final_url") or a.get("url"),
        })
    return hits, len(results)


async def run_notices_check(
    check_id: str,
    source_id: str,
    listing: dict[str, Any],
    deduction_for: Callable[[int], float],
    area_score: Callable[[str, float], int],
    noun: str,
) -> dict[str, Any]:
    source = SOURCES[source_id]
    locality = listing.get("locality") or ""
    words = place_words(locality)
    if not words:
        return could_not_verify(check_id, f"Could not pick a place name out of '{locality}'.")
    place = " ".join(w.upper() if len(w) <= 3 else w.title() for w in words)
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=WINDOW_DAYS)

    official_res, news_res = await asyncio.gather(
        asyncio.wait_for(official_notices(source_id, today), OFFICIAL_BUDGET_SECONDS),
        asyncio.wait_for(news_hits(source, locality, cutoff), NEWS_BUDGET_SECONDS),
        return_exceptions=True,
    )

    lines: list[str] = []
    findings: list[dict[str, Any]] = []
    if isinstance(official_res, BaseException):
        why = "timed out" if isinstance(official_res, asyncio.TimeoutError) else str(official_res)[:160]
        lines.append(f"Official {source['label']} page could not be checked ({why}).")
    elif not official_res.get("page_loaded"):
        lines.append(f"Official {source['label']} page did not load for the TinyFish agent.")
    else:
        off = official_hits(official_res, words, cutoff)
        findings += off
        if not off:
            latest = official_res.get("latest_notice_date") or "unknown"
            lines.append(
                f"No official {source['label']} notice naming {place} since {cutoff.isoformat()} "
                f"(latest notice on the page: {latest})."
            )

    if isinstance(news_res, BaseException):
        why = "timed out" if isinstance(news_res, asyncio.TimeoutError) else str(news_res)[:160]
        lines.append(f"News search could not be completed ({why}).")
    else:
        hits, checked = news_res
        findings += hits
        if not hits:
            lines.append(f"No news report naming {place} since {cutoff.isoformat()} ({checked} articles checked).")

    for f in findings:
        label = (
            f"Official {source['label']} notice" if f["kind"] == "official" else f"News report — {f['publisher']}"
        )
        f["label"] = label
        lines.insert(0, f"{label}, {f['date']}: {f['title']} ({f['source_url']})")

    if not findings:
        result = could_not_verify(check_id, " ".join(lines))
        result["details"] = lines
        result["source_url"] = source["url"]
        return result

    n = len(findings)
    n_official = sum(f["kind"] == "official" for f in findings)
    deduction = deduction_for(n)
    basis = (
        f"{n_official} official notice{'s' * (n_official != 1)}"
        if n_official == n
        else f"{n - n_official} news report{'s' * (n - n_official != 1)}"
        + (f" + {n_official} official notice{'s' * (n_official != 1)}" if n_official else "")
    )
    return {
        "id": check_id,
        "status": "verified",
        "score": area_score(check_id, deduction),
        "tag": f"{n} in 30 days",
        "headline": f"{n} {noun}{'s' * (n != 1)} for {place} in the last 30 days ({basis})",
        "details": lines,
        "findings": findings,
        "source_url": findings[0]["source_url"],
        "fetched_at": now_iso(),
    }
