#!/usr/bin/env python3
"""
Build the comparison viewer from render_area.py's PMTiles.

    compare.py build --config c.yaml    # -> <work>/compare/ (index.html, manifest.json, data/, vendor/, serve.py)
    compare.py serve --config c.yaml [port]
    compare.py shot  --config c.yaml URL OUT.png '{"A": {"G": "set"}, "B": {...}}'   # scripted screenshot

Two synchronised maps; in each, any set can be chosen per tile group, or a preset (config
`presets: [{label: ..., sets: {G: set, ...}}]`). Styling is production's: mapant-nf's
make_viewer.py fills assets/viewer/style.json (as the vector version of the mapant webapp loads
it); green tones come from each set's ini (make_viewer.ini_colors -- a set with 7 greenshades draws
406 darker). The tiles start at z12 as in production; each area opens at config
`areas.<name>.start: [lon, lat, zoom]` (default: its centre at z13). Everything is local except the
optional OSM background; it needs HTTP range requests (serve.py), not file://.

Optional config: `set_labels: {set: "label"}`, `group_labels: {G: "LAS 1.4 tiles"}`, `title:`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import kp  # noqa: E402
import render_area  # noqa: E402
import sets as setsmod  # noqa: E402

VENDOR = {"maplibre-gl.js": "https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js",
          "maplibre-gl.css": "https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css",
          "pmtiles.js": "https://unpkg.com/pmtiles@4.5.0/dist/pmtiles.js"}


def out_dir() -> Path:
    return common.work() / "compare"


def outline(area: str) -> dict:
    import numpy as np
    import shapely
    from pyproj import Transformer
    from shapely.geometry import box, mapping

    T = common.tiles()
    tf = Transformer.from_crs(T.crs, 4326, always_xy=True)
    tl = render_area.area_tiles(area)
    feats = []
    for g in sorted(set(tl.values())):
        u = shapely.union_all([box(*T.bounds(t)) for t, gg in tl.items() if gg == g])
        u = shapely.segmentize(u, 100)
        u = shapely.transform(u, lambda xy: np.column_stack(tf.transform(xy[:, 0], xy[:, 1])))
        feats.append({"type": "Feature", "properties": {"group": g}, "geometry": mapping(u)})
    return {"type": "FeatureCollection", "features": feats}


def build() -> None:
    sys.path.insert(0, str(common.mapant_nf() / "bin"))
    import make_viewer
    import mercantile
    from pyproj import Transformer

    c = common.cfg()
    out = out_dir()
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "vendor").mkdir(exist_ok=True)
    for f, url in VENDOR.items():
        if not (out / "vendor" / f).exists():
            urllib.request.urlretrieve(url, out / "vendor" / f)
    allsets = setsmod.load_sets()
    T = common.tiles()
    to_ll = Transformer.from_crs(T.crs, 4326, always_xy=True)
    labels = c.get("set_labels", {})
    glabels = {str(k): v for k, v in (c.get("group_labels") or {}).items()}
    man = {"title": c.get("title", f"{c.get('name', '')} parameter sets"), "regions": {}, "groups": {}, "sets": {},
           "presets": c.get("presets", [])}
    for area, a in c["areas"].items():
        pm = render_area.area_dir(area) / "pmtiles"
        if not (pm / "base.pmtiles").exists():
            print(f"{area}: not tiled yet, skipped")
            continue
        rd = out / f"data/{area}"
        rd.mkdir(parents=True, exist_ok=True)
        files = sorted(p.name for p in pm.glob("*.pmtiles"))
        for f in files:
            (rd / f).unlink(missing_ok=True)
            os.link(pm / f, rd / f)  # hard links: the build costs no disk
        tl = render_area.area_tiles(area)
        bs = [T.bounds(t) for t in tl]
        w, s = to_ll.transform(min(b[0] for b in bs), min(b[1] for b in bs))
        e, n = to_ll.transform(max(b[2] for b in bs), max(b[3] for b in bs))
        parents = list(mercantile.tiles(w, s, e, n, 12))
        (rd / "parents.csv").write_text("z,x,y\n" + "".join(f"{p.z},{p.x},{p.y}\n" for p in parents))
        ini = kp.effective_ini({})
        ini.update(render_area.OWNED)
        kp.write_ini(rd / "default.ini", ini)
        make_viewer.main(["--template-dir", str(common.mapant_nf() / "assets/viewer"), "--parent-tiles", str(rd / "parents.csv"),
                          "--ini", str(rd / "default.ini"), "--base-zoom", "12", "--max-zoom", str(render_area.MAX_ZOOM),
                          "--title", area, "--out-dir", str(rd)])
        (rd / "index.html").unlink(missing_ok=True)
        (rd / "outline.geojson").write_text(json.dumps(outline(area)))
        cnt = {}
        for g in tl.values():
            cnt[g] = cnt.get(g, 0) + 1
        man["regions"][area] = dict(files=files, bounds=[w, s, e, n], tiles=cnt,
                                    start=a.get("start", [(w + e) / 2, (s + n) / 2, 13]))
        for g in cnt:
            man["groups"].setdefault(g, {"label": glabels.get(g, f"group {g}"), "sets": render_area.sets_for(g)})
    for g in man["groups"].values():
        for sname in g["sets"]:
            o = allsets.get(sname, {})
            man["sets"][sname] = dict(label=labels.get(sname, "karttapullautin default" if sname == "kp_default" else ""),
                                      colors=make_viewer.ini_colors(kp.effective_ini(o)), params=o)
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    shutil.copy(Path(__file__).with_name("compare.html"), out / "index.html")
    shutil.copy(Path(__file__).with_name("compare_serve.py"), out / "serve.py")
    print(f"{out}: {', '.join(man['regions'])}; groups {list(man['groups'])}; serve with: python3 {out / 'serve.py'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "serve", "shot"])
    ap.add_argument("args", nargs="*")
    common.add_config_arg(ap)
    a = ap.parse_args()
    common.set_config(a.config)
    if a.cmd == "build":
        build()
    elif a.cmd == "serve":
        import compare_serve
        compare_serve.serve(out_dir(), int(a.args[0]) if a.args else 8765)
    else:
        subprocess.run(["node", str(Path(__file__).with_name("compare_shot.mjs")), a.args[0], a.args[1], "1600", "900",
                        a.args[2] if len(a.args) > 2 else ""], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
