"""Static public datasets bundled in backend/data/ (loaded once, no TinyFish).

Both come from OpenCity (official data on a secondary host, Public Domain).
They are dated snapshots: never present them as current conditions.
"""

from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FLOOD_KML = DATA_DIR / "flooding_vulnerable_locations.kml"
FLOOD_DATASET_URL = "https://data.opencity.in/dataset/flooding-locations-in-bengaluru-urban"
FLOOD_DATASET_DATE = "27 Nov 2025"
FLOOD_DATASET_ISO = "2025-11-27"
FLOOD_DATASET_LABEL = "BBMP/KSRSAC flood-vulnerable locations (OpenCity)"

CAUVERY_CSV = DATA_DIR / "bwssb_cauvery_stage_areas.csv"
CAUVERY_DATASET_URL = "https://data.opencity.in/dataset/bwssb-stage-wise-cauvery-water-supply-areas"
CAUVERY_DATASET_DATE = "27 Nov 2025"

_KML = "{http://www.opengis.net/kml/2.2}"

# Words too generic to identify a place on their own.
GENERIC_WORDS = {
    "layout", "nagar", "nagara", "road", "main", "cross", "stage", "block", "phase", "sector",
    "bengaluru", "bangalore", "east", "west", "north", "south", "the", "and", "near", "extension",
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def place_words(s: str) -> list[str]:
    return [w for w in norm(s).split() if len(w) >= 3 and w not in GENERIC_WORDS and not w.isdigit()]


def sector_numbers(s: str) -> set[str]:
    t = norm(s)
    return set(re.findall(r"sector (\d+)", t)) | set(re.findall(r"(\d+)(?:st|nd|rd|th)? sector", t))


@lru_cache(maxsize=1)
def flood_points() -> list[dict[str, Any]]:
    points = []
    for pm in ET.parse(FLOOD_KML).getroot().iter(_KML + "Placemark"):
        data = {d.get("name"): (d.text or "").strip() for d in pm.iter(_KML + "SimpleData")}
        coords = pm.find(f".//{_KML}coordinates")
        lon, lat = (coords.text.strip().split(",")[:2] if coords is not None else (None, None))
        points.append({
            "ward": data.get("WARD_NAME", ""),
            "zone": data.get("ZONE", ""),
            "location": data.get("LocationName", ""),
            "lat": float(lat) if lat else None,
            "lon": float(lon) if lon else None,
        })
    return points


@lru_cache(maxsize=1)
def cauvery_areas() -> list[tuple[str, str]]:
    """(stage, area name) pairs."""
    raw = CAUVERY_CSV.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")  # the published file is Windows-1252
    rows = list(csv.reader(text.splitlines()))
    header, body = rows[0], rows[1:]
    out = []
    for row in body:
        for stage, cell in zip(header, row):
            if cell.strip():
                out.append((stage.strip(), cell.strip()))
    return out
