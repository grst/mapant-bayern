# Sachsen LAZ tile index

`laz_tiles.csv` lists every tile of the *Laserscandaten* (LSC) product that the Staatsbetrieb
Geobasisinformation und Vermessung Sachsen (GeoSN) publishes as OpenData under
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0).

**4,981 tiles of 2 km x 2 km, 1.60 TiB total** (index generated 2026-10-04).

## Where it comes from

The tiles are served from a public Nextcloud share,
`https://geocloud.landesvermessung.sachsen.de/public.php/dav/files/EpkzyJHScGb5ndd/`, as one ZIP
per tile, `lsc_33<E>_<N>_2_sn_laz.zip`. There is no listing. The tile list is rebuilt from the
`batchConfig` embedded in the portal's [batch download page](https://www.geodaten.sachsen.de/batch-download-4719.html):
a run-length encoded list of 1 km cells per municipality, which the page's own JavaScript aggregates
to the product's 2 km package grid -- `../../common/build_zip_tile_index.py` does the same. Of the
4,989 cells it yields, 8 do not exist on the server and are dropped.

Each ZIP holds the tile's `.laz` and a small `_akt.csv` with its acquisition date; mapant-nf
unpacks the one `.laz` and ignores the rest.

## Columns

As in Bavaria's index, plus `inner_laz`, the `.laz` member of each archive (informational; the
pipeline finds it itself):

* `size_bytes` -- the archive's exact size, from the `Content-Range` of a 100-byte range request.
  The share answers `HEAD` with 401, and a *one*-byte range (`bytes=0-0`) with the whole file.
* `sha256` -- the checksum column. The share sends `OC-Checksum: SHA1:<hex>` where Nextcloud has
  one stored, which is written as `sha1:<hex>`: **802 of the 4,981 tiles**. The rest have none, and
  mapant-nf checks their size and the ZIP's CRC-32s only. `--fill-sha256` would compute SHA-256 for
  them by streaming all 1.6 TiB.
* `min_x` .. `max_y` -- EPSG:25833. The file name carries the lower-left corner in km
  (`lsc_33430_5640_2_sn_laz.zip` is 430-432 km E, 5640-5642 km N), the same convention as every
  other German ALS product surveyed in `../../docs/lidar_open_data_germany.md`. The test region
  (`conf/test_dresden.yml`) puts it to use over ~250 tiles.

## Regenerating

```sh
scripts/build_laz_tile_index.sh
```

About four minutes at 8 concurrent requests.
