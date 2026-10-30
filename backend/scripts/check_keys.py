"""Confirm backend/.env loads and the LLM key works. Prints only set/missing, never values."""

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

VARS = ["TINYFISH_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY"]
for name in VARS:
    print(f"{name}: {'set' if os.getenv(name) else 'missing'}")

if os.getenv("LLM_PROVIDER", "").lower() != "groq" or not os.getenv("LLM_API_KEY"):
    sys.exit("LLM_PROVIDER is not groq or LLM_API_KEY missing; skipping Groq call")

r = httpx.post(
    "https://api.groq.com/openai/v1/chat/completions",
    headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
    json={
        "model": os.environ["LLM_MODEL"],
        "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
        "max_completion_tokens": 200,
    },
    timeout=20,
)
print("groq http status:", r.status_code)
if r.is_success:
    body = r.json()
    print("model:", body.get("model"))
    print("reply:", (body["choices"][0]["message"].get("content") or "").strip()[:80])
    print("usage:", body.get("usage", {}).get("total_tokens"), "tokens")
else:
    print("error:", r.json().get("error", {}).get("message", "")[:200])
