#!/usr/bin/env python3
"""
Multi-objective parameter search, one study per feature group.

    optimize.py <study> --trials N [--workers W] [--threads T] [--variant full] [--sites a,b]
                [--fixed fixed.json]

Studies and their objectives (all maximised; means over the training sites):

  green     vegetation shades:  green_ba, green_kappa, readability (= -|log boundary_ratio|)
  yellow    open land:          open_f1, open_ba
  ug        undergrowth:        ug_f1, ug_ba
  cliffs    cliffs:             cliff_precision, cliff_recall
  knolls    dot knolls:         knoll_precision, knoll_recall

Trials are stored in work/optuna.db (study name "<study>-<variant>"), each with its per-site metrics
as user attributes, so the search resumes after an interruption and the fronts can be analysed
later. The karttapullautin default is always trial 0.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import optuna

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402
import score  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STORAGE_URL = f"sqlite:///{ROOT / 'work/optuna.db'}"


def storage() -> optuna.storages.RDBStorage:
    # several studies run side by side in separate processes: wait for SQLite's lock rather than fail
    return optuna.storages.RDBStorage(STORAGE_URL, engine_kwargs={"connect_args": {"timeout": 300}})


def odd(trial, name, lo, hi):
    return 2 * trial.suggest_int(name + "_half", lo // 2, hi // 2) + 1


# --------------------------------------------------------------------------------------------
# search spaces: trial -> ini overrides (strings, as karttapullautin reads them)


def space_green(t: optuna.Trial) -> dict:
    # bounds widened in round 2 where round 1's Pareto fronts sat on them
    z_lo = t.suggest_float("z_lo", 0.5, 1.6)
    z1 = t.suggest_float("z1", 1.2, 5.0)
    z2 = z1 + t.suggest_float("z2_d", 0.3, 2.5)
    z3 = z2 + t.suggest_float("z3_d", 0.5, 4.0)
    f2 = t.suggest_float("f2", 0.0, 1.0)
    f3 = t.suggest_float("f3", 0.0, 0.6)
    t_low = t.suggest_float("t_low", 0.005, 0.4, log=True)
    t_high = t.suggest_float("t_high", 0.005, 0.4, log=True)
    s1 = t.suggest_float("s1", 0.05, 1.0, log=True)
    s2 = s1 + t.suggest_float("s2_d", 0.1, 2.5, log=True)
    s3 = s2 + t.suggest_float("s3_d", 0.2, 4.0, log=True)
    gds = t.suggest_int("greendetectsize", 2, 8)
    return {
        "zone1": f"{z_lo:.2f}|{z1:.2f}|99|1",
        "zone2": f"{z1:.2f}|{z2:.2f}|99|{f2:.2f}",
        "zone3": f"{z2:.2f}|{z3:.2f}|8|{f3:.2f}",
        "thresold1": f"0.20|3|{t_low:.3f}",
        "thresold2": f"3|4|{t_low:.3f}",
        "thresold3": f"4|7|{t_low:.3f}",
        "thresold4": f"7|20|{t_high:.3f}",
        "thresold5": f"20|99|{t_high:.3f}",
        "greenground": f"{t.suggest_float('greenground', 0.4, 1.6):.2f}",
        "greenhigh": f"{t.suggest_float('greenhigh', 1.2, 4.0):.2f}",
        "topweight": f"{t.suggest_float('topweight', 0.05, 1.0):.2f}",
        "pointvolumefactor": f"{t.suggest_float('pointvolumefactor', 0.0, 0.8):.2f}",
        "firstandlastreturnasground": str(t.suggest_int("firstandlastreturnasground", 1, 4)),
        "firstandlastreturnfactor": f"{t.suggest_float('firstandlastreturnfactor', 0.0, 1.5):.2f}",
        "lastreturnfactor": f"{t.suggest_float('lastreturnfactor', 0.0, 1.0):.2f}",
        "greendetectsize": str(gds),
        "groundboxsize": str(t.suggest_categorical("groundboxsize", [1, 3])),
        "medianboxsize": str(odd(t, "medianboxsize", 1, 31)),
        "medianboxsize2": str(odd(t, "medianboxsize2", 1, 9)),
        "greenshades": f"{s1:.3f}|{s2:.3f}|{s3:.3f}",
        "greenshadeisom": "406|408|410",
        "vegesimplify": f"{t.suggest_float('vegesimplify', 0.5, 6.0):.2f}",
    }


def space_yellow(t: optuna.Trial) -> dict:
    return {
        "yellowheight": f"{t.suggest_float('yellowheight', 0.2, 2.0):.2f}",
        "yellowthresold": f"{t.suggest_float('yellowthresold', 0.4, 0.99):.3f}",
        "yellowfirstlast": str(t.suggest_int("yellowfirstlast", 0, 3)),
        "yellowmedianboxsize": str(odd(t, "yellowmedianboxsize", 1, 15)),
    }


def space_ug(t: optuna.Trial) -> dict:
    u1 = t.suggest_float("undergrowth", 0.05, 0.7)
    u2 = u1 + t.suggest_float("undergrowth2_d", 0.02, 0.6)
    return {"undergrowth": f"{u1:.3f}", "undergrowth2": f"{u2:.3f}"}


def space_cliffs(t: optuna.Trial) -> dict:
    c1 = t.suggest_float("cliff1", 0.5, 2.5)
    return {
        "cliff1": f"{c1:.2f}",
        "cliff2": f"{c1 + t.suggest_float('cliff2_d', 0.1, 2.5):.2f}",
        "cliffthin": f"{t.suggest_float('cliffthin', 0.2, 1.0):.2f}",
        "cliffsteepfactor": f"{t.suggest_float('cliffsteepfactor', 0.1, 0.8):.2f}",
        "cliffflatplace": f"{t.suggest_float('cliffflatplace', 1.0, 10.0):.2f}",
        "cliffnosmallciffs": f"{t.suggest_float('cliffnosmallciffs', 0.0, 12.0):.2f}",
    }


def space_knolls(t: optuna.Trial) -> dict:
    return {
        "knolls": f"{t.suggest_float('knolls', 0.05, 1.0):.3f}",
        "smoothing": f"{t.suggest_float('smoothing', 0.3, 2.5):.2f}",
        "curviness": f"{t.suggest_float('curviness', 0.6, 1.8):.2f}",
    }


def readability(m: dict) -> float:
    return -abs(math.log(max(m["boundary_ratio"], 1e-3)))


STUDIES = {
    # name: (stage, space, objective names, objective extractor)
    "green": ("vege", space_green, ["green_ba", "green_kappa", "readability"],
              lambda m: [m["green_ba"], m["green_kappa"], readability(m)]),
    "yellow": ("vege", space_yellow, ["open_f1", "open_ba"], lambda m: [m["open_f1"], m["open_ba"]]),
    "ug": ("vege", space_ug, ["ug_f1", "ug_ba"], lambda m: [m["ug_f1"], m["ug_ba"]]),
    "cliffs": ("cliffs", space_cliffs, ["cliff_precision", "cliff_recall"],
               lambda m: [m["cliff_precision"], m["cliff_recall"]]),
    "knolls": ("contours", space_knolls, ["knoll_precision", "knoll_recall"],
               lambda m: [m["knoll_precision"], m["knoll_recall"]]),
}

# sites whose reference is too weak for a feature (few or no symbols of that kind)
SKIP = {
    "knolls": {"kastensee", "doebraberg", "ochsenkopf", "schneckenberg", "kohlbruck", "reitimwinkl"},
    "ug": {"kastensee", "doebraberg", "reitimwinkl"},
    # a ski-O map maps open land only; Kohlbruck's black hatching reads as rock
    "green": {"reitimwinkl"},
    "cliffs": {"kohlbruck", "reitimwinkl"},
}


def evaluate(overrides: dict, stage: str, sites: dict[str, dict], variant: str, workers: int,
             threads: int) -> dict[str, dict]:
    jobs = [(site, t) for site, s in sites.items() for t in s["core"]]
    with ThreadPoolExecutor(workers) as ex:
        dirs = list(ex.map(lambda j: kp.run_stage(j[1], stage, overrides, variant=variant, threads=threads), jobs))
    by_site: dict[str, dict] = {}
    for (site, t), d in zip(jobs, dirs):
        by_site.setdefault(site, {})[t] = {stage: d}
    return {site: score.score(site, sites[site]["core"], td) for site, td in by_site.items()}


def aggregate(per_site: dict[str, dict], extract, skip: set[str]) -> list[float]:
    vals = np.array([extract(m) for s, m in per_site.items() if s not in skip], dtype=float)
    return [float(np.nanmean(vals[:, i])) for i in range(vals.shape[1])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("study", choices=STUDIES)
    ap.add_argument("--trials", type=int, default=100)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--variant", default="full")
    ap.add_argument("--split", default="train")
    ap.add_argument("--sites", default="")
    ap.add_argument("--fixed", type=Path, help="json of ini overrides held fixed (e.g. the chosen green set)")
    ap.add_argument("--seed-params", type=Path, help="json list of optuna param dicts to enqueue first")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    stage, space, names, extract = STUDIES[args.study]
    all_sites = kp.sites()
    sites = {k: v for k, v in all_sites.items()
             if (k in args.sites.split(",") if args.sites else v["split"] == args.split)}
    fixed = json.loads(args.fixed.read_text()) if args.fixed else {}
    skip = SKIP.get(args.study, set())

    name = f"{args.study}-{args.variant}{args.tag}"
    sampler = optuna.samplers.TPESampler(multivariate=True, seed=0, n_startup_trials=20)
    study = optuna.create_study(study_name=name, storage=storage(), directions=["maximize"] * len(names),
                                sampler=sampler, load_if_exists=True)
    study.set_metric_names(names)
    study.set_user_attr("fixed", fixed)
    study.set_user_attr("sites", list(sites))
    if len(study.trials) == 0:
        # trial 0: karttapullautin's default, expressed as "no overrides"
        study.enqueue_trial({}, user_attrs={"default": True}, skip_if_exists=True)
    if args.seed_params and len(study.trials) <= 1:
        for p in json.loads(args.seed_params.read_text()):
            study.enqueue_trial(p, skip_if_exists=True)

    def objective(trial: optuna.Trial):
        t0 = time.time()
        if trial.user_attrs.get("default"):
            overrides = dict(fixed)
        else:
            overrides = {**fixed, **space(trial)}
        per_site = evaluate(overrides, stage, sites, args.variant, args.workers, args.threads)
        trial.set_user_attr("overrides", overrides)
        trial.set_user_attr("per_site", per_site)
        vals = aggregate(per_site, extract, skip)
        trial.set_user_attr("seconds", round(time.time() - t0, 1))
        print(f"[{name}] trial {trial.number}: " + " ".join(f"{n}={v:.3f}" for n, v in zip(names, vals))
              + f" ({time.time() - t0:.0f}s)", flush=True)
        return vals

    done = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
    study.optimize(objective, n_trials=max(args.trials - done, 0), catch=(RuntimeError,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
