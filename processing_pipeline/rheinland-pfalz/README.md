# Mapant Rheinland-Pfalz Processing Pipeline

Rheinland-Pfalz is rendered with the same [mapant-nf](https://github.com/grst/mapant-nf) pipeline as
Bavaria; see [../bayern/README.md](../bayern/README.md) for the pipeline and the compute setup.

## Obtaining input data

LiDAR for Rheinland-Pfalz is the *Laserpunkte Objekte und Gelände* (LPO/LPG) product of the
[Landesamt für Vermessung und Geobasisinformation](https://lvermgeo.rlp.de), OpenData under
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0): 21,207 tiles of 1 km² in `.laz` (4.71 TiB),
EPSG:25832. A statewide Metalink carries size and SHA-256 for every tile, so
[`scripts/build_laz_tile_index.py`](scripts/build_laz_tile_index.py) builds the samplesheet,
[laz_tiles.csv](input/laz_tiles.csv), from one request. See [input/README.md](input/README.md).

The OSM extract, `rheinland-pfalz-latest.osm.pbf`, comes from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html); see
[download_osm.sh](input/download_osm.sh).

## Running the pipeline

 * [run_test_koblenz.sh](./run_test_koblenz.sh) launches a test run over Koblenz, Rhein and Mosel
   ([conf/test_koblenz.yml](conf/test_koblenz.yml)).
 * [run_prod.sh](./run_prod.sh) starts the production run over all of Rheinland-Pfalz.

Both use **Bavaria's production settings for now** -- its karttapullautin ini and OSM rules
(`../bayern/conf/`), zooms, download settings and grid size --
and Bavaria's compute configs. The run scripts need a mapant-nf revision that unpacks `.zip` tiles
and accepts optional sizes and checksums: they pin mapant-nf `1619f9c` (grst/mapant-nf#2;
`MAPANT_NF_REVISION` overrides it).

[scripts/benchmark_download.sh](scripts/benchmark_download.sh) measures the tile server the way the
pipeline fetches from it (Bavaria's benchmark, pointed at this samplesheet).

## Test run

`conf/test_koblenz.yml`, 2026-10-04, in a 16-vCPU devcontainer (8 karttapullautin workers, one
grid at a time; the map-shaping settings exactly as in the config): 423 core tiles in 6 grids,
159 GiB downloaded at ~29 MiB/s over 8 streams, **3 h 52 min** wall time, ~7.5 CPU hours. No
download or render failures. The archive is 160 MB. Download-bound: RLP's tiles are ~250 MB each,
over twice NRW's.
