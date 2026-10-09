# Mapant Germany Processing Pipeline

Mapant Germany is rendered using the
[mapant-nf](https://github.com/grst/mapant-nf) nextflow pipeline that wraps
[karttapullautin](https://github.com/karttapullautin/karttapullautin) and
[karttapullautin2tiles](https://github.com/grst/kartapullautin2tiles) into into
a [nextflow](https://www.nextflow.io/) workflow.
Each federal state is processed in a separate run.

Nextflow abstracts the compute infrastructure, which enables to run the same
pipeline on a local machine, a HPC, or a cloud batch scheduler by just changing
a few lines of config files.

## Obtaining input data

[This website](https://wiesehahn.github.io/posts/lidar_availability/) lists LiDAR availability for German fedaral
states.
Additionally there's an AI generated overview in [lidar_open_data_germany.md](lidar_open_data_germany.md).

Additionally, OSM shape data is required to render streets, houses etc. The respective
`.pbf` files can be downloaded from
[geofabrik.de](https://download.geofabrik.de/europe/germany.html).
See e.g.
[download-osm.sh](./bayern/input/download_osm.sh).

## Setting up the compute environment

Karttapullautin is now much faster than it was in the past.
Processing on consumer grade hardware is now
totally an option and mostly limited by download speed.
Bavaria, the largest federal state with 15TB of data
was processed on a single `c8id.32xlarge` instance on AWS EC2.
It has 32vCPUs, 64GB of RAM and (that's important) 1.7TB of fast SSD
scratch space.

To install all dependencies and to setup scratch storage, the script [prepare_c8id.sh](scripts/prepare_c8id.sh)
was run after launching the node.

Other federal states were processed on different local hardware.

## Running the pipeline

This is done by triggering the launch scripts.
They trigger the nextflow pipeline with the appropriate configurations
from the [./conf](./conf/) dir.
E.g.

* [run_allgaeu.sh](./bayern/run_allgaeu.sh) is the script to launch a test run of the Allgaeu region
* [run_prod.sh](./bayern/run_prod.sh) starts the production run on the full Bavaria dataset.

## Compute requirements

As an example, Bavaria has an area of ca.
70,541 km².
Downloading and processing the corresponding 71979 LIDAR tiles (ca.
15 TB) on a c8id.8xlarge AWS EC2 instance with 64GB or memory and 32 vCPU this completed in 34h wall time, consuming 1088 allocated CPU hours.
With on-demand pricing, this cost of the run was about 60 USD.
This corresponds to 0.0109 CPUh or 0.00083 USD per tile.

This is a significant improvement over a previous version of the pipeline that used an older version of karttapullautin, which used 5042 CPU hours for Bavaria (0.07 CPUh or 0.0028 USD per tile).

Downloading tiles with multiple connections achieved an average speed around 2.5 - 3.5 Gbps.
Therefore,
the run was still compute-bound, but there wouldn't have been a huge benefit from adding much more compute resources.
