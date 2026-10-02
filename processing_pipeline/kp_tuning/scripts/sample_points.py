#!/usr/bin/env python3
"""
Step 1b of the batch-effect check: point-level statistics of a sample of tiles.

The header says how a delivery was packaged; what karttapullautin's vegetation actually depends on
is how the laser saw the forest. Two campaigns with the same header can differ in season (leaf-on
vs. leaf-off), sensor (returns per pulse, penetration) or classification, and kp's green comes from
exactly that: the share of returns between ground and canopy relative to all returns. So for a
sample of tiles -- stratified over the header groups, forest tiles first -- this reads every point
and records:

  acquisition   date range from GPS time (adjusted standard GPS time only; week time has no date),
                month -> leaf-on (May-Oct) or leaf-off
  structure     points/m², pulses/m², returns per pulse, share of pulses with >= 2 returns
  canopy        on 2 m cells with vegetation over 3 m: returns per pulse, share of returns below
                0.5 m (ground reached through the canopy), share between 0.5 and 3 m (the
                undergrowth kp turns into green)
  classes       share of points per ASPRS class; whether low/medium/high vegetation (3/4/5) are used
  sensor        |scan angle| p95, intensity p50/p99 (8 vs 16 bit scaling)

    sample_points.py --config region.yaml [--per-group 4] [--by las_version,point_format] [--tiles a,b]

Output: <results>/points.parquet. Downloads the sampled tiles to <work>/laz (kept for later steps).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

GPS_EPOCH = dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)


def stats(t: str) -> dict:
    import laspy

    f = common.download(t)
    las = laspy.read(f)
    n = len(las.points)
    x0, y0, x1, y1 = common.tiles().bounds(t)
    area = (x1 - x0) * (y1 - y0)
    x, y, z = np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)
    inside = (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
    rn = np.asarray(las.return_number)
    nr = np.asarray(las.number_of_returns)
    cl = np.asarray(las.classification)
    first = rn == 1
    out: dict = dict(id=t, n_points=n, density=inside.sum() / area, pulse_density=(first & inside).sum() / area,
                     returns_per_pulse=n / max(first.sum(), 1), multi_share=float((nr[first] >= 2).mean()) if first.any() else np.nan)
    # acquisition date (bit 0 of the global encoding: adjusted standard GPS time = GPS s - 1e9)
    ge = las.header.global_encoding
    adjusted = bool(getattr(ge, "gps_time_type", 0)) if not isinstance(ge, int) else bool(ge & 1)
    gt = np.asarray(las.gps_time) if "gps_time" in las.point_format.dimension_names else None
    if gt is not None and adjusted and len(gt):
        q = np.percentile(gt, [1, 50, 99])
        days = [GPS_EPOCH + dt.timedelta(seconds=float(v) + 1e9) for v in q]
        out.update(acq_start=days[0].date().isoformat(), acq_median=days[1].date().isoformat(),
                   acq_end=days[2].date().isoformat(), acq_month=days[1].month,
                   leaf_on=bool(5 <= days[1].month <= 10), acq_span_days=(days[2] - days[0]).days)
    else:
        out.update(acq_start=None, acq_median=None, acq_end=None, acq_month=np.nan, leaf_on=None,
                   acq_span_days=np.nan, gps_week_time=gt is not None)
    # classes
    h = np.bincount(cl, minlength=32)[:32] / max(n, 1)
    for c in (1, 2, 3, 4, 5, 6, 7, 9, 17, 18):
        out[f"cls_{c}"] = float(h[c])
    out["veg_classes"] = bool(h[3] + h[4] + h[5] > 0.001)
    full = np.bincount(cl) / max(n, 1)
    top = np.argsort(full)[::-1][:6]
    out["classes_top"] = ",".join(f"{c}:{full[c]:.2f}" for c in top if full[c] >= 0.005)
    # canopy structure on 2 m cells: ground from class 2 (min z per cell, gaps filled from the
    # nearest ground cell), height above it per point
    res = 2.0
    ci = np.clip(((x - x0) / res).astype(int), 0, int((x1 - x0) / res) - 1)
    ri = np.clip(((y - y0) / res).astype(int), 0, int((y1 - y0) / res) - 1)
    W, H = int((x1 - x0) / res), int((y1 - y0) / res)
    g = cl == 2
    if g.sum() > 1000:
        from scipy import ndimage as ndi

        dtm = np.full((H, W), np.inf)
        np.minimum.at(dtm, (ri[g], ci[g]), z[g])
        miss = ~np.isfinite(dtm)
        if miss.any():
            _, (iy, ix) = ndi.distance_transform_edt(miss, return_indices=True)
            dtm = dtm[iy, ix]
        hag = z - dtm[ri, ci]
        top = np.full((H, W), -np.inf)
        np.maximum.at(top, (ri, ci), hag)
        canopy_cell = (top > 3.0)[ri, ci] & inside
        firsts = canopy_cell & first
        nf = max(int(firsts.sum()), 1)
        out.update(canopy_cover=float((top > 3.0).mean()),
                   canopy_returns_per_pulse=float(canopy_cell.sum() / nf),
                   canopy_ground_share=float((canopy_cell & (hag < 0.5)).sum() / nf),
                   canopy_low_share=float((canopy_cell & (hag >= 0.5) & (hag < 3.0)).sum() / nf),
                   canopy_multi_share=float((nr[firsts] >= 2).mean()) if firsts.any() else np.nan)
    if "scan_angle" in las.point_format.dimension_names:
        sa = np.abs(np.asarray(las.scan_angle, dtype=float) * (0.006 if las.header.version.minor >= 4 else 1.0))
    elif "scan_angle_rank" in las.point_format.dimension_names:
        sa = np.abs(np.asarray(las.scan_angle_rank, dtype=float))
    else:
        sa = None
    if sa is not None and len(sa):
        out["scan_angle_p95"] = float(np.percentile(sa, 95))
    it = np.asarray(las.intensity, dtype=float)
    if len(it):
        out["intensity_p50"], out["intensity_p99"] = (float(v) for v in np.percentile(it, [50, 99]))
    return out


def pick(per_group: int, by: list[str]) -> list[str]:
    """A stratified sample: per header group, the most forested tiles (by multi-return share)."""
    sv = pd.read_parquet(common.results() / "survey.parquet")
    sv = sv[sv.get("error", pd.Series(index=sv.index, dtype=object)).isna()] if "error" in sv else sv
    picks = []
    for _, g in sv.groupby(by, dropna=False):
        g = g[g.multi_share.notna()]
        if g.empty:
            continue
        # forest tiles (top third by multi-return share), spread out: every k-th of them
        f = g[g.multi_share >= g.multi_share.quantile(0.67)].sort_values(["min_x", "min_y"])
        step = max(len(f) // per_group, 1)
        picks += list(f.id.iloc[::step][:per_group])
    return picks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common.add_config_arg(ap)
    ap.add_argument("--per-group", type=int, default=4)
    ap.add_argument("--by", default="las_version,point_format,software,creation_year",
                    help="header columns that define the strata")
    ap.add_argument("--tiles", default="", help="explicit tile ids instead of a sample")
    ap.add_argument("--jobs", type=int, default=3, help="tiles read in parallel (memory: ~1-2 GB each)")
    ap.add_argument("--keep-laz", action="store_true", help="keep the downloaded tiles")
    args = ap.parse_args()
    common.set_config(args.config)

    todo = args.tiles.split(",") if args.tiles else pick(args.per_group, args.by.split(","))
    out_p = common.results() / "points.parquet"
    old = pd.read_parquet(out_p) if out_p.exists() else pd.DataFrame(columns=["id"])
    todo = [t for t in todo if t not in set(old.id)]
    print(f"{len(todo)} tiles to sample", flush=True)

    def one(t):
        had = common.laz_path(t).exists()
        try:
            r = stats(t)
        except Exception as e:  # noqa: BLE001
            r = dict(id=t, error=repr(e))
        if not had and not args.keep_laz:
            common.laz_path(t).unlink(missing_ok=True)
        print(t, {k: r.get(k) for k in ("acq_median", "returns_per_pulse", "canopy_low_share", "error") if k in r}, flush=True)
        return r

    with ThreadPoolExecutor(args.jobs) as ex:
        rows = list(ex.map(one, todo))
    df = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    df.to_parquet(out_p)
    print(f"{len(df)} tiles -> {out_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
