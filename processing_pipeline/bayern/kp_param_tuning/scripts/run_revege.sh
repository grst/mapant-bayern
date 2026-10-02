#!/bin/bash
# Only needed for renders made before region.py used kp's own crop (fresh runs are correct already).
# Redo the vegetation layers of the comparison areas with kp's own crop, re-tile, rebuild the viewer.
cd "$(dirname "$0")/.."
PY=.venv/bin/python
for r in wuerzburg allgaeu; do
  $PY scripts/region.py run $r --revege --workers 6 --threads 4 > work/logs/revege_$r.log 2>&1 || exit 1
  $PY scripts/region.py run $r --revege --workers 6 --threads 4 >> work/logs/revege_$r.log 2>&1 || exit 1  # failed tiles again
done
for r in wuerzburg allgaeu; do
  find work/region/$r/pmtiles -name 'v1[24]_*.pmtiles' -delete
  $PY scripts/region.py tile $r --jobs 14 >> work/logs/region_tile2.log 2>&1 || exit 1
done
$PY scripts/compare.py build >> work/logs/region_tile2.log 2>&1
echo REVEGE_DONE
