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


# LAS 1.4: trial 38 is best on every objective among the bias-limited trials, so "detail" would
#   repeat it; trial 42 is its near-equal with ~no green bias (1.03 vs 1.21) -> "lessgreen".
# LAS 1.2: trial 90 has the best agreement within +-25 % green bias (readability -0.25);
#   trial 31 is the cleaner neighbour; trial 65 the best agreement at any bias (1.66).
MANUAL = {
    "las14": {"balanced": 38, "lessgreen": 42, "clean": 29},
    "las12": {"balanced": 90, "clean": 31, "detail": 65},
}


def green_choices(study: str) -> dict:
    df, names = pareto.front(study)
    bias_ok = lambda d: np.abs(np.log(d.green_bias)) <= LOG125  # noqa: E731
    best_ok_ba = df[bias_ok(df)].green_ba.max()
    out = {
        "balanced": pareto.pick(df, names, [1.0, 1.0, 0.5], lambda d: bias_ok(d) & (d.readability >= -0.2)),
        # the most agreement with the reference, whatever the green amount and edge detail
        "detail": pareto.pick(df, names, [1.0, 1.0, 0.0]),
        "clean": pareto.pick(df, names, [0.2, 0.2, 1.0],
                             lambda d: bias_ok(d) & (d.green_ba >= best_ok_ba - 0.015)),
    }
    return df, out


def main() -> int:
    (ROOT / "results/fronts").mkdir(parents=True, exist_ok=True)
    choices, dfs = {}, {}
    for gen in ("las14", "las12"):
        df, ch = green_choices(f"green-full-{gen}")
        dfs[f"green-{gen}"] = df
        for k, row in ch.items():
            choices[f"green-{gen}-{k}"] = row
        # Where the automatic picks collapse or cross, the choice was made by hand from the
        # constrained front, looking at the panels:
        by_num = df.set_index("number")
        manual = MANUAL.get(gen, {})
        for k, num in manual.items():
            choices[f"green-{gen}-{k}"] = by_num.loc[num].rename(num).to_frame().T.reset_index(names="number").iloc[0]
    df, names = pareto.front("yellow-full")
    dfs["yellow"] = df
    choices["yellow"] = pareto.pick(df, names, [1.0, 0.5])
    df, names = pareto.front("ug-full")
    dfs["ug"] = df
    # The undergrowth metrics do not separate parameter sets (F1 <= 0.11 everywhere, reached only by
    # painting 7-22x the reference area). Calibrating the amount instead (undergrowth=0.27, bias ~1
    # on average) was evaluated and rejected: it adds undergrowth where the mappers drew none
    # (Doebraberg 14x, Kastensee 4x) and still almost none where they drew a lot (Raffawald 0.08x).
    # So kp's default thresholds stay.
    choices["ug"] = pd.Series({"number": -1, "overrides": {}})
    df, names = pareto.front("cliffs-full")
    dfs["cliffs"] = df
    choices["cliffs-precise"] = pareto.pick(df, names, [1.0, 0.4])
    choices["cliffs-rich"] = pareto.pick(df, names, [0.6, 1.0], lambda d: d.cliff_precision >= 0.6)
    df, names = pareto.front("knolls-full")
    dfs["knolls"] = df
    # knolls/smoothing/curviness barely move the knoll count (19-23 per km2 in every trial) and
    # nothing agrees with the reference's dots beyond chance, so the default stays
    choices["knolls"] = pd.Series({"number": -1, "overrides": {}})

    for k, df in dfs.items():
        df.drop(columns=["per_site"]).assign(overrides=df.overrides.map(json.dumps)).to_csv(
            ROOT / f"results/fronts/{k}.csv", index=False)
    pareto.save_json({k: {"trial": int(r.number), "overrides": r.overrides,
                          **{m: float(r[m]) for m in r.index if isinstance(r[m], (float, np.floating))}}
                      for k, r in choices.items()}, ROOT / "results/choices.json")

    common = {**choices["yellow"].overrides, **choices["ug"].overrides, **choices["knolls"].overrides}
    sets = {"kp_default": {}}
    for gen in ("las14", "las12"):
        for style in MANUAL[gen]:
            sets[f"{gen}-{style}"] = {**choices[f"green-{gen}-{style}"].overrides, **common,
                                     **choices["cliffs-precise"].overrides}
        sets[f"{gen}-balanced-richcliffs"] = {**sets[f"{gen}-balanced"], **choices["cliffs-rich"].overrides}
        for n in (2, 3):
            sets[f"{gen}-balanced-sub{n}"] = subshades(sets[f"{gen}-balanced"], n)
    (ROOT / "work/sets.json").write_text(json.dumps(sets, indent=1))
    for k, r in choices.items():
        print(f"{k:28s} trial {int(r.number):4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
