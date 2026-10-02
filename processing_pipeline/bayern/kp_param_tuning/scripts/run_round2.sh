#!/bin/sh
# Round 2: new reference sites and the generation-border blocks.
cd "$(dirname "$0")/.."
NEW="roethenbach fuerstenschlag kozina tyrolsberg reitimwinkl kohlbruck hechenberg"
until grep -q '^done' work/logs/laz_dl3.log; do sleep 30; done
for s in $NEW; do
  .venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import kp; kp.prepare('$s', processes=3); print('$s prepared', flush=True)"
done
.venv/bin/python scripts/register.py $NEW
until grep -q '^done' work/logs/laz_dl_border.log; do sleep 30; done
.venv/bin/python scripts/border.py prepare
echo ROUND2_PREPARED
