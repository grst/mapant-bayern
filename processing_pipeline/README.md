# Mapant Bayern Processing Pipeline

Mapant Bayern is rendered using the [mapant-nf](https://github.com/grst/mapant-nf) nextflow pipeline that 
wraps [karttapullautin](https://github.com/karttapullautin/karttapullautin) and [karttapullautin2tiles](https://github.com/grst/kartapullautin2tiles)
into into a [nextflow](https://www.nextflow.io/) workflow. 

Nextflow abstracts the compute infrastructure, which enables to run the same pipeline on a local machine, a HPC, or 
a cloud batch scheduler by just changing a few lines of config files. 

## Beyond Bayern

The pipeline only needs a tiles CSV, so any region with an OpenData point cloud can be rendered.
`input/` currently holds tile indices for **Bayern** and **Rheinland-Pfalz** (both runnable) and
**Nordrhein-Westfalen** (needs a checksum pass first) -- see [`input/README.md`](input/README.md).

[`docs/lidar_open_data_germany.md`](docs/lidar_open_data_germany.md) surveys all 16 Bundeslaender:
which of them publish an airborne laserscanning point cloud as OpenData, in what form, and what it
would take to index each one.

