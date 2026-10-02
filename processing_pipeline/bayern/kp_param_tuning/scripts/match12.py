#!/usr/bin/env python3
"""
Round 3: LAS 1.2 parameter sets that make LAS 1.2 areas look like LAS 1.4 areas.

LAS 1.4 is the better-supported generation (more and cleaner reference maps). So each LAS 1.4 set
from the report is taken as given, and a LAS 1.2 set is searched for that makes the map on the
LAS 1.2 side of a generation border look like the map the LAS 1.4 set draws on the other side.

Data: the 2x2 km border blocks of border.yaml (two tiles of each generation), extended to 52 blocks
in round 3. Blocks are split into train (2/3) and holdout (1/3). Only forest is compared (OSM
landuse=forest / natural=wood), so a border that also separates forest from farmland does not
count as a map difference.

Per block and side, within forest, at 2 m:
  p        share of white, 406, 408, 410 and open (yellow) area
  edges    class boundary length per forest area (patchiness, what makes a map look busy)

Mismatch of a LAS 1.2 set against a LAS 1.4 target, over the blocks (b):
  systematic  EMD over the ordered levels white<406<408<410 of mean_b(p14 - p12), + |mean open diff|
              + 0.2 |mean_b log(edges14 / edges12)|
  per_block   the same terms averaged per block (absolute), which also rewards following the
              LAS 1.4 side's forest-to-forest variation
  objective   systematic + 0.3 per_block (minimised)

    match12.py prepare              # download + cache new blocks, LAS 1.4 targets, free space
    match12.py forest               # OSM forest polygons per block
    match12.py search --trials N    # one TPE study per target; every trial is scored for all
    match12.py choose               # sets -> work/sets.json, params/*.ini
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import optuna
import yaml

sys.path.insert(0, str(Path(__file__).parent))
import border  # noqa: E402
import kp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORK = kp.WORK
DONE = WORK / "border/done"
FOREST = WORK / "border/forest"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
URL = "https://geodaten.bayern.de/odd_data/laser/{}.laz"

# LAS 1.4 sets from the report that get a LAS 1.2 counterpart; *-sub3 follows from its parent
TARGETS = ["las14-r1", "las14-balanced", "las14-clean"]
# every set whose border rows the report may show (LAS 1.4 side / LAS 1.2 side)
SETS14 = ["kp_default", "las14-r1", "las14-balanced", "las14-clean", "las14-balanced-sub3"]
SETS12 = ["kp_default", "las12-r1", "las12-balanced", "las12-lessgreen", "las12-clean", "las12-detail",
          "las12-balanced-sub3", "las14-balanced"]
KEEP_LAZ = {"567_5528", "568_5528", "567_5529", "568_5529"}  # Würzburg block: e2e shots


def sets() -> dict:
    return json.loads((WORK / "sets.json").read_text())


def ov(name: str) -> dict:
    return {} if name == "kp_default" else sets()[name]


def split(name: str) -> str:
    return "holdout" if sorted(border.blocks()).index(name) % 3 == 2 else "train"


# --------------------------------------------------------------------------------------------
# prepare


def download(tile: str) -> None:
    f = WORK / f"laz/{tile}.laz"
    if f.exists():
        return
    tmp = f.with_suffix(".part")
    for attempt in range(5):
        r = subprocess.run(["curl", "-sSf", "--retry", "3", "-o", str(tmp), URL.format(tile)])
        if r.returncode == 0:
            tmp.rename(f)
            return
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"download {tile} failed")


def site_tiles() -> set[str]:
    return {t for s in kp.sites().values() for t in s["core"] + s["halo"]}


def prepare() -> None:
    DONE.mkdir(parents=True, exist_ok=True)
    todo = [(n, b) for n, b in border.blocks().items() if not (DONE / n).exists()]
    keep = site_tiles()
    ahead: dict[str, threading.Thread] = {}

    def fetch(b):
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(download, [t for t in b["core"] if not kp.xyz_path(t).exists()]))

    for i, (name, b) in enumerate(todo):
        for n2, b2 in todo[i:i + 2]:  # download one block ahead
            if n2 not in ahead:
                ahead[n2] = threading.Thread(target=fetch, args=(b2,))
                ahead[n2].start()
        ahead[name].join()
        t0 = time.time()
        kp.prepare(name, site_def=b, processes=4)
        t1 = time.time()
        jobs = [(t, s) for t in b["las14"] for s in SETS14] + [(t, s) for t in b["las12"] for s in SETS12]
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(lambda j: kp.run_stage(j[0], "vege", ov(j[1]), threads=4), jobs))
        for t in b["las14"]:
            if t not in keep:
                kp.xyz_path(t).unlink(missing_ok=True)
        for t in b["core"]:
            if t not in keep and t not in KEEP_LAZ:
                (WORK / f"laz/{t}.laz").unlink(missing_ok=True)
        (DONE / name).write_text("")
        print(f"{name}: prepare {t1 - t0:.0f}s, runs {time.time() - t1:.0f}s", flush=True)


# --------------------------------------------------------------------------------------------
# OSM forest


def forest() -> None:
    import requests
    from pyproj import Transformer
    from shapely.geometry import LineString, Polygon, box, mapping
    from shapely.ops import linemerge, polygonize, unary_union

    FOREST.mkdir(parents=True, exist_ok=True)
    to_ll = Transformer.from_crs(25832, 4326, always_xy=True)
    to_m = Transformer.from_crs(4326, 25832, always_xy=True)
    for name, b in border.blocks().items():
        p = FOREST / f"{name}.json"
        if p.exists():
            continue
        xs = [int(t.split("_")[0]) for t in b["core"]]
        ys = [int(t.split("_")[1]) for t in b["core"]]
        w, s = to_ll.transform(min(xs) * 1000 - 100, min(ys) * 1000 - 100)
        e, n = to_ll.transform(max(xs) * 1000 + 1100, max(ys) * 1000 + 1100)
        q = f"""[out:json][timeout:120];
(way["landuse"="forest"]({s},{w},{n},{e}); way["natural"="wood"]({s},{w},{n},{e});
 relation["landuse"="forest"]({s},{w},{n},{e}); relation["natural"="wood"]({s},{w},{n},{e}););
out geom;"""
        for attempt in range(8):
            try:
                r = requests.post(OVERPASS[attempt % len(OVERPASS)], data={"data": q}, timeout=180,
                                  headers={"User-Agent": "mapant-bayern parameter study"})
                r.raise_for_status()
                data = r.json()
                break
            except requests.RequestException as ex:
                print(f"  overpass retry ({ex})", flush=True)
                time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError("overpass failed")

        def line(g):
            return [to_m.transform(pt["lon"], pt["lat"]) for pt in g]

        polys = []
        for el in data["elements"]:
            if el["type"] == "way" and "geometry" in el and len(el["geometry"]) > 3:
                c = line(el["geometry"])
                if c[0] == c[-1]:
                    polys.append(Polygon(c).buffer(0))
            elif el["type"] == "relation":
                outer = [LineString(line(m["geometry"])) for m in el.get("members", [])
                         if m.get("role") == "outer" and "geometry" in m]
                inner = [LineString(line(m["geometry"])) for m in el.get("members", [])
                         if m.get("role") == "inner" and "geometry" in m]
                o = unary_union([pg.buffer(0) for pg in polygonize(linemerge(outer))]) if outer else None
                if o is None or o.is_empty:
                    continue
                if inner:
                    o = o.difference(unary_union([pg.buffer(0) for pg in polygonize(linemerge(inner))]))
                polys.append(o)
        x0, y0 = min(xs) * 1000, min(ys) * 1000
        geom = (unary_union(polys) if polys else Polygon()).intersection(box(x0, y0, x0 + 2000, y0 + 2000))
        p.write_text(json.dumps(mapping(geom)))
        print(f"{name}: forest {geom.area / 4e6:.0%} of block", flush=True)
        time.sleep(5)


# --------------------------------------------------------------------------------------------
# block statistics

_masks: dict[str, np.ndarray] = {}


def forest_mask(tile: str, block: str, res: float = 2.0) -> np.ndarray:
    key = f"{block}/{tile}"
    if key not in _masks:
        from affine import Affine
        from rasterio.features import rasterize
        from shapely.geometry import shape

        g = shape(json.loads((FOREST / f"{block}.json").read_text()))
        x, y = (int(v) * 1000 for v in tile.split("_"))
        n = int(1000 / res)
        tf = Affine(res, 0, x, 0, -res, y + 1000)
        _masks[key] = (rasterize([(g, 1)], out_shape=(n, n), transform=tf, fill=0, dtype=np.uint8) > 0
                       if not g.is_empty else np.zeros((n, n), bool))
    return _masks[key]


def side_stats(tiles: list[str], dirs: list[Path], block: str) -> dict:
    """p = shares of [white, 406, 408, 410, open] in forest; edges = boundary px per forest px."""
    cnt = np.zeros(5)
    edges = 0.0
    area = 0
    lut = np.array([0, 0, 4, 4, 1, 2, 3], np.uint8)  # class raster -> 0 white 1..3 green 4 open
    for t, d in zip(tiles, dirs):
        c = lut[border.tile_classes(t, d)]
        m = forest_mask(t, block)
        cnt += np.bincount(c[m], minlength=5)[:5]
        area += int(m.sum())
        eh = (c[:, 1:] != c[:, :-1]) & m[:, 1:] & m[:, :-1]
        ev = (c[1:, :] != c[:-1, :]) & m[1:, :] & m[:-1, :]
        edges += eh.sum() + ev.sum()
    return dict(p=(cnt / max(area, 1)).tolist(), edges=edges / max(area, 1), forest_px=area)


def usable(stats14: dict, stats12: dict, min_px: int = 40_000) -> bool:
    # >= 0.16 km² forest in each strip (2 m pixels)
    return stats14["forest_px"] >= min_px and stats12["forest_px"] >= min_px


def dist(p14: np.ndarray, p12: np.ndarray, e14: float, e12: float) -> float:
    d = p14 - p12
    emd = np.abs(np.cumsum(d[:4])[:3]).sum()
    return float(emd + abs(d[4]) + 0.2 * abs(math.log(max(e14, 1e-6) / max(e12, 1e-6))))


def mismatch(s14: dict[str, dict], s12: dict[str, dict], names: list[str]) -> dict:
    names = [n for n in names if usable(s14[n], s12[n])]
    P14 = np.array([s14[n]["p"] for n in names])
    P12 = np.array([s12[n]["p"] for n in names])
    L = np.array([math.log(max(s14[n]["edges"], 1e-6) / max(s12[n]["edges"], 1e-6)) for n in names])
    d = (P14 - P12).mean(0)
    systematic = float(np.abs(np.cumsum(d[:4])[:3]).sum() + abs(d[4]) + 0.2 * abs(L.mean()))
    per_block = float(np.mean([dist(P14[i], P12[i], s14[n]["edges"], s12[n]["edges"])
                               for i, n in enumerate(names)]))
    lv = np.array([0, 1, 2, 3])

    def level(P):
        return (P[:, :4] * lv).sum(1) / np.maximum(P[:, :4].sum(1), 1e-6)

    return dict(objective=systematic + 0.3 * per_block, systematic=systematic, per_block=per_block,
                green_step=float((P14[:, 1:4].sum(1) - P12[:, 1:4].sum(1)).mean()),
                level_step=float((level(P14) - level(P12)).mean()),
                open_step=float(d[4]), edge_logratio=float(L.mean()), n=len(names))


# The comparison uses a strip of STRIP m on each side of the generation border, where the two
# generations meet on the map. The LAS 1.2 strip is rendered from a cropped point cloud (both LAS
# 1.2 tiles' points within the strip + kp's 127 m buffer, work/cache/strip/<block>.xyz.bin), which
# makes a trial about three times faster than two whole tiles; the LAS 1.4 strip is cut from the
# whole-tile runs.
STRIP = 300
BUF = 127
XYZ_DTYPE = np.dtype([("x", "<f8"), ("y", "<f8"), ("z", "<f4"), ("c", "u1"), ("n", "u1"), ("r", "u1"), ("p", "u1")])


def strip_box(name: str, side: str) -> tuple[int, int, int, int]:
    b = border.blocks()[name]
    x0 = min(int(t.split("_")[0]) for t in b["core"]) * 1000
    y0 = min(int(t.split("_")[1]) for t in b["core"]) * 1000
    first = b[side][0]
    if name.endswith("h"):  # columns: the border is the vertical line x0 + 1000
        low = int(first.split("_")[0]) * 1000 == x0
        return (x0 + 1000 - STRIP, y0, x0 + 1000, y0 + 2000) if low else (x0 + 1000, y0, x0 + 1000 + STRIP, y0 + 2000)
    low = int(first.split("_")[1]) * 1000 == y0
    return (x0, y0 + 1000 - STRIP, x0 + 2000, y0 + 1000) if low else (x0, y0 + 1000, x0 + 2000, y0 + 1000 + STRIP)


def strip_xyz(name: str) -> None:
    """Both LAS 1.2 tiles' points in the strip + buffer, each point once."""
    out = kp.xyz_path(name, "strip")
    if out.exists():
        return
    bx0, by0, bx1, by1 = strip_box(name, "las12")
    bx0, by0, bx1, by1 = bx0 - BUF, by0 - BUF, bx1 + BUF, by1 + BUF
    ts = border.blocks()[name]["las12"]
    sq = [(int(t.split("_")[0]) * 1000, int(t.split("_")[1]) * 1000) for t in ts]

    def dist(x, y, s):
        dx = np.maximum(np.maximum(s[0] - x, 0), x - (s[0] + 1000))
        dy = np.maximum(np.maximum(s[1] - y, 0), y - (s[1] + 1000))
        return np.hypot(dx, dy)

    parts = []
    for i, t in enumerate(ts):
        a = np.memmap(kp.xyz_path(t), dtype=XYZ_DTYPE, mode="r", offset=12)
        p = np.asarray(a[(a["x"] >= bx0) & (a["x"] < bx1) & (a["y"] >= by0) & (a["y"] < by1)])
        ox, oy = np.floor(p["x"] / 1000) * 1000, np.floor(p["y"] / 1000) * 1000
        own = (ox == sq[i][0]) & (oy == sq[i][1])
        mine = own.copy()
        other = np.ones(len(p), bool)
        for j, s_ in enumerate(sq):
            other &= ~((ox == s_[0]) & (oy == s_[1]))
        # a buffer point of a tile outside the pair: from the nearer of the two tiles only
        d = [dist(p["x"], p["y"], s_) for s_ in sq]
        nearest = np.argmin(np.stack(d), axis=0) == i
        mine |= other & nearest
        parts.append(p[mine])
    pts = np.concatenate(parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        f.write(b"XYZB")
        f.write(np.uint64(len(pts)).tobytes())
        f.write(pts.tobytes())
    tmp.rename(out)


def classes_box(run: Path, box: tuple[int, int, int, int], res: float = 2.0) -> np.ndarray:
    """Class raster (as border.tile_classes) of one run's layers over a box."""
    from affine import Affine
    from rasterio.features import rasterize

    import score

    x0, y0, x1, y1 = box
    shape = (int((y1 - y0) / res), int((x1 - x0) / res))
    tf = Affine(res, 0, x0, 0, -res, y1)
    shapes = [(f["geometry"], 3) for f in score._read(run / "yellow.geojson")]
    shapes += [(f["geometry"], score.VEG_CODE.get(str(f["properties"].get("isom")), 5))
               for f in score._read(run / "vegetation.geojson")]
    if not shapes:
        return np.ones(shape, np.uint8)
    return rasterize(shapes, out_shape=shape, transform=tf, fill=1, dtype=np.uint8)


_fmask: dict = {}


def forest_box(block: str, box: tuple[int, int, int, int], res: float = 2.0) -> np.ndarray:
    key = (block, box)
    if key not in _fmask:
        from affine import Affine
        from rasterio.features import rasterize
        from shapely.geometry import shape

        g = shape(json.loads((FOREST / f"{block}.json").read_text()))
        x0, y0, x1, y1 = box
        sh = (int((y1 - y0) / res), int((x1 - x0) / res))
        _fmask[key] = (rasterize([(g, 1)], out_shape=sh, transform=Affine(res, 0, x0, 0, -res, y1), fill=0,
                                 dtype=np.uint8) > 0) if not g.is_empty else np.zeros(sh, bool)
    return _fmask[key]


def box_stats(pieces: list[tuple[Path, tuple]], block: str) -> dict:
    """side_stats over (run, box) pieces: p = shares of [white, 406, 408, 410, open] in forest."""
    cnt = np.zeros(5)
    edges = 0.0
    area = 0
    lut = np.array([0, 0, 4, 4, 1, 2, 3], np.uint8)
    for run, box in pieces:
        c = lut[classes_box(run, box)]
        m = forest_box(block, box)
        cnt += np.bincount(c[m], minlength=5)[:5]
        area += int(m.sum())
        eh = (c[:, 1:] != c[:, :-1]) & m[:, 1:] & m[:, :-1]
        ev = (c[1:, :] != c[:-1, :]) & m[1:, :] & m[:-1, :]
        edges += eh.sum() + ev.sum()
    return dict(p=(cnt / max(area, 1)).tolist(), edges=edges / max(area, 1), forest_px=area)


def stats_for(name: str, side: str, overrides: dict, names: list[str], workers: int = 4) -> dict[str, dict]:
    """Per block: statistics of `side`'s strip, rendered with `overrides`."""
    bl = border.blocks()
    if side == "las12":  # one run of the cropped strip cloud per block
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(strip_xyz, names))
        with ThreadPoolExecutor(workers) as ex:
            dirs = list(ex.map(lambda n: kp.run_stage(n, "vege", overrides, variant="strip", threads=4), names))
        return {n: box_stats([(d, strip_box(n, side))], n) for n, d in zip(names, dirs)}
    jobs = [(n, t) for n in names for t in bl[n][side]]
    with ThreadPoolExecutor(workers) as ex:
        dirs = list(ex.map(lambda j: kp.run_stage(j[1], "vege", overrides, threads=4), jobs))
    dm = dict(zip(jobs, dirs))
    out = {}
    for n in names:
        sx0, sy0, sx1, sy1 = strip_box(n, side)
        pieces = []
        for t in bl[n][side]:  # the strip's part inside each tile, from that tile's own run
            tx, ty = int(t.split("_")[0]) * 1000, int(t.split("_")[1]) * 1000
            box = (max(sx0, tx), max(sy0, ty), min(sx1, tx + 1000), min(sy1, ty + 1000))
            if box[0] < box[2] and box[1] < box[3]:
                pieces.append((dm[(n, t)], box))
        out[n] = box_stats(pieces, n)
    return out


def target_stats() -> dict[str, dict[str, dict]]:
    p = WORK / "border/targets_strip.json"
    cache = json.loads(p.read_text()) if p.exists() else {}
    names = list(border.blocks())
    for s in SETS14:
        if s not in cache or set(cache[s]) != set(names):
            cache[s] = stats_for(s, "las14", ov(s), names)
    p.write_text(json.dumps(cache))
    return cache


# --------------------------------------------------------------------------------------------
# search


def fixed_keys(target: str) -> dict:
    """Everything but the green keys comes from the target's LAS 1.2 sibling (yellow, cliffs)."""
    import optimize

    base = ov("las12-r1" if target == "las14-r1" else "las12-balanced")
    green = set(optimize.space_green(optuna.trial.FixedTrial(SEED_PARAMS)).keys())
    return {k: v for k, v in base.items() if k not in green}


# a valid point in the green space (only used to list its keys)
SEED_PARAMS = dict(z_lo=1, z1=2, z2_d=1, z3_d=1, f2=0.5, f3=0.3, t_low=0.02, t_high=0.02, s1=0.3, s2_d=0.5,
                   s3_d=1, greendetectsize=3, greenground=0.9, greenhigh=2, topweight=0.8,
                   pointvolumefactor=0.1, firstandlastreturnasground=3, firstandlastreturnfactor=1,
                   lastreturnfactor=1, groundboxsize=1, medianboxsize_half=4, medianboxsize2_half=2,
                   vegesimplify=1)


def search(trials: int, workers: int) -> None:
    import optimize

    tstats = target_stats()
    train = [n for n in border.blocks() if split(n) == "train"]
    studies = {}
    for tg in TARGETS:
        st = optuna.create_study(study_name=f"match12s-{tg}", storage=optimize.storage(), direction="minimize",
                                 sampler=optuna.samplers.TPESampler(multivariate=True, seed=1 + TARGETS.index(tg), n_startup_trials=15),
                                 load_if_exists=True)
        studies[tg] = st
    # seeds: the green params of every earlier LAS 1.2 study's chosen trials and of the LAS 1.4 targets
    seeds = []
    for study_name in ("green-full-r2-las12", "green-full-r2-las14"):
        st = optuna.load_study(study_name=study_name, storage=optimize.storage())
        ch = json.loads((ROOT / "results/choices.json").read_text())
        nums = {v["trial"] for k, v in ch.items() if k.startswith("green-")}
        for t in st.trials:
            if t.number in nums and t.params:
                seeds.append(t.params)
    r1 = optuna.load_study(study_name="green-full-las12", storage=optimize.storage()) \
        if "green-full-las12" in optuna.get_all_study_names(optimize.storage()) else None
    if r1 is not None:
        seeds += [t.params for t in r1.best_trials[:3] if t.params]

    def run(params: dict, fixed: dict) -> dict:
        o = {**fixed, **optimize.space_green(optuna.trial.FixedTrial(params))}
        s12 = stats_for("trial", "las12", o, train, workers)
        return {tg: mismatch(tstats[tg], s12, train) for tg in TARGETS}, s12, o

    i = 0
    while True:
        tg = TARGETS[i % len(TARGETS)]
        st = studies[tg]
        # a study's own trials (every trial is also shared with the other studies)
        def own(s):
            return len([t for t in s.trials if t.state == optuna.trial.TrialState.COMPLETE
                        and "shared_from" not in t.user_attrs])
        n_done = own(st)
        if all(own(s) >= trials for s in studies.values()):
            break
        i += 1
        if n_done >= trials:
            continue
        if n_done == 0 and seeds and tg == TARGETS[0]:  # the others get these via sharing
            for p in seeds:
                st.enqueue_trial(p, skip_if_exists=True)
        t0 = time.time()
        trial = st.ask()
        fixed = fixed_keys(tg)
        params_o = optimize.space_green(trial)  # registers the distributions
        try:
            res, s12, o = run(trial.params, fixed)
        except RuntimeError as ex:
            print("failed:", ex, flush=True)
            st.tell(trial, state=optuna.trial.TrialState.FAIL)
            continue
        trial.set_user_attr("overrides", o)
        trial.set_user_attr("all", res)
        st.tell(trial, res[tg]["objective"])
        # the same LAS 1.2 renders scored against the other targets: share them with those studies
        for other in TARGETS:
            if other == tg:
                continue
            # the fixed keys differ between targets in cliff keys only, which the vege stage ignores
            studies[other].add_trial(optuna.trial.create_trial(
                params=trial.params, distributions=trial.distributions, value=res[other]["objective"],
                user_attrs={"overrides": {**fixed_keys(other), **params_o}, "all": res, "shared_from": tg}))
        print(f"[{tg}] #{trial.number} " + " ".join(f"{k[6:]}={v['objective']:.3f}" for k, v in res.items())
              + f" green_step={res[tg]['green_step']:+.3f} ({time.time() - t0:.0f}s)", flush=True)


def choose() -> None:
    """Per target: the trial with the lowest training mismatch -> las12-match-<target>, + holdout."""
    import choose_sets
    import optimize

    tstats = target_stats()
    bl = border.blocks()
    hold = [n for n in bl if split(n) == "holdout"]
    train = [n for n in bl if split(n) == "train"]
    all_sets = sets()
    out, table = {}, []
    for tg in TARGETS:
        st = optuna.load_study(study_name=f"match12s-{tg}", storage=optimize.storage())
        best = min((t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE), key=lambda t: t.value)
        o = best.user_attrs["overrides"]
        name = "las12-match-" + tg.removeprefix("las14-")
        out[name] = o
        if tg == "las14-balanced":
            out[name + "-sub3"] = choose_sets.subshades(o, 3)
        print(f"{name}: {tg} trial {best.number}, train objective {best.value:.3f}", flush=True)
    all_sets.update(out)
    (WORK / "sets.json").write_text(json.dumps(all_sets, indent=1))
    # mismatch table: every LAS 1.2 set against every LAS 1.4 target, train and holdout blocks
    s12s = {}
    for s12 in SETS12 + list(out):
        s12s[s12] = stats_for(s12, "las12", ov(s12), list(bl))
    for s14 in SETS14:
        for s12, st12 in s12s.items():
            for part, names in (("train", train), ("holdout", hold)):
                table.append(dict(las14=s14, las12=s12, blocks=part, **mismatch(tstats[s14], st12, names)))
    import pandas as pd

    df = pd.DataFrame(table)
    df.to_csv(ROOT / "results/match12.csv", index=False)
    (WORK / "border/s12_stats.json").write_text(json.dumps(s12s))
    for tg in TARGETS + ["las14-balanced-sub3"]:
        print(df[(df.las14 == tg)].pivot(index="las12", columns="blocks", values="objective").round(3)
              .sort_values("train").to_string(), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--trials", type=int, default=150)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.cmd == "prepare":
        prepare()
    elif a.cmd == "forest":
        forest()
    elif a.cmd == "targets":
        ts = target_stats()
        for s in SETS14:
            print(s, {k: round(float(np.mean([v["p"][i] for v in ts[s].values()])), 3)
                      for i, k in enumerate(["white", "406", "408", "410", "open"])})
    elif a.cmd == "search":
        search(a.trials, a.workers)
    elif a.cmd == "choose":
        choose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
