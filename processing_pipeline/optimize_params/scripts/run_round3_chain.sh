#!/bin/bash
# Overnight chain: matched LAS 1.2 sets, then the LAS 1.2 renders of the comparison areas (the LAS
# 1.4 pass runs separately, started earlier), then vector tiles and the comparison app.
cd "$(dirname "$0")/.."
PY=.venv/bin/python
while pgrep -f "match12.py (prepare|forest)" > /dev/null; do sleep 60; done
scripts/run_round3.sh > work/logs/round3.log 2>&1 || { echo "round3 failed"; exit 1; }
$PY scripts/region.py run wuerzburg --gen 1.2 --workers 3 > work/logs/region_v12_wuerzburg.log 2>&1 || exit 1
$PY scripts/region.py run allgaeu --gen 1.2 --workers 4 > work/logs/region_v12_allgaeu.log 2>&1 || exit 1
while pgrep -f "region.py run .* --gen 1.4" > /dev/null; do sleep 60; done
for r in wuerzburg allgaeu; do $PY scripts/region.py tile $r --jobs 4 >> work/logs/region_tile.log 2>&1 || exit 1; done
$PY scripts/compare.py build >> work/logs/region_tile.log 2>&1
echo CHAIN_DONE
