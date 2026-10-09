#!/bin/bash
nextflow run grst/mapant-nf -params-file conf/production.yml -profile podman -c conf/atom.config  -r v2026.10.9 -resume
