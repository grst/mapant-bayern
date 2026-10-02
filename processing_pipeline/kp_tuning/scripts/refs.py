#!/usr/bin/env python3
"""
Reference maps -> scoring layers, for vegetation (white / 406 / 408 / 410) and open land.

    refs.py fetch    --config region.yaml [site ...]   # omaps tiles -> <work>/omaps/<id>/ref.tif (index CRS, 1 m)
    refs.py osm      --config region.yaml [site ...]   # OSM ways/areas -> <work>/osm/<site>.json (masks)
    refs.py classify --config region.yaml [site ...]   # -> <work>/ref/<site>.npz + .png (look at the PNGs!)
    refs.py register --config region.yaml [site ...]   # georeferencing offset -> <work>/ref/<site>_shift.json

fetch: the map's XYZ tiles at its deepest zoom (~3-5 m/px), mosaicked and reprojected onto a 1 m
grid aligned to whole metres; pixels outside the map's outline are 0.

osm: highways/railways/barriers/power lines (their black lines are not vegetation and their
corridors are drawn over it in production), water, buildings, settlements and farmland/meadow
(fields are where maps and kp disagree for reasons that are not forest: crops, season).

classify: per-map white balance (paper -> white, darkest ink -> black), then each pixel to the
nearest ISOM ink in CIELAB. Line inks (black, brown, blue, purple) take the area class of the
nearest area pixel. Masked: outside the map, course overprint (purple), water, OSM areas, ways.
veg codes: 0 unknown, 1 white, 2 open 401, 3 rough open 403, 4/5/6 green 406/408/410.

register: the shift (within +-40 m) that best aligns the reference's open land/forest with kp's
default render, by FFT cross-correlation, each image masked by its own coverage. Rejected (kept 0)
if it runs to the edge of the window or lowers green agreement -- where fields are masked there is
little to correlate.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import kp  # noqa: E402

INKS = [  # ISOM inks as they appear on omaps.me maps (sampled from good digital maps)
    ("white", (253, 253, 251)), ("y401", (244, 180, 56)), ("y403", (252, 216, 148)),
    ("g406", (196, 228, 190)), ("g408", (141, 203, 138)), ("g410", (78, 170, 80)),
    ("black", (40, 40, 35)), ("brown", (190, 115, 50)), ("brown2", (215, 160, 100)),
    ("blue", (40, 170, 225)), ("blue2", (150, 210, 235)), ("purple", (190, 50, 140)),
    ("olive", (160, 150, 40)), ("grey", (170, 170, 170)),
]
AREA = {"white": 1, "y401": 2, "y403": 3, "g406": 4, "g408": 5, "g410": 6}
MAX_SHIFT = 40


def ref_dir() -> Path:
    p = common.work() / "ref"
    p.mkdir(parents=True, exist_ok=True)
    return p


def omaps_maps() -> dict:
    return {m["id"]: m for m in json.loads((common.results() / "omaps_maps.json").read_text())}


# --------------------------------------------------------------------------------------------
# fetch


def fetch(site: str, s: dict, res: float = 1.0) -> None:
    import mercantile
    import rasterio
    from PIL import Image
    from rasterio.crs import CRS
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds, from_origin
    from rasterio.warp import Resampling, reproject, transform_geom

    m = omaps_maps()[s["omaps_id"]]
    d = common.work() / f"omaps/{s['omaps_id']}"
    if (d / "ref.tif").exists():
        return
    tj = m["tilejson"]
    zoom = tj["maxzoom"]
    size = tj.get("tileSize", 256)
    ts = list(mercantile.tiles(*tj["bounds"], zoom))
    xs, ys = [t.x for t in ts], [t.y for t in ts]
    x0, y0 = min(xs), min(ys)
    arr = np.zeros(((max(ys) - y0 + 1) * size, (max(xs) - x0 + 1) * size, 4), np.uint8)
    sess = requests.Session()
    sess.headers["User-Agent"] = common.user_agent()
    (d / "tiles").mkdir(parents=True, exist_ok=True)
    for t in ts:
        cache = d / "tiles" / f"{t.z}_{t.x}_{t.y}.img"
        if not cache.exists():
            for attempt in range(4):
                try:
                    r = sess.get(tj["tiles"][0].format(z=t.z, x=t.x, y=t.y), timeout=60)
                    cache.write_bytes(b"" if r.status_code == 404 else r.content)
                    if r.status_code != 404:
                        r.raise_for_status()
                    break
                except requests.RequestException:
                    time.sleep(2**attempt)
        if cache.stat().st_size if cache.exists() else 0:
            img = Image.open(io.BytesIO(cache.read_bytes())).convert("RGBA").resize((size, size))
            r0, c0 = (t.y - y0) * size, (t.x - x0) * size
            arr[r0:r0 + size, c0:c0 + size] = np.asarray(img)
    ul, lr = mercantile.xy_bounds(x0, y0, zoom), mercantile.xy_bounds(max(xs), max(ys), zoom)
    src_tf = from_bounds(ul.left, lr.bottom, lr.right, ul.top, arr.shape[1], arr.shape[0])
    crs = f"EPSG:{common.epsg()}"
    outline = transform_geom("EPSG:4326", crs, m["outline"])
    ring = outline["coordinates"][0] if outline["type"] == "Polygon" else outline["coordinates"][0][0]
    gx0, gx1 = math.floor(min(p[0] for p in ring)), math.ceil(max(p[0] for p in ring))
    gy0, gy1 = math.floor(min(p[1] for p in ring)), math.ceil(max(p[1] for p in ring))
    W, H = int((gx1 - gx0) / res), int((gy1 - gy0) / res)
    dst_tf = from_origin(gx0, gy1, res, res)
    dst = np.zeros((4, H, W), np.uint8)
    for b in range(4):
        reproject(arr[:, :, b], dst[b], src_transform=src_tf, src_crs=CRS.from_epsg(3857), dst_transform=dst_tf,
                  dst_crs=CRS.from_string(crs), resampling=Resampling.bilinear)
    inside = rasterize([outline], out_shape=(H, W), transform=dst_tf, fill=0, default_value=1)
    valid = (inside == 1) & (dst[3] > 200)
    rgb = np.where(valid[None], dst[:3], 0)
    with rasterio.open(d / "ref.tif", "w", driver="GTiff", width=W, height=H, count=4, dtype="uint8", crs=crs,
                       transform=dst_tf, compress="deflate", tiled=True) as f:
        f.write(np.concatenate([rgb, (valid * 255).astype(np.uint8)[None]]))
    (d / "meta.json").write_text(json.dumps(dict(id=m["id"], name=m["name"], date=m.get("date"), zoom=zoom,
                                                 m_per_px=156543.03 / 2**zoom * 256 / size), indent=1))
    print(f"{site}: {W}x{H} m at z{zoom}", flush=True)


# --------------------------------------------------------------------------------------------
# osm


def osm(site: str, s: dict) -> None:
    from pyproj import Transformer

    p = common.work() / f"osm/{site}.json"
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    T = common.tiles()
    bs = [T.bounds(t) for t in s["core"]]
    x0, y0 = min(b[0] for b in bs) - 200, min(b[1] for b in bs) - 200
    x1, y1 = max(b[2] for b in bs) + 200, max(b[3] for b in bs) + 200
    to_ll = Transformer.from_crs(T.crs, 4326, always_xy=True)
    to_m = Transformer.from_crs(4326, T.crs, always_xy=True)
    w, so = to_ll.transform(x0, y0)
    e, n = to_ll.transform(x1, y1)
    q = f"""[out:json][timeout:120];
(way["highway"]({so},{w},{n},{e}); way["railway"]({so},{w},{n},{e}); way["power"="line"]({so},{w},{n},{e});
 way["barrier"]({so},{w},{n},{e}); way["waterway"]({so},{w},{n},{e}); way["building"]({so},{w},{n},{e});
 way["natural"="water"]({so},{w},{n},{e});
 way["landuse"~"residential|industrial|commercial|farmyard|quarry|farmland|meadow|grass"]({so},{w},{n},{e}););
out geom;"""
    eps = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
    for attempt in range(8):
        try:
            r = requests.post(eps[attempt % 2], data={"data": q}, timeout=180, headers={"User-Agent": common.user_agent()})
            r.raise_for_status()
            data = r.json()
            break
        except requests.RequestException as ex:
            print(f"  overpass retry ({ex})", flush=True)
            time.sleep(15 * (attempt + 1))
    else:
        raise RuntimeError("overpass failed")
    ways, areas = [], []
    for el in data["elements"]:
        if "geometry" not in el:
            continue
        c = [list(to_m.transform(pt["lon"], pt["lat"])) for pt in el["geometry"]]
        tags = el.get("tags", {})
        if len(c) > 3 and c[0] == c[-1] and ("building" in tags or tags.get("natural") == "water" or "landuse" in tags):
            areas.append({"type": "Polygon", "coordinates": [c], "tags": tags})
        else:
            ways.append({"type": "LineString", "coordinates": c, "tags": tags})
    p.write_text(json.dumps({"ways": ways, "areas": areas}))
    print(f"{site}: {len(ways)} ways, {len(areas)} areas", flush=True)
    time.sleep(5)


# --------------------------------------------------------------------------------------------
# classify


def classify(site: str, s: dict) -> None:
    import rasterio
    from PIL import Image
    from rasterio.features import rasterize
    from scipy import ndimage as ndi
    from shapely.geometry import shape
    from skimage import color

    with rasterio.open(common.work() / f"omaps/{s['omaps_id']}/ref.tif") as f:
        a, tf = f.read(), f.transform
    rgb, valid = a[:3], a[3] > 0
    valid = ndi.binary_erosion(valid, iterations=5)
    if s.get("keep_rows"):
        lo, hi = s["keep_rows"]
        valid[: int(lo * valid.shape[0])] = False
        valid[int(hi * valid.shape[0]):] = False
    # white balance: paper -> white, darkest ink -> black
    px = rgb[:, valid].astype(np.float32)
    bright = px.sum(0)
    paper = np.median(px[:, bright >= np.percentile(bright, 90)], axis=1)
    black = np.percentile(px, 1, axis=1)
    rgb = np.clip((rgb.astype(np.float32) - black[:, None, None]) / np.maximum(paper - black, 1)[:, None, None] * 255, 0, 255)
    lab = color.rgb2lab(np.moveaxis(rgb, 0, -1) / 255.0)
    inks = color.rgb2lab(np.array([[c for _, c in INKS]], dtype=np.float64) / 255.0)[0]
    dist = np.stack([np.linalg.norm(lab - ink, axis=-1) for ink in inks])
    idx, dmin = dist.argmin(0).astype(np.uint8), dist.min(0)
    ink = lambda *names: np.isin(idx, [i for i, (n, _) in enumerate(INKS) if n in names])  # noqa: E731
    veg = np.array([AREA.get(n, 0) for n, _ in INKS], np.uint8)[idx]
    veg[~valid | (dmin > 30)] = 0
    # yellow / light green are also the anti-aliased edges of brown and black lines: a real area
    # survives an opening; rough open land along dense contours is a string of specks
    for cls in (3, 4):
        m = veg == cls
        veg[m & ~ndi.binary_opening(m, iterations=2)] = 0
    lb, _ = ndi.label(veg == 3)
    veg[(veg == 3) & (np.bincount(lb.ravel()) < 150)[lb]] = 0
    _, (iy, ix) = ndi.distance_transform_edt(veg == 0, return_indices=True)
    veg = veg[iy, ix]
    veg[~valid] = 0
    o = json.loads((common.work() / f"osm/{site}.json").read_text())
    r = lambda gs: rasterize(gs, out_shape=veg.shape, transform=tf, fill=0, default_value=1).astype(bool) \
        if gs else np.zeros(veg.shape, bool)  # noqa: E731
    ways = r([shape(w).buffer(7) for w in o["ways"] if any(k in w["tags"] for k in ("highway", "railway", "barrier", "power"))])
    water_l = r([shape(w).buffer(4) for w in o["ways"] if "waterway" in w["tags"]])
    areas = r([shape(x).buffer(5) for x in o["areas"] if x["tags"].get("landuse") not in ("farmland", "meadow", "grass")])
    fields = r([shape(x) for x in o["areas"] if x["tags"].get("landuse") in ("farmland", "meadow", "grass")])
    purple = ndi.binary_dilation(ink("purple"), iterations=6)
    olive = ndi.binary_dilation(ndi.binary_opening(ink("olive"), iterations=3), iterations=3)
    water = ndi.binary_dilation(ndi.binary_opening(ink("blue", "blue2"), iterations=3), iterations=3)
    mask = valid & ~purple & ~olive & ~water & ~areas & ~water_l & ~fields & ~ways
    np.savez_compressed(ref_dir() / f"{site}.npz", veg=veg, mask=mask, transform=np.array(tf)[:6], shape=np.array(veg.shape))
    pal = np.array([[128, 128, 128], [255, 255, 255], [245, 180, 60], [253, 220, 150],
                    [197, 230, 190], [140, 205, 138], [60, 160, 70]], np.uint8)
    img = pal[veg]
    img[~mask & valid] = (img[~mask & valid] * 0.5 + 60).astype(np.uint8)
    Image.fromarray(img).save(ref_dir() / f"{site}.png")
    fr = np.bincount(veg[mask], minlength=7) / max(mask.sum(), 1)
    print(f"{site}: white {fr[1]:.2f} open {fr[2] + fr[3]:.2f} green {fr[4]:.2f}/{fr[5]:.2f}/{fr[6]:.2f} "
          f"(scored share of map {mask.sum() / max(valid.sum(), 1):.0%})", flush=True)


# --------------------------------------------------------------------------------------------
# register


def register(site: str, s: dict) -> None:
    from scipy.signal import fftconvolve

    import score

    p = ref_dir() / f"{site}_shift.json"
    p.unlink(missing_ok=True)
    score.load_ref.cache_clear()
    ref = score.load_ref(site, tuple(s["core"]))
    kp.prepare(site, s)
    dirs = {t: kp.run_stage(t, "vege", {}) for t in s["core"]}
    k = score.kp_layers(ref, dirs)

    def sig(v):
        out = np.zeros(v.shape, np.float32)
        out[np.isin(v, [2, 3])] = 1.0
        out[v == 1] = -0.6
        out[np.isin(v, [4, 5, 6])] = -1.0
        return out

    mask, kmask = ref.mask & (ref.veg > 0), k["veg"] > 0
    a = np.where(mask, sig(ref.veg), 0)
    b = np.where(kmask, sig(k["veg"]), 0)
    a -= a[mask].mean() * mask
    b -= b[kmask].mean() * kmask
    cc = fftconvolve(b, a[::-1, ::-1], mode="same")
    cy, cx = np.array(cc.shape) // 2
    win = cc[cy - MAX_SHIFT: cy + MAX_SHIFT + 1, cx - MAX_SHIFT: cx + MAX_SHIFT + 1]
    iy, ix = np.unravel_index(win.argmax(), win.shape)
    dx, dy = int(ix - MAX_SHIFT), int(iy - MAX_SHIFT)
    shift = (dx * ref.tf.a, dy * ref.tf.e)
    before = score.score_vege(ref, k)
    p.write_text(json.dumps({"shift": shift}))
    score.load_ref.cache_clear()
    ref2 = score.load_ref(site, tuple(s["core"]))
    after = score.score_vege(ref2, score.kp_layers(ref2, dirs))
    ok = max(abs(dx), abs(dy)) < MAX_SHIFT * 0.6 and after["green_ba"] >= before["green_ba"] - 0.005
    if not ok:
        p.write_text(json.dumps({"shift": (0.0, 0.0), "rejected": shift}))
    score.load_ref.cache_clear()
    print(f"{site}: shift E{shift[0]:+.0f} N{shift[1]:+.0f} m; green_ba {before['green_ba']:.3f} -> "
          f"{after['green_ba']:.3f}{'' if ok else ' -> rejected, kept 0'}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "osm", "classify", "register"])
    ap.add_argument("sites", nargs="*")
    common.add_config_arg(ap)
    a = ap.parse_args()
    common.set_config(a.config)
    sites = kp.sites()
    fn = {"fetch": fetch, "osm": osm, "classify": classify, "register": register}[a.cmd]
    for name in a.sites or sites:
        fn(name, sites[name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
