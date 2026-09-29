#!/usr/bin/env python3
"""
Pick representative points from each study's Pareto front and combine them into full parameter
sets. Writes results/fronts/<study>.csv (all trials, with a Pareto flag), results/choices.json
(which trial each choice is) and work/sets.json (name -> ini overrides) for evaluate.py.

The feature groups read disjoint parameters, so a green choice, a yellow choice, etc. combine
freely.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import pareto  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOG125 = math.log(1.25)


def subshades(overrides: dict, n: int) -> dict:
    """
    Split each of the three ISOM green levels into n equally spaced greenshades and map them back
    with greenshadeisom. kp median-filters and dissolves small patches on the shade index before
    mapping it to ISOM codes, so this is not the same map as the 3-shade original.
    """
    s1, s2, s3 = (float(v) for v in overrides["greenshades"].split("|"))
    bounds = [s1, s2, s3, s3 + (s3 - s2)]
    shades, isom = [], []
    for level, code in enumerate(("406", "408", "410")):
        lo, hi = bounds[level], bounds[level + 1]
        for k in range(n if level < 2 else 1):
            shades.append(lo + (hi - lo) * k / n)
            isom.append(code)
    return {**overrides, "greenshades": "|".join(f"{v:.3f}" for v in shades), "greenshadeisom": "|".join(isom)}


# Round 2 studies (more sites, fixed registration, wider bounds). Picks are made on the front of the
# trials whose geometric-mean green amount is within +-25 % of the maps: an arithmetic mean lets one
# reference that maps little green (Kohlbruck) dominate the constraint.
STUDY = {"las14": "green-full-r2-las14", "las12": "green-full-r2-las12"}
MANUAL: dict[str, dict[str, int]] = {"las14": {}, "las12": {}}


def geo_bias(per_site: dict) -> float:
    v = [m["green_bias"] for m in per_site.values() if m.get("green_bias") and m["green_bias"] > 0]
    return float(np.exp(np.mean(np.log(v)))) if v else float("nan")


def green_choices(study: str) -> tuple[pd.DataFrame, dict]:
    df, names = pareto.front(study)
    df["green_bias_geo"] = df.per_site.map(geo_bias)
    bias_ok = lambda d: np.abs(np.log(d.green_bias_geo)) <= LOG125  # noqa: E731
    best_ok_ba = df[bias_ok(df)].green_ba.max()
    out = {
        # agreement first, readability as a tie-breaker, within the bias limit
        "balanced": pareto.pick(df, names, [1.0, 1.0, 0.3], lambda d: bias_ok(d) & (d.readability >= -0.35)),
        # the most agreement with the reference, whatever the green amount and edge detail
        "detail": pareto.pick(df, names, [1.0, 1.0, 0.0]),
        # smooth, map-like patches, at little cost in agreement
        "clean": pareto.pick(df, names, [0.3, 0.3, 1.0],
                             lambda d: bias_ok(d) & (d.green_ba >= best_ok_ba - 0.015)),
        # about the maps' green amount
        "lessgreen": pareto.pick(df, names, [1.0, 1.0, 0.3],
                                 lambda d: (np.abs(np.log(d.green_bias_geo)) <= np.log(1.08)) & (d.readability >= -0.35)),
    }
    return df, out


YELLOW_KEYS = ("yellowheight", "yellowthresold", "yellowfirstlast", "yellowmedianboxsize")
STYLES = ("balanced", "lessgreen", "clean", "detail")


def main() -> int:
    (ROOT / "results/fronts").mkdir(parents=True, exist_ok=True)
    old = json.loads((ROOT / "work/sets.json").read_text())
    choices, dfs = {}, {}
    for gen in ("las14", "las12"):
        df, ch = green_choices(STUDY[gen])
        dfs[f"green-{gen}"] = df
        by_num = df.set_index("number")
        for k, num in MANUAL.get(gen, {}).items():
            ch[k] = by_num.loc[num].rename(num).to_frame().T.reset_index(names="number").iloc[0]
        for k, row in ch.items():
            choices[f"green-{gen}-{k}"] = row
        # open land, searched per generation with round 1's vegetation set held fixed: only the
        # yellow keys of the chosen trial are used
        df, names = pareto.front(f"yellow-full-r2-{gen}")
        dfs[f"yellow-{gen}"] = df
        # F1 first: the trials with higher balanced accuracy all draw 1.4x the maps' open land.
        # (Trial 0 is round 1's yellow, which the study held fixed; it stays the best on F1.)
        choices[f"yellow-{gen}"] = df.loc[df.open_f1.idxmax()]
    df, names = pareto.front("ug-full")
    dfs["ug"] = df
    # The undergrowth metrics do not separate parameter sets (F1 <= 0.11 everywhere, reached only by
    # painting 7-22x the reference area). Calibrating the amount instead (undergrowth=0.27, bias ~1
    # on average) was evaluated and rejected: it adds undergrowth where the mappers drew none
    # (Doebraberg 14x, Kastensee 4x) and still almost none where they drew a lot (Raffawald 0.08x).
    # So kp's default thresholds stay.
    df, names = pareto.front("cliffs-full-r2")
    dfs["cliffs"] = df
    choices["cliffs"] = pareto.pick(df, names, [1.0, 0.4])
    df, names = pareto.front("knolls-full")
    dfs["knolls"] = df
    # knolls/smoothing/curviness barely move the knoll count (19-23 per km2 in every trial) and
    # nothing agrees with the reference's dots beyond chance, so the default stays

    for k, df in dfs.items():
        df.drop(columns=["per_site"]).assign(overrides=df.overrides.map(json.dumps)).to_csv(
            ROOT / f"results/fronts/{k}.csv", index=False)
    pareto.save_json({k: {"trial": int(r.number), "overrides": r.overrides,
                          **{m: float(r[m]) for m in r.index if isinstance(r[m], (float, np.floating))}}
                      for k, r in choices.items()}, ROOT / "results/choices.json")

    sets = {"kp_default": {}}
    # round 1's recommendations, for comparison
    for gen in ("las14", "las12"):
        sets[f"{gen}-r1"] = old[f"{gen}-r1"]
    for gen in ("las14", "las12"):
        yellow = {k: v for k, v in choices[f"yellow-{gen}"].overrides.items() if k in YELLOW_KEYS}
        seen = {}
        for style in STYLES:
            row = choices[f"green-{gen}-{style}"]
            if int(row.number) in seen:  # two picks landed on the same trial
                print(f"{gen}-{style} = {gen}-{seen[int(row.number)]} (trial {int(row.number)}), dropped")
                continue
            seen[int(row.number)] = style
            green = {k: v for k, v in row.overrides.items() if k not in YELLOW_KEYS}
            sets[f"{gen}-{style}"] = {**green, **yellow, **choices["cliffs"].overrides}
        sets[f"{gen}-balanced-sub3"] = subshades(sets[f"{gen}-balanced"], 3)
    (ROOT / "work/sets.json").write_text(json.dumps(sets, indent=1))
    for k, r in choices.items():
        print(f"{k:28s} trial {int(r.number):4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
