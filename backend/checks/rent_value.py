"""rent_value check. Stub mode returns simulated demo data, not real findings."""

from __future__ import annotations

from typing import Any

from checks.base import live_check, stub_delay, stub_result
from tinyfish_client import is_live_mode

CHECK_ID = "rent_value"
GOAL = "Find rents of comparable {bhk} BHK listings in {locality}."


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        return await live_check(CHECK_ID, listing, GOAL)
    await stub_delay()
    return stub_result(
        CHECK_ID,
        48,
        "Above median",
        "Simulated: rent above the area median",
        ["No real sources were queried in stub mode."],
    )
