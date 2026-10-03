"""
Run karttapullautin (kp) for the parameter study, fast.

* prepare(site_def): one kp batch run over a site's core tiles (halo tiles only lend their
  points), keeping each core tile's buffered point cloud (`xyztemp.xyz.bin`, core + 127 m) in
  <work>/cache/<tile>.xyz.bin. Every later run starts from that file, so reading the laz and
  merging the neighbours happens once per tile (~1 min) instead of once per trial.

* run_stage(tile, stage, overrides): one stage (vege | cliffs | contours) of one tile from the
  cached point cloud, with kp's default ini plus `overrides`. Results are cached by a content hash
  of (tile, stage, the parameters that stage reads) in <work>/runs/stage/, so a search can be
  interrupted and resumed, and two sets that differ only in another stage's keys share runs.
  Outputs are uncropped GeoJSON in the index CRS (scoring works in metres).

kp must be the vector-output build (grst/karttapullautin#3 or later) with patches/kp-hardlink.patch
applied: unpatched, every stage run copies the 1+ GB point cloud into its temp folder, which on a
plain ext4 disk makes the whole search IO-bound (and writes terabytes).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

STAGES = {
    "vege": ("vegeonly", ("vegetation", "yellow", "undergrowth")),
    "cliffs": ("cliffsonly", ("cliffs",)),
    "contours": ("contoursonly", ("contours", "formlines", "dotknolls")),
}

# Parameters each stage reads (src/vegetation.rs, src/cliffs.rs, src/knolls.rs, src/contours.rs).
# A run's cache key includes only these.
STAGE_KEYS = {
    "vege": {
        "undergrowth", "undergrowth2", "greenground", "greenhigh", "topweight", "vegezoffset",
        "greendetectsize", "pointvolumefactor", "pointvolumeexponent", "firstandlastreturnfactor",
        "lastreturnfactor", "firstandlastreturnasground", "greenshades", "lightgreentone",
        "greendotsize", "groundboxsize", "medianboxsize", "medianboxsize2", "yellowheight",
        "yellowthresold", "yellowfirstlast", "vegethin", "yellow_smoothing", "yellowmedianboxsize",
        "greenshadeisom", "vegesimplify", "vegeshade", "vege_bitmode", "waterclass", "buildingsclass",
        "waterelevation", "zone*", "thresold*", "scalefactor", "zoffset",
    },
    "cliffs": {"cliff1", "cliff2", "cliffthin", "cliffsteepfactor", "cliffflatplace",
               "cliffnosmallciffs", "scalefactor", "zoffset", "waterclass"},
    "contours": {"knolls", "smoothing", "curviness", "contour_interval", "formline",
                 "formlinesteepness", "formlineaddition", "minimumgap", "dashlength", "gaplength",
                 "indexcontours", "depression_length", "remove_touching_contours",
                 "skipknolldetection", "scalefactor", "zoffset", "waterclass"},
}


def fixed() -> dict[str, str]:
    """Keys the harness owns (mapant-nf's render_ini.py OWNED, minus the WGS84 output)."""
    return {
        "batch": "0", "processes": "1", "vectorvege": "1", "geojson_wgs84": "0", "epsg": str(common.epsg()),
        "output_dxf": "0", "batchmerge": "0", "savetempfiles": "0", "savetempfolders": "0",
        "experimental_use_in_memory_fs": "0", "detectbuildings": "0", "vectorconf": "",
        "lazfolder": "./in", "batchoutfolder": "./out", "vegeonly": "0", "cliffsonly": "0", "contoursonly": "0",
    }


def cache_dir() -> Path:
    return common.work() / "cache"


def runs_dir() -> Path:
    return common.work() / "runs/stage"


def read_ini(path: Path) -> dict[str, str]:
    """kp ini as an ordered dict; the first occurrence of a key wins, as in rust-ini."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out.setdefault(k.strip(), v.strip())
    return out


def base_ini() -> dict[str, str]:
    ini = read_ini(common.kp_default_ini())
    ini.update(fixed())
    return ini


def write_ini(path: Path, ini: dict[str, str]) -> None:
    path.write_text("".join(f"{k}={v}\n" for k, v in ini.items()))


def _stage_relevant(stage: str, ini: dict[str, str]) -> dict[str, str]:
    keys = STAGE_KEYS[stage]
    exact = {k for k in keys if not k.endswith("*")}
    prefixes = tuple(k[:-1] for k in keys if k.endswith("*"))
    return {k: v for k, v in sorted(ini.items()) if k in exact or k.startswith(prefixes)}


def effective_ini(overrides: dict) -> dict[str, str]:
    ini = base_ini()
    for k, v in overrides.items():
        if v is None:
            ini.pop(k, None)
        else:
            ini[k] = str(v)
    # zones/thresholds are read until the first missing index: a shorter list must not leave the
    # default's higher indices in place
    for prefix in ("zone", "thresold"):
        if any(k.startswith(prefix) for k in overrides):
            given = {k for k in overrides if k.startswith(prefix)}
            for k in [k for k in ini if k.startswith(prefix) and k[len(prefix):].isdigit()]:
                if k not in given:
                    del ini[k]
    return ini


def run_key(tile: str, stage: str, ini: dict[str, str], variant: str = "full") -> str:
    blob = json.dumps([tile, variant, stage, _stage_relevant(stage, ini)], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def xyz_path(tile: str, variant: str = "full") -> Path:
    return cache_dir() / variant / f"{tile}.xyz.bin"


def run_stage(tile: str, stage: str, overrides: dict, variant: str = "full", threads: int = 4) -> Path:
    """Run one stage for one tile (or cropped cloud); return the directory holding its GeoJSON."""
    flag, layers = STAGES[stage]
    ini = effective_ini(overrides)
    ini[flag] = "1"
    key = run_key(tile, stage, ini, variant)
    out = runs_dir() / stage / key[:2] / f"{key}_{tile}"
    if (out / "done").exists():
        return out
    src = xyz_path(tile, variant)
    if not src.exists():
        raise FileNotFoundError(f"{src}: prepare this tile first")
    tmp = out.with_name(out.name + f".tmp{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    write_ini(tmp / "pullauta.ini", ini)
    (tmp / "t.xyz.bin").symlink_to(src.resolve())
    env = dict(os.environ, RAYON_NUM_THREADS=str(threads), RUST_LOG="warn")
    proc = subprocess.run([str(common.kp_binary()), "t.xyz.bin", "norender"], cwd=tmp, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        (tmp / "stderr.txt").write_text(proc.stderr[-20000:])
        raise RuntimeError(f"pullauta failed on {tile} {stage} ({key}): {proc.stderr[-2000:]}")
    for layer in layers:
        f = tmp / "temp" / f"{layer}.geojson"
        if f.exists():
            f.rename(tmp / f"{layer}.geojson")
    shutil.rmtree(tmp / "temp", ignore_errors=True)
    (tmp / "t.xyz.bin").unlink()
    (tmp / "params.json").write_text(json.dumps(_stage_relevant(stage, ini), indent=0))
    (tmp / "done").write_text("")
    if out.exists():  # a concurrent worker got there first
        shutil.rmtree(tmp)
    else:
        tmp.rename(out)
    return out


def sites() -> dict:
    p = common.path("sites", "sites.yaml")
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def prepare(name: str, site_def: dict, processes: int = 4, variant: str = "full") -> None:
    """Batch-run a site's (or block's) core tiles once and cache each one's buffered point cloud."""
    todo = [t for t in site_def["core"] if not xyz_path(t, variant).exists()]
    if not todo:
        return
    lend = site_def.get("halo") or []
    for t in site_def["core"] + lend:
        if t in common.tiles():
            common.download(t)
    run = common.work() / f"runs/prepare/{variant}/{name}"
    shutil.rmtree(run, ignore_errors=True)
    (run / "in").mkdir(parents=True)
    (run / "out").mkdir()
    for t in site_def["core"] + lend:
        f = common.laz_path(t)
        if f.exists():
            (run / "in" / f.name).symlink_to(f.resolve())
            if t not in todo:
                (run / "out" / f"{t}.png").touch()  # kp batch skips tiles whose output exists
    ini = base_ini()
    ini.update(batch="1", processes=str(processes), savetempfolders="1")
    write_ini(run / "pullauta.ini", ini)
    env = dict(os.environ, RAYON_NUM_THREADS="8", RUST_LOG="info")
    with open(run / "pullauta.log", "w") as log:
        proc = subprocess.run([str(common.kp_binary())], cwd=run, env=env, stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"prepare {name} failed, see {run}/pullauta.log")
    (cache_dir() / variant).mkdir(parents=True, exist_ok=True)
    for t in todo:
        shutil.move(run / f"temp_{t}_dir" / "xyztemp.xyz.bin", xyz_path(t, variant))
    shutil.rmtree(run)
