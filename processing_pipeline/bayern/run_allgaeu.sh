#!/bin/bash
nextflow run grst/mapant-nf -params-file conf/test_allgaeu.yml -profile docker -c conf/c8id.4xlarge.config  -r 03297698ddf9a1433ccb54fe37f30fd327d672c4 -resume
