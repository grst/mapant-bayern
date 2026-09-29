"""
Side-by-side panels for eyeballing: the original reference map, its classification, and
karttapullautin renderings of one or more parameter sets, all cropped to the same window.

kp output is drawn roughly as the production style does: white paper, yellow 403, the three
greens, undergrowth as vertical stripes, cliffs black, knolls as brown dots.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont

import kp as kpmod
import score

ROOT = Path(__file__).resolve().parents[1]

PAL = np.array([
    [150, 150, 150],  # 0 outside
    [255, 255, 255],  # 1 white
    [255, 186, 83],   # 2 open 401
    [255, 219, 166],  # 3 rough open 403
    [197, 232, 190],  # 4 green 406
    [139, 205, 132],  # 5 green 408
    [62, 175, 80],    # 6 green 410
], np.uint8)


def render_kp(layers: dict, shape) -> np.ndarray:
    img = PAL[layers.get("veg", np.ones(shape, np.uint8))].copy()
    if "ug" in layers:
        stripe = (np.arange(shape[1]) % 6 < 2)[None, :]
        img[layers["ug"] & stripe] = (62, 175, 80)
    if "cliffs" in layers:
        img[layers["cliffs"] > 0] = (0, 0, 0)
    return img


def dots(img: np.ndarray, pts: np.ndarray, tf, color=(166, 85, 43), r=3, win=None) -> None:
    inv = ~tf
    for x, y in pts:
        c, rr = inv * (x, y)
        c, rr = int(c), int(rr)
        if win is not None:
            rr -= win[0].start
            c -= win[1].start
        if 0 <= rr < img.shape[0] and 0 <= c < img.shape[1]:
            img[max(rr - r, 0) : rr + r + 1, max(c - r, 0) : c + r + 1] = color


def panels(site: str, param_sets: dict[str, dict], window: tuple[int, int, int] | None = None,
           stages=("vege", "cliffs", "contours"), out: Path | None = None, width: int = 700) -> Path:
    """
    window = (easting, northing, size_m) of the crop's lower-left corner, or None for the site's
    first core tile.
    """
    s = kpmod.sites()[site]
    ref = score.load_ref(site, tuple(s["core"]))
    if window is None:
        t = s["core"][0]
        window = (int(t.split("_")[0]) * 1000, int(t.split("_")[1]) * 1000, 1000)
    e, n, size = window
    inv = ~ref.tf
    c0, r0 = inv * (e, n + size)
    c0, r0 = int(round(c0)), int(round(r0))
    win = (slice(max(r0, 0), max(r0, 0) + size), slice(max(c0, 0), max(c0, 0) + size))

    with rasterio.open(ROOT / f"work/omaps/{s['omaps_id']}/ref.tif") as f:
        orig = f.read([1, 2, 3]).transpose(1, 2, 0)
    # the reference raster is on the unshifted grid; the classification's transform carries the
    # registration shift, so cut the original by the shifted window too
    d = np.load(ROOT / f"work/ref/{site}.npz")
    tf0 = score.Affine(*d["transform"])
    oc, orow = ~tf0 * (e, n + size)
    ow = (slice(max(int(round(orow)), 0), max(int(round(orow)), 0) + size),
          slice(max(int(round(oc)), 0), max(int(round(oc)), 0) + size))
    tiles = [("reference map", orig[ow])]

    rimg = PAL[ref.veg].copy()
    stripe = (np.arange(ref.veg.shape[1]) % 6 < 2)[None, :]
    rimg[ref.ug & stripe] = (62, 175, 80)
    rimg[ref.rock > 0] = (0, 0, 0)
    rimg[~ref.mask] = (rimg[~ref.mask] * 0.45 + 70).astype(np.uint8)
    rimg = rimg[win].copy()
    dots(rimg, ref.knolls, ref.tf, win=win)
    tiles.append(("reference, classified", rimg))

    tiles_core = [t for t in s["core"]]
    for label, params in param_sets.items():
        dirs = {t: {st: kpmod.run_stage(t, st, params.get(st, params.get("all", {})) if isinstance(params.get(st, None), dict) else params)
                    for st in stages} for t in tiles_core}
        layers = score.kp_layers(ref, dirs)
        img = render_kp(layers, ref.veg.shape)[win].copy()
        if "knolls" in layers:
            dots(img, layers["knolls"], ref.tf, win=win)
        tiles.append((label, img))

    font = ImageFont.load_default(size=18)
    k = len(tiles)
    cols = 3 if k in (5, 6) else min(k, 4)
    rows = (k + cols - 1) // cols
    sheet = Image.new("RGB", (cols * width, rows * (width + 28)), "white")
    dr = ImageDraw.Draw(sheet)
    for i, (label, arr) in enumerate(tiles):
        im = Image.fromarray(np.ascontiguousarray(arr)).resize((width, width), Image.NEAREST)
        x, y = (i % cols) * width, (i // cols) * (width + 28)
        sheet.paste(im, (x, y + 28))
        dr.text((x + 6, y + 4), label, fill="black", font=font)
    out = out or ROOT / f"work/viz/{site}_{e}_{n}_{size}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
