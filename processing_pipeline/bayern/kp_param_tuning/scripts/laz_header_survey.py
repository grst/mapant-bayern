#!/usr/bin/env python3
"""
Read the LAS public header of every Bavarian LAZ tile with an HTTP range request.

The header (first 375 bytes) carries the point count, point format, the bounds and the file
creation date, which is enough to map point density across the whole state without downloading
15 TB. Output: results/density.parquet (one row per tile).
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import faulthandler
import signal

import requests

faulthandler.register(signal.SIGUSR1)

HEADER_BYTES = 375


def parse_header(b: bytes) -> dict:
    if b[:4] != b"LASF":
        raise ValueError("not a LAS file")
    major, minor = b[24], b[25]
    doy, year = struct.unpack("<HH", b[90:94])
    fmt = b[104] & 0x3F
    n = struct.unpack("<I", b[107:111])[0]
    if minor >= 4 and len(b) >= 255:
        n = struct.unpack("<Q", b[247:255])[0] or n
    by_return = list(struct.unpack("<5I", b[111:131]))
    if minor >= 4 and len(b) >= 375:
        by_return = list(struct.unpack("<15Q", b[255:375]))
    maxx, minx, maxy, miny, maxz, minz = struct.unpack("<6d", b[179:227])
    return dict(
        las_version=f"{major}.{minor}",
        point_format=fmt,
        n_points=n,
        creation_year=year,
        creation_doy=doy,
        software=b[58:90].split(b"\0")[0].decode(errors="replace"),
        min_z=minz,
        max_z=maxz,
        ext_x=maxx - minx,
        ext_y=maxy - miny,
        n_first=by_return[0],
        n_second=by_return[1],
        n_third_plus=sum(by_return[2:]),
    )


def fetch(session: requests.Session, url: str, retries: int = 4) -> dict:
    for attempt in range(retries):
        try:
            r = session.get(url, headers={"Range": f"bytes=0-{HEADER_BYTES - 1}", "Accept-Encoding": "identity"},
                timeout=30,
                stream=True,
            )
            if r.status_code != 206:
                r.close()
                raise ValueError(f"HTTP {r.status_code}, no range support")
            r.raise_for_status()
            return parse_header(r.content)
        except Exception as e:  # noqa: BLE001 -- recorded, retried
            err = repr(e)
            time.sleep(2**attempt)
    return {"error": err}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("../input/laz_tiles.csv"))
    ap.add_argument("--out", type=Path, default=Path("results/density.parquet"))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    tiles = pd.read_csv(args.csv)
    if args.limit:
        tiles = tiles.sample(args.limit, random_state=0)
    done = pd.read_parquet(args.out) if args.out.exists() else pd.DataFrame(columns=["tile"])
    if "error" in done:
        done = done[done["error"].isna()]
    todo = tiles[~tiles.tile.isin(done.tile)]
    print(f"{len(todo)} tiles to survey ({len(done)} cached)", flush=True)

    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=args.jobs))
    rows = []
    t0 = time.time()
    with ThreadPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(fetch, session, u): t for t, u in zip(todo.tile, todo.url)}
        for i, f in enumerate(as_completed(futs), 1):
            rows.append({"tile": futs[f], **f.result()})
            if i % 2000 == 0 or i == len(futs):
                print(f"{i}/{len(futs)} {time.time() - t0:.0f}s", flush=True)
                out = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
                out.to_parquet(args.out)
    out = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
    meta = tiles[["tile", "size_bytes", "min_x", "min_y", "min_lon", "min_lat", "max_lon", "max_lat", "units"]]
    out = meta.merge(out.drop(columns=[c for c in meta.columns if c != "tile" and c in out]), on="tile")
    out["density"] = out.n_points / 1e6  # points per m² (1 km² tiles)
    out["pulse_density"] = out.n_first / 1e6  # first returns per m² ~ pulses per m²
    out.to_parquet(args.out)
    print(out.density.describe(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
