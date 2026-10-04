#!/usr/bin/env python3
"""
Render whole areas with every parameter set, for the side-by-side viewer (compare/).

A production run would be one karttapullautin batch run per parameter set. Most of that run is the
same for every set (reading the laz with its neighbours, the ground model, the contours), so here
each tile gets one batch run (contours only, but with the production ini: WGS84 GeoJSON cropped
to the tile), which also leaves the tile's buffered point cloud behind. The per-set layers --
vegetation, yellow, undergrowth, cliffs -- are then run from that point cloud (vegeonly /
cliffsonly, as in the study) and cropped to the tile and reprojected to WGS84 here, as
karttapullautin's batch mode does (crop_geojson in src/geojson.rs). `check` compares that with a
plain production batch run on one tile.

Tiles of each point generation get the sets of their generation (SETS). The LAZ files are fetched
as the tiles need them (a tile and its 8 neighbours) and deleted when no remaining tile needs them.

    region.py tiles <region>                  # list
    region.py run <region> [--gen 1.4] [--workers 3]
    region.py check <region> <tile>
    region.py tile <region> [--jobs 4]        # tippecanoe: base.pmtiles + v12_<set>/v14_<set>.pmtiles
    region.py run|tile <region> --sweep       # the visual sweep around the production ini, on every tile (sweep_sets.py)

Output: work/region/<region>/{base,sets/<set>}/<tile>_vec/<tile>_<layer>.geojson.gz, pmtiles/
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402
import sweep_sets  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORK = kp.WORK
URL = "https://geodaten.bayern.de/odd_data/laser/{}.laz"
TILER = "localhost/mapant/tiler:latest"
NF = WORK / "mapant-nf"
MAX_ZOOM = 17
MIN_FREE_GB = 35
DOWNLOADS = 6  # parallel laz downloads

REGIONS = {
    # Oberallgäu, Kempten to Oberstdorf's north: both generations, pre-Alpine to Alpine
    "allgaeu": dict(ll=(10.141995, 47.536451, 10.434060, 47.771032)),
    # the generation border north of Würzburg (Gramschatzer Wald), 6 x 6 km
    "wuerzburg": dict(box=(565, 5526, 571, 5532)),
}

SETS = {
    1.4: ["kp_default", "las14-r1", "las14-balanced", "las14-clean", "las14-balanced-sub3"],
    1.2: ["kp_default", "las12-r1", "las12-balanced", "las12-lessgreen", "las12-clean", "las12-detail",
          "las12-balanced-sub3", "las14-balanced", "las12-match-r1", "las12-match-balanced", "las12-match-clean",
          "las12-match-balanced-sub3"],
}

VEGE_LAYERS = ("vegetation", "yellow", "undergrowth")
BASE_LAYERS = ("contours", "formlines", "dotknolls")

OWNED = {  # mapant-nf bin/render_ini.py
    "batch": "1", "lazfolder": "./in", "batchoutfolder": "./out", "savetempfiles": "0",
    "savetempfolders": "0", "experimental_use_in_memory_fs": "0", "vectorvege": "1",
    "geojson_wgs84": "1", "batchmerge": "0", "output_dxf": "0", "vectorconf": "", "epsg": "25832",
}


def density() -> pd.DataFrame:
    d = pd.read_parquet(ROOT / "results/density.parquet")
    d["t"] = (d.min_x // 1000).astype(int).astype(str) + "_" + (d.min_y // 1000).astype(int).astype(str)
    return d.set_index("t")


def tiles(region: str) -> dict[str, float]:
    """tile -> LAS version"""
    d = density()
    r = REGIONS[region]
    if "ll" in r:
        w, s, e, n = r["ll"]
        d = d[(d.max_lon > w) & (d.min_lon < e) & (d.max_lat > s) & (d.min_lat < n)]
    else:
        x0, y0, x1, y1 = r["box"]
        x, y = d.min_x // 1000, d.min_y // 1000
        d = d[(x >= x0) & (x < x1) & (y >= y0) & (y < y1)]
    return {t: float(v) for t, v in d.las_version.items()}


def neighbours(t: str, known) -> list[str]:
    x, y = (int(v) for v in t.split("_"))
    return [f"{x + dx}_{y + dy}" for dy in (-1, 0, 1) for dx in (-1, 0, 1) if f"{x + dx}_{y + dy}" in known]


def sets_for(v: float, sweep: bool = False) -> list[str]:
    if sweep:  # the sweep's sets do not depend on the generation
        return list(sweep_sets.sweep())
    return SETS[v]


def overrides(name: str, all_sets: dict) -> dict:
    return {} if name == "kp_default" else all_sets[name]


# --------------------------------------------------------------------------------------------
# crop + reproject, as karttapullautin's batch mode writes its GeoJSON


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
        self.tf = Transformer.from_crs(25832, 4326, always_xy=True)

    def _wgs(self, node):
        if node and isinstance(node[0], (int, float)):
            lon, lat = self.tf.transform(node[0], node[1])
            return [round(lon, 7), round(lat, 7)]
        return [self._wgs(n) for n in node]

    def __call__(self, src: Path, dst: Path, tile: str) -> int:
        x0, y0 = (int(v) * 1000 for v in tile.split("_"))
        box = (x0, y0, x0 + 1000, y0 + 1000)
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


# --------------------------------------------------------------------------------------------
# per tile


def stage(xyz: Path, stage_name: str, ov: dict, work: Path, threads: int) -> Path:
    flag, _ = kp.STAGES[stage_name]
    ini = kp.effective_ini(ov)
    ini[flag] = "1"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    kp.write_ini(work / "pullauta.ini", ini)
    (work / "t.xyz.bin").symlink_to(xyz)
    proc = subprocess.run([str(kp.PULLAUTA), "t.xyz.bin", "norender"], cwd=work,
                          env=dict(os.environ, RAYON_NUM_THREADS=str(threads), RUST_LOG="warn"),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{stage_name} failed in {work}: {proc.stderr[-2000:]}")
    return work / "temp"


def batch(tile: str, known: set[str], d: Path, threads: int, contours_only: bool = True,
          keep_xyz: Path | None = None, extra: dict | None = None) -> Path:
    run = d / f"tmp/{tile}_batch"
    shutil.rmtree(run, ignore_errors=True)
    (run / "in").mkdir(parents=True)
    (run / "out").mkdir()
    for t in neighbours(tile, known):
        (run / "in" / f"{t}.laz").symlink_to((WORK / f"laz/{t}.laz").resolve())
        if t != tile:
            (run / "out" / f"{t}.png").touch()
    ini = kp.base_ini()
    ini.update(OWNED)
    ini.update(processes="1", savetempfolders="1" if keep_xyz else "0",
               contoursonly="1" if contours_only else "0")
    ini.update(extra or {})
    kp.write_ini(run / "pullauta.ini", ini)
    with open(run / "pullauta.log", "w") as log:
        p = subprocess.run([str(kp.PULLAUTA)], cwd=run, env=dict(os.environ, RAYON_NUM_THREADS=str(threads)),
                           stdout=log, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise RuntimeError(f"batch {tile} failed, see {run}/pullauta.log")
    if keep_xyz:
        shutil.move(run / f"temp_{tile}_dir/xyztemp.xyz.bin", keep_xyz)
        shutil.rmtree(run / f"temp_{tile}_dir")
    return run


def process_tile(region: str, tile: str, v: float, known: set[str], all_sets: dict, threads: int,
                 crop: Cropper) -> None:
    d = WORK / f"region/{region}"
    marks = d / "done"
    marks.mkdir(parents=True, exist_ok=True)
    todo = [s for s in sets_for(v) if not (marks / f"{tile}.{s}").exists()]
    if (marks / f"{tile}.base").exists() and not todo:
        return
    xyz = d / f"tmp/{tile}.xyz.bin"
    if (marks / f"{tile}.base").exists() and xyz.exists():  # interrupted earlier: base and cloud are there
        run = None
    else:
        run = batch(tile, known, d, threads, keep_xyz=xyz)
    for layer in BASE_LAYERS if run else ():
        f = run / "out" / f"{tile}_{layer}.geojson"
        dst = d / f"base/{tile}_vec/{tile}_{layer}.geojson.gz"
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "rb") if f.exists() else open(os.devnull, "rb") as fi, gzip.open(dst, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    if run:
        shutil.rmtree(run)
        (marks / f"{tile}.base").write_text("")
    vege_done: dict[str, Path] = {}  # stage key -> folder of cropped layers
    cliff_done: dict[str, Path] = {}
    for s in todo:
        o = overrides(s, all_sets)
        out = d / f"sets/{s}/{tile}_vec"
        vk = kp.run_key(tile, "full", "vege", {**kp.effective_ini(o), "vegeonly": "1"})
        ck = kp.run_key(tile, "full", "cliffs", {**kp.effective_ini(o), "cliffsonly": "1"})
        if vk not in vege_done:
            tmp = stage(xyz, "vege", o, d / f"tmp/{tile}_vege", threads)
            for layer in VEGE_LAYERS:
                crop(tmp / f"{layer}.geojson", out / f"{tile}_{layer}.geojson.gz", tile)
            shutil.rmtree(tmp.parent)
            vege_done[vk] = out
        else:
            out.mkdir(parents=True, exist_ok=True)
            for layer in VEGE_LAYERS:
                shutil.copy(vege_done[vk] / f"{tile}_{layer}.geojson.gz", out)
        if ck not in cliff_done:
            tmp = stage(xyz, "cliffs", o, d / f"tmp/{tile}_cliffs", threads)
            crop(tmp / "cliffs.geojson", out / f"{tile}_cliffs.geojson.gz", tile)
            shutil.rmtree(tmp.parent)
            cliff_done[ck] = out
        else:
            shutil.copy(cliff_done[ck] / f"{tile}_cliffs.geojson.gz", out)
        (marks / f"{tile}.{s}").write_text("")
    xyz.unlink(missing_ok=True)


def revege_tile(region: str, tile: str, v: float, known: set[str], all_sets: dict, threads: int,
                crop: Cropper) -> None:
    """
    Redo the vegetation layers (vegetation, yellow, undergrowth) of every set of a tile with kp's
    own crop (the first version cropped with GEOS, which mangles polygons kp's simplification left
    invalid). One batch run with vegeonly=1 gives kp_default's layers as production writes them and
    the point cloud for the other sets. Contours, knolls and cliffs stay as they are.
    """
    d = WORK / f"region/{region}"
    marks = d / "done2"
    marks.mkdir(parents=True, exist_ok=True)
    todo = [s for s in sets_for(v) if not (marks / f"{tile}.{s}").exists()]
    if not todo:
        return
    xyz = d / f"tmp/{tile}.xyz.bin"
    run = batch(tile, known, d, threads, contours_only=False, keep_xyz=xyz, extra={"vegeonly": "1"})
    done: dict[str, Path] = {}
    for s in todo:
        o = overrides(s, all_sets)
        out = d / f"sets/{s}/{tile}_vec"
        out.mkdir(parents=True, exist_ok=True)
        vk = kp.run_key(tile, "full", "vege", {**kp.effective_ini(o), "vegeonly": "1"})
        if s == "kp_default":
            for layer in VEGE_LAYERS:
                f = run / "out" / f"{tile}_{layer}.geojson"
                with open(f, "rb") if f.exists() else open(os.devnull, "rb") as fi, \
                        gzip.open(out / f"{tile}_{layer}.geojson.gz", "wb") as fo:
                    shutil.copyfileobj(fi, fo)
        elif vk in done:
            for layer in VEGE_LAYERS:
                shutil.copy(done[vk] / f"{tile}_{layer}.geojson.gz", out)
        else:
            tmp = stage(xyz, "vege", o, d / f"tmp/{tile}_vege", threads)
            for layer in VEGE_LAYERS:
                crop(tmp / f"{layer}.geojson", out / f"{tile}_{layer}.geojson.gz", tile)
            shutil.rmtree(tmp.parent)
        done[vk] = out
        (marks / f"{tile}.{s}").write_text("")
    shutil.rmtree(run)
    xyz.unlink(missing_ok=True)


def sweep_tile(region: str, tile: str, v: float, known: set[str], all_sets: dict, threads: int,
               crop: Cropper) -> None:
    """
    The sweep sets of a tile. One batch run with the production ini and vegeonly=1 gives prod-las14's
    layers as production writes them and the point cloud for the other sets (vegeonly stage + kp's
    crop). Contours and knolls are in base/ already; the sweep leaves cliffs at kp's default, so they
    are kp_default's.
    """
    d = WORK / f"region/{region}"
    marks = d / "done_sweep"
    marks.mkdir(parents=True, exist_ok=True)
    todo = [s for s in sets_for(v, sweep=True) if not (marks / f"{tile}.{s}").exists()]
    if not todo:
        return
    xyz = d / f"tmp/{tile}.xyz.bin"
    prod = "prod-las14"
    run = batch(tile, known, d, threads, contours_only=False, keep_xyz=xyz,
                extra={**kp.effective_ini(overrides(prod, all_sets)), **OWNED, "processes": "1",
                       "savetempfolders": "1", "contoursonly": "0", "vegeonly": "1"})
    cliffs = d / f"sets/kp_default/{tile}_vec/{tile}_cliffs.geojson.gz"
    done: dict[str, Path] = {}
    for s in todo:
        o = overrides(s, all_sets)
        out = d / f"sets/{s}/{tile}_vec"
        out.mkdir(parents=True, exist_ok=True)
        vk = kp.run_key(tile, "full", "vege", {**kp.effective_ini(o), "vegeonly": "1"})
        if s == prod:
            for layer in VEGE_LAYERS:
                f = run / "out" / f"{tile}_{layer}.geojson"
                with open(f, "rb") if f.exists() else open(os.devnull, "rb") as fi, \
                        gzip.open(out / f"{tile}_{layer}.geojson.gz", "wb") as fo:
                    shutil.copyfileobj(fi, fo)
        elif vk in done:
            for layer in VEGE_LAYERS:
                shutil.copy(done[vk] / f"{tile}_{layer}.geojson.gz", out)
        else:
            tmp = stage(xyz, "vege", o, d / f"tmp/{tile}_vege", threads)
            for layer in VEGE_LAYERS:
                crop(tmp / f"{layer}.geojson", out / f"{tile}_{layer}.geojson.gz", tile)
            shutil.rmtree(tmp.parent)
        if cliffs.exists():
            shutil.copy(cliffs, out)
        done[vk] = out
        (marks / f"{tile}.{s}").write_text("")
    shutil.rmtree(run)
    xyz.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------
# driver: download ahead, process, delete laz nobody needs any more


def free_gb() -> float:
    return shutil.disk_usage(WORK).free / 1e9


def download(tile: str) -> None:
    f = WORK / f"laz/{tile}.laz"
    if f.exists():
        return
    tmp = f.with_suffix(f".part{os.getpid()}_{threading.get_ident()}")  # two passes may fetch the same file
    # the server drops connections mid-file now and then: resume (-C -) instead of starting over
    for attempt in range(10):
        if subprocess.run(["curl", "-sSf", "-C", "-", "--retry", "5", "--retry-all-errors", "--retry-delay", "3",
                           "-o", str(tmp), URL.format(tile)]).returncode == 0:
            tmp.rename(f)
            return
        time.sleep(5 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"download {tile} failed")


def protected() -> set[str]:
    """laz the study still uses (sites, the Würzburg border block)"""
    keep = {t for s in kp.sites().values() for t in s["core"] + s["halo"]}
    return keep | {"567_5528", "568_5528", "567_5529", "568_5529"}


def run(region: str, gens: list[float], workers: int, threads: int, reverse: bool = False,
        revege: bool = False, sweep: bool = False, limit: int = 0) -> None:
    """
    reverse=True is a helper next to a running pass: it takes the queue from the end and stops
    short of the tiles the other pass has started (a margin of 12 queue places), so that the two
    never work on one tile.
    """
    d = WORK / f"region/{region}"
    all_sets = json.loads((WORK / "sets.json").read_text())
    for v in gens:
        missing = [s for s in sets_for(v, sweep) if s != "kp_default" and s not in all_sets]
        if missing:
            raise SystemExit(f"sets missing from work/sets.json: {missing}")
    tl = tiles(region)
    known = set(density().index)
    marks = d / "done"
    marks.mkdir(parents=True, exist_ok=True)

    if revege or sweep:
        marks = d / ("done_sweep" if sweep else "done2")
        marks.mkdir(parents=True, exist_ok=True)

    def finished(t):
        if revege or sweep:
            return all((marks / f"{t}.{s}").exists() for s in sets_for(tl[t], sweep))
        return (marks / f"{t}.base").exists() and all((marks / f"{t}.{s}").exists() for s in sets_for(tl[t]))

    order = sorted(tl, key=lambda t: (-int(t.split("_")[1]), int(t.split("_")[0])))
    queue = [t for t in order if tl[t] in gens and not finished(t)]
    if limit:
        queue = queue[:limit]
    fwd = list(queue)
    mine: set[str] = set()
    if reverse:
        queue = queue[::-1]

    def taken_by_other(t):
        """reverse mode: t is within reach of the forward pass"""
        started = [i for i, u in enumerate(fwd) if u not in mine and ((marks / f"{u}.base").exists()
                   or (d / f"tmp/{u}_batch").exists() or (d / f"tmp/{u}.xyz.bin").exists())]
        return bool(started) and fwd.index(t) <= max(started) + 12
    # a laz stays while any unfinished tile of the region (this pass or a later one) needs it
    pending = {t for t in order if not finished(t)}
    lock = threading.Lock()
    keep = protected()
    ready: dict[str, threading.Event] = {t: threading.Event() for t in queue}
    started = time.time()
    n_done = [0]

    def downloader():
        # one pool for all files, so that it keeps DOWNLOADS connections busy across tiles (most of a
        # tile's neighbours are already there); a tile is ready when all of its files are
        futs: dict = {}
        waiting: list = []

        def watch():
            for t, fs in _drain():
                for f in fs:
                    try:
                        f.result()
                    except Exception as e:  # the tile's batch run fails and reports it; a rerun picks it up
                        print(f"{region} {t}: {e}", flush=True)
                ready[t].set()

        def _drain():
            i = 0
            while True:
                while i >= len(waiting):
                    time.sleep(1)
                if waiting[i] is None:
                    return
                yield waiting[i]
                i += 1

        threading.Thread(target=watch, daemon=True).start()
        with ThreadPoolExecutor(DOWNLOADS) as ex:
            for i, t in enumerate(queue):
                while i - n_done[0] > 3 * workers + 4 or free_gb() < MIN_FREE_GB:
                    time.sleep(5)
                waiting.append((t, [futs.setdefault(n, ex.submit(download, n)) for n in neighbours(t, known)]))
            waiting.append(None)

    def cleanup():
        with lock:
            need = {n for t in pending for n in neighbours(t, known)}
        for f in (WORK / "laz").glob("*.laz"):
            s = f.stem
            if s in tl or any(n in tl for n in neighbours(s, known)):
                if s not in need and s not in keep:
                    f.unlink(missing_ok=True)

    crop = Cropper()

    def work(t):
        ready[t].wait()
        if reverse:
            with lock:
                if taken_by_other(t):
                    n_done[0] += 1  # lets the downloader move on
                    return
                mine.add(t)
        t0 = time.time()
        try:
            fn = sweep_tile if sweep else revege_tile if revege else process_tile
            fn(region, t, tl[t], known, all_sets, threads, crop)
        except Exception:  # report now, not when the pool is drained; a rerun picks the tile up
            import traceback
            print(f"{region} {t} FAILED\n{traceback.format_exc()}", flush=True)
            return
        with lock:
            pending.discard(t)
            n_done[0] += 1
            k = n_done[0]
        cleanup()
        el = time.time() - started
        print(f"{region} {t} (LAS {tl[t]}) {time.time() - t0:.0f}s  [{k}/{len(queue)}, "
              f"{el / 3600:.1f} h, ~{el / k * (len(queue) - k) / 3600:.1f} h left, {free_gb():.0f} GB free]",
              flush=True)

    threading.Thread(target=downloader, daemon=True).start()
    with ThreadPoolExecutor(workers) as ex:
        for f in [ex.submit(work, t) for t in queue]:
            f.result()


def check(region: str, tile: str) -> None:
    """Production batch run (all layers, default ini) vs this script's kp_default layers."""
    import shapely
    from shapely.geometry import shape

    d = WORK / f"region/{region}"
    known = set(density().index)
    for t in neighbours(tile, known):
        download(t)
    r = batch(tile, known, d, 8, contours_only=False)
    for layer in VEGE_LAYERS + ("cliffs",) + BASE_LAYERS:
        a = r / "out" / f"{tile}_{layer}.geojson"
        src = d / ("base" if layer in BASE_LAYERS else "sets/kp_default") / f"{tile}_vec/{tile}_{layer}.geojson.gz"
        fa = json.loads(a.read_text())["features"] if a.exists() else []
        fb = json.loads(gzip.open(src, "rt").read())["features"] if src.exists() else []
        ga = shapely.union_all([shape(f["geometry"]) for f in fa]) if fa else shapely.Point()
        gb = shapely.union_all([shape(f["geometry"]) for f in fb]) if fb else shapely.Point()
        m = "area" if layer in VEGE_LAYERS else "length"
        va, vb = getattr(ga, m), getattr(gb, m)
        sym = getattr(ga.symmetric_difference(gb), m) if m == "area" else float("nan")
        print(f"{layer:12s} production {len(fa):5d} feats {va:.3e} | here {len(fb):5d} feats {vb:.3e}"
              + (f" | sym.diff {sym / max(va, 1e-12):.2%}" if m == "area" else ""))
    shutil.rmtree(r)


# --------------------------------------------------------------------------------------------
# vector tiles


def tile_pmtiles(region: str, jobs: int, only: str = "", sweep: bool = False) -> None:
    """One PMTiles archive per (generation, set) plus base; tippecanoe runs in parallel over parents."""
    import mercantile

    d = WORK / f"region/{region}"
    tl = tiles(region)
    out = d / "pmtiles"
    out.mkdir(exist_ok=True)
    targets = [("base", d / "base", list(tl))]
    for v, tag in ((1.4, "v14"), (1.2, "v12")):
        ts = [t for t in tl if tl[t] == v]
        if ts:
            targets += [(f"{tag}_{s}", d / f"sets/{s}", ts) for s in sets_for(v, sweep)]
    if only:
        targets = [t for t in targets if t[0].startswith(only)]
    targets = [t for t in targets if not (out / f"{t[0]}.pmtiles").exists()]
    to_ll = __import__("pyproj").Transformer.from_crs(25832, 4326, always_xy=True)
    plan = {}
    for name, src, ts in targets:
        stage_dir = d / f"tiling/{name}"
        shutil.rmtree(stage_dir, ignore_errors=True)
        (stage_dir / "vec").mkdir(parents=True)
        ts = [t for t in ts if (src / f"{t}_vec").exists()]
        for t in ts:  # hard links: the container sees no symlink targets
            shutil.copytree(src / f"{t}_vec", stage_dir / f"vec/{t}_vec", copy_function=os.link)
        # the z12 parents the tiles touch (the generations form ragged areas, so not their bbox)
        parents = set()
        for t in ts:
            x, y = (int(v) * 1000 for v in t.split("_"))
            w, s_ = to_ll.transform(x, y)
            e, n = to_ll.transform(x + 1000, y + 1000)
            parents |= set(mercantile.tiles(w, s_, e, n, 12))
        plan[name] = (stage_dir, sorted(parents))

    def cut(job):
        name, p = job
        stage_dir = plan[name][0]
        r = subprocess.run(["podman", "run", "--rm", "-v", f"{stage_dir}:/data", "-v", f"{NF / 'bin'}:/nfbin:ro",
                            TILER, "python", "/nfbin/make_vector_tiles.py", "/data/vec",
                            f"/data/p_{p.z}_{p.x}_{p.y}.pmtiles", "--parent", str(p.z), str(p.x), str(p.y),
                            "--max-zoom", str(MAX_ZOOM)], capture_output=True, text=True)
        # 110: tippecanoe found no feature inside this parent (only a buffer's edge of a tile)
        if r.returncode != 0:
            if "exit status 110" not in r.stderr:
                raise RuntimeError(f"{name} {p}: {r.stderr[-3000:]}")
            (stage_dir / f"p_{p.z}_{p.x}_{p.y}.pmtiles").unlink(missing_ok=True)

    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(cut, [(name, p) for name, (_, ps) in plan.items() for p in ps]))

    for name, (stage_dir, parents) in plan.items():
        parts = [f"/data/p_{p.z}_{p.x}_{p.y}.pmtiles" for p in parents
                 if (stage_dir / f"p_{p.z}_{p.x}_{p.y}.pmtiles").exists()]
        subprocess.run(["podman", "run", "--rm", "-v", f"{stage_dir}:/data", TILER, "tile-join", "--force",
                        "--no-tile-size-limit", "-o", "/data/out.pmtiles", *parts], check=True, capture_output=True)
        shutil.move(stage_dir / "out.pmtiles", out / f"{name}.pmtiles")
        shutil.rmtree(stage_dir)
        print(f"{region}: {name}.pmtiles ({(out / f'{name}.pmtiles').stat().st_size / 1e6:.0f} MB)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tiles", "run", "check", "tile"])
    ap.add_argument("region", choices=list(REGIONS))
    ap.add_argument("tile", nargs="?")
    ap.add_argument("--gen", type=float, action="append")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--threads", type=int, default=5)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--reverse", action="store_true", help="helper pass from the end of the queue")
    ap.add_argument("--revege", action="store_true", help="redo the vegetation layers with kp's own crop")
    ap.add_argument("--only", default="", help="tile only the archives whose name starts with this")
    ap.add_argument("--sweep", action="store_true", help="the sweep sets of sweep_sets.py (every tile)")
    ap.add_argument("--limit", type=int, default=0, help="run: only the first N tiles of the queue (timing)")
    a = ap.parse_args()
    if a.cmd == "tiles":
        tl = tiles(a.region)
        print(len(tl), pd.Series(tl).value_counts().to_dict(),
              f"{density().loc[list(tl)].size_bytes.sum() / 1e9:.0f} GB laz")
    elif a.cmd == "run":
        run(a.region, a.gen or [1.4, 1.2], a.workers, a.threads, a.reverse, a.revege, a.sweep, a.limit)
    elif a.cmd == "check":
        check(a.region, a.tile)
    elif a.cmd == "tile":
        tile_pmtiles(a.region, a.jobs, a.only, a.sweep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
