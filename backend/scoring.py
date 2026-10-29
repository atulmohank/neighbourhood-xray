"""Scoring and verdict logic (handoff v2 rule).

Start at 100 and subtract a capped deduction per area. A check with status
``could_not_verify`` never deducts anything and is shown greyed out.

Per-area score (shown in the UI) = 100 - deduction / max_deduction * 100,
so an area with no problems scores 100 and one at its cap scores 0.
The overall score is 100 minus the sum of deductions, rounded half up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

START_SCORE = 100

# Maximum deduction per area (handoff v2).
MAX_WATER_CUTS = 25
MAX_POWER_CUTS = 20
MAX_FLOODING = 25
MAX_WATER_SOURCE = 10  # flat deduction when the listing says tanker/borewell only
MAX_RENT_ABOVE_MEDIAN = 20

MAX_DEDUCTIONS: dict[str, int] = {
    "water_cuts": MAX_WATER_CUTS,
    "power_cuts": MAX_POWER_CUTS,
    "flooding": MAX_FLOODING,
    "water_source": MAX_WATER_SOURCE,
    "rent_compare": MAX_RENT_ABOVE_MEDIAN,
}

# How findings turn into deductions (our own calibration; the handoff only fixes the caps).
WATER_CUT_POINTS_PER_NOTICE = 5  # 5 sourced water-cut notices in 30 days hit the cap
POWER_CUT_POINTS_PER_NOTICE = 3  # 7 sourced outage notices hit the cap
FLOOD_POINTS_WARD_LISTED = 10  # ward appears in the official vulnerable-locations list
FLOOD_POINTS_PER_LOCALITY_MATCH = 5  # each vulnerable point whose name matches the locality
RENT_POINTS_PER_PERCENT_ABOVE = 1  # 1 point per % above the median

AREA_LABELS: dict[str, str] = {
    "water_cuts": "Water supply",
    "power_cuts": "Power",
    "flooding": "Flood risk",
    "rent_compare": "Rent value",
    "water_source": "Water source",
}

# Statuses whose result may deduct. "stub" results are simulated demo data:
# they are scored so the demo flow works, but the report says data_mode="stub".
SCORABLE_STATUSES = {"verified", "stub"}

VERDICT_GOOD_MIN = 75
VERDICT_CHECK_MIN = 50
VERDICT_GOOD = "Looks good"
VERDICT_CHECK = "Check before signing"
VERDICT_RISK = "High risk"
NO_DATA_VERDICT = "Not enough data"

# Area colour levels for the UI (per-area score).
LEVEL_GOOD_MIN = 70
LEVEL_WATCH_MIN = 40


def capped(area_id: str, points: float) -> float:
    return max(0.0, min(float(MAX_DEDUCTIONS[area_id]), points))


def water_cuts_deduction(notice_count: int) -> float:
    return capped("water_cuts", notice_count * WATER_CUT_POINTS_PER_NOTICE)


def power_cuts_deduction(notice_count: int) -> float:
    return capped("power_cuts", notice_count * POWER_CUT_POINTS_PER_NOTICE)


def flooding_deduction(ward_listed: bool, locality_matches: int) -> float:
    if not ward_listed and not locality_matches:
        return 0.0
    return capped("flooding", FLOOD_POINTS_WARD_LISTED + locality_matches * FLOOD_POINTS_PER_LOCALITY_MATCH)


def water_source_deduction(tanker_or_borewell_only: bool) -> float:
    return float(MAX_WATER_SOURCE) if tanker_or_borewell_only else 0.0


def rent_deduction(percent_above_median: float) -> float:
    return capped("rent_compare", percent_above_median * RENT_POINTS_PER_PERCENT_ABOVE)


def area_score(area_id: str, deduction: float) -> int:
    return int(START_SCORE - deduction / MAX_DEDUCTIONS[area_id] * 100 + 0.5)


def area_deduction(area: dict[str, Any]) -> float:
    """Deduction implied by an area's displayed score; 0 for could_not_verify."""
    if area.get("status") not in SCORABLE_STATUSES or area.get("score") is None:
        return 0.0
    max_d = MAX_DEDUCTIONS.get(area["id"], 0)
    return (START_SCORE - area["score"]) / 100 * max_d


def level_for(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= LEVEL_GOOD_MIN:
        return "good"
    if score >= LEVEL_WATCH_MIN:
        return "watch"
    return "risk"


def overall_score(area_scores: list[dict[str, Any]]) -> int | None:
    """None when no area could be checked: 100 would wrongly read as "Looks good"."""
    if not any(a.get("status") in SCORABLE_STATUSES and a.get("score") is not None for a in area_scores):
        return None
    total = sum(area_deduction(a) for a in area_scores)
    # Round half up (Python's round() uses banker's rounding).
    return max(0, int(START_SCORE - total + 0.5))


def verdict_for(score: int | None) -> str:
    if score is None:
        return NO_DATA_VERDICT
    if score >= VERDICT_GOOD_MIN:
        return VERDICT_GOOD
    if score >= VERDICT_CHECK_MIN:
        return VERDICT_CHECK
    return VERDICT_RISK


def score_report(area_scores: list[dict[str, Any]]) -> tuple[int | None, str]:
    score = overall_score(area_scores)
    return score, verdict_for(score)


EXAMPLE_REPORT_PATH = Path(__file__).resolve().parent.parent / "shared" / "report.example.json"


def sample_report() -> dict[str, Any]:
    """The shared example report, re-scored with these rules (expected: 58, Check before signing)."""
    report = json.loads(EXAMPLE_REPORT_PATH.read_text(encoding="utf-8"))
    report["score"], report["verdict"] = score_report(report["area_scores"])
    return report


if __name__ == "__main__":
    r = sample_report()
    print(r["score"], r["verdict"])
