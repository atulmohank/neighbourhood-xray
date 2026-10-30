"""power_cuts check. Live: official BESCOM notices (TinyFish agent) plus labelled
news reports (TinyFish Search + Fetch); see checks/notices.py. Stub mode
returns simulated demo data."""

from __future__ import annotations

from typing import Any

import scoring
from checks.base import stub_delay, stub_result
from checks.notices import run_notices_check
from tinyfish_client import is_live_mode

CHECK_ID = "power_cuts"


async def run(listing: dict[str, Any]) -> dict[str, Any]:
    if is_live_mode():
        return await run_notices_check(
            CHECK_ID, "bescom", listing, scoring.power_cuts_deduction, scoring.area_score, "power cut"
        )
    await stub_delay()
    return stub_result(
        CHECK_ID,
        85,
        "Stable",
        "Simulated: few planned power cuts",
        ["No real sources were queried in stub mode."],
    )
