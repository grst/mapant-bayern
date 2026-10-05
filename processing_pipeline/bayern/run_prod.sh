#!/bin/bash
nextflow run grst/mapant-nf -params-file conf/production.yml -profile docker -c conf/c8id.8xlarge.config  -r 1619f9c336eed4cd87fc328b554da314461cf610 -resume
