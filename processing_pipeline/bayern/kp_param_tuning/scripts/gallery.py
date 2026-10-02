#!/usr/bin/env python3
"""
Comparison sheets for every scored tile of every site: the omaps.me map, its classification, kp
default, and the parameter sets of that site's point generation. One JPEG per 1 km tile in
report/img/gallery/, plus an index the report links to.

    gallery.py [--sets las14-balanced,...] [--sites a,b]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402
import viz  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report/img/gallery"

# what each generation's sheet shows, left to right after reference + classification
SHOW = {
    "1.4": ["kp_default", "las14-r1", "las14-balanced", "las14-clean"],
    "1.2": ["kp_default", "las12-r1", "las12-balanced", "las12-lessgreen"],
}
LABEL = {"kp_default": "kp default", "las14-r1": "round 1 (las14)", "las12-r1": "round 1 (las12)",
         "las14-balanced": "recommended (las14)", "las12-balanced": "recommended (las12)",
         "las14-clean": "alternative: clean", "las12-lessgreen": "alternative: less green"}


def generation(site: dict) -> str:
    d = pd.read_parquet(ROOT / "results/density.parquet", columns=["tile", "las_version"])
    v = dict(zip(d.tile.str.removesuffix(".laz"), d.las_version))
    gens = {v[t] for t in site["core"]}
    return gens.pop() if len(gens) == 1 else "1.4"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", default="")
    ap.add_argument("--width", type=int, default=520)
    args = ap.parse_args()
    sets = json.loads((ROOT / "work/sets.json").read_text())
    sites = kp.sites()
    names = args.sites.split(",") if args.sites else list(sites)
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for site in names:
        s = sites[site]
        gen = generation(s)
        show = {LABEL.get(n, n): sets[n] for n in SHOW[gen] if n in sets}
        for t in s["core"]:
            e, n = (int(v) * 1000 for v in t.split("_"))
            png = viz.panels(site, show, window=(e, n, 1000), out=ROOT / f"work/viz/gallery_{site}_{t}.png",
                             width=args.width, cols=len(show) + 2)
            jpg = OUT / f"{site}_{t}.jpg"
            Image.open(png).convert("RGB").save(jpg, "JPEG", quality=80, optimize=True)
            index.append(dict(site=site, tile=t, split=s["split"], generation=gen, file=f"img/gallery/{jpg.name}",
                              panels=["reference map", "reference, classified", *show]))
            print(jpg, flush=True)
    (OUT / "index.json").write_text(json.dumps(index, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
