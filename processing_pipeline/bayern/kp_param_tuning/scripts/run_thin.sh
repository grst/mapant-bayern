#!/bin/bash
# Pulse-thinned variants of three training sites and their point-cloud caches.
cd "$(dirname "$0")/.."
PY=.venv/bin/python
export PYTHONWARNINGS=ignore
for v in "thin50 0.5" "thin25 0.25"; do
  set -- $v
  $PY scripts/thin_laz.py --fraction $2 --variant $1 raffawald fuerstenhaenge auerbach
  for s in raffawald fuerstenhaenge auerbach; do
    $PY -c "import sys; sys.path.insert(0,'scripts'); import kp; kp.prepare('$s', variant='$1', processes=1)"
  done
done
echo THIN_DONE
