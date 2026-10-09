# Mapant Saarland Processing Pipeline

Saarland is rendered with the same [mapant-nf](https://github.com/grst/mapant-nf) pipeline as
Bavaria; see [../bayern/README.md](../bayern/README.md) for the pipeline and the compute setup.

## Obtaining input data

LiDAR for Saarland is the 2025 *Airborne Laserscanning* point cloud of the Landesamt für
Vermessung, Geoinformation und Landentwicklung ([LVGL](https://geoportal.saarland.de)), OpenData
under [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0) and thinned to 4 pts/m². It comes as one
ZIP per Landkreis, EPSG:25832. The ZIPs were unpacked into one folder per Landkreis on a local HTTP
server, `http://192.168.193.220:10200/saarland/OD_LIDAR_Punktwolke_2025_laz_LK/LIDAR_laz_<LK>/`.

[`scripts/build_laz_tile_index.py`](scripts/build_laz_tile_index.py) builds the samplesheet,
[laz_tiles.local.csv](input/laz_tiles.local.csv), from those listings: **2,775 tiles of 1 km²,
104 GiB**. Sizes come from a `HEAD` per tile, and the box from the file name
(`3dm_32_308_5488_1_SL_2025_050.laz` is 308-309 km E, 5488-5489 km N). Tiles on a Landkreis border
are in every Landkreis' ZIP: there are 3,076 files, all copies of a tile have the same size, and
the first copy is used. There are no checksums.

The OSM extract, `saarland-latest.osm.pbf`, comes from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html); see
[download_osm.sh](input/download_osm.sh).

## Running the pipeline

[run_prod.sh](./run_prod.sh) starts the production run over all of Saarland
([conf/production.yml](conf/production.yml)) on the 16-vCPU p16s
([conf/p16s.config](conf/p16s.config)), with the same mapant-nf revision as Sachsen's local run.
The local mirror must be up for the run. It uses **Bavaria's production settings for now**: its
karttapullautin ini and OSM rules (`../bayern/conf/`), zooms and grid size. The tiles are thinned
to 4 pts/m², so the vegetation settings tuned on Bavaria's denser clouds may not carry over.
