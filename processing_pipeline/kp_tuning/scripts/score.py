"""
Score kp's vegetation output for a site against the reference, at perception scale.

Both are compared on the reference's 1 m grid, inside the site's core tiles and the reference's
mask, in 10 m cells (each the majority area class) -- the size of detail a runner reads off a
1:10 000 map -- rather than pixel by pixel. Pixel agreement rewards speckle that nobody can read.

  green_ba        balanced accuracy of green (any shade) vs. white, over reference forest cells
  green_kappa     quadratic-weighted kappa over {white, 406, 408, 410}, reference forest cells
  green_bias      kp green share / reference green share (1 is ideal; >1 kp draws more green)
  open_f1/ba      open land (401/403) vs. forest
  open_bias       kp open share / reference open share
  speckle         kp green patches < 100 m² per km² (lower is better)
  boundary_ratio  kp / reference green-white boundary length (1 is ideal)
  readability     -|log boundary_ratio| (0 is ideal; the search maximises it)
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from affine import Affine
from rasterio.features import rasterize
from scipy import ndimage as ndi
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

VEG_CODE = {"406": 4, "408": 5, "410": 6}


@dataclass
class Ref:
    veg: np.ndarray
    mask: np.ndarray
    tf: Affine


@lru_cache(maxsize=32)
def load_ref(site: str, core: tuple[str, ...]) -> Ref:
    d = np.load(common.work() / f"ref/{site}.npz")
    tf = Affine(*d["transform"])
    shift = common.work() / f"ref/{site}_shift.json"
    if shift.exists():
        dx, dy = json.loads(shift.read_text())["shift"]
        tf = Affine.translation(dx, dy) * tf
    mask = d["mask"].copy()
    T = common.tiles()
    mask &= rasterize([box(*T.bounds(t)) for t in core], out_shape=mask.shape, transform=tf, fill=0,
                      default_value=1).astype(bool)
    return Ref(d["veg"], mask, tf)


def read(path: Path) -> list[dict]:
    return json.loads(path.read_text())["features"] if path.exists() else []


def _window(ref: Ref, tile: str):
    x0, y0, x1, y1 = common.tiles().bounds(tile)
    inv = ~ref.tf
    c0, r0 = inv * (x0, y1)
    c1, r1 = inv * (x1, y0)
    r0, r1 = max(int(round(r0)), 0), min(int(round(r1)), ref.veg.shape[0])
    c0, c1 = max(int(round(c0)), 0), min(int(round(c1)), ref.veg.shape[1])
    return None if r0 >= r1 or c0 >= c1 else (slice(r0, r1), slice(c0, c1))


def veg_shapes(run: Path) -> list:
    """kp's layers as (geometry, class) in drawing order: yellow, then vegetation over it."""
    shapes = [(f["geometry"], 3) for f in read(run / "yellow.geojson")]
    shapes += [(f["geometry"], VEG_CODE.get(str(f["properties"].get("isom")), 5)) for f in read(run / "vegetation.geojson")]
    return shapes


def kp_layers(ref: Ref, tile_dirs: dict[str, Path]) -> dict[str, np.ndarray]:
    """kp's vegetation on the reference grid, each tile only inside its own tile square."""
    out = np.zeros(ref.veg.shape, np.uint8)
    for tile, d in tile_dirs.items():
        win = _window(ref, tile)
        if win is None:
            continue
        rs, cs = win
        tf = ref.tf * Affine.translation(cs.start, rs.start)
        shp = (rs.stop - rs.start, cs.stop - cs.start)
        s = veg_shapes(d)
        out[win] = rasterize(s, out_shape=shp, transform=tf, fill=1, dtype=np.uint8) if s else 1
    return {"veg": out}


def _blocks(a: np.ndarray, n: int) -> np.ndarray:
    h, w = a.shape[0] // n * n, a.shape[1] // n * n
    return a[:h, :w].reshape(h // n, n, w // n, n).swapaxes(1, 2).reshape(h // n, w // n, n * n)


def _cell_class(veg, mask, n):
    b, m = _blocks(veg, n), _blocks(mask, n)
    counts = np.stack([((b == c) & m).sum(-1) for c in range(7)], -1)
    counts[..., 0] = 0
    return counts.argmax(-1), m.mean(-1) >= 0.8


def _ba(pred, truth) -> float:
    p, n = truth.sum(), (~truth).sum()
    if p == 0 or n == 0:
        return float("nan")
    return float(((pred & truth).sum() / p + (~pred & ~truth).sum() / n) / 2)


def _f1(pred, truth) -> float:
    d = pred.sum() + truth.sum()
    return float(2 * (pred & truth).sum() / d) if d else float("nan")


def _qwk(a, b, k: int = 4) -> float:
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
    ordinal = np.array([0, 0, 0, 0, 1, 2, 3])
    out = dict(
        green_ba=_ba(k_green[forest], r_green[forest]),
        green_bias=float(k_green[forest].mean() / max(r_green[forest].mean(), 1e-6)),
        green_kappa=_qwk(ordinal[rc[forest]], ordinal[kc[forest]]),
        open_f1=_f1(k_open, r_open), open_ba=_ba(k_open, r_open),
        open_bias=float(k_open.mean() / max(r_open.mean(), 1e-6)), n_cells=int(ok.sum()))
    km2 = mask.sum() / 1e6
    kg = np.isin(kp["veg"], [4, 5, 6]) & mask
    lab, _ = ndi.label(kg)
    out["speckle"] = float((np.bincount(lab.ravel())[1:] < 100).sum() / max(km2, 1e-6))
    rg = np.isin(ref.veg, [4, 5, 6]) & mask
    bnd = lambda g: np.count_nonzero(g[1:, :] != g[:-1, :]) + np.count_nonzero(g[:, 1:] != g[:, :-1])  # noqa: E731
    out["boundary_ratio"] = float(bnd(kg) / max(bnd(rg), 1))
    out["readability"] = -abs(math.log(max(out["boundary_ratio"], 1e-3)))
    return out


def score(site: str, core: list[str], tile_dirs: dict[str, Path]) -> dict:
    ref = load_ref(site, tuple(core))
    return score_vege(ref, kp_layers(ref, tile_dirs))
