#!/usr/bin/env python3
"""
From searches to parameter sets, their scores, ini files and the samplesheet column.

    sets.py choose      --config region.yaml --group G     # Pareto picks -> <results>/sets.json, fronts/
    sets.py evaluate    --config region.yaml [set ...]      # all sets x all sites -> <results>/eval.csv
    sets.py inis        --config region.yaml set ...        # -> <results>/params/pullauta.<region>-<set>.ini
    sets.py samplesheet --config region.yaml --map G=set,G2=set2   # index + group + pullauta_ini columns
    sets.py import-bavaria --config region.yaml   # bayern-las14 / bayern-las12 (mapant-bayern production) as priors
    sets.py export --config region.yaml SET OUT.json   # a set's overrides without open-land keys (for --fixed)

choose: on the green study's Pareto front (green_ba, green_kappa, readability), restricted to
trials whose geometric-mean green amount across sites is within +-25 % of the maps (an arithmetic
mean lets one map that draws little green dominate):
  <G>-balanced   weights 1/1/0.3 on min-max-normalised objectives, readability >= -0.35
  <G>-clean      readability first, within 0.015 green_ba of the best
  <G>-lessgreen  like balanced, green amount within +-8 % of the maps
  <G>-detail     most agreement whatever the amount and patchiness
plus the open-land keys of the yellow study's F1-best trial (if that study exists). Picks that land
on the same trial are dropped. `kp_default` is always in sets.json.

Production sets contain vegetation and open-land keys only: cliffs, knolls, contours and
undergrowth stay at kp's defaults (the Bavarian study found the reference maps too weak for them).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import optuna
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import kp  # noqa: E402
import optimize  # noqa: E402
import score  # noqa: E402

LOG125 = math.log(1.25)


def sets_path() -> Path:
    return common.results() / "sets.json"


def load_sets() -> dict:
    p = sets_path()
    return json.loads(p.read_text()) if p.exists() else {"kp_default": {}}


def save_sets(s: dict) -> None:
    s.setdefault("kp_default", {})
    sets_path().write_text(json.dumps(s, indent=1))


def trials(name: str) -> tuple[pd.DataFrame, list[str]]:
    st = optuna.load_study(study_name=name, storage=optimize.storage())
    names = st.metric_names
    rows = []
    for t in st.trials:
        if t.state != optuna.trial.TrialState.COMPLETE:
            continue
        ps = t.user_attrs.get("per_site", {})
        r = {"number": t.number, **dict(zip(names, t.values)), "overrides": t.user_attrs.get("overrides", {}),
             "per_site": ps}
        for k in ("green_bias", "open_bias", "speckle", "boundary_ratio"):
            v = [m[k] for m in ps.values() if m.get(k) is not None and not (isinstance(m[k], float) and math.isnan(m[k]))]
            r[k] = float(np.mean(v)) if v else np.nan
        g = [m["green_bias"] for m in ps.values() if m.get("green_bias") and m["green_bias"] > 0]
        r["green_bias_geo"] = float(np.exp(np.mean(np.log(g)))) if g else np.nan
        rows.append(r)
    return pd.DataFrame(rows), names


def pareto_mask(v: np.ndarray) -> np.ndarray:
    keep = np.ones(len(v), bool)
    for i in range(len(v)):
        if keep[i] and (np.all(v >= v[i], axis=1) & np.any(v > v[i], axis=1)).any():
            keep[i] = False
    return keep


def pick(df, names, weights, constraint=None) -> pd.Series:
    d = df if constraint is None else df[constraint(df)]
    if d.empty:
        raise ValueError("no trial meets the constraint")
    d = d[pareto_mask(np.nan_to_num(d[names].to_numpy(float), nan=-1e9))]
    z = sum(w * (d[n] - df[n].min()) / max(df[n].max() - df[n].min(), 1e-9) for n, w in zip(names, weights))
    return d.loc[z.idxmax()]


def choose(group: str) -> None:
    df, names = trials(f"green-{group}")
    ok = lambda d: np.abs(np.log(d.green_bias_geo)) <= LOG125  # noqa: E731
    best = df[ok(df)].green_ba.max() if ok(df).any() else df.green_ba.max()
    rules = {
        "balanced": ([1, 1, 0.3], lambda d: ok(d) & (d.readability >= -0.35)),
        "clean": ([0.3, 0.3, 1], lambda d: ok(d) & (d.green_ba >= best - 0.015)),
        "lessgreen": ([1, 1, 0.3], lambda d: (np.abs(np.log(d.green_bias_geo)) <= math.log(1.08)) & (d.readability >= -0.35)),
        "detail": ([1, 1, 0], None),
    }
    picks = {}
    for style, (w, cons) in rules.items():
        try:
            picks[style] = pick(df, names, w, cons)
        except ValueError:
            print(f"{group}-{style}: no trial meets its constraint (search too short, or the maps disagree on the "
                  f"green amount); left out")
    yellow = {}
    try:
        ydf, _ = trials(f"yellow-{group}")
        y = ydf.loc[ydf.open_f1.idxmax()]
        yellow = {k: v for k, v in y.overrides.items() if k in optimize.YELLOW_KEYS}
        print(f"yellow-{group}: trial {int(y.number)}, open_f1 {y.open_f1:.3f}")
    except KeyError:
        print(f"no yellow-{group} study: the open-land keys the green study held fixed are used")
    out = common.results() / "fronts"
    out.mkdir(exist_ok=True)
    df["pareto"] = pareto_mask(np.nan_to_num(df[names].to_numpy(float), nan=-1e9))
    df.drop(columns=["per_site"]).assign(overrides=df.overrides.map(json.dumps)).to_csv(out / f"green-{group}.csv", index=False)
    sets, seen = load_sets(), {}
    for style, r in picks.items():
        n = int(r.number)
        if n in seen:
            print(f"{group}-{style} = {group}-{seen[n]} (trial {n}), dropped")
            continue
        seen[n] = style
        o = {k: v for k, v in r.overrides.items() if not k.startswith(("cliff", "knoll"))}
        o.update(yellow)
        sets[f"{group}-{style}"] = o
        print(f"{group}-{style}: trial {n}  ba {r.green_ba:.3f} kappa {r.green_kappa:.3f} "
              f"readability {r.readability:.3f} green x{r.green_bias_geo:.2f}")
    save_sets(sets)


def evaluate(names: list[str], workers: int = 4) -> None:
    sets = load_sets()
    sites = kp.sites()
    rows = []
    for s, d in sites.items():
        kp.prepare(s, d)
    for name in names or list(sets):
        o = sets[name]
        jobs = [(s, t) for s, d in sites.items() for t in d["core"]]
        with ThreadPoolExecutor(workers) as ex:
            dirs = list(ex.map(lambda j: kp.run_stage(j[1], "vege", o), jobs))
        by: dict = {}
        for (s, t), d in zip(jobs, dirs):
            by.setdefault(s, {})[t] = d
        for s, td in by.items():
            rows.append({"set": name, "site": s, "split": sites[s]["split"], "group": sites[s].get("group"),
                         **score.score(s, sites[s]["core"], td)})
        print(name, "done", flush=True)
    df = pd.DataFrame(rows)
    p = common.results() / "eval.csv"
    if p.exists():
        old = pd.read_csv(p)
        df = pd.concat([old[~old.set.isin(df.set.unique())], df], ignore_index=True)
    df.to_csv(p, index=False)
    t = df.pivot_table(index=["group", "split", "set"], values=["green_kappa", "green_ba", "green_bias", "open_f1"], aggfunc="mean")
    print(t.round(3).to_string())


def write_ini(name: str, overrides: dict) -> Path:
    region = common.cfg().get("name", "region").split()[0].lower()
    lines = common.kp_default_ini().read_text().splitlines()
    todo = dict(overrides)
    out = [f"# pullauta.ini, parameter set '{name}' for {common.cfg().get('name', region)}.",
           "# karttapullautin defaults, with the keys the kp_tuning study changed marked below.", ""]
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in todo:
            new, old = todo.pop(key), line.split("=", 1)[1].strip()
            if str(new) != old:
                out.append(f"# tuned (default: {old})")
            out.append(f"{key}={new}")
        elif key and key.rstrip("0123456789") in ("zone", "thresold") and any(
                k.rstrip("0123456789") == key.rstrip("0123456789") for k in overrides):
            out.append(f"# removed (kp reads zones/thresholds until the first gap): {line.strip()}")
        else:
            out.append(line)
    if todo:
        out += ["", "# ---- tuned, not in the default ini ----"] + [f"{k}={v}" for k, v in todo.items()]
    p = common.results() / f"params/pullauta.{region}-{name}.ini"
    p.parent.mkdir(exist_ok=True)
    p.write_text("\n".join(out) + "\n")
    # check: the file must parse back to exactly the intended parameters
    got, want = kp.read_ini(p), kp.effective_ini(overrides)
    bad = {k: (got.get(k), v) for k, v in want.items() if k not in kp.fixed() and got.get(k) != v}
    if bad:
        raise RuntimeError(f"{p}: does not parse back to the set: {bad}")
    return p


def samplesheet(mapping: dict[str, str]) -> None:
    sets = load_sets()
    df = common.tiles().df.copy()
    g = pd.read_csv(common.results() / "groups.csv", dtype=str)
    df = df.merge(g, on="id", how="left")
    files = {grp: write_ini(s, sets[s]) for grp, s in mapping.items()}
    df["pullauta_ini"] = df.group.map({k: str(v) for k, v in files.items()})
    p = common.results() / "tiles_with_ini.csv"
    df.drop(columns=["id"]).to_csv(p, index=False)
    print(df.group.value_counts().to_string(), f"\n-> {p}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["choose", "evaluate", "inis", "samplesheet", "import-bavaria", "export"])
    ap.add_argument("names", nargs="*")
    common.add_config_arg(ap)
    ap.add_argument("--group")
    ap.add_argument("--map", default="", help="samplesheet: group=set,group=set")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    common.set_config(a.config)
    if a.cmd == "choose":
        choose(a.group)
    elif a.cmd == "evaluate":
        evaluate(a.names, a.workers)
    elif a.cmd == "inis":
        sets = load_sets()
        for n in a.names:
            print(write_ini(n, sets[n]))
    elif a.cmd == "samplesheet":
        samplesheet(dict(kv.split("=") for kv in a.map.split(",")))
    elif a.cmd == "import-bavaria":
        prod = json.loads(optimize.SEEDS.read_text())["production"]
        sets = load_sets()
        for k, v in prod.items():
            sets[f"bayern-{k}"] = v
        save_sets(sets)
        print("added", [f"bayern-{k}" for k in prod])
    else:
        o = {k: v for k, v in load_sets()[a.names[0]].items() if k not in optimize.YELLOW_KEYS}
        Path(a.names[1]).write_text(json.dumps(o, indent=1))
        print(f"{a.names[0]} (without open-land keys) -> {a.names[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
