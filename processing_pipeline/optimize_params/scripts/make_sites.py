#!/usr/bin/env python3
"""
Define the study sites from the reference maps: the 1 km tiles a map covers best (core) and the ring
around them (halo, for karttapullautin's 127 m batch buffer). Writes sites.yaml.

Train/holdout is split by whole map, so no holdout pixel shares a reference with a training pixel.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[1]

# omaps id -> (short name, split, max core tiles, terrain note)
SITES = {
    13217: ("fuerstenhaenge", "train", 5, "Franconian Jura: rock, cliffs, mixed forest"),
    14044: ("ochsenkopf", "train", 4, "Fichtelgebirge granite: boulders, spruce"),
    5172: ("raffawald", "train", 4, "Oberpfalz flat pine forest: undergrowth, clearings"),
    13252: ("auerbach", "train", 4, "Bavarian Forest foothills: mixed forest"),
    12555: ("kastensee", "train", 3, "Moraine south-east of Munich (photo reference, low confidence)"),
    12803: ("stubenthal", "holdout", 3, "Franconian Jura: rock, cliffs"),
    13172: ("schneckenberg", "holdout", 2, "Oberpfalz: mixed forest"),
    10206: ("doebraberg", "holdout", 4, "Frankenwald: spruce, steep slopes (scan with overprint)"),
    13273: ("schaufling", "holdout", 4, "Bavarian Forest, LAS 1.2 low density (LiDAR 2018, map 2026 draft)"),
}
MIN_COVER = 0.6
# per-site exceptions: a small map whose best tile is under the general threshold
MIN_COVER_SITE = {"schaufling": 0.05}


def main() -> None:
    tr = Transformer.from_crs(4326, 25832, always_xy=True)
    maps = {m["id"]: m for m in json.loads((ROOT / "results/omaps_maps.json").read_text())}
    out = {}
    for mid, (name, split, n_core, note) in SITES.items():
        g = transform(lambda x, y, z=None: tr.transform(x, y), shape(maps[mid]["outline"]))
        x0, y0, x1, y1 = (int(v // 1000) for v in g.bounds)
        cover = {
            (x, y): g.intersection(box(x * 1000, y * 1000, x * 1000 + 1000, y * 1000 + 1000)).area / 1e6
            for x in range(x0, x1 + 1)
            for y in range(y0, y1 + 1)
        }
        min_cover = MIN_COVER_SITE.get(name, MIN_COVER)
        core = sorted((c for c in cover if cover[c] >= min_cover), key=lambda c: -cover[c])[:n_core]
        halo = sorted({(x + dx, y + dy) for x, y in core for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - set(core))
        out[name] = dict(
            omaps_id=mid, split=split, note=note, map_date=maps[mid]["date"], map_name=maps[mid]["name"],
            core=[f"{x}_{y}" for x, y in sorted(core)],
            halo=[f"{x}_{y}" for x, y in halo],
            cover={f"{x}_{y}": round(cover[(x, y)], 2) for x, y in sorted(core)},
        )
    (ROOT / "sites.yaml").write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))
    n = sum(len(s["core"]) for s in out.values())
    print(f"{len(out)} sites, {n} core tiles, {len({t for s in out.values() for t in s['core'] + s['halo']})} files")


if __name__ == "__main__":
    main()
