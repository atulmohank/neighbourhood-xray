"""rent_compare check. Stub mode returns simulated demo data, not real findings."""

from __future__ import annotations

from typing import Any

from checks.base import could_not_verify, stub_delay, stub_result
from tinyfish_client import is_live_mode

CHECK_ID = "rent_compare"


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        return could_not_verify(CHECK_ID, "Live rent comparison is not implemented yet.")
    await stub_delay()
    return stub_result(
        CHECK_ID,
        50,
        "Above median",
        "Simulated: rent above the area median",
        ["No real sources were queried in stub mode."],
    )
