#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyproj"]
# ///
"""Build input/laz_tiles.local.csv for Berlin from the local mirror.

Berlin publishes its ALS only as 8 regional ZIPs (see input/download_berlin_laz.sh). Those were
unpacked, the .las converted to .laz, and the 1,066 tiles served from a local HTTP server. This
lists that directory, takes each file's exact size from a HEAD request, and derives the 1 km box
from the name: 3dm_33_369_5808_1_be.laz is 369-370 km E, 5808-5809 km N, EPSG:25833. No checksums.

    uv run scripts/build_laz_tile_index.py input/laz_tiles.local.csv
"""
import csv, re, sys, urllib.request, concurrent.futures
from pyproj import Transformer

BASE = "http://192.168.193.220:10200/berlin/berlin_als/zip/"
out = sys.argv[1]
html = urllib.request.urlopen(BASE).read().decode()
names = sorted(set(re.findall(r'href="(3dm_33_\d+_\d+_1_be\.laz)"', html)))

def size(n):
    r = urllib.request.urlopen(urllib.request.Request(BASE + n, method="HEAD"))
    return int(r.headers["Content-Length"])

with concurrent.futures.ThreadPoolExecutor(16) as ex:
    sizes = dict(zip(names, ex.map(size, names)))

tr = Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True)
rows = []
for n in names:
    e, nn = map(int, re.match(r"3dm_33_(\d+)_(\d+)_1_be", n).groups())
    x0, y0, x1, y1 = e * 1000, nn * 1000, e * 1000 + 1000, nn * 1000 + 1000
    lons, lats = tr.transform([x0, x1, x1, x0], [y0, y0, y1, y1])
    rows.append(dict(tile=n, url=BASE + n, size_bytes=sizes[n], sha256="", crs="EPSG:25833",
        min_x=x0, min_y=y0, max_x=x1, max_y=y1,
        min_lon=f"{min(lons):.7f}", min_lat=f"{min(lats):.7f}",
        max_lon=f"{max(lons):.7f}", max_lat=f"{max(lats):.7f}", units="Berlin"))
rows.sort(key=lambda r: (r["min_x"], r["min_y"]))
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader(); w.writerows(rows)
print(len(rows), "rows")
