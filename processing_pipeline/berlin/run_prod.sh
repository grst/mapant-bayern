#!/bin/bash
# The production run over all of Berlin on the 16-vCPU p16s, from the local mirror
# (input/laz_tiles.local.csv). Same mapant-nf revision and compute config as ../sachsen/run_prod.sh;
# MAPANT_NF_REVISION overrides the revision.
set -euo pipefail
cd "$(dirname "$0")"
nextflow run grst/mapant-nf -r "${MAPANT_NF_REVISION:-0ab1cda93e217926907d209fbfe5a9c67979bf6b}" \
    -params-file conf/production.yml -profile podman -c conf/p16s.config -resume
