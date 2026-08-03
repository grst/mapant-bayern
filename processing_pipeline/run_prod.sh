#!/bin/bash
nextflow run grst/mapant-nf -params-file conf/production.yml -profile docker -c conf/c8id.32xlarge.config  -r 7375123 -resume
