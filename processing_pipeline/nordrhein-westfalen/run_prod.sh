#!/bin/bash
# The production run over all of Nordrhein-Westfalen on a c8id.32xlarge (see ../bayern/README.md).
#
# mapant-nf 1619f9c (grst/mapant-nf#2) is the first revision that unpacks .zip tiles and takes
# optional sizes and sha1: checksums. MAPANT_NF_REVISION overrides it.
set -euo pipefail
cd "$(dirname "$0")"
nextflow run grst/mapant-nf -r "${MAPANT_NF_REVISION:-1619f9c336eed4cd87fc328b554da314461cf610}" \
    -params-file conf/production.yml -profile docker -c ../bayern/conf/c8id.32xlarge.config -resume
