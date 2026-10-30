"""rent_compare check. Live: comparable rents from NoBroker and MagicBricks
locality search pages via TinyFish Fetch (free); if Fetch yields too few
comparables, one TinyFish agent run on the NoBroker page. Stub mode returns
simulated demo data.

Comparables are same-BHK listings whose locality names the same parent area.
Outliers (below 50% or above 200% of the first-pass median) are dropped before
the median, fair band and cheapest comparable are computed. Rents are not
adjusted for size or furnishing, so the "fair band" is the middle half
(25th-75th percentile) of what is listed, not a valuation.
"""

from __future__ import annotations

import asyncio
import re
import statistics
from typing import Any

import scoring
import tinyfish_client as tf
from checks import datasets as ds
from checks.base import could_not_verify, no_reports, now_iso, stub_delay, stub_result
from checks.places import match_area, match_words
from tinyfish_client import is_live_mode

CHECK_ID = "rent_compare"

MIN_COMPARABLES = 3
OUTLIER_LOW, OUTLIER_HIGH = 0.5, 2.0  # keep rents within 50%-200% of the first-pass median
RENT_MIN, RENT_MAX = 3000, 500000  # sanity bounds for a monthly rent in INR
AGENT_MAX_SECONDS = 200

# /property/2-bhk-apartment-for-rent-in-hsr-layout-sector-7-bangalore-for-rs-22000/<id>/detail
NOBROKER_LINK_RE = re.compile(
    r"https://www\.nobroker\.in/property/(\d+)-bhk-[a-z-]*?for-rent-in-([a-z0-9-]+?)-bangalore-for-rs-(\d+)/([0-9a-f]+)/detail"
)
MB_CARD_RE = re.compile(r"^#+\s*(\d+)\s*BHK[^\n]*?for Rent in ([^\n]+)$", re.I | re.M)
MB_PRICE_RE = re.compile(r"^₹\s?([\d,]+)\s*$", re.M)
MB_AREA_RE = re.compile(r"(?:Super|Carpet|Built-up) Area\s+(\d{3,5})\s*sqft", re.I)

AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "listings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rent": {"type": "integer"},
                    "bhk": {"type": "integer"},
                    "locality": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["rent", "bhk", "url"],
            },
        }
    },
    "required": ["listings"],
}


def portal_urls(area: str, bhk: int) -> dict[str, str]:
    words = ds.norm(area).split()
    return {
        "NoBroker": f"https://www.nobroker.in/{bhk}bhk-flats-for-rent-in-{'_'.join(words)}_bangalore",
        "MagicBricks": f"https://www.magicbricks.com/{bhk}-bhk-flats-for-rent-in-{'-'.join(words)}-bangalore-pppfr",
    }


def parse_nobroker(links: list[str], bhk: int) -> list[dict[str, Any]]:
    out, seen = [], set()
    for link in links:
        m = NOBROKER_LINK_RE.search(link)
        if not m or m.group(4) in seen:
            continue
        seen.add(m.group(4))
        if int(m.group(1)) != bhk:
            continue
        out.append({
            "portal": "NoBroker",
            "rent": int(m.group(3)),
            "bhk": bhk,
            "locality": m.group(2).replace("-", " ").title(),
            "area_sqft": None,
            "source_url": m.group(0),
        })
    return out


def parse_magicbricks(text: str, links: list[str], bhk: int, page_url: str) -> list[dict[str, Any]]:
    heads = list(MB_CARD_RE.finditer(text))
    out = []
    for i, h in enumerate(heads):
        if int(h.group(1)) != bhk:
            continue
        card = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        price = MB_PRICE_RE.search(card)
        if not price:
            continue
        area = MB_AREA_RE.search(card)
        sqft = int(area.group(1)) if area else None
        url = page_url
        if sqft:
            matches = [l for l in links if "propertyDetails" in l and f"/{bhk}-BHK-{sqft}-Sq-ft" in l]
            if len(matches) == 1:
                url = matches[0]
        out.append({
            "portal": "MagicBricks",
            "rent": int(price.group(1).replace(",", "")),
            "bhk": bhk,
            "locality": h.group(2).strip(),
            "area_sqft": sqft,
            "source_url": url,
        })
    return out


def keep(comps: list[dict[str, Any]], words: list[str], own_url: str | None) -> list[dict[str, Any]]:
    own = (own_url or "").split("?")[0]
    return [
        c for c in comps
        if RENT_MIN <= c["rent"] <= RENT_MAX
        and set(words) <= set(ds.norm(c["locality"]).split())
        and c["source_url"].split("?")[0] != own
    ]


def drop_outliers(comps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(kept, dropped): rents outside 50%-200% of the first-pass median."""
    if not comps:
        return [], []
    median = statistics.median(c["rent"] for c in comps)
    kept = [c for c in comps if OUTLIER_LOW * median <= c["rent"] <= OUTLIER_HIGH * median]
    return kept, [c for c in comps if c not in kept]


async def fetch_comparables(urls: dict[str, str], bhk: int) -> tuple[list[dict[str, Any]], list[str], int]:
    """(comparables, notes, pages_read)."""
    results, errors = await tf.fetch(list(urls.values()), format="markdown", links=True, per_url_timeout_ms=40000)
    notes = [f"{e.get('url')}: {e.get('error')}" for e in errors]
    pages_read = sum(1 for r in results if r.get("text"))
    comps: list[dict[str, Any]] = []
    for r in results:
        text = r.get("text") if isinstance(r.get("text"), str) else ""
        links = r.get("links") or []
        if r["url"] == urls["NoBroker"]:
            comps += parse_nobroker(links, bhk)
        elif r["url"] == urls["MagicBricks"]:
            comps += parse_magicbricks(text, links, bhk, r["url"])
    return comps, notes, pages_read


async def agent_comparables(url: str, area: str, bhk: int) -> list[dict[str, Any]]:
    run = await tf.run_agent(
        url,
        f"List the {bhk} BHK rental listings shown on this page for {area}, Bangalore: monthly rent in rupees "
        "as an integer, BHK, locality as written, and the listing URL. Only listings actually shown; do not guess.",
        AGENT_SCHEMA,
        max_duration_seconds=AGENT_MAX_SECONDS,
    )
    rows = run["result"].get("listings", []) if isinstance(run["result"], dict) else []
    return [
        {"portal": "NoBroker", "rent": int(r["rent"]), "bhk": bhk, "locality": r.get("locality") or area,
         "area_sqft": None, "source_url": r["url"]}
        for r in rows
        if isinstance(r.get("rent"), int) and int(r.get("bhk") or 0) == bhk and str(r.get("url", "")).startswith("http")
    ]


def percentile(sorted_vals: list[int], q: float) -> int:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return int(round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)))


def build_rent_compare(rent: int, bhk: int, comps: list[dict[str, Any]], urls: dict[str, str]) -> dict[str, Any]:
    rents = sorted(c["rent"] for c in comps)
    median = int(statistics.median(rents))
    premium = round((rent - median) / median * 100, 1)
    extra = rent - median
    portals = []
    for name, url in urls.items():
        pr = [c["rent"] for c in comps if c["portal"] == name]
        if pr:
            portals.append({"name": name, "median": int(statistics.median(pr)), "listings": len(pr), "source_url": url})
    cheapest = min(comps, key=lambda c: c["rent"])
    return {
        "status": "verified",
        "currency": "INR",
        "listing_rent": rent,
        "fair_range": {"low": percentile(rents, 0.25), "high": percentile(rents, 0.75)},
        "median": median,
        "premium_percent": premium,
        "monthly_extra": extra if extra > 0 else 0,
        "yearly_overpay": extra * 12 if extra > 0 else 0,
        "spread": {"min": rents[0], "max": rents[-1], "n": len(rents)},
        "portals": portals,
        "cheapest_comparable": {
            "rent": cheapest["rent"],
            "bhk": bhk,
            "area_sqft": cheapest["area_sqft"],
            "locality": cheapest["locality"],
            "distance_m": None,
            "note": None,
            "portal": cheapest["portal"],
            "monthly_saving": max(0, rent - cheapest["rent"]),
            "source_url": cheapest["source_url"],
        },
        "fetched_at": now_iso(),
    }


async def check_rent(listing: dict[str, Any]) -> dict[str, Any]:
    rent, bhk = listing.get("rent"), listing.get("bhk")
    if not rent or not bhk:
        return could_not_verify(CHECK_ID, "The listing's rent and BHK are needed to compare rents.")
    area = match_area(listing.get("locality") or "")
    words = match_words(listing.get("locality") or "")
    if not area or not words:
        return could_not_verify(CHECK_ID, "Could not pick an area name out of the locality.")
    urls = portal_urls(area, bhk)

    notes: list[str] = []
    pages_read = 0
    try:
        comps, notes, pages_read = await fetch_comparables(urls, bhk)
    except tf.TinyFishError as exc:
        comps, notes = [], [str(exc)]
    comps = keep(comps, words, listing.get("listing_url"))
    method = "TinyFish Fetch"
    if len(comps) < MIN_COMPARABLES:
        try:
            agent = keep(await agent_comparables(urls["NoBroker"], area, bhk), words, listing.get("listing_url"))
            seen = {c["source_url"] for c in comps}
            comps += [c for c in agent if c["source_url"] not in seen]
            pages_read += 1
            method = "TinyFish Fetch + agent"
        except (tf.TinyFishError, asyncio.TimeoutError) as exc:
            notes.append(f"Agent fallback failed: {str(exc)[:120]}")
    comps, outliers = drop_outliers(comps)
    if len(comps) < MIN_COMPARABLES:
        reason = f"Only {len(comps)} comparable {bhk} BHK listings found for {area}; need {MIN_COMPARABLES}."
        if pages_read:
            return no_reports(
                CHECK_ID, f"Too few comparable {bhk} BHK listings in {area} to judge the rent",
                [reason, *notes], urls["NoBroker"], tag="Too few listings",
            )
        result = could_not_verify(CHECK_ID, reason)
        result["details"] += notes
        result["source_url"] = urls["NoBroker"]
        result["degraded"] = True  # no portal page could be read (network/blocking)
        return result
    if outliers:
        notes.insert(0, f"Dropped {len(outliers)} outlier listings outside 50%-200% of the median "
                        f"(₹{', ₹'.join(f'{c['rent']:,}' for c in sorted(outliers, key=lambda c: c['rent']))}).")

    rc = build_rent_compare(rent, bhk, comps, urls)
    premium = rc["premium_percent"]
    deduction = scoring.rent_deduction(max(0.0, premium))
    names = " + ".join(p["name"] for p in rc["portals"])
    direction = "above" if premium > 0 else "below" if premium < 0 else "at"
    return {
        "id": CHECK_ID,
        "status": "verified",
        "score": scoring.area_score(CHECK_ID, deduction),
        "tag": f"{premium:+.0f}% vs median",
        "headline": (
            f"Rent ₹{rent:,} is {abs(premium):.0f}% {direction} the ₹{rc['median']:,} median "
            f"for {bhk} BHK in {area} ({len(comps)} listings, {names})"
        ),
        "details": [
            f"Middle half of listed rents: ₹{rc['fair_range']['low']:,}–₹{rc['fair_range']['high']:,}; "
            f"range ₹{rc['spread']['min']:,}–₹{rc['spread']['max']:,}.",
            *(f"{p['name']}: median ₹{p['median']:,} across {p['listings']} listings ({p['source_url']})" for p in rc["portals"]),
            f"Cheapest comparable: ₹{rc['cheapest_comparable']['rent']:,} in {rc['cheapest_comparable']['locality']} "
            f"({rc['cheapest_comparable']['source_url']})",
            f"Listings as advertised today via {method}; not adjusted for size or furnishing.",
            *notes,
        ],
        "source_url": rc["portals"][0]["source_url"],
        "evidence": [
            *({"date": rc["fetched_at"][:10], "title": f"{p['listings']} comparable {bhk} BHK listings, median ₹{p['median']:,}",
               "label": f"{p['name']} search page", "source_url": p["source_url"]} for p in rc["portals"]),
            {"date": rc["fetched_at"][:10],
             "title": f"Cheapest comparable: ₹{rc['cheapest_comparable']['rent']:,} in {rc['cheapest_comparable']['locality']}",
             "label": f"{rc['cheapest_comparable']['portal']} listing", "source_url": rc["cheapest_comparable"]["source_url"]},
        ],
        "fetched_at": now_iso(),
        "rent_compare": rc,
    }


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        return await check_rent(listing)
    await stub_delay()
    return stub_result(
        CHECK_ID,
        50,
        "Above median",
        "Simulated: rent above the area median",
        ["No real sources were queried in stub mode."],
    )
