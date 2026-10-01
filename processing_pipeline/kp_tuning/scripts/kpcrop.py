"""
karttapullautin's batch-mode crop (src/geojson.rs: clip_seg, clip_line, clip_ring, clip_polygon),
ported line by line, plus the WGS84 reprojection it applies with `geojson_wgs84=1`.

Stage runs (vegeonly etc. on a cached point cloud) write uncropped GeoJSON in the index CRS; the
production batch writes each layer cropped to the tile and in WGS84. Cropper turns the first into
the second. Do not use GEOS/shapely clipping for this: kp's simplification leaves many polygons
invalid (self-touching rings), GEOS clipping is undefined for those and turned some into
tile-sized fills in a first attempt. On a test tile this port matches a production run feature for
feature (coordinates within 1e-7 deg).
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402


# karttapullautin's own crop (src/geojson.rs: clip_seg, clip_line, clip_ring, clip_polygon), ported
# line by line so the result is what its batch mode writes, including for polygons its
# simplification has made invalid (GEOS clipping is undefined for those).


def _clip_seg(a, b, minx, miny, maxx, maxy):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p_, q in ((-dx, a[0] - minx), (dx, maxx - a[0]), (-dy, a[1] - miny), (dy, maxy - a[1])):
        if p_ == 0.0:
            if q < 0.0:
                return None
        else:
            r = q / p_
            if p_ < 0.0:
                if r > t1:
                    return None
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return None
                if r < t1:
                    t1 = r
    return (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)


def _clip_line(pts, minx, miny, maxx, maxy):
    out, cur = [], []
    for a, b in zip(pts, pts[1:]):
        seg = _clip_seg(a, b, minx, miny, maxx, maxy)
        if seg:
            a2, b2 = seg
            contiguous = bool(cur) and abs(cur[-1][0] - a2[0]) < 1e-9 and abs(cur[-1][1] - a2[1]) < 1e-9
            if not contiguous:
                if len(cur) > 1:
                    out.append(cur)
                cur = [a2]
            cur.append(b2)
        else:
            if len(cur) > 1:
                out.append(cur)
            cur = []
    if len(cur) > 1:
        out.append(cur)
    return out


def _clip_ring(ring, minx, miny, maxx, maxy):
    pts = [tuple(p[:2]) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    for edge in range(4):
        if edge == 0:
            inside = lambda p: p[0] >= minx
            cut = lambda a, b: (minx, a[1] + (minx - a[0]) / (b[0] - a[0]) * (b[1] - a[1]))
        elif edge == 1:
            inside = lambda p: p[0] <= maxx
            cut = lambda a, b: (maxx, a[1] + (maxx - a[0]) / (b[0] - a[0]) * (b[1] - a[1]))
        elif edge == 2:
            inside = lambda p: p[1] >= miny
            cut = lambda a, b: (a[0] + (miny - a[1]) / (b[1] - a[1]) * (b[0] - a[0]), miny)
        else:
            inside = lambda p: p[1] <= maxy
            cut = lambda a, b: (a[0] + (maxy - a[1]) / (b[1] - a[1]) * (b[0] - a[0]), maxy)
        inp, pts = pts, []
        if not inp:
            return []
        n = len(inp)
        for i in range(n):
            cur, prev = inp[i], inp[i - 1]
            ic, ip = inside(cur), inside(prev)
            if ip and ic:
                pts.append(cur)
            elif ic:
                pts.append(cut(prev, cur))
                pts.append(cur)
            elif ip:
                pts.append(cut(prev, cur))
    if len(pts) < 3:
        return []
    pts.append(pts[0])
    return pts


def _clip_polygon(rings, minx, miny, maxx, maxy):
    out = []
    for i, ring in enumerate(rings):
        c = _clip_ring(ring, minx, miny, maxx, maxy)
        if not c:
            if i == 0:
                return None
            continue
        out.append(c)
    return out


def _r2(v):
    return round(v, 2)


def crop_geometry(g: dict, box) -> dict | None:
    """kp's crop_geojson for one geometry (coordinates rounded to cm as coords_line does)."""
    t, c = g["type"], g["coordinates"]
    r = lambda pts: [[_r2(x), _r2(y)] for x, y in pts]
    if t == "LineString":
        parts = _clip_line([tuple(p[:2]) for p in c], *box)
        if not parts:
            return None
        return {"type": "LineString", "coordinates": r(parts[0])} if len(parts) == 1 else \
            {"type": "MultiLineString", "coordinates": [r(p) for p in parts]}
    if t == "MultiLineString":
        parts = [q for line in c for q in _clip_line([tuple(p[:2]) for p in line], *box)]
        return {"type": "MultiLineString", "coordinates": [r(p) for p in parts]} if parts else None
    if t == "Polygon":
        rings = _clip_polygon(c, *box)
        return {"type": "Polygon", "coordinates": [r(x) for x in rings]} if rings is not None else None
    if t == "MultiPolygon":
        polys = [p for p in (_clip_polygon(rr, *box) for rr in c) if p is not None]
        return {"type": "MultiPolygon", "coordinates": [[r(x) for x in p] for p in polys]} if polys else None
    if t == "Point":
        x, y = c[:2]
        return g if box[0] <= x <= box[2] and box[1] <= y <= box[3] else None
    return None


class Cropper:
    """Crop to the tile and reproject to WGS84 (7 decimals), as kp's batch mode does."""

    def __init__(self):
        from pyproj import Transformer
        self.tf = Transformer.from_crs(common.epsg(), 4326, always_xy=True)

    def _wgs(self, node):
        if node and isinstance(node[0], (int, float)):
            lon, lat = self.tf.transform(node[0], node[1])
            return [round(lon, 7), round(lat, 7)]
        return [self._wgs(n) for n in node]

    def __call__(self, src: Path, dst: Path, tile: str) -> int:
        box = common.tiles().bounds(tile)
        feats = json.loads(src.read_text()).get("features", []) if src.exists() else []
        out = []
        for f in feats:
            g = crop_geometry(f["geometry"], box)
            if g is None:
                continue
            out.append({"type": "Feature", "properties": f.get("properties", {}),
                        "geometry": {"type": g["type"], "coordinates": self._wgs(g["coordinates"])}})
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        with gzip.open(tmp, "wt") as fh:
            json.dump({"type": "FeatureCollection", "features": out}, fh, separators=(",", ":"))
        tmp.rename(dst)
        return len(out)
