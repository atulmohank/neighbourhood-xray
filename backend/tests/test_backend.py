import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["XRAY_MODE"] = "stub"
# Never call Groq or use real keys from backend/.env in tests (load_dotenv does not override these).
os.environ["LLM_PROVIDER"] = "none"
os.environ["TINYFISH_API_KEY"] = ""
os.environ["XRAY_STUB_MIN_DELAY"] = "0.01"
os.environ["XRAY_STUB_MAX_DELAY"] = "0.05"
os.environ["XRAY_DEMO_STEP"] = "0"

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


def test_check_states_and_minimum_checked():
    areas = [
        {"id": "power_cuts", "label": "Power", "score": 80, "status": "verified"},  # 20% of 20 = 4 points
        {"id": "water_cuts", "label": "Water supply", "score": 100, "status": "no_reports"},  # checked, 0 points
        {"id": "water_source", "label": "Water source", "score": None, "status": "could_not_verify"},
    ]
    assert scoring.overall_score(areas) == 96
    assert scoring.unverified_labels(areas) == ["Water source"]
    # Only one checked area -> no score, "Not enough verified data".
    one = [areas[0], areas[2]]
    assert scoring.score_report(one) == (None, "Not enough verified data")
    assert scoring.score_report([{"id": "power_cuts", "score": None, "status": "could_not_verify"}])[0] is None


def test_notice_windows_weighting():
    # Last 30 days full weight, 1-12 months half weight, handoff caps.
    assert scoring.water_cuts_deduction(1, 0) == 5
    assert scoring.water_cuts_deduction(0, 2) == 5
    assert scoring.water_cuts_deduction(4, 4) == 25
    assert scoring.power_cuts_deduction(0, 4) == 6


def test_timeout_and_error_become_could_not_verify(monkeypatch):
    class Slow:
        CHECK_ID = "power_cuts"

        @staticmethod
        async def run(listing):
            await asyncio.sleep(1)

    class Broken:
        CHECK_ID = "flooding"

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
        health = client.get("/health").json()
        assert health["status"] == "ok" and health["mode"] == "stub"
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
    assert not (BACKEND / "cache" / "hsr-layout.json").exists()  # stub scans are never cached


def test_cors_allows_extension_origin():
    with TestClient(main.app) as client:
        r = client.options(
            "/scan",
            headers={"Origin": "chrome-extension://abcdef", "Access-Control-Request-Method": "POST"},
        )
        assert r.headers.get("access-control-allow-origin") == "chrome-extension://abcdef"


def test_handoff_deduction_rules():
    assert scoring.water_cuts_deduction(100) == 25
    assert scoring.power_cuts_deduction(100) == 20
    assert scoring.flooding_deduction(True, 10) == 25
    assert scoring.flooding_deduction(False, 0) == 0
    assert scoring.water_source_deduction(True) == 10
    assert scoring.rent_deduction(50) == 20 and scoring.rent_deduction(-5) == 0
    assert scoring.area_score("water_cuts", 25) == 0 and scoring.area_score("power_cuts", 0) == 100
    assert scoring.verdict_for(75) == "Looks good"
    assert scoring.verdict_for(74) == "Check before signing"
    assert scoring.verdict_for(49) == "High risk"


def test_flooding_matches_official_ward():
    from checks.flooding import check_flooding

    hsr7 = check_flooding({"locality": "HSR Layout Sector 7, Bengaluru"})
    assert hsr7["status"] == "verified" and hsr7["source_url"].startswith("https://data.opencity.in/")
    assert hsr7["score"] == scoring.area_score("flooding", scoring.flooding_deduction(True, 0))
    hsr2 = check_flooding({"locality": "HSR Layout Sector 2, Bengaluru"})
    assert hsr2["score"] < hsr7["score"]  # sector 2 has its own listed spot
    # Dataset read fine, nothing listed for the ward -> no_reports (0 deduction), never could_not_verify.
    bsk = check_flooding({"locality": "Banashankari, Bengaluru"})
    assert bsk["status"] == "no_reports" and bsk["score"] == 100
    mdp = check_flooding({"locality": "Mahadevapura"})
    assert mdp["status"] == "no_reports" and any("zone" in d for d in mdp["details"])
    sub = check_flooding({"locality": "Rajiv Gandhi Nagar, 7th Sector, Somasundarapalya"})
    assert sub["status"] == "verified"  # sub-area normalised to HSR Layout


def test_water_source_uses_listing_text_only():
    from checks.water_source import check_water_source

    url = "https://www.nobroker.in/property/x"
    none = check_water_source({"locality": "HSR Layout Sector 7", "listing_text": "2 BHK, lift", "listing_url": url})
    assert none["status"] == "no_reports" and "Area-level context only" in none["details"][-1]
    unread = check_water_source({"locality": "x", "listing_url": url}, "")
    assert unread["status"] == "could_not_verify"
    bore = check_water_source({"locality": "x", "listing_text": "borewell water 24x7", "listing_url": url})
    assert bore["status"] == "verified" and bore["score"] == 0 and bore["source_url"] == url
    cauvery = check_water_source({"locality": "x", "listing_text": "Cauvery and borewell", "listing_url": url})
    assert cauvery["score"] == 100


def test_demo_replays_cached_live_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CACHE_DIR", tmp_path)
    saved = json.loads((ROOT / "shared" / "report.example.json").read_text(encoding="utf-8"))
    saved["data_mode"] = "live"
    main.save_to_cache(saved)
    assert (tmp_path / "hsr-layout-sector-2-bengaluru.json").is_file() and (tmp_path / "latest.json").is_file()
    with TestClient(main.app) as client:
        assert client.post("/scan?demo=1", json={"locality": "Nowhere"}).status_code == 200  # falls back to latest
        scan_id = client.post("/scan?demo=1", json={"locality": "HSR Layout Sector 2, Bengaluru"}).json()["scan_id"]
        with client.stream("GET", f"/scan/{scan_id}/stream") as s:
            events = parse_sse("".join(s.iter_text()))
        report = events[-2][1]
        assert report["data_mode"] == "cache" and report["score"] == saved["score"]
        assert report["cached_from"]["generated_at"] == saved["generated_at"]
    monkeypatch.setattr(main, "CACHE_DIR", tmp_path / "empty")
    with TestClient(main.app) as client:
        assert client.post("/scan?demo=1", json={"locality": "HSR"}).status_code == 404


def test_summary_falls_back_to_template(monkeypatch):
    import summary

    report = {"listing": {"locality": "X"}, "score": 90, "verdict": "Looks good",
              "checks": [{"id": "power_cuts", "status": "verified", "headline": "2 power cut reports", "details": []}]}
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    monkeypatch.setattr(summary, "GROQ_CHAT_URL", "http://127.0.0.1:9/unreachable")
    text, method = asyncio.run(summary.generate_summary(report))
    assert method == "template" and "2 power cut reports" in text
    assert summary.numbers_grounded("2 reports", '{"x": "2 power cut reports"}')
    assert not summary.numbers_grounded("7 reports", '{"x": "2 power cut reports"}')


def test_water_source_reads_nobroker_field():
    from checks.water_source import check_water_source

    url = "https://www.nobroker.in/property/x"
    corp = check_water_source({"locality": "x", "listing_url": url}, "##### Water Supply ##### Corporation ##### Floors")
    assert corp["status"] == "verified" and corp["score"] == 100
    bore = check_water_source({"locality": "x", "listing_url": url}, "##### Water Supply ##### Borewell #####")
    assert bore["status"] == "verified" and bore["score"] == 0


def test_rent_compare_parsing_and_stats():
    from checks import rent_compare as rc

    from checks.places import match_area

    assert match_area("Rajiv Gandhi Nagar, HSR Layout Sector 7, Bengaluru") == "HSR Layout"
    assert match_area("Rajiv Gandhi Nagar, 7th Sector, HSR Layout, Bangalore") == "HSR Layout"
    kept, dropped = rc.drop_outliers([{"rent": r} for r in (14000, 40000, 44000, 50000, 120000)])
    assert [c["rent"] for c in dropped] == [14000, 120000]
    urls = rc.portal_urls("HSR Layout", 2)
    assert urls["NoBroker"].endswith("/2bhk-flats-for-rent-in-hsr_layout_bangalore")
    links = [
        "https://www.nobroker.in/property/2-bhk-apartment-for-rent-in-hsr-layout-sector-7-bangalore-for-rs-22000/aa11/detail",
        "https://www.nobroker.in/property/2-bhk-apartment-for-rent-in-hsr-layout-sector-7-bangalore-for-rs-22000/aa11/detail",
        "https://www.nobroker.in/property/3-bhk-apartment-for-rent-in-hsr-layout-bangalore-for-rs-60000/bb22/detail",
        "https://www.nobroker.in/property/2-bhk-apartment-for-rent-in-junnasandra-bangalore-for-rs-37000/cc33/detail",
    ]
    nb = rc.parse_nobroker(links, 2)
    assert [c["rent"] for c in nb] == [22000, 37000]
    md = "## 2 BHK Flat for Rent in HSR Layout, Bangalore\n\nSuper Area\n\n1286 sqft\n\n₹28,000\n\nSecurity Deposit\n"
    mb = rc.parse_magicbricks(md, ["https://www.magicbricks.com/propertyDetails/2-BHK-1286-Sq-ft-X&id=1"], 2, "https://mb")
    assert mb[0]["rent"] == 28000 and mb[0]["source_url"].endswith("&id=1")
    kept = rc.keep(nb + mb, ["hsr"], None)
    assert sorted(c["rent"] for c in kept) == [22000, 28000]  # Junnasandra dropped
    out = rc.build_rent_compare(30000, 2, kept + [dict(kept[0], rent=32000, source_url="u3")], urls)
    assert out["median"] == 28000 and out["premium_percent"] == 7.1 and out["monthly_extra"] == 2000
    assert out["cheapest_comparable"]["rent"] == 22000 and out["spread"]["n"] == 3


def test_official_notice_table_and_events():
    from datetime import date

    from checks import notices as nt

    page = """<table>
    <tr><th>Sl</th><th>Description</th><th>Date</th><th>Doc</th></tr>
    <tr><td>1</td><td>Water Shutdown on 31-07-2026.</td><td>27.07.2026</td><td><a href="/uploads/a.pdf">Download</a></td></tr>
    <tr><td>2</td><td>JULY 2026</td><td>Contingency Power Outages details</td><td></td></tr>
    <tr><td>3</td><td>Old notice</td><td>2021-06-16</td><td></td></tr>
    </table>"""
    rows = nt.parse_notice_table(page, "https://bwssb.karnataka.gov.in/109/Press-Release/en")
    assert [r["date"] for r in rows] == ["2026-07-31", "2026-07-01", "2021-06-16"]
    assert rows[0]["urls"] == ["https://bwssb.karnataka.gov.in/uploads/a.pdf"]
    assert "JULY 2026" in rows[1]["title"]
    assert nt.date_in_text("FY 2025-26 details") == date(2026, 3, 31)

    since = date(2025, 10, 30)
    data = {"url": "https://x", "notices": [
        {"title": "Shutdown", "date": "2026-07-31", "urls": ["https://x/a.pdf"],
         "documents": [{"url": "https://x/a.pdf", "readable": True,
                        "events": [{"date": "2026-07-31", "areas": ["H.S.R. Layout", "Agara"]}]}]},
        {"title": "Shutdown 2", "date": "2026-07-22", "urls": ["https://x/b.jpg"],
         "documents": [{"url": "https://x/b.jpg", "readable": False, "events": []}]},
    ]}
    events, unreadable = nt.official_events(data, ["hsr"], since)
    assert [e["date"] for e in events] == ["2026-07-31"] and events[0]["source_url"] == "https://x/a.pdf"
    assert [n["title"] for n in unreadable] == ["Shutdown 2"]
    assert nt.official_events(data, ["banashankari"], since)[0] == []


def test_ask_endpoint_falls_back_without_llm():
    with TestClient(main.app) as client:
        assert client.post("/ask", json={"scan_id": "nope", "question": "Is water bad?"}).status_code == 404
        scan_id = client.post("/scan", json={"locality": "HSR Layout", "rent": 30000, "bhk": 2}).json()["scan_id"]
        with client.stream("GET", f"/scan/{scan_id}/stream") as s:
            "".join(s.iter_text())
        a = client.post("/ask", json={"scan_id": scan_id, "question": "Is it safe at night?"}).json()
        assert a["in_scan"] is False and a["answer"] == "Not in this scan." and "night" in a["owner_question"]


def test_ask_context_sources_are_numbered_from_scan():
    import ask

    report = json.loads((ROOT / "shared" / "report.example.json").read_text(encoding="utf-8"))
    facts, sources = ask.scan_context(report)
    urls = [s["url"] for s in sources]
    assert len(urls) == len(set(urls)) and all(u.startswith("http") for u in urls)
    assert facts["listing"]["rent"] == 32000


def test_empty_agent_page_read_is_a_failure_not_no_reports(monkeypatch):
    import pytest

    import tinyfish_client as tf
    from checks import notices as nt

    async def fake_agent(url, goal, schema=None, **kw):
        return {"run_id": "r", "result": {"page_loaded": True, "notices": []}}  # no latest_notice_date

    monkeypatch.setattr(tf, "run_agent", fake_agent)
    with pytest.raises(tf.TinyFishError):
        asyncio.run(nt.read_page_agent(nt.SOURCES["bwssb"], __import__("datetime").date(2025, 10, 30)))


def test_cache_drops_listing_text(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CACHE_DIR", tmp_path)
    report = json.loads((ROOT / "shared" / "report.example.json").read_text(encoding="utf-8"))
    report["listing"]["listing_text"] = "Owner: Some Person, phone hidden"
    main.save_to_cache(report)
    saved = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert "listing_text" not in saved["listing"] and saved["listing"]["locality"]


def test_water_source_fetches_listing_when_sent_text_is_silent(monkeypatch):
    from checks import water_source as ws

    async def fake_fetch(url):
        return "##### Water Supply ##### Corporation #####"

    monkeypatch.setattr(ws, "fetch_listing_text", fake_fetch)
    listing = {"locality": "HSR Layout", "listing_url": "https://www.nobroker.in/x", "listing_text": "2 BHK, lift, parking"}
    text = asyncio.run(ws.listing_text_for(listing))
    r = ws.check_water_source(listing, text)
    assert r["status"] == "verified" and r["score"] == 100
    # Live-page innerText can run the label and value together.
    assert ws.check_water_source(listing, "Water SupplyCorporation")["status"] == "verified"


def test_summary_wording_follows_check_states():
    import summary

    checks = [
        {"id": "water_cuts", "status": "no_reports", "headline": "No water cuts reported"},
        {"id": "power_cuts", "status": "verified", "headline": "2 power cuts in last 30 days"},
    ]
    text = summary.build_summary(checks)
    assert "No reports found: water cuts." in text and "Could not verify" not in text
    assert not summary.wording_matches_states("Water cuts could not be verified.", checks)
    assert summary.wording_matches_states("No water cut reports were found.", checks)
    checks.append({"id": "rent_compare", "status": "could_not_verify", "headline": "x"})
    assert "Could not verify: rent compare." in summary.build_summary(checks)


def test_news_weighting_and_same_day_dedupe(monkeypatch, tmp_path):
    from datetime import date

    import tinyfish_client as tf
    from checks import notices as nt

    monkeypatch.setattr(nt, "NEWS_MEMORY_DIR", tmp_path)  # never write fake articles into the real memory

    arts = {
        "https://n/a": ("Power cut in Banashankari on Oct 31", "2026-10-29", "Banashankari 3rd stage affected"),
        "https://n/b": ("Bengaluru power cut: full list of areas", "2026-10-29", "Areas: Jayanagar, Banashankari"),
        "https://n/c": ("Bengaluru power outage list for June 20", "2026-06-20", "Banashankari, BTM"),
        "https://n/d": ("Bengaluru power cut areas", "2026-06-21", "Only Whitefield"),  # doesn't name the area
    }

    async def fake_search(query, **kw):
        return [{"url": u, "title": t[0], "publisher": "X"} for u, t in arts.items()]

    async def fake_fetch(urls, **kw):
        return [{"url": u, "title": arts[u][0], "published_date": arts[u][1], "text": arts[u][2]} for u in urls], []

    monkeypatch.setattr(tf, "search", fake_search)
    monkeypatch.setattr(tf, "fetch", fake_fetch)
    events, _ = asyncio.run(nt.news_events(nt.SOURCES["bescom"], "Banashankari", date(2025, 10, 30)))
    by_date = {e["date"]: e for e in events}
    assert set(by_date) == {"2026-10-29", "2026-06-20"}  # one per date; Whitefield-only article dropped
    assert by_date["2026-10-29"]["scope"] == "local" and by_date["2026-10-29"]["weight"] == 1.0
    assert by_date["2026-06-20"]["scope"] == "citywide" and by_date["2026-06-20"]["weight"] == 0.5


def test_news_memory_keeps_earlier_reports(monkeypatch, tmp_path):
    from datetime import date

    from checks import notices as nt

    monkeypatch.setattr(nt, "NEWS_MEMORY_DIR", tmp_path)
    src, since = nt.SOURCES["bwssb"], date(2025, 10, 30)
    first = [{"kind": "news", "scope": "citywide", "title": "A", "date": "2026-09-22", "weight": 0.5, "source_url": "https://a"}]
    assert len(nt.merge_news_memory(src, "Banashankari", first, since)) == 1
    later = [{"kind": "news", "scope": "local", "title": "B", "date": "2026-10-07", "weight": 1.0, "source_url": "https://b"}]
    merged = nt.merge_news_memory(src, "Banashankari", later, since)  # search missed A this time
    assert [e["date"] for e in merged] == ["2026-10-07", "2026-09-22"]
    old = [{"kind": "news", "scope": "local", "title": "C", "date": "2025-01-01", "weight": 1.0, "source_url": "https://c"}]
    assert all(e["date"] != "2025-01-01" for e in nt.merge_news_memory(src, "Banashankari", old, since))


def _fake_residents_sites(monkeypatch, pages, blocked=("quora.com",)):
    import tinyfish_client as tf

    async def fake_search(query, include_domains="", **kw):
        return [{"url": u, "title": p["title"]} for u, p in pages.items() if any(d in u for d in include_domains.split(","))]

    async def fake_fetch(urls, **kw):
        res = [{"url": u, "title": pages[u]["title"], "published_date": pages[u]["date"], "text": pages[u]["text"]}
               for u in urls if not any(b in u for b in blocked)]
        errs = [{"url": u, "error": "bot_blocked"} for u in urls if any(b in u for b in blocked)]
        return res, errs

    monkeypatch.setattr(tf, "search", fake_search)
    monkeypatch.setattr(tf, "fetch", fake_fetch)


def test_residents_quotes_themes_and_blocked_sites(monkeypatch, tmp_path):
    from checks import residents

    monkeypatch.setattr(residents, "CACHE_DIR", tmp_path)
    pages = {
        "https://www.reddit.com/r/HSRLayout/comments/1/power": {
            "title": "Power cut in HSR", "date": "2026-05-01",
            "text": "r/HSRLayout u/someone\nAnyone else experiencing power outage for the nth time this week in HSR?\n"
                    "Ask u/admin for details about the water tanker schedule please today."},
        "https://x.com/chairmanbwssb/status/1": {
            "title": "BWSSB", "date": "2026-06-22", "text": "HSR Layout water samples meet all quality standards today."},
        "https://x.com/someone/status/2": {
            "title": "x", "date": "2026-10-18", "text": "Some Name on X: \"HSR Layout water supply was cut for two days.\""},
        "https://www.quora.com/q": {"title": "q", "date": "2026-05-01", "text": "HSR Layout water is fine"},
        "https://www.reddit.com/r/bangalore/comments/2/old": {
            "title": "old", "date": "2024-01-01", "text": "HSR Layout flooding was terrible this monsoon season again."},
    }
    _fake_residents_sites(monkeypatch, pages)
    r = asyncio.run(residents.scan_residents({"locality": "Rajiv Gandhi Nagar, 7th Sector, HSR Layout"}))
    assert r["status"] == "verified"
    sites = {s["site"]: s["status"] for s in r["sources"]}
    assert sites == {"Reddit": "ok", "X": "ok", "Quora": "could_not_verify"}
    texts = [q["text"] for q in r["quotes"]]
    assert "Anyone else experiencing power outage for the nth time this week in HSR?" in texts
    assert all("u/" not in t and " on X" not in t for t in texts)  # no usernames/names
    assert not any("quality standards" in t for t in texts)  # official account excluded
    assert not any("terrible this monsoon" in t for t in texts)  # outside the 12-month window
    assert all(q["source_url"].startswith("https://") and q["posted_at"] for q in r["quotes"])
    assert {t["id"] for t in r["themes"]} >= {"power"}


def test_residents_no_reports_when_nothing_relevant(monkeypatch, tmp_path):
    from checks import residents

    monkeypatch.setattr(residents, "CACHE_DIR", tmp_path)
    _fake_residents_sites(monkeypatch, {"https://www.reddit.com/r/x/comments/3/y": {
        "title": "Cats", "date": "2026-05-01", "text": "My cat likes Koramangala cafes a lot honestly."}})
    r = asyncio.run(residents.scan_residents({"locality": "HSR Layout"}))
    assert r["status"] == "no_reports" and r["quotes"] == [] and r["themes"] == []


def test_ask_wording_states_and_owner_origins():
    import ask
    import summary

    assert ask.soften_overclaims("No power cuts have occurred in the last 30 days.") == \
        "No power cuts were reported in this scan in the last 30 days."
    assert ask.soften_overclaims("There have been no water cuts.").startswith("This scan found no reports of")
    report = {"checks": [{"id": "water_cuts", "status": "no_reports"}, {"id": "power_cuts", "status": "verified"}]}
    used = [{"label": "Power", "url": "https://x", "check_id": "power_cuts"}]
    assert ask.check_states_for(report, used, "anything") == [{"check_id": "power_cuts", "label": "Power", "status": "verified"}]
    assert ask.check_states_for(report, [], "Is water bad here?")[0]["status"] == "no_reports"  # topic fallback
    items = summary.build_owner_items(
        [{"id": "power_cuts", "status": "verified"}],
        [{"id": "power_cuts", "label": "Power", "level": "watch"}])
    assert items == [{"text": summary._TOPIC_QUESTIONS["power_cuts"], "from": "power check", "check_id": "power_cuts"}]


def test_failed_news_uses_memory_and_degraded_scans_are_not_cached(monkeypatch, tmp_path):
    from datetime import date, datetime, timezone

    import tinyfish_client as tf
    from checks import notices as nt

    monkeypatch.setattr(nt, "NEWS_MEMORY_DIR", tmp_path / "mem")
    today = datetime.now(timezone.utc).date()
    nt.merge_news_memory(nt.SOURCES["bescom"], "Banashankari", [{
        "kind": "news", "scope": "citywide", "title": "Power cut list", "date": today.isoformat(),
        "weight": 0.5, "publisher": "X", "source_url": "https://n/x"}], date(2000, 1, 1))

    async def official(source_id, today):
        return {"method": "page HTML", "latest_notice_date": "2026-07-01", "notices": [], "url": "https://o"}

    async def down(*a, **k):
        raise tf.TinyFishError("getaddrinfo failed")

    monkeypatch.setattr(nt, "official_notices", official)
    monkeypatch.setattr(nt, "news_events", down)
    import scoring

    r = asyncio.run(nt.run_notices_check("power_cuts", "bescom", {"locality": "Banashankari"},
                                         scoring.power_cuts_deduction, scoring.area_score, "power cut"))
    assert r["status"] == "verified" and r["degraded"] is True and r["confidence"] == "partial"
    assert any("verified on earlier scans" in d for d in r["details"])


def test_live_scan_with_a_failed_check_is_not_cached(monkeypatch, tmp_path):
    class Broken:
        CHECK_ID = "rent_compare"

        @staticmethod
        async def run(listing):
            raise OSError("getaddrinfo failed")

    class Fine:
        def __init__(self, cid):
            self.CHECK_ID = cid

        async def run(self, listing):
            return {"id": self.CHECK_ID, "status": "no_reports", "score": 100, "tag": "None", "headline": "ok",
                    "details": [], "source_url": "https://x", "fetched_at": "t"}

    async def no_residents(listing):
        return {"status": "no_reports", "themes": [], "quotes": [], "sources": [{"site": "Reddit", "status": "ok"}]}

    monkeypatch.setattr(main, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(main, "is_live_mode", lambda: True)
    monkeypatch.setattr(main, "ALL_CHECKS", [Fine("water_cuts"), Fine("power_cuts"), Broken])
    monkeypatch.setattr(main.residents, "run", no_residents)

    async def go():
        scan = main.Scan("t1", {"locality": "Banashankari", "rent": 26000, "bhk": 2})
        await main.run_scan(scan)
        return scan.report

    report = asyncio.run(go())
    assert report["degraded_checks"] == ["rent_compare"]
    assert not (tmp_path / "latest.json").exists()
