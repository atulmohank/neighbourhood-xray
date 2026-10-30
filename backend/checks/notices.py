"""Shared logic for the power_cuts and water_cuts live checks.

Two windows: the last 30 days (full weight) and 1-12 months ago (half weight).
Two kinds of evidence, always labelled separately:

1. Official notices on the BESCOM / BWSSB pages. The notice table (every row,
   back 12 months) is read straight from the page HTML; if that fails, a
   TinyFish agent run reads the page instead. Each notice document in the
   window (scanned PDF, JPEG, often Kannada) is read by a TinyFish agent and
   cached permanently by URL, since published notices don't change. A notice
   whose document can't be read is reported but never attributed to an area.
2. News reports found with TinyFish Search and read with TinyFish Fetch. A
   report counts only if the fetched article's own publish date is in the
   window, its text names the area and its title describes a cut/outage.
   Same-day reports are one event. News is never called "official".

States: verified (events found), no_reports (official page read, nothing for
this area), could_not_verify (official page unreadable and no news events).
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import ssl
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import truststore

import tinyfish_client as tf
from checks import datasets as ds
from checks.base import could_not_verify, no_reports, now_iso
from checks.places import match_area, match_words

RECENT_DAYS = 30
YEAR_DAYS = 365
OFFICIAL_TTL_SECONDS = 6 * 3600
OFFICIAL_AGENT_MAX_SECONDS = 240  # agent runs on these sites took ~250 s
OFFICIAL_BUDGET_SECONDS = 280
NEWS_BUDGET_SECONDS = 120
MAX_NEWS_ARTICLES = 40  # Fetch is free up to 1,000 URLs/day; Search results vary run to run
MAX_DOCS_PER_SOURCE = 8
# A news report whose title names the area counts fully; a city-wide "full list of areas"
# roundup that only mentions it in the body counts half. Official notices count fully.
CITYWIDE_NEWS_WEIGHT = 0.5

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
DOC_CACHE_DIR = CACHE_DIR / "official_docs"
# TinyFish Search returns a few, varying results per call, so a real report found once can be
# missing the next time. Reports that passed every filter are remembered per source and area
# and merged into later scans while they are still inside the 12-month window.
NEWS_MEMORY_DIR = CACHE_DIR / "news_memory"

PAGE_AGENT_SCHEMA = {
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
                    "urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "date"],
            },
        },
    },
    "required": ["page_loaded", "notices"],
}

DOC_SCHEMA = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "areas": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["areas"],
            },
        },
    },
    "required": ["readable", "events"],
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
        # City-wide outage lists name many areas; the article text must still name ours.
        "city_queries": ["Bengaluru power cut today BESCOM areas", "BESCOM scheduled power outage list Bengaluru"],
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
        "city_queries": ["BWSSB water supply disruption Bengaluru areas", "Bengaluru Cauvery water supply cut areas"],
    },
}

_locks: dict[str, asyncio.Lock] = {}

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}


# ---------- dates and matching ----------

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


def date_in_text(text: str) -> date | None:
    """First date in a table cell: 27.07.2026, 2021-06-16, 27-12-2021, 'JULY 2026', 'FY 2025-26' (FY end)."""
    for m in re.finditer(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2})\b", text):
        d = parse_date(m.group(1).replace("/", "-") if len(m.group(1)) == 10 else m.group(1))
        if d:
            return d
    m = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", text, re.I)
    if m:
        return date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
    m = re.search(r"\bFY\s*(\d{4})\s*-\s*(\d{2})\b", text, re.I)
    if m:
        return date(int(m.group(1)) + 1, 3, 31)
    return None


def names_place(text: str, words: list[str]) -> bool:
    """All place words appear in the text; also matches dotted/joined forms ("H.S.R. Layout", "HSRLayout")."""
    if not words:
        return False
    t = f" {ds.norm(text)} "
    if all(f" {w} " in t for w in words):
        return True
    compact = re.sub(r"[^a-z0-9]", "", t)
    return "".join(words) in compact


def place_words(locality: str) -> list[str]:
    """Kept for callers: parent-area words (see checks/places.py)."""
    return match_words(locality)


# ---------- official pages ----------

def parse_notice_table(page_html: str, base_url: str) -> list[dict[str, Any]]:
    """Every table row with a date: {title, date, urls}."""
    notices = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S | re.I):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        d = date_in_text(" | ".join(cells))
        if not d or not cells:
            continue
        urls = [httpx.URL(base_url).join(html.unescape(u)).__str__()
                for u in re.findall(r'href="([^"]+)"', row) if not u.startswith(("#", "javascript"))]
        # Every descriptive cell, so month labels ("JULY 2026") survive; drop serial numbers and link labels.
        title = " · ".join(c for c in cells if c and not c.isdigit() and c.lower() != "download")
        notices.append({"title": title, "date": d.isoformat(), "urls": list(dict.fromkeys(urls))})
    return notices


# BWSSB serves an incomplete certificate chain; the OS trust store (which fetches the
# missing intermediate) verifies it where Python's bundled CA list fails. Still verified.
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


async def read_page_direct(url: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        timeout=30, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, verify=_SSL
    ) as c:
        r = await c.get(url)
    r.raise_for_status()
    notices = parse_notice_table(r.text, url)
    if not notices:
        raise ValueError("no dated notice rows found on the page")
    return notices


async def read_page_agent(source: dict[str, Any], since: date) -> list[dict[str, Any]]:
    run = await tf.run_agent(
        source["url"],
        f"This {source['label']} page lists {source['what']} notices in a table, often with linked PDF/image "
        f"files. List every notice dated {since.isoformat()} or later: title, date as YYYY-MM-DD, and every "
        "document URL in that row. Do not guess.",
        PAGE_AGENT_SCHEMA,
        max_duration_seconds=OFFICIAL_AGENT_MAX_SECONDS,
    )
    res = run["result"] if isinstance(run["result"], dict) else {}
    if not res.get("page_loaded"):
        raise tf.TinyFishError("the agent could not load the page")
    notices = [n for n in res.get("notices", []) if parse_date(n.get("date"))]
    # An empty list must not become "nothing found": require the agent to have seen the
    # newest notice on the page, so an empty window is a real reading, not a misread.
    latest = parse_date(res.get("latest_notice_date"))
    if not latest:
        raise tf.TinyFishError("the agent did not report the page's latest notice; treating the read as failed")
    notices.append({"title": "(latest notice on page)", "date": latest.isoformat(), "urls": [], "marker": True})
    return notices


async def read_document(source: dict[str, Any], url: str) -> dict[str, Any]:
    """Agent read of one notice document, cached permanently by URL."""
    DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = DOC_CACHE_DIR / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    run = await tf.run_agent(
        url,
        f"Open this {source['label']} {source['what']} notice (it may be a scanned image and may be in Kannada). "
        "For each outage/shutdown it announces, give the date as YYYY-MM-DD and EVERY affected locality/area, "
        "transliterated to English as commonly written (e.g. HSR Layout, Mahadevapura, Banashankari). "
        "Do not guess: if you cannot read it, set readable=false and events=[].",
        DOC_SCHEMA,
        max_duration_seconds=OFFICIAL_AGENT_MAX_SECONDS,
    )
    res = run["result"] if isinstance(run["result"], dict) else {}
    data = {"url": url, "run_id": run["run_id"], "fetched_at": now_iso(),
            "readable": bool(res.get("readable")), "events": res.get("events") or []}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


async def official_notices(source_id: str, today: date) -> dict[str, Any]:
    """Notices from the last 12 months with their documents read; cached 6 h."""
    source = SOURCES[source_id]
    path = CACHE_DIR / f"official_{source_id}.json"
    async with _locks.setdefault(source_id, asyncio.Lock()):
        if path.is_file():
            cached = json.loads(path.read_text(encoding="utf-8"))
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))
            if age.total_seconds() < OFFICIAL_TTL_SECONDS and cached.get("version") == 2:
                return cached
        since = today - timedelta(days=YEAR_DAYS)
        try:
            all_notices, method = await read_page_direct(source["url"]), "page HTML"
        except Exception:
            all_notices, method = await read_page_agent(source, since), "TinyFish agent"
        dated = [n for n in all_notices if parse_date(n["date"])]
        latest = max((parse_date(n["date"]) for n in dated), default=None)
        in_window = [n for n in dated if parse_date(n["date"]) >= since and not n.get("marker")]

        doc_urls = list(dict.fromkeys(u for n in in_window for u in n.get("urls", [])))[:MAX_DOCS_PER_SOURCE]
        docs = await asyncio.gather(*(read_document(source, u) for u in doc_urls), return_exceptions=True)
        doc_by_url = {u: d for u, d in zip(doc_urls, docs) if isinstance(d, dict)}
        for n in in_window:
            n["documents"] = [
                doc_by_url.get(u, {"url": u, "readable": False, "events": [], "error": "not read"})
                for u in n.get("urls", [])
            ]
        data = {
            "version": 2,
            "source_id": source_id,
            "url": source["url"],
            "method": method,
            "fetched_at": now_iso(),
            "latest_notice_date": latest.isoformat() if latest else None,
            "notices": in_window,
        }
        CACHE_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data


def official_events(data: dict[str, Any], words: list[str], since: date) -> tuple[list[dict], list[dict]]:
    """(events naming the area, notices in the window whose documents couldn't be read)."""
    events, unreadable = [], []
    for n in data.get("notices", []):
        notice_date = parse_date(n["date"])
        docs = n.get("documents", [])
        readable = [d for d in docs if d.get("readable")]
        if docs and len(readable) < len(docs):  # any unread document leaves the area list incomplete
            unreadable.append(n)
        matched_dates = set()
        for d in readable:
            for ev in d.get("events", []):
                if names_place(" ".join(ev.get("areas") or []), words):
                    ev_date = parse_date(ev.get("date")) or notice_date
                    if ev_date and ev_date >= since and ev_date not in matched_dates:
                        matched_dates.add(ev_date)
                        events.append({"kind": "official", "title": n["title"], "date": ev_date.isoformat(),
                                       "source_url": d["url"]})
        if not matched_dates and names_place(n["title"], words) and notice_date and notice_date >= since:
            url = (n.get("urls") or [data["url"]])[0]
            events.append({"kind": "official", "title": n["title"], "date": notice_date.isoformat(), "source_url": url})
    return events, unreadable


# ---------- news ----------

async def news_events(source: dict[str, Any], locality: str, since: date) -> tuple[list[dict[str, Any]], int]:
    """(events, articles_checked). Same-day reports are merged into one event."""
    words = match_words(locality)
    place = match_area(locality)
    seen: dict[str, dict[str, Any]] = {}
    searches = [(q.format(place=place), page) for q in source["queries"] for page in (0, 1)]
    searches += [(q, 0) for q in source.get("city_queries", [])]
    ok = 0
    for query, page in searches:
        try:
            results = await tf.search(query, location="IN", language="en", domain_type="news",
                                      after_date=since.isoformat(), page=page)
            ok += 1
        except tf.TinyFishError:
            continue  # one failed query (e.g. rate limit) shouldn't drop all news
        for r in results:
            url = r.get("url") or ""
            if url.startswith("http") and url not in seen and source["topic_re"].search(r.get("title") or ""):
                seen[url] = r
    if not ok:
        raise tf.TinyFishError("every news search failed")
    urls = list(seen)[:MAX_NEWS_ARTICLES]
    articles: list[dict[str, Any]] = []
    for i in range(0, len(urls), 10):
        results, _errors = await tf.fetch(urls[i:i + 10], format="markdown", per_url_timeout_ms=30000)
        articles += results
    by_day: dict[str, dict[str, Any]] = {}
    for a in articles:
        d = parse_date(a.get("published_date"))
        text = a.get("text") if isinstance(a.get("text"), str) else ""
        meta = seen.get(a.get("url"), {})
        title = (a.get("title") or meta.get("title") or "").strip()
        if not d or d < since or not source["topic_re"].search(title) or not names_place(f"{title} {text}", words):
            continue
        scope = "local" if names_place(title, words) else "citywide"
        event = {
            "kind": "news", "scope": scope, "title": title, "date": d.isoformat(),
            "weight": 1.0 if scope == "local" else CITYWIDE_NEWS_WEIGHT,
            "publisher": meta.get("publisher") or meta.get("site_name") or "",
            "source_url": a.get("final_url") or a.get("url"),
        }
        # One event per date; a report about the area beats a city-wide list on the same day.
        prev = by_day.get(d.isoformat())
        if prev is None or (prev["scope"] == "citywide" and scope == "local"):
            by_day[d.isoformat()] = event
    fresh = list(by_day.values())
    return merge_news_memory(source, place, fresh, since), len(articles)


def news_memory_path(source: dict[str, Any], place: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", place.lower()).strip("-") or "unknown"
    return NEWS_MEMORY_DIR / f"{source['label'].lower()}_{slug}.json"


def merge_news_memory(source: dict[str, Any], place: str, fresh: list[dict[str, Any]], since: date) -> list[dict[str, Any]]:
    """Union of this scan's reports and earlier verified ones, one per date (local beats city-wide)."""
    path = news_memory_path(source, place)
    try:
        remembered = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    except (OSError, ValueError):
        remembered = []
    by_day: dict[str, dict[str, Any]] = {}
    for e in remembered + fresh:  # fresh last, so it wins ties
        d = parse_date(e.get("date"))
        if not d or d < since or not (e.get("source_url") or "").startswith("http"):
            continue
        prev = by_day.get(e["date"])
        # Keep a local report over a city-wide list; otherwise the later (fresher) entry wins.
        if prev is None or not (prev.get("scope") == "local" and e.get("scope") == "citywide"):
            by_day[e["date"]] = e
    merged = sorted(by_day.values(), key=lambda e: e["date"], reverse=True)
    try:
        NEWS_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        keep = [{k: e.get(k) for k in ("kind", "scope", "title", "date", "weight", "publisher", "source_url")}
                for e in merged]
        path.write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # memory is best effort
    return merged


# ---------- the check ----------

def fmt_day(d: str) -> str:
    """2026-07-27 -> 27 Jul 2026"""
    return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")


async def run_notices_check(
    check_id: str,
    source_id: str,
    listing: dict[str, Any],
    deduction_for: Callable[[int, int], float],
    area_score: Callable[[str, float], int],
    noun: str,
) -> dict[str, Any]:
    source = SOURCES[source_id]
    locality = listing.get("locality") or ""
    words = match_words(locality)
    if not words:
        return could_not_verify(check_id, f"Could not pick a place name out of '{locality}'.")
    place = match_area(locality)
    today = datetime.now(timezone.utc).date()
    recent_since = today - timedelta(days=RECENT_DAYS)
    year_since = today - timedelta(days=YEAR_DAYS)

    official_res, news_res = await asyncio.gather(
        asyncio.wait_for(official_notices(source_id, today), OFFICIAL_BUDGET_SECONDS),
        asyncio.wait_for(news_events(source, locality, year_since), NEWS_BUDGET_SECONDS),
        return_exceptions=True,
    )

    lines: list[str] = []
    events: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []  # every row a judge can click, incl. unread notices
    official_ok = not isinstance(official_res, BaseException)
    if not official_ok:
        why = "timed out" if isinstance(official_res, asyncio.TimeoutError) else str(official_res)[:160]
        lines.append(f"Official {source['label']} page could not be read ({why}).")
    else:
        off, unreadable = official_events(official_res, words, year_since)
        for e in off:
            e["weight"] = 1.0
        events += off
        latest = official_res.get("latest_notice_date")
        evidence.append({"date": latest, "title": f"Notice list ({len(official_res.get('notices', []))} in past 12 months)",
                         "label": f"Official {source['label']} page", "source_url": source["url"]})
        for n in unreadable:
            evidence.append({"date": n["date"], "title": n["title"],
                             "label": f"Official {source['label']} notice — couldn't be fully read",
                             "source_url": next((d["url"] for d in n.get("documents", []) if not d.get("readable")),
                                                (n.get("urls") or [source["url"]])[0])})
        n_window = len(official_res.get("notices", []))
        lines.append(
            f"Official {source['label']} page read ({official_res.get('method')}): {n_window} notice"
            f"{'s' * (n_window != 1)} in the past 12 months, {len(off)} naming {place}; "
            f"page last updated {fmt_day(latest) if latest else 'unknown'}."
        )
        if unreadable:
            lines.append(
                f"{len(unreadable)} official notice{'s' * (len(unreadable) != 1)} in the window could not be read "
                "(scanned image or legacy-font Kannada), so their area lists are incomplete: "
                + "; ".join(f"{n['title']} ({fmt_day(n['date'])})" for n in unreadable)
            )

    news_failed = isinstance(news_res, BaseException)
    if news_failed:
        why = "timed out" if isinstance(news_res, asyncio.TimeoutError) else str(news_res)[:160]
        # Search is down: fall back to reports that passed every filter on earlier scans.
        remembered = merge_news_memory(source, place, [], year_since)
        events += remembered
        lines.append(f"News search could not be completed now ({why}); "
                     f"using {len(remembered)} report{'s' * (len(remembered) != 1)} verified on earlier scans.")
    else:
        news, checked = news_res
        events += news
        lines.append(f"News: {len(news)} report{'s' * (len(news) != 1)} naming {place} in 12 months "
                     f"({checked} articles checked).")

    events.sort(key=lambda e: e["date"], reverse=True)
    for e in events:
        if e["kind"] == "official":
            e["label"] = f"Official {source['label']} notice"
        else:
            e["label"] = f"News report — {e['publisher']}" + (" (city-wide list)" if e["scope"] == "citywide" else "")
        e["window"] = "30d" if parse_date(e["date"]) >= recent_since else "12m"
    evidence = events + evidence
    for e in reversed(events):
        lines.insert(0, f"{e['label']}, {fmt_day(e['date'])}: {e['title']} ({e['source_url']})")

    recent = [e for e in events if e["window"] == "30d"]
    older = [e for e in events if e["window"] == "12m"]
    plural = f"{noun}s"

    if not events:
        if not official_ok:
            result = could_not_verify(check_id, lines[0])
            result["details"] = lines
            result["source_url"] = source["url"]
            return result
        latest = official_res.get("latest_notice_date")
        headline = f"No {plural} reported for {place} in the past 12 months"
        if unreadable:
            # Don't let unreadable notices read as "nothing here".
            headline += (f" · {len(unreadable)} official notice{'s' * (len(unreadable) != 1)} "
                         "couldn't be fully read")
        result = no_reports(
            check_id,
            headline,
            lines,
            source["url"],
            tag=f"None · page updated {fmt_day(latest)}" if latest else "None reported",
        )
        result["evidence"] = evidence
        return mark_partial(result, unreadable, news_failed)

    def describe(evs: list[dict[str, Any]]) -> str:
        n_off = sum(e["kind"] == "official" for e in evs)
        n_local = sum(e["kind"] == "news" and e["scope"] == "local" for e in evs)
        n_city = len(evs) - n_off - n_local
        parts = []
        if n_off:
            parts.append(f"{n_off} official notice{'s' * (n_off != 1)}")
        if n_local:
            parts.append(f"{n_local} news report{'s' * (n_local != 1)} about {place}")
        if n_city:
            parts.append(f"{n_city} city-wide list{'s' * (n_city != 1)}")
        return " + ".join(parts)

    head_recent = f"{len(recent)} {noun if len(recent) == 1 else plural} in last 30 days ({describe(recent)})" \
        if recent else f"No {plural} in last 30 days"
    head_year = f"{describe(older)} in past 12 months" if older else "none earlier in past 12 months"
    headline = f"{head_recent} · {head_year} (latest {fmt_day(events[0]['date'])})"
    recent_w = sum(e["weight"] for e in recent)
    older_w = sum(e["weight"] for e in older)
    lines.append(f"Weighting: last 30 days full, 1-12 months half; city-wide lists count {CITYWIDE_NEWS_WEIGHT:g}x "
                 f"(weighted {recent_w:g} recent + {older_w:g} older).")
    result = {
        "id": check_id,
        "status": "verified",
        "score": area_score(check_id, deduction_for(recent_w, older_w)),
        "tag": f"{len(recent)} in 30d · {len(events)} in 12m",
        "headline": headline,
        "details": lines,
        "findings": events,
        "evidence": evidence,
        "source_url": events[0]["source_url"],
        "fetched_at": now_iso(),
    }
    return mark_partial(result, unreadable, news_failed)


def mark_partial(result: dict[str, Any], unreadable: list[dict[str, Any]], news_failed: bool = False) -> dict[str, Any]:
    """Flag lower confidence when official notices couldn't be read or the news search failed."""
    notes = []
    if unreadable:
        notes.append(f"{len(unreadable)} official notice{'s' * (len(unreadable) != 1)} couldn't be fully read")
    if news_failed:
        notes.append("the news search failed during this scan")
        result["degraded"] = True  # never saved as a demo cache
    if notes:
        result["confidence"] = "partial"
        result["partial_note"] = " and ".join(notes).capitalize() + ", so this may miss cuts"
    return result
