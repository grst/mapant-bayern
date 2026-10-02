#!/bin/bash
# Overnight search. Each lane runs its studies one after another; every study is retried until it
# exits cleanly (optuna resumes from work/optuna.db). Logs in work/logs/.
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
lane "run study_green_las14.log green --trials 200 --workers 2 --threads 4 --sites fuerstenhaenge,ochsenkopf,raffawald --tag=-las14"
lane "run study_green_las12.log green --trials 200 --workers 1 --threads 4 --sites auerbach,kastensee --tag=-las12"
lane "run study_cliffs.log cliffs --trials 60 --workers 1 --threads 4; run study_knolls.log knolls --trials 80 --workers 1 --threads 4"
lane "run study_yellow.log yellow --trials 60 --workers 1 --threads 4; run study_ug.log ug --trials 50 --workers 1 --threads 4"
