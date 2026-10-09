"""
Score karttapullautin's vector output for a site against the reference map layers.

Everything is compared on the reference's 1 m grid, restricted to the site's core tiles and the
reference's valid mask, and then judged at a perception scale -- the size of detail a runner
reads off a 1:10 000 map -- rather than pixel by pixel:

  vegetation  10 m cells, each the majority area class
  undergrowth 20 m cells, present if >= 30 % of the cell carries stripes
  rock/cliffs 25 m cells
  knolls      point matching within 15 m

Metric names (all "higher is better" unless noted):

  green_ba        balanced accuracy of green (any shade) vs. white, over reference forest cells
  green_bias      kp green fraction / reference green fraction (1 is ideal)
  green_kappa     quadratic-weighted kappa of {white, 406, 408, 410} over reference forest cells
  open_f1, open_ba  open land (403, and 401 where the reference is not masked) vs. forest
  open_bias       kp open fraction / reference open fraction
  ug_f1, ug_ba, ug_bias
  speckle         kp green patches under 100 m2 per km2 (lower is better)
  boundary_ratio  kp / reference green-white boundary length (1 is ideal)
  cliff_precision, cliff_recall, cliff_f1   kp cliff cells vs. reference rock cells, one cell slack
  rock_spearman   rank correlation of kp cliff density and reference rock density per cell
  knoll_precision, knoll_recall, knoll_f1, knoll_ratio
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from affine import Affine
from rasterio.features import rasterize
from scipy import ndimage as ndi
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree
from scipy.stats import spearmanr
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "work/ref"

VEG_CODE = {"406": 4, "408": 5, "410": 6}


@dataclass
class Ref:
    veg: np.ndarray
    ug: np.ndarray
    rock: np.ndarray
    mask: np.ndarray
    knolls: np.ndarray
    tf: Affine


@lru_cache(maxsize=16)
def load_ref(site: str, core: tuple[str, ...]) -> Ref:
    d = np.load(REF / f"{site}.npz")
    tf = Affine(*d["transform"])
    shift = REF / f"{site}_shift.json"
    if shift.exists():
        dx, dy = json.loads(shift.read_text())["shift"]
        tf = Affine.translation(dx, dy) * tf
    mask = d["mask"].copy()
    # only the core tiles count
    core_geoms = [box(int(t.split("_")[0]) * 1000, int(t.split("_")[1]) * 1000,
                      int(t.split("_")[0]) * 1000 + 1000, int(t.split("_")[1]) * 1000 + 1000) for t in core]
    mask &= rasterize(core_geoms, out_shape=mask.shape, transform=tf, fill=0, default_value=1).astype(bool)
    kn = d["knolls"] + (np.array([tf.c, tf.f]) - d["transform"][[2, 5]])
    return Ref(d["veg"], d["ug"], d["rock"].astype(np.float32), mask, kn, tf)


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text())["features"] if path.exists() else []


def _tile_window(ref: Ref, tile: str) -> tuple[slice, slice] | None:
    """The reference-grid window a 1 km tile covers, or None if it is off the grid."""
    x, y = (int(v) * 1000 for v in tile.split("_"))
    inv = ~ref.tf
    c0, r0 = inv * (x, y + 1000)
    c1, r1 = inv * (x + 1000, y)
    r0, r1 = max(int(round(r0)), 0), min(int(round(r1)), ref.veg.shape[0])
    c0, c1 = max(int(round(c0)), 0), min(int(round(c1)), ref.veg.shape[1])
    if r0 >= r1 or c0 >= c1:
        return None
    return slice(r0, r1), slice(c0, c1)


def _burn(ref: Ref, win, shapes, fill=0, dtype=np.uint8, all_touched=False) -> np.ndarray:
    """Rasterise shapes onto just the window (kp's features extend 127 m past their tile)."""
    rs, cs = win
    tf = ref.tf * Affine.translation(cs.start, rs.start)
    shp = (rs.stop - rs.start, cs.stop - cs.start)
    if not shapes:
        return np.full(shp, fill, dtype)
    return rasterize(shapes, out_shape=shp, transform=tf, fill=fill, dtype=dtype, all_touched=all_touched)


def kp_layers(ref: Ref, tile_dirs: dict[str, dict[str, Path]]) -> dict[str, np.ndarray]:
    """
    Rasterise kp's layers onto the reference grid, each tile only inside its own square
    kilometre. `tile_dirs` maps tile -> stage -> run dir. Drawing order follows the style: yellow,
    then vegetation over it.
    """
    shp = ref.veg.shape
    stages = {s for st in tile_dirs.values() for s in st}
    out: dict[str, np.ndarray] = {}
    if "vege" in stages:
        out["veg"] = np.zeros(shp, np.uint8)
        out["ug"] = np.zeros(shp, bool)
    if "cliffs" in stages:
        out["cliffs"] = np.zeros(shp, np.float32)
    knolls = []
    for tile, st in tile_dirs.items():
        win = _tile_window(ref, tile)
        if "contours" in st:
            x, y = (int(v) * 1000 for v in tile.split("_"))
            for f in _read(st["contours"] / "dotknolls.geojson"):
                px, py = f["geometry"]["coordinates"][:2]
                if x <= px < x + 1000 and y <= py < y + 1000:
                    knolls.append((px, py))
        if win is None:
            continue
        if "vege" in st:
            d = st["vege"]
            shapes = [(f["geometry"], 3) for f in _read(d / "yellow.geojson")]
            shapes += [(f["geometry"], VEG_CODE.get(str(f["properties"].get("isom")), 5))
                       for f in _read(d / "vegetation.geojson")]
            out["veg"][win] = _burn(ref, win, shapes, fill=1)
            out["ug"][win] = _burn(ref, win, [(f["geometry"], 1) for f in _read(d / "undergrowth.geojson")])
        if "cliffs" in st:
            # the style draws cliffs 2.54 m wide; all_touched on 1 m pixels is ~2 px
            out["cliffs"][win] = _burn(ref, win, [(f["geometry"], 1) for f in _read(st["cliffs"] / "cliffs.geojson")],
                                       all_touched=True)
    if "contours" in stages:
        out["knolls"] = np.array(knolls, dtype=np.float64).reshape(-1, 2)
    return out


def _blocks(a: np.ndarray, n: int) -> np.ndarray:
    h, w = a.shape[0] // n * n, a.shape[1] // n * n
    return a[:h, :w].reshape(h // n, n, w // n, n).swapaxes(1, 2).reshape(h // n, w // n, n * n)


def _cell_class(veg: np.ndarray, mask: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Majority class per n x n cell, and which cells are mostly inside the mask."""
    b = _blocks(veg, n)
    m = _blocks(mask, n)
    counts = np.stack([((b == c) & m).sum(-1) for c in range(7)], -1)
    counts[..., 0] = 0
    return counts.argmax(-1), m.mean(-1) >= 0.8


def _ba(pred: np.ndarray, truth: np.ndarray) -> float:
    tp, tn = (pred & truth).sum(), (~pred & ~truth).sum()
    p, n = truth.sum(), (~truth).sum()
    if p == 0 or n == 0:
        return float("nan")
    return float((tp / p + tn / n) / 2)


def _f1(pred: np.ndarray, truth: np.ndarray) -> float:
    tp = (pred & truth).sum()
    d = pred.sum() + truth.sum()
    return float(2 * tp / d) if d else float("nan")


def _qwk(a: np.ndarray, b: np.ndarray, k: int = 4) -> float:
    if len(a) == 0:
        return float("nan")
    o = np.zeros((k, k))
    np.add.at(o, (a, b), 1)
    w = np.subtract.outer(np.arange(k), np.arange(k)) ** 2 / (k - 1) ** 2
    e = np.outer(o.sum(1), o.sum(0)) / o.sum()
    return float(1 - (w * o).sum() / max((w * e).sum(), 1e-9))


def score_vege(ref: Ref, kp: dict) -> dict:
    mask = ref.mask & (ref.veg > 0)
    rc, ok = _cell_class(ref.veg, mask, 10)
    kc, _ = _cell_class(kp["veg"], mask, 10)
    rc, kc = rc[ok], kc[ok]
    forest = np.isin(rc, [1, 4, 5, 6])
    r_green, k_green = np.isin(rc, [4, 5, 6]), np.isin(kc, [4, 5, 6])
    r_open, k_open = np.isin(rc, [2, 3]), np.isin(kc, [2, 3])
    ordinal = np.array([0, 0, 0, 0, 1, 2, 3])  # white/open -> 0
    out = dict(
        green_ba=_ba(k_green[forest], r_green[forest]),
        green_bias=float(k_green[forest].mean() / max(r_green[forest].mean(), 1e-6)),
        green_kappa=_qwk(ordinal[rc[forest]], ordinal[kc[forest]]),
        open_f1=_f1(k_open, r_open),
        open_ba=_ba(k_open, r_open),
        open_bias=float(k_open.mean() / max(r_open.mean(), 1e-6)),
        n_cells=int(ok.sum()),
    )
    # undergrowth at 20 m
    ub_r = _blocks(ref.ug & mask, 20).mean(-1) >= 0.3
    ub_k = _blocks(kp["ug"] & mask, 20).mean(-1) >= 0.3
    ok20 = _blocks(mask, 20).mean(-1) >= 0.8
    rf = np.isin(_cell_class(ref.veg, mask, 20)[0], [1, 4, 5, 6])  # forest cells only
    sel = ok20 & rf
    out.update(ug_f1=_f1(ub_k[sel], ub_r[sel]), ug_ba=_ba(ub_k[sel], ub_r[sel]),
               ug_bias=float(ub_k[sel].mean() / max(ub_r[sel].mean(), 1e-6)))
    # readability: speckle and boundary length, on the 1 m rasters inside the mask
    km2 = mask.sum() / 1e6
    kg = np.isin(kp["veg"], [4, 5, 6]) & mask
    lab, n = ndi.label(kg)
    sizes = np.bincount(lab.ravel())[1:]
    out["speckle"] = float((sizes < 100).sum() / max(km2, 1e-6))
    rg = np.isin(ref.veg, [4, 5, 6]) & mask

    def boundary(g):
        return (np.count_nonzero(g[1:, :] != g[:-1, :]) + np.count_nonzero(g[:, 1:] != g[:, :-1]))

    out["boundary_ratio"] = float(boundary(kg) / max(boundary(rg), 1))
    return out


def score_cliffs(ref: Ref, kp: dict) -> dict:
    mask = ref.mask
    ok = _blocks(mask, 25).mean(-1) >= 0.8
    r = _blocks(ref.rock * mask, 25).mean(-1)
    k = _blocks(kp["cliffs"] * mask, 25).mean(-1)
    r_rock, k_cliff = r >= 0.01, k >= 0.01
    r_near = ndi.binary_dilation(r_rock)
    k_near = ndi.binary_dilation(k_cliff)
    prec = float((k_cliff & r_near & ok).sum() / max((k_cliff & ok).sum(), 1))
    rec = float((r_rock & k_near & ok).sum() / max((r_rock & ok).sum(), 1))
    rho = spearmanr(r[ok], k[ok]).statistic if ok.sum() > 10 else float("nan")
    return dict(cliff_precision=prec, cliff_recall=rec,
                cliff_f1=2 * prec * rec / (prec + rec) if prec + rec else 0.0,
                rock_spearman=float(rho), cliff_density=float(k[ok].mean()), rock_density=float(r[ok].mean()))


def score_knolls(ref: Ref, kp: dict, tol: float = 15.0) -> dict:
    inv = ~ref.tf

    def inside(pts):
        if len(pts) == 0:
            return pts
        c, r = inv * (pts[:, 0], pts[:, 1])
        r, c = np.asarray(r).astype(int), np.asarray(c).astype(int)
        ok = (r >= 0) & (c >= 0) & (r < ref.mask.shape[0]) & (c < ref.mask.shape[1])
        ok[ok] = ref.mask[r[ok], c[ok]]
        return pts[ok]

    a, b = inside(kp["knolls"]), inside(ref.knolls)
    km2 = ref.mask.sum() / 1e6
    if len(a) == 0 or len(b) == 0:
        return dict(knoll_precision=0.0 if len(a) else float("nan"), knoll_recall=0.0, knoll_f1=0.0,
                    knoll_ratio=len(a) / max(len(b), 1), knolls_kp_km2=len(a) / km2, knolls_ref_km2=len(b) / km2)
    ta = cKDTree(a)
    pairs = ta.query_ball_tree(cKDTree(b), tol)
    rows, cols, cost = [], [], []
    for i, js in enumerate(pairs):
        for j in js:
            rows.append(i)
            cols.append(j)
            cost.append(np.hypot(*(a[i] - b[j])))
    matched = 0
    if rows:
        # Hungarian on the sparse candidate pairs
        ui, ri = np.unique(rows, return_inverse=True)
        uj, cj = np.unique(cols, return_inverse=True)
        m = np.full((len(ui), len(uj)), 1e6)
        m[ri, cj] = cost
        r_, c_ = linear_sum_assignment(m)
        matched = int((m[r_, c_] <= tol).sum())
    p, r = matched / len(a), matched / len(b)
    return dict(knoll_precision=p, knoll_recall=r, knoll_f1=2 * p * r / (p + r) if p + r else 0.0,
                knoll_ratio=len(a) / len(b), knolls_kp_km2=len(a) / km2, knolls_ref_km2=len(b) / km2)


def score(site: str, core: list[str], tile_dirs: dict[str, dict[str, Path]]) -> dict:
    ref = load_ref(site, tuple(core))
    kp = kp_layers(ref, tile_dirs)
    out = {}
    if "veg" in kp:
        out.update(score_vege(ref, kp))
    if "cliffs" in kp:
        out.update(score_cliffs(ref, kp))
    if "knolls" in kp:
        out.update(score_knolls(ref, kp))
    return out
