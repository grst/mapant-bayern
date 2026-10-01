"""
Shared plumbing for the kp_tuning scripts: the region config, the tile index, downloads.

Every script takes `--config <region.yaml>` (or the KPT_CONFIG environment variable). Paths in the
config are relative to the config file. Bulky data goes to `work:` (default `<config dir>/work`),
small results to `results:` (default `<config dir>/results`).

The tile index is a CSV in mapant's samplesheet format:

    tile,url,size_bytes,sha256,crs,min_x,min_y,max_x,max_y,min_lon,min_lat,max_lon,max_lat,units[,inner_laz]

`tile` is the file name (its stem is the tile id everywhere here), bounds are in the index CRS
(metres), `sha256` may be empty, and `url` may point at a ZIP holding one tile (then `inner_laz`
names the member, or the single .laz/.las in it is used).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import threading
import time
import zipfile
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
KPT = HERE.parent  # the skill folder


# --------------------------------------------------------------------------------------------
# config


def add_config_arg(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--config", type=Path, default=os.environ.get("KPT_CONFIG"),
                    help="region config (default: $KPT_CONFIG)")


def set_config(path: Path | str | None) -> None:
    if path is None:
        raise SystemExit("no config: pass --config <region.yaml> or set KPT_CONFIG")
    os.environ["KPT_CONFIG"] = str(Path(path).resolve())
    cfg.cache_clear()
    tiles.cache_clear()


@lru_cache(maxsize=1)
def cfg() -> dict:
    p = os.environ.get("KPT_CONFIG")
    if not p:
        raise SystemExit("no config: pass --config <region.yaml> or set KPT_CONFIG")
    p = Path(p).resolve()
    c = yaml.safe_load(p.read_text())
    c["_dir"] = p.parent
    return c


def path(key: str, default: str) -> Path:
    v = cfg().get(key, default)
    p = Path(v)
    return p if p.is_absolute() else (cfg()["_dir"] / p).resolve()


def work() -> Path:
    p = path("work", "work")
    p.mkdir(parents=True, exist_ok=True)
    return p


def results() -> Path:
    p = path("results", "results")
    p.mkdir(parents=True, exist_ok=True)
    return p


def epsg() -> int:
    """The index CRS as an EPSG code (all tiles of a region share one)."""
    c = cfg().get("crs") or tiles().crs
    return int(str(c).split(":")[-1])


def kp_binary() -> Path:
    return path("kp_binary", "work/kp/pullauta")


def kp_default_ini() -> Path:
    return path("kp_default_ini", "work/kp/src/pullauta.default.ini")


def mapant_nf() -> Path:
    return path("mapant_nf", "work/mapant-nf")


def tiler_image() -> str:
    return cfg().get("tiler_image", "localhost/mapant/tiler:latest")


def user_agent() -> str:
    return cfg().get("user_agent", "mapant kp_tuning (karttapullautin parameter study)")


# --------------------------------------------------------------------------------------------
# tile index


class Tiles:
    """The tile index: id -> url, bounds; grid neighbours."""

    def __init__(self, csv: Path):
        df = pd.read_csv(csv, dtype={"sha256": str})
        df["id"] = df.tile.str.replace(r"\.(laz|las|zip)$", "", regex=True)
        if df.id.duplicated().any():
            raise SystemExit(f"{csv}: duplicate tile ids, e.g. {df.id[df.id.duplicated()].iloc[0]}")
        self.df = df.set_index("id", drop=False)
        crs = df.crs.dropna().unique()
        if len(crs) != 1:
            raise SystemExit(f"{csv}: expected one CRS, found {list(crs)}")
        self.crs = crs[0]
        sizes = (df.max_x - df.min_x).round().unique()
        if len(sizes) != 1:
            raise SystemExit(f"{csv}: expected one tile size, found {sizes}")
        self.size = float(sizes[0])
        self._grid = {(int(round(x)), int(round(y))): i for i, x, y in zip(df.id, df.min_x, df.min_y)}

    def __contains__(self, t: str) -> bool:
        return t in self.df.index

    def __len__(self) -> int:
        return len(self.df)

    def ids(self) -> list[str]:
        return list(self.df.index)

    def bounds(self, t: str) -> tuple[float, float, float, float]:
        r = self.df.loc[t]
        return float(r.min_x), float(r.min_y), float(r.max_x), float(r.max_y)

    def at(self, x: float, y: float) -> str | None:
        """The tile whose lower-left corner is (x, y)."""
        return self._grid.get((int(round(x)), int(round(y))))

    def offset(self, t: str, dx: int, dy: int) -> str | None:
        """The tile dx tiles east and dy tiles north of t."""
        x0, y0, _, _ = self.bounds(t)
        return self.at(x0 + dx * self.size, y0 + dy * self.size)

    def neighbours(self, t: str, include_self: bool = True) -> list[str]:
        """t and the up to 8 tiles around it (karttapullautin's 127 m buffer reaches only those)."""
        out = [self.offset(t, dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
               if include_self or (dx, dy) != (0, 0)]
        return [o for o in out if o]

    def in_box(self, x0: float, y0: float, x1: float, y1: float) -> list[str]:
        d = self.df
        sel = (d.max_x > x0) & (d.min_x < x1) & (d.max_y > y0) & (d.min_y < y1)
        return list(d.index[sel])

    def in_lonlat(self, w: float, s: float, e: float, n: float) -> list[str]:
        d = self.df
        if "min_lon" in d:
            sel = (d.max_lon > w) & (d.min_lon < e) & (d.max_lat > s) & (d.min_lat < n)
            return list(d.index[sel])
        from pyproj import Transformer
        tf = Transformer.from_crs(4326, self.crs, always_xy=True)
        xs, ys = zip(*[tf.transform(a, b) for a in (w, e) for b in (s, n)])
        return self.in_box(min(xs), min(ys), max(xs), max(ys))


@lru_cache(maxsize=1)
def tiles() -> Tiles:
    return Tiles(path("index", "tiles.csv"))


# --------------------------------------------------------------------------------------------
# downloads


def laz_dir() -> Path:
    p = work() / "laz"
    p.mkdir(parents=True, exist_ok=True)
    return p


def laz_path(t: str) -> Path:
    return laz_dir() / f"{t}.laz"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while b := f.read(4 << 20):
            h.update(b)
    return h.hexdigest()


def download(t: str, verify: bool = True) -> Path:
    """
    The tile's point cloud as work/laz/<id>.laz (a .las is kept under that name too: kp reads by
    content). ZIP deliveries are unpacked. Size and sha256 are checked when the index has them --
    a truncated laz does not make kp fail, it renders a plausible but wrong map.
    """
    out = laz_path(t)
    if out.exists():
        return out
    r = tiles().df.loc[t]
    tmp = out.with_name(f"{out.name}.part{os.getpid()}_{threading.get_ident()}")
    url = str(r.url)
    for attempt in range(6):
        if url.startswith("file://"):
            shutil.copy(url[7:], tmp)
            ok = True
        else:
            ok = subprocess.run(["curl", "-sSfL", "--retry", "3", "-A", user_agent(), "-o", str(tmp), url]).returncode == 0
        if ok and verify:
            size = r.get("size_bytes")
            if pd.notna(size) and tmp.stat().st_size != int(size):
                ok = False
            sha = r.get("sha256")
            if ok and isinstance(sha, str) and sha and _sha256(tmp) != sha:
                ok = False
        if ok:
            break
        tmp.unlink(missing_ok=True)
        time.sleep(15 * (attempt + 1))
    else:
        raise RuntimeError(f"download {t} failed ({url})")
    if url.lower().endswith(".zip") or zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            inner = r.get("inner_laz") if "inner_laz" in r and isinstance(r.get("inner_laz"), str) else None
            names = [n for n in z.namelist() if n.lower().endswith((".laz", ".las"))]
            member = inner if inner in z.namelist() else (names[0] if len(names) == 1 else None)
            if member is None:
                raise RuntimeError(f"{t}: cannot tell which member of the zip is the tile ({names[:5]})")
            with z.open(member) as src, open(out.with_suffix(".unz"), "wb") as dst:
                shutil.copyfileobj(src, dst)
        tmp.unlink()
        out.with_suffix(".unz").rename(out)
    else:
        tmp.rename(out)
    return out


def free_gb() -> float:
    return shutil.disk_usage(work()).free / 1e9


def kill_by_pattern(pattern: str) -> None:
    """Kill processes whose command line matches, by PID (never `pkill -f`: it matches the shell
    that runs it and kills that too)."""
    out = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout
    me = os.getpid()
    for line in out.splitlines()[1:]:
        pid, _, args = line.strip().partition(" ")
        if pattern in args and int(pid) != me and "ps -eo" not in args:
            try:
                os.kill(int(pid), 15)
            except ProcessLookupError:
                pass


def md_table(df: "pd.DataFrame", digits: int = 3) -> str:
    """A DataFrame as a GitHub markdown table (no tabulate dependency)."""
    d = df.reset_index() if df.index.name or not isinstance(df.index, pd.RangeIndex) else df
    fmt = lambda v: f"{v:.{digits}f}" if isinstance(v, float) else str(v)  # noqa: E731
    rows = ["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * len(d.columns)]
    rows += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in d.itertuples(index=False)]
    return "\n".join(rows)
