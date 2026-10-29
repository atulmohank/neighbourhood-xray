"""water_source check. Live mode reads the listing text; the BWSSB Cauvery
stage dataset is area-level context only. A building's actual source can't be
checked against any public record, so without a statement in the listing the
result is no_reports when the listing was read but says nothing (summary.py
turns it into an owner question), and could_not_verify only if it couldn't be read.
Stub mode deliberately fails, to demonstrate could_not_verify."""

from __future__ import annotations

import re
from typing import Any

import scoring
from checks import datasets as ds
from checks.base import could_not_verify, no_reports, now_iso, stub_delay
from checks.places import match_words
import tinyfish_client as tf
from tinyfish_client import is_live_mode

CHECK_ID = "water_source"

# Free text, plus NoBroker's "Water Supply: Corporation | Borewell | Both" field.
MUNICIPAL_RE = re.compile(
    r"\b(cauvery|kaveri|bwssb|corporation water|municipal water)\b"
    r"|water supply\W+(corporation|both(\W+corporation\W+and\W+borewell)?)\b",
    re.I,
)
PRIVATE_RE = re.compile(r"\b(bore\s?well|tankers?)\b", re.I)


def cauvery_context(locality: str) -> str | None:
    words = set(match_words(locality))
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


async def listing_text_for(listing: dict[str, Any]) -> str:
    """The text the extension sent, else the listing page via TinyFish Fetch."""
    if listing.get("listing_text"):
        return listing["listing_text"]
    url = listing.get("listing_url") or ""
    if not url.startswith("http"):
        return ""
    results, _errors = await tf.fetch([url], format="markdown", per_url_timeout_ms=30000)
    return results[0]["text"] if results and isinstance(results[0].get("text"), str) else ""


def check_water_source(listing: dict[str, Any], text: str | None = None) -> dict[str, Any]:
    if text is None:
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
            "tag": "Borewell/tanker only" if only_private else "Municipal (per listing)",
            # Quote what the listing says; "Corporation" is not proof of a Cauvery connection.
            "headline": (
                f"Listing mentions \"{' '.join(m.group(0).split())}\" water, not a municipal supply"
                if only_private
                else f"Listing says: \"{' '.join(re.sub(r'[#:]+', ' ', m.group(0)).split())}\" (municipal supply, per owner)"
            ),
            "details": details,
            "source_url": url,
            "fetched_at": now_iso(),
        }

    if url and text:
        # The listing was read fine but doesn't say: checked, nothing to deduct, ask the owner.
        details = ["The listing does not say where the water comes from."]
        if context:
            details.append(context)
        return no_reports(
            CHECK_ID, "Listing doesn't say where the water comes from", details, url, tag="Not stated"
        )
    result = could_not_verify(
        CHECK_ID,
        "Could not read the listing page." if url else "No listing URL or text was provided.",
    )
    if context:
        result["details"].append(context)
    return result


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        try:
            text = await listing_text_for(listing)
        except tf.TinyFishError:
            text = ""
        return check_water_source(listing, text)
    await stub_delay()
    raise RuntimeError("Simulated source failure (stub mode demo of could_not_verify)")
