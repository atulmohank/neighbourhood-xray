"""TinyFish integration wrapper (PLACEHOLDER — live mode NOT implemented).

What the official docs (https://docs.tinyfish.ai, checked 2026-10-29) confirm:
* Agent API base: https://agent.tinyfish.ai/v1/automation/
  with /run (sync), /run-async (start then poll) and /run-sse (event stream).
* Auth: API key in the ``X-API-Key`` header; docs suggest ``TINYFISH_API_KEY``.
* /run-sse body includes ``url`` and ``goal``; an ``output_schema`` can be given.
* SSE event types seen in the docs: STARTED, PROGRESS, COMPLETE
  (COMPLETE carries ``status`` and ``result``).

Not yet confirmed (read the API reference before implementing):
* Required vs optional body fields and the ``output_schema`` format.
* Error responses / error events, rate limits, timeouts and credit usage.
* The exact shape of ``result`` for our goals.

Until those are confirmed, ``run_agent`` raises in live mode so a check fails
into ``could_not_verify`` instead of returning made-up data. Stub mode is the
default and needs no API key.
"""

from __future__ import annotations

import os
from typing import Any

AGENT_BASE_URL = "https://agent.tinyfish.ai/v1/automation"


class TinyFishNotConfigured(RuntimeError):
    pass


def is_live_mode() -> bool:
    return os.getenv("XRAY_MODE", "stub").lower() == "live"


def api_key() -> str | None:
    # Read from the environment only. Never hardcode or log the key.
    return os.getenv("TINYFISH_API_KEY") or None


async def run_agent(url: str, goal: str, output_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    if not api_key():
        raise TinyFishNotConfigured("TINYFISH_API_KEY is not set")
    raise NotImplementedError(
        "Live TinyFish calls are not implemented yet. Verify the request/response "
        "schema against https://docs.tinyfish.ai before implementing."
    )
