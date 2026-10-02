#!/usr/bin/env python3
"""
Write the recommended parameter sets as full pullauta.ini files: karttapullautin's own default
ini (pullauta.default.ini of the PR build, comments kept), with the tuned keys replaced in place
and marked. Keys mapant-nf owns (bin/render_ini.py) are left as they are; RENDER_INI sets them.

    write_inis.py <name> [<name> ...]     # names from work/sets.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INI = ROOT / "work/kp/src/pullauta.default.ini"
OUT = ROOT / "params"


def write(name: str, overrides: dict, header: str) -> Path:
    lines = DEFAULT_INI.read_text().splitlines()
    todo = dict(overrides)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in todo:
            new = todo.pop(key)
            old = line.split("=", 1)[1].strip()
            if str(new) != old:
                out.append(f"# tuned for Bavaria (default: {old})")
            out.append(f"{key}={new}")
        elif key and key.rstrip("0123456789") in ("zone", "thresold") and any(
                k.rstrip("0123456789") == key.rstrip("0123456789") for k in overrides):
            # a zone/threshold index the tuned set does not have: kp reads them until the first gap
            out.append(f"# removed for Bavaria: {line.strip()}")
        else:
            out.append(line)
    if todo:
        out.append("")
        out.append("# ---- tuned for Bavaria, not in the default ini ----")
        out += [f"{k}={v}" for k, v in todo.items()]
    OUT.mkdir(exist_ok=True)
    p = OUT / f"pullauta.bayern-{name}.ini"
    p.write_text(header + "\n" + "\n".join(out) + "\n")
    return p


def main() -> int:
    sets = json.loads((ROOT / "work/sets.json").read_text())
    for name in sys.argv[1:]:
        header = (f"# pullauta.ini for mapant-bayern, parameter set '{name}'.\n"
                  f"# karttapullautin grst/karttapullautin#3 (c2a060f) defaults, with the keys the Bavarian\n"
                  f"# parameter study tuned marked below. See processing_pipeline/optimize_params/README.md.")
        print(write(name, sets[name], header))
    return 0


if __name__ == "__main__":
    sys.exit(main())
