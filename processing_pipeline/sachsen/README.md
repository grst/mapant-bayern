# Mapant Sachsen Processing Pipeline

Sachsen is rendered with the same [mapant-nf](https://github.com/grst/mapant-nf) pipeline as
Bavaria; see [../bayern/README.md](../bayern/README.md) for the pipeline and the compute setup.

## Obtaining input data

LiDAR for Sachsen is the *Laserscandaten* product of the
[Staatsbetrieb Geobasisinformation und Vermessung](https://www.geodaten.sachsen.de) (GeoSN),
OpenData under [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0): 4,981 tiles of **2 km x 2 km**
(1.60 TiB), each a `.zip` holding one `.laz`, on a Nextcloud share, EPSG:25833. The tile list is
rebuilt from the portal's batch-download page; sizes, and a SHA-1 for the 802 tiles Nextcloud has
one for, come from a range request per tile.
[`scripts/build_laz_tile_index.sh`](scripts/build_laz_tile_index.sh) builds
[laz_tiles.csv](input/laz_tiles.csv) with the shared zip indexer; mapant-nf verifies `sha1:`
checksums like SHA-256 ones. See [input/README.md](input/README.md).

Because the tiles are 2 km, the grids are 8 x 8 tiles rather than Bavaria's 16 x 16: the same
ground, and about the same bytes, per grid.

The OSM extract, `sachsen-latest.osm.pbf`, comes from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html); see
[download_osm.sh](input/download_osm.sh).

## Running the pipeline

 * [run_test_dresden.sh](./run_test_dresden.sh) launches a test run over Dresden and the Elbsandstein
   ([conf/test_dresden.yml](conf/test_dresden.yml)).
 * [run_prod.sh](./run_prod.sh) starts the production run over all of Sachsen.

Both use **Bavaria's production settings for now** -- its karttapullautin ini and OSM rules
(`../bayern/conf/`), zooms, download settings and grid size (8 x 8 tiles for 2 km tiles) --
and Bavaria's compute configs. The run scripts need a mapant-nf revision that unpacks `.zip` tiles
and accepts optional sizes and checksums: they pin mapant-nf `1619f9c` (grst/mapant-nf#2;
`MAPANT_NF_REVISION` overrides it).

[scripts/benchmark_download.sh](scripts/benchmark_download.sh) measures the tile server the way the
pipeline fetches from it (Bavaria's benchmark, pointed at this samplesheet).

## Test run

Not yet rendered (the overnight run on 2026-10-05 was stopped before its first grid finished). An
earlier four-tile run proved the path end to end: the zips download, verify by size, unpack and
render. The server delivered ~1 MB/s per connection.
