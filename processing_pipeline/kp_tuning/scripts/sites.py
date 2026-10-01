#!/usr/bin/env python3
"""
Turn the chosen reference maps into study sites: the tiles a map covers best (core, scored) and
the ring around them (halo: lends points to kp's 127 m buffer, not scored). Writes sites.yaml.

    sites.py --config region.yaml

Input: `sites_input.yaml` next to the config (path: config key `sites_input`), one entry per map:

    13217:                       # omaps id
      name: fuerstenhaenge
      split: train               # or holdout -- split by whole map, never by tile
      max_core: 5                # at most this many core tiles (the best covered ones)
      note: "Franconian Jura, digital map"
      # optional:
      min_cover: 0.6             # share of a tile the map must cover (default 0.6)
      exclude_core: [761_5285]   # tiles to leave out (e.g. another group than the rest)
      keep_rows: [0.30, 0.72]    # photo of a full sheet: rows (fractions) that are map, not legend
      skip: [green]              # studies this map must not count in (green: e.g. ski-O maps)

A site is scored within one tile group: core tiles outside the site's majority group are dropped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common.add_config_arg(ap)
    a = ap.parse_args()
    common.set_config(a.config)
    T = common.tiles()
    spec = yaml.safe_load(common.path("sites_input", "sites_input.yaml").read_text())
    maps = {m["id"]: m for m in json.loads((common.results() / "omaps_maps.json").read_text())}
    gp = common.results() / "groups.csv"
    groups = dict(pd.read_csv(gp, dtype=str).values) if gp.exists() else {}
    tr = Transformer.from_crs(4326, T.crs, always_xy=True)
    out = {}
    for mid, s in spec.items():
        m = maps[int(mid)]
        g = transform(lambda x, y, z=None: tr.transform(x, y), shape(m["outline"])).buffer(0)
        cover = {t: g.intersection(box(*T.bounds(t))).area / T.size ** 2 for t in T.in_box(*g.bounds)}
        cover = {t: c for t, c in cover.items() if c >= s.get("min_cover", 0.6) and t not in s.get("exclude_core", [])}
        core = sorted(cover, key=lambda t: -cover[t])[: s.get("max_core", 4)]
        if not core:
            print(f"{s['name']}: no tile covered enough, skipped")
            continue
        gs = [groups.get(t, "all") for t in core]
        major = max(set(gs), key=gs.count)
        dropped = [t for t, gg in zip(core, gs) if gg != major]
        core = [t for t, gg in zip(core, gs) if gg == major]
        halo = sorted({n for t in core for n in T.neighbours(t)} - set(core))
        out[s["name"]] = dict(
            omaps_id=int(mid), split=s["split"], group=major, note=s.get("note", ""),
            map_date=m.get("date"), map_name=m.get("name"), core=sorted(core), halo=halo,
            cover={t: round(cover[t], 2) for t in sorted(core)},
            **{k: s[k] for k in ("keep_rows", "skip") if k in s})
        print(f"{s['name']}: {len(core)} core tiles in group {major}" + (f" (dropped {dropped})" if dropped else ""))
    p = common.path("sites", "sites.yaml")
    p.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))
    print(f"{len(out)} sites -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
