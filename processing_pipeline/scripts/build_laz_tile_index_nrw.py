#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyproj"]
# ///
"""Build a CSV index of every LAZ tile offered as OpenData by Geobasis NRW
(Bezirksregierung Koeln).

Background
----------
NRW publishes the "3D-Messdaten aus dem Laserscanning" point clouds at

    https://www.opengeodata.nrw.de/produkte/geobasis/hm/3dm_l_las/3dm_l_las/

and -- unusually for a German state -- backs the download page with a flat,
machine-readable index of the whole product:

    .../3dm_l_las/index.json     35860 files, ~3.17 TiB

so the whole state is one request.  Each entry carries a name, a byte size and
a timestamp.  The URL is the directory plus the name.

**It does not carry a checksum, and NRW publishes none anywhere else.**  The
sibling ``3dm_meta.zip`` holds ``3dm_nw.csv``, which is per-tile acquisition
metadata (date, method, accuracy, CRS) with no hash column, and there are no
``.md5``/``.sha256`` sidecars or Metalinks on the server.  Since mapant-nf
makes ``sha256`` mandatory and load-bearing -- a truncated laz renders as a
plausible but wrong map rather than as an error -- the index this script
produces by default is **not directly usable as a tiles CSV**: the ``sha256``
column is empty and nf-schema will reject it.

``--fill-sha256`` closes that gap by streaming every tile and hashing it
without writing it to disk.  That is a one-off ~3.2 TiB of transfer; it needs
no disk, resumes, and is the only honest way to get the column, since a hash
that was not computed from the bytes is worse than no hash at all.

Bounding boxes
--------------
As in Bavaria and Rheinland-Pfalz the file name carries the geometry:
``3dm_32_280_5652_1_nw.laz`` is UTM zone 32, easting 280 km, northing 5652 km
at the *lower-left* corner, 1 km edge.  Verified against the LAS public header
of that tile, which reports its point extent as

    X 280000.00 .. 280999.99   Y 5652000.00 .. 5652999.99

i.e. inside the derived box, hugging all four edges.  ``--verify-headers N``
re-runs that check on N random tiles via HTTP range requests.

Usage
-----
    # the part that is cheap: everything except the checksums
    uv run scripts/build_laz_tile_index_nrw.py -o input/laz_tiles_nrw.nosha256.csv

    # the part that costs 3.2 TiB of transfer; resumable, safe to re-run
    uv run scripts/build_laz_tile_index_nrw.py -o input/laz_tiles_nrw.csv \
        --fill-sha256 --resume-from input/laz_tiles_nrw.csv --jobs 8
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import random
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PRODUCT_BASE = (
    "https://www.opengeodata.nrw.de/produkte/geobasis/hm/3dm_l_las/3dm_l_las/"
)
INDEX_URL = f"{PRODUCT_BASE}index.json"

# The dataset inside index.json that holds the single-tile packaging; the file
# also advertises other packagings, which we do not want.
DATASET_NAME = "3dm_kacheln"

# Native CRS of the tiling scheme and the tile edge length in metres.
TILE_CRS = "EPSG:25832"
TILE_SIZE_M = 1000

# All of NRW is in UTM zone 32; a zone 33 file would silently land in the wrong
# place, so the parser rejects it rather than guessing.
TILE_ZONE = 32

# "3dm_32_280_5652_1_nw.laz" -> zone 32, easting 280 km, northing 5652 km.
TILE_NAME_RE = re.compile(
    r"^3dm_(?P<zone>\d{2})_(?P<east_km>\d+)_(?P<north_km>\d+)_1_nw\.laz$"
)

USER_AGENT = (
    "laz-tile-index/1.0 (+https://www.opengeodata.nrw.de/; "
    "builds a CSV index of OpenData LAZ tiles)"
)

# Offset of the (maxx, minx, maxy, miny, maxz, minz) doubles in the LAS public
# header block, and how many bytes we need to fetch to reach the end of them.
LAS_EXTENT_OFFSET = 179
LAS_HEADER_PROBE = 400

HASH_CHUNK = 1 << 22  # 4 MiB

CSV_FIELDS = [
    "tile",
    "url",
    "size_bytes",
    "sha256",
    "crs",
    "min_x",
    "min_y",
    "max_x",
    "max_y",
    "min_lon",
    "min_lat",
    "max_lon",
    "max_lat",
    "units",
]


@dataclass
class Tile:
    tile: str
    url: str
    size_bytes: int
    sha256: str = ""
    # index.json's own timestamp; a change here invalidates a cached hash.
    timestamp: str = ""
    units: str = field(default="Nordrhein-Westfalen")

    @property
    def bbox_utm(self) -> tuple[int, int, int, int]:
        m = TILE_NAME_RE.match(self.tile)
        if not m:
            raise ValueError(f"unexpected tile name: {self.tile!r}")
        if int(m["zone"]) != TILE_ZONE:
            raise ValueError(
                f"{self.tile!r} is in UTM zone {m['zone']}, but this index "
                f"assumes zone {TILE_ZONE} ({TILE_CRS})"
            )
        min_x = int(m["east_km"]) * 1000
        min_y = int(m["north_km"]) * 1000
        return min_x, min_y, min_x + TILE_SIZE_M, min_y + TILE_SIZE_M


def open_url(url: str, *, retries: int = 4, timeout: int = 300, headers=None):
    """Open a URL with a couple of retries on transient failures.

    Returns the live response object so callers can stream it; the caller is
    responsible for closing it.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except (urllib.error.URLError, TimeoutError) as error:
            # 4xx are not worth retrying; anything else might be.
            if isinstance(error, urllib.error.HTTPError) and 400 <= error.code < 500:
                raise
            last_error = error
            if attempt < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"failed to fetch {url}") from last_error


def fetch(url: str, **kwargs) -> bytes:
    with open_url(url, **kwargs) as response:
        return response.read()


def parse_index(index_bytes: bytes) -> list[Tile]:
    """Return one Tile per entry of the single-tile dataset in index.json."""
    document = json.loads(index_bytes)
    datasets = {d.get("name"): d for d in document.get("datasets", [])}
    dataset = datasets.get(DATASET_NAME)
    if dataset is None:
        raise RuntimeError(
            f"{DATASET_NAME!r} not in index.json (found {sorted(datasets)}) - "
            "has the product been repackaged?"
        )
    tiles: list[Tile] = []
    for entry in dataset.get("files", []):
        name = entry.get("name")
        if not name or not name.endswith(".laz"):
            continue
        tiles.append(
            Tile(
                tile=name,
                url=PRODUCT_BASE + name,
                size_bytes=int(entry["size"]),
                timestamp=entry.get("timestamp", ""),
            )
        )
    return tiles


def load_cached_hashes(path: Path) -> dict[tuple[str, int], str]:
    """Read sha256 values from an earlier run, keyed by (tile, size).

    Keying on the size too means a tile that was re-flown and republished at a
    different size loses its cached hash instead of keeping a stale one.
    """
    if not path.exists():
        return {}
    cached: dict[tuple[str, int], str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            sha256 = (row.get("sha256") or "").strip()
            if len(sha256) == 64:
                try:
                    cached[(row["tile"], int(row["size_bytes"]))] = sha256
                except (KeyError, ValueError):
                    continue
    return cached


def hash_tile(tile: Tile) -> tuple[str, int]:
    """Stream a tile and return its (sha256, byte count) without storing it."""
    digest = hashlib.sha256()
    total = 0
    with open_url(tile.url) as response:
        while chunk := response.read(HASH_CHUNK):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def fill_sha256(tiles: list[Tile], cached: dict[tuple[str, int], str], jobs: int) -> int:
    """Fill in the sha256 of every tile that has none.  Returns the failure count."""
    for tile in tiles:
        tile.sha256 = cached.get((tile.tile, tile.size_bytes), "")

    todo = [t for t in tiles if not t.sha256]
    reused = len(tiles) - len(todo)
    remaining_bytes = sum(t.size_bytes for t in todo)
    print(
        f"  {reused} hashes reused, {len(todo)} to compute "
        f"({remaining_bytes / 1024**4:.2f} TiB to transfer)",
        file=sys.stderr,
    )
    if not todo:
        return 0

    lock = threading.Lock()
    state = {"done": 0, "bytes": 0, "failed": 0}
    started = time.monotonic()

    def worker(tile: Tile) -> None:
        try:
            sha256, total = hash_tile(tile)
        except Exception as error:  # noqa: BLE001 - one bad tile must not stop the pass
            with lock:
                state["failed"] += 1
                print(f"  FAILED {tile.tile}: {error}", file=sys.stderr)
            return
        if total != tile.size_bytes:
            # The index disagrees with what the server served; trust the bytes
            # we actually hashed and record both, since a wrong size_bytes
            # costs a redundant download in the pipeline.
            with lock:
                print(
                    f"  WARNING: {tile.tile} is {total} bytes, index says "
                    f"{tile.size_bytes}; using the served size",
                    file=sys.stderr,
                )
            tile.size_bytes = total
        tile.sha256 = sha256
        with lock:
            state["done"] += 1
            state["bytes"] += total
            if state["done"] % 100 == 0 or state["done"] == len(todo):
                elapsed = max(time.monotonic() - started, 1e-9)
                rate = state["bytes"] / elapsed / 1024**2
                print(
                    f"  {state['done']}/{len(todo)} hashed, "
                    f"{state['bytes'] / 1024**3:.1f} GiB, {rate:.0f} MiB/s",
                    file=sys.stderr,
                )

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(worker, todo))
    return state["failed"]


def verify_headers(tiles: list[Tile], count: int) -> int:
    """Range-GET the LAS public header of `count` random tiles and compare its
    point extent with the box derived from the file name.  Returns the number
    of mismatches."""
    sample = random.sample(tiles, min(count, len(tiles)))
    mismatches = 0
    for tile in sample:
        blob = fetch(tile.url, headers={"Range": f"bytes=0-{LAS_HEADER_PROBE - 1}"})
        if blob[:4] != b"LASF":
            print(f"  {tile.tile}: not a LAS file?", file=sys.stderr)
            mismatches += 1
            continue
        max_x, min_x, max_y, min_y, _, _ = struct.unpack_from(
            "<6d", blob, LAS_EXTENT_OFFSET
        )
        box = tile.bbox_utm
        # Points sit strictly inside the tile, so the header extent must be
        # contained in the derived box (and, for a full tile, hug its edges).
        inside = box[0] <= min_x <= max_x <= box[2] and box[1] <= min_y <= max_y <= box[3]
        print(
            f"  {tile.tile}: header X {min_x:.2f}..{max_x:.2f} "
            f"Y {min_y:.2f}..{max_y:.2f} vs derived {box} "
            f"{'OK' if inside else 'MISMATCH'}",
            file=sys.stderr,
        )
        if not inside:
            mismatches += 1
    return mismatches


def make_wgs84_transformer():
    """Return a UTM32 -> WGS84 bbox transform, or None if pyproj is missing."""
    try:
        from pyproj import Transformer
    except ImportError:
        print(
            "pyproj not installed - leaving the lon/lat columns empty "
            "(run via `uv run` to get them)",
            file=sys.stderr,
        )
        return None

    transformer = Transformer.from_crs(TILE_CRS, "EPSG:4326", always_xy=True)

    def to_wgs84(min_x: int, min_y: int, max_x: int, max_y: int):
        # Transform all four corners: the tile edges are not straight lines in
        # WGS84, so taking only two corners would clip the true extent.
        corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
        lons, lats = transformer.transform(
            [x for x, _ in corners], [y for _, y in corners]
        )
        return min(lons), min(lats), max(lons), max(lats)

    return to_wgs84


def write_csv(tiles: list[Tile], out_path: Path) -> None:
    to_wgs84 = make_wgs84_transformer()
    # Sort by tile coordinates so the CSV is stable across runs.
    ordered = sorted(tiles, key=lambda t: t.bbox_utm)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for tile in ordered:
            min_x, min_y, max_x, max_y = tile.bbox_utm
            row = {
                "tile": tile.tile,
                "url": tile.url,
                "size_bytes": tile.size_bytes,
                "sha256": tile.sha256,
                "crs": TILE_CRS,
                "min_x": min_x,
                "min_y": min_y,
                "max_x": max_x,
                "max_y": max_y,
                "min_lon": "",
                "min_lat": "",
                "max_lon": "",
                "max_lat": "",
                "units": tile.units,
            }
            if to_wgs84 is not None:
                min_lon, min_lat, max_lon, max_lat = to_wgs84(min_x, min_y, max_x, max_y)
                row |= {
                    "min_lon": f"{min_lon:.7f}",
                    "min_lat": f"{min_lat:.7f}",
                    "max_lon": f"{max_lon:.7f}",
                    "max_lat": f"{max_lat:.7f}",
                }
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("laz_tiles_nrw.csv"),
        help="CSV to write (default: %(default)s)",
    )
    parser.add_argument(
        "--fill-sha256",
        action="store_true",
        help="stream every tile and hash it (~3.2 TiB of transfer, no disk "
        "needed); without this the sha256 column is empty and the CSV will "
        "not pass mapant-nf's input validation",
    )
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="reuse sha256 values from an earlier CSV (defaults to --output "
        "if it exists)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=8,
        help="concurrent hashing streams (default: %(default)s)",
    )
    parser.add_argument(
        "--verify-headers",
        type=int,
        default=0,
        metavar="N",
        help="range-GET the LAS header of N random tiles and check the derived "
        "bounding box against the point extent it declares",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="only index the first N tiles (for a quick smoke test)",
    )
    args = parser.parse_args()

    print(f"Fetching {INDEX_URL}", file=sys.stderr)
    tiles = parse_index(fetch(INDEX_URL))
    if not tiles:
        print("No tiles found - has the format changed?", file=sys.stderr)
        return 1
    print(f"Found {len(tiles)} tiles", file=sys.stderr)

    duplicates = len(tiles) - len({t.tile for t in tiles})
    if duplicates:
        print(f"WARNING: {duplicates} duplicate tile names", file=sys.stderr)

    # Fail loudly rather than writing a CSV with a silently wrong bbox.
    for tile in tiles:
        tile.bbox_utm

    if args.limit:
        tiles = tiles[: args.limit]
        print(f"Limited to {len(tiles)} tiles", file=sys.stderr)

    if args.verify_headers:
        print(f"Verifying {args.verify_headers} LAS headers", file=sys.stderr)
        mismatches = verify_headers(tiles, args.verify_headers)
        if mismatches:
            print(f"{mismatches} header(s) did not match", file=sys.stderr)
            return 1

    failed = 0
    if args.fill_sha256:
        resume_from = args.resume_from or args.output
        cached = load_cached_hashes(resume_from)
        if cached:
            print(f"Loaded {len(cached)} hashes from {resume_from}", file=sys.stderr)
        print(f"Hashing with {args.jobs} streams", file=sys.stderr)
        failed = fill_sha256(tiles, cached, args.jobs)

    write_csv(tiles, args.output)

    total_bytes = sum(t.size_bytes for t in tiles if t.size_bytes > 0)
    missing_hash = sum(1 for t in tiles if not t.sha256)
    print(
        f"Wrote {len(tiles)} tiles to {args.output} "
        f"({total_bytes / 1024**4:.2f} TiB total)",
        file=sys.stderr,
    )
    if missing_hash:
        print(
            f"WARNING: {missing_hash} tiles have no SHA-256. NRW publishes none, "
            "so this CSV will be rejected by mapant-nf until you run "
            "--fill-sha256 (re-run to resume).",
            file=sys.stderr,
        )
    if failed:
        print(f"WARNING: {failed} tile(s) could not be hashed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
