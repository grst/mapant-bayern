#!/usr/bin/env python3
"""
Add the per-tile karttapullautin config to the pipeline samplesheet (input/laz_tiles.csv).

Two columns are added (or refreshed), from the LAS header survey (results/density.parquet):

  las_version   1.2 or 1.4, the point-record generation of the tile
  pullauta_ini  the recommended ini for that generation, relative to processing_pipeline/

Run it again after regenerating laz_tiles.csv with scripts/build_laz_tile_index.py, or after
re-running the header survey (tiles are re-delivered in batches, so a tile's generation can change).

    samplesheet_ini.py [--csv ../input/laz_tiles.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT.parent
INI = {
    "1.2": "optimize_params/params/pullauta.bayern-las12.ini",
    "1.4": "optimize_params/params/pullauta.bayern-las14.ini",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=PIPELINE / "input/laz_tiles.csv")
    args = ap.parse_args()

    for p in INI.values():
        if not (PIPELINE / p).exists():
            raise SystemExit(f"missing {p}")
    d = pd.read_parquet(ROOT / "results/density.parquet", columns=["tile", "las_version"])
    ver = dict(zip(d.tile, d.las_version.astype(str)))

    with open(args.csv, newline="") as f:
        reader = csv.DictReader(f)
        fields = [c for c in reader.fieldnames if c not in ("las_version", "pullauta_ini")]
        rows = list(reader)
    missing = [r["tile"] for r in rows if r["tile"] not in ver]
    if missing:
        raise SystemExit(f"{len(missing)} tiles have no header survey entry, e.g. {missing[:3]}; re-run "
                         "laz_header_survey.py first")
    fields += ["las_version", "pullauta_ini"]
    tmp = args.csv.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            v = ver[r["tile"]]
            w.writerow({**{k: r[k] for k in fields[:-2]}, "las_version": v, "pullauta_ini": INI[v]})
    tmp.replace(args.csv)
    n = pd.Series([ver[r["tile"]] for r in rows]).value_counts().to_dict()
    print(f"{args.csv}: {len(rows)} tiles, {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
