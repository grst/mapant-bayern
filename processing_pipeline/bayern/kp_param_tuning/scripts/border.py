#!/usr/bin/env python3
"""
Consistency across the LAS 1.2 / LAS 1.4 generation border.

Where two point-cloud generations meet, the map should not change character at the tile edge. The
test uses 2x2 km blocks straddling the border: two tiles of one generation next to two of the
other, both sides mostly forest (by the share of multiple returns, ranked within each generation).
Each block is rendered with a parameter set, where every tile gets the set of its own generation
(or one set for all), and each side's vegetation is summarised:

  green share    green (406/408/410) area / non-open area
  green level    mean ISOM level over non-open area (0 white, 1 = 406, 2 = 408, 3 = 410)
  open share     yellow (401/403) area / total

Forest does change across any line, but not systematically with the point generation. So the
signed mean over many blocks of (LAS 1.4 side - LAS 1.2 side) estimates the generation step a
parameter set leaves in the map; the mean absolute step is its typical visible size.

    border.py select            # pick blocks -> border.yaml, list of laz to download
    border.py prepare           # cache the point clouds (kp batch per block, no halo needed)
    border.py eval <set> ...    # sets from work/sets.json, "kp_default", or "gen:<las12 set>,<las14 set>"
    border.py steps             # the table again from results/border.csv
    border.py shots <label> <set> <block,...>   # production-path renders + screenshots
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
YAML = ROOT / "border.yaml"
OUT = ROOT / "results/border.csv"
# Würzburg north: the border the first map version shows most plainly
MUST = [(567, 5528, "v")]


# The Allgäu area rendered for the final visual comparison stays out of the blocks (test area).
EXCLUDE = (585, 5265, 608, 5292)


def select(n_spread: int = 20, min_score: float = 0.64, min_km: float = 25, extend: bool = False) -> None:
    """Pick blocks. extend=True keeps border.yaml's blocks and adds more (round 3: 50 in all)."""
    d = pd.read_parquet(ROOT / "results/density.parquet")
    d["x"], d["y"] = d.min_x // 1000, d.min_y // 1000
    d["ret"] = (d.n_second + d.n_third_plus) / d.n_first
    d["pct"] = d.groupby("las_version").ret.rank(pct=True)
    g = d.set_index(["x", "y"])
    v, pc = g.las_version.to_dict(), g.pct.to_dict()

    def block(x, y, o):
        a, b = ([(x, y), (x, y + 1)], [(x + 1, y), (x + 1, y + 1)]) if o == "h" else \
               ([(x, y), (x + 1, y)], [(x, y + 1), (x + 1, y + 1)])
        if not all(t in v for t in a + b):
            return None
        if len({v[t] for t in a}) != 1 or len({v[t] for t in b}) != 1 or v[a[0]] == v[b[0]]:
            return None
        return a, b, min(pc[t] for t in a + b)

    cands = []
    for (x, y) in v:
        for o in ("h", "v"):
            r = block(x, y, o)
            if r:
                cands.append((r[2], x, y, o))
    cands.sort(reverse=True)
    old = blocks() if extend else {}
    chosen = [(int(k[1:].split("_")[0]), int(k.split("_")[1][:-1]), k[-1]) for k in old] or list(MUST)
    ex0, ey0, ex1, ey1 = EXCLUDE
    for sc, x, y, o in cands:
        if sc < min_score or len(chosen) > n_spread:
            break
        if ex0 - 2 <= x <= ex1 + 1 and ey0 - 2 <= y <= ey1 + 1:
            continue
        if all(np.hypot(x - cx, y - cy) > min_km for cx, cy, _ in chosen):
            chosen.append((x, y, o))
    out = dict(old)
    for x, y, o in chosen:
        if f"b{x}_{y}{o}" in out:
            continue
        a, b, sc = block(x, y, o)
        lv = {f"{t[0]}_{t[1]}": float(v[t]) for t in a + b}
        side12, side14 = (a, b) if float(v[a[0]]) == 1.2 else (b, a)
        out[f"b{x}_{y}{o}"] = dict(
            core=[f"{t[0]}_{t[1]}" for t in a + b], halo=[],
            las12=[f"{t[0]}_{t[1]}" for t in side12], las14=[f"{t[0]}_{t[1]}" for t in side14],
            forest_rank=round(float(sc), 2), las_version=lv)
    YAML.write_text(yaml.safe_dump(out, sort_keys=False))
    need = [t for b in out.values() for t in b["core"] if not (kp.WORK / f"laz/{t}.laz").exists()]
    (kp.WORK / "border/laz_needed.txt").write_text(
        "".join(f"https://geodaten.bayern.de/odd_data/laser/{t}.laz\n" for t in need))
    print(f"{len(out)} blocks, {len(need)} tiles to download")


def blocks() -> dict:
    return yaml.safe_load(YAML.read_text())


def prepare(processes: int = 2) -> None:
    for name, b in blocks().items():
        kp.prepare(name, site_def=b, processes=processes)
        print(name, "prepared", flush=True)


def tile_classes(tile: str, run: Path, res: float = 2.0) -> np.ndarray:
    """Class raster of one tile inside its own square kilometre: 1 white, 3 open, 4/5/6 green."""
    from affine import Affine
    from rasterio.features import rasterize

    import score

    x, y = (int(v) * 1000 for v in tile.split("_"))
    n = int(1000 / res)
    tf = Affine(res, 0, x, 0, -res, y + 1000)
    shapes = [(f["geometry"], 3) for f in score._read(run / "yellow.geojson")]
    shapes += [(f["geometry"], score.VEG_CODE.get(str(f["properties"].get("isom")), 5))
               for f in score._read(run / "vegetation.geojson")]
    if not shapes:
        return np.ones((n, n), np.uint8)
    return rasterize(shapes, out_shape=(n, n), transform=tf, fill=1, dtype=np.uint8)


def summarise(cls: np.ndarray) -> dict:
    h = np.bincount(cls.ravel(), minlength=7) / cls.size
    rest = max(1 - h[2] - h[3], 1e-6)
    return dict(green_share=(h[4] + h[5] + h[6]) / rest,
                green_level=(h[4] + 2 * h[5] + 3 * h[6]) / rest,
                open_share=h[2] + h[3])


def resolve(name: str, sets: dict) -> tuple[dict, dict]:
    """(overrides for LAS 1.2 tiles, overrides for LAS 1.4 tiles)"""
    if name == "kp_default":
        return {}, {}
    if name.startswith("gen:"):
        a, b = name[4:].split(",")
        return resolve(a, sets)[0], resolve(b, sets)[1]
    return sets[name], sets[name]


def evaluate(names: list[str], workers: int = 4, threads: int = 4) -> pd.DataFrame:
    sets = json.loads((kp.WORK / "sets.json").read_text())
    rows = []
    for name in names:
        o12, o14 = resolve(name, sets)
        jobs = [(bn, t, o12 if b["las_version"][t] == 1.2 else o14)
                for bn, b in blocks().items() for t in b["core"]]
        with ThreadPoolExecutor(workers) as ex:
            dirs = list(ex.map(lambda j: kp.run_stage(j[1], "vege", j[2], threads=threads), jobs))
        dmap = {(bn, t): d for (bn, t, _), d in zip(jobs, dirs)}
        for bn, b in blocks().items():
            r = dict(set=name, block=bn)
            for side in ("las12", "las14"):
                s = summarise(np.concatenate([tile_classes(t, dmap[(bn, t)]) for t in b[side]]))
                r.update({f"{k}_{side}": v for k, v in s.items()})
            rows.append(r)
        print(name, "done", flush=True)
    df = pd.DataFrame(rows)
    old = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame()
    if len(old):
        old = old[~old.set.isin(names)]
    df = pd.concat([old, df], ignore_index=True)
    OUT.parent.mkdir(exist_ok=True)
    df.to_csv(OUT, index=False)
    return df


def steps(df: pd.DataFrame) -> pd.DataFrame:
    """Per set: signed mean and mean absolute step (LAS 1.4 side - LAS 1.2 side) over the blocks."""
    out = []
    for name, g in df.groupby("set", sort=False):
        r = dict(set=name, n=len(g))
        for k in ("green_share", "green_level", "open_share"):
            dlt = g[f"{k}_las14"] - g[f"{k}_las12"]
            r[f"{k}_step"] = dlt.mean()
            r[f"{k}_step_se"] = dlt.std() / np.sqrt(len(g))
            r[f"{k}_absstep"] = dlt.abs().mean()
        out.append(r)
    return pd.DataFrame(out)


def shots(label: str, name: str, which: list[str], zoom: float = 15.3) -> None:
    """Production-path render (e2e.py) of blocks, each tile with its generation's set; screenshot."""
    import e2e
    from pyproj import Transformer

    sets = json.loads((kp.WORK / "sets.json").read_text())
    o12, o14 = resolve(name, sets)
    to_ll = Transformer.from_crs(25832, 4326, always_xy=True)
    for bn in which:
        b = blocks()[bn]
        per_tile = {t: (o12 if b["las_version"][t] == 1.2 else o14) for t in b["core"]}
        d = e2e.render(f"border_{bn}", label, {}, site_def=b, tile_overrides=per_tile)
        xs = [int(t.split("_")[0]) for t in b["core"]]
        ys = [int(t.split("_")[1]) for t in b["core"]]
        lon, lat = to_ll.transform(min(xs) * 1000 + 1000, min(ys) * 1000 + 1000)
        print(e2e.screenshot(d, lon, lat, zoom, d / f"shot_z{zoom:g}.png"), flush=True)


def main() -> int:
    cmd = sys.argv[1]
    if cmd == "select":
        select()
    elif cmd == "extend":
        select(n_spread=int(sys.argv[2]), min_score=float(sys.argv[3]), min_km=float(sys.argv[4]), extend=True)
    elif cmd == "prepare":
        prepare()
    elif cmd == "eval":
        df = evaluate(sys.argv[2:])
        print(steps(df[df.set.isin(sys.argv[2:])]).round(3).to_string())
    elif cmd == "shots":
        shots(sys.argv[2], sys.argv[3], sys.argv[4].split(","))
    elif cmd == "steps":
        print(steps(pd.read_csv(OUT)).round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
