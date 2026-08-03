#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyproj"]
# ///
"""Build tiles CSVs for the German states that publish their LiDAR point
clouds as **per-tile ZIP archives** rather than as bare .laz files.

Covers four sources, each with a different way of being enumerated:

    sachsen       4989 x 2 km  EPSG:25833  Nextcloud share, tile list from a
                                           grid encoded in the portal's JS
    brandenburg  13086 x 1 km  EPSG:25833  plain Apache directory listing
    thueringen   ~16000 x 1 km EPSG:25832  GeoJSON query API, result-capped,
                                           so the bbox is subdivided
    berlin           8 bundles EPSG:25833  ATOM feed; each ZIP holds many
                                           tiles, see the caveat below

None of them publishes a checksum and none publishes a per-file size in
machine-readable form, so this script probes every candidate URL once: that
resolves existence (404s are dropped) *and* the exact byte size, in a single
range request per tile.  ``--fill-sha256`` then streams and hashes each archive
the way the NRW indexer does.

The ``tile`` column ends in ``.zip``.  That is deliberate -- these rows name
the file the pipeline has to fetch -- but it does not satisfy mapant-nf's
current ``^...\\.(laz|las)$`` pattern, so it needs the pipeline-side unzip
support to be in place first.

Berlin is the odd one out
-------------------------
Berlin does not publish per-tile URLs at all: its ~200 GB is packed into 8
regional ZIPs of 1-37 GB.  One row therefore describes a *bundle*, not a tile,
and its bounding box is the union of the tiles inside it -- which is far too
coarse for the pipeline's grid planning.  The member list is read out of each
ZIP's central directory over HTTP range requests (no download), so
``--members-csv`` can write the true per-tile manifest alongside it.  Treat the
Berlin CSV as a coverage description, not as something to run as-is.

Usage
-----
    uv run scripts/build_zip_tile_index.py --source sachsen \
        -o input/laz_tiles_sachsen.nosha256.csv --jobs 16
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = (
    "laz-tile-index/1.0 (+https://github.com/grst/mapant-nf; "
    "builds a CSV index of OpenData LiDAR tiles)"
)

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
    # Extra, ignored by the schema: the .laz member inside the archive. Each
    # source names it differently enough that guessing it is a trap -- Sachsen
    # turns the `_laz` suffix back into an extension -- so it is recorded here
    # for whatever does the unzipping. Empty for Berlin, whose archives hold
    # hundreds of members (see --members-csv).
    "inner_laz",
]

# ---------------------------------------------------------------- sources ---

SACHSEN_BATCH_URL = "https://www.geodaten.sachsen.de/batch-download-4719.html"
SACHSEN_DAV = "https://geocloud.landesvermessung.sachsen.de/public.php/dav/files"

BRANDENBURG_LISTING = "https://data.geobasis-bb.de/geobasis/daten/als/laz/"

THUERINGEN_API = (
    "https://geoportal.geoportal-th.de/gaialight-th/_apps/dladownload/"
    "_ajax/overview.php"
)
THUERINGEN_DL = "https://geoportal.geoportal-th.de/hoehendaten/LAS"
# The portal's own object types; the year range is also the directory name.
THUERINGEN_EPOCHS = {
    "dhm1": "2014-2019",
    "dhm2": "2010-2013",
    "dhm5": "1996-2006",
}
# Generous cover of Thuringia in EPSG:25832, subdivided until the API stops
# answering "tooManyObjects".
THUERINGEN_EXTENT = (555000, 5545000, 765000, 5735000)
THUERINGEN_CHUNK_M = 10000

BERLIN_ATOM = "https://gdi.berlin.de/data/a_als/atom/0.atom"


@dataclass
class Tile:
    tile: str
    url: str
    crs: str
    min_x: int
    min_y: int
    max_x: int
    max_y: int
    units: str
    size_bytes: int = -1
    sha256: str = ""
    inner_laz: str = ""
    # Berlin only: the .las members packed into this archive.
    members: list[str] = field(default_factory=list)

    @property
    def bbox_utm(self) -> tuple[int, int, int, int]:
        return self.min_x, self.min_y, self.max_x, self.max_y


# ------------------------------------------------------------------ http ---


def open_url(url: str, *, retries: int = 4, timeout: int = 300, headers=None, method=None):
    """Open a URL with a couple of retries on transient failures.

    Returns the live response; the caller closes it.  4xx is raised straight
    away because it is an answer, not a failure -- callers use that to detect
    tiles that do not exist.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}, method=method
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except (urllib.error.URLError, TimeoutError) as error:
            if isinstance(error, urllib.error.HTTPError) and 400 <= error.code < 500:
                raise
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            last_error = error
            if attempt < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"failed to fetch {url}") from last_error


def fetch(url: str, **kwargs) -> bytes:
    with open_url(url, **kwargs) as response:
        return response.read()


def range_get(url: str, start: int, end: int) -> bytes:
    return fetch(url, headers={"Range": f"bytes={start}-{end}"})


def probe_size(url: str, *, prefer_range: bool = False) -> int | None:
    """Exact byte size of `url`, or None if it does not exist.

    HEAD is the cheap way, but Sachsen's Nextcloud answers 401 to HEAD on a
    public share while happily serving ranged GETs, so a one-byte range request
    is the fallback -- its Content-Range carries the total. `prefer_range`
    skips straight to it for sources known to reject HEAD.

    An `HTTPError` is itself an open response. Python only closes it when it is
    garbage collected, and under a thread pool that is late enough to exhaust
    the connection pool and wedge every worker, so each one is closed
    explicitly.
    """
    if not prefer_range:
        try:
            with open_url(url, method="HEAD") as response:
                length = response.headers.get("Content-Length")
                if length:
                    return int(length)
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 404:
                return None
            # 401/405 on HEAD is a server quirk, not an answer about the file.
        except Exception:  # noqa: BLE001 - fall through to the range probe
            pass

    try:
        with open_url(url, headers={"Range": "bytes=0-0"}) as response:
            response.read()  # drain, so the socket is reusable/closable
            content_range = response.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)$", content_range)
            if m:
                return int(m.group(1))
            length = response.headers.get("Content-Length")
            return int(length) if length else None
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            return None
        raise


# -------------------------------------------------------------- sachsen ----


def enumerate_sachsen() -> list[Tile]:
    """Rebuild the LSC tile list from the portal's batch-download page.

    The page embeds ``batchConfig.mapping`` (per municipality, a run-length
    encoded list of 1 km grid cells) and ``batchConfig.products`` (the file
    name template and the Nextcloud share id).  Its own JS aggregates the 1 km
    cells to the product's package size and substitutes them into the
    template; this reproduces that exactly.

    A grid cell is a 7-character string: 3 digits of easting in km followed by
    4 digits of northing in km.
    """
    page = fetch(SACHSEN_BATCH_URL).decode("utf-8", "replace")

    products_match = re.search(r"batchConfig\.products\s*=\s*(\{.*?\})\s*\n", page, re.S)
    mapping_match = re.search(r"batchConfig\.mapping\s*=\s*(\{.*?\})\s*\n", page, re.S)
    if not products_match or not mapping_match:
        raise RuntimeError("batchConfig not found in the page - has it changed?")
    products = json.loads(products_match.group(1))
    mapping = json.loads(mapping_match.group(1))

    product = products.get("LSC")
    if product is None:
        raise RuntimeError(f"no LSC product (found {sorted(products)})")
    resolution_km = int(product["packagesize"]) // 1000
    template = product["filename"]
    share_id = product["share_id"]

    # Decode the run-length encoded 1 km cells, then floor to the package grid.
    cells: set[tuple[int, int]] = set()
    for entry in mapping.values():
        grid = entry["grid_id"]
        for i in range(0, len(grid), 2):
            start, count = int(grid[i]), int(grid[i + 1])
            east = int(str(start)[:3])
            north = int(str(start)[3:7])
            for offset in range(count):
                cells.add((east, north + offset))
    aggregated = {
        (east // resolution_km * resolution_km, north // resolution_km * resolution_km)
        for east, north in cells
    }

    tiles: list[Tile] = []
    for east, north in sorted(aggregated):
        name = template.replace("$Rechtswert$", str(east)).replace(
            "$Hochwert$", str(north)
        )
        tiles.append(
            Tile(
                tile=name,
                url=f"{SACHSEN_DAV}/{share_id}/{name}",
                crs="EPSG:25833",
                min_x=east * 1000,
                min_y=north * 1000,
                max_x=(east + resolution_km) * 1000,
                max_y=(north + resolution_km) * 1000,
                units="Sachsen",
                inner_laz=name.removesuffix("_laz.zip") + ".laz",
            )
        )
    return tiles


# --------------------------------------------------------- brandenburg -----

BRANDENBURG_NAME_RE = re.compile(r"^als_(?P<zone>\d{2})(?P<east_km>\d{3})-(?P<north_km>\d{4})\.zip$")


def enumerate_brandenburg() -> list[Tile]:
    """Read the Apache listing.  Names are ``als_33<east>-<north>.zip``, 1 km."""
    listing = fetch(BRANDENBURG_LISTING).decode("utf-8", "replace")
    names = sorted(
        {href for href in re.findall(r'href="([^"]+)"', listing) if href.endswith(".zip")}
    )
    tiles: list[Tile] = []
    for name in names:
        m = BRANDENBURG_NAME_RE.match(name)
        if not m:
            print(f"  skipping unparseable name {name!r}", file=sys.stderr)
            continue
        if m["zone"] != "33":
            raise ValueError(f"{name!r} is not in UTM zone 33")
        east = int(m["east_km"]) * 1000
        north = int(m["north_km"]) * 1000
        tiles.append(
            Tile(
                tile=name,
                url=BRANDENBURG_LISTING + name,
                crs="EPSG:25833",
                min_x=east,
                min_y=north,
                max_x=east + 1000,
                max_y=north + 1000,
                units="Brandenburg",
                inner_laz=name.removesuffix(".zip") + ".laz",
            )
        )
    return tiles


# ----------------------------------------------------------- thueringen ----

THUERINGEN_TITLE_RE = re.compile(r"^(?P<east_km>\d{3})_(?P<north_km>\d{4})_1x1km$")


def _thueringen_query(bbox: tuple[int, int, int, int], obj_type: str):
    query = urllib.parse.urlencode(
        {
            "bbox": ",".join(str(v) for v in bbox),
            "crs": "EPSG:25832",
            "type[]": obj_type,
        }
    )
    document = json.loads(fetch(f"{THUERINGEN_API}?{query}", timeout=120))
    if not document.get("success"):
        if document.get("reason") == "tooManyObjects":
            return None
        raise RuntimeError(f"query failed: {document.get('message')}")
    return document["result"]["features"]


def enumerate_thueringen(obj_type: str, jobs: int = 8) -> list[Tile]:
    """Walk the download app's GeoJSON API over a grid of bboxes.

    The API refuses any query that would return too many objects, so a chunk
    that comes back as ``tooManyObjects`` is split into quarters and requeued.
    Boxes are worked in parallel: there are several hundred of them and each
    round trip is ~1 s, so doing this sequentially dominates the runtime.
    """
    epoch = THUERINGEN_EPOCHS[obj_type]
    min_x, min_y, max_x, max_y = THUERINGEN_EXTENT

    pending: list[tuple[int, int, int, int]] = []
    for x in range(min_x, max_x, THUERINGEN_CHUNK_M):
        for y in range(min_y, max_y, THUERINGEN_CHUNK_M):
            pending.append((x, y, min(x + THUERINGEN_CHUNK_M, max_x), min(y + THUERINGEN_CHUNK_M, max_y)))

    found: dict[str, tuple[int, int]] = {}
    lock = threading.Lock()
    processed = 0
    total_seen = len(pending)

    def handle(box):
        nonlocal processed
        features = _thueringen_query(box, obj_type)
        if features is None:
            # Too many results: split into quarters and retry.
            mx = (box[0] + box[2]) // 2
            my = (box[1] + box[3]) // 2
            if mx <= box[0] or my <= box[1]:
                raise RuntimeError(f"cannot subdivide {box} any further")
            return [
                (box[0], box[1], mx, my),
                (mx, box[1], box[2], my),
                (box[0], my, mx, box[3]),
                (mx, my, box[2], box[3]),
            ]
        with lock:
            processed += 1
            for feature in features:
                title = feature["properties"]["title"]
                m = THUERINGEN_TITLE_RE.match(title)
                if not m:
                    print(f"  skipping unparseable title {title!r}", file=sys.stderr)
                    continue
                found[title] = (int(m["east_km"]), int(m["north_km"]))
            if processed % 50 == 0:
                print(
                    f"  {processed}/{total_seen} boxes done, {len(found)} tiles",
                    file=sys.stderr,
                )
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        while pending:
            batch, pending = pending, []
            for extra in pool.map(handle, batch):
                pending.extend(extra)
            total_seen += len(pending)

    tiles: list[Tile] = []
    for east_km, north_km in sorted(found.values()):
        name = f"las_{east_km}_{north_km}_1_th_{epoch}.zip"
        tiles.append(
            Tile(
                tile=name,
                url=f"{THUERINGEN_DL}/las_{epoch}/{name}",
                crs="EPSG:25832",
                min_x=east_km * 1000,
                min_y=north_km * 1000,
                max_x=east_km * 1000 + 1000,
                max_y=north_km * 1000 + 1000,
                units=f"Thüringen {epoch}",
                inner_laz=name.removesuffix(".zip") + ".laz",
            )
        )
    return tiles


# ---------------------------------------------------------------- berlin ---

BERLIN_MEMBER_RE = re.compile(
    r"^3dm_(?P<zone>\d{2})_(?P<east_km>\d{3})_(?P<north_km>\d{4})_1_be\.(?:las|laz)$"
)


def read_zip_members(url: str, size: int) -> list[tuple[str, int]]:
    """Read a remote ZIP's central directory over HTTP range requests.

    Returns (name, uncompressed size) per member without downloading the
    payload.  Handles the ZIP64 records, which the larger Berlin bundles need.
    """
    tail_len = min(size, 1 << 16)
    tail = range_get(url, size - tail_len, size - 1)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise RuntimeError(f"no end-of-central-directory in {url}")
    cd_size = struct.unpack_from("<I", tail, eocd + 12)[0]
    cd_offset = struct.unpack_from("<I", tail, eocd + 16)[0]

    # 0xffffffff is the ZIP64 escape; the real values live in the ZIP64 EOCD.
    if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        locator = tail.rfind(b"PK\x06\x07")
        if locator < 0:
            raise RuntimeError(f"ZIP64 locator missing in {url}")
        zip64_eocd_offset = struct.unpack_from("<Q", tail, locator + 8)[0]
        header = range_get(url, zip64_eocd_offset, zip64_eocd_offset + 55)
        if header[:4] != b"PK\x06\x06":
            raise RuntimeError(f"bad ZIP64 EOCD in {url}")
        cd_size = struct.unpack_from("<Q", header, 40)[0]
        cd_offset = struct.unpack_from("<Q", header, 48)[0]

    directory = range_get(url, cd_offset, cd_offset + cd_size - 1)
    members: list[tuple[str, int]] = []
    pos = 0
    while pos < len(directory) and directory[pos : pos + 4] == b"PK\x01\x02":
        uncompressed = struct.unpack_from("<I", directory, pos + 24)[0]
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", directory, pos + 28)
        name = directory[pos + 46 : pos + 46 + name_len].decode("utf-8", "replace")
        members.append((name, uncompressed))
        pos += 46 + name_len + extra_len + comment_len
    return members


def enumerate_berlin() -> list[Tile]:
    """One row per regional bundle, with the bbox read from its contents."""
    feed = fetch(BERLIN_ATOM).decode("utf-8-sig")
    links = sorted(
        {
            href
            for href in re.findall(r'<link[^>]*href="([^"]+)"', feed)
            if href.endswith(".zip")
        }
    )
    if not links:
        raise RuntimeError("no .zip links in the Berlin ATOM feed")

    tiles: list[Tile] = []
    for url in links:
        name = url.rsplit("/", 1)[-1]
        size = probe_size(url)
        if size is None:
            print(f"  {name}: 404, skipping", file=sys.stderr)
            continue
        members = read_zip_members(url, size)
        boxes = []
        member_names = []
        for member_name, _ in members:
            m = BERLIN_MEMBER_RE.match(member_name.rsplit("/", 1)[-1])
            if not m:
                continue
            if m["zone"] != "33":
                raise ValueError(f"{member_name!r} is not in UTM zone 33")
            east = int(m["east_km"]) * 1000
            north = int(m["north_km"]) * 1000
            boxes.append((east, north, east + 1000, north + 1000))
            member_names.append(member_name)
        if not boxes:
            print(f"  {name}: no recognisable tiles inside, skipping", file=sys.stderr)
            continue
        print(f"  {name}: {size / 1024**3:.1f} GiB, {len(boxes)} tiles", file=sys.stderr)
        tiles.append(
            Tile(
                tile=name,
                url=url,
                crs="EPSG:25833",
                min_x=min(b[0] for b in boxes),
                min_y=min(b[1] for b in boxes),
                max_x=max(b[2] for b in boxes),
                max_y=max(b[3] for b in boxes),
                units=f"Berlin {Path(name).stem}",
                size_bytes=size,
                members=sorted(member_names),
            )
        )
    return tiles


SOURCES = {
    "sachsen": enumerate_sachsen,
    "brandenburg": enumerate_brandenburg,
    "thueringen": enumerate_thueringen,
    "berlin": enumerate_berlin,
}


# ------------------------------------------------------------- probing -----


def probe_sizes(tiles: list[Tile], jobs: int, prefer_range: bool = False) -> list[Tile]:
    """Fill in size_bytes, dropping tiles the server does not have."""
    todo = [t for t in tiles if t.size_bytes < 0]
    if not todo:
        return tiles
    lock = threading.Lock()
    state = {"done": 0, "missing": 0, "failed": 0}
    started = time.monotonic()

    def worker(tile: Tile) -> None:
        try:
            size = probe_size(tile.url, prefer_range=prefer_range)
        except Exception as error:  # noqa: BLE001 - report and keep going
            with lock:
                state["failed"] += 1
                print(f"  ERROR {tile.tile}: {error}", file=sys.stderr)
            return
        with lock:
            state["done"] += 1
            if size is None:
                state["missing"] += 1
            else:
                tile.size_bytes = size
            if state["done"] % 500 == 0 or state["done"] == len(todo):
                rate = state["done"] / max(time.monotonic() - started, 1e-9)
                print(
                    f"  {state['done']}/{len(todo)} probed, "
                    f"{state['missing']} absent, {rate:.0f}/s",
                    file=sys.stderr,
                )

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(worker, todo))

    if state["failed"]:
        print(
            f"  WARNING: {state['failed']} tile(s) could not be probed and are "
            "dropped; re-run to retry them",
            file=sys.stderr,
        )
    kept = [t for t in tiles if t.size_bytes > 0]
    print(
        f"  {len(kept)} tiles exist, {len(tiles) - len(kept)} dropped",
        file=sys.stderr,
    )
    return kept


def load_cached(path: Path) -> dict[str, tuple[int, str]]:
    """Read (size, sha256) per tile from an earlier run.

    Probing 13k URLs takes half an hour against the slower portals, so a re-run
    should not repeat it. Sizes are reused as-is; a hash is only reused when the
    size still matches, so a republished archive loses its stale hash.
    """
    if not path or not path.exists():
        return {}
    cached: dict[str, tuple[int, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                size = int(row["size_bytes"])
            except (KeyError, ValueError):
                continue
            sha256 = (row.get("sha256") or "").strip()
            cached[row["tile"]] = (size, sha256 if len(sha256) == 64 else "")
    return cached


def fill_sha256(tiles: list[Tile], cached: dict[str, tuple[int, str]], jobs: int) -> int:
    for tile in tiles:
        size, sha256 = cached.get(tile.tile, (None, ""))
        tile.sha256 = sha256 if size == tile.size_bytes else ""
    todo = [t for t in tiles if not t.sha256]
    print(
        f"  {len(tiles) - len(todo)} hashes reused, {len(todo)} to compute "
        f"({sum(t.size_bytes for t in todo) / 1024**4:.2f} TiB to transfer)",
        file=sys.stderr,
    )
    if not todo:
        return 0

    lock = threading.Lock()
    state = {"done": 0, "bytes": 0, "failed": 0}
    started = time.monotonic()

    def worker(tile: Tile) -> None:
        digest = hashlib.sha256()
        total = 0
        try:
            with open_url(tile.url) as response:
                while chunk := response.read(HASH_CHUNK):
                    digest.update(chunk)
                    total += len(chunk)
        except Exception as error:  # noqa: BLE001 - one bad tile must not stop the pass
            with lock:
                state["failed"] += 1
                print(f"  FAILED {tile.tile}: {error}", file=sys.stderr)
            return
        if total != tile.size_bytes:
            with lock:
                print(
                    f"  WARNING: {tile.tile} is {total} bytes, probe said "
                    f"{tile.size_bytes}; using the served size",
                    file=sys.stderr,
                )
            tile.size_bytes = total
        tile.sha256 = digest.hexdigest()
        with lock:
            state["done"] += 1
            state["bytes"] += total
            if state["done"] % 100 == 0 or state["done"] == len(todo):
                elapsed = max(time.monotonic() - started, 1e-9)
                print(
                    f"  {state['done']}/{len(todo)} hashed, "
                    f"{state['bytes'] / 1024**3:.1f} GiB, "
                    f"{state['bytes'] / elapsed / 1024**2:.0f} MiB/s",
                    file=sys.stderr,
                )

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(worker, todo))
    return state["failed"]


# ------------------------------------------------------------------ csv ----


def make_wgs84_transformer(crs: str):
    try:
        from pyproj import Transformer
    except ImportError:
        print(
            "pyproj not installed - leaving the lon/lat columns empty "
            "(run via `uv run` to get them)",
            file=sys.stderr,
        )
        return None
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

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
    crs_values = {t.crs for t in tiles}
    if len(crs_values) != 1:
        raise RuntimeError(f"mixed CRS in one CSV: {crs_values}")
    to_wgs84 = make_wgs84_transformer(next(iter(crs_values)))
    ordered = sorted(tiles, key=lambda t: t.bbox_utm)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for tile in ordered:
            row = {
                "tile": tile.tile,
                "url": tile.url,
                "size_bytes": tile.size_bytes,
                "sha256": tile.sha256,
                "crs": tile.crs,
                "min_x": tile.min_x,
                "min_y": tile.min_y,
                "max_x": tile.max_x,
                "max_y": tile.max_y,
                "min_lon": "",
                "min_lat": "",
                "max_lon": "",
                "max_lat": "",
                "units": tile.units,
                "inner_laz": tile.inner_laz,
            }
            if to_wgs84 is not None:
                min_lon, min_lat, max_lon, max_lat = to_wgs84(
                    tile.min_x, tile.min_y, tile.max_x, tile.max_y
                )
                row |= {
                    "min_lon": f"{min_lon:.7f}",
                    "min_lat": f"{min_lat:.7f}",
                    "max_lon": f"{max_lon:.7f}",
                    "max_lat": f"{max_lat:.7f}",
                }
            writer.writerow(row)


def write_members_csv(tiles: list[Tile], out_path: Path) -> int:
    """Berlin: the per-tile manifest hidden inside the bundles."""
    rows = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["member", "archive", "archive_url", "crs", "min_x", "min_y", "max_x", "max_y"])
        for tile in sorted(tiles, key=lambda t: t.tile):
            for member in tile.members:
                m = BERLIN_MEMBER_RE.match(member.rsplit("/", 1)[-1])
                if not m:
                    continue
                east = int(m["east_km"]) * 1000
                north = int(m["north_km"]) * 1000
                writer.writerow(
                    [member, tile.tile, tile.url, tile.crs, east, north, east + 1000, north + 1000]
                )
                rows += 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--thueringen-type",
        default="dhm1",
        choices=sorted(THUERINGEN_EPOCHS),
        help="Thuringia epoch: dhm1=2014-2019 (default, best density), "
        "dhm2=2010-2013, dhm5=1996-2006",
    )
    parser.add_argument(
        "--members-csv",
        type=Path,
        help="Berlin only: also write the per-tile manifest of the bundles",
    )
    parser.add_argument("--jobs", type=int, default=16, help="concurrent requests")
    parser.add_argument(
        "--fill-sha256",
        action="store_true",
        help="stream every archive and hash it; without this the sha256 column "
        "is empty and mapant-nf will reject the CSV",
    )
    parser.add_argument("--resume-from", type=Path, help="reuse sha256 from an earlier CSV")
    parser.add_argument("--limit", type=int, help="only the first N tiles (smoke test)")
    args = parser.parse_args()

    print(f"Enumerating {args.source}", file=sys.stderr)
    if args.source == "thueringen":
        tiles = enumerate_thueringen(args.thueringen_type, args.jobs)
    else:
        tiles = SOURCES[args.source]()
    if not tiles:
        print("No tiles found - has the source changed?", file=sys.stderr)
        return 1
    print(f"{len(tiles)} candidate tiles", file=sys.stderr)

    duplicates = len(tiles) - len({t.tile for t in tiles})
    if duplicates:
        print(f"WARNING: {duplicates} duplicate tile names", file=sys.stderr)

    if args.limit:
        tiles = tiles[: args.limit]
        print(f"Limited to {len(tiles)} tiles", file=sys.stderr)

    cached = load_cached(args.resume_from or args.output)
    if cached:
        print(f"Reusing {len(cached)} probed sizes from an earlier run", file=sys.stderr)
        for tile in tiles:
            if tile.tile in cached:
                tile.size_bytes = cached[tile.tile][0]

    print(f"Probing sizes with {args.jobs} workers", file=sys.stderr)
    tiles = probe_sizes(tiles, args.jobs, prefer_range=args.source == "sachsen")
    if not tiles:
        print("Nothing left after probing", file=sys.stderr)
        return 1

    failed = 0
    if args.fill_sha256:
        print(f"Hashing with {args.jobs} streams", file=sys.stderr)
        failed = fill_sha256(tiles, cached, args.jobs)

    write_csv(tiles, args.output)
    total = sum(t.size_bytes for t in tiles)
    missing_hash = sum(1 for t in tiles if not t.sha256)
    print(
        f"Wrote {len(tiles)} rows to {args.output} ({total / 1024**4:.2f} TiB total)",
        file=sys.stderr,
    )

    if args.members_csv:
        rows = write_members_csv(tiles, args.members_csv)
        print(f"Wrote {rows} member rows to {args.members_csv}", file=sys.stderr)

    if missing_hash:
        print(
            f"WARNING: {missing_hash} rows have no SHA-256; this source publishes "
            "none, so run --fill-sha256 (resumable) before using the CSV.",
            file=sys.stderr,
        )
    if failed:
        print(f"WARNING: {failed} archive(s) could not be hashed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
