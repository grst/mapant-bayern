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

`conf/test_dresden.yml`, 2026-10-05, in a 16-vCPU devcontainer (4 karttapullautin workers -- the 2 km
tiles hold four times the points of a 1 km tile -- one grid at a time; the map-shaping settings
exactly as in the config): 288 core tiles in 9 grids of 6 x 6 tiles. Six grids rendered, ~3.5 h; a
grid peaked at 3.1-5.3 GB with 4 workers, about 1.3 GB per worker. The archive is 170 MB.

**Three grids are missing**, lost to the server rather than to the pipeline. Around 09:00 the share
first answered some requests with 502s and with 960-byte error pages sent as 200 (mapant-nf now
retries those rather than taking them for wrong files), then with 404 for every tile, including
tiles it had served half an hour before, and for the share's own page. The portal still names the
same share. Whether GeoSN withdrew it or blocked the address after ~350 GB in a day is not known;
check that a tile URL answers before a production run.

The OSM extraction is what needs memory here: each osmium pass over `sachsen-latest.osm.pbf`
peaked at 14.7 GB, so they must not run three at once on a small machine.
