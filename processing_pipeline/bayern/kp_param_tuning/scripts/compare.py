#!/usr/bin/env python3
"""
Build the comparison web app from region.py's vector tiles.

    compare.py build          # -> work/compare/ (index.html, data/, vendor/)
    compare.py serve [port]   # serve it with HTTP range requests (PMTiles needs them)

The app shows each area with any LAS 1.4 set on the LAS 1.4 tiles and any LAS 1.2 set on the LAS
1.2 tiles, in one map or two synchronised ones. The styling is production's: mapant-nf's
make_viewer.py fills assets/viewer/style.json, and the green colours come from each set's ini
(make_viewer.ini_colors), since a set with seven greenshades draws its ISOM greens in other tones
than one with three. Everything is local (MapLibre and PMTiles are vendored), except the optional
OSM background.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402
import region  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = kp.WORK / "compare"
APP = Path(__file__).with_name("compare.html")
sys.path.insert(0, str(region.NF / "bin"))

LABELS = {
    "kp_default": "karttapullautin default",
    "las14-r1": "round 1 (reference maps)",
    "las14-balanced": "round 2 balanced (recommended)",
    "las14-clean": "round 2 clean",
    "las14-balanced-sub3": "round 2 balanced, 7 greenshades",
    "las12-r1": "round 1 (reference maps)",
    "las12-balanced": "round 2 balanced (reference maps)",
    "las12-lessgreen": "round 2 less green",
    "las12-clean": "round 2 clean",
    "las12-detail": "round 2 detail",
    "las12-balanced-sub3": "round 2 balanced, 7 greenshades",
    "las14-balanced": "LAS 1.4 set (round 2 balanced)",
    "las12-match-r1": "round 3: matches las14-r1",
    "las12-match-balanced": "round 3: matches las14-balanced",
    "las12-match-clean": "round 3: matches las14-clean",
    "las12-match-balanced-sub3": "round 3: matches las14-balanced-sub3",
}

# where each area opens: a forested stretch of the generation border, at zoom 13.5
START = {"allgaeu": [10.3825, 47.566, 13.5], "wuerzburg": [9.947, 49.9095, 13.5]}

PRESETS = [
    ("kp default", "kp_default", "kp_default"),
    ("round 1", "las14-r1", "las12-r1"),
    ("round 2 balanced", "las14-balanced", "las12-balanced"),
    ("round 2 clean", "las14-clean", "las12-clean"),
    ("round 2 balanced + las12-detail", "las14-balanced", "las12-detail"),
    ("round 2 balanced + las12-lessgreen", "las14-balanced", "las12-lessgreen"),
    ("round 2, 7 greenshades", "las14-balanced-sub3", "las12-balanced-sub3"),
    ("LAS 1.4 set everywhere", "las14-balanced", "las14-balanced"),
    ("round 3: r1 + matched", "las14-r1", "las12-match-r1"),
    ("round 3: balanced + matched", "las14-balanced", "las12-match-balanced"),
    ("round 3: clean + matched", "las14-clean", "las12-match-clean"),
    ("round 3: 7 greenshades + matched", "las14-balanced-sub3", "las12-match-balanced-sub3"),
]


def outline(name: str) -> dict:
    """The LAS 1.2 / 1.4 tiles as dissolved polygons (WGS84) for the generation overlay."""
    import shapely
    from pyproj import Transformer
    from shapely.geometry import box, mapping

    tf = Transformer.from_crs(25832, 4326, always_xy=True)
    feats = []
    for v, tag in ((1.2, "LAS 1.2"), (1.4, "LAS 1.4")):
        ts = [t for t, g in region.tiles(name).items() if g == v]
        if not ts:
            continue
        u = shapely.union_all([box(int(t.split("_")[0]) * 1000, int(t.split("_")[1]) * 1000,
                                   int(t.split("_")[0]) * 1000 + 1000, int(t.split("_")[1]) * 1000 + 1000) for t in ts])
        u = shapely.segmentize(u, 100)
        u = shapely.transform(u, lambda xy: __import__("numpy").column_stack(tf.transform(xy[:, 0], xy[:, 1])))
        feats.append({"type": "Feature", "properties": {"gen": tag}, "geometry": mapping(u)})
    return {"type": "FeatureCollection", "features": feats}


def build() -> None:
    import make_viewer
    import mercantile

    sets = json.loads((kp.WORK / "sets.json").read_text())
    OUT.mkdir(exist_ok=True)
    (OUT / "data").mkdir(exist_ok=True)
    manifest = {"regions": {}, "sets": {}, "presets": []}
    for name in region.REGIONS:
        pm = kp.WORK / f"region/{name}/pmtiles"
        if not (pm / "base.pmtiles").exists():
            continue
        rd = OUT / f"data/{name}"
        rd.mkdir(exist_ok=True)
        files = sorted(p.name for p in pm.glob("*.pmtiles"))
        for f in files:
            if (rd / f).exists():
                (rd / f).unlink()
            os.link(pm / f, rd / f)
        tl = region.tiles(name)
        to_ll = __import__("pyproj").Transformer.from_crs(25832, 4326, always_xy=True)
        xs = [int(t.split("_")[0]) * 1000 for t in tl]
        ys = [int(t.split("_")[1]) * 1000 for t in tl]
        w, s = to_ll.transform(min(xs), min(ys))
        e, n = to_ll.transform(max(xs) + 1000, max(ys) + 1000)
        parents = list(mercantile.tiles(w, s, e, n, 12))
        (rd / "parents.csv").write_text("z,x,y\n" + "".join(f"{p.z},{p.x},{p.y}\n" for p in parents))
        # style + sprite at this area's latitude; colours are replaced per set in the app
        ini = kp.effective_ini({})
        ini.update(region.OWNED)
        kp.write_ini(rd / "default.ini", ini)
        make_viewer.main(["--template-dir", str(region.NF / "assets/viewer"), "--parent-tiles", str(rd / "parents.csv"),
                          "--ini", str(rd / "default.ini"), "--base-zoom", "12", "--max-zoom", str(region.MAX_ZOOM),
                          "--title", name, "--out-dir", str(rd)])
        (rd / "index.html").unlink(missing_ok=True)
        (rd / "outline.geojson").write_text(json.dumps(outline(name)))
        manifest["regions"][name] = dict(
            files=files, bounds=[w, s, e, n], start=START.get(name, [(w + e) / 2, (s + n) / 2, 13]),
            tiles={"LAS 1.2": sum(v == 1.2 for v in tl.values()), "LAS 1.4": sum(v == 1.4 for v in tl.values())})
    used = {s for v in region.SETS.values() for s in v}
    for s in used:
        o = {} if s == "kp_default" else sets.get(s)
        if o is None:
            continue
        ini = kp.effective_ini(o)
        manifest["sets"][s] = dict(label=LABELS.get(s, s), colors=make_viewer.ini_colors(ini),
                                   params={k: v for k, v in o.items()})
    manifest["presets"] = [dict(label=a, v14=b, v12=c) for a, b, c in PRESETS
                           if b in manifest["sets"] and c in manifest["sets"]]
    manifest["gens"] = {"v14": region.SETS[1.4], "v12": region.SETS[1.2]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    shutil.copy(APP, OUT / "index.html")
    shutil.copy(Path(__file__).with_name("compare_serve.py"), OUT / "serve.py")
    print(f"{OUT}: {', '.join(manifest['regions'])}; {len(manifest['sets'])} sets")


def main() -> int:
    if sys.argv[1] == "build":
        build()
    elif sys.argv[1] == "serve":
        import compare_serve
        compare_serve.serve(OUT, int(sys.argv[2]) if len(sys.argv) > 2 else 8765)
    return 0


if __name__ == "__main__":
    sys.exit(main())
