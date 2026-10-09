# Brandenburg LAZ tile index

`laz_tiles.csv` lists every airborne laserscanning tile that the Landesvermessung und
Geobasisinformation Brandenburg (LGB) publishes as OpenData under
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0).

**13,086 tiles of 1 km x 1 km, 1.29 TiB total** (index generated 2026-10-04), EPSG:25833.

## Where it comes from

The tiles are a plain Apache directory listing, one ZIP per tile:
<https://data.geobasis-bb.de/geobasis/daten/als/laz/>. Each `als_33<E>-<N>.zip` holds the tile's
`.laz` plus its metadata as `.xml` and `.html`; mapant-nf unpacks the one `.laz` and ignores the
rest. The listing renders sizes only human-readable (`103M`), so the indexer asks for each file's
`Content-Length` with a `HEAD` request -- about 45 minutes at the ~5 requests/s the server answers.
All 13,086 listed archives exist.

## Columns

As in Bavaria's index, plus `inner_laz`, the `.laz` member of each archive (informational):

* `size_bytes` -- each archive's exact size.
* `sha256` -- empty: LGB publishes no checksums. mapant-nf checks the size and the ZIP's CRC-32s
  when it unpacks the archive. `--fill-sha256` would compute SHA-256 by streaming all 1.3 TiB.
* `min_x` .. `max_y` -- the file name carries the lower-left corner in km, after the UTM zone
  (`als_33304-5862.zip` is 304-305 km E, 5862-5863 km N in zone 33).

## Regenerating

```sh
scripts/build_laz_tile_index.sh
```
