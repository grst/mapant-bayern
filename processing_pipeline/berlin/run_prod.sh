#!/bin/bash
nextflow run grst/mapant-nf -params-file conf/production.yml -profile apptainer -c conf/atom.config  -r 0ab1cda93e217926907d209fbfe5a9c67979bf6b -resume
