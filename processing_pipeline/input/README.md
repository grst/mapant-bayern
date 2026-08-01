# Bavarian OpenData LAZ tile index

`laz_tiles.csv` lists every LAZ tile (airborne laserscanning point cloud) that the
Bayerische Vermessungsverwaltung publishes as OpenData under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de) on the
[OpenData portal](https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=laserdaten).

**71,979 tiles, 13.66 TiB total** (index generated 2026-07-29 from Metalinks
published 2026-07-28).

## Is there an official list?

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

## CSV columns

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

### Where the bounding boxes come from

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

## Regenerating

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

## Caveats

* `size_bytes` and `sha256` are the values the portal declares; they are not
  recomputed for all 71,979 files.
* The laser data is updated *losweise* (in batches) as new flight campaigns are
  processed, so re-run the script rather than treating the CSV as permanent.
* 71,979 tiles slightly exceeds Bavaria's 70,550 km² because tiles on the state
  border are included whole.
