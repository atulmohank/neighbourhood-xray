"""Residents: what people post about the area (NOT scored).

TinyFish Search finds posts from the last 12 months on Reddit, then X (Quora is
tried too); TinyFish Fetch reads the top threads. A thread counts only if its own
post date is in the window and its text names the area. Quotes are verbatim
sentences of at most QUOTE_MAX_WORDS words that mention a topic; sentences with
usernames, handles or links are skipped and nothing is paraphrased. Theme counts
are threads mentioning the theme (one per thread). Sentiment is a simple word-list
label, marked as automatic in the UI.

A site that blocks fetching or needs a login is reported as could_not_verify for
that site; it is never worked around. Results are cached per locality for 6 h.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import tinyfish_client as tf
from checks.notices import names_place, parse_date
from checks.places import match_area, match_words

CHECK_ID = "residents"
WINDOW_DAYS = 365
CACHE_TTL_SECONDS = 6 * 3600
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "residents"
QUOTE_MIN_WORDS, QUOTE_MAX_WORDS = 6, 25
MAX_QUOTES = 8
MAX_QUOTES_PER_THREAD = 2

SITES = [
    {"name": "Reddit", "domains": "reddit.com", "max_threads": 8,
     "topics": ["water tanker", "power cut", "flooding waterlogging", "rent landlord", "traffic"]},
    {"name": "X", "domains": "x.com,twitter.com", "max_threads": 5,
     "topics": ["water", "power cut", "flooding"]},
    {"name": "Quora", "domains": "quora.com", "max_threads": 2, "topics": ["living"]},
]

THEMES = [
    ("water", "Water / tankers", re.compile(r"\b(water|tankers?|borewell|cauvery|bwssb|sump)\b", re.I)),
    ("power", "Power cuts", re.compile(r"\b(power (cut|outage)s?|outages?|bescom|electricity|no power)\b", re.I)),
    ("flooding", "Flooding / waterlogging", re.compile(r"\b(flood\w*|waterlog\w*|inundat\w*|drains?)\b", re.I)),
    ("rent", "Rent / landlords", re.compile(r"\b(rents?|rental|landlords?|owners?|deposit|brokerage)\b", re.I)),
    ("traffic", "Traffic", re.compile(r"\b(traffic|commute|silk board|jam|congestion)\b", re.I)),
]
POSITIVE_RE = re.compile(r"\b(good|great|nice|love|lovely|peaceful|better|best|clean|safe|rarely|convenient|happy)\b", re.I)
NEGATIVE_RE = re.compile(
    r"\b(no water|cuts?|outages?|stink\w*|contaminat\w*|sewage|problem|issues?|worst|bad|terrible|flood\w*|"
    r"waterlog\w*|expensive|inflated|overpriced|crisis|frequent|constant|hell|jam)\b", re.I)
# Official/agency accounts on X are not residents (matched on the URL only; never displayed).
OFFICIAL_X_ACCOUNTS = re.compile(
    r"x\.com/(chairmanbwssb|NammaBESCOM|GBA_office|BBMPCOMM|BBMP_MAYOR|blrcitytraffic|BlrCityPolice|"
    r"KarnatakaVarthe|CMofKarnataka|DKShivakumar|BMRCL|NammaMetro_|RAshokaBJP)/", re.I)
SITE_ORDER = {"Reddit": 0, "X": 1, "Quora": 2}
# Usernames, handles, links, page chrome, and X page titles ("<Name> on X: ...") never become quotes.
NOT_A_QUOTE = re.compile(
    r"\bu/\w|@\w|\br/\w|https?://|www\.|log in|sign up|\[deleted\]|\[removed\]|\bon (X|Twitter)\b\s*:?", re.I)


def sentiment(text: str) -> str:
    neg, pos = bool(NEGATIVE_RE.search(text)), bool(POSITIVE_RE.search(text))
    return "mixed" if neg and pos else "negative" if neg else "positive" if pos else "neutral"


def age_text(d: date, today: date) -> str:
    days = (today - d).days
    if days < 30:
        return f"{max(days, 0)} days ago" if days != 1 else "1 day ago"
    months = days // 30
    return f"{months} month{'s' * (months != 1)} ago"


def clean_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)  # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> their text
    text = re.sub(r"[#*_>`|]+", " ", text)
    return text


def candidate_quotes(text: str) -> list[str]:
    """Verbatim sentences (after removing markdown symbols) of 6-25 words that mention a topic."""
    out = []
    for line in clean_markdown(text).splitlines():
        for sent in re.split(r"(?<=[.!?])\s+", line.strip()):
            s = " ".join(sent.split()).strip(" -–—\"'“”‘’")
            words = s.split()
            if not (QUOTE_MIN_WORDS <= len(words) <= QUOTE_MAX_WORDS) or NOT_A_QUOTE.search(s):
                continue
            if any(rx.search(s) for _, _, rx in THEMES):
                out.append(s)
    return out


def source_label(site: str, url: str) -> str:
    if site == "Reddit":
        m = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)", url)
        return f"Reddit · r/{m.group(1)}" if m else "Reddit"
    return f"{site} post"


async def site_threads(site: dict[str, Any], place: str, since: date) -> tuple[list[dict[str, Any]], str | None]:
    """(fetched threads, error). error is set when the site blocks/needs login or every call failed."""
    seen: dict[str, dict[str, Any]] = {}
    searched = 0
    for topic in site["topics"]:
        try:
            results = await tf.search(f"{place} {topic}", location="IN", language="en",
                                      include_domains=site["domains"], after_date=since.isoformat())
            searched += 1
        except tf.TinyFishError:
            continue
        for r in results:
            url = r.get("url") or ""
            if url.startswith("http") and url not in seen:
                seen[url] = r
    if not searched:
        return [], "search failed"
    urls = list(seen)[: site["max_threads"]]
    if not urls:
        return [], None
    results, errors = await tf.fetch(urls, format="markdown", per_url_timeout_ms=30000)
    blocked = [e for e in errors if e.get("error") in {"bot_blocked", "login_required"}]
    if not results and blocked:
        return [], f"{blocked[0]['error'].replace('_', ' ')} (not worked around)"
    return results, None


async def scan_residents(listing: dict[str, Any]) -> dict[str, Any]:
    locality = listing.get("locality") or ""
    place, words = match_area(locality), match_words(locality)
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=WINDOW_DAYS)
    if not words:
        return {"status": "could_not_verify", "window": "12 months", "total_mentions": 0, "themes": [],
                "quotes": [], "sources": [], "note": "Could not pick an area name out of the locality."}

    site_results = await asyncio.gather(*(site_threads(s, place, since) for s in SITES), return_exceptions=True)
    sources, threads = [], []
    for site, res in zip(SITES, site_results):
        if isinstance(res, BaseException):
            sources.append({"site": site["name"], "status": "could_not_verify", "note": str(res)[:120], "threads": 0})
            continue
        fetched, err = res
        if err:
            sources.append({"site": site["name"], "status": "could_not_verify", "note": err, "threads": 0})
            continue
        kept = 0
        for a in fetched:
            d = parse_date(a.get("published_date"))
            text = a.get("text") if isinstance(a.get("text"), str) else ""
            title = a.get("title") or ""
            url = a.get("final_url") or a["url"]
            if not d or d < since or not names_place(f"{title} {text}", words) or OFFICIAL_X_ACCOUNTS.search(url):
                continue
            threads.append({"site": site["name"], "date": d, "title": title, "text": text, "url": url})
            kept += 1
        sources.append({"site": site["name"], "status": "ok", "threads": kept})

    themes = []
    for tid, label, rx in THEMES:
        hits = [t for t in threads if rx.search(f"{t['title']} {t['text']}")]
        if hits:
            neg = sum(sentiment(t["text"]) in {"negative", "mixed"} for t in hits)
            themes.append({"id": tid, "label": label, "mentions": len(hits),
                           "sentiment": "negative" if neg > len(hits) / 2 else "mixed" if neg else "positive"})
    themes.sort(key=lambda t: t["mentions"], reverse=True)
    positives = [t for t in threads if sentiment(t["text"]) == "positive"]
    if positives:
        themes.append({"id": "positives", "label": "Positives", "mentions": len(positives), "sentiment": "positive"})

    quotes, seen_quotes = [], set()
    # Reddit first, then X; newest first within a site.
    for t in sorted(threads, key=lambda t: (SITE_ORDER.get(t["site"], 9), -t["date"].toordinal())):
        per_thread = 0
        for q in candidate_quotes(t["text"]):
            if per_thread >= MAX_QUOTES_PER_THREAD or len(quotes) >= MAX_QUOTES:
                break
            key = re.sub(r"[^a-z0-9]+", " ", q.lower()).strip()
            if key in seen_quotes:
                continue
            seen_quotes.add(key)
            theme = next((tid for tid, _, rx in THEMES if rx.search(q)), "other")
            quotes.append({"text": q, "theme": theme, "source": source_label(t["site"], t["url"]),
                           "source_url": t["url"], "posted_at": t["date"].isoformat(),
                           "age": age_text(t["date"], today), "sentiment": sentiment(q)})
            per_thread += 1

    any_ok = any(s["status"] == "ok" for s in sources)
    status = "verified" if (quotes or themes) else "no_reports" if any_ok else "could_not_verify"
    return {
        "status": status,
        "place": place,
        "window": "12 months",
        "total_mentions": len(threads),
        "themes": themes,
        "quotes": quotes,
        "sources": sources,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Quotes are verbatim sentences from public posts; usernames are not shown. Sentiment is automatic.",
    }


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    """Cached per area for CACHE_TTL_SECONDS."""
    place = match_area(listing.get("locality") or "")
    path = CACHE_DIR / f"{re.sub(r'[^a-z0-9]+', '-', place.lower()).strip('-') or 'unknown'}.json"
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))
        if age.total_seconds() < CACHE_TTL_SECONDS:
            return cached
    result = await scan_residents(listing)
    if result["status"] != "could_not_verify":
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
