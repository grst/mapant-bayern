#!/usr/bin/env python3
"""
Step 1c of the batch-effect check: find the groups of tiles that need their own parameter set.

A batch effect is a property of the delivery (campaign, sensor, season, processing line, file
format) that changes the point cloud systematically and therefore the map, at an edge that has
nothing to do with the landscape. In Bavaria it was LAS 1.2 (2015-22, 1.4 returns/pulse) vs.
LAS 1.4 (2023-, 1.6 returns/pulse): kp's defaults drew the LAS 1.4 side ~13 points greener.

From survey.parquet (headers of all tiles) and, if present, points.parquet (point statistics of a
sample), this

  1. lists every header field that varies (>= 2 values with >= 0.5 % of the tiles each) and maps it;
  2. for each such field, measures the seams it forms between neighbouring tiles and how much the
     return structure (log returns per pulse, multi-return share) jumps across them compared with
     neighbours inside one value -- a ratio well above 1 along a long seam is a batch effect, a
     ratio near 1 is a label without consequence;
  3. compares the point-level statistics (season, canopy penetration, low-vegetation returns,
     classes) between the values of each field;
  4. writes groups.csv for a grouping (--group-by), the report batch/report.md and maps.

    batch_effects.py --config region.yaml [--group-by las_version] [--min-share 0.005]

Read the report, look at the maps, and decide the grouping yourself: fields that are only labels
(a software version string that changed mid-campaign without changing the points) should not split
the parameter sets; season or sensor changes inside one label should. Rerun with --group-by (any
columns of survey.parquet, or `none`) to write the groups the later steps use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

CATEGORICAL = ["las_version", "point_format", "software", "system_identifier", "creation_year", "scale_x",
               "scale_z", "max_return", "record_length", "global_encoding", "file_source_id"]
CONTINUOUS = ["pulse_density", "returns_per_pulse", "multi_share", "density"]
POINT_STATS = ["acq_median", "leaf_on", "returns_per_pulse", "multi_share", "canopy_returns_per_pulse",
               "canopy_ground_share", "canopy_low_share", "canopy_multi_share", "cls_1", "cls_3", "cls_4", "cls_5",
               "scan_angle_p95", "intensity_p99", "pulse_density"]


def neighbour_pairs(sv: pd.DataFrame) -> pd.DataFrame:
    """All east and north neighbour pairs of surveyed tiles."""
    T = common.tiles()
    idx = {t: i for i, t in enumerate(sv.id)}
    a, b = [], []
    for t in sv.id:
        for dx, dy in ((1, 0), (0, 1)):
            u = T.offset(t, dx, dy)
            if u in idx:
                a.append(idx[t])
                b.append(idx[u])
    return pd.DataFrame({"a": a, "b": b})


def seam_stats(sv: pd.DataFrame, pairs: pd.DataFrame, key: str) -> dict:
    va, vb = sv[key].to_numpy()[pairs.a], sv[key].to_numpy()[pairs.b]
    across = (va != vb) & ~(pd.isna(va) & pd.isna(vb))
    lr = np.log(sv.returns_per_pulse.to_numpy())
    d = np.abs(lr[pairs.a] - lr[pairs.b])
    ok = np.isfinite(d)
    within = d[ok & ~across]
    acr = d[ok & across]
    return dict(key=key, seam_km=float(across.sum() * common.tiles().size / 1000),
                jump_across=float(np.median(acr)) if len(acr) else np.nan,
                jump_within=float(np.median(within)) if len(within) else np.nan,
                ratio=float(np.median(acr) / max(np.median(within), 1e-6)) if len(acr) and len(within) else np.nan)


def plot_map(sv: pd.DataFrame, col: str, out: Path, categorical: bool) -> None:
    """The field as a raster, one pixel per tile."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    size = common.tiles().size
    ix = ((sv.min_x - sv.min_x.min()) / size).round().astype(int).to_numpy()
    iy = ((sv.min_y - sv.min_y.min()) / size).round().astype(int).to_numpy()
    grid = np.full((iy.max() + 1, ix.max() + 1), np.nan)
    ext = [sv.min_x.min() / 1000, (sv.min_x.min() + (ix.max() + 1) * size) / 1000,
           sv.min_y.min() / 1000, (sv.min_y.min() + (iy.max() + 1) * size) / 1000]
    fig, ax = plt.subplots(figsize=(8, 8))
    if categorical:
        vals = sv[col].astype(str)
        cats = list(vals.value_counts().index[:12])
        code = vals.map({c: i for i, c in enumerate(cats)}).fillna(len(cats)).to_numpy()
        grid[iy, ix] = code
        cmap = plt.get_cmap("tab10" if len(cats) <= 10 else "tab20")
        colors = [cmap(i % cmap.N) for i in range(len(cats))] + [(0.8, 0.8, 0.8, 1)]
        ax.imshow(grid, origin="lower", extent=ext, cmap=ListedColormap(colors), vmin=-0.5, vmax=len(cats) + 0.5,
                  interpolation="nearest")
        for i, c in enumerate(cats):
            ax.scatter([], [], marker="s", color=colors[i], label=f"{c} ({(vals == c).sum()})")
        if (code == len(cats)).any():
            ax.scatter([], [], marker="s", color=colors[-1], label=f"other ({(code == len(cats)).sum()})")
        ax.legend(fontsize=8, loc="best")
    else:
        v = sv[col].astype(float).to_numpy()
        lo, hi = np.nanpercentile(v, [2, 98])
        grid[iy, ix] = np.clip(v, lo, hi)
        im = ax.imshow(grid, origin="lower", extent=ext, cmap="viridis", interpolation="nearest")
        fig.colorbar(im, ax=ax, shrink=0.7, label=col)
    ax.set_title(col)
    ax.set_xlabel("km E")
    ax.set_ylabel("km N")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def straight_edges(sv: pd.DataFrame, fields: list[str], col: str = "multi_share", min_km: float = 8,
                   factor: float = 2.5) -> pd.DataFrame:
    """
    Long straight runs along the tile grid where `col` jumps much more than between neighbours in
    general. Campaign and delivery blocks follow the grid; landscape does not. Finds batch
    boundaries no header field marks.
    """
    size = common.tiles().size
    ix = ((sv.min_x - sv.min_x.min()) / size).round().astype(int).to_numpy()
    iy = ((sv.min_y - sv.min_y.min()) / size).round().astype(int).to_numpy()
    g = np.full((iy.max() + 1, ix.max() + 1), np.nan)
    g[iy, ix] = sv[col].astype(float).to_numpy()
    gi = np.full(g.shape, -1)
    gi[iy, ix] = np.arange(len(sv))
    cat = {f: sv[f].astype(str).to_numpy() for f in fields}
    base = np.nanmedian(np.abs(np.concatenate([np.diff(g, axis=0).ravel(), np.diff(g, axis=1).ravel()])))
    rows = []
    run_min = max(int(round(min_km * 1000 / size)), 3)
    for axis, name in ((1, "x"), (0, "y")):  # jumps across vertical lines (x = const), then horizontal
        # signed differences: a delivery boundary shifts the value the same way all along it, a
        # landscape edge goes both ways (fields next to forest on either side)
        d = np.diff(g, axis=axis)
        # a delivery boundary is a level shift: 3-tile bands on either side differ as much as the
        # adjacent tiles do. A river or forest band one or two tiles wide steps up and down again.
        gg = g if axis == 1 else g.T  # columns: across the line
        band = lambda k0, k1: np.nanmean(np.stack([gg[:, k] if 0 <= k < gg.shape[1] else np.full(gg.shape[0], np.nan)  # noqa: E731
                                                   for k in range(k0, k1)]), axis=0)
        d3 = np.stack([band(li + 1, li + 4) - band(li - 2, li + 1) for li in range(gg.shape[1] - 1)], axis=1)
        d = d if axis == 1 else d.T  # rows: positions along the line; columns: line index
        for li in range(d.shape[1]):
            v = pd.Series(d[:, li]).rolling(run_min, min_periods=run_min // 2, center=True).median().to_numpy()
            v3 = pd.Series(d3[:, li]).rolling(run_min, min_periods=run_min // 2, center=True).median().to_numpy()
            hot = (np.abs(v) > factor * base) & (np.sign(v3) == np.sign(v)) & (np.abs(v3) >= 0.7 * np.abs(v))
            i = 0
            while i < len(hot):
                if hot[i]:
                    j = i
                    while j < len(hot) and hot[j]:
                        j += 1
                    if j - i >= run_min:
                        # which header fields change across this run (for most of its pairs)
                        if axis == 1:
                            a_, b_ = gi[i:j, li], gi[i:j, li + 1]
                        else:
                            a_, b_ = gi[li, i:j], gi[li + 1, i:j]
                        ok = (a_ >= 0) & (b_ >= 0)
                        expl = [f for f in fields if ok.any() and (cat[f][a_[ok]] != cat[f][b_[ok]]).mean() >= 0.5]
                        coord = (sv.min_x.min() if axis == 1 else sv.min_y.min()) + (li + 1) * size
                        start = (sv.min_y.min() if axis == 1 else sv.min_x.min()) + i * size
                        rows.append(dict(line=f"{name} = {coord / 1000:.0f} km", along=f"{start / 1000:.0f}..{(start + (j - i) * size) / 1000:.0f} km",
                                         length_km=(j - i) * size / 1000, step=float(np.nanmedian(d[i:j, li])), ratio=float(abs(np.nanmedian(d[i:j, li])) / base),
                                         changes=",".join(expl) or "-- none --"))
                    i = j
                else:
                    i += 1
    return pd.DataFrame(rows).sort_values("length_km", ascending=False) if rows else pd.DataFrame()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common.add_config_arg(ap)
    ap.add_argument("--group-by", default="", help="columns that define the groups (comma-separated), or 'none'")
    ap.add_argument("--min-share", type=float, default=0.005, help="share of tiles a value needs to count")
    ap.add_argument("--no-maps", action="store_true")
    args = ap.parse_args()
    common.set_config(args.config)

    out = common.results() / "batch"
    out.mkdir(parents=True, exist_ok=True)
    sv = pd.read_parquet(common.results() / "survey.parquet")
    if "error" in sv:
        bad = sv.error.notna()
        print(f"{bad.sum()} tiles without a header (errors); left out")
        sv = sv[~bad]
    sv = sv.reset_index(drop=True)
    sv["multi_share"] = sv.n_second / sv.n_first.where(sv.n_first > 0)  # (older surveys computed it differently)
    pts_p = common.results() / "points.parquet"
    pts = pd.read_parquet(pts_p) if pts_p.exists() else None
    if pts is not None and "error" in pts:
        pts = pts[pts.error.isna()]
    pairs = neighbour_pairs(sv)
    lines = [f"# Batch-effect check: {common.cfg().get('name', '')}", "",
             f"{len(sv)} tiles surveyed ({len(common.tiles())} in the index), {len(pairs)} neighbour pairs."
             + (f" Point statistics for {len(pts)} sampled tiles." if pts is not None else
                " No point sample yet (sample_points.py)."), ""]

    # 1+2: header fields that vary, and their seams
    lines += ["## Header fields that vary", "",
              "| field | values (share) | seam km | jump across | jump within | ratio |", "|---|---|---|---|---|---|"]
    varying = []
    for k in CATEGORICAL:
        if k not in sv:
            continue
        vc = sv[k].astype(str).value_counts(normalize=True)
        vc = vc[vc >= args.min_share]
        if len(vc) < 2:
            continue
        varying.append(k)
        st = seam_stats(sv, pairs, k)
        vals = ", ".join(f"{v} ({s:.0%})" for v, s in vc.head(6).items()) + (" …" if len(vc) > 6 else "")
        lines.append(f"| {k} | {vals} | {st['seam_km']:.0f} | {st['jump_across']:.3f} | {st['jump_within']:.3f} | "
                     f"**{st['ratio']:.2f}** |")
        if not args.no_maps:
            plot_map(sv, k, out / f"map_{k}.png", categorical=True)
    if not varying:
        lines.append("| (none) | | | | | |")
    lines += ["", "*Jump*: median |Δ log(returns per pulse)| between neighbouring tiles, across a seam of the "
              "field vs. between neighbours with the same value. Forest/field changes make both > 0; a "
              "ratio well above 1 along a long seam means the field marks a change in the point cloud.", ""]
    if not args.no_maps:
        for k in CONTINUOUS:
            if k in sv:
                plot_map(sv, k, out / f"map_{k}.png", categorical=False)
    lines += ["## Return structure by value", ""]
    for k in varying:
        g = sv.groupby(sv[k].astype(str))
        t = g.agg(tiles=("id", "size"), pulse_density=("pulse_density", "median"),
                  returns_per_pulse=("returns_per_pulse", "median"), multi_share=("multi_share", "median"),
                  year_min=("creation_year", "min"), year_max=("creation_year", "max"))
        t = t[t.tiles >= args.min_share * len(sv)].sort_values("tiles", ascending=False)
        lines += [f"**{k}**", "", common.md_table(t), ""]

    # straight edges in the return structure (boundaries no header field marks)
    se = straight_edges(sv, [f for f in varying if f not in ("software", "max_return", "file_source_id")])
    lines += ["## Straight edges in the return structure", "",
              "Runs of >= 8 km along the tile grid where the multi-return share (pulses with >= 2 returns) steps "
              "consistently in one direction by > 2.5x the typical neighbour difference (`step`: east/north minus "
              "west/south). Landscape edges are rarely straight for kilometres; campaign and "
              "delivery blocks are. `changes`: header fields that differ across most of the run (software, max_return "
              "and file_source_id left out: they change all the time). An edge no field explains needs a point sample "
              "on both sides (sample_points.py --tiles) and a look at the map.", ""]
    lines += [common.md_table(se.head(20).reset_index(drop=True)) if len(se) else "(none found)", ""]

    # 3: point statistics by value
    if pts is not None and len(pts):
        m = pts.merge(sv[["id"] + varying], on="id", how="left")
        lines += ["## Point statistics of the sample by value", "",
                  "Per sampled (forest) tile: season from GPS time, canopy penetration "
                  "(`canopy_ground_share`: returns below 0.5 m per pulse under canopy), undergrowth returns "
                  "(`canopy_low_share`: 0.5-3 m per pulse under canopy, what kp turns into green), classes. "
                  "Differences here change kp's vegetation directly.", ""]
        cols = [c for c in POINT_STATS if c in m]
        for k in varying:
            num = [c for c in cols if c not in ("acq_median", "leaf_on")]
            t = m.groupby(m[k].astype(str))[num].median()
            t.insert(0, "n", m.groupby(m[k].astype(str)).size())
            if "acq_median" in m:
                t.insert(1, "acq", m.groupby(m[k].astype(str)).acq_median.agg(
                    lambda s: f"{min(s.dropna(), default='?')}..{max(s.dropna(), default='?')}"))
            if "leaf_on" in m:
                t.insert(2, "leaf_on", m.groupby(m[k].astype(str)).leaf_on.agg(
                    lambda s: f"{s.dropna().astype(bool).mean():.0%}" if s.notna().any() else "?"))
            lines += [f"**{k}**", "", common.md_table(t), ""]
        if "leaf_on" in pts and pts.leaf_on.notna().any() and pts.leaf_on.dropna().nunique() > 1:
            lines += ["**Season varies inside the sample.** Leaf-off and leaf-on flights see the forest very "
                      "differently; check whether the season follows a header field or cuts across them "
                      "(then group by season, which needs a point sample per area).", ""]

    # 4: groups
    if args.group_by:
        by = [] if args.group_by == "none" else args.group_by.split(",")
        g = sv[["id"]].copy()
        g["group"] = sv[by].astype(str).agg("-".join, axis=1) if by else "all"
        # tiles without a header (ZIP deliveries, errors) take the group of their nearest neighbour
        T = common.tiles()
        have = set(g.id)
        missing = [t for t in T.ids() if t not in have]
        if missing:
            known = dict(zip(g.id, g.group))
            extra = []
            for t in missing:
                ns = [known[u] for u in T.neighbours(t, include_self=False) if u in known]
                extra.append((t, max(set(ns), key=ns.count) if ns else "unknown"))
            g = pd.concat([g, pd.DataFrame(extra, columns=["id", "group"])], ignore_index=True)
        g.to_csv(common.results() / "groups.csv", index=False)
        vc = g.group.value_counts()
        lines += ["## Groups written", "", f"`groups.csv` by {by or 'nothing (one group)'}:", "",
                  common.md_table(vc.to_frame("tiles")), ""]
        print(vc.to_string())
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print(f"-> {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
