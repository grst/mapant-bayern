#!/bin/bash
# The visual sweep around the LAS 1.4 production ini (sweep_sets.py): render Allgäu's LAS 1.4 tiles
# with every sweep set, tile them, build the viewer in work/compare_sweep/.
cd "$(dirname "$0")/.."
PY=.venv/bin/python
$PY scripts/sweep_sets.py install || exit 1
$PY scripts/region.py run allgaeu --sweep --workers 6 --threads 3 > work/logs/sweep_run.log 2>&1
$PY scripts/region.py run allgaeu --sweep --workers 6 --threads 3 >> work/logs/sweep_run.log 2>&1  # failed tiles again
$PY scripts/region.py tile allgaeu --sweep --jobs 14 > work/logs/sweep_tile.log 2>&1 || exit 1
$PY scripts/compare.py build --sweep >> work/logs/sweep_tile.log 2>&1 || exit 1
echo SWEEP_DONE
