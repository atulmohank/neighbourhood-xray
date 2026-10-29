"""Neighbourhood X-Ray backend (FastAPI).

Run from the backend/ folder:  uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

from checks import ALL_CHECKS  # noqa: E402  (after load_dotenv so env is set)
from checks.base import could_not_verify, now_iso  # noqa: E402
from scoring import AREA_LABELS, level_for, score_report  # noqa: E402
from summary import build_owner_questions, build_summary  # noqa: E402
from tinyfish_client import is_live_mode  # noqa: E402

CHECK_TIMEOUT_SECONDS = float(os.getenv("XRAY_CHECK_TIMEOUT", "45"))
CACHE_DIR = Path(__file__).resolve().parent / "cache"

app = FastAPI(title="Neighbourhood X-Ray", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^chrome-extension://.*$|^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    locality: str = Field(min_length=2, max_length=200)
    rent: int | None = Field(default=None, ge=0)
    bhk: int | None = Field(default=None, ge=0, le=20)
    listing_url: str | None = None
    source: str = "manual"


class Scan:
    def __init__(self, scan_id: str, listing: dict[str, Any]):
        self.id = scan_id
        self.listing = listing
        self.status = "running"
        self.started = time.monotonic()
        self.report: dict[str, Any] | None = None
        self.task: asyncio.Task[None] | None = None
        self.events: list[tuple[str, dict[str, Any]]] = []
        self._changed = asyncio.Condition()

    async def emit(self, event: str, data: dict[str, Any]) -> None:
        async with self._changed:
            self.events.append((event, data))
            self._changed.notify_all()

    async def wait_for_events(self, seen: int) -> None:
        async with self._changed:
            await self._changed.wait_for(lambda: len(self.events) > seen)


SCANS: dict[str, Scan] = {}


async def run_one(check: Any, listing: dict[str, Any]) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(check.run(listing), timeout=CHECK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return could_not_verify(check.CHECK_ID, f"Timed out after {CHECK_TIMEOUT_SECONDS:g} seconds.")
    except Exception as exc:  # any failure must become could_not_verify, never a finding
        return could_not_verify(check.CHECK_ID, f"Check failed: {exc}")


def build_report(scan: Scan, results: list[dict[str, Any]]) -> dict[str, Any]:
    area_scores = [
        {
            "id": r["id"],
            "label": AREA_LABELS.get(r["id"], r["id"]),
            "score": r["score"],
            "level": level_for(r["score"]),
            "tag": r["tag"],
            "status": r["status"],
        }
        for r in results
    ]
    checks = [{k: r[k] for k in ("id", "status", "headline", "details", "source_url", "fetched_at")} for r in results]
    score, verdict = score_report(area_scores)
    good = [
        {"text": c["headline"], "source_label": None, "source_url": c["source_url"]}
        for c, a in zip(checks, area_scores)
        if a["level"] == "good"
    ]
    watch_out = [
        {"text": c["headline"], "source_label": None, "source_url": c["source_url"]}
        for c, a in zip(checks, area_scores)
        if a["level"] in {"watch", "risk", "unknown"}
    ]
    sourced = [c for c in checks if c["source_url"]]
    data_mode = "live" if is_live_mode() else "stub"
    return {
        "schema_version": "0.1.0",
        "data_mode": data_mode,
        "disclaimer": (
            "DEMO DATA: checks ran in stub mode. Results are simulated and are not real findings."
            if data_mode == "stub"
            else ""
        ),
        "scan_id": scan.id,
        "generated_at": now_iso(),
        "duration_seconds": round(time.monotonic() - scan.started, 1),
        "listing": scan.listing,
        "score": score,
        "verdict": verdict,
        "summary": build_summary(checks),
        "sources_count": len(sourced),
        "sources": [],
        "area_scores": area_scores,
        "checks": checks,
        "good": good,
        "watch_out": watch_out,
        "rent_compare": {
            "status": "could_not_verify",
            "currency": "INR",
            "listing_rent": scan.listing.get("rent"),
            "fair_range": None,
            "median": None,
            "premium_percent": None,
            "monthly_extra": None,
            "yearly_overpay": None,
            "spread": None,
            "portals": [],
            "cheapest_comparable": None,
            "fetched_at": now_iso(),
        },
        "residents": {"status": "could_not_verify", "window": None, "total_mentions": 0, "themes": [], "quotes": []},
        "questions_for_owner": build_owner_questions(checks, area_scores),
    }


async def run_scan(scan: Scan) -> None:
    total = len(ALL_CHECKS)
    await scan.emit("started", {"scan_id": scan.id, "total": total, "checks": [c.CHECK_ID for c in ALL_CHECKS]})
    results: dict[str, dict[str, Any]] = {}

    async def run_and_report(check: Any) -> None:
        result = await run_one(check, scan.listing)
        results[check.CHECK_ID] = result
        await scan.emit(
            "progress",
            {
                "scan_id": scan.id,
                "check_id": result["id"],
                "status": result["status"],
                "headline": result["headline"],
                "completed": len(results),
                "total": total,
            },
        )

    await asyncio.gather(*(run_and_report(c) for c in ALL_CHECKS))
    ordered = [results[c.CHECK_ID] for c in ALL_CHECKS]
    scan.report = build_report(scan, ordered)
    scan.status = "complete"
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        (CACHE_DIR / f"{scan.id}.json").write_text(json.dumps(scan.report, indent=2), encoding="utf-8")
    except OSError:
        pass  # caching is best effort
    await scan.emit("report", scan.report)
    await scan.emit("done", {"scan_id": scan.id, "status": scan.status})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "mode": "live" if is_live_mode() else "stub"}


@app.post("/scan")
async def start_scan(req: ScanRequest) -> dict[str, Any]:
    scan_id = uuid.uuid4().hex[:12]
    scan = Scan(scan_id, req.model_dump())
    SCANS[scan_id] = scan
    scan.task = asyncio.create_task(run_scan(scan))  # keep a reference so it is not GC'd
    return {"scan_id": scan_id, "stream_url": f"/scan/{scan_id}/stream", "report_url": f"/scan/{scan_id}"}


@app.get("/scan/{scan_id}/stream")
async def stream_scan(scan_id: str) -> StreamingResponse:
    scan = SCANS.get(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Unknown scan id")

    async def events() -> AsyncIterator[str]:
        seen = 0
        while True:
            # Replays earlier events, so a client that connects late still sees everything.
            while seen < len(scan.events):
                event, data = scan.events[seen]
                seen += 1
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                if event == "done":
                    return
            try:
                await asyncio.wait_for(scan.wait_for_events(seen), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/scan/{scan_id}")
async def get_scan(scan_id: str) -> dict[str, Any]:
    scan = SCANS.get(scan_id)
    if scan is not None:
        return {"scan_id": scan_id, "status": scan.status, "report": scan.report}
    cached = CACHE_DIR / f"{scan_id}.json"
    if scan_id.isalnum() and cached.is_file():
        return {"scan_id": scan_id, "status": "complete", "report": json.loads(cached.read_text(encoding="utf-8"))}
    raise HTTPException(status_code=404, detail="Unknown scan id")
