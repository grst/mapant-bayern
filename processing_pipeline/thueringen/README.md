# Mapant Thüringen Processing Pipeline

Thüringen is rendered with the same [mapant-nf](https://github.com/grst/mapant-nf) pipeline as
Bavaria; see [../bayern/README.md](../bayern/README.md) for the pipeline and the compute setup.

## Obtaining input data

LiDAR for Thüringen is published by the
[Landesamt für Bodenmanagement und Geoinformation](https://www.geoportal-th.de) as OpenData under
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0): 17,127 tiles of 1 km² from the 2014-2019
flights, each a `.zip` holding one `.laz`, EPSG:25832. They are enumerated through the download
app's GeoJSON API; there are no checksums.
[`scripts/build_laz_tile_index.sh`](scripts/build_laz_tile_index.sh) builds
[laz_tiles.csv](input/laz_tiles.csv) with the shared zip indexer. See
[input/README.md](input/README.md).

There is no test region for Thüringen yet.

The OSM extract, `thueringen-latest.osm.pbf`, comes from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html); see
[download_osm.sh](input/download_osm.sh).

## Running the pipeline

 * [run_prod.sh](./run_prod.sh) starts the production run over all of Thüringen.

It uses **Bavaria's production settings for now** -- its karttapullautin ini and OSM rules
(`../bayern/conf/`), zooms, download settings and grid size --
and Bavaria's compute configs. The run script needs a mapant-nf revision that unpacks `.zip` tiles
and accepts optional sizes and checksums: they pin mapant-nf `1619f9c` (grst/mapant-nf#2;
`MAPANT_NF_REVISION` overrides it).

[scripts/benchmark_download.sh](scripts/benchmark_download.sh) measures the tile server the way the
pipeline fetches from it (Bavaria's benchmark, pointed at this samplesheet).
