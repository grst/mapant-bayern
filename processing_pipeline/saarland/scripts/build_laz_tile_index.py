#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyproj"]
# ///
"""Build input/laz_tiles.local.csv for Saarland from the local mirror.

Saarland hands out its 2025 point cloud (thinned to 4 pts/m^2) as one ZIP per Landkreis. Those
were unpacked into one folder per Landkreis (LIDAR_laz_<LK>/) on a local HTTP server. This lists
every folder, takes each file's exact size from a HEAD request, and derives the 1 km box from the
name: 3dm_32_308_5488_1_SL_2025_050.laz is 308-309 km E, 5488-5489 km N, EPSG:25832.

Tiles on a Landkreis border are in each Landkreis' ZIP (3,076 files, 2,775 tiles); the first
copy is kept, and a copy of different size is reported. No checksums.

    uv run scripts/build_laz_tile_index.py input/laz_tiles.local.csv
"""
import csv, re, sys, urllib.request, concurrent.futures
from pyproj import Transformer

BASE = "http://192.168.193.220:10200/saarland/OD_LIDAR_Punktwolke_2025_laz_LK/"
out = sys.argv[1]
root = urllib.request.urlopen(BASE).read().decode()
dirs = sorted(set(re.findall(r'href="(LIDAR_laz_[A-Z]+/)"', root)))
urls = []
for d in dirs:
    html = urllib.request.urlopen(BASE + d).read().decode()
    urls += [BASE + d + n for n in sorted(set(re.findall(r'href="(3dm_32_\d+_\d+_1_SL_2025_050\.laz)"', html)))]

def size(u):
    r = urllib.request.urlopen(urllib.request.Request(u, method="HEAD"))
    return int(r.headers["Content-Length"])

with concurrent.futures.ThreadPoolExecutor(16) as ex:
    sizes = dict(zip(urls, ex.map(size, urls)))

# Border tiles appear in several district folders; keep the first copy.
tiles = {}
for u in urls:
    n = u.rsplit("/", 1)[1]
    if n in tiles:
        if sizes[tiles[n]] != sizes[u]:
            print(f"WARNING: size mismatch for {n}: {tiles[n]} vs {u}", file=sys.stderr)
        continue
    tiles[n] = u

tr = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
rows = []
for n, u in tiles.items():
    e, nn = map(int, re.match(r"3dm_32_(\d+)_(\d+)_1_SL", n).groups())
    x0, y0, x1, y1 = e * 1000, nn * 1000, e * 1000 + 1000, nn * 1000 + 1000
    lons, lats = tr.transform([x0, x1, x1, x0], [y0, y0, y1, y1])
    rows.append(dict(tile=n, url=u, size_bytes=sizes[u], sha256="", crs="EPSG:25832",
        min_x=x0, min_y=y0, max_x=x1, max_y=y1,
        min_lon=f"{min(lons):.7f}", min_lat=f"{min(lats):.7f}",
        max_lon=f"{max(lons):.7f}", max_lat=f"{max(lats):.7f}", units="Saarland"))
rows.sort(key=lambda r: (r["min_x"], r["min_y"]))
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader(); w.writerows(rows)
print(len(urls), "files,", len(rows), "unique tiles")
