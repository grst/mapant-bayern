#!/usr/bin/env python3
"""
Simulate a sparser LiDAR campaign by dropping whole laser pulses.

A lower pulse density is not the same as dropping random points: every return of a dropped pulse
has to go, or the ratio of first to later returns -- which is what karttapullautin's vegetation
model reads -- would stay unchanged. Returns of one pulse share their GPS time, so a pulse is kept
when a hash of its GPS time falls below the kept fraction. The hash makes the choice identical in
every tile, so a pulse on a tile edge is not kept on one side and dropped on the other.

    thin_laz.py --fraction 0.5 --variant thin50 <site> [<site> ...]

Writes work/laz_<variant>/<tile>.laz for the site's core and halo tiles.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import laspy
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def keep_mask(gps_time: np.ndarray, fraction: float) -> np.ndarray:
    # splitmix64 of the float's bits: uniform on [0, 1) and identical for equal GPS times
    z = gps_time.astype(np.float64).view(np.uint64) + np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    z = z ^ (z >> np.uint64(31))
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53) < fraction


def thin(src: Path, dst: Path, fraction: float) -> str:
    if dst.exists():
        return f"{dst.name} cached"
    las = laspy.read(src)
    keep = keep_mask(np.asarray(las.gps_time), fraction)
    out = laspy.LasData(las.header)
    out.points = las.points[keep]
    tmp = dst.with_suffix(".tmp.laz")
    out.write(tmp, laz_backend=laspy.LazBackend.LazrsParallel)
    tmp.rename(dst)
    return f"{dst.name}: {len(las.points)} -> {keep.sum()} points ({keep.mean():.2f})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sites", nargs="+")
    ap.add_argument("--fraction", type=float, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()
    out_dir = ROOT / f"work/laz_{args.variant}"
    out_dir.mkdir(parents=True, exist_ok=True)
    sites = kp.sites()
    tiles = sorted({t for s in args.sites for t in sites[s]["core"] + sites[s]["halo"]})
    jobs = [(ROOT / f"work/laz/{t}.laz", out_dir / f"{t}.laz") for t in tiles
            if (ROOT / f"work/laz/{t}.laz").exists()]
    with ProcessPoolExecutor(args.jobs) as ex:
        for msg in ex.map(thin, [a for a, _ in jobs], [b for _, b in jobs], [args.fraction] * len(jobs)):
            print(msg, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
