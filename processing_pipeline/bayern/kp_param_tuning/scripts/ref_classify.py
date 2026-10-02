#!/usr/bin/env python3
"""
Turn a reference map image (work/omaps/<id>/ref.tif, EPSG:25832, 1 m) into the layers the scoring
compares against.

    ref_classify.py <site> [<site> ...]      # sites from sites.yaml

Writes work/ref/<site>.npz with, on the reference's 1 m grid:

  veg      uint8  the area symbol under the line work: 0 outside/unknown, 1 white forest,
                  2 open land (401), 3 rough open land (403), 4 green 406, 5 green 408, 6 green 410
  ug       bool   undergrowth stripes (407/409) present
  rock     float  cliff-like black faces (>= 9 m long), OSM ways and straight lines removed
  rock_all float  all black point/line detail (boulders, stony ground, cliffs)
  mask     bool   pixels that count: inside the map, not overprint, water, settlement or OSM areas
  knolls   (n,2)  brown dot symbols (109/111-like), easting/northing
  transform, shape

and a false-colour PNG work/ref/<site>.png for eyeballing the classification.

Method: per-map white balance (paper -> white, darkest ink -> black), then each pixel to the nearest
ISOM ink in CIELAB. Line inks (black, brown, blue, purple) are not area symbols: those pixels get the
area class of the nearest area pixel, which is how a reader sees the area continue under a line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
import yaml
from rasterio.features import rasterize
from scipy import ndimage as ndi
from shapely.geometry import shape
from skimage import color, measure

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work/ref"

# ISOM inks as they appear on well-printed/digital maps on omaps.me (sampled from Fürstenhänge and
# Raffawald). Index -> (name, RGB).
INKS = [
    ("white", (253, 253, 251)),
    ("y401", (244, 180, 56)),
    ("y403", (252, 216, 148)),
    ("g406", (196, 228, 190)),
    ("g408", (141, 203, 138)),
    ("g410", (78, 170, 80)),
    ("black", (40, 40, 35)),
    ("brown", (190, 115, 50)),
    ("brown2", (215, 160, 100)),
    ("blue", (40, 170, 225)),
    ("blue2", (150, 210, 235)),
    ("purple", (190, 50, 140)),
    ("olive", (160, 150, 40)),
    ("grey", (170, 170, 170)),
]
AREA = {"white": 1, "y401": 2, "y403": 3, "g406": 4, "g408": 5, "g410": 6}
LINE = {"black", "brown", "brown2", "blue", "blue2", "purple", "grey"}


def white_balance(rgb: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Stretch each channel so the map's paper is white and its darkest ink black."""
    px = rgb[:, valid].astype(np.float32)
    bright = px.sum(0)
    paper_px = px[:, bright >= np.percentile(bright, 90)]
    paper = np.median(paper_px, axis=1)
    black = np.percentile(px, 1, axis=1)
    out = (rgb.astype(np.float32) - black[:, None, None]) / np.maximum(paper - black, 1)[:, None, None]
    return np.clip(out * 255, 0, 255)


def classify(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest ink in CIELAB, and the distance to it."""
    lab = color.rgb2lab(np.moveaxis(rgb, 0, -1) / 255.0)
    inks = color.rgb2lab(np.array([[c for _, c in INKS]], dtype=np.float64) / 255.0)[0]
    d = np.stack([np.linalg.norm(lab - ink, axis=-1) for ink in inks])
    return d.argmin(0).astype(np.uint8), d.min(0)


def ink_mask(idx: np.ndarray, *names: str) -> np.ndarray:
    ids = [i for i, (n, _) in enumerate(INKS) if n in names]
    return np.isin(idx, ids)


def undergrowth(rgb: np.ndarray, area: np.ndarray) -> np.ndarray:
    """
    ISOM 407/409 are vertical green stripes. On the 1 m grid they give greenness that oscillates
    along x with a period of 5-10 m and barely changes along y, which no solid area and no line
    work does.
    """
    r, g, b = rgb.astype(np.float32)
    green = g - (r + b) / 2
    hx = green - ndi.uniform_filter1d(green, 9, axis=1)
    hy = green - ndi.uniform_filter1d(green, 9, axis=0)
    ex = ndi.uniform_filter(hx**2, 21)
    ey = ndi.uniform_filter(hy**2, 21)
    gm = ndi.uniform_filter(green, 21)
    # stripes: strong oscillation along x, little along y, on a mostly white ground (solid green
    # next to a north-south boundary oscillates too, but its mean greenness is high)
    stripes = (ex > 10) & (ex > 2.5 * (ey + 1)) & (ex > 0.5 * (gm + 5))
    stripes &= area != 0
    stripes = ndi.binary_opening(stripes, iterations=2)
    return ndi.binary_closing(stripes, iterations=4)


def knolls(idx: np.ndarray, tf) -> np.ndarray:
    """Brown blobs of dot size and compact shape: 109 small knolls (and 111/112-like dots)."""
    # A dot is solid ink several metres across; a contour is ~1.5 m wide and blurs to a lighter
    # brown at omaps' ~3 m/px, so it rarely reaches the core ink and never the thickness.
    brown = ink_mask(idx, "brown")
    lab = measure.label(brown, connectivity=2)
    pts = []
    for p in measure.regionprops(lab):
        if not 15 <= p.area <= 160:
            continue
        if p.eccentricity > 0.8 or p.solidity < 0.8:
            continue
        if p.axis_major_length > 16 or p.axis_minor_length < 3.5:
            continue
        y, x = p.centroid
        pts.append(tf * (x + 0.5, y + 0.5))
    return np.array(pts, dtype=np.float64).reshape(-1, 2)


def line_footprint(length: int, angle_deg: float) -> np.ndarray:
    t = np.radians(angle_deg)
    n = length // 2
    fp = np.zeros((2 * n + 1, 2 * n + 1), bool)
    for k in np.linspace(-n, n, 4 * n + 1):
        fp[int(round(n - k * np.sin(t))), int(round(n + k * np.cos(t)))] = True
    return fp


def straight_lines(black: np.ndarray) -> np.ndarray:
    """
    Pixels on long straight black features, dashed or not: rides, fences, unmapped paths. Close
    the dash gaps along each direction, keep what survives an opening 60 m long in that direction.
    """
    out = np.zeros_like(black)
    for ang in range(0, 180, 12):
        closed = ndi.binary_closing(black, structure=line_footprint(15, ang))
        out |= ndi.binary_opening(closed, structure=line_footprint(61, ang))
    return ndi.binary_dilation(out, iterations=2) & black


def rock(idx: np.ndarray, ways_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Black ink that is not a mapped way and not a long straight line, split in two:

    * all of it -- boulders, boulder fields, stony ground and cliffs (`rock_all`)
    * the cliff-like part: faces at least 9 m long (`cliff`). A boulder dot is 4-6 m across, a
      cliff face at 1:10 000 is a line of 1 mm (10 m) or more with ticks.

    karttapullautin draws no boulders, so its cliffs are scored against the second.
    """
    black = ink_mask(idx, "black") & ~ways_mask
    black &= ~straight_lines(black)
    lab = measure.label(black, connectivity=2)
    keep = np.zeros(lab.max() + 1, bool)
    cliff = np.zeros(lab.max() + 1, bool)
    for p in measure.regionprops(lab):
        # Fences, rides and unmapped paths are long thin lines, and their dashes thin and straight;
        # rock symbols are dots, ticks and short faces.
        dash = p.axis_major_length > 8 and p.axis_minor_length < 2.6 and p.eccentricity > 0.97
        keep[p.label] = p.axis_major_length <= 45 and not dash
        cliff[p.label] = keep[p.label] and p.axis_major_length >= 9
    return keep[lab].astype(np.float32), cliff[lab]


def osm_masks(site: str, shape_hw, tf) -> tuple[np.ndarray, np.ndarray]:
    osm = json.loads((ROOT / f"work/osm/{site}.json").read_text())
    ways = [shape(w).buffer(7) for w in osm["ways"]
            if "highway" in w["tags"] or "railway" in w["tags"] or "barrier" in w["tags"]
            or "power" in w["tags"]]
    water_lines = [shape(w).buffer(4) for w in osm["ways"] if "waterway" in w["tags"]]
    areas = [shape(a).buffer(5) for a in osm["areas"]
             if not a["tags"].get("landuse") in ("farmland", "meadow", "grass")]
    fields = [shape(a) for a in osm["areas"] if a["tags"].get("landuse") in ("farmland", "meadow", "grass")]
    r = lambda gs: rasterize(gs, out_shape=shape_hw, transform=tf, fill=0, default_value=1).astype(bool) \
        if gs else np.zeros(shape_hw, bool)
    return r(ways), r(areas) | r(water_lines) | r(fields)


# Photos of a full sheet: the band of the image (as fractions of its rows) that is map; legend,
# title and text blocks outside it are paper white and would read as white forest.
KEEP_ROWS = {"tyrolsberg": (0.30, 0.72)}


def run(site: str, meta: dict) -> None:
    src = ROOT / f"work/omaps/{meta['omaps_id']}/ref.tif"
    with rasterio.open(src) as f:
        a = f.read()
        tf = f.transform
    rgb, valid = a[:3], a[3] > 0
    valid = ndi.binary_erosion(valid, iterations=5)
    if site in KEEP_ROWS:
        lo, hi = KEEP_ROWS[site]
        valid[: int(lo * valid.shape[0])] = False
        valid[int(hi * valid.shape[0]):] = False
    rgb = white_balance(rgb, valid)
    idx, dist = classify(rgb)

    names = np.array([n for n, _ in INKS])
    area_of_ink = np.array([AREA.get(n, 0) for n, _ in INKS], np.uint8)
    veg = area_of_ink[idx]
    veg[~valid | (dist > 30)] = 0
    # Yellow and light green are also what the anti-aliased edges of brown and black lines look
    # like. A real area is several metres across, so only what survives an opening counts.
    for cls in (3, 4):
        m = veg == cls
        veg[m & ~ndi.binary_opening(m, iterations=2)] = 0
    # rough open land along dense contours: what survives the opening is still a string of specks
    lab, _ = ndi.label(veg == 3)
    veg[(veg == 3) & (np.bincount(lab.ravel()) < 150)[lab]] = 0
    # area under line work: nearest area pixel
    unknown = veg == 0
    _, (iy, ix) = ndi.distance_transform_edt(unknown, return_indices=True)
    veg = veg[iy, ix]
    veg[~valid] = 0

    ways_mask, osm_area_mask = osm_masks(site, veg.shape, tf)
    purple = ndi.binary_dilation(ink_mask(idx, "purple"), iterations=6)
    olive = ndi.binary_opening(ink_mask(idx, "olive"), iterations=3)
    olive = ndi.binary_dilation(olive, iterations=3)
    water = ndi.binary_opening(ink_mask(idx, "blue", "blue2"), iterations=3)
    water = ndi.binary_dilation(water, iterations=3)
    mask = valid & ~purple & ~olive & ~water & ~osm_area_mask

    # stripes next to masked line work (north lines, streams) are mostly those lines
    near_mask = ndi.binary_dilation(~mask & valid, iterations=10)
    # Mapped ways are drawn over the vegetation in production (and karttapullautin sees their
    # open corridor as yellow), so their corridors do not count either.
    mask &= ~ways_mask
    ug = undergrowth(rgb, veg) & mask & ~near_mask
    ug = ndi.binary_closing(ug, iterations=6)
    lab, n = ndi.label(ug)
    ug &= (np.bincount(lab.ravel()) >= 400)[lab]
    ug &= mask
    # cultivated land (412) is yellow with black dots: neither rock nor knolls
    fields = ndi.binary_dilation(veg == 2, iterations=4)
    rk_all, cl = rock(idx, ways_mask)
    rk_all *= mask & ~fields
    rk = (cl & mask & ~fields).astype(np.float32)
    kn = knolls(idx, tf)
    if len(kn):
        c, r_ = (~tf * (kn[:, 0], kn[:, 1]))
        r_, c = r_.astype(int).clip(0, veg.shape[0] - 1), c.astype(int).clip(0, veg.shape[1] - 1)
        kn = kn[mask[r_, c] & ~fields[r_, c]]

    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT / f"{site}.npz", veg=veg, ug=ug, rock=rk.astype(np.float16), rock_all=rk_all.astype(np.float16), mask=mask, knolls=kn,
        transform=np.array(tf)[:6], shape=np.array(veg.shape),
    )
    # eyeball image: area classes, stripes hatched dark green, rock black, knolls brown, mask grey
    pal = np.array([[128, 128, 128], [255, 255, 255], [245, 180, 60], [253, 220, 150],
                    [197, 230, 190], [140, 205, 138], [60, 160, 70]], np.uint8)
    img = pal[veg]
    img[ug & ((np.arange(veg.shape[1]) // 3) % 2 == 0)[None, :]] = (20, 110, 30)
    img[rk > 0] = (0, 0, 0)
    img[~mask & valid] = (img[~mask & valid] * 0.5 + 60).astype(np.uint8)
    for x, y in kn:
        c, r_ = ~tf * (x, y)
        img[max(int(r_) - 2, 0) : int(r_) + 3, max(int(c) - 2, 0) : int(c) + 3] = (160, 70, 20)
    from PIL import Image

    Image.fromarray(img).save(OUT / f"{site}.png")
    frac = np.bincount(veg[mask], minlength=7) / max(mask.sum(), 1)
    print(f"{site}: white {frac[1]:.2f} open {frac[2] + frac[3]:.2f} green {frac[4]:.2f}/{frac[5]:.2f}/{frac[6]:.2f}"
          f" ug {ug[mask].mean():.3f} rock {rk_all[mask].mean():.4f} cliff {rk[mask].mean():.4f} knolls {len(kn)}", flush=True)


def main() -> int:
    sites = yaml.safe_load((ROOT / "sites.yaml").read_text())
    for s in sys.argv[1:] or sites:
        run(s, sites[s])
    return 0


if __name__ == "__main__":
    sys.exit(main())
