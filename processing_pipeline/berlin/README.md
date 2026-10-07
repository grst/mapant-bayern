# Mapant Berlin Processing Pipeline

Berlin is rendered with the same [mapant-nf](https://github.com/grst/mapant-nf) pipeline as
Bavaria; see [../bayern/README.md](../bayern/README.md) for the pipeline and the compute setup.

## Obtaining input data

LiDAR for Berlin is the *Airborne Laserscanning (ALS)* point cloud from the
[Geoportal Berlin](https://gdi.berlin.de/geonetwork/srv/ger/catalog.search#/metadata/f4a8997d-4dea-382f-aa3a-d452f4bf3943),
OpenData under [dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0). It is not published per
tile, only as regional ZIPs of 1-37 GB, EPSG:25833.
[`input/download_berlin_laz.sh`](input/download_berlin_laz.sh) downloads them, unpacks them and
converts the `.las` to `.laz` with PDAL. The 1,066 tiles of 1 km² (61.5 GiB as `.laz`) are then
served from a local HTTP server, `http://192.168.193.220:10200/berlin/berlin_als/zip/`.

[`scripts/build_laz_tile_index.py`](scripts/build_laz_tile_index.py) builds the samplesheet,
[laz_tiles.local.csv](input/laz_tiles.local.csv), from that directory listing. Sizes come from a
`HEAD` per tile, and the box from the file name (`3dm_33_369_5808_1_be.laz` is 369-370 km E,
5808-5809 km N). There are no checksums.

The OSM extract, `berlin-latest.osm.pbf`, comes from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html); see
[download_osm.sh](input/download_osm.sh).

## Running the pipeline

[run_prod.sh](./run_prod.sh) starts the production run over all of Berlin
([conf/production.yml](conf/production.yml)) on the 16-vCPU p16s
([conf/p16s.config](conf/p16s.config)), with the same mapant-nf revision as Sachsen's local run.
The local mirror must be up for the run. It uses **Bavaria's production settings for now**: its
karttapullautin ini and OSM rules (`../bayern/conf/`), zooms and grid size.
