"""flooding check. Live mode matches the locality against the official
flood-vulnerable locations dataset (static, no TinyFish). Stub mode returns
simulated demo data."""

from __future__ import annotations

from typing import Any

import scoring
from checks import datasets as ds
from checks.base import no_reports, now_iso, stub_delay, stub_result
from checks.places import parent_area
from tinyfish_client import is_live_mode

CHECK_ID = "flooding"


def match_flood_points(locality: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (ward_points, locality_points, zone_points) for a locality string."""
    loc = ds.norm(f"{locality} {parent_area(locality) or ''}")
    points = ds.flood_points()
    ward_points = [p for p in points if p["ward"] and ds.norm(p["ward"]) in loc]
    zone_points = [p for p in points if p["zone"] and ds.norm(p["zone"]) in loc] if not ward_points else []

    # Inside the ward, points that name this part of it (same sector or a shared place word).
    ward_words = {w for p in ward_points for w in ds.place_words(p["ward"])}
    extra_words = set(ds.place_words(locality)) - ward_words
    sectors = ds.sector_numbers(locality)
    locality_points = [
        p for p in ward_points
        if (sectors and sectors & ds.sector_numbers(p["location"]))
        or (extra_words & set(ds.place_words(p["location"])))
    ]
    return ward_points, locality_points, zone_points


def check_flooding(listing: dict[str, Any]) -> dict[str, Any]:
    locality = listing.get("locality") or ""
    ward_points, locality_points, zone_points = match_flood_points(locality)
    dated = f"dataset updated {ds.FLOOD_DATASET_DATE}; lists vulnerable spots, not dated incidents"

    if not ward_points:
        # The dataset was read fine; it just lists nothing for this ward.
        details = [
            f"No flood-vulnerable spot listed for '{locality}' in the official list. "
            "The list uses old BBMP ward names, so a renamed ward may be missed."
        ]
        if zone_points:
            details.append(
                f"Context: the wider {zone_points[0]['zone']} zone has {len(zone_points)} listed spots in other wards."
            )
        details.append(f"Source: {ds.FLOOD_DATASET_LABEL}, {dated}.")
        return no_reports(
            CHECK_ID,
            f"No official flood-vulnerable spot listed for this ward (as of {ds.FLOOD_DATASET_DATE})",
            details,
            ds.FLOOD_DATASET_URL,
            tag="None listed",
        )

    ward = ward_points[0]["ward"]
    deduction = scoring.flooding_deduction(True, len(locality_points))
    details = [f"{p['location']} (ward {p['ward']})" for p in ward_points]
    if locality_points:
        details.insert(0, "Matches this part of the ward: " + "; ".join(p["location"] for p in locality_points))
    details.append(f"Source: {ds.FLOOD_DATASET_LABEL}, {dated}.")
    return {
        "id": CHECK_ID,
        "status": "verified",
        "score": scoring.area_score(CHECK_ID, deduction),
        "tag": f"{len(ward_points)} official flood spots",
        "headline": f"{ward} ward has {len(ward_points)} officially flood-vulnerable spots (as of {ds.FLOOD_DATASET_DATE})",
        "details": details,
        "source_url": ds.FLOOD_DATASET_URL,
        "fetched_at": now_iso(),
    }


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        return check_flooding(listing)
    await stub_delay()
    return stub_result(
        CHECK_ID,
        52,
        "Low-lying pocket",
        "Simulated: one flooding report nearby",
        ["No real sources were queried in stub mode."],
    )
