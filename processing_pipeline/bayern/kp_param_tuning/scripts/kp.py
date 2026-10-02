"""
Run karttapullautin for the parameter study.

Two entry points:

* prepare(site): one batch run over the site's core tiles (halo tiles only lend their points, as in
  mapant-nf's run_pullauta.py), keeping each core tile's buffered point cloud
  (`xyztemp.xyz.bin`, core + 127 m) in work/cache/<variant>/<tile>.xyz.bin. Every later run starts
  from that file, so the laz decoding and the neighbour merge happen once.

* run_stage(tile, stage, overrides): one stage (vege | cliffs | contours) of one tile from the cached
  point cloud, with an ini made of the base ini plus `overrides`. Results are cached by content
  hash of (tile, variant, stage, effective stage parameters) in work/runs/, so a sweep can be
  interrupted and resumed, and a parameter set that only changes another stage's keys is free.

The base ini is karttapullautin's own default (pullauta.default.ini of the PR build) with the keys
mapant-nf owns (bin/render_ini.py OWNED) applied, minus the WGS84 reprojection: scoring works in
EPSG:25832 metres.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
PULLAUTA = WORK / "kp/pullauta"
DEFAULT_INI = WORK / "kp/src/pullauta.default.ini"
CACHE = WORK / "cache"
RUNS = WORK / "runs/stage"

STAGES = {
    "vege": ("vegeonly", ("vegetation", "yellow", "undergrowth")),
    "cliffs": ("cliffsonly", ("cliffs",)),
    "contours": ("contoursonly", ("contours", "formlines", "dotknolls")),
}

# Parameters each stage reads. A run's cache key only includes these, so e.g. a vegetation sweep
# does not invalidate the cliff results. (Read off src/vegetation.rs, src/cliffs.rs, src/knolls.rs
# and src/contours.rs.)
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

FIXED = {
    "batch": "0",
    "processes": "1",
    "vectorvege": "1",
    "geojson_wgs84": "0",
    "epsg": "25832",
    "output_dxf": "0",
    "batchmerge": "0",
    "savetempfiles": "0",
    "savetempfolders": "0",
    "experimental_use_in_memory_fs": "0",
    "detectbuildings": "0",
    "vectorconf": "",
    "lazfolder": "./in",
    "batchoutfolder": "./out",
    "vegeonly": "0",
    "cliffsonly": "0",
    "contoursonly": "0",
}


def read_ini(path: Path) -> dict[str, str]:
    """karttapullautin ini as an ordered dict; the first occurrence of a key wins, as in rust-ini."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out.setdefault(k.strip(), v.strip())
    return out


def base_ini() -> dict[str, str]:
    ini = read_ini(DEFAULT_INI)
    ini.update(FIXED)
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
    # zones/thresholds are read until the first missing index, so a shorter list must not leave
    # the default's higher indices in place
    for prefix in ("zone", "thresold"):
        if any(k.startswith(prefix) for k in overrides):
            given = {k for k in overrides if k.startswith(prefix)}
            for k in [k for k in ini if k.startswith(prefix) and k[len(prefix):].isdigit()]:
                if k not in given:
                    del ini[k]
    return ini


def run_key(tile: str, variant: str, stage: str, ini: dict[str, str]) -> str:
    blob = json.dumps([tile, variant, stage, _stage_relevant(stage, ini)], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def xyz_path(tile: str, variant: str = "full") -> Path:
    return CACHE / variant / f"{tile}.xyz.bin"


def run_stage(tile: str, stage: str, overrides: dict, variant: str = "full", threads: int = 4) -> Path:
    """Run one stage for one tile; return the directory holding its GeoJSON layers."""
    flag, layers = STAGES[stage]
    ini = effective_ini(overrides)
    ini[flag] = "1"
    key = run_key(tile, variant, stage, ini)
    out = RUNS / stage / key[:2] / f"{key}_{tile}"
    if (out / "done").exists():
        return out
    src = xyz_path(tile, variant)
    if not src.exists():
        raise FileNotFoundError(f"{src}: run prepare() for this tile first")
    tmp = out.with_name(out.name + f".tmp{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    write_ini(tmp / "pullauta.ini", ini)
    (tmp / "t.xyz.bin").symlink_to(src)
    env = dict(os.environ, RAYON_NUM_THREADS=str(threads), RUST_LOG="warn")
    proc = subprocess.run([str(PULLAUTA), "t.xyz.bin", "norender"], cwd=tmp, env=env,
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
    return yaml.safe_load((ROOT / "sites.yaml").read_text())


def prepare(site: str, variant: str = "full", processes: int = 2, laz_dir: Path | None = None,
            site_def: dict | None = None) -> None:
    """Batch-run a site's core tiles once and cache each one's buffered point cloud."""
    s = site_def or sites()[site]
    todo = [t for t in s["core"] if not xyz_path(t, variant).exists()]
    if not todo:
        return
    laz_dir = laz_dir or (WORK / "laz" if variant == "full" else WORK / f"laz_{variant}")
    run = WORK / f"runs/prepare/{variant}/{site}"
    shutil.rmtree(run, ignore_errors=True)
    (run / "in").mkdir(parents=True)
    (run / "out").mkdir()
    for t in s["core"] + s["halo"]:
        for ext in ("laz", "las"):
            f = laz_dir / f"{t}.{ext}"
            if f.exists():
                (run / "in" / f.name).symlink_to(f.resolve())
    for t in s["core"] + s["halo"]:
        if t not in todo:
            (run / "out" / f"{t}.png").touch()
    ini = base_ini()
    ini.update(batch="1", processes=str(processes), savetempfolders="1")
    write_ini(run / "pullauta.ini", ini)
    env = dict(os.environ, RAYON_NUM_THREADS="8", RUST_LOG="info")
    with open(run / "pullauta.log", "w") as log:
        proc = subprocess.run([str(PULLAUTA)], cwd=run, env=env, stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"prepare {site}/{variant} failed, see {run}/pullauta.log")
    (CACHE / variant).mkdir(parents=True, exist_ok=True)
    for t in todo:
        d = run / f"temp_{t}_dir"
        shutil.move(d / "xyztemp.xyz.bin", xyz_path(t, variant))
    shutil.rmtree(run)
