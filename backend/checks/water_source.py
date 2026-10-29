"""water_source check. Live mode reads the listing text; the BWSSB Cauvery
stage dataset is area-level context only. A building's actual source can't be
checked against any public record, so without a statement in the listing the
result is could_not_verify (and summary.py turns it into an owner question).
Stub mode deliberately fails, to demonstrate could_not_verify."""

from __future__ import annotations

import re
from typing import Any

import scoring
from checks import datasets as ds
from checks.base import could_not_verify, now_iso, stub_delay
from tinyfish_client import is_live_mode

CHECK_ID = "water_source"

MUNICIPAL_RE = re.compile(r"\b(cauvery|kaveri|bwssb|corporation water|municipal water)\b", re.I)
PRIVATE_RE = re.compile(r"\b(bore\s?well|tankers?)\b", re.I)


def cauvery_context(locality: str) -> str | None:
    words = set(ds.place_words(locality.split(",")[0]))
    if not words:
        return None
    for stage, area in ds.cauvery_areas():
        if words <= set(ds.place_words(area)):
            return (
                f"Area-level context only: '{area}' is listed under BWSSB Cauvery {stage} "
                f"(OpenCity dataset updated {ds.CAUVERY_DATASET_DATE}). This does not show that "
                "this building is connected or that supply is adequate."
            )
    return None


def snippet(text: str, m: re.Match) -> str:
    start, end = max(0, m.start() - 60), min(len(text), m.end() + 60)
    return "…" + " ".join(text[start:end].split()) + "…"


def check_water_source(listing: dict[str, Any]) -> dict[str, Any]:
    text = listing.get("listing_text") or ""
    context = cauvery_context(listing.get("locality") or "")
    municipal = MUNICIPAL_RE.search(text)
    private = PRIVATE_RE.search(text)
    url = listing.get("listing_url")

    if url and (municipal or private):
        only_private = bool(private) and not municipal
        deduction = scoring.water_source_deduction(only_private)
        m = private if only_private else municipal
        details = [f"Listing text: {snippet(text, m)}"]
        if context:
            details.append(context)
        return {
            "id": CHECK_ID,
            "status": "verified",
            "score": scoring.area_score(CHECK_ID, deduction),
            "tag": "Borewell/tanker only" if only_private else "Cauvery (per listing)",
            "headline": (
                "Listing mentions borewell/tanker water, not Cauvery"
                if only_private
                else "Listing says the flat has Cauvery/BWSSB water"
            ),
            "details": details,
            "source_url": url,
            "fetched_at": now_iso(),
        }

    reason = "The listing does not say where the water comes from."
    if not url:
        reason = "No listing text/URL was provided to check the water source."
    result = could_not_verify(CHECK_ID, reason)
    if context:
        result["details"].append(context)
        result["source_url"] = ds.CAUVERY_DATASET_URL
    return result


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        return check_water_source(listing)
    await stub_delay()
    raise RuntimeError("Simulated source failure (stub mode demo of could_not_verify)")
