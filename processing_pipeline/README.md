# Mapant Bayern Processing Pipeline

Mapant Bayern is rendered using the [mapant-nf](https://github.com/grst/mapant-nf) nextflow pipeline that 
wraps [karttapullautin](https://github.com/karttapullautin/karttapullautin) and [karttapullautin2tiles](https://github.com/grst/kartapullautin2tiles)
into into a [nextflow](https://www.nextflow.io/) workflow. 

Nextflow abstracts the compute infrastructure, which enables to run the same pipeline on a local machine, a HPC, or 
a cloud batch scheduler by just changing a few lines of config files. 

