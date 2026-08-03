#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyproj"]
# ///
"""Build a CSV index of every LAZ tile offered as OpenData by the surveying
administration of Rheinland-Pfalz (LVermGeo RP).

Background
----------
RLP publishes the "Laserpunkte Objekte und Gelaende" (LPO/LPG) point clouds as
plain files on a directory-listing server:

    https://geobasis-rlp.de/data/las/current/las/     21207 x *.laz
    https://geobasis-rlp.de/data/las/current/meta4/   Metalink 4.0 files
    https://geobasis-rlp.de/data/las/current/metadata/  per-tile ISO XML

Unlike Bavaria there is no picker to scrape: a single statewide Metalink
covers the whole state, so the index is one request.  ``las_las_07.meta4``
(07 = Regionalschluessel of Rheinland-Pfalz) lists every tile with its file
name, size, SHA-256 and download URL -- exactly the four things the mapant-nf
tiles CSV contract needs that cannot be derived.  Finer-grained Metalinks
exist alongside it (``las_las_<5-digit Kreis>.meta4`` and
``las_las_<8-digit Gemeinde>.meta4``) but they are strict subsets.

The tiles are 1 km x 1 km in EPSG:25832 (ETRS89 / UTM zone 32N), which covers
all of Rheinland-Pfalz, so -- unlike Bavaria -- there is no zone split to worry
about.

Bounding boxes
--------------
The Metalink carries no geometry, but the download file name does:
``lpolpg_32_441_5527_1_rp.laz`` is UTM zone 32, easting 441 km, northing
5527 km at the *lower-left* corner, 1 km edge.  Verified against the LAS public
header of that tile, which reports its point extent as

    X 441000.00 .. 442000.00   Y 5527000.00 .. 5528000.00

i.e. exactly the derived box.  The header can be read without downloading the
file:

    curl -r 0-399 https://geobasis-rlp.de/data/las/current/las/lpolpg_32_441_5527_1_rp.laz

and unpacking the six doubles at offset 179 (maxx, minx, maxy, miny, maxz,
minz) of the LAS 1.2 public header block.  ``--verify-headers N`` does this for
N random tiles.

Note that the Metalink's ``name`` attribute (``LAS_441_5527_las12.laz``) is
*not* the name of the file it points at; the ``tile`` column uses the basename
of the URL, which is what actually lands on disk.

Usage
-----
    uv run scripts/build_laz_tile_index_rlp.py -o input/laz_tiles_rlp.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

# One statewide Metalink; 07 is the Regionalschluessel of Rheinland-Pfalz.
METALINK_URL = "https://geobasis-rlp.de/data/las/current/meta4/las_las_07.meta4"
LISTING_URL = "https://geobasis-rlp.de/data/las/current/las/"

# Native CRS of the tiling scheme and the tile edge length in metres.
TILE_CRS = "EPSG:25832"
TILE_SIZE_M = 1000

# Every tile is in UTM zone 32; a zone 33 file would silently land in the wrong
# place, so the parser rejects it rather than guessing.
TILE_ZONE = 32

METALINK_NS = {"m": "urn:ietf:params:xml:ns:metalink"}

# "lpolpg_32_441_5527_1_rp.laz" -> zone 32, easting 441 km, northing 5527 km.
TILE_NAME_RE = re.compile(
    r"^lpolpg_(?P<zone>\d{2})_(?P<east_km>\d+)_(?P<north_km>\d+)_1_rp\.laz$"
)

USER_AGENT = (
    "laz-tile-index/1.0 (+https://lvermgeo.rlp.de/geodaten-geoshop/open-data/; "
    "builds a CSV index of OpenData LAZ tiles)"
)

# Offset of the (maxx, minx, maxy, miny, maxz, minz) doubles in the LAS public
# header block, and how many bytes we need to fetch to reach the end of them.
LAS_EXTENT_OFFSET = 179
LAS_HEADER_PROBE = 400

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
    sha256: str

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


def fetch(url: str, *, retries: int = 4, timeout: int = 300, headers=None) -> bytes:
    """GET a URL with a couple of retries on transient failures."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            # 4xx are not worth retrying; anything else might be.
            if isinstance(error, urllib.error.HTTPError) and 400 <= error.code < 500:
                raise
            last_error = error
            if attempt < retries:
                backoff = 2**attempt
                print(
                    f"  retry {attempt}/{retries - 1} in {backoff}s ({error})",
                    file=sys.stderr,
                )
                time.sleep(backoff)
    raise RuntimeError(f"failed to fetch {url}") from last_error


def parse_metalink(metalink_bytes: bytes) -> list[Tile]:
    """Return one Tile per ``<file>`` entry.

    The ``name`` attribute is a delivery name unrelated to the served file, so
    the tile name comes from the URL instead.
    """
    root = ET.fromstring(metalink_bytes)
    tiles: list[Tile] = []
    for file_el in root.findall("m:file", METALINK_NS):
        url_el = file_el.find("m:url", METALINK_NS)
        size_el = file_el.find("m:size", METALINK_NS)
        sha256_el = file_el.find("m:hash[@type='sha-256']", METALINK_NS)
        if url_el is None or not url_el.text:
            print(
                f"  skipping <file> entry without url: {file_el.get('name')!r}",
                file=sys.stderr,
            )
            continue
        url = url_el.text.strip()
        tiles.append(
            Tile(
                tile=url.rsplit("/", 1)[-1],
                url=url,
                size_bytes=int(size_el.text) if size_el is not None and size_el.text else -1,
                sha256=(sha256_el.text or "").strip() if sha256_el is not None else "",
            )
        )
    return tiles


def cross_check_listing(tiles: list[Tile]) -> None:
    """Warn if the Metalink and the directory listing disagree.

    The Metalink is the contract, but the listing is the ground truth for what
    is actually downloadable, and a tile in one but not the other means the
    index is stale in one direction or the other.
    """
    try:
        listing = fetch(LISTING_URL).decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001 - a cross-check must never be fatal
        print(f"  could not fetch the directory listing ({error})", file=sys.stderr)
        return
    served = {
        href
        for href in re.findall(r'href="([^"]+)"', listing)
        if href.endswith(".laz")
    }
    indexed = {t.tile for t in tiles}
    only_listing = served - indexed
    only_metalink = indexed - served
    if only_listing:
        print(
            f"  WARNING: {len(only_listing)} laz on the server are missing from "
            f"the Metalink, e.g. {sorted(only_listing)[:3]}",
            file=sys.stderr,
        )
    if only_metalink:
        print(
            f"  WARNING: {len(only_metalink)} Metalink entries are not on the "
            f"server, e.g. {sorted(only_metalink)[:3]}",
            file=sys.stderr,
        )
    if not only_listing and not only_metalink:
        print(f"  listing and Metalink agree on all {len(served)} tiles", file=sys.stderr)


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
                # Kept for column parity with the Bavarian CSV, where it names
                # the Regierungsbezirk.  RLP's index is statewide in one file.
                "units": "Rheinland-Pfalz",
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
        default=Path("laz_tiles_rlp.csv"),
        help="CSV to write (default: %(default)s)",
    )
    parser.add_argument(
        "--metalink",
        default=METALINK_URL,
        help="Metalink to index; pass a Kreis/Gemeinde one to index a subset "
        "(default: the statewide %(default)s)",
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
        "--no-cross-check",
        action="store_true",
        help="skip comparing the Metalink against the directory listing",
    )
    args = parser.parse_args()

    print(f"Fetching {args.metalink}", file=sys.stderr)
    tiles = parse_metalink(fetch(args.metalink))
    if not tiles:
        print("No <file> entries found - has the format changed?", file=sys.stderr)
        return 1
    print(f"Found {len(tiles)} tiles", file=sys.stderr)

    duplicates = len(tiles) - len({t.tile for t in tiles})
    if duplicates:
        print(f"WARNING: {duplicates} duplicate tile names", file=sys.stderr)

    # Fail loudly rather than writing a CSV with a silently wrong bbox.
    for tile in tiles:
        tile.bbox_utm

    if not args.no_cross_check:
        print("Cross-checking against the directory listing", file=sys.stderr)
        cross_check_listing(tiles)

    if args.verify_headers:
        print(f"Verifying {args.verify_headers} LAS headers", file=sys.stderr)
        mismatches = verify_headers(tiles, args.verify_headers)
        if mismatches:
            print(f"{mismatches} header(s) did not match", file=sys.stderr)
            return 1

    write_csv(tiles, args.output)

    total_bytes = sum(t.size_bytes for t in tiles if t.size_bytes > 0)
    missing_hash = sum(1 for t in tiles if not t.sha256)
    print(
        f"Wrote {len(tiles)} tiles to {args.output} "
        f"({total_bytes / 1024**4:.2f} TiB total)",
        file=sys.stderr,
    )
    if missing_hash:
        print(f"WARNING: {missing_hash} tiles have no SHA-256", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
