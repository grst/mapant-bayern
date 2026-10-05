# Mapant Nordrhein-Westfalen Processing Pipeline

Nordrhein-Westfalen is rendered with the same [mapant-nf](https://github.com/grst/mapant-nf) pipeline as
Bavaria; see [../bayern/README.md](../bayern/README.md) for the pipeline and the compute setup.

## Obtaining input data

LiDAR for Nordrhein-Westfalen is the *3D-Messdaten aus dem Laserscanning* product of
[Geobasis NRW](https://www.bezreg-koeln.nrw.de/geobasis-nrw), OpenData under
[dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0): 35,860 tiles of 1 km² in `.laz` (3.17 TiB),
EPSG:25832. A flat JSON index lists name and size per tile, but NRW publishes no checksums, so the
samplesheet's `sha256` column is empty and mapant-nf checks each download by its size.
[`scripts/build_laz_tile_index.py`](scripts/build_laz_tile_index.py) builds
[laz_tiles.csv](input/laz_tiles.csv); `--fill-sha256` would compute the checksums by streaming all
3.2 TiB. See [input/README.md](input/README.md).

The OSM extract, `nordrhein-westfalen-latest.osm.pbf`, comes from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html); see
[download_osm.sh](input/download_osm.sh).

## Running the pipeline

 * [run_test_teutoburger_wald.sh](./run_test_teutoburger_wald.sh) launches a test run over Teutoburger Wald
   ([conf/test_teutoburger_wald.yml](conf/test_teutoburger_wald.yml)).
 * [run_prod.sh](./run_prod.sh) starts the production run over all of Nordrhein-Westfalen.

Both use **Bavaria's production settings for now** -- its karttapullautin ini and OSM rules
(`../bayern/conf/`), zooms, download settings and grid size --
and Bavaria's compute configs. The run scripts need a mapant-nf revision that unpacks `.zip` tiles
and accepts optional sizes and checksums: they pin mapant-nf `1619f9c` (grst/mapant-nf#2;
`MAPANT_NF_REVISION` overrides it).

[scripts/benchmark_download.sh](scripts/benchmark_download.sh) measures the tile server the way the
pipeline fetches from it (Bavaria's benchmark, pointed at this samplesheet).

## Test run

`conf/test_teutoburger_wald.yml`, 2026-10-04, in a 16-vCPU devcontainer (8 karttapullautin workers,
one grid at a time; the map-shaping settings exactly as in the config): 345 core tiles in 6 grids,
52 GiB downloaded, **1 h 14 min** wall time, ~2.7 CPU hours. No download or render failures. The
archive is 56 MB. The grids ran at about two cores' worth of CPU: the run was bound by the
download, not by karttapullautin.
