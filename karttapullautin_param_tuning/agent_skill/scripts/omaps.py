#!/usr/bin/env python3
"""
Reference maps from omaps.me: list the region's georeferenced orienteering maps and rank them as
candidates.

    omaps.py scrape     --config region.yaml      # -> <results>/omaps_maps.json (cached HTML in <work>/omaps/html)
    omaps.py candidates --config region.yaml      # -> <results>/omaps_candidates.csv
    omaps.py preview    --config region.yaml ID [ID ...]   # -> <work>/omaps/preview/<id>.jpg (z13 mosaic)

`scrape` asks the outline endpoint (`/maps/outline_polygons.json?bbox=`) for every georeferenced map
in a grid of boxes over the region (config `omaps.bbox` [w, s, e, n], default: the index's extent),
then reads each map's page for scale, type, event and date. `candidates` keeps maps that overlap
the index, are not sprint/urban scale (scale denominator >= 7500 unless `omaps.min_scale` says
otherwise), and adds per map: covered tiles, best tile cover, the tile group(s) under it, the
header creation year of those tiles and the date difference. Look at the previews before choosing:
photos of printed maps, faded scans, heavy course overprint and other mapping styles (ski-O maps
draw no vegetation) make bad references.

The page date is the event/upload date, an upper bound of the survey date. omaps.worldofo.com was
behind a Cloudflare challenge in 2026 and was not used; do not try to bypass it.
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

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

BASE = "https://omaps.me"
TAG = re.compile(r"<[^>]+>")


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = common.user_agent()
    return s


def get(s: requests.Session, url: str, delay: float) -> str:
    cache = common.work() / "omaps/html"
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if p.exists():
        return p.read_text()
    time.sleep(delay)
    r = s.get(url, timeout=60)
    r.raise_for_status()
    p.write_text(r.text)
    return r.text


def details(s, row: dict, delay: float) -> dict:
    h = get(s, BASE + row["url"], delay)
    side = html.unescape(TAG.sub("\n", h))
    lines = [ln.strip() for ln in side.splitlines() if ln.strip()]
    out = {}
    for key in ("Scale", "Event", "Type of competition", "Organiser", "Equidistance", "Map maker",
                "Map type", "Discipline", "Notes", "Location"):
        if key in lines:
            i = lines.index(key)
            out[key.lower().replace(" ", "_")] = lines[i + 1] if i + 1 < len(lines) else None
    return out


def region_bbox() -> tuple[float, float, float, float]:
    b = common.cfg().get("omaps", {}).get("bbox")
    if b:
        return tuple(b)
    d = common.tiles().df
    return float(d.min_lon.min()), float(d.min_lat.min()), float(d.max_lon.max()), float(d.max_lat.max())


def scrape(delay: float, step: float = 0.5) -> None:
    s = session()
    seen: dict[int, dict] = {}
    w0, s0, e0, n0 = region_bbox()
    lon = w0
    while lon < e0:
        lat = s0
        while lat < n0:
            bbox = f"{lon},{lat},{min(lon + step, e0)},{min(lat + step, n0)}"
            for f in json.loads(get(s, f"{BASE}/maps/outline_polygons.json?bbox={bbox}", delay)):
                seen[f["properties"]["id"]] = f
            lat += step
        lon += step
    print(f"{len(seen)} georeferenced maps in the region's box", flush=True)
    rows = []
    for i, f in enumerate(seen.values(), 1):
        p = f["properties"]
        row = dict(id=p["id"], name=p["name"], date=p["date"], url=p["url"], tilejson=p.get("tilejson"),
                   outline=f["geometry"])
        try:
            row.update(details(s, row, delay))
        except Exception as e:  # noqa: BLE001
            row["error"] = repr(e)
        rows.append(row)
        if i % 50 == 0:
            print(f"{i}/{len(seen)}", flush=True)
    (common.results() / "omaps_maps.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


def scale_den(s) -> float:
    m = re.search(r"1\s*:\s*([\d .,]+)", str(s or ""))
    return float(re.sub(r"[ .,]", "", m.group(1))) if m else float("nan")


def candidates() -> None:
    from pyproj import Transformer
    from shapely.geometry import box, shape
    from shapely.ops import transform

    T = common.tiles()
    tr = Transformer.from_crs(4326, T.crs, always_xy=True)
    maps = json.loads((common.results() / "omaps_maps.json").read_text())
    gp = common.results() / "groups.csv"
    groups = dict(pd.read_csv(gp).values) if gp.exists() else {}
    sv_p = common.results() / "survey.parquet"
    year = dict(pd.read_parquet(sv_p, columns=["id", "creation_year"]).values) if sv_p.exists() else {}
    min_scale = common.cfg().get("omaps", {}).get("min_scale", 7500)
    rows = []
    for m in maps:
        if not m.get("tilejson") or not m.get("outline"):
            continue
        den = scale_den(m.get("scale"))
        if den == den and den < min_scale:
            continue
        g = transform(lambda x, y, z=None: tr.transform(x, y), shape(m["outline"]))
        if g.is_empty or not g.is_valid:
            g = g.buffer(0)
        ts = T.in_box(*g.bounds)
        cover = {t: g.intersection(box(*T.bounds(t))).area / (T.size ** 2) for t in ts}
        cover = {t: c for t, c in cover.items() if c > 0.05}
        if not cover:
            continue
        best = sorted(cover.items(), key=lambda kv: -kv[1])
        yrs = [year[t] for t in cover if t in year and year[t]]
        mdate = str(m.get("date") or "")[:4]
        rows.append(dict(id=m["id"], name=m["name"], date=m.get("date"), scale=m.get("scale"),
                         map_type=m.get("map_type"), discipline=m.get("discipline"), event=m.get("event"),
                         url=BASE + m["url"], area_km2=round(g.area / 1e6, 2),
                         tiles_ge60=sum(c >= 0.6 for c in cover.values()), best_cover=round(best[0][1], 2),
                         groups=",".join(sorted({str(groups.get(t, "?")) for t in cover})),
                         lidar_year=int(pd.Series(yrs).median()) if yrs else None,
                         years_off=(int(mdate) - int(pd.Series(yrs).median())) if yrs and mdate.isdigit() else None))
    df = pd.DataFrame(rows).sort_values(["tiles_ge60", "area_km2"], ascending=False)
    p = common.results() / "omaps_candidates.csv"
    df.to_csv(p, index=False)
    print(f"{len(df)} candidate maps -> {p}")
    print(df.head(30)[["id", "name", "date", "scale", "tiles_ge60", "groups", "years_off"]].to_string(index=False))


def preview(ids: list[int], zoom: int = 13) -> None:
    import io

    import mercantile
    from PIL import Image

    maps = {m["id"]: m for m in json.loads((common.results() / "omaps_maps.json").read_text())}
    s = session()
    out = common.work() / "omaps/preview"
    out.mkdir(parents=True, exist_ok=True)
    for mid in ids:
        tj = maps[mid]["tilejson"]
        z = min(zoom, tj.get("maxzoom", zoom))
        ts = list(mercantile.tiles(*tj["bounds"], z))
        xs, ys = [t.x for t in ts], [t.y for t in ts]
        size = tj.get("tileSize", 256)
        img = Image.new("RGB", ((max(xs) - min(xs) + 1) * size, (max(ys) - min(ys) + 1) * size), "white")
        for t in ts:
            r = s.get(tj["tiles"][0].format(z=t.z, x=t.x, y=t.y), timeout=60)
            if r.ok and r.content:
                img.paste(Image.open(io.BytesIO(r.content)).convert("RGB").resize((size, size)),
                          ((t.x - min(xs)) * size, (t.y - min(ys)) * size))
        img.thumbnail((1600, 1600))
        img.save(out / f"{mid}.jpg", quality=85)
        print(out / f"{mid}.jpg")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["scrape", "candidates", "preview"])
    ap.add_argument("ids", type=int, nargs="*")
    common.add_config_arg(ap)
    ap.add_argument("--delay", type=float, default=0.5)
    a = ap.parse_args()
    common.set_config(a.config)
    {"scrape": lambda: scrape(a.delay), "candidates": candidates, "preview": lambda: preview(a.ids)}[a.cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
