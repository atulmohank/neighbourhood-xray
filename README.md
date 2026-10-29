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

Check statuses:
- `verified`: findings exist, each with a date and `source_url`.
- `no_reports`: the source was read fine but has nothing for this area (counts as
  checked, 0 deduction), e.g. "No water cuts reported for HSR Layout in the past 12 months".
- `could_not_verify`: only when the source failed, was blocked or timed out.
- `stub`: simulated demo data (stub mode only).

If fewer than 2 checks are `verified`/`no_reports`, the report shows **"Not enough
verified data"** and lists the unverified checks instead of a score.

`POST /ask` with `{"scan_id", "question"}` answers from that scan's findings only
(Groq, ≤60 words, links taken from the scan's own sources) or says "Not in this
scan" with a question to ask the owner.

## Chrome extension

1. Start the backend (above).
2. Open `chrome://extensions`, turn on **Developer mode**.
3. Click **Load unpacked** and select the `extension` folder.
4. Open a NoBroker rental listing and click the Neighbourhood X-Ray toolbar icon
   to open the side panel.
5. Check the locality (type it if extraction failed) and click **Scan neighbourhood**.

The panel opens on the bundled example report (labelled *Example data*). Scan
results from stub mode are labelled *Demo*. **Replay cached scan** calls
`POST /scan?demo=1` and replays the saved live scan for the typed locality (or the
latest one), labelled *Cached*. If you edit `shared/report.example.json`,
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
| `power_cuts` | BESCOM Contingency Power Outages page: notice table read from the page HTML (TinyFish agent fallback), each notice document read by the TinyFish agent (India proxy); plus news (TinyFish Search + Fetch) | Last 30 days full weight, 1–12 months half weight. News shown as "News report — publisher", never as official |
| `water_cuts` | BWSSB Press Release page, same method | Same windows and labelling |
| `flooding` | OpenCity flood-vulnerable locations KML (static, dataset 27 Nov 2025) | Ward match = verified; nothing listed for the ward = no_reports |
| `water_source` | Listing text (sent by the extension, else fetched); BWSSB Cauvery stage CSV as area context only | Listing read but silent = no_reports + owner question |
| `rent_compare` | NoBroker + MagicBricks locality search pages via TinyFish Fetch; one agent run on NoBroker if fewer than 3 comparables | Same-BHK listings naming the same area; fair band = middle half of listed rents, not size-adjusted |

- Official pages are the same for every locality, so each page read is cached for
  6 hours in `backend/cache/official_<source>.json` and filtered per locality. Notice
  documents are cached permanently in `backend/cache/official_docs/`.
- Localities are matched on their parent area (`checks/places.py`: "Rajiv Gandhi Nagar,
  7th Sector, HSR Layout" → HSR Layout); the original name is kept for display.
- News counts only if the fetched article's own publish date is within 12 months, its
  text names the area and its title is about a cut/outage; same-day reports are one event.
- Every successful live scan is saved to `backend/cache/<locality>.json` and
  `latest.json`; `POST /scan?demo=1` replays it with `data_mode: "cache"`.
- Summary: Groq, ~60 words, 10 s timeout, only the report's own facts; falls back to a
  template on any error, an over-long reply or a number not in the report.

## Current limitations

- Official notices are sparse and hard to read: on 30 Oct 2026 BWSSB had 2 notices in
  the past 12 months (22 and 31 Jul 2026) and BESCOM one scanned full-year PDF. The
  BWSSB documents are a scanned image and legacy-font Kannada, which the TinyFish agent
  could not read, so their areas are unknown and they are never attributed to an area
  (the headline says so).
- Agent runs take ~250 s; a cold document cache makes the first live scan slow.
- TinyFish returns no credit usage in the API; check the dashboard.
- Residents are not live yet (could_not_verify). Rent comparables aren't adjusted for
  size or furnishing; Housing.com blocks Fetch (HTTP 406).
- The listing reader takes locality/rent/BHK from the NoBroker URL and title (and the
  MagicBricks URL); other portals need manual entry.
- Saved demo scans for the three demo listings are committed in `backend/cache/`
  (HSR Sector 7, HSR Sector 2, Sobha Daffodil) so **Replay cached scan** works offline.
- Running scans are kept in memory; restarting the backend loses them.
- Ask needs a scan that is still in the backend's memory (run or replay it first).

## Secrets

Never commit `.env` or API keys. `.env.example` lists variable names only.
