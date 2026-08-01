#!/bin/bash
nextflow run grst/mapant-nf -params-file conf/test_allgaeu.yml -profile docker -c conf/c8id.config  -r 7375123 -resume
