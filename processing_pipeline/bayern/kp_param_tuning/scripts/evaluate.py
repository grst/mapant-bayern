#!/usr/bin/env python3
"""
Score named parameter sets on every site (training and holdout) and on the thinned variants.

    evaluate.py sets.json [--workers 3] [--variants full,thin50,thin25] [--out results/eval.csv]

sets.json maps a set name to its ini overrides ({} is karttapullautin's default). Every stage
runs for every core tile, so the table has all metrics for all sets side by side.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402
import score  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("vege", "cliffs", "contours")


def evaluate_set(name: str, overrides: dict, variant: str, sites: dict, workers: int, threads: int) -> list[dict]:
    jobs = [(site, t, st) for site, s in sites.items() for t in s["core"] for st in STAGES
            if kp.xyz_path(t, variant).exists()]
    with ThreadPoolExecutor(workers) as ex:
        dirs = list(ex.map(lambda j: kp.run_stage(j[1], j[2], overrides, variant=variant, threads=threads), jobs))
    by_site: dict[str, dict] = {}
    for (site, t, st), d in zip(jobs, dirs):
        by_site.setdefault(site, {}).setdefault(t, {})[st] = d
    rows = []
    for site, td in by_site.items():
        m = score.score(site, sites[site]["core"], td)
        rows.append({"set": name, "variant": variant, "site": site, "split": sites[site]["split"], **m})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sets", type=Path)
    ap.add_argument("--variants", default="full")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "results/eval.csv")
    args = ap.parse_args()
    sets = json.loads(args.sets.read_text())
    sites = kp.sites()
    rows = []
    for variant in args.variants.split(","):
        for name, overrides in sets.items():
            rows += evaluate_set(name, overrides, variant, sites, args.workers, args.threads)
            print(f"{variant} {name} done", flush=True)
    df = pd.DataFrame(rows)
    if args.out.exists():
        old = pd.read_csv(args.out)
        keep = ~(old.set.isin(df.set.unique()) & old.variant.isin(df.variant.unique()))
        df = pd.concat([old[keep], df], ignore_index=True)
    df.to_csv(args.out, index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
