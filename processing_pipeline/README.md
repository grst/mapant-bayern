# Mapant Bayern Processing Pipeline

Mapant Bayern is rendered using the
[mapant-nf](https://github.com/grst/mapant-nf) nextflow pipeline that wraps
[karttapullautin](https://github.com/karttapullautin/karttapullautin) and
[karttapullautin2tiles](https://github.com/grst/kartapullautin2tiles) into into
a [nextflow](https://www.nextflow.io/) workflow.

Nextflow abstracts the compute infrastructure, which enables to run the same
pipeline on a local machine, a HPC, or a cloud batch scheduler by just changing
a few lines of config files.

## Obtaining input data

LIDAR data for Bavaria is available from [Geoportal
Bayern](https://geodaten.bayern.de/opengeodata/index.html) under CC-BY-4.0
license. All data are 71979 1km² tiles in `.laz` format (ca. 15 TB). The script
`scripts/build_laz_tile_index.py` parses the metalink files provided in the
geoportal and generates one single samplesheet with all tile URLs:
[laz_tiles.csv](./input/laz_tiles.csv).

Additionally, OSM shape data is required to render streets, houses etc. The
`bayern-latest.osm.pbf` file can be downloaded from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html). See
[download-osm.sh](./input/download_osm.sh).

## Setting up the compute environment

I opted to run the workflow on a single, beefy node: A `c8id.32xlarge` instance
on AWS EC2. It has 128vCPUs, 256GB of RAM and (that's important) 7TB of fast SSD
scratch space. I used a smaller node of the same family (`c8id.4xlarge`) for a
test run.

To install all dependencies and to setup scratch storage, the script [prepare_c8id.sh](scripts/prepare_c8id.sh) 
was run after launching the node. 

## Running the pipeline

This is done by triggering the launch scripts. They trigger the nextflow pipeline with the appropriate configurations 
from the [./conf](./conf/) dir. 

 * [run_allgaeu.sh](./run_allgaeu.sh) is the script to launch a test run of the Allgaeu region
 * [run_prod.sh](./run_prod.sh) starts the production run on the full Bavaria dataset.

## Compute requirements

Bavaria has an area of ca. 70,541 km². Downloading and processing the
corresponding 71979 LIDAR tiles (ca. 15 TB) on a `c8id.32xlarge` AWS EC2
instance with 256GB or memory and 128 vCPU this completed in 27h wall time,
consuming 5042 CPU hours. With on-demand pricing, this cost of the run was a
little less than 200 USD.

Downloading tiles with multiple connections achieved an average speed around 2.5 - 3.5 Gbps. Therefore, 
the run was still compute-bound, but there wouldn't have been a huge benefit from adding much more compute resources.