# OpenData LAZ tile indices

One CSV per source, each satisfying mapant-nf's
[tiles CSV contract](https://github.com/grst/mapant-nf/blob/main/assets/schema_tiles.json):

| file | source | tiles | volume | runnable |
| --- | --- | --- | --- | --- |
| `laz_tiles.csv` | Bayern | 71,979 | 13.66 TiB | yes |
| `laz_tiles_rlp.csv` | Rheinland-Pfalz | 21,207 | 4.71 TiB | yes |
| `laz_tiles_nrw.nosha256.csv` | Nordrhein-Westfalen | 35,860 | 3.17 TiB | **no — see below** |

All three share the same columns and the same CRS (`EPSG:25832`), so a run only
differs by `tiles_csv` and the matching `osm_pbf`.

For why only these three, and what the other 13 states publish, see
[`../docs/lidar_open_data_germany.md`](../docs/lidar_open_data_germany.md).

## Bayern — `laz_tiles.csv`

`laz_tiles.csv` lists every LAZ tile (airborne laserscanning point cloud) that the
Bayerische Vermessungsverwaltung publishes as OpenData under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de) on the
[OpenData portal](https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=laserdaten).

**71,979 tiles, 13.66 TiB total** (index generated 2026-07-29 from Metalinks
published 2026-07-28).

### Is there an official list?

No. The portal offers the data either tile-by-tile through a map picker, or as a
"Massendownload" per administrative unit or per drawn polygon — the polygon
selection is capped at a small area, so it cannot be used to grab all of Bavaria
at once. There is no published flat index, no ATOM/OpenSearch download service
and no WFS tile index.

What *is* official and machine-readable are the
[Metalink 4.0](https://datatracker.ietf.org/doc/html/rfc5854) files that back the
Massendownload. They are static URLs and already carry the file name, byte size,
SHA-256 and download URL for each tile. The picker's KML exists at two
granularities — 2,229 municipalities and 7 Regierungsbezirke — and the 7
Regierungsbezirke tile the whole state, so the entire index is reachable in
7 requests. That is what `scripts/build_laz_tile_index.py` does.

### CSV columns

The other two CSVs use the same columns, with `units` naming the state instead
of a Regierungsbezirk.

| column | meaning |
| --- | --- |
| `tile` | file name, e.g. `674_5403.laz` |
| `url` | direct download link |
| `size_bytes` | file size as declared in the Metalink |
| `sha256` | SHA-256 as declared in the Metalink |
| `crs` | CRS of the `min_*`/`max_*` columns — always `EPSG:25832` |
| `min_x`, `min_y`, `max_x`, `max_y` | tile bounding box in EPSG:25832 (metres) |
| `min_lon`, `min_lat`, `max_lon`, `max_lat` | same box in WGS84 (EPSG:4326), degrees |
| `units` | Regierungsbezirk(e) whose Metalink listed the tile, `\|`-separated |

Rows are sorted by `(min_x, min_y)`, so the file is stable across runs and diffs
cleanly.

#### Where the bounding boxes come from

The Metalinks carry no geometry, but the tile name does: `674_5403.laz` is the
1 km × 1 km tile whose **lower-left** corner is at easting 674 km / northing
5403 km in EPSG:25832 (ETRS89 / UTM zone 32N). So the box is
`[674000, 675000] × [5403000, 5404000]`.

This is derived, not published, so it was verified three ways:

* the portal's own grid WMS resolves a point inside that extent to
  `674_5403.laz`, and probes just inside each of the four corners land in the
  expected neighbouring tiles;
* the same holds for random samples drawn from the finished CSV;
* the LAS public header of a downloaded tile reports its point extent as
  `759000.25 … 759999.74` × `5308000.25 … 5308999.75` for `759_5308.laz` —
  inside the derived box, hugging all four edges.

The WGS84 columns transform all four corners and take the min/max, because the
UTM tile edges are not straight lines in WGS84.

The declared SHA-256 was also checked end-to-end by downloading a tile and
hashing it.

### Regenerating

```sh
uv run scripts/build_laz_tile_index.py -o laz_tiles.csv
```

Takes about a minute. `uv run` supplies `pyproj` (the only dependency, used for
the WGS84 columns) via the script's inline PEP 723 metadata; with a plain
`python3` the script still runs but leaves the lon/lat columns empty.

Useful flags:

* `--limit N` — only the first N units, for a quick smoke test.
* `--delay S` — pause between Metalink requests (default 0.5 s).
* `--per-gemeinde` — scrape the 2,229 municipality Metalinks instead. Much
  slower, but then `units` names the municipalities a tile belongs to.

The unit list is discovered from the KML rather than hard-coded, so the script
keeps working if the set of administrative units changes. It warns if a tile
listed in two Metalinks disagrees on size or hash, and if any tile lacks a
SHA-256 (neither occurred in the current run).

### Caveats

* `size_bytes` and `sha256` are the values the portal declares; they are not
  recomputed for all 71,979 files.
* The laser data is updated *losweise* (in batches) as new flight campaigns are
  processed, so re-run the script rather than treating the CSV as permanent.
* 71,979 tiles slightly exceeds Bavaria's 70,550 km² because tiles on the state
  border are included whole.

## Rheinland-Pfalz — `laz_tiles_rlp.csv`

`laz_tiles_rlp.csv` lists every LAZ tile of the *Laserpunkte Objekte und
Gelände* (LPO/LPG) product that the Landesamt für Vermessung und
Geobasisinformation Rheinland-Pfalz publishes as OpenData under
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0).

**21,207 tiles, 4.71 TiB total** (index generated 2026-08-02 from the Metalink
published 2026-01-13).

RLP is the one other state that makes this easy. The tiles are plain files on a
directory-listing server, and a single statewide
[Metalink 4.0](https://datatracker.ietf.org/doc/html/rfc5854) sits beside them
carrying size and SHA-256 for each — the whole index is *one* request:

* <https://geobasis-rlp.de/data/las/current/las/> — the `.laz` files
* <https://geobasis-rlp.de/data/las/current/meta4/las_las_07.meta4> — the index
  (`07` is the Regionalschlüssel of Rheinland-Pfalz)

Finer Metalinks exist per Kreis (`las_las_<5-digit>.meta4`) and per Gemeinde
(`las_las_<8-digit>.meta4`), but they are strict subsets, so the statewide one
is all you need. Pass one to `--metalink` to index a subset.

Attribution required by the licence:
`©GeoBasis-DE / LVermGeoRP<year>, dl-de/by-2-0, www.lvermgeo.rlp.de`.

### Verification

Same tiling scheme as Bavaria, different file name:
`lpolpg_32_441_5527_1_rp.laz` is the 1 km × 1 km tile with its **lower-left**
corner at easting 441 km / northing 5527 km in EPSG:25832. Checked three ways:

* the Metalink and the directory listing agree on all 21,207 tiles — the script
  cross-checks this on every run and warns on either kind of drift;
* the LAS public headers of random tiles, fetched with an HTTP range request,
  report point extents inside the derived box and hugging its edges (e.g.
  `lpolpg_32_336_5500_1_rp.laz` → `336000.00 … 336999.99` ×
  `5500000.00 … 5500999.99`). `--verify-headers N` re-runs this;
* the declared size and SHA-256 were confirmed end-to-end by downloading
  `lpolpg_32_385_5620_1_rp.laz` and hashing it.

Note that the Metalink's `name` attribute (`LAS_441_5527_las12.laz`) is *not*
the name of the file it points at. The `tile` column uses the URL basename,
which is what actually lands on disk.

### Regenerating

```sh
uv run scripts/build_laz_tile_index_rlp.py -o laz_tiles_rlp.csv --verify-headers 5
```

Takes a few seconds plus whatever `--verify-headers` costs.

## Nordrhein-Westfalen — `laz_tiles_nrw.nosha256.csv`

> **This file is not runnable as-is.** Its `sha256` column is empty and
> mapant-nf will reject it at input validation. See below.

`laz_tiles_nrw.nosha256.csv` lists every LAZ tile of the *3D-Messdaten aus dem
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

Since checksums are mandatory and load-bearing in mapant-nf — a truncated laz
renders as a plausible but wrong map rather than as an error — the only honest
way to get the column is to compute it:

```sh
uv run scripts/build_laz_tile_index_nrw.py -o laz_tiles_nrw.csv \
    --fill-sha256 --jobs 8
```

This streams each tile and hashes it in flight. It needs **no disk**, resumes
from a partially filled CSV (re-run the same command), and costs a one-off
~3.2 TiB of transfer — about as much as a single rendering pass over the same
data would download anyway. Tiles that fail are reported and left blank rather
than guessed.

### Verification

`3dm_32_280_5652_1_nw.laz` is the 1 km × 1 km tile with its **lower-left**
corner at easting 280 km / northing 5652 km in EPSG:25832; all 35,860 names
parse and all are in zone 32. LAS public headers of random tiles confirm it
(e.g. `280000.00 … 280999.99` × `5652000.00 … 5652999.99`), and
`--verify-headers N` re-runs the check. A hash produced by `--fill-sha256` was
confirmed against an independent download of the same tile.

### Regenerating

```sh
# cheap: everything except the checksums
uv run scripts/build_laz_tile_index_nrw.py -o laz_tiles_nrw.nosha256.csv

# expensive but resumable: fill them in
uv run scripts/build_laz_tile_index_nrw.py -o laz_tiles_nrw.csv --fill-sha256
```
