#!/usr/bin/env python3
"""Build input/laz_tiles.local.csv for Brandenburg from the local mirror.

The LGB server is too slow to feed a run directly, so its archives were mirrored unchanged to a
local HTTP server. This takes input/laz_tiles.csv, points each row at the mirror, and checks every
archive's size there with a HEAD request against the index. Tiles missing from the mirror, or of a
different size, are reported and left out.

    python3 scripts/build_local_tile_index.py input/laz_tiles.csv input/laz_tiles.local.csv
"""
import csv, re, sys, urllib.request, concurrent.futures

BASE = "http://192.168.193.220:10200/brandenburg/"
src, out = sys.argv[1], sys.argv[2]

with open(src, newline="") as f:
    rows = list(csv.DictReader(f))
html = urllib.request.urlopen(BASE).read().decode()
mirrored = set(re.findall(r'href="(als_33\d+-\d+\.zip)"', html))

def size(n):
    r = urllib.request.urlopen(urllib.request.Request(BASE + n, method="HEAD"))
    return int(r.headers["Content-Length"])

present = [r for r in rows if r["tile"] in mirrored]
with concurrent.futures.ThreadPoolExecutor(16) as ex:
    sizes = dict(zip((r["tile"] for r in present), ex.map(size, (r["tile"] for r in present))))

missing = [r["tile"] for r in rows if r["tile"] not in mirrored]
wrong = [r["tile"] for r in present if sizes[r["tile"]] != int(r["size_bytes"])]
extra = sorted(mirrored - {r["tile"] for r in rows})
keep = [dict(r, url=BASE + r["tile"]) for r in present if r["tile"] not in wrong]

with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader(); w.writerows(keep)
print(f"{len(keep)} rows; {len(missing)} missing from the mirror, {len(wrong)} size mismatches, "
      f"{len(extra)} on the mirror but not in the index")
for label, l in (("missing", missing), ("size mismatch", wrong), ("not in index", extra)):
    for n in l[:20]:
        print(f"  {label}: {n}")
