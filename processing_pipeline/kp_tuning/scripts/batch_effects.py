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
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    T = common.tiles()
    cx = (sv.min_x + sv.max_x) / 2 / 1000
    cy = (sv.min_y + sv.max_y) / 2 / 1000
    fig, ax = plt.subplots(figsize=(8, 8))
    s = max(0.5, 3e4 / max(len(sv), 1)) * (T.size / 1000) ** 2
    if categorical:
        vals = sv[col].astype(str)
        cats = vals.value_counts().index[:12]
        cmap = plt.get_cmap("tab10" if len(cats) <= 10 else "tab20")
        for i, c in enumerate(cats):
            m = vals == c
            ax.scatter(cx[m], cy[m], s=s, marker="s", color=cmap(i % cmap.N), label=f"{c} ({m.sum()})", linewidths=0)
        rest = ~vals.isin(cats)
        if rest.any():
            ax.scatter(cx[rest], cy[rest], s=s, marker="s", color="lightgrey", label=f"other ({rest.sum()})", linewidths=0)
        ax.legend(markerscale=6 / max(s, 0.1) ** 0.5, fontsize=8, loc="best")
    else:
        v = sv[col].astype(float)
        lo, hi = np.nanpercentile(v, [2, 98])
        sc = ax.scatter(cx, cy, c=v.clip(lo, hi), s=s, marker="s", cmap="viridis", linewidths=0)
        fig.colorbar(sc, ax=ax, shrink=0.7, label=col)
    ax.set_aspect("equal")
    ax.set_title(col)
    ax.set_xlabel("km E")
    ax.set_ylabel("km N")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


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
        missing = [t for t in T.ids() if t not in set(g.id)]
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
