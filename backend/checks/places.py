"""Locality normalisation: match on the parent area, display the original name.

Listings name sub-areas ("Rajiv Gandhi Nagar, 7th Sector, HSR Layout"), while
official notices, news and portal search pages use the parent area ("HSR
Layout"). Small names such as "Rajiv Gandhi Nagar" recur across the city, so
they are never matched on their own.
"""

from __future__ import annotations

import re

from checks import datasets as ds

# Parent areas we can match on (most specific spelling first where they overlap).
PARENT_AREAS = [
    "HSR Layout", "BTM Layout", "Koramangala", "Mahadevapura", "Banashankari", "Bellandur", "Whitefield",
    "Marathahalli", "Indiranagar", "Jayanagar", "JP Nagar", "Electronic City", "Sarjapur", "Hebbal",
    "Yelahanka", "Rajajinagar", "Malleshwaram", "Basavanagudi", "Bommanahalli", "KR Puram", "Hoodi",
    "Brookefield", "Kadugodi", "Varthur", "Kundalahalli", "Domlur", "Ulsoor", "Frazer Town", "RT Nagar",
    "Hennur", "Banaswadi", "Kammanahalli", "Vijayanagar", "Kengeri", "Uttarahalli", "Begur", "Hulimavu",
    "Bannerghatta Road", "Bilekahalli", "Arekere", "Hosa Road", "Kudlu", "Haralur", "Agara",
]
# Sub-areas that sit inside a parent area but are usually written without it.
SUBAREA_PARENT = {
    "somasundarapalya": "HSR Layout",
    "somasundara palya": "HSR Layout",
    "parangi palya": "HSR Layout",
    "garden layout hsr": "HSR Layout",
    "itpl": "Whitefield",
    "kaggadasapura": "Mahadevapura",
    "doddanekkundi": "Mahadevapura",
}
SECTOR_RE = re.compile(r"\b(\d+(st|nd|rd|th)?\s+)?(sector|block|stage|phase)\b(\s+\d+)?", re.I)


def _norm_compact(s: str) -> str:
    return " ".join(ds.norm(s).split())


def parent_area(locality: str) -> str | None:
    """Parent area named anywhere in the locality, else a known sub-area's parent."""
    loc = f" {_norm_compact(locality)} "
    loc_nospace = loc.replace(" ", "")
    for name in PARENT_AREAS:
        n = _norm_compact(name)
        if f" {n} " in loc or n.replace(" ", "") in loc_nospace:
            return name
    for sub, parent in SUBAREA_PARENT.items():
        if f" {sub} " in loc:
            return parent
    return None


def match_area(locality: str) -> str:
    """Area name used for matching sources: the parent area, else the broadest named part."""
    parent = parent_area(locality)
    if parent:
        return parent
    parts = [p for p in locality.split(",") if ds.place_words(p)]
    name = parts[-1] if parts else locality
    return SECTOR_RE.sub("", name).strip() or name.strip()


def match_words(locality: str) -> list[str]:
    return ds.place_words(match_area(locality))
