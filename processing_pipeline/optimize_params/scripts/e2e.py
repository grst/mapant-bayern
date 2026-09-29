#!/usr/bin/env python3
"""
Render a site the way production does, end to end, and screenshot it in the production viewer.

    e2e.py <site> <label> [--params params.json] [--zoom 15] [--variant full]

1. karttapullautin batch run over the site's core tiles (halo tiles lend their points), with the
   ini that mapant-nf's RENDER_INI would write: the parameter set, plus the keys the pipeline owns
   (bin/render_ini.py OWNED), incl. geojson_wgs84=1. No OSM, as in the study.
2. The per-tile GeoJSON bundled into <tile>_vec/ (run_pullauta.py's layout).
3. mapant-nf's bin/make_vector_tiles.py (tippecanoe) per z12 parent, in the tiler image, then
   tile-join into one mapant.pmtiles.
4. bin/make_viewer.py fills the style from the ini; the viewer is served with range requests and
   screenshotted by headless Chromium at the site's core centre.

Output: work/e2e/<site>/<label>/{viewer/, shot_z<zoom>.png}
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import mercantile
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NF = ROOT / "work/mapant-nf"
TILER = "localhost/mapant/tiler:latest"
MAX_ZOOM = 17

OWNED = {  # mapant-nf bin/render_ini.py
    "batch": "1", "lazfolder": "./in", "batchoutfolder": "./out", "savetempfiles": "0",
    "savetempfolders": "0", "experimental_use_in_memory_fs": "0", "vectorvege": "1",
    "geojson_wgs84": "1", "batchmerge": "0", "output_dxf": "0", "vectorconf": "", "epsg": "25832",
}


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler plus single-range requests, which PMTiles needs."""

    def log_message(self, *a):
        pass

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        start, _, end = rng.removeprefix("bytes=").partition("-")
        start = int(start)
        end = min(int(end) if end else size - 1, size - 1)
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        n = getattr(self, "_remaining", None)
        if n is None:
            return super().copyfile(source, outputfile)
        outputfile.write(source.read(n))
        self._remaining = None


def render(site: str, label: str, overrides: dict, variant: str = "full", site_def: dict | None = None,
           tile_overrides: dict[str, dict] | None = None) -> Path:
    """
    `tile_overrides` (tile -> overrides) renders tiles with different parameter sets, e.g. each with
    the set of its point generation: one batch run per set, the other tiles lending points only.
    """
    s = site_def or kp.sites()[site]
    d = ROOT / f"work/e2e/{site}/{label}"
    groups: dict[str, list[str]] = {}
    for t in s["core"]:
        o = (tile_overrides or {}).get(t, overrides)
        groups.setdefault(json.dumps(o, sort_keys=True), []).append(t)
    if not (d / "vec").exists():
        vec = d / "vec.tmp"
        shutil.rmtree(vec, ignore_errors=True)
        for gi, (okey, tiles) in enumerate(groups.items()):
            run = d / f"run{gi}"
            shutil.rmtree(run, ignore_errors=True)
            (run / "in").mkdir(parents=True)
            (run / "out").mkdir()
            laz_dir = ROOT / ("work/laz" if variant == "full" else f"work/laz_{variant}")
            for t in s["core"] + s["halo"]:
                f = laz_dir / f"{t}.laz"
                if f.exists():
                    (run / "in" / f.name).symlink_to(f.resolve())
                if t not in tiles:
                    (run / "out" / f"{t}.png").touch()
            ini = kp.effective_ini(json.loads(okey))
            ini.update(OWNED)
            ini["processes"] = "2"
            kp.write_ini(run / "pullauta.ini", ini)
            shutil.copy(run / "pullauta.ini", d / ("effective.ini" if gi == 0 else f"effective{gi}.ini"))
            with open(run / "pullauta.log", "w") as log:
                subprocess.run([str(kp.PULLAUTA)], cwd=run, env=dict(os.environ, RAYON_NUM_THREADS="8"),
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            for t in tiles:
                b = vec / f"{t}_vec"
                b.mkdir(parents=True)
                for f in (run / "out").glob(f"{t}_*.geojson"):
                    shutil.move(f, b / f.name)
            shutil.rmtree(run)
        vec.rename(d / "vec")

    # parents: the z12 tiles the core tiles touch
    to_ll = Transformer.from_crs(25832, 4326, always_xy=True)
    xs = [int(t.split("_")[0]) * 1000 for t in s["core"]]
    ys = [int(t.split("_")[1]) * 1000 for t in s["core"]]
    w, south = to_ll.transform(min(xs), min(ys))
    e, north = to_ll.transform(max(xs) + 1000, max(ys) + 1000)
    parents = list(mercantile.tiles(w, south, e, north, 12))
    if not (d / "mapant.pmtiles").exists():
        for p in parents:
            subprocess.run(["podman", "run", "--rm", "-v", f"{d}:/data", "-v", f"{NF / 'bin'}:/nfbin:ro", TILER,
                            "python", "/nfbin/make_vector_tiles.py", "/data/vec", f"/data/p_{p.z}_{p.x}_{p.y}.pmtiles",
                            "--parent", str(p.z), str(p.x), str(p.y), "--max-zoom", str(MAX_ZOOM)],
                           check=True, capture_output=True)
        parts = [f"/data/p_{p.z}_{p.x}_{p.y}.pmtiles" for p in parents]
        subprocess.run(["podman", "run", "--rm", "-v", f"{d}:/data", TILER, "tile-join", "--force",
                        "--no-tile-size-limit", "-o", "/data/mapant.pmtiles", *parts], check=True, capture_output=True)
    viewer = d / "viewer"
    viewer.mkdir(exist_ok=True)
    (d / "parents.csv").write_text("z,x,y\n" + "".join(f"{p.z},{p.x},{p.y}\n" for p in parents))
    subprocess.run(["podman", "run", "--rm", "-v", f"{d}:/data", "-v", f"{NF}:/nf:ro", TILER, "python",
                    "/nf/bin/make_viewer.py", "--template-dir", "/nf/assets/viewer", "--parent-tiles",
                    "/data/parents.csv", "--ini", "/data/effective.ini", "--base-zoom", "12",
                    "--max-zoom", str(MAX_ZOOM), "--title", f"{site} {label}", "--out-dir", "/data/viewer"],
                   check=True, capture_output=True)
    shutil.copy(d / "mapant.pmtiles", viewer / "mapant.pmtiles")
    return d


def screenshot(d: Path, lon: float, lat: float, zoom: float, out: Path, size: int = 1000) -> Path:
    handler = functools.partial(RangeHandler, directory=str(d / "viewer"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/index.html#{zoom}/{lat}/{lon}"
    try:
        subprocess.run(["node", str(Path(__file__).with_name("shot.mjs")), url, str(out), str(size)],
                       check=True, timeout=300)
    finally:
        srv.shutdown()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("label")
    ap.add_argument("--params", type=Path)
    ap.add_argument("--variant", default="full")
    ap.add_argument("--zoom", type=float, default=15)
    ap.add_argument("--at", nargs=2, type=float, metavar=("E", "N"), help="EPSG:25832 centre")
    args = ap.parse_args()
    overrides = json.loads(args.params.read_text()) if args.params else {}
    d = render(args.site, args.label, overrides, args.variant)
    s = kp.sites()[args.site]
    if args.at:
        cx, cy = args.at
    else:
        cx = sum(int(t.split("_")[0]) for t in s["core"]) / len(s["core"]) * 1000 + 500
        cy = sum(int(t.split("_")[1]) for t in s["core"]) / len(s["core"]) * 1000 + 500
    lon, lat = Transformer.from_crs(25832, 4326, always_xy=True).transform(cx, cy)
    print(screenshot(d, lon, lat, args.zoom, d / f"shot_z{args.zoom:g}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
