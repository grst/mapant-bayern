#!/usr/bin/env bash
# Measure how fast the local mirror of Saarland's tiles delivers, the way mapant-nf fetches: Bavaria's
# benchmark (../bayern/scripts/benchmark_download.sh, which documents the method) pointed at this
# state's samplesheet. Extra arguments pass through, e.g. --levels '1 8 32' --duration 20.
set -euo pipefail
cd "$(dirname "$0")/.."
exec ../bayern/scripts/benchmark_download.sh --csv input/laz_tiles.local.csv "$@"
