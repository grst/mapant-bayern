#!/usr/bin/env python3
"""
Side-by-side sheets for looking at results: the reference map, its classification, and kp's
vegetation for several sets, cropped to the same window (default: every core tile of the site).

    viz.py --config c.yaml SITE [--sets kp_default,G-balanced,...] [--tile T] [--width 600]

Writes <results>/viz/<site>_<tile>.jpg. Look at these -- metrics alone miss mapping-style
differences (a map that draws almost no green, a photo with a colour cast) and registration
errors. Colours roughly follow the production style: white, yellow 401/403, three greens; the
masked part of the reference is greyed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import kp  # noqa: E402
import score  # noqa: E402
import sets as setsmod  # noqa: E402

PAL = np.array([[150, 150, 150], [255, 255, 255], [255, 186, 83], [255, 219, 166],
                [197, 232, 190], [139, 205, 132], [62, 175, 80]], np.uint8)


def sheet(site: str, tile: str, names: list[str], width: int) -> Path:
    import rasterio

    s = kp.sites()[site]
    allsets = setsmod.load_sets()
    ref = score.load_ref(site, tuple(s["core"]))
    x0, y0, x1, y1 = common.tiles().bounds(tile)
    c0, r0 = ~ref.tf * (x0, y1)
    c0, r0 = max(int(round(c0)), 0), max(int(round(r0)), 0)
    n = int(round(x1 - x0))
    win = (slice(r0, r0 + n), slice(c0, c0 + n))
    # the image and its classification share one pixel grid (the registration shift is in ref.tf)
    with rasterio.open(common.work() / f"omaps/{s['omaps_id']}/ref.tif") as f:
        orig = f.read([1, 2, 3]).transpose(1, 2, 0)
    rimg = PAL[ref.veg].copy()
    rimg[~ref.mask] = (rimg[~ref.mask] * 0.45 + 70).astype(np.uint8)
    panels = [("reference map", orig[win]), ("reference, classified", rimg[win])]
    for name in names:
        d = {t: kp.run_stage(t, "vege", allsets.get(name, {})) for t in s["core"]}
        panels.append((name, PAL[score.kp_layers(ref, d)["veg"]][win]))
    font = ImageFont.load_default(size=16)
    cols = min(len(panels), 4)
    rows = (len(panels) + cols - 1) // cols
    img = Image.new("RGB", (cols * width, rows * (width + 24)), "white")
    dr = ImageDraw.Draw(img)
    for i, (label, arr) in enumerate(panels):
        x, y = (i % cols) * width, (i // cols) * (width + 24)
        if arr.size:
            img.paste(Image.fromarray(np.ascontiguousarray(arr)).resize((width, width), Image.NEAREST), (x, y + 24))
        dr.text((x + 6, y + 3), label, fill="black", font=font)
    out = common.results() / f"viz/{site}_{tile}.jpg"
    out.parent.mkdir(exist_ok=True)
    img.save(out, quality=85)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site")
    common.add_config_arg(ap)
    ap.add_argument("--sets", default="kp_default")
    ap.add_argument("--tile", default="")
    ap.add_argument("--width", type=int, default=600)
    a = ap.parse_args()
    common.set_config(a.config)
    s = kp.sites()[a.site]
    for t in [a.tile] if a.tile else s["core"]:
        print(sheet(a.site, t, a.sets.split(","), a.width))
    return 0


if __name__ == "__main__":
    sys.exit(main())
