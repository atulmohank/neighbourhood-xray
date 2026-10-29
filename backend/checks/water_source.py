"""water_source check. In stub mode it deliberately fails, to demonstrate the
could_not_verify path end to end."""

from __future__ import annotations

from typing import Any

from checks.base import live_check, stub_delay
from tinyfish_client import is_live_mode

CHECK_ID = "water_source"
GOAL = "Find whether buildings in {locality} use municipal, borewell or tanker water."


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        return await live_check(CHECK_ID, listing, GOAL)
    await stub_delay()
    raise RuntimeError("Simulated source failure (stub mode demo of could_not_verify)")
