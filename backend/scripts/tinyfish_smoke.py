r"""TinyFish smoke test: one /run-sse call, raw stream saved to smoke_output.txt.

Usage (from backend/):  .venv\Scripts\python scripts\tinyfish_smoke.py [url] [goal]
Body fields per https://docs.tinyfish.ai/api-reference/automation/run-browser-automation-with-sse-streaming
The API key is read from backend/.env and never printed.
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")

ENDPOINT = "https://agent.tinyfish.ai/v1/automation/run-sse"
URL = sys.argv[1] if len(sys.argv) > 1 else "https://bescom.karnataka.gov.in/421/Contingency-Power-Outages/en"
GOAL = sys.argv[2] if len(sys.argv) > 2 else (
    "list power outage notices for the last 30 days and upcoming week: locality, date, time, notice/PDF link"
)
OUT = HERE / os.getenv("SMOKE_OUT", "smoke_output.txt")

key = os.getenv("TINYFISH_API_KEY")
if not key:
    sys.exit("TINYFISH_API_KEY missing")

PROXY = os.getenv("TINYFISH_PROXY_COUNTRY", "IN")  # gov.in sites time out from TinyFish's default (US) browsers
body = {"url": URL, "goal": GOAL, "agent_config": {"max_duration_seconds": 240}}
if PROXY:
    body["proxy_config"] = {"enabled": True, "country_code": PROXY}
t0 = time.monotonic()
final = None
with OUT.open("w", encoding="utf-8") as out, httpx.Client(timeout=httpx.Timeout(30, read=120)) as client:
    with client.stream("POST", ENDPOINT, headers={"X-API-Key": key}, json=body) as r:
        print("http status:", r.status_code)
        if r.status_code != 200:
            text = r.read().decode("utf-8", "replace")
            out.write(text)
            sys.exit(f"error body: {text[:500]}")
        for line in r.iter_lines():
            out.write(line + "\n")
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            kind = ev.get("type")
            if kind == "PROGRESS":
                print(f"[{time.monotonic() - t0:5.1f}s] PROGRESS:", str(ev.get("purpose"))[:100])
            elif kind != "HEARTBEAT":
                print(f"[{time.monotonic() - t0:5.1f}s] {kind}")
            if kind == "COMPLETE":
                final = ev

print(f"elapsed: {time.monotonic() - t0:.1f}s")
if final:
    print("COMPLETE keys:", sorted(final))
    print("status:", final.get("status"), "| error:", final.get("error"))
    print("result:", json.dumps(final.get("result"), indent=2, ensure_ascii=False)[:4000])
