#!/usr/bin/env python3
"""
Render whole areas with several parameter sets, for the visual check in the comparison viewer.

    render_area.py run   --config c.yaml AREA [--workers 6]   # per tile: batch + per-set vege
    render_area.py check --config c.yaml AREA TILE [--set S]  # production batch vs. this, one tile
    render_area.py tile  --config c.yaml AREA [--jobs 14]     # tippecanoe -> PMTiles per (group, set)

Config:

    areas:
      allgaeu: {lonlat: [10.142, 47.536, 10.434, 47.771]}   # or box: [x0, y0, x1, y1] in the index CRS
    render_sets:                                            # sets (sets.json) per tile group
      "1.4": [kp_default, 1.4-balanced]
      "1.2": [kp_default, 1.2-balanced, 1.2-match-1.4-balanced]

Per tile: one kp batch run with the production ini (WGS84, cropped to the tile, kp defaults) gives
contours, formlines, dot knolls and cliffs -- the layers the production sets leave at the default --
and the tile's buffered point cloud. Vegetation, yellow and undergrowth of every set are then run
from that cloud (vegeonly) and cropped/reprojected with kpcrop (kp's own clipping, ported). `check`
proves the equivalence on a tile. LAZ files are fetched as tiles need them (a tile and its
neighbours) and deleted when no remaining tile needs them; downloads pause below `min_free_gb`.

A tile that fails is reported at once (not when the pool drains) and picked up by the next run.

Cost (Bavaria, 16 cores): ~1.5-2.5 min per tile with 12 sets at 6 workers, about 25 MB of vector
tiles per km² for 17 sets; tippecanoe ~2-10 min per z12 parent and set (single-threaded, so the
tile step runs parents in parallel).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import kp  # noqa: E402
import kpcrop  # noqa: E402
import sets as setsmod  # noqa: E402

VEGE_LAYERS = ("vegetation", "yellow", "undergrowth")
BASE_LAYERS = ("contours", "formlines", "dotknolls", "cliffs")
MAX_ZOOM = 17
OWNED = {  # mapant-nf bin/render_ini.py
    "batch": "1", "lazfolder": "./in", "batchoutfolder": "./out", "savetempfiles": "0", "savetempfolders": "0",
    "experimental_use_in_memory_fs": "0", "vectorvege": "1", "geojson_wgs84": "1", "batchmerge": "0",
    "output_dxf": "0", "vectorconf": "",
}


def area_dir(area: str) -> Path:
    return common.work() / f"areas/{area}"


def area_tiles(area: str) -> dict[str, str]:
    """tile -> group"""
    a = common.cfg()["areas"][area]
    T = common.tiles()
    ts = T.in_lonlat(*a["lonlat"]) if "lonlat" in a else T.in_box(*a["box"])
    g = setsmod.pd.read_csv(common.results() / "groups.csv", dtype=str)
    G = dict(g.values)
    return {t: G.get(t, "all") for t in ts}


def sets_for(group: str) -> list[str]:
    return [str(s) for s in common.cfg()["render_sets"][str(group)]]


def batch(tile: str, d: Path, threads: int, ini_extra: dict | None = None, keep_xyz: Path | None = None) -> Path:
    T = common.tiles()
    run = d / f"tmp/{tile}_batch"
    shutil.rmtree(run, ignore_errors=True)
    (run / "in").mkdir(parents=True)
    (run / "out").mkdir()
    for t in T.neighbours(tile):
        (run / "in" / f"{t}.laz").symlink_to(common.laz_path(t).resolve())
        if t != tile:
            (run / "out" / f"{t}.png").touch()
    ini = kp.base_ini()
    ini.update(OWNED)
    ini.update({k: v for k, v in (ini_extra or {}).items() if k not in ("processes", "savetempfolders")})
    ini.update(processes="1", savetempfolders="1" if keep_xyz else "0")
    kp.write_ini(run / "pullauta.ini", ini)
    with open(run / "pullauta.log", "w") as log:
        p = subprocess.run([str(common.kp_binary())], cwd=run, env=dict(os.environ, RAYON_NUM_THREADS=str(threads)),
                           stdout=log, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise RuntimeError(f"batch {tile} failed, see {run}/pullauta.log")
    if keep_xyz:
        shutil.move(run / f"temp_{tile}_dir/xyztemp.xyz.bin", keep_xyz)
        shutil.rmtree(run / f"temp_{tile}_dir")
    return run


def stage(xyz: Path, overrides: dict, work: Path, threads: int) -> Path:
    ini = kp.effective_ini(overrides)
    ini["vegeonly"] = "1"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    kp.write_ini(work / "pullauta.ini", ini)
    (work / "t.xyz.bin").symlink_to(xyz.resolve())
    p = subprocess.run([str(common.kp_binary()), "t.xyz.bin", "norender"], cwd=work,
                       env=dict(os.environ, RAYON_NUM_THREADS=str(threads), RUST_LOG="warn"), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"vege stage failed in {work}: {p.stderr[-2000:]}")
    return work / "temp"


def gz(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") if src.exists() else open(os.devnull, "rb") as fi, gzip.open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)


def process_tile(area: str, tile: str, group: str, allsets: dict, threads: int, crop) -> None:
    d = area_dir(area)
    marks = d / "done"
    marks.mkdir(parents=True, exist_ok=True)
    todo = [s for s in sets_for(group) if not (marks / f"{tile}.{s}").exists()]
    xyz = d / f"tmp/{tile}.xyz.bin"
    if (marks / f"{tile}.base").exists() and not todo:
        return
    if not ((marks / f"{tile}.base").exists() and xyz.exists()):  # else: interrupted, resume from the cloud
        run = batch(tile, d, threads, keep_xyz=xyz)
        for layer in BASE_LAYERS:
            gz(run / "out" / f"{tile}_{layer}.geojson", d / f"base/{tile}_vec/{tile}_{layer}.geojson.gz")
        for layer in VEGE_LAYERS:  # the production render of kp_default, as written by kp itself
            gz(run / "out" / f"{tile}_{layer}.geojson", d / f"sets/kp_default/{tile}_vec/{tile}_{layer}.geojson.gz")
        shutil.rmtree(run)
        (marks / f"{tile}.base").write_text("")
        (marks / f"{tile}.kp_default").write_text("")
        todo = [s for s in todo if s != "kp_default"]
    done: dict[str, Path] = {}
    for s in todo:
        o = allsets.get(s, {})
        out = d / f"sets/{s}/{tile}_vec"
        out.mkdir(parents=True, exist_ok=True)
        key = json.dumps(kp._stage_relevant("vege", kp.effective_ini(o)), sort_keys=True)
        if key in done:
            for layer in VEGE_LAYERS:
                shutil.copy(done[key] / f"{tile}_{layer}.geojson.gz", out)
        else:
            tmp = stage(xyz, o, d / f"tmp/{tile}_vege", threads)
            for layer in VEGE_LAYERS:
                crop(tmp / f"{layer}.geojson", out / f"{tile}_{layer}.geojson.gz", tile)
            shutil.rmtree(tmp.parent)
        done[key] = out
        (marks / f"{tile}.{s}").write_text("")
    xyz.unlink(missing_ok=True)


def run(area: str, workers: int, threads: int) -> None:
    T = common.tiles()
    tl = area_tiles(area)
    allsets = setsmod.load_sets()
    for g in set(tl.values()):
        missing = [s for s in sets_for(g) if s != "kp_default" and s not in allsets]
        if missing:
            raise SystemExit(f"sets missing from sets.json: {missing}")
    d = area_dir(area)
    marks = d / "done"
    marks.mkdir(parents=True, exist_ok=True)
    finished = lambda t: (marks / f"{t}.base").exists() and all((marks / f"{t}.{s}").exists() for s in sets_for(tl[t]))  # noqa: E731
    order = sorted(tl, key=lambda t: (-T.bounds(t)[1], T.bounds(t)[0]))
    queue = [t for t in order if not finished(t)]
    pending = set(queue)
    keep = {t for s in kp.sites().values() for t in s["core"] + s["halo"]}
    lock = threading.Lock()
    ready = {t: threading.Event() for t in queue}
    started, n_done = time.time(), [0]
    min_free = float(common.cfg().get("min_free_gb", 35))

    def downloader():
        for i, t in enumerate(queue):
            # the limit counts every tile handled, skipped or failed too, or it would wait forever
            while i - n_done[0] > 3 * workers + 4 or common.free_gb() < min_free:
                time.sleep(5)
            try:
                with ThreadPoolExecutor(4) as ex:
                    list(ex.map(common.download, T.neighbours(t)))
            except Exception as ex:  # noqa: BLE001
                print(f"{t}: download failed ({ex})", flush=True)
            ready[t].set()

    def cleanup():
        with lock:
            need = {n for t in pending for n in T.neighbours(t)}
        for f in common.laz_dir().glob("*.laz"):
            s = f.stem
            if s not in need and s not in keep and (s in tl or any(n in tl for n in T.neighbours(s) if s in T)):
                f.unlink(missing_ok=True)

    crop = kpcrop.Cropper()

    def work(t):
        ready[t].wait()
        t0 = time.time()
        ok = True
        try:
            process_tile(area, t, tl[t], allsets, threads, crop)
        except Exception:  # report now; the next run picks the tile up
            ok = False
            print(f"{area} {t} FAILED\n{traceback.format_exc()}", flush=True)
        with lock:
            if ok:
                pending.discard(t)
            n_done[0] += 1
            k = n_done[0]
        cleanup()
        el = time.time() - started
        print(f"{area} {t} ({tl[t]}) {time.time() - t0:.0f}s [{k}/{len(queue)}, {el / 3600:.1f} h, "
              f"~{el / k * (len(queue) - k) / 3600:.1f} h left, {common.free_gb():.0f} GB free]", flush=True)

    threading.Thread(target=downloader, daemon=True).start()
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(work, queue))
    left = [t for t in tl if not finished(t)]
    print(f"{area}: {len(tl) - len(left)}/{len(tl)} tiles complete" + (f"; rerun for {left[:10]}" if left else ""))


def check(area: str, tile: str, set_name: str) -> None:
    """A plain production batch run of one tile with a set vs. this script's output for it."""
    import numpy as np

    T = common.tiles()
    d = area_dir(area)
    for t in T.neighbours(tile):
        common.download(t)
    o = setsmod.load_sets().get(set_name, {})
    r = batch(tile, d, 8, ini_extra={k: str(v) for k, v in kp.effective_ini(o).items() if k not in OWNED})
    for layer in VEGE_LAYERS:
        a = json.loads((r / "out" / f"{tile}_{layer}.geojson").read_text())["features"] \
            if (r / "out" / f"{tile}_{layer}.geojson").exists() else []
        p = d / f"sets/{set_name}/{tile}_vec/{tile}_{layer}.geojson.gz"
        b = json.load(gzip.open(p))["features"] if p.exists() else []

        def coords(fs):
            out = []

            def walk(n):
                if n and isinstance(n[0], (int, float)):
                    out.append(n[:2])
                else:
                    for m in n:
                        walk(m)
            for f in fs:
                walk(f["geometry"]["coordinates"])
            return np.array(out)
        ca, cb = coords(a), coords(b)
        same = len(a) == len(b) and all(x["geometry"]["type"] == y["geometry"]["type"] for x, y in zip(a, b))
        dev = float(np.abs(ca - cb).max()) if ca.shape == cb.shape and len(ca) else None
        print(f"{layer:12s} production {len(a)} features / here {len(b)}; types equal {same}; "
              f"vertices {len(ca)} / {len(cb)}" + (f"; max deviation {dev:.1e} deg" if dev is not None else ""))
    shutil.rmtree(r)


def tile(area: str, jobs: int) -> None:
    """One PMTiles archive per (group, set) plus `base`, with mapant-nf's make_vector_tiles.py."""
    import mercantile
    from pyproj import Transformer

    T = common.tiles()
    d = area_dir(area)
    tl = area_tiles(area)
    out = d / "pmtiles"
    out.mkdir(exist_ok=True)
    targets = [("base", d / "base", list(tl))]
    for g in sorted(set(tl.values())):
        ts = [t for t in tl if tl[t] == g]
        targets += [(f"g{g}__{s}", d / f"sets/{s}", ts) for s in sets_for(g)]
    targets = [t for t in targets if not (out / f"{t[0]}.pmtiles").exists()]
    to_ll = Transformer.from_crs(T.crs, 4326, always_xy=True)
    nf = common.mapant_nf()
    plan = {}
    for name, src, ts in targets:
        sd = d / f"tiling/{name}"
        shutil.rmtree(sd, ignore_errors=True)
        (sd / "vec").mkdir(parents=True)
        ts = [t for t in ts if (src / f"{t}_vec").exists()]
        for t in ts:  # hard links: the container sees no symlink targets
            shutil.copytree(src / f"{t}_vec", sd / f"vec/{t}_vec", copy_function=os.link)
        parents = set()
        for t in ts:
            x0, y0, x1, y1 = T.bounds(t)
            w, s = to_ll.transform(x0, y0)
            e, n = to_ll.transform(x1, y1)
            parents |= set(mercantile.tiles(w, s, e, n, 12))
        plan[name] = (sd, sorted(parents))

    def cut(job):
        name, p = job
        sd = plan[name][0]
        r = subprocess.run(["podman", "run", "--rm", "-v", f"{sd}:/data", "-v", f"{nf / 'bin'}:/nfbin:ro", common.tiler_image(),
                            "python", "/nfbin/make_vector_tiles.py", "/data/vec", f"/data/p_{p.z}_{p.x}_{p.y}.pmtiles",
                            "--parent", str(p.z), str(p.x), str(p.y), "--max-zoom", str(MAX_ZOOM)],
                           capture_output=True, text=True)
        if r.returncode != 0:  # 110: no feature inside this parent (only a tile buffer's edge)
            if "exit status 110" not in r.stderr:
                raise RuntimeError(f"{name} {p}: {r.stderr[-3000:]}")
            (sd / f"p_{p.z}_{p.x}_{p.y}.pmtiles").unlink(missing_ok=True)

    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(cut, [(n, p) for n, (_, ps) in plan.items() for p in ps]))
    for name, (sd, parents) in plan.items():
        parts = [f"/data/p_{p.z}_{p.x}_{p.y}.pmtiles" for p in parents if (sd / f"p_{p.z}_{p.x}_{p.y}.pmtiles").exists()]
        subprocess.run(["podman", "run", "--rm", "-v", f"{sd}:/data", common.tiler_image(), "tile-join", "--force",
                        "--no-tile-size-limit", "-o", "/data/out.pmtiles", *parts], check=True, capture_output=True)
        shutil.move(sd / "out.pmtiles", out / f"{name}.pmtiles")
        shutil.rmtree(sd)
        print(f"{area}: {name}.pmtiles ({(out / f'{name}.pmtiles').stat().st_size / 1e6:.0f} MB)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "check", "tile"])
    ap.add_argument("area")
    ap.add_argument("tile_id", nargs="?")
    common.add_config_arg(ap)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--jobs", type=int, default=14)
    ap.add_argument("--set", default="kp_default")
    a = ap.parse_args()
    common.set_config(a.config)
    if a.cmd == "run":
        run(a.area, a.workers, a.threads)
    elif a.cmd == "check":
        check(a.area, a.tile_id, a.set)
    else:
        tile(a.area, a.jobs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
