#!/usr/bin/env python3
"""
Fetch the OSM features that mask the scoring, per site, from the Overpass API: ways (their black
lines on the reference are not cliffs), buildings and water (deactivated in the study).

Writes work/osm/<site>.json: {"ways": [...], "areas": [...]} as EPSG:25832 GeoJSON geometries.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
import yaml
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work/osm"
ENDPOINTS = ["https://overpass-api.de/api/interpreter"]
UA = {"User-Agent": "mapant-bayern parameter study (mail@gregor-sturm.de)"}


def site_bounds(site: dict) -> tuple[int, int, int, int]:
    xs = [int(t.split("_")[0]) for t in site["core"]]
    ys = [int(t.split("_")[1]) for t in site["core"]]
    return min(xs) * 1000 - 200, min(ys) * 1000 - 200, (max(xs) + 1) * 1000 + 200, (max(ys) + 1) * 1000 + 200


def query(bbox_ll: tuple[float, float, float, float]) -> dict:
    w, s, e, n = bbox_ll
    q = f"""[out:json][timeout:120];
(
  way["highway"]({s},{w},{n},{e});
  way["railway"]({s},{w},{n},{e});
  way["power"="line"]({s},{w},{n},{e});
  way["barrier"]({s},{w},{n},{e});
  way["waterway"]({s},{w},{n},{e});
  way["building"]({s},{w},{n},{e});
  way["natural"="water"]({s},{w},{n},{e});
  way["landuse"~"residential|industrial|commercial|farmyard|quarry|farmland|meadow|grass"]({s},{w},{n},{e});
);
out geom;"""
    for attempt in range(6):
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            r = requests.post(url, data={"data": q}, timeout=180, headers=UA)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            print(f"  overpass retry ({e})", flush=True)
            time.sleep(30 * (attempt + 1))
    raise RuntimeError("overpass failed")


def main() -> int:
    sites = yaml.safe_load((ROOT / "sites.yaml").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    to_ll = Transformer.from_crs(25832, 4326, always_xy=True)
    to_m = Transformer.from_crs(4326, 25832, always_xy=True)
    for name, site in sites.items():
        p = OUT / f"{name}.json"
        if p.exists():
            continue
        x0, y0, x1, y1 = site_bounds(site)
        w, s = to_ll.transform(x0, y0)
        e, n = to_ll.transform(x1, y1)
        data = query((w, s, e, n))
        ways, areas = [], []
        for el in data["elements"]:
            if "geometry" not in el:
                continue
            coords = [list(to_m.transform(pt["lon"], pt["lat"])) for pt in el["geometry"]]
            tags = el.get("tags", {})
            closed = len(coords) > 3 and coords[0] == coords[-1]
            if closed and ("building" in tags or tags.get("natural") == "water" or "landuse" in tags):
                areas.append({"type": "Polygon", "coordinates": [coords], "tags": tags})
            else:
                ways.append({"type": "LineString", "coordinates": coords, "tags": tags})
        p.write_text(json.dumps({"ways": ways, "areas": areas}))
        print(f"{name}: {len(ways)} ways, {len(areas)} areas", flush=True)
        time.sleep(20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
