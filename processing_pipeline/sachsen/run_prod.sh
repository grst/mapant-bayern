#!/bin/bash
nextflow run grst/mapant-nf -params-file conf/production.yml -profile podman -c conf/p16s.config  -r 0ab1cda93e217926907d209fbfe5a9c67979bf6b -resume
