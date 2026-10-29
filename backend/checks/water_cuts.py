"""water_cuts check. Stub mode returns simulated demo data, not real findings."""

from __future__ import annotations

from typing import Any

from checks.base import live_check, stub_delay, stub_result
from tinyfish_client import is_live_mode

CHECK_ID = "water_cuts"
GOAL = "Find recent water supply interruption notices for {locality}."


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        return await live_check(CHECK_ID, listing, GOAL)
    await stub_delay()
    return stub_result(
        CHECK_ID,
        32,
        "Severe deficit",
        "Simulated: frequent water supply cuts",
        ["No real sources were queried in stub mode."],
    )
