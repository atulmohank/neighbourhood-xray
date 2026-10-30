"""TinyFish Agent API client (POST /v1/automation/run-sse).

Verified against the docs and a real smoke test on 2026-10-29
(backend/scripts/tinyfish_smoke.py):

* Request: POST https://agent.tinyfish.ai/v1/automation/run-sse, header
  ``X-API-Key``, JSON body with required ``url`` and ``goal``; optional
  ``output_schema``, ``agent_config`` ({mode, max_steps, max_duration_seconds}),
  ``browser_profile`` (lite|stealth), ``proxy_config`` ({enabled, country_code}).
* Stream: SSE ``data:`` lines with JSON events, ``type`` one of STARTED,
  STREAMING_URL, PROGRESS, TF_API_RESULT, HEARTBEAT, COMPLETE.
* COMPLETE carries ``status`` (COMPLETED | FAILED | CANCELLED), optional
  ``error`` (string) and ``result``. Without an output_schema the result is
  ``{"result": "<free text>"}``; with one it is the JSON object itself.
* A COMPLETED run can still mean "could not find it": the agent says so in
  the result text. Callers must check the content, not just the status.
* Karnataka government sites (bescom/bwssb .karnataka.gov.in) time out from
  TinyFish's default browsers; with ``proxy_config`` country ``IN`` they load.
* Runs on those sites took ~250 s in the smoke test, so long-running checks
  need a budget well above 45 s or a cached result.
* HTTP errors: 400 invalid input, 401 bad key, 402/403 credits, 500. Error
  body: {"error": {"code", "message", "details"}, "request_id"}.
* No credit/cost field is returned by the API; check usage in the dashboard.

Search (GET https://api.search.tinyfish.ai) and Fetch (POST
https://api.fetch.tinyfish.ai) are free within daily allowances (Search
12,000 requests/day, 30/min; Fetch 1,000 URLs/day, 150/min). Checked
2026-10-29:
* Fetch cannot reach bescom/bwssb .karnataka.gov.in (per-URL ``proxy_error``)
  and has no proxy option, so official pages go through run_agent.
* Search ``date`` values are relative ("1 week ago") and not reliable: a
  March article came back as "1 week ago" with after_date set. Use the
  fetched article's ``published_date`` instead.
"""

from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable

import httpx

AGENT_RUN_SSE_URL = "https://agent.tinyfish.ai/v1/automation/run-sse"
SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"


class TinyFishError(RuntimeError):
    pass


class TinyFishNotConfigured(TinyFishError):
    pass


def is_live_mode() -> bool:
    return os.getenv("XRAY_MODE", "stub").lower() == "live"


def api_key() -> str | None:
    # Read from the environment only. Never hardcode or log the key.
    return os.getenv("TINYFISH_API_KEY") or None


async def run_agent(
    url: str,
    goal: str,
    output_schema: dict[str, Any] | None = None,
    *,
    proxy_country: str | None = "IN",
    max_duration_seconds: int | None = None,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Run one agent and return {"run_id", "result"}.

    Raises TinyFishError on HTTP errors, FAILED/CANCELLED runs or a stream that
    ends without COMPLETE. The caller turns any exception into could_not_verify.
    """
    key = api_key()
    if not key:
        raise TinyFishNotConfigured("TINYFISH_API_KEY is not set")

    body: dict[str, Any] = {"url": url, "goal": goal}
    if output_schema:
        body["output_schema"] = output_schema
    if max_duration_seconds:
        body["agent_config"] = {"max_duration_seconds": max_duration_seconds}
    if proxy_country:
        body["proxy_config"] = {"enabled": True, "country_code": proxy_country}

    timeout = httpx.Timeout(30, read=120)  # HEARTBEAT events keep the read alive
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", AGENT_RUN_SSE_URL, headers={"X-API-Key": key}, json=body) as r:
            if r.status_code != 200:
                raw = (await r.aread()).decode("utf-8", "replace")
                try:
                    err = json.loads(raw).get("error", {})
                    detail = f"{err.get('code')}: {err.get('message')}"
                except (json.JSONDecodeError, AttributeError):
                    detail = raw[:200]
                raise TinyFishError(f"TinyFish HTTP {r.status_code} ({detail})")

            run_id = None
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                run_id = event.get("run_id", run_id)
                if kind == "PROGRESS" and on_progress:
                    await on_progress(str(event.get("purpose", "")))
                elif kind == "COMPLETE":
                    status = event.get("status")
                    if status != "COMPLETED":
                        raise TinyFishError(f"TinyFish run {status}: {event.get('error') or 'no detail'}")
                    return {"run_id": run_id, "result": event.get("result")}
    raise TinyFishError("TinyFish stream ended without a COMPLETE event")


def result_text(result: Any) -> str:
    """Free-text answer from a run without output_schema."""
    if isinstance(result, dict) and isinstance(result.get("result"), str):
        return result["result"]
    return json.dumps(result, ensure_ascii=False) if result is not None else ""


def _headers() -> dict[str, str]:
    key = api_key()
    if not key:
        raise TinyFishNotConfigured("TINYFISH_API_KEY is not set")
    return {"X-API-Key": key}


async def search(query: str, **params: Any) -> list[dict[str, Any]]:
    """Search API. Returns results[] ({title, snippet, url, date, publisher, ...})."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(SEARCH_URL, headers=_headers(), params={"query": query, **params})
    if r.status_code != 200:
        raise TinyFishError(f"TinyFish search HTTP {r.status_code}")
    return r.json().get("results", [])


async def fetch(urls: list[str], **body: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch API (max 10 URLs). Returns (results, errors)."""
    async with httpx.AsyncClient(timeout=150) as client:
        r = await client.post(FETCH_URL, headers=_headers(), json={"urls": urls[:10], **body})
    if r.status_code != 200:
        raise TinyFishError(f"TinyFish fetch HTTP {r.status_code}")
    data = r.json()
    return data.get("results", []), data.get("errors", [])
