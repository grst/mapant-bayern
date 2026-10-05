# Mapant Brandenburg Processing Pipeline

Brandenburg is rendered with the same [mapant-nf](https://github.com/grst/mapant-nf) pipeline as
Bavaria; see [../bayern/README.md](../bayern/README.md) for the pipeline and the compute setup.

## Obtaining input data

LiDAR for Brandenburg is published by the
[Landesvermessung und Geobasisinformation Brandenburg](https://geobasis-bb.de) as OpenData under
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0): 13,086 tiles of 1 km², each a `.zip` holding
one `.laz`, in a plain directory listing, EPSG:25833. There are no checksums; the sizes come from a
`HEAD` per tile. [`scripts/build_laz_tile_index.sh`](scripts/build_laz_tile_index.sh) builds
[laz_tiles.csv](input/laz_tiles.csv) with the shared zip indexer. mapant-nf downloads each archive,
checks its size and the ZIP's CRC-32s, and unpacks the `.laz`. See [input/README.md](input/README.md).

The OSM extract, `brandenburg-latest.osm.pbf`, comes from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html); see
[download_osm.sh](input/download_osm.sh).

## Running the pipeline

 * [run_test_barnim.sh](./run_test_barnim.sh) launches a test run over Barnim and Schorfheide
   ([conf/test_barnim.yml](conf/test_barnim.yml)).
 * [run_prod.sh](./run_prod.sh) starts the production run over all of Brandenburg.

Both use **Bavaria's production settings for now** -- its karttapullautin ini and OSM rules
(`../bayern/conf/`), zooms, download settings and grid size --
and Bavaria's compute configs. The run scripts need a mapant-nf revision that unpacks `.zip` tiles
and accepts optional sizes and checksums: they pin mapant-nf `1619f9c` (grst/mapant-nf#2;
`MAPANT_NF_REVISION` overrides it).

[scripts/benchmark_download.sh](scripts/benchmark_download.sh) measures the tile server the way the
pipeline fetches from it (Bavaria's benchmark, pointed at this samplesheet).

## Test run

Not yet rendered. The first attempt (2026-10-05, 03:00) found the tile server delivering ~28 KB/s
per connection -- the 77 GiB of the test region would have taken days -- and was stopped. Worth
measuring with `scripts/benchmark_download.sh` at another time of day before a production run:
13,086 tiles at that rate is out of the question.
