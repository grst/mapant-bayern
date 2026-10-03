#!/usr/bin/env python3
"""
Multi-objective search of kp's vegetation (green) or open-land (yellow) parameters for one tile
group, against the group's training sites.

    optimize.py green  --config region.yaml --group G --trials 160 [--fixed yellow.json]
    optimize.py yellow --config region.yaml --group G --trials 60  --fixed green.json

Objectives (means over the training sites, all maximised):
  green   green_ba, green_kappa, readability (= -|log boundary_ratio|)
  yellow  open_f1, open_ba

Studies live in <work>/optuna.db as "<study>-<group>"; every trial stores its overrides and its
per-site metrics, so a run resumes after an interruption and the fronts can be analysed later.
Trial 0 is kp's default; then the Bavarian optima (reference/bavaria_seeds.json) are enqueued, then
TPE (multivariate, 20 random start trials) takes over. Expect the constrained best to keep
improving for ~100-150 trials; 6 tiles x 4 workers take ~1-2 min per trial.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import optuna

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import kp  # noqa: E402
import score  # noqa: E402

SEEDS = common.KPT / "reference/bavaria_seeds.json"
optuna.logging.set_verbosity(optuna.logging.WARNING)
YELLOW_KEYS = ("yellowheight", "yellowthresold", "yellowfirstlast", "yellowmedianboxsize")


def storage() -> optuna.storages.RDBStorage:
    return optuna.storages.RDBStorage(f"sqlite:///{common.work() / 'optuna.db'}",
                                      engine_kwargs={"connect_args": {"timeout": 300}})


def odd(t, name, lo, hi):
    return 2 * t.suggest_int(name + "_half", lo // 2, hi // 2) + 1


def space_green(t: optuna.Trial) -> dict:
    """Vegetation keys. Bounds as widened in Bavaria round 2, where round 1's fronts sat on them."""
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
        "zone1": f"{z_lo:.2f}|{z1:.2f}|99|1", "zone2": f"{z1:.2f}|{z2:.2f}|99|{f2:.2f}",
        "zone3": f"{z2:.2f}|{z3:.2f}|8|{f3:.2f}",
        "thresold1": f"0.20|3|{t_low:.3f}", "thresold2": f"3|4|{t_low:.3f}", "thresold3": f"4|7|{t_low:.3f}",
        "thresold4": f"7|20|{t_high:.3f}", "thresold5": f"20|99|{t_high:.3f}",
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


STUDIES = {
    "green": (space_green, ["green_ba", "green_kappa", "readability"]),
    "yellow": (space_yellow, ["open_f1", "open_ba"]),
}


def group_sites(group: str, split: str = "train", study: str = "green") -> dict:
    return {k: v for k, v in kp.sites().items()
            if str(v.get("group", "all")) == str(group) and v["split"] == split and study not in v.get("skip", [])}


def evaluate(overrides: dict, sites: dict, workers: int, threads: int) -> dict[str, dict]:
    jobs = [(s, t) for s, d in sites.items() for t in d["core"]]
    with ThreadPoolExecutor(workers) as ex:
        dirs = list(ex.map(lambda j: kp.run_stage(j[1], "vege", overrides, threads=threads), jobs))
    by: dict[str, dict] = {}
    for (s, t), d in zip(jobs, dirs):
        by.setdefault(s, {})[t] = d
    return {s: score.score(s, sites[s]["core"], td) for s, td in by.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("study", choices=STUDIES)
    common.add_config_arg(ap)
    ap.add_argument("--group", required=True)
    ap.add_argument("--trials", type=int, default=150)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--fixed", type=Path, help="json of ini overrides held fixed (e.g. the chosen green set)")
    ap.add_argument("--no-seeds", action="store_true")
    a = ap.parse_args()
    common.set_config(a.config)

    space, names = STUDIES[a.study]
    sites = group_sites(a.group, "train", a.study)
    if not sites:
        raise SystemExit(f"no training sites in group {a.group}")
    for s, d in sites.items():
        kp.prepare(s, d)
    fixed = json.loads(a.fixed.read_text()) if a.fixed else {}
    if a.study == "green" and not a.fixed:
        # open land is searched afterwards; meanwhile the Bavarian choice (better than the default)
        fixed = json.loads(SEEDS.read_text())["yellow_overrides"]["las14"]
    name = f"{a.study}-{a.group}"
    st = optuna.create_study(study_name=name, storage=storage(), directions=["maximize"] * len(names),
                             sampler=optuna.samplers.TPESampler(multivariate=True, seed=0, n_startup_trials=20),
                             load_if_exists=True)
    st.set_metric_names(names)
    st.set_user_attr("fixed", fixed)
    st.set_user_attr("sites", list(sites))
    if not st.trials:
        st.enqueue_trial({}, user_attrs={"default": True})
        if not a.no_seeds and SEEDS.exists():
            seeds = json.loads(SEEDS.read_text())[f"{a.study}_params"]
            for p in seeds.values():
                if p:
                    st.enqueue_trial(p, skip_if_exists=True)

    def objective(trial: optuna.Trial):
        t0 = time.time()
        # trial 0: kp's default for the searched keys (the fixed keys stay)
        o = dict(fixed) if trial.user_attrs.get("default") else {**fixed, **space(trial)}
        if trial.user_attrs.get("default") and a.study == "green":
            o = {}
        per_site = evaluate(o, sites, a.workers, a.threads)
        trial.set_user_attr("overrides", o)
        trial.set_user_attr("per_site", per_site)
        vals = [float(np.nanmean([m[n] for m in per_site.values()])) for n in names]
        print(f"[{name}] #{trial.number} " + " ".join(f"{n}={v:.3f}" for n, v in zip(names, vals))
              + f" ({time.time() - t0:.0f}s)", flush=True)
        return vals

    done = len([t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE])
    st.optimize(objective, n_trials=max(a.trials - done, 0), catch=(RuntimeError,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
