#!/bin/bash
nextflow run grst/mapant-nf -params-file conf/test_allgaeu.yml -profile docker -c conf/c8id.4xlarge.config  -r 1619f9c336eed4cd87fc328b554da314461cf610  -resume
