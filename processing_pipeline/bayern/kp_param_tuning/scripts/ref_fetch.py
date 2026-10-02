#!/usr/bin/env python3
"""
Download an omaps.me map's XYZ tiles at its deepest zoom and mosaic them into a GeoTIFF on the
EPSG:25832 grid the LiDAR tiles use (1 m pixels, aligned to whole metres).

    ref_fetch.py <omaps id> [<omaps id> ...]

Writes work/omaps/<id>/ref.tif (RGB, 0 = outside the map) and work/omaps/<id>/meta.json.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from pathlib import Path

import mercantile
import numpy as np
import rasterio
import requests
from PIL import Image
from rasterio.crs import CRS
from rasterio.features import rasterize
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import Resampling, reproject, transform_geom

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "results/omaps_maps.json"
OUT = ROOT / "work/omaps"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "mapant-bayern parameter study (mail@gregor-sturm.de)"


def fetch_tile(url: str, cache: Path) -> Image.Image | None:
    if cache.exists():
        return Image.open(cache).convert("RGBA") if cache.stat().st_size else None
    for attempt in range(4):
        try:
            r = SESSION.get(url, timeout=60)
            if r.status_code == 404:
                cache.write_bytes(b"")
                return None
            r.raise_for_status()
            cache.write_bytes(r.content)
            return Image.open(io.BytesIO(r.content)).convert("RGBA")
        except requests.RequestException:
            time.sleep(2**attempt)
    raise RuntimeError(f"could not fetch {url}")


def mosaic(m: dict, zoom: int, tile_dir: Path) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """The map's tiles at `zoom`, as one RGBA array and its web-mercator bounds."""
    tj = m["tilejson"]
    w, s, e, n = tj["bounds"]
    size = tj.get("tileSize", 256)
    tiles = list(mercantile.tiles(w, s, e, n, zoom))
    xs = [t.x for t in tiles]
    ys = [t.y for t in tiles]
    x0, y0 = min(xs), min(ys)
    arr = np.zeros(((max(ys) - y0 + 1) * size, (max(xs) - x0 + 1) * size, 4), np.uint8)
    tile_dir.mkdir(parents=True, exist_ok=True)
    for t in tiles:
        url = tj["tiles"][0].format(z=t.z, x=t.x, y=t.y)
        img = fetch_tile(url, tile_dir / f"{t.z}_{t.x}_{t.y}.webp")
        if img is None:
            continue
        if img.size != (size, size):
            img = img.resize((size, size))
        r, c = (t.y - y0) * size, (t.x - x0) * size
        arr[r : r + size, c : c + size] = np.asarray(img)
    ul = mercantile.xy_bounds(x0, y0, zoom)
    lr = mercantile.xy_bounds(max(xs), max(ys), zoom)
    return arr, (ul.left, lr.bottom, lr.right, ul.top)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", type=int, nargs="+")
    ap.add_argument("--res", type=float, default=1.0)
    args = ap.parse_args()
    maps = {m["id"]: m for m in json.loads(MAPS.read_text())}

    for mid in args.ids:
        m = maps[mid]
        zoom = m["tilejson"]["maxzoom"]
        d = OUT / str(mid)
        arr, (l, b, r, t) = mosaic(m, zoom, d / "tiles")
        src_tf = from_bounds(l, b, r, t, arr.shape[1], arr.shape[0])

        outline = transform_geom("EPSG:4326", "EPSG:25832", m["outline"])
        xs = [p[0] for p in outline["coordinates"][0]]
        ys = [p[1] for p in outline["coordinates"][0]]
        x0, x1 = math.floor(min(xs)), math.ceil(max(xs))
        y0, y1 = math.floor(min(ys)), math.ceil(max(ys))
        W, H = int((x1 - x0) / args.res), int((y1 - y0) / args.res)
        dst_tf = from_origin(x0, y1, args.res, args.res)
        dst = np.zeros((4, H, W), np.uint8)
        for band in range(4):
            reproject(
                arr[:, :, band], dst[band], src_transform=src_tf, src_crs=CRS.from_epsg(3857),
                dst_transform=dst_tf, dst_crs=CRS.from_epsg(25832), resampling=Resampling.bilinear,
            )
        inside = rasterize([outline], out_shape=(H, W), transform=dst_tf, fill=0, default_value=1)
        valid = (inside == 1) & (dst[3] > 200)
        rgb = np.where(valid[None], dst[:3], 0)
        prof = dict(driver="GTiff", width=W, height=H, count=4, dtype="uint8", crs="EPSG:25832",
                    transform=dst_tf, compress="deflate", tiled=True)
        with rasterio.open(d / "ref.tif", "w", **prof) as f:
            f.write(np.concatenate([rgb, (valid * 255).astype(np.uint8)[None]]))
        meta = {k: m.get(k) for k in ("id", "name", "date", "scale", "url", "map_type", "event")}
        meta.update(zoom=zoom, bounds_25832=[x0, y0, x1, y1],
                    m_per_px_native=156543.03 * math.cos(math.radians((b + t) / 2 / 6378137)) / 2**zoom
                    * 256 / m["tilejson"].get("tileSize", 256))
        (d / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
        print(f"{mid} {m['name']}: {W}x{H} m, z{zoom}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
