r"""Run the live power_cuts and water_cuts checks for a few localities and print results.

Official pages are fetched by one TinyFish agent run each (cached 6 h in backend/cache/),
news via TinyFish Search + Fetch. Usage (from backend/): .venv\Scripts\python scripts\live_checks_probe.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
os.environ["XRAY_MODE"] = "live"

from checks import power_cuts, water_cuts  # noqa: E402

LOCALITIES = sys.argv[1:] or ["HSR Layout, Bengaluru", "Mahadevapura, Bengaluru", "Banashankari, Bengaluru"]


async def main() -> None:
    t0 = time.monotonic()
    jobs = [(loc, mod) for loc in LOCALITIES for mod in (power_cuts, water_cuts)]
    results = await asyncio.gather(*(m.run({"locality": loc}) for loc, m in jobs), return_exceptions=True)
    for (loc, mod), r in zip(jobs, results):
        print(f"\n=== {loc} / {mod.CHECK_ID}")
        if isinstance(r, BaseException):
            print("EXCEPTION:", repr(r)[:300])
            continue
        print(r["status"], "| score", r["score"], "|", r["headline"])
        for d in r["details"]:
            print("  -", d)
    print(f"\nelapsed {time.monotonic() - t0:.0f}s")


asyncio.run(main())
