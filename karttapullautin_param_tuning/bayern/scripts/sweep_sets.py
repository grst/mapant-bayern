#!/usr/bin/env python3
"""
The visual sweep around the production LAS 1.4 ini (params/pullauta.bayern-las14.ini).

No search and no scores: a fixed list of sets, rendered over all of Allgäu's tiles (LAS 1.2 and 1.4
alike, the sets no longer depend on the generation) by
`region.py run allgaeu --sweep` and compared by eye in `compare.py build --sweep`. Each set is a
full override dict (vegetation and yellow keys); cliffs, contours and knolls stay at kp's default.

* prod-las14: the production ini as it is (anchor).
* B (sw-vs2.0): the production ini with vegesimplify 2.0 (kp's default; < 1.5 makes no sense).
* one or two knobs of B moved, for green detail (smoothing) and for yellow.
* a gradient kp default -> B at t = 1/6 .. 5/6 that moves every key at once.

    sweep_sets.py install   # add the sets to work/sets.json (region.py reads them from there)
    sweep_sets.py show      # print the sets
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROD_INI = ROOT / "params/pullauta.bayern-las14.ini"

# karttapullautin's code defaults for keys its default ini leaves out (src/config.rs)
CODE_DEFAULTS = {"yellowfirstlast": "1"}

# keys the gradient moves, in the order of the overview table
GRADIENT_KEYS = [
    "greenground", "greenhigh", "topweight", "greendetectsize", "groundboxsize", "medianboxsize", "medianboxsize2",
    "pointvolumefactor", "firstandlastreturnfactor", "lastreturnfactor", "firstandlastreturnasground",
    "thresold1", "thresold2", "thresold3", "thresold4", "thresold5", "zone1", "zone2", "zone3", "greenshades",
    "greenshadeisom", "yellowheight", "yellowthresold", "yellowmedianboxsize", "yellowfirstlast", "vegesimplify",
]
INT_KEYS = {"greendetectsize", "groundboxsize", "medianboxsize", "medianboxsize2", "firstandlastreturnasground",
            "yellowmedianboxsize", "yellowfirstlast"}
DECIMALS = {"greenground": 2, "greenhigh": 2, "topweight": 2, "pointvolumefactor": 2, "firstandlastreturnfactor": 2,
            "lastreturnfactor": 3, "yellowheight": 2, "yellowthresold": 3}
GRADIENT_T = [1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6]


def _fmt(x: float, d: int) -> str:
    s = f"{x:.{d}f}".rstrip("0").rstrip(".")
    return s or "0"


def _same(a: str | None, b: str) -> bool:
    try:
        return a is not None and float(a) == float(b)
    except ValueError:
        return a == b


def default_vege() -> dict[str, str]:
    """kp's default for every vegetation key (its default ini, plus code defaults it leaves out)."""
    return {**CODE_DEFAULTS, **kp._stage_relevant("vege", kp.base_ini())}


def production() -> dict[str, str]:
    """The vegetation keys of the production ini that differ from kp's default."""
    d = default_vege()
    p = kp._stage_relevant("vege", kp.read_ini(PROD_INI))
    return {k: v for k, v in p.items() if d.get(k) != v}


def _isom_bounds(shades: str, isom: str) -> list[float]:
    """greenshades + greenshadeisom -> the value at which 406, 408 and 410 start."""
    sh = [float(v) for v in shades.split("|")]
    codes = isom.split("|")
    out = {}
    for i, v in enumerate(sh):
        code = codes[min(i, len(codes) - 1)]
        if v < 90 and code not in out:
            out[code] = v
    return [out["406"], out["408"], out["410"]]


def gradient(t: float, a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    """Set at position t between a (t=0) and b (t=1)."""
    out = {}
    for k in GRADIENT_KEYS:
        if k == "greenshadeisom":
            continue
        va, vb = a[k], b[k]
        if k == "greenshades":
            ba, bb = _isom_bounds(va, a["greenshadeisom"]), _isom_bounds(vb, b["greenshadeisom"])
            out[k] = "|".join(_fmt(x + (y - x) * t, 2) for x, y in zip(ba, bb))
            out["greenshadeisom"] = "406|408|410"
        elif k.startswith("thresold"):  # roof low | roof high | ratio: the ratio spans a decade -> geometric
            pa, pb = va.split("|"), vb.split("|")
            ra, rb = float(pa[2]), float(pb[2])
            out[k] = f"{pa[0]}|{pa[1]}|{_fmt(ra * (rb / ra) ** t, 3)}"
        elif k.startswith("zone"):  # low | high | roof | factor
            pa, pb = va.split("|"), vb.split("|")
            out[k] = "|".join(_fmt(float(x) + (float(y) - float(x)) * t, 2) for x, y in zip(pa, pb))
        else:
            x = float(va) + (float(vb) - float(va)) * t
            out[k] = str(int(round(x + 1e-9))) if k in INT_KEYS else _fmt(x, DECIMALS.get(k, 2))
    return out


def sweep() -> dict[str, dict]:
    """name -> {group, label, change, question, params} in viewer order."""
    prod = production()
    B = {**prod, "vegesimplify": "2.0"}
    D = default_vege()
    full_b = {**D, **B}
    sets: dict[str, dict] = {}

    def add(name, group, change, question, ov, base=B):
        sets[name] = dict(group=group, label=change, change=change, question=question, params={**base, **ov})

    add("prod-las14", "anchor", "production ini (vegesimplify 1.31)", "what production renders today", {}, prod)
    add("sw-vs2.0", "base", "B = production ini with vegesimplify 2.0", "base of all sets below", {})
    add("sw-vs1.5", "green", "vegesimplify 1.5", "simplification, lower end", {"vegesimplify": "1.5"})
    add("sw-vs3.0", "green", "vegesimplify 3.0", "simplification, higher", {"vegesimplify": "3.0"})
    add("sw-vs4.0", "green", "vegesimplify 4.0", "simplification, upper end", {"vegesimplify": "4.0"})
    add("sw-mbox15", "green", "medianboxsize 15", "green smoothing, midway", {"medianboxsize": "15"})
    add("sw-mbox9", "green", "medianboxsize 9", "green smoothing at default", {"medianboxsize": "9"})
    add("sw-mbox2-3", "green", "medianboxsize2 3", "small-patch filter, midway", {"medianboxsize2": "3"})
    add("sw-mbox2-1", "green", "medianboxsize2 1", "small-patch filter at default", {"medianboxsize2": "1"})
    add("sw-gds3", "green", "greendetectsize 3", "green detection window at default", {"greendetectsize": "3"})
    add("sw-detail-mild", "green", "medianboxsize 15, medianboxsize2 3", "combined, mild",
        {"medianboxsize": "15", "medianboxsize2": "3"})
    add("sw-detail-full", "green", "medianboxsize 9, medianboxsize2 1, greendetectsize 3",
        "combined, all green smoothing at default", {"medianboxsize": "9", "medianboxsize2": "1", "greendetectsize": "3"})
    add("sw-ymbox3", "yellow", "yellowmedianboxsize 3", "yellow smoothing, midway", {"yellowmedianboxsize": "3"})
    add("sw-ymbox0", "yellow", "yellowmedianboxsize 0", "yellow smoothing off (default)", {"yellowmedianboxsize": "0"})
    add("sw-yh0.7", "yellow", "yellowheight 0.7", "yellow height, midway", {"yellowheight": "0.7"})
    add("sw-yh0.9", "yellow", "yellowheight 0.9", "yellow height at default", {"yellowheight": "0.9"})
    add("sw-yfl1", "yellow", "yellowfirstlast 1", "single returns count once (default)", {"yellowfirstlast": "1"})
    add("sw-ythr0.8", "yellow", "yellowthresold 0.8", "yellow threshold, looser", {"yellowthresold": "0.8"})
    add("sw-detail-yellow", "combined",
        "medianboxsize 15, medianboxsize2 3, yellowmedianboxsize 3, yellowheight 0.7", "combined green and yellow",
        {"medianboxsize": "15", "medianboxsize2": "3", "yellowmedianboxsize": "3", "yellowheight": "0.7"})
    for t in GRADIENT_T:
        pct = round(t * 100)
        g = gradient(t, D, full_b)
        ov = {k: v for k, v in g.items() if not _same(D.get(k), v)}  # keys still at the default stay out
        sets[f"sw-grad{pct}"] = dict(group="gradient", label=f"gradient {pct} % of the way from kp default to B",
                                      change=f"all keys {pct} % from kp default to B",
                                      question="production candidate", params=ov, t=t)
    return sets


def install() -> None:
    f = kp.WORK / "sets.json"
    all_sets = json.loads(f.read_text())
    for name, s in sweep().items():
        all_sets[name] = s["params"]
    f.write_text(json.dumps(all_sets, indent=1))
    print(f"{f}: {len(sweep())} sweep sets")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "install":
        install()
    else:
        D = default_vege()
        for name, s in sweep().items():
            print(f"{name:20s} {s['change']}")
            if s["group"] == "gradient":
                print("   ", {k: s["params"].get(k, D.get(k)) for k in GRADIENT_KEYS})
    return 0


if __name__ == "__main__":
    sys.exit(main())
