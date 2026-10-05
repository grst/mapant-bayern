#!/bin/bash
# Build input/laz_tiles.csv. The zip states share one indexer, ../common/build_zip_tile_index.py,
# which documents how each source is enumerated; this is the call that produced the committed CSV.
# Re-running reuses the sizes (and checksums) already in it; delete it for a fresh probe.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ../common/build_zip_tile_index.py --source sachsen -o input/laz_tiles.csv --jobs 8 "$@"
