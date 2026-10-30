# Neighbourhood X-Ray: execution handoff (v2)

Paste or attach this at the start of the next chat, together with `xray_ui_design.zip`. That chat's job is to **build the working product** for the finale.

## Context
- Event: Swim with TinyFish hackathon, Presidency University, Bengaluru. **Team YellowTail is shortlisted.** Finale **Fri 30 Oct 2026**, from 10 AM on campus. Build window 11:30 to 16:00, then demos and judging. The team has **full-day OD** on 30 Oct, so the morning (from 8:50) is free for setup.
- Team (all B.Tech CSE AI & ML, Presidency Univ):
  - **Atul Mohan K**: lead, backend core (FastAPI, SSE, scoring, LLM summary, cache), git owner (creates the repo, reviews and merges PRs)
  - **Muhammed Faheem K**: TinyFish agents (`backend/checks/`, `backend/tinyfish_client.py`)
  - **Muhammed Fadhil K**: Chrome extension UI and demo (`extension/`)
- The team has a TinyFish account and API key. Nobody has used git collaboration before. They use **GitHub Desktop**, not the terminal.
- It must be a **real, working product**: live TinyFish calls on real sites. The cache is a saved real scan, used only if the venue internet fails.

## Product
Open a NoBroker/MagicBricks listing, click the extension, and TinyFish agents check the area live. A side panel shows a sourced report, styled after the **Flash AI (flash.co) shopping extension**.

**Features (Flash-style)**
- A floating badge injected on the listing page ("58 · Check before signing · 31 sources") plus red flags next to the rent and the "24x7 water" claim
- Live progress: each check row ticks off as its agent finishes (SSE)
- **Overview tab:** score ring /100 + verdict; "Checked N live sources" chips; area scores with a short label each (Water 35 "Severe deficit", Power 85 "Stable", Flood 62, Rent value 48, Water source n/a "Could not verify"); What's good / Watch out with a source link under each item; "Export due-diligence PDF" button
- **Rent tab:** "Priced above the area" + Fair band / Monthly extra / 1-year overpay boxes; rent spread bar with the fair zone and a pin for this flat; median rent per portal (NoBroker, MagicBricks, Housing.com) with a "Lowest" tag; "Better-value flat nearby" card
- **Residents tab (if time):** top complaints with mention counts; quotes from Reddit and news with source and age
- **Ask tab (stretch):** chat grounded in the scan sources; "Ask the owner" checklist; suggestion chips

**Checks:** water cuts (BWSSB), power cuts (BESCOM), rent comparison (2 to 3 portals), flooding (news), water source (listing + news), residents (Reddit/news, if time). Bengaluru only.

**Honesty rule:** if a source is blocked, slow or times out (45 s), that check returns `status: "could_not_verify"`. It's shown greyed out and never counted in the score. Every finding carries a `source_url`.

**Scoring:** start at 100; subtract up to 25 for water cuts, up to 20 for power cuts, up to 25 for flooding, 10 for tanker/borewell-only water, up to 20 for rent above median. Bands: 75+ "Looks good", 50 to 74 "Check before signing", below 50 "High risk".

## Final UI design (locked)
In `xray_ui_design.zip`: `final/xray_ui_final.html` is the design to build from; `stitch_reference/` is layout reference only.
- Palette: paper `#F6F3EC`, card `#FFFDF8`, ink `#1C1A17`, ink-2 `#55504A`, mute `#8D867C`, line `#E7E1D6`, one accent amber `#C98A12`, good `#4F7A5A`, watch `#B7791F`, risk `#A8432F`
- Fonts: Inter for text, JetBrains Mono for all numbers, Fraunces only for big headline lines and quotes
- Side panel about 420 px wide, card radius 12 px, no neon or glow
- MV3 can't load remote scripts (no Tailwind CDN), so write plain CSS. Bundle fonts locally or fall back to system fonts.

## Architecture
```
Listing page (content.js) → Side panel (Chrome MV3 sidePanel)
  → POST /scan → FastAPI backend (keys in .env only)
     → 5-6 TinyFish checks in parallel (asyncio.gather, 45 s timeout each)
     → scoring.py + summary.py (LLM)
  ← GET /scan/{id}/stream (SSE): one event per check, then the full report
Cache: every full report saved to backend/cache/; ?demo=1 replays it offline
```

## Repo layout (each person edits only their own folder)
```
neighbourhood-xray/
  shared/report.example.json   # THE CONTRACT (Atul writes, then freezes)
  backend/  main.py scoring.py summary.py (Atul) · tinyfish_client.py checks/ (Faheem) · cache/ requirements.txt .env.example
  extension/  manifest.json content.js sidepanel.html sidepanel.js styles.css (Fadhil)
  design/  (the UI zip contents)
  .gitignore (must include .env)  README.md
```

**The contract must include:** locality, rent, bhk, score, verdict, summary, sources_count + sources breakdown, area_scores[] (id, label, score, tag, status), checks[] (id, status ok|could_not_verify, headline, details[], source_url, fetched_at), good[], watch_out[] (text + source_url), rent_compare (fair_low, fair_high, median, portals[] {name, median, count}, cheapest {desc, rent, url}), residents (themes[] {name, count}, quotes[] {text, source, age, url, sentiment}), questions_for_owner[].

## Git workflow (GitHub Desktop)
1. Everyone installs GitHub Desktop, VS Code, Python 3.11 and Chrome, and sends Atul their GitHub username.
2. Atul: File > New repository `neighbourhood-xray`, Git ignore Python, README, then Publish repository.
3. Atul commits the skeleton straight to `main` (the only direct commit).
4. Atul: github.com > Settings > Collaborators: add Faheem and Fadhil.
5. They accept the invite, then File > Clone repository.
6. Each task: Current branch > New branch `name/task`, commit often, Push, Create Pull Request, post the link in the group.
7. Atul merges on github.com (checks there's no `.env` and only that person's folder changed); everyone switches to main and pulls.
- Never commit `.env` or keys. Branch > Update from main to pick up merged work mid-task.

## Timeline
- **29 Oct evening:** setup (45 min) → parallel work → **Checkpoint 1**: extension shows the stub report from the local backend with rows ticking.
- **29 Oct night:** real water + power checks, scoring, summary, cache, Rent tab, badge → **Checkpoint 2**: one real HSR Layout scan end to end, cached.
- **30 Oct morning (OD):** flood/source checks, polish, laptop + hotspot setup.
- **11:30 to 14:30:** fixes, Residents if time. **14:30 code freeze:** cache all demo listings, rehearse 3 times.
- Demo script (30 s): open a real listing → click → checks light up live → report: score, "6 water cuts in 30 days (BWSSB)", rent X% above similar flats → click one source link → "Remove TinyFish and none of this exists: no API, scattered, changes weekly."

## Status at handoff (29 Oct)
- Done: idea, PPT, UI design locked, team plan shared (PDF/HTML), GitHub Desktop installed by Atul.
- Atul may already have done: created and published the empty repo, added collaborators.
- **Not started:** skeleton code, contract, TinyFish test call.

## Open items
- Verify the real TinyFish API first: endpoint, agent goal format, response shape, rate limits. **Don't assume it. Check the docs.**
- Which LLM for the summary (whatever key the team has).
- Pick 2 to 3 demo listings and localities with recent BWSSB/BESCOM entries (e.g. HSR Layout).
