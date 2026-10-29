# neighbourhood-xray

AI-powered neighbourhood intelligence using TinyFish.

Neighbourhood X-Ray is a Chrome extension that helps renters check a neighbourhood
before renting a flat. It reads the listing (locality, rent, BHK) from a NoBroker
page, runs a set of checks through a FastAPI backend, and shows a scored report in
the Chrome side panel.

> **Status: project skeleton.** The backend runs in **stub mode**: every check returns
> simulated demo data (or a simulated failure). Nothing it shows is a real finding.
> Live TinyFish checks are **not implemented** yet.

## Layout

```
shared/report.example.json   Canonical report contract (illustrative example data)
backend/
  main.py                    FastAPI app: /health, /scan, /scan/{id}/stream (SSE), /scan/{id}
  scoring.py                 Overall score + verdict (provisional rules, see file)
  summary.py                 Placeholder for LLM summary + owner questions
  tinyfish_client.py         TinyFish wrapper placeholder (live mode not implemented)
  checks/                    One module per check (stub data in stub mode)
  cache/                     Finished scan reports (JSON, git-ignored)
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
| POST | `/scan` | Body `{"locality": "...", "rent": 32000, "bhk": 2}` → `{"scan_id": ...}` |
| GET | `/scan/{id}/stream` | SSE: `started`, one `progress` per finished check, `report` (full report), `done` |
| GET | `/scan/{id}` | `{"scan_id", "status", "report"}` (report is `null` while running) |

Checks run concurrently with a 45-second timeout each (`XRAY_CHECK_TIMEOUT`). Any
error or timeout becomes `could_not_verify`; it is never turned into a finding.

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

## Current limitations (stub mode)

- All check results are simulated. Stub checks sleep 2–5 s and return fixed demo
  scores; the `water_source` check deliberately fails to show `could_not_verify`.
- Rent comparison and resident themes are not produced by the backend yet; they
  come back as `could_not_verify`. The Rent and Residents tabs show real layouts only
  for the example report.
- `summary.py` only restates check headlines; no LLM is called.
- Scoring rules in `scoring.py` are provisional (the handoff document with the agreed
  rules was not in the repo when this was written).
- TinyFish live mode raises on purpose. The request/response schema must be confirmed
  against https://docs.tinyfish.ai before it is implemented.
- NoBroker extraction uses page-title/text heuristics and may miss fields.
- Scans are kept in memory; restarting the backend loses running scans (finished ones
  are cached in `backend/cache/`).
- The Ask tab's free-form questions are not implemented.

## Secrets

Never commit `.env` or API keys. `.env.example` lists variable names only.
