"""Shared helpers for check modules.

A check returns a dict with: id, status, score, tag, headline, details[],
source_url, fetched_at. status is one of:
  "verified"          - a real source returned data (live mode only)
  "stub"              - simulated demo data, NOT a real finding
  "could_not_verify"  - error, timeout, or no usable source
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, timezone
from typing import Any



def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def stub_delay() -> None:
    lo = float(os.getenv("XRAY_STUB_MIN_DELAY", "2"))
    hi = float(os.getenv("XRAY_STUB_MAX_DELAY", "5"))
    await asyncio.sleep(random.uniform(lo, hi))


def stub_result(check_id: str, score: int, tag: str, headline: str, details: list[str]) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "stub",
        "score": score,
        "tag": tag,
        "headline": f"[Demo] {headline}",
        "details": [f"[Demo] {d}" for d in details],
        "source_url": None,
        "fetched_at": now_iso(),
    }


def could_not_verify(check_id: str, reason: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "could_not_verify",
        "score": None,
        "tag": "Could not verify",
        "headline": f"Could not verify {check_id.replace('_', ' ')}",
        "details": [reason],
        "source_url": None,
        "fetched_at": now_iso(),
    }

