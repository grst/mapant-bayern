#!/usr/bin/env python3
"""
Collect the Bavarian orienteering maps on omaps.me that can serve as a reference.

Asks the world map's outline endpoint (`/maps/outline_polygons.json?bbox=...`) for every
georeferenced map in a grid of boxes covering Bavaria, then reads each map's page for its scale,
map type and event. Only georeferenced maps are listed by that endpoint, which is all a reference
needs. Writes results/omaps_maps.json. Responses are cached under work/omaps/html.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://omaps.me"
CACHE = Path("work/omaps/html")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "mapant-bayern parameter study (mail@gregor-sturm.de)"


def get(url: str, delay: float) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if p.exists():
        return p.read_text()
    time.sleep(delay)
    r = SESSION.get(url, timeout=60)
    r.raise_for_status()
    p.write_text(r.text)
    return r.text


TAG = re.compile(r"<[^>]+>")


def attr(h: str, name: str):
    m = re.search(rf'{name}="([^"]*)"', h)
    return json.loads(html.unescape(m.group(1))) if m else None


def details(row: dict, delay: float) -> dict:
    h = get(BASE + row["url"], delay)
    out = {}
    # The sidebar lists "Label\n value" pairs; scale is the one we need, the rest is kept for context.
    side = html.unescape(TAG.sub("\n", h))
    lines = [ln.strip() for ln in side.splitlines() if ln.strip()]
    for key in ("Scale", "Event", "Type of competition", "Organiser", "Equidistance", "Map maker",
                "Map type", "Discipline", "Notes", "Location"):
        if key in lines:
            i = lines.index(key)
            out[key.lower().replace(" ", "_")] = lines[i + 1] if i + 1 < len(lines) else None
    return out


BAVARIA = (8.9, 47.2, 13.9, 50.6)


def world_features(delay: float, step: float = 0.5) -> list[dict]:
    """Every georeferenced map whose outline meets Bavaria's bounding box, one query per box."""
    seen: dict[int, dict] = {}
    w0, s0, e0, n0 = BAVARIA
    lon = w0
    while lon < e0:
        lat = s0
        while lat < n0:
            bbox = f"{lon},{lat},{min(lon + step, e0)},{min(lat + step, n0)}"
            for f in json.loads(get(f"{BASE}/maps/outline_polygons.json?bbox={bbox}", delay)):
                seen[f["properties"]["id"]] = f
            lat += step
        lon += step
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("results/omaps_maps.json"))
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    feats = world_features(args.delay)
    print(f"{len(feats)} georeferenced maps around Bavaria", flush=True)
    rows = []
    for i, f in enumerate(feats, 1):
        p = f["properties"]
        row = dict(id=p["id"], name=p["name"], date=p["date"], url=p["url"], tilejson=p["tilejson"],
                   outline=f["geometry"], bbox_polygon=p.get("bounding_box"))
        try:
            row.update(details(row, args.delay))
        except Exception as e:  # noqa: BLE001 -- recorded, one bad page does not stop the scrape
            row["error"] = repr(e)
        rows.append(row)
        if i % 50 == 0:
            print(f"{i}/{len(feats)}", flush=True)
    args.out.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
