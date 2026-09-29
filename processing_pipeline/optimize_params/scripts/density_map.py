"""Statewide maps of LiDAR pulse density and point-record generation, with the study sites."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

d = pd.read_parquet(ROOT / "results/density.parquet")
d = d[d.n_points > 0]
sites = yaml.safe_load((ROOT / "sites.yaml").read_text())
fig, ax = plt.subplots(1, 2, figsize=(15, 7.5))
sc = ax[0].scatter(d.min_x / 1000, d.min_y / 1000, c=d.pulse_density.clip(0, 35), s=0.5, marker="s",
                   cmap="viridis", linewidths=0)
plt.colorbar(sc, ax=ax[0], label="first returns per m² (≈ pulses per m²)")
ax[0].set_title("LiDAR pulse density (1 km tiles)")
old = d.las_version == "1.2"
ax[1].scatter(d.min_x[old] / 1000, d.min_y[old] / 1000, color="#e08a2c", s=0.5, marker="s", linewidths=0,
              label=f"LAS 1.2 / format 1 ({old.sum()} tiles, {(d.n_points / d.n_first)[old].median():.2f} returns/pulse)")
ax[1].scatter(d.min_x[~old] / 1000, d.min_y[~old] / 1000, color="#3a78b5", s=0.5, marker="s", linewidths=0,
              label=f"LAS 1.4 / format 6 ({(~old).sum()} tiles, {(d.n_points / d.n_first)[~old].median():.2f} returns/pulse)")
ax[1].legend(markerscale=20, loc="lower left", fontsize=9)
ax[1].set_title("Point-record generation (campaign / sensor)")
for a in ax:
    a.set_aspect("equal")
    a.set_xlabel("UTM32 easting [km]")
    for k, v in sites.items():
        x, y = (int(t) for t in v["core"][0].split("_"))
        a.plot(x, y, "^", color="red" if v["split"] == "train" else "magenta", ms=7, mec="black")
        a.annotate(k, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=8, color="black")
plt.tight_layout()
plt.savefig(ROOT / "results/density_map.png", dpi=110)
