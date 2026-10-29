# neighbourhood-xray

AI-powered neighbourhood intelligence using TinyFish.

Neighbourhood X-Ray is a Chrome extension that helps renters check a neighbourhood
before renting a flat. It reads the listing (locality, rent, BHK) from a NoBroker
page, runs a set of checks through a FastAPI backend, and shows a scored report in
the Chrome side panel.

> Two modes: **stub** (default, no keys, simulated demo data labelled *Demo*) and
> **live** (`XRAY_MODE=live` in `backend/.env`: real TinyFish, OpenCity and Groq calls).
> See *Live mode* below for what is live and what is still missing.

## Layout

```
shared/report.example.json   Canonical report contract (illustrative example data)
backend/
  main.py                    FastAPI app: /health, /scan, /scan/{id}/stream (SSE), /scan/{id}
  scoring.py                 Handoff rule: 100 minus capped deductions per area
  summary.py                 Groq summary (template fallback) + owner questions
  tinyfish_client.py         TinyFish Agent (run-sse), Search and Fetch
  checks/                    One module per check (stub data in stub mode)
  data/                      Static datasets: OpenCity flood KML, BWSSB Cauvery CSV
  scripts/                   check_keys.py, tinyfish_smoke.py, live_checks_probe.py
  cache/                     Saved live scans + official-page agent results (git-ignored)
  tests/                     pytest tests
  requirements.txt, .env.example
extension/                   Chrome Manifest V3 extension with a side panel
  data/report.example.json   Copy of shared/report.example.json (keep identical; a test checks this)
design/xray_ui_design/       UI design reference (build from final/)
```

## Backend setup (Windows PowerShell)

Requires Python 3.11+.

```powershell
cd backend
py -3.11 -m venv .venv          # or: python -m venv .venv
.\.venv\Scripts\Activate.ps1    # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
Copy-Item .env.example .env     # optional; stub mode needs no keys
```

Start the backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```

Check it: open http://localhost:8000/health (expect `{"status":"ok","mode":"stub"}`)
or http://localhost:8000/docs.

Run the tests:

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
```

### API

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Liveness + current mode (`stub` / `live`) |
| POST | `/scan` | Body `{"locality": "...", "rent": 32000, "bhk": 2, "listing_url": "...", "listing_text": "..."}` → `{"scan_id": ...}`. Add `?demo=1` to replay the saved live scan for that locality (or `latest.json`) |
| GET | `/scan/{id}/stream` | SSE: `started`, one `progress` per finished check, `report` (full report), `done` |
| GET | `/scan/{id}` | `{"scan_id", "status", "report"}` (report is `null` while running) |

Checks run concurrently with a timeout each (`XRAY_CHECK_TIMEOUT`: 45 s in stub
mode, 300 s in live mode because agent runs on the government sites take ~250 s).
Any error or timeout becomes `could_not_verify`; it is never turned into a finding.

Check statuses: `verified` (real source, live mode only), `stub` (simulated demo
data), `could_not_verify`.

## Chrome extension

1. Start the backend (above).
2. Open `chrome://extensions`, turn on **Developer mode**.
3. Click **Load unpacked** and select the `extension` folder.
4. Open a NoBroker rental listing and click the Neighbourhood X-Ray toolbar icon
   to open the side panel.
5. Check the locality (type it if extraction failed) and click **Scan neighbourhood**.

The panel opens on the bundled example report (labelled *Example data*). Scan
results from stub mode are labelled *Demo*. If you edit `shared/report.example.json`,
copy it to `extension/data/report.example.json`:

```powershell
Copy-Item shared\report.example.json extension\data\report.example.json
```

## Live mode

Set `XRAY_MODE=live` in `backend/.env` (with `TINYFISH_API_KEY`, `LLM_PROVIDER=groq`,
`LLM_MODEL`, `LLM_API_KEY`). Check keys without printing them:
`.\.venv\Scripts\python scripts\check_keys.py`.

| Check | Live source | Notes |
|---|---|---|
| `power_cuts` | BESCOM Contingency Power Outages page (TinyFish agent, India proxy) + news (TinyFish Search + Fetch) | News shown as "News report — publisher", never as an official notice |
| `water_cuts` | BWSSB Press Release page (TinyFish agent, India proxy) + news | Same labelling |
| `flooding` | OpenCity flood-vulnerable locations KML (static, dataset 27 Nov 2025) | Ward match only; zone-only or no match = could_not_verify |
| `water_source` | Listing text (`listing_text`); BWSSB Cauvery stage CSV as area context only | Without a statement in the listing = could_not_verify + owner question |
| `rent_compare` | not implemented | could_not_verify in live mode |

- Official pages are the same for every locality, so each agent result is cached for
  6 hours in `backend/cache/official_<source>.json` and filtered per locality.
- News counts only if the fetched article's own publish date is within 30 days, its
  text names the locality and its title is about a cut/outage.
- Every successful live scan is saved to `backend/cache/<locality>.json` and
  `latest.json`; `POST /scan?demo=1` replays it with `data_mode: "cache"`.
- Summary: Groq, ~60 words, 10 s timeout, only the report's own facts; falls back to a
  template on any error, an over-long reply or a number not in the report.

## Current limitations

- BESCOM's page only links a scanned full-year PDF and BWSSB's newest press releases
  were from July 2026 when checked (29 Oct 2026), so recent hits usually come from news.
- Agent runs take ~250 s; the first live scan in a 6-hour window is slow.
- TinyFish returns no credit usage in the API; check the dashboard.
- Rent comparison and residents are not live yet (could_not_verify). The Rent and
  Residents tabs show real layouts only for the example report.
- The extension does not send `listing_text` yet, so `water_source` is usually
  could_not_verify; there's no UI switch for `?demo=1` yet.
- NoBroker extraction uses page-title/text heuristics and may miss fields.
- Running scans are kept in memory; restarting the backend loses them.
- The Ask tab's free-form questions are not implemented.

## Secrets

Never commit `.env` or API keys. `.env.example` lists variable names only.
