# Nordrhein-Westfalen LAZ tile index

`laz_tiles.csv` lists every LAZ tile of the *3D-Messdaten aus dem
Laserscanning* product that Geobasis NRW publishes as OpenData under
[dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0).

**35,860 tiles, 3.17 TiB total** (index generated 2026-08-02 from an index
published 2026-07-28).

NRW is the only state besides Bavaria and RLP with a genuine flat index:

* <https://www.opengeodata.nrw.de/produkte/geobasis/hm/3dm_l_las/3dm_l_las/index.json>

It gives a name, a byte size and a timestamp per tile — and no hash. NRW
publishes none anywhere: the sibling `3dm_meta.zip` holds `3dm_nw.csv`, which
is per-tile acquisition metadata (date, method, accuracy, CRS) with no hash
column, and the server has no `.md5`/`.sha256` sidecars and no Metalink.

Its `sha256` column is therefore empty. mapant-nf treats the checksum as
optional and verifies each download against `size_bytes` instead, which catches
the common failure, a truncated transfer, so the CSV is runnable as it is. If
you want the checksums anyway, the only honest way to get them is to compute
them:

```sh
uv run scripts/build_laz_tile_index.py -o input/laz_tiles.csv \
    --fill-sha256 --jobs 8
```

This streams each tile and hashes it in flight. It needs **no disk**, resumes
from a partially filled CSV (re-run the same command), and costs a one-off
~3.2 TiB of transfer -- about as much as a single rendering pass over the same
data would download anyway. Tiles that fail are reported and left blank rather
than guessed.

## Verification

`3dm_32_280_5652_1_nw.laz` is the 1 km × 1 km tile with its **lower-left**
corner at easting 280 km / northing 5652 km in EPSG:25832; all 35,860 names
parse and all are in zone 32. LAS public headers of random tiles confirm it
(e.g. `280000.00 … 280999.99` × `5652000.00 … 5652999.99`), and
`--verify-headers N` re-runs the check. A hash produced by `--fill-sha256` was
confirmed against an independent download of the same tile.

## Regenerating

```sh
# cheap: everything except the checksums -- what laz_tiles.csv is
uv run scripts/build_laz_tile_index.py -o input/laz_tiles.csv

# optional, expensive but resumable: fill them in
uv run scripts/build_laz_tile_index.py -o input/laz_tiles.csv --fill-sha256
```
