#!/bin/bash
# Finish the comparison areas: wait for the render passes, redo tiles a pass left unfinished, cut
# the vector tiles, build the viewer.
cd "$(dirname "$0")/.."
PY=.venv/bin/python
while pgrep -f "region.py run allgaeu" > /dev/null; do sleep 30; done
for r in wuerzburg allgaeu; do
  $PY scripts/region.py run $r --workers 4 >> work/logs/region_repair.log 2>&1 || { echo "repair $r failed"; exit 1; }
done
for r in wuerzburg allgaeu; do $PY scripts/region.py tile $r --jobs 4 >> work/logs/region_tile.log 2>&1 || exit 1; done
$PY scripts/compare.py build >> work/logs/region_tile.log 2>&1
echo FINISH_DONE
