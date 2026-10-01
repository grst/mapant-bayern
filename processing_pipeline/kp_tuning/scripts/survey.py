#!/usr/bin/env python3
"""
Step 1a of the batch-effect check: the LAS public header of every tile, by HTTP range request.

The first 375 bytes of a LAS/LAZ file carry what the producer wrote about the delivery: version
and point format, generating software and system identifier, file creation date, scale factors,
point counts per return number and the bounds. Different campaigns, sensors or processing lines
show up here long before anyone renders a map -- in Bavaria the LAS 1.2 / 1.4 split. For a whole
state this costs a few hundred MB of traffic instead of terabytes.

    survey.py --config region.yaml [--jobs 8] [--limit N]

Output: <results>/survey.parquet (one row per tile; failures keep an `error`). Tiles delivered as
ZIP cannot be read by range; for those, run sample_points.py on a sample instead (it downloads).
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

HEADER_BYTES = 375


def parse_header(b: bytes) -> dict:
    if b[:4] != b"LASF":
        raise ValueError("not a LAS file")
    major, minor = b[24], b[25]
    doy, year = struct.unpack("<HH", b[90:94])
    fmt = b[104] & 0x3F
    compressed = bool(b[104] & 0xC0)
    n = struct.unpack("<I", b[107:111])[0]
    if minor >= 4 and len(b) >= 255:
        n = struct.unpack("<Q", b[247:255])[0] or n
    by_return = list(struct.unpack("<5I", b[111:131]))
    if minor >= 4 and len(b) >= 375:
        by_return = list(struct.unpack("<15Q", b[255:375]))
    sx, sy, sz, ox, oy, oz = struct.unpack("<6d", b[131:179])
    maxx, minx, maxy, miny, maxz, minz = struct.unpack("<6d", b[179:227])
    s = lambda a, c: b[a:c].split(b"\0")[0].decode(errors="replace").strip()  # noqa: E731
    return dict(
        las_version=f"{major}.{minor}",
        point_format=fmt,
        laz_flag=compressed,
        record_length=struct.unpack("<H", b[105:107])[0],
        n_vlrs=struct.unpack("<I", b[100:104])[0],
        file_source_id=struct.unpack("<H", b[4:6])[0],
        global_encoding=struct.unpack("<H", b[6:8])[0],
        system_identifier=s(26, 58),
        software=s(58, 90),
        creation_year=year,
        creation_doy=doy,
        scale_x=sx, scale_z=sz, offset_x=ox, offset_z=oz,
        n_points=n,
        n_first=by_return[0], n_second=by_return[1], n_third_plus=sum(by_return[2:]),
        max_return=max((i + 1 for i, v in enumerate(by_return) if v), default=0),
        min_z=minz, max_z=maxz, ext_x=maxx - minx, ext_y=maxy - miny,
    )


def fetch(session: requests.Session, url: str, retries: int = 4) -> dict:
    err = ""
    for attempt in range(retries):
        try:
            r = session.get(url, headers={"Range": f"bytes=0-{HEADER_BYTES - 1}", "Accept-Encoding": "identity"},
                            timeout=30, stream=True)
            if r.status_code != 206:
                r.close()
                raise ValueError(f"HTTP {r.status_code}, no range support")
            return parse_header(r.raw.read(HEADER_BYTES))
        except Exception as e:  # noqa: BLE001 -- recorded, retried
            err = repr(e)
            time.sleep(2**attempt)
    return {"error": err}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common.add_config_arg(ap)
    ap.add_argument("--jobs", type=int, default=8, help="parallel requests (be polite)")
    ap.add_argument("--limit", type=int, default=0, help="random sample of N tiles (quick look)")
    args = ap.parse_args()
    common.set_config(args.config)

    T = common.tiles()
    tl = T.df
    if args.limit:
        tl = tl.sample(min(args.limit, len(tl)), random_state=0)
    tl = tl[~tl.url.str.lower().str.endswith(".zip")]
    out_p = common.results() / "survey.parquet"
    done = pd.read_parquet(out_p) if out_p.exists() else pd.DataFrame(columns=["id"])
    if "error" in done:
        done = done[done["error"].isna()]
    todo = tl[~tl.id.isin(done.id)]
    print(f"{len(todo)} tiles to survey ({len(done)} cached, {len(T) - len(tl)} not by range)", flush=True)

    session = requests.Session()
    session.headers["User-Agent"] = common.user_agent()
    session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=args.jobs))
    rows, t0 = [], time.time()

    def save():
        df = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
        meta = T.df[["id", "size_bytes", "min_x", "min_y", "max_x", "max_y"]].reset_index(drop=True)
        df = meta.merge(df.drop(columns=[c for c in meta.columns if c != "id" and c in df]), on="id")
        area = (df.max_x - df.min_x) * (df.max_y - df.min_y)
        df["density"] = df.n_points / area  # points per m²
        df["pulse_density"] = df.n_first / area  # first returns per m² ~ pulses per m²
        df["returns_per_pulse"] = df.n_points / df.n_first.where(df.n_first > 0)
        df["multi_share"] = (df.n_second + df.n_third_plus) / df.n_first.where(df.n_first > 0)
        df.to_parquet(out_p)
        return df

    with ThreadPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(fetch, session, u): t for t, u in zip(todo.id, todo.url)}
        for i, f in enumerate(as_completed(futs), 1):
            rows.append({"id": futs[f], **f.result()})
            if i % 2000 == 0 or i == len(futs):
                print(f"{i}/{len(futs)} {time.time() - t0:.0f}s", flush=True)
                save()
    df = save()
    print(f"{len(df)} tiles, {df.get('error', pd.Series(dtype=str)).notna().sum()} errors -> {out_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
