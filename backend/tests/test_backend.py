import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["XRAY_MODE"] = "stub"
os.environ["XRAY_STUB_MIN_DELAY"] = "0.01"
os.environ["XRAY_STUB_MAX_DELAY"] = "0.05"

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import scoring  # noqa: E402

REQUIRED_TOP = {
    "listing", "score", "verdict", "summary", "sources_count", "sources", "area_scores",
    "checks", "good", "watch_out", "rent_compare", "residents", "questions_for_owner",
}
STATUSES = {"verified", "stub", "could_not_verify"}


def test_example_contract_shape():
    report = json.loads((ROOT / "shared" / "report.example.json").read_text(encoding="utf-8"))
    assert REQUIRED_TOP <= report.keys()
    assert report["data_mode"] == "example" and "ILLUSTRATIVE" in report["disclaimer"]
    assert {"locality", "rent", "bhk"} <= report["listing"].keys()
    for a in report["area_scores"]:
        assert {"id", "label", "score", "tag", "status"} <= a.keys()
    for c in report["checks"]:
        assert {"id", "status", "headline", "details", "source_url", "fetched_at"} <= c.keys()
        assert c["status"] in STATUSES
    assert any(c["status"] == "could_not_verify" for c in report["checks"])
    assert report["sources_count"] == sum(s["count"] for s in report["sources"])
    rc = report["rent_compare"]
    assert {"fair_range", "median", "portals", "cheapest_comparable"} <= rc.keys()
    assert all("source_url" in q for q in report["residents"]["quotes"])


def test_extension_copy_matches_shared_contract():
    shared = (ROOT / "shared" / "report.example.json").read_bytes()
    copy = (ROOT / "extension" / "data" / "report.example.json").read_bytes()
    assert json.loads(shared) == json.loads(copy)


def test_sample_report_scores_58():
    report = scoring.sample_report()
    assert report["score"] == 58
    assert report["verdict"] == "Check before signing"


def test_unverified_areas_are_excluded():
    areas = [
        {"id": "power", "score": 80, "status": "verified"},
        {"id": "water_source", "score": None, "status": "could_not_verify"},
    ]
    assert scoring.overall_score(areas) == 80
    assert scoring.score_report([{"id": "power", "score": None, "status": "could_not_verify"}]) == (
        None,
        "Not enough data",
    )


def test_timeout_and_error_become_could_not_verify(monkeypatch):
    class Slow:
        CHECK_ID = "power"

        @staticmethod
        async def run(listing):
            await asyncio.sleep(1)

    class Broken:
        CHECK_ID = "flood_risk"

        @staticmethod
        async def run(listing):
            raise ValueError("boom")

    monkeypatch.setattr(main, "CHECK_TIMEOUT_SECONDS", 0.05)
    slow = asyncio.run(main.run_one(Slow, {}))
    broken = asyncio.run(main.run_one(Broken, {}))
    assert slow["status"] == "could_not_verify" and slow["score"] is None
    assert "Timed out" in slow["details"][0]
    assert broken["status"] == "could_not_verify" and "boom" in broken["details"][0]


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.splitlines() if not ln.startswith(":")]
        if not lines:
            continue
        event = next(ln[7:] for ln in lines if ln.startswith("event: "))
        data = json.loads(next(ln[6:] for ln in lines if ln.startswith("data: ")))
        events.append((event, data))
    return events


def test_scan_flow_over_sse():
    with TestClient(main.app) as client:
        assert client.get("/health").json() == {"status": "ok", "mode": "stub"}
        r = client.post("/scan", json={"locality": "HSR Layout", "rent": 32000, "bhk": 2})
        scan_id = r.json()["scan_id"]
        with client.stream("GET", f"/scan/{scan_id}/stream") as s:
            body = "".join(s.iter_text())
        events = parse_sse(body)
        names = [e for e, _ in events]
        assert names[0] == "started"
        assert names.count("progress") == len(main.ALL_CHECKS)
        assert names[-2:] == ["report", "done"]
        report = events[-2][1]
        assert report["data_mode"] == "stub"
        assert report["score"] == 58 and report["verdict"] == "Check before signing"
        statuses = {c["id"]: c["status"] for c in report["checks"]}
        assert statuses["water_source"] == "could_not_verify"
        assert all(v in {"stub", "could_not_verify"} for v in statuses.values())  # never "verified" in stub mode

        got = client.get(f"/scan/{scan_id}").json()
        assert got["status"] == "complete" and got["report"]["scan_id"] == scan_id
        assert client.get("/scan/doesnotexist").status_code == 404
    (BACKEND / "cache" / f"{scan_id}.json").unlink(missing_ok=True)


def test_cors_allows_extension_origin():
    with TestClient(main.app) as client:
        r = client.options(
            "/scan",
            headers={"Origin": "chrome-extension://abcdef", "Access-Control-Request-Method": "POST"},
        )
        assert r.headers.get("access-control-allow-origin") == "chrome-extension://abcdef"
