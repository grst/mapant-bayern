#!/usr/bin/env python3
"""
Make the groups look alike where they meet: search a parameter set for group G whose map, on G's
side of a G|R border, looks like what R's chosen set draws on the other side.

Use it when one group (R) has clearly better reference support and the others' sets are shakier,
or when the seams between groups stay visible with each group's own best set. In Bavaria
(R = LAS 1.4, G = LAS 1.2) it cut the forest mismatch across the border by 20-48 % on held-out
blocks, mostly by making both sides equally patchy, at a small cost in agreement with G's maps.

    seams.py select  --config c.yaml --ref R --other G [--n 50 --min-km 9]   # blocks -> <results>/seams_G.yaml
    seams.py prepare --config c.yaml --other G --targets R-balanced,...      # clouds, R-side renders, free disk
    seams.py forest  --config c.yaml --other G                               # OSM forest per block
    seams.py search  --config c.yaml --other G --targets ... --trials 50
    seams.py choose  --config c.yaml --other G --targets ...                 # -> sets.json "G-match-<target>"

Blocks are 2 x 2 tiles straddling the border (two tiles of each group), in forest (both sides in
the top third of their group's multi-return share), at least --min-km apart, areas listed in the
config under `areas:` left out (they are for the visual check). Every third block (by name) is
held out of the search.

Only forest counts (OSM landuse=forest / natural=wood), in a STRIP m wide strip on each side of
the border. Per strip: shares of white / 406 / 408 / 410 / open, and class-boundary length per
forest area (patchiness). Mismatch of a G set against an R set over the blocks:
  systematic  EMD over the ordered levels white < 406 < 408 < 410 of the mean share difference,
              + |mean open difference| + 0.2 |mean log boundary-density ratio|
  per_block   the same per block, averaged
  objective   systematic + 0.3 per_block  (minimised)
G's strip is rendered from a cropped point cloud (both G tiles' points in the strip + kp's 127 m
buffer; 96-99 % pixel agreement with whole-tile runs, ~2x faster). One TPE study per target; every
render is scored against all targets and shared with the other studies.

Where G's point cloud simply lacks the information (Würzburg: 0.9 M vs 20 M third-or-later
returns per km²) no parameter set closes the seam; the per-block table shows such blocks.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import kp  # noqa: E402
import optimize  # noqa: E402
import score  # noqa: E402
import sets as setsmod  # noqa: E402

STRIP = 300
BUF = 127
XYZ = np.dtype([("x", "<f8"), ("y", "<f8"), ("z", "<f4"), ("c", "u1"), ("n", "u1"), ("r", "u1"), ("p", "u1")])
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]


def blocks_path(other: str) -> Path:
    return common.results() / f"seams_{other}.yaml"


def blocks(other: str) -> dict:
    return yaml.safe_load(blocks_path(other).read_text())


def split(name: str, bl: dict) -> str:
    return "holdout" if sorted(bl).index(name) % 3 == 2 else "train"


def groups() -> dict[str, str]:
    return dict(pd.read_csv(common.results() / "groups.csv", dtype=str).values)


# --------------------------------------------------------------------------------------------
# select


def excluded_boxes() -> list[tuple]:
    """Index-CRS boxes of the comparison areas (kept out of the blocks)."""
    from pyproj import Transformer

    out = []
    tf = Transformer.from_crs(4326, common.tiles().crs, always_xy=True)
    for a in (common.cfg().get("areas") or {}).values():
        if "lonlat" in a:
            w, s, e, n = a["lonlat"]
            xs, ys = zip(*[tf.transform(x, y) for x in (w, e) for y in (s, n)])
            out.append((min(xs), min(ys), max(xs), max(ys)))
        elif "box" in a:
            out.append(tuple(a["box"]))
    return out


def select(ref: str, other: str, n: int, min_km: float, min_rank: float) -> None:
    T, G = common.tiles(), groups()
    sv = pd.read_parquet(common.results() / "survey.parquet", columns=["id", "multi_share"]).dropna()
    sv["g"] = sv.id.map(G)
    sv["rank"] = sv.groupby("g").multi_share.rank(pct=True)
    rank = dict(zip(sv.id, sv["rank"]))
    ex = excluded_boxes()
    cands = []
    for t in T.ids():
        for o in ("h", "v"):
            a = [t, T.offset(t, 0, 1)] if o == "h" else [t, T.offset(t, 1, 0)]
            b = [T.offset(t, 1, 0), T.offset(t, 1, 1)] if o == "h" else [T.offset(t, 0, 1), T.offset(t, 1, 1)]
            if None in a + b:
                continue
            ga, gb = {G.get(x) for x in a}, {G.get(x) for x in b}
            if len(ga) != 1 or len(gb) != 1 or ga == gb or {ga.pop(), gb.pop()} != {ref, other}:
                continue
            sc = min(rank.get(x, 0) for x in a + b)
            x0, y0, _, _ = T.bounds(t)
            if any(bx0 - 2 * T.size <= x0 <= bx1 + T.size and by0 - 2 * T.size <= y0 <= by1 + T.size
                   for bx0, by0, bx1, by1 in ex):
                continue
            cands.append((sc, t, o, a, b))
    cands.sort(key=lambda c: -c[0])
    chosen = []
    for sc, t, o, a, b in cands:
        if sc < min_rank or len(chosen) >= n:
            break
        x0, y0, _, _ = T.bounds(t)
        if all(math.hypot(x0 - cx, y0 - cy) > min_km * 1000 for cx, cy, *_ in chosen):
            chosen.append((x0, y0, t, o, a, b, sc))
    out = {}
    for x0, y0, t, o, a, b, sc in chosen:
        side_ref, side_other = (a, b) if G[a[0]] == ref else (b, a)
        out[f"b_{t}_{o}"] = dict(core=a + b, halo=[], ref=side_ref, other=side_other, orient=o, forest_rank=round(sc, 2))
    blocks_path(other).write_text(yaml.safe_dump(out, sort_keys=False))
    print(f"{len(out)} blocks between {ref} and {other} ({len(cands)} candidates) -> {blocks_path(other)}")


# --------------------------------------------------------------------------------------------
# geometry of a block


def block_origin(b: dict) -> tuple[float, float]:
    T = common.tiles()
    bs = [T.bounds(t) for t in b["core"]]
    return min(x[0] for x in bs), min(x[1] for x in bs)


def strip_box(b: dict, side: str) -> tuple[float, float, float, float]:
    T = common.tiles()
    s = T.size
    x0, y0 = block_origin(b)
    tx, ty, _, _ = T.bounds(b[side][0])
    if b["orient"] == "h":  # columns: border is the vertical line x0 + s
        return (x0 + s - STRIP, y0, x0 + s, y0 + 2 * s) if tx == x0 else (x0 + s, y0, x0 + s + STRIP, y0 + 2 * s)
    return (x0, y0 + s - STRIP, x0 + 2 * s, y0 + s) if ty == y0 else (x0, y0 + s, x0 + 2 * s, y0 + s + STRIP)


def strip_cloud(name: str, b: dict) -> None:
    """Both G tiles' points in the strip + buffer, each point once (tile clouds overlap by 127 m)."""
    out = kp.xyz_path(name, "strip")
    if out.exists():
        return
    T = common.tiles()
    bx0, by0, bx1, by1 = strip_box(b, "other")
    bx0, by0, bx1, by1 = bx0 - BUF, by0 - BUF, bx1 + BUF, by1 + BUF
    ts = b["other"]
    sq = [T.bounds(t) for t in ts]

    def dist(x, y, s):
        dx = np.maximum(np.maximum(s[0] - x, 0), x - s[2])
        dy = np.maximum(np.maximum(s[1] - y, 0), y - s[3])
        return np.hypot(dx, dy)

    parts = []
    for i, t in enumerate(ts):
        a = np.memmap(kp.xyz_path(t), dtype=XYZ, mode="r", offset=12)
        p = np.asarray(a[(a["x"] >= bx0) & (a["x"] < bx1) & (a["y"] >= by0) & (a["y"] < by1)])
        owner = np.full(len(p), -1)
        for j, s in enumerate(sq):
            owner[(p["x"] >= s[0]) & (p["x"] < s[2]) & (p["y"] >= s[1]) & (p["y"] < s[3])] = j
        nearest = np.argmin(np.stack([dist(p["x"], p["y"], s) for s in sq]), axis=0)
        parts.append(p[(owner == i) | ((owner == -1) & (nearest == i))])
    pts = np.concatenate(parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        f.write(b"XYZB")
        f.write(np.uint64(len(pts)).tobytes())
        f.write(pts.tobytes())
    tmp.rename(out)


# --------------------------------------------------------------------------------------------
# statistics


def classes_box(run: Path, box, res: float = 2.0) -> np.ndarray:
    from affine import Affine
    from rasterio.features import rasterize

    x0, y0, x1, y1 = box
    shape = (int(round((y1 - y0) / res)), int(round((x1 - x0) / res)))
    s = score.veg_shapes(run)
    return rasterize(s, out_shape=shape, transform=Affine(res, 0, x0, 0, -res, y1), fill=1, dtype=np.uint8) \
        if s else np.ones(shape, np.uint8)


_fmask: dict = {}
_flock = threading.Lock()


def forest_box(name: str, box, res: float = 2.0) -> np.ndarray:
    key = (name, box)
    with _flock:
        if key in _fmask:
            return _fmask[key]
    from affine import Affine
    from rasterio.features import rasterize
    from shapely.geometry import shape as shp

    g = shp(json.loads((common.work() / f"seams/forest/{name}.json").read_text()))
    x0, y0, x1, y1 = box
    sh = (int(round((y1 - y0) / res)), int(round((x1 - x0) / res)))
    m = (rasterize([(g, 1)], out_shape=sh, transform=Affine(res, 0, x0, 0, -res, y1), fill=0, dtype=np.uint8) > 0) \
        if not g.is_empty else np.zeros(sh, bool)
    with _flock:
        _fmask[key] = m
    return m


def box_stats(pieces, name: str) -> dict:
    cnt, edges, area = np.zeros(5), 0.0, 0
    lut = np.array([0, 0, 4, 4, 1, 2, 3], np.uint8)  # class -> 0 white, 1-3 green, 4 open
    for run, box in pieces:
        c = lut[classes_box(run, box)]
        m = forest_box(name, box)
        cnt += np.bincount(c[m], minlength=5)[:5]
        area += int(m.sum())
        edges += ((c[:, 1:] != c[:, :-1]) & m[:, 1:] & m[:, :-1]).sum() + ((c[1:] != c[:-1]) & m[1:] & m[:-1]).sum()
    return dict(p=(cnt / max(area, 1)).tolist(), edges=edges / max(area, 1), forest_px=area)


def stats_for(other: str, side: str, overrides: dict, names: list[str], workers: int = 4) -> dict:
    bl = blocks(other)
    T = common.tiles()
    if side == "other":
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(lambda n: strip_cloud(n, bl[n]), names))
        with ThreadPoolExecutor(workers) as ex:
            dirs = list(ex.map(lambda n: kp.run_stage(n, "vege", overrides, variant="strip"), names))
        return {n: box_stats([(d, strip_box(bl[n], "other"))], n) for n, d in zip(names, dirs)}
    jobs = [(n, t) for n in names for t in bl[n][side]]
    with ThreadPoolExecutor(workers) as ex:
        dirs = dict(zip(jobs, ex.map(lambda j: kp.run_stage(j[1], "vege", overrides), jobs)))
    out = {}
    for n in names:
        sx0, sy0, sx1, sy1 = strip_box(bl[n], side)
        pieces = []
        for t in bl[n][side]:
            tx0, ty0, tx1, ty1 = T.bounds(t)
            b = (max(sx0, tx0), max(sy0, ty0), min(sx1, tx1), min(sy1, ty1))
            if b[0] < b[2] and b[1] < b[3]:
                pieces.append((dirs[(n, t)], b))
        out[n] = box_stats(pieces, n)
    return out


def dist(p_ref, p_oth, e_ref, e_oth) -> float:
    d = np.asarray(p_ref) - np.asarray(p_oth)
    return float(np.abs(np.cumsum(d[:4])[:3]).sum() + abs(d[4]) + 0.2 * abs(math.log(max(e_ref, 1e-6) / max(e_oth, 1e-6))))


def mismatch(s_ref: dict, s_oth: dict, names: list[str], min_px: int = 40_000) -> dict:
    names = [n for n in names if s_ref[n]["forest_px"] >= min_px and s_oth[n]["forest_px"] >= min_px]
    if not names:
        return dict(objective=np.nan, n=0)
    P1, P2 = np.array([s_ref[n]["p"] for n in names]), np.array([s_oth[n]["p"] for n in names])
    L = np.array([math.log(max(s_ref[n]["edges"], 1e-6) / max(s_oth[n]["edges"], 1e-6)) for n in names])
    d = (P1 - P2).mean(0)
    systematic = float(np.abs(np.cumsum(d[:4])[:3]).sum() + abs(d[4]) + 0.2 * abs(L.mean()))
    per_block = float(np.mean([dist(s_ref[n]["p"], s_oth[n]["p"], s_ref[n]["edges"], s_oth[n]["edges"]) for n in names]))
    return dict(objective=systematic + 0.3 * per_block, systematic=systematic, per_block=per_block,
                green_step=float((P1[:, 1:4].sum(1) - P2[:, 1:4].sum(1)).mean()), open_step=float(d[4]),
                edge_logratio=float(L.mean()), n=len(names))


def target_stats(other: str, targets: list[str]) -> dict:
    p = common.work() / f"seams/targets_{other}.json"
    cache = json.loads(p.read_text()) if p.exists() else {}
    names = list(blocks(other))
    allsets = setsmod.load_sets()
    for t in targets:
        if t not in cache or set(cache[t]) != set(names):
            cache[t] = stats_for(other, "ref", allsets[t], names)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache))
    return cache


# --------------------------------------------------------------------------------------------
# prepare, forest


def prepare(other: str, targets: list[str]) -> None:
    """Point clouds per block; the R side rendered with the targets, then its clouds deleted."""
    bl = blocks(other)
    allsets = setsmod.load_sets()
    keep = {t for s in kp.sites().values() for t in s["core"] + s["halo"]}
    done_dir = common.work() / "seams/done"
    done_dir.mkdir(parents=True, exist_ok=True)
    for name, b in bl.items():
        if (done_dir / name).exists():
            continue
        t0 = time.time()
        kp.prepare(name, b)
        jobs = [(t, s) for t in b["ref"] for s in targets] + [(t, "kp_default") for t in b["other"]]
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(lambda j: kp.run_stage(j[0], "vege", allsets.get(j[1], {})), jobs))
        for t in b["ref"]:
            if t not in keep:
                kp.xyz_path(t).unlink(missing_ok=True)
        for t in b["core"]:
            if t not in keep:
                common.laz_path(t).unlink(missing_ok=True)
        (done_dir / name).write_text(",".join(targets))
        print(f"{name}: {time.time() - t0:.0f}s ({common.free_gb():.0f} GB free)", flush=True)


def forest(other: str) -> None:
    import requests
    from pyproj import Transformer
    from shapely.geometry import LineString, Polygon, box, mapping
    from shapely.ops import linemerge, polygonize, unary_union

    d = common.work() / "seams/forest"
    d.mkdir(parents=True, exist_ok=True)
    T = common.tiles()
    to_ll = Transformer.from_crs(T.crs, 4326, always_xy=True)
    to_m = Transformer.from_crs(4326, T.crs, always_xy=True)
    for name, b in blocks(other).items():
        p = d / f"{name}.json"
        if p.exists():
            continue
        x0, y0 = block_origin(b)
        x1, y1 = x0 + 2 * T.size, y0 + 2 * T.size
        w, s = to_ll.transform(x0 - 100, y0 - 100)
        e, n = to_ll.transform(x1 + 100, y1 + 100)
        q = f"""[out:json][timeout:120];
(way["landuse"="forest"]({s},{w},{n},{e}); way["natural"="wood"]({s},{w},{n},{e});
 relation["landuse"="forest"]({s},{w},{n},{e}); relation["natural"="wood"]({s},{w},{n},{e}););
out geom;"""
        for attempt in range(8):
            try:
                r = requests.post(OVERPASS[attempt % 2], data={"data": q}, timeout=180,
                                  headers={"User-Agent": common.user_agent()})
                r.raise_for_status()
                data = r.json()
                break
            except requests.RequestException as ex:
                print(f"  overpass retry ({ex})", flush=True)
                time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError("overpass failed")
        line = lambda g: [to_m.transform(pt["lon"], pt["lat"]) for pt in g]  # noqa: E731
        polys = []
        for el in data["elements"]:
            if el["type"] == "way" and "geometry" in el and len(el["geometry"]) > 3:
                c = line(el["geometry"])
                if c[0] == c[-1]:
                    polys.append(Polygon(c).buffer(0))
            elif el["type"] == "relation":
                mem = el.get("members", [])
                outer = [LineString(line(m["geometry"])) for m in mem if m.get("role") == "outer" and "geometry" in m]
                inner = [LineString(line(m["geometry"])) for m in mem if m.get("role") == "inner" and "geometry" in m]
                o = unary_union([pg.buffer(0) for pg in polygonize(linemerge(outer))]) if outer else None
                if o is None or o.is_empty:
                    continue
                if inner:
                    o = o.difference(unary_union([pg.buffer(0) for pg in polygonize(linemerge(inner))]))
                polys.append(o)
        geom = (unary_union(polys) if polys else Polygon()).intersection(box(x0, y0, x1, y1))
        p.write_text(json.dumps(mapping(geom)))
        print(f"{name}: forest {geom.area / (x1 - x0) / (y1 - y0):.0%}", flush=True)
        time.sleep(5)


# --------------------------------------------------------------------------------------------
# search, choose


def match_name(other: str, target: str) -> str:
    return f"{other}-match-{target}"


def search(other: str, targets: list[str], trials: int, workers: int) -> None:
    bl = blocks(other)
    train = [n for n in bl if split(n, bl) == "train"]
    ts = target_stats(other, targets)
    allsets = setsmod.load_sets()
    green_keys = set(optimize.space_green(optuna.trial.FixedTrial(SEED)).keys())
    # the matched set keeps the open-land keys of G's own set, else of the target
    own = allsets.get(f"{other}-balanced", {})

    def fixed_for(t):
        src = own or allsets[t]
        return {k: v for k, v in src.items() if k not in green_keys and not k.startswith(("cliff", "knoll"))}

    studies = {t: optuna.create_study(study_name=f"seams-{other}-{t}", storage=optimize.storage(), direction="minimize",
                                      sampler=optuna.samplers.TPESampler(multivariate=True, seed=1 + i, n_startup_trials=15),
                                      load_if_exists=True) for i, t in enumerate(targets)}
    seeds = list(json.loads(optimize.SEEDS.read_text())["green_params"].values()) if optimize.SEEDS.exists() else []

    def own_n(s):
        return len([x for x in s.trials if x.state == optuna.trial.TrialState.COMPLETE and "shared_from" not in x.user_attrs])

    i = 0
    while not all(own_n(s) >= trials for s in studies.values()):
        tg = targets[i % len(targets)]
        i += 1
        st = studies[tg]
        if own_n(st) >= trials:
            continue
        if own_n(st) == 0 and tg == targets[0]:
            for p in seeds:
                st.enqueue_trial(p, skip_if_exists=True)
        t0 = time.time()
        trial = st.ask()
        g = optimize.space_green(trial)
        o = {**fixed_for(tg), **g}
        try:
            s_oth = stats_for(other, "other", o, train, workers)
        except RuntimeError as ex:
            print("failed:", ex, flush=True)
            st.tell(trial, state=optuna.trial.TrialState.FAIL)
            continue
        res = {t: mismatch(ts[t], s_oth, train) for t in targets}
        trial.set_user_attr("overrides", o)
        trial.set_user_attr("all", res)
        st.tell(trial, res[tg]["objective"])
        for t in targets:  # the same render, scored for the other targets
            if t != tg:
                studies[t].add_trial(optuna.trial.create_trial(
                    params=trial.params, distributions=trial.distributions, value=res[t]["objective"],
                    user_attrs={"overrides": {**fixed_for(t), **g}, "all": res, "shared_from": tg}))
        print(f"[{tg}] #{trial.number} " + " ".join(f"{t}={r['objective']:.3f}" for t, r in res.items())
              + f" green_step={res[tg]['green_step']:+.3f} ({time.time() - t0:.0f}s)", flush=True)


# a valid point of the green space (to list its keys)
SEED = dict(z_lo=1, z1=2, z2_d=1, z3_d=1, f2=0.5, f3=0.3, t_low=0.02, t_high=0.02, s1=0.3, s2_d=0.5, s3_d=1,
            greendetectsize=3, greenground=0.9, greenhigh=2, topweight=0.8, pointvolumefactor=0.1,
            firstandlastreturnasground=3, firstandlastreturnfactor=1, lastreturnfactor=1, groundboxsize=1,
            medianboxsize_half=4, medianboxsize2_half=2, vegesimplify=1)


def choose(other: str, targets: list[str]) -> None:
    bl = blocks(other)
    names = list(bl)
    parts = {"train": [n for n in names if split(n, bl) == "train"], "holdout": [n for n in names if split(n, bl) == "holdout"]}
    allsets = setsmod.load_sets()
    for tg in targets:
        st = optuna.load_study(study_name=f"seams-{other}-{tg}", storage=optimize.storage())
        best = min((t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE), key=lambda t: t.value)
        allsets[match_name(other, tg)] = best.user_attrs["overrides"]
        print(f"{match_name(other, tg)}: trial {best.number}, train mismatch {best.value:.3f}")
    setsmod.save_sets(allsets)
    ts = target_stats(other, targets)
    cand = [s for s in allsets if s.startswith(f"{other}-")] + ["kp_default"]
    rows, per_block = [], []
    for s in cand:
        so = stats_for(other, "other", allsets[s], names)
        for tg in targets:
            for part, ns in parts.items():
                rows.append(dict(target=tg, set=s, blocks=part, **mismatch(ts[tg], so, ns)))
            for n in names:
                g = lambda p: sum(p["p"][1:4])  # noqa: E731
                per_block.append(dict(target=tg, set=s, block=n, split=split(n, bl),
                                      green_ref=g(ts[tg][n]), green_other=g(so[n]),
                                      forest_px=min(ts[tg][n]["forest_px"], so[n]["forest_px"])))
    df = pd.DataFrame(rows)
    df.to_csv(common.results() / f"seams_{other}.csv", index=False)
    pd.DataFrame(per_block).to_csv(common.results() / f"seams_{other}_blocks.csv", index=False)
    for tg in targets:
        t = df[df.target == tg].pivot(index="set", columns="blocks", values="objective").sort_values("holdout")
        print(f"\nmismatch against {tg} (lower is better):\n{t.round(3).to_string()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["select", "prepare", "forest", "search", "choose"])
    common.add_config_arg(ap)
    ap.add_argument("--ref")
    ap.add_argument("--other", required=True)
    ap.add_argument("--targets", default="")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--min-km", type=float, default=9)
    ap.add_argument("--min-rank", type=float, default=0.45)
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    common.set_config(a.config)
    tg = [t for t in a.targets.split(",") if t]
    if a.cmd == "select":
        select(a.ref, a.other, a.n, a.min_km, a.min_rank)
    elif a.cmd == "prepare":
        prepare(a.other, tg)
    elif a.cmd == "forest":
        forest(a.other)
    elif a.cmd == "search":
        search(a.other, tg, a.trials, a.workers)
    else:
        choose(a.other, tg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
