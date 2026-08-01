#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyproj"]
# ///
"""Build a CSV index of every LAZ tile offered as OpenData by the Bavarian
surveying administration (LDBV / Bayerische Vermessungsverwaltung).

Background
----------
https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=laserdaten
offers the laser point clouds either tile-by-tile (1 km x 1 km) or as a
"Massendownload" per administrative unit.  There is no published flat index of
all tiles, but the Massendownload is driven by Metalink 4.0 files (RFC 5854)
that the portal generates per administrative unit, and those *are* static,
machine-readable and contain exactly what we want: file name, size, SHA-256 and
download URL.

The KML that backs the "Verwaltungseinheit" picker exists at two granularities:

    .../meta/kml/gemeinde.kml          2229 municipalities
    .../meta/kml/regierungsbezirk.kml     7 administrative districts

The 7 Regierungsbezirke tile all of Bavaria, so scraping their Metalinks covers
the whole state in 7 requests instead of 2229.  This script discovers the
Metalink URLs from that KML (rather than hard-coding 091..097) so that it keeps
working if the set of units ever changes.

Bounding boxes
--------------
The Metalink carries no geometry, but the tile name does: ``674_5403.laz`` is
the tile whose lower-left corner is at easting 674 km / northing 5403 km in
EPSG:25832 (ETRS89 / UTM zone 32N), and tiles are 1 km x 1 km.  Verified
against the portal's own grid WMS, e.g.

    curl "https://geoservices.bayern.de/od/wms/grid/v1/opendatagrid?service=WMS\
&version=1.3.0&request=GetFeatureInfo&layers=laser&query_layers=laser\
&crs=EPSG:25832&bbox=674000,5403000,675000,5404000&width=10&height=10&i=5&j=5\
&format=image/png&info_format=text/html"

which answers ``674_5403.laz``; probes just inside the four corners of that
extent confirm the tile spans [674000, 675000) x [5403000, 5404000).

Usage
-----
    uv run scripts/build_laz_tile_index.py -o laz_tiles.csv

Adding ``--per-gemeinde`` uses the municipality-level Metalinks instead, which
is much slower but additionally records which municipality each tile belongs to.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

KML_BASE = "https://geodaten.bayern.de/odd/a/laser/meta/kml"
KML_BY_LEVEL = {
    "regierungsbezirk": f"{KML_BASE}/regierungsbezirk.kml",
    "gemeinde": f"{KML_BASE}/gemeinde.kml",
}

# Native CRS of the tiling scheme and the tile edge length in metres.
TILE_CRS = "EPSG:25832"
TILE_SIZE_M = 1000

METALINK_NS = {"m": "urn:ietf:params:xml:ns:metalink"}
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

# "674_5403.laz" -> easting 674 km, northing 5403 km (lower-left corner).
TILE_NAME_RE = re.compile(r"^(?P<east_km>\d+)_(?P<north_km>\d+)\.laz$")

METALINK_HREF_RE = re.compile(
    r"https://geodaten\.bayern\.de/odd/a/laser/meta/metalink/[^\"'\s<>]+\.meta4"
)

USER_AGENT = (
    "laz-tile-index/1.0 (+https://geodaten.bayern.de/opengeodata/; "
    "builds a CSV index of OpenData LAZ tiles)"
)

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
class Unit:
    """One administrative unit offered in the Massendownload picker."""

    name: str
    metalink_url: str

    @property
    def key(self) -> str:
        return self.metalink_url.rsplit("/", 1)[-1].removesuffix(".meta4")


@dataclass
class Tile:
    tile: str
    url: str
    size_bytes: int
    sha256: str
    # A tile on a unit border is listed in several Metalinks; keep all names.
    units: list[str] = field(default_factory=list)

    @property
    def bbox_utm(self) -> tuple[int, int, int, int]:
        m = TILE_NAME_RE.match(self.tile)
        if not m:
            raise ValueError(f"unexpected tile name: {self.tile!r}")
        min_x = int(m["east_km"]) * 1000
        min_y = int(m["north_km"]) * 1000
        return min_x, min_y, min_x + TILE_SIZE_M, min_y + TILE_SIZE_M


def fetch(url: str, *, retries: int = 4, timeout: int = 300) -> bytes:
    """GET a URL with a couple of retries on transient failures."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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


def parse_units(kml_bytes: bytes) -> list[Unit]:
    """Pull (unit name, Metalink URL) out of the picker KML.

    The Metalink URL sits in an HTML-escaped ``<a href=...>`` inside each
    Placemark's ``<description>``.
    """
    root = ET.fromstring(kml_bytes)
    units: list[Unit] = []
    for placemark in root.iter(f"{{{KML_NS['k']}}}Placemark"):
        name_el = placemark.find("k:name", KML_NS)
        description_el = placemark.find("k:description", KML_NS)
        if name_el is None or description_el is None or not description_el.text:
            continue
        match = METALINK_HREF_RE.search(html.unescape(description_el.text))
        if match:
            units.append(Unit(name=(name_el.text or "").strip(), metalink_url=match[0]))
    return units


def parse_metalink(metalink_bytes: bytes) -> list[tuple[str, str, int, str]]:
    """Return (name, url, size, sha256) for every ``<file>`` in a Metalink."""
    root = ET.fromstring(metalink_bytes)
    files: list[tuple[str, str, int, str]] = []
    for file_el in root.findall("m:file", METALINK_NS):
        name = file_el.get("name")
        url_el = file_el.find("m:url", METALINK_NS)
        size_el = file_el.find("m:size", METALINK_NS)
        sha256_el = file_el.find("m:hash[@type='sha-256']", METALINK_NS)
        if name is None or url_el is None or not url_el.text:
            print(f"  skipping incomplete <file> entry: {name!r}", file=sys.stderr)
            continue
        files.append(
            (
                name,
                url_el.text.strip(),
                int(size_el.text) if size_el is not None and size_el.text else -1,
                (sha256_el.text or "").strip() if sha256_el is not None else "",
            )
        )
    return files


def collect_tiles(units: list[Unit], *, delay: float) -> "OrderedDict[str, Tile]":
    """Download every unit's Metalink and merge the entries, de-duplicating
    tiles that appear in more than one unit."""
    tiles: OrderedDict[str, Tile] = OrderedDict()
    for index, unit in enumerate(units, start=1):
        print(f"[{index}/{len(units)}] {unit.name} ({unit.key})", file=sys.stderr)
        entries = parse_metalink(fetch(unit.metalink_url))
        new = 0
        for name, url, size, sha256 in entries:
            existing = tiles.get(name)
            if existing is None:
                tiles[name] = Tile(name, url, size, sha256, [unit.name])
                new += 1
                continue
            existing.units.append(unit.name)
            # The same tile served from two Metalinks should be byte-identical;
            # if it is not, the source data is inconsistent and worth knowing.
            if existing.sha256 != sha256 or existing.size_bytes != size:
                print(
                    f"  WARNING: {name} differs between {existing.units[0]!r} "
                    f"and {unit.name!r} (size {existing.size_bytes} vs {size}, "
                    f"sha256 {existing.sha256} vs {sha256})",
                    file=sys.stderr,
                )
        print(f"  {len(entries)} files, {new} new (total {len(tiles)})", file=sys.stderr)
        if delay and index < len(units):
            time.sleep(delay)
    return tiles


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


def write_csv(tiles: "OrderedDict[str, Tile]", out_path: Path) -> None:
    to_wgs84 = make_wgs84_transformer()
    # Sort by tile coordinates so the CSV is stable across runs.
    ordered = sorted(tiles.values(), key=lambda t: t.bbox_utm)
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
                "units": "|".join(dict.fromkeys(tile.units)),
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
        default=Path("laz_tiles.csv"),
        help="CSV to write (default: %(default)s)",
    )
    parser.add_argument(
        "--per-gemeinde",
        dest="level",
        action="store_const",
        const="gemeinde",
        default="regierungsbezirk",
        help=(
            "scrape the 2229 municipality Metalinks instead of the 7 "
            "Regierungsbezirk ones; slower, but fills the 'units' column with "
            "municipality names"
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="seconds to wait between Metalink requests (default: %(default)s)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="only process the first N units (for a quick smoke test)",
    )
    args = parser.parse_args()

    kml_url = KML_BY_LEVEL[args.level]
    print(f"Fetching unit list from {kml_url}", file=sys.stderr)
    units = parse_units(fetch(kml_url))
    if not units:
        print("No Metalink URLs found in the KML - has the format changed?", file=sys.stderr)
        return 1
    print(f"Found {len(units)} units", file=sys.stderr)
    if args.limit:
        units = units[: args.limit]
        print(f"Limited to {len(units)} units", file=sys.stderr)

    tiles = collect_tiles(units, delay=args.delay)
    write_csv(tiles, args.output)

    total_bytes = sum(t.size_bytes for t in tiles.values() if t.size_bytes > 0)
    missing_hash = sum(1 for t in tiles.values() if not t.sha256)
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
