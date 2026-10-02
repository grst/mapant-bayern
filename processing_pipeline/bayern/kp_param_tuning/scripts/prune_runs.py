#!/usr/bin/env python3
"""
Delete cached stage runs (work/runs/stage) older than --age minutes, except those of the named
parameter sets in work/sets.json. Search trials never reuse each other's runs, so after scoring they
are only disk. Named sets are kept so that evaluate.py, border.py and gallery.py stay cheap.

    prune_runs.py [--age 30] [--loop 1200]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def keep_set() -> set[str]:
    sites = kp.sites()
    blocks = yaml.safe_load((ROOT / "border.yaml").read_text()) if (ROOT / "border.yaml").exists() else {}
    tiles = [(t, "full") for s in sites.values() for t in s["core"]]
    tiles += [(t, "full") for b in blocks.values() for t in b["core"]]
    tiles += [(t, v) for v in ("thin50", "thin25") for t in
              (x.name.removesuffix(".xyz.bin") for x in (kp.CACHE / v).glob("*.xyz.bin"))]
    keep = set()
    for o in json.loads((kp.WORK / "sets.json").read_text()).values():
        ini = kp.effective_ini(o)
        for t, v in tiles:
            for st in kp.STAGES:
                keep.add(f"{kp.run_key(t, v, st, ini)}_{t}")
    return keep


def prune(age_min: float) -> int:
    keep, now, n = keep_set(), time.time(), 0
    for d in kp.RUNS.glob("*/*/*"):
        if d.name not in keep and now - d.stat().st_mtime > age_min * 60:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--age", type=float, default=30)
    ap.add_argument("--loop", type=float, default=0, help="repeat every N seconds")
    args = ap.parse_args()
    while True:
        print(time.strftime("%H:%M"), "pruned", prune(args.age), flush=True)
        if not args.loop:
            return 0
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(main())
