# Thüringen LAZ tile index

`laz_tiles.csv` lists every tile of the 2014-2019 airborne laserscanning epoch that the Thüringer
Landesamt für Bodenmanagement und Geoinformation publishes as OpenData under
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0).

**17,127 tiles of 1 km x 1 km** (index generated 2026-08-02), EPSG:25832.

## Where it comes from

The download app at
<https://geoportal.geoportal-th.de/gaialight-th/_apps/dladownload/dl-dhm.html> is backed by a
GeoJSON query API (`_ajax/overview.php`) that answers a bounding box with the tiles in it, and the
files themselves are static, one ZIP per tile:
`https://geoportal.geoportal-th.de/hoehendaten/LAS/las_2014-2019/las_<E>_<N>_1_th_2014-2019.zip`.
The API refuses queries with too many results, so `../../common/build_zip_tile_index.py` walks the
state in 10 km boxes and quarters any box it refuses.

The app offers three epochs as object types: `dhm1` (2014-2019, the densest, used here), `dhm2`
(2010-2013) and `dhm5` (1996-2006, "Download noch nicht verfügbar"). A 2020-2025 epoch is
mentioned on the portal but not offered by the API (as of 2026-10). Pass `--thueringen-type` to the
indexer for another epoch.

## Columns

As in Bavaria's index, plus `inner_laz` (informational). `size_bytes` is each archive's
`Content-Length`; there is no checksum, so mapant-nf checks the size and the ZIP's CRC-32s.

## Regenerating

```sh
scripts/build_laz_tile_index.sh
```
