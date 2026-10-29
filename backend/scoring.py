"""Scoring and verdict logic.

NOTE: the project handoff document with the agreed scoring rules was not in the
repository when this skeleton was written. The rules below are a provisional,
documented stand-in and should be replaced with the handoff's rules:

* Each area has a score from 0 to 100 (higher is better for the renter).
* Areas are weighted equally for now (AREA_WEIGHTS).
* The overall score is the weighted average of the areas that have a result,
  rounded half up.
  Areas with status ``could_not_verify`` are left out and the remaining
  weights are renormalised, so a missing check never counts as good or bad.
* Area level (colour): 70+ good, 40-69 watch, below 40 risk.
* Verdict bands: 70+ "Looks good", 50-69 "Check before signing",
  below 50 "Think twice". No verifiable areas -> "Not enough data".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AREA_WEIGHTS: dict[str, float] = {
    "water_supply": 1.0,
    "power": 1.0,
    "flood_risk": 1.0,
    "rent_value": 1.0,
    "water_source": 1.0,
}

AREA_LABELS: dict[str, str] = {
    "water_supply": "Water supply",
    "power": "Power",
    "flood_risk": "Flood risk",
    "rent_value": "Rent value",
    "water_source": "Water source",
}

# Statuses whose score may count towards the overall score. "stub" results are
# simulated demo data: they are scored so the demo flow works end to end, but
# the report is marked data_mode="stub" and the UI labels them as demo results.
SCORABLE_STATUSES = {"verified", "stub"}

VERDICT_BANDS: list[tuple[int, str]] = [
    (70, "Looks good"),
    (50, "Check before signing"),
    (0, "Think twice"),
]
NO_DATA_VERDICT = "Not enough data"


def level_for(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 70:
        return "good"
    if score >= 40:
        return "watch"
    return "risk"


def overall_score(area_scores: list[dict[str, Any]]) -> int | None:
    total_weight = 0.0
    weighted = 0.0
    for area in area_scores:
        if area.get("status") not in SCORABLE_STATUSES or area.get("score") is None:
            continue
        weight = AREA_WEIGHTS.get(area["id"], 0.0)
        total_weight += weight
        weighted += weight * area["score"]
    if total_weight == 0:
        return None
    # Round half up so 57.5 -> 58 (Python's round() would use banker's rounding).
    return int(weighted / total_weight + 0.5)


def verdict_for(score: int | None) -> str:
    if score is None:
        return NO_DATA_VERDICT
    for threshold, verdict in VERDICT_BANDS:
        if score >= threshold:
            return verdict
    return VERDICT_BANDS[-1][1]


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
