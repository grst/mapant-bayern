#!/bin/bash
# Round 3: LAS 1.2 sets matched to the LAS 1.4 sets across the generation border, then the renders
# of the comparison areas. Resumable: every step skips what is done.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
mkdir -p work/logs

$PY scripts/match12.py prepare          # new border blocks, LAS 1.4 targets
$PY scripts/match12.py forest           # OSM forest per block
$PY scripts/match12.py search --trials "${TRIALS:-50}"
$PY scripts/match12.py choose           # -> work/sets.json (las12-match-*), results/match12.csv
$PY - <<'EOF'
import json
s = json.load(open("work/sets.json"))
json.dump({k: v for k, v in s.items() if k.startswith("las12-match")}, open("work/sets_match.json", "w"))
EOF
$PY scripts/evaluate.py work/sets_match.json --workers 4
$PY scripts/border.py eval kp_default gen:las12-r1,las14-r1 gen:las12-balanced,las14-balanced \
    las14-balanced gen:las12-detail,las14-balanced gen:las12-clean,las14-clean \
    gen:las12-match-r1,las14-r1 gen:las12-match-balanced,las14-balanced gen:las12-match-clean,las14-clean \
    gen:las12-match-balanced-sub3,las14-balanced-sub3
$PY scripts/write_inis.py las12-match-r1 las12-match-balanced las12-match-clean las12-match-balanced-sub3 las14-r1 las14-balanced-sub3
echo ROUND3_SETS_DONE
