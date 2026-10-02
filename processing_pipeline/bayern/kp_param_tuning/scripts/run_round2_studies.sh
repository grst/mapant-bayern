#!/bin/bash
# Round 2 search: more reference maps, fixed registration, wider green bounds, seeded with round 1's
# Pareto fronts. Same retry lanes as run_night.sh.
cd "$(dirname "$0")/.."
export PYTHONWARNINGS=ignore
PY=.venv/bin/python
run() {  # run <log> <optimize.py args...>
    local log=$1; shift
    until $PY scripts/optimize.py "$@" >> "work/logs/$log" 2>&1; do sleep 15; done
}
export -f run
export PY
lane() { setsid nohup bash -c "$1" > /dev/null 2>&1 & }
L14=fuerstenhaenge,ochsenkopf,raffawald,roethenbach,fuerstenschlag,kozina
L12=auerbach,kastensee,kohlbruck
lane "run r2_green_las14.log green --trials 160 --workers 3 --threads 4 --sites $L14 --tag=-r2-las14 --seed-params work/seeds_green_las14.json"
lane "run r2_green_las12.log green --trials 160 --workers 2 --threads 3 --sites $L12 --tag=-r2-las12 --seed-params work/seeds_green_las12.json"
lane "run r2_cliffs.log cliffs --trials 60 --workers 1 --threads 3 --sites $L14,auerbach,kastensee --tag=-r2 --seed-params work/seeds_cliffs.json; \
      run r2_yellow_las14.log yellow --trials 40 --workers 1 --threads 3 --sites $L14,reitimwinkl --tag=-r2-las14 --fixed work/fixed_r1_las14.json --seed-params work/seeds_yellow.json; \
      run r2_yellow_las12.log yellow --trials 40 --workers 1 --threads 3 --sites $L12 --tag=-r2-las12 --fixed work/fixed_r1_las12.json --seed-params work/seeds_yellow.json"
