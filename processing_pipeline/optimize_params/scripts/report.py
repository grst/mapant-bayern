#!/usr/bin/env python3
"""
Build the study report.

    report.py offline     # report/index.html + report/gallery.html, images as files in report/img/
    report.py artifact    # work/report/report.html, one self-contained page (images inlined,
                          # a smaller gallery) for publishing

Inputs: results/eval.csv, results/border.csv, results/fronts/*.csv, results/choices.json,
results/density.parquet, work/sets.json, report/img/gallery/index.json (gallery.py),
work/viz/final_*.png (made via viz.panels), work/e2e/*/*/shot_*.png (e2e.py, border.py shots).

The offline report is not tracked in git: it shows crops of third-party orienteering maps.
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / "report"
ARTIFACT = ROOT / "work/report"

SITE_LABEL = {
    "fuerstenhaenge": "Fürstenhänge", "ochsenkopf": "Ochsenkopf", "raffawald": "Raffawald", "auerbach": "Auerbach",
    "kastensee": "Kastensee", "stubenthal": "Stubenthal", "schneckenberg": "Schneckenberg",
    "doebraberg": "Döbraberg", "schaufling": "Schaufling", "roethenbach": "Röthenbacher Holz",
    "fuerstenschlag": "Fürstenschlag", "kozina": "Kozina", "tyrolsberg": "Tyrolsberg", "reitimwinkl": "Reit im Winkl",
    "kohlbruck": "Kohlbruck", "hechenberg": "Hechenberg",
}
# sites whose reference does not map a feature (see optimize.SKIP)
NO_GREEN = {"reitimwinkl"}
NO_CLIFFS = {"kohlbruck", "reitimwinkl"}
# Döbraberg's scan shows almost no green: kept for open land and cliffs, not for green agreement
WEAK_GREEN = {"doebraberg"}


class Images:
    """Inline images (artifact) or write them next to the page (offline)."""

    def __init__(self, mode: str, out_dir: Path):
        self.mode, self.dir = mode, out_dir / "img"

    def tag(self, src: Path | Image.Image, alt: str, width: int | None = None, quality: int = 82,
            name: str | None = None, link: bool = False) -> str:
        im = src if isinstance(src, Image.Image) else Image.open(src)
        im = im.convert("RGB")
        if width and im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=quality, method=6)
        if self.mode == "artifact":
            url = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
        else:
            stem = name or (Path(src).stem if not isinstance(src, Image.Image) else
                            hashlib.sha1(buf.getvalue()).hexdigest()[:12])
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{stem}.webp").write_bytes(buf.getvalue())
            url = f"img/{stem}.webp"
        tag = (f'<img src="{url}" alt="{html.escape(alt)}" width="{im.width}" height="{im.height}" '
               f'loading="lazy">')
        return f'<a href="{url}">{tag}</a>' if link and self.mode == "offline" else tag


def esc(s) -> str:
    return html.escape(str(s))


# ------------------------------------------------------------------ charts (inline SVG)

def scatter(df: pd.DataFrame, x: str, y: str, xlabel: str, ylabel: str, marks: dict[str, int],
            title: str) -> str:
    """All trials (muted), the Pareto front (series 1), kp default and chosen sets labelled."""
    W, H, ml, mr, mt, mb = 520, 340, 56, 18, 16, 46
    d = df.dropna(subset=[x, y])
    xs, ys = d[x].to_numpy(float), d[y].to_numpy(float)
    x0, x1 = np.percentile(xs, 2), xs.max()
    y0, y1 = np.percentile(ys, 2), ys.max()
    padx, pady = (x1 - x0) * 0.06 or 0.01, (y1 - y0) * 0.08 or 0.01
    x0, x1, y0, y1 = x0 - padx, x1 + padx, y0 - pady, y1 + pady

    def sx(v):
        return ml + (v - x0) / (x1 - x0) * (W - ml - mr)

    def sy(v):
        return H - mb - (v - y0) / (y1 - y0) * (H - mt - mb)

    def ticks(a, b, n=5):
        step = 10 ** math.floor(math.log10((b - a) / n))
        for m in (1, 2, 5, 10):
            if (b - a) / (step * m) <= n:
                step *= m
                break
        t = math.ceil(a / step) * step
        out = []
        while t <= b + 1e-12:
            out.append(round(t, 10))
            t += step
        return out

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}" class="chart">']
    for t in ticks(x0, x1):
        parts.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{mt}" y2="{H - mb}" class="grid"/>'
                     f'<text x="{sx(t):.1f}" y="{H - mb + 16}" class="tick" text-anchor="middle">{t:g}</text>')
    for t in ticks(y0, y1):
        parts.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" class="grid"/>'
                     f'<text x="{ml - 8}" y="{sy(t) + 4:.1f}" class="tick" text-anchor="end">{t:g}</text>')
    parts.append(f'<text x="{(ml + W - mr) / 2}" y="{H - 8}" class="axis" text-anchor="middle">{esc(xlabel)}</text>')
    parts.append(f'<text transform="translate(14 {(mt + H - mb) / 2}) rotate(-90)" class="axis" '
                 f'text-anchor="middle">{esc(ylabel)}</text>')
    inside = (xs >= x0) & (ys >= y0)
    for (_, r), ok in zip(d.iterrows(), inside):
        if not ok or r.get("pareto"):
            continue
        parts.append(f'<circle cx="{sx(r[x]):.1f}" cy="{sy(r[y]):.1f}" r="3.2" class="pt-all">'
                     f'<title>trial {int(r.number)}: {x} {r[x]:.3f}, {y} {r[y]:.3f}</title></circle>')
    for _, r in d[d.pareto & (d[x] >= x0) & (d[y] >= y0)].iterrows():
        parts.append(f'<circle cx="{sx(r[x]):.1f}" cy="{sy(r[y]):.1f}" r="4.5" class="pt-front">'
                     f'<title>trial {int(r.number)} (Pareto): {x} {r[x]:.3f}, {y} {r[y]:.3f}</title></circle>')
    # chosen sets usually sit together at the front's corner: stack their labels in a column to the
    # lower left of the cluster, each with a leader line to its point
    placed = 0
    for label, num in marks.items():
        row = d[d.number == num]
        if row.empty:
            continue
        r = row.iloc[0]
        cx, cy = sx(max(r[x], x0)), sy(max(r[y], y0))
        cls = "pt-default" if label == "kp default" else "pt-chosen"
        if label == "kp default":
            lx, ly, anchor = cx + 9, cy - 9, "start"
        else:
            lx, ly, anchor = sx(x0 + (x1 - x0) * 0.62), mt + 34 + 17 * placed, "end"
            placed += 1
            parts.append(f'<line x1="{lx + 3:.1f}" y1="{ly - 4:.1f}" x2="{cx:.1f}" y2="{cy:.1f}" class="leader"/>')
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" class="{cls}"><title>{esc(label)}: trial {num}, '
                     f'{x} {r[x]:.3f}, {y} {r[y]:.3f}</title></circle>'
                     f'<text x="{lx:.1f}" y="{ly:.1f}" class="lbl" text-anchor="{anchor}">{esc(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def legend() -> str:
    return ('<div class="legend"><span><i class="sw all"></i>trial</span><span><i class="sw front"></i>Pareto front</span>'
            '<span><i class="sw chosen"></i>chosen set</span><span><i class="sw default"></i>kp default</span></div>')


# ------------------------------------------------------------------ tables

def fmt(v, digits=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    return f"{v:.{digits}f}"


def metric_table(ev: pd.DataFrame, sets: list[str], sites: list[str], metrics: list[tuple[str, str, int]],
                 caption: str) -> str:
    rows = []
    d = ev[(ev.variant == "full") & ev.site.isin(sites)]
    base = d[d.set == "kp_default"].set_index("site")
    head = "".join(f"<th>{esc(lbl)}</th>" for _, lbl, _ in metrics)
    for s in sets:
        ds = d[d.set == s].set_index("site")
        cells = []
        for m, _, dig in metrics:
            for split in ("train", "holdout"):
                pass
            tr = ds[ds.split == "train"][m].mean() if m in ds else float("nan")
            ho = ds[ds.split == "holdout"][m].mean() if m in ds else float("nan")
            btr = base[base.split == "train"][m].mean()
            bho = base[base.split == "holdout"][m].mean()
            better = "" if s == "kp_default" else (
                " up" if (not math.isnan(ho) and ho > bho + 0.005) else (" down" if (not math.isnan(ho) and ho < bho - 0.005) else ""))
            if m in ("green_bias", "open_bias", "ug_bias", "boundary_ratio"):
                better = ""
            cells.append(f'<td class="num">{fmt(tr, dig)}<span class="sep">/</span><b class="{better.strip()}">{fmt(ho, dig)}</b></td>')
        rows.append(f"<tr><th scope=\"row\">{esc(s)}</th>{''.join(cells)}</tr>")
    return (f'<div class="tablewrap"><table><caption>{caption}</caption><thead><tr><th>set</th>{head}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def site_table(ev: pd.DataFrame) -> str:
    sites = yaml.safe_load((ROOT / "sites.yaml").read_text())
    dens = pd.read_parquet(ROOT / "results/density.parquet").set_index("tile")
    rows = []
    for k, s in sites.items():
        dd = dens.loc[[t + ".laz" for t in s["core"]]]
        gen = "LAS 1.4" if (dd.las_version == "1.4").all() else "LAS 1.2"
        rows.append(
            f"<tr><th scope=\"row\">{esc(SITE_LABEL[k])}</th><td>{esc(s['map_name'])}</td><td class=\"num\">{esc(s['map_date'][:4])}</td>"
            f"<td class=\"num\">{int(dd.creation_year.median())}</td><td>{gen}</td>"
            f"<td class=\"num\">{dd.pulse_density.median():.1f}</td><td class=\"num\">{len(s['core'])}</td>"
            f"<td>{'training' if s['split'] == 'train' else 'holdout'}</td><td class=\"note\">{esc(s['note'])}</td></tr>")
    return ('<div class="tablewrap"><table><caption>Reference sites. Map year is the upload/event date on omaps.me; '
            'LiDAR year is the processing date in the LAS header. Pulses are first returns per m².</caption>'
            '<thead><tr><th>site</th><th>omaps.me map</th><th>map</th><th>LiDAR</th><th>generation</th><th>pulses/m²</th>'
            '<th>km²</th><th>split</th><th>terrain</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def param_table(sets: dict, names: list[str]) -> str:
    import kp

    base = kp.base_ini()
    keys = sorted({k for n in names for k in sets[n]}, key=lambda k: (k.rstrip("0123456789"), k))
    head = "".join(f"<th>{esc(n)}</th>" for n in names)
    rows = []
    for k in keys:
        cells = "".join(f'<td class="code">{esc(sets[n].get(k, base.get(k, "")))}</td>' for n in names)
        rows.append(f'<tr><th scope="row" class="code">{esc(k)}</th><td class="code muted">{esc(base.get(k, "–"))}</td>{cells}</tr>')
    return (f'<div class="tablewrap"><table class="params"><caption>Changed keys. Everything else is '
            f'karttapullautin’s default ini.</caption><thead><tr><th>key</th><th>kp default</th>{head}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>")


# ------------------------------------------------------------------ page

CSS = """
:root{
  --paper:#fafaf6; --ink:#1e231f; --muted:#5b645c; --rule:#dcdfd6; --panel:#f1f2ec;
  --accent:#a6552b; --accent-ink:#8a4420;
  --s1:#2a78d6; --s2:#eb6834; --s-all:#b9beb5; --s-def:#1e231f;
  --up:#1b7a4a; --down:#b3402f;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  color-scheme:dark; --paper:#141815; --ink:#e3e7e0; --muted:#9aa39a; --rule:#2d342e; --panel:#1b201c;
  --accent:#d98a5c; --accent-ink:#e7a47c; --s1:#3987e5; --s2:#d95926; --s-all:#4a524b; --s-def:#e3e7e0;
  --up:#5cc58d; --down:#ec7c6b; }}
:root[data-theme="dark"]{
  color-scheme:dark; --paper:#141815; --ink:#e3e7e0; --muted:#9aa39a; --rule:#2d342e; --panel:#1b201c;
  --accent:#d98a5c; --accent-ink:#e7a47c; --s1:#3987e5; --s2:#d95926; --s-all:#4a524b; --s-def:#e3e7e0;
  --up:#5cc58d; --down:#ec7c6b; }
body{background:var(--paper); color:var(--ink); font:17px/1.6 "Source Serif 4", Georgia, serif;
  padding-inline:20px; padding-block:0 64px;}
main{max-width:1180px; margin:0 auto;}
.col{max-width:68ch;}
h1,h2,h3{font-family:"Barlow Semi Condensed","Arial Narrow",sans-serif; font-weight:600; line-height:1.15;
  text-wrap:balance; letter-spacing:.005em;}
h1{font-size:2.6rem; margin:56px 0 8px;}
h2{font-size:1.75rem; margin:56px 0 12px; padding-top:18px; border-top:2px solid var(--accent);}
h3{font-size:1.25rem; margin:32px 0 8px;}
.kicker{font:600 .8rem/1 "Barlow Semi Condensed",sans-serif; letter-spacing:.12em; text-transform:uppercase;
  color:var(--accent-ink);}
.lede{font-size:1.15rem; color:var(--ink);}
p{margin:0 0 14px;} a{color:var(--accent-ink);}
.muted,.note{color:var(--muted);}
code,.code{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:.82em;}
.num{font-family:"IBM Plex Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums; font-size:.85em;
  text-align:right; white-space:nowrap;}
.recs{display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:18px; margin:22px 0;}
.rec{background:var(--panel); border:1px solid var(--rule); border-radius:6px; padding:16px 18px;}
.rec h3{margin:0 0 4px;} .rec .file{font-family:"IBM Plex Mono",monospace; font-size:.8rem; color:var(--muted);}
.rec dl{display:grid; grid-template-columns:auto 1fr; gap:4px 14px; margin:12px 0 0; font-size:.92rem;}
.rec dt{color:var(--muted);} .rec dd{margin:0; font-family:"IBM Plex Mono",monospace; font-size:.85rem;}
.tablewrap{overflow-x:auto; margin:16px 0 24px;}
table{border-collapse:collapse; font-size:.9rem; min-width:100%;}
caption{caption-side:bottom; text-align:left; color:var(--muted); font-size:.85rem; padding-top:8px;}
th,td{padding:6px 10px; border-bottom:1px solid var(--rule); vertical-align:top;}
thead th{font:600 .78rem/1.2 "Barlow Semi Condensed",sans-serif; letter-spacing:.06em; text-transform:uppercase;
  color:var(--muted); text-align:left; border-bottom:1.5px solid var(--ink);}
tbody th{text-align:left; font-weight:600;}
td .sep{color:var(--muted); padding:0 4px;} b.up{color:var(--up);} b.down{color:var(--down);}
table.params td,table.params th{font-size:.78rem; padding:4px 8px;}
.figs{display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:26px; margin:18px 0;}
figure{margin:0;} figcaption{color:var(--muted); font-size:.88rem; margin-top:6px; max-width:80ch;}
figure img{max-width:100%; height:auto; display:block; border:1px solid var(--rule);}
.chart{width:100%; height:auto; background:var(--paper);}
.chart .grid{stroke:var(--rule); stroke-width:1;} .chart .tick{fill:var(--muted); font:11px "IBM Plex Mono",monospace;}
.chart .axis{fill:var(--ink); font:600 12px "Barlow Semi Condensed",sans-serif;}
.chart .pt-all{fill:var(--s-all);} .chart .pt-front{fill:var(--s1); stroke:var(--paper); stroke-width:2;}
.chart .pt-chosen{fill:var(--s2); stroke:var(--paper); stroke-width:2;}
.chart .leader{stroke:var(--muted); stroke-width:1;}
.chart .zero{stroke:var(--muted); stroke-width:1.2;} .chart .meanbar{stroke:var(--s2); stroke-width:3.5;}
.chart .pt-default{fill:none; stroke:var(--s-def); stroke-width:2.2;}
.chart .lbl{fill:var(--ink); font:600 12px "Barlow Semi Condensed",sans-serif; paint-order:stroke;
  stroke:var(--paper); stroke-width:3px;}
.legend{display:flex; flex-wrap:wrap; gap:14px; font-size:.82rem; color:var(--muted); margin:4px 0 0;}
.legend .sw{display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:-1px;}
.sw.all{background:var(--s-all);} .sw.front{background:var(--s1);} .sw.chosen{background:var(--s2);}
.sw.default{border:2px solid var(--s-def); box-sizing:border-box;}
.wide img{width:100%;}
.keyrow{display:flex; flex-wrap:wrap; gap:6px 16px; font-size:.82rem; color:var(--muted); margin:6px 0 10px;}
.keyrow i{display:inline-block; width:14px; height:10px; margin-right:5px; vertical-align:-1px; border:1px solid var(--rule);}
ul{padding-left:1.2em;} li{margin:0 0 6px;}
:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}
@media (max-width:520px){ h1{font-size:2rem;} .figs{grid-template-columns:1fr;} }
"""

KEY = ('<div class="keyrow"><span><i style="background:#fff"></i>white forest</span>'
       '<span><i style="background:#ffdba6"></i>open land (403)</span><span><i style="background:#ffba53"></i>open land (401)</span>'
       '<span><i style="background:#c5e8be"></i>406</span><span><i style="background:#8bcd84"></i>408</span>'
       '<span><i style="background:#3eaf50"></i>410</span><span><i style="background:repeating-linear-gradient(90deg,#3eaf50 0 2px,#fff 2px 6px)"></i>undergrowth</span>'
       '<span><i style="background:#000"></i>cliffs / rock</span><span><i style="background:#a6552b"></i>knolls</span>'
       '<span><i style="background:#8a8f88"></i>not scored (masked)</span></div>')



# ------------------------------------------------------------------ border chart

BORDER_LABEL = {
    "kp_default": "kp default",
    "gen:las12-r1,las14-r1": "round 1, per generation",
    "gen:las12-balanced,las14-balanced": "recommended, per generation",
    "las14-balanced": "las14 set on all tiles",
    "gen:las12-detail,las14-balanced": "las12-detail + las14",
}


def border_strip(bd: pd.DataFrame, names: list[str], key: str, xlabel: str) -> str:
    """One row per set: each block's step (LAS 1.4 side minus LAS 1.2 side) as a dot, the mean as a bar."""
    W, ml, mr, mt, row, mb = 640, 190, 20, 14, 46, 40
    H = mt + row * len(names) + mb
    steps = {n: (bd[bd.set == n][f"{key}_las14"] - bd[bd.set == n][f"{key}_las12"]).to_numpy() for n in names}
    allv = np.concatenate([v for v in steps.values() if len(v)])
    lim = max(abs(np.percentile(allv, 2)), abs(np.percentile(allv, 98)), 0.05) * 1.1
    x0, x1 = -lim, lim

    def sx(v):
        return ml + (min(max(v, x0), x1) - x0) / (x1 - x0) * (W - ml - mr)

    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(xlabel)}" class="chart">']
    step = 0.2 if lim > 0.45 else (0.1 if lim > 0.25 else 0.05)
    t = math.ceil(x0 / step) * step
    while t <= x1 + 1e-9:
        cls = "zero" if abs(t) < 1e-9 else "grid"
        p.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{mt}" y2="{H - mb}" class="{cls}"/>'
                 f'<text x="{sx(t):.1f}" y="{H - mb + 16}" class="tick" text-anchor="middle">{t:+.2f}</text>')
        t += step
    p.append(f'<text x="{(ml + W - mr) / 2}" y="{H - 6}" class="axis" text-anchor="middle">{esc(xlabel)}</text>')
    rng = np.random.default_rng(0)
    for i, n in enumerate(names):
        v = steps[n]
        cy = mt + row * i + row / 2
        p.append(f'<text x="{ml - 12}" y="{cy + 4:.1f}" class="lbl" text-anchor="end">{esc(BORDER_LABEL.get(n, n))}</text>')
        blocks = bd[bd.set == n].block.tolist()
        for val, b in zip(v, blocks):
            jy = cy + rng.uniform(-9, 9)
            p.append(f'<circle cx="{sx(val):.1f}" cy="{jy:.1f}" r="3.6" class="pt-front"><title>{esc(b)}: {val:+.3f}</title></circle>')
        if len(v):
            m = v.mean()
            p.append(f'<line x1="{sx(m):.1f}" x2="{sx(m):.1f}" y1="{cy - 15:.1f}" y2="{cy + 15:.1f}" class="meanbar">'
                     f'<title>mean {m:+.3f}</title></line>')
    p.append("</svg>")
    return "".join(p)


# ------------------------------------------------------------------ page

def mean(ev, s, sites, m, variant="full"):
    d = ev[(ev.set == s) & (ev.variant == variant) & ev.site.isin(sites)]
    return d[m].mean()


def site_groups() -> dict:
    sites = yaml.safe_load((ROOT / "sites.yaml").read_text())
    dens = pd.read_parquet(ROOT / "results/density.parquet", columns=["tile", "las_version"])
    v = dict(zip(dens.tile.str.removesuffix(".laz"), dens.las_version))
    g = {}
    for k, s in sites.items():
        gen = "las14" if all(v[t] == "1.4" for t in s["core"]) else "las12"
        g.setdefault((gen, s["split"]), []).append(k)
    return g


def build(mode: str) -> Path:
    out_dir = OFFLINE if mode == "offline" else ARTIFACT
    IM = Images(mode, out_dir)
    ev = pd.read_csv(ROOT / "results/eval.csv")
    sets = json.loads((ROOT / "work/sets.json").read_text())
    choices = json.loads((ROOT / "results/choices.json").read_text())
    fronts = {k: pd.read_csv(ROOT / f"results/fronts/{k}.csv") for k in
              ("green-las14", "green-las12", "yellow-las14", "yellow-las12", "cliffs")}
    G = site_groups()
    tr14, ho14 = G[("las14", "train")], G[("las14", "holdout")]
    tr12, ho12 = G[("las12", "train")], G[("las12", "holdout")]
    g_tr14 = [s for s in tr14 if s not in NO_GREEN]
    g_ho14 = [s for s in ho14 if s not in WEAK_GREEN]
    all_sites = tr14 + ho14 + tr12 + ho12
    have = set(ev.set)

    def delta(s, sites, m, base="kp_default"):
        return mean(ev, base, sites, m), mean(ev, s, sites, m)

    k0, k1 = delta("las14-balanced", g_ho14, "green_kappa")
    b0, b1 = delta("las14-balanced", g_ho14, "green_ba")
    kr1 = mean(ev, "las14-r1", g_ho14, "green_kappa")
    k120, k121 = delta("las12-balanced", ho12, "green_kappa")
    kr112 = mean(ev, "las12-r1", ho12, "green_kappa")

    bd = pd.read_csv(ROOT / "results/border.csv") if (ROOT / "results/border.csv").exists() else pd.DataFrame()

    def bstep(name, key="green_share"):
        d = bd[bd.set == name]
        x = d[f"{key}_las14"] - d[f"{key}_las12"]
        return x.mean(), x.std() / math.sqrt(max(len(x), 1)), x.abs().mean()

    h = ['<title>Mapant Bayern Parameter Study</title>',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600&'
         'family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">',
         f"<style>{CSS}</style><main>",
         '<p class="kicker" style="margin-top:48px">mapant-bayern · karttapullautin #3 (c2a060f) · vector output · round 2</p>',
         "<h1>Mapant Bayern Parameter Study</h1>", '<div class="col">']
    lede = (f'Karttapullautin’s defaults get the amount of green wrong in opposite directions depending on which '
            f'LiDAR generation a tile comes from. Tuned separately for the two generations and checked against '
            f'{len(all_sites)} real orienteering maps, vegetation agrees clearly better. On the LAS 1.4 holdout maps, '
            f'green-level kappa goes from {k0:.2f} (default) to {k1:.2f}, and green-vs-white balanced accuracy from '
            f'{b0:.2f} to {b1:.2f}.')
    if len(bd):
        m0, _, _ = bstep("kp_default")
        m1, _, _ = bstep("gen:las12-balanced,las14-balanced")
        lede += (f' Where the two generations meet, the jump in green share at the tile edge shrinks from '
                 f'{m0 * 100:+.0f} to {m1 * 100:+.0f} percentage points on average.')
    h.append(f'<p class="lede">{lede}</p>')
    if mode == "artifact":
        h.append('<p class="muted">This page shows one comparison sheet per site. The offline copy '
                 '(<code>processing_pipeline/optimize_params/report/</code>) has a sheet for every scored tile.</p>')
    else:
        h.append('<p class="muted">Offline copy. <a href="gallery.html">Gallery</a>: every scored tile of every site, '
                 'reference next to the parameter sets.</p>')
    h.append("</div>")

    # recommendations
    def rec_card(name, file, gen_label, tiles, sites_, s):
        k0, k1 = delta(s, sites_, "green_kappa")
        g0, g1 = delta(s, sites_, "green_bias")
        c0, c1 = delta(s, [x for x in sites_ if x not in NO_CLIFFS], "cliff_recall")
        return (f'<div class="rec"><p class="kicker">{esc(gen_label)}</p><h3>{esc(name)}</h3>'
                f'<p class="file">params/{esc(file)}</p><p style="margin:10px 0 0;font-size:.95rem">For the {tiles}.</p>'
                f'<dl><dt>green kappa</dt><dd>{k0:.2f} → {k1:.2f}</dd><dt>green amount vs. map</dt><dd>{g0:.2f}× → {g1:.2f}×</dd>'
                f'<dt>cliff recall</dt><dd>{c0:.2f} → {c1:.2f}</dd></dl>'
                f'<p class="muted" style="font-size:.8rem;margin:8px 0 0">means over {", ".join(SITE_LABEL[x] for x in sites_)}</p></div>')

    n14 = (pd.read_parquet(ROOT / "results/density.parquet").las_version == "1.4").sum()
    h.append('<div class="recs">')
    h.append(rec_card("las14", "pullauta.bayern-las14.ini", "recommended · LAS 1.4 tiles",
                      f"{n14:,} tiles delivered as LAS 1.4 / point format 6 (processed 2023 and later)",
                      g_tr14 + g_ho14, "las14-balanced"))
    h.append(rec_card("las12", "pullauta.bayern-las12.ini", "recommended · LAS 1.2 tiles",
                      f"{71979 - n14:,} tiles delivered as LAS 1.2 / point format 1 (processed 2015–2022)",
                      tr12 + ho12, "las12-balanced"))
    h.append("</div>")
    h.append('<div class="col"><p>The pipeline samplesheet <code>input/laz_tiles.csv</code> now carries '
             '<code>las_version</code> and <code>pullauta_ini</code> for every tile, written by '
             '<code>scripts/samplesheet_ini.py</code> from the header survey. mapant-nf still renders one ini per run; '
             'using the column is the next step there.</p><p>Alternatives from the same Pareto fronts, all in '
             '<code>params/</code>: <code>las14-clean</code> (a little more green, smoother patches), '
             '<code>las12-lessgreen</code> (about the maps’ green amount; best on the two LAS 1.2 holdout maps, weaker on '
             'training), <code>las12-clean</code>, and <code>las12-detail</code> (most agreement on training but greener; it '
             'matches the LAS 1.4 set best at the border).</p></div>')

    # round 2
    h.append("<h2>What changed since round 1</h2><div class='col'><ul>"
             f"<li><b>More reference maps:</b> {len(all_sites)} instead of 9. Seven new maps from omaps.me, including the first "
             "Alpine one (Reit im Winkl, a ski-O map used for open land only) and two more LAS 1.2 maps (Kohlbruck, "
             "Hechenberg). omaps.worldofo.com could not be used: it only answers with a Cloudflare bot challenge, and the "
             "older maps.worldofo.com database returns no maps.</li>"
             "<li><b>Registration fixed:</b> round 1 masked both images with the reference’s mask when estimating each "
             "map’s offset, which pinned the estimate to zero. With the fix, offsets of up to 10 m were found (Raffawald 7 m, "
             "Schneckenberg 11 m) and applied. Every number in this report is re-scored with them.</li>"
             "<li><b>Wider search:</b> where round 1’s Pareto fronts sat on a bound (for LAS 1.2 "
             "<code>greendetectsize</code>, <code>medianboxsize</code>, <code>vegesimplify</code>; for LAS 1.4 "
             "<code>topweight</code>, the density thresholds, <code>pointvolumefactor</code>), the bound was widened. "
             "Each round-2 search started from round 1’s Pareto front.</li>"
             "<li><b>Generation border:</b> a new check of how different the two generations look side by side.</li>"
             "</ul></div>")

    # density
    h.append("<h2>Density and point generation across Bavaria</h2><div class='col'>")
    dd = pd.read_parquet(ROOT / "results/density.parquet")
    dd = dd[dd.n_points > 0]
    rpp = (dd.n_points / dd.n_first).groupby(dd.las_version).median()
    cross = mean(ev, "las14-balanced", tr12 + ho12, "green_kappa")
    cross0 = mean(ev, "kp_default", tr12 + ho12, "green_kappa")
    h.append(f"<p>The LAS header of all {len(dd):,} tiles was read with HTTP range requests. The survey counts first "
             f"returns, as a pulse count, because total density mixes pulse density with vegetation. Median pulse density "
             f"is {dd.pulse_density.median():.1f}/m² (10th–90th percentile {dd.pulse_density.quantile(.1):.1f}–"
             f"{dd.pulse_density.quantile(.9):.1f}).</p>"
             f"<p>The sharper divide is the point-record generation. LAS 1.2 tiles record {rpp['1.2']:.2f} returns per pulse "
             f"and LAS 1.4 tiles {rpp['1.4']:.2f}. Karttapullautin’s vegetation model counts returns by height, so with "
             f"the defaults LAS 1.4 maps come out too green and LAS 1.2 maps too white. The LAS 1.4 set applied to LAS 1.2 "
             f"tiles scores below the default there (kappa {cross0:.2f} → {cross:.2f}).</p></div>")
    h.append(f'<figure class="wide">{IM.tag(ROOT / "results/density_map.png", "Maps of Bavaria: pulse density and point generation per 1 km tile", 1400)}'
             f"<figcaption>Left: first returns per m² per tile. Right: point-record generation. Triangles: reference sites "
             f"(red training, magenta holdout).</figcaption></figure>")
    rows = []
    for site, s in (("fuerstenhaenge", "las14-balanced"), ("raffawald", "las14-balanced"), ("auerbach", "las12-balanced")):
        cells = []
        for var in ("full", "thin50", "thin25"):
            a = ev[(ev.site == site) & (ev.variant == var) & (ev.set == "kp_default")].green_kappa.mean()
            b = ev[(ev.site == site) & (ev.variant == var) & (ev.set == s)].green_kappa.mean()
            cells.append(f'<td class="num">{fmt(a)}<span class="sep">→</span><b>{fmt(b)}</b></td>')
        rows.append(f'<tr><th scope="row">{SITE_LABEL[site]}</th><td class="code">{s}</td>{"".join(cells)}</tr>')
    h.append("<div class='col'><h3>Does density need its own parameters?</h3><p>Three training sites were re-rendered from "
             "copies with half and a quarter of their laser pulses (whole pulses dropped by GPS time). That reaches Bavaria’s "
             "5th percentile and below. The tuned sets keep their advantage at every density.</p></div>")
    h.append('<div class="tablewrap"><table><caption>Green-level kappa, kp default → tuned set, at full, 50 % and 25 % of the '
             'pulses.</caption><thead><tr><th>site</th><th>set</th><th>100 %</th><th>50 %</th><th>25 %</th></tr></thead><tbody>'
             + "".join(rows) + "</tbody></table></div>")

    # references
    h.append("<h2>Reference maps</h2><div class='col'><p>Georeferenced omaps.me maps were kept if they are forest maps at "
             "1:7 500–1:15 000, dated close to the LiDAR, and clean enough to classify by colour. Training and holdout are "
             "split by whole map. Rejected in round 2: Silberhütte (photo too pale to recover its greens), and three 2026 "
             "maps near Hersbruck whose tiles are not public.</p></div>")
    h.append(site_table(ev))
    h.append("<div class='col'><p>Each reference is white-balanced; every pixel gets the nearest ISOM ink in CIELAB, and line "
             "work is filled with the area symbol under it. Course overprint, water, settlements, OSM fields and meadows, and "
             "OSM way corridors are masked, since production draws them from OSM. kp’s GeoJSON is rasterised on the same grid "
             "and compared at reading scale: green vs. white as balanced accuracy in 10 m cells; green levels as "
             "quadratic-weighted kappa over white/406/408/410; readability as boundary length relative to the map; open land "
             "as F1; cliffs in 25 m cells with one cell of slack; knolls matched within 15 m.</p></div>")
    h.append(KEY)

    # vegetation
    h.append("<h2>Vegetation</h2><div class='col'>")
    h.append(f"<p>One multi-objective search per generation ({len(fronts['green-las14'])} and "
             f"{len(fronts['green-las12'])} trials in round 2). It covers the height zones, hit-ratio thresholds, ground and "
             "top weights, return weights, <code>greendetectsize</code>, both median filters, three greenshades mapped to "
             "406/408/410 and <code>vegesimplify</code>. The objectives were green-vs-white balanced accuracy, green-level "
             "kappa and readability. Sets were picked on the front with the green amount within ±25 % of the maps.</p>"
             f"<p>Round 2 against round 1, on the holdout maps: LAS 1.4 kappa {kr1:.2f} → {k1:.2f}, LAS 1.2 kappa "
             f"{kr112:.2f} → {k121:.2f} (default {k120:.2f}).</p></div>")
    marks14 = {"kp default": 0, "las14 (balanced)": choices["green-las14-balanced"]["trial"]}
    marks12 = {"kp default": 0, "las12 (balanced)": choices["green-las12-balanced"]["trial"]}
    for k in ("lessgreen", "clean"):
        if f"green-las14-{k}" in choices:
            marks14[k] = choices[f"green-las14-{k}"]["trial"]
    for k in ("detail", "clean"):
        if f"green-las12-{k}" in choices:
            marks12[k] = choices[f"green-las12-{k}"]["trial"]
    h.append('<div class="figs">')
    h.append(f"<figure>{scatter(fronts['green-las14'], 'green_ba', 'green_kappa', 'green vs. white, balanced accuracy', 'green-level kappa', marks14, 'LAS 1.4 vegetation trials')}"
             f"{legend()}<figcaption>LAS 1.4 search ({', '.join(SITE_LABEL[x] for x in g_tr14)}). Hover a point for its trial.</figcaption></figure>")
    h.append(f"<figure>{scatter(fronts['green-las12'], 'green_ba', 'green_kappa', 'green vs. white, balanced accuracy', 'green-level kappa', marks12, 'LAS 1.2 vegetation trials')}"
             f"{legend()}<figcaption>LAS 1.2 search ({', '.join(SITE_LABEL[x] for x in tr12)}).</figcaption></figure>")
    h.append("</div>")
    metrics = [("green_ba", "green BA", 2), ("green_kappa", "kappa", 2), ("green_bias", "green ×", 2),
               ("boundary_ratio", "edges ×", 2), ("speckle", "specks/km²", 0)]
    s14 = [x for x in ["kp_default", "las14-r1", "las14-balanced", "las14-lessgreen", "las14-clean", "las14-balanced-sub3",
                       "las12-balanced"] if x in have]
    s12 = [x for x in ["kp_default", "las12-r1", "las12-balanced", "las12-lessgreen", "las12-clean", "las12-detail",
                       "las12-balanced-sub3",
                       "las14-balanced"] if x in have]
    h.append(metric_table(ev, s14, g_tr14 + g_ho14, metrics,
                          f"LAS 1.4 sites. Each cell is training mean / <b>holdout mean</b> (holdout: "
                          f"{', '.join(SITE_LABEL[x] for x in g_ho14)}; Döbraberg’s scan shows almost no green and is left out "
                          f"here). Green × and edges × are kp relative to the map (1 is ideal). <code>-r1</code> is round 1’s "
                          f"recommendation."))
    h.append(metric_table(ev, s12, tr12 + ho12, metrics,
                          f"LAS 1.2 sites. Training: {', '.join(SITE_LABEL[x] for x in tr12)}; <b>holdout</b>: "
                          f"{', '.join(SITE_LABEL[x] for x in ho12)}."))
    t0, t1 = delta("las14-balanced", ["tyrolsberg"], "green_kappa")
    h.append(f"<div class='col'><h3>Maps disagree with each other</h3><p>No single set fits every map. Raffawald, "
             f"Schneckenberg and Röthenbacher Holz show less green than karttapullautin finds with any setting, while the "
             f"two 2026 maps from the Hersbruck/Neumarkt Jura (Fürstenschlag, Tyrolsberg) show much more, mostly as 408/410. "
             f"On Tyrolsberg the recommended set scores below the default (kappa {t0:.2f} → {t1:.2f}). This looks like "
             f"differences in mapping style between regions and mappers more than in the forest, so the sets aim at the "
             f"middle.</p></div>")
    h.append("<div class='col'><h3>More greenshades than ISOM levels</h3><p>karttapullautin median-filters and dissolves "
             "small patches on the shade index before <code>greenshadeisom</code> maps it to ISOM codes, so splitting each "
             "level into sub-shades changes the output. On the balanced sets it lowers speckle a little and leaves "
             "agreement about the same (<code>-sub3</code> rows). It stays optional.</p></div>")

    # comparison sheets (one per site here; all tiles in the gallery)
    h.append("<h3>Reference against the parameter sets</h3>")
    gal = json.loads((OFFLINE / "img/gallery/index.json").read_text())
    shown = set()
    for g in gal:
        if g["site"] in shown:
            continue
        shown.add(g["site"])
        cap = (f"{SITE_LABEL[g['site']]} ({'training' if g['split'] == 'train' else 'holdout'}, LAS {g['generation']}), "
               f"tile {g['tile']}: " + ", ".join(g["panels"]) + ".")
        src = OFFLINE / g["file"]
        h.append(f'<figure class="wide">{IM.tag(src, cap, 1560 if mode == "offline" else 1300, quality=78, name="sheet_" + src.stem, link=True)}'
                 f"<figcaption>{esc(cap)}</figcaption></figure>")
    if mode == "offline":
        h.append('<p><a href="gallery.html">All tiles of all sites →</a></p>')

    # border
    if len(bd):
        nb = bd.block.nunique()
        h.append("<h2>Where the generations meet</h2><div class='col'>")
        m0, se0, a0 = bstep("kp_default")
        m1, se1, a1 = bstep("gen:las12-balanced,las14-balanced")
        h.append(f"<p>The first version of the map shows seams where a LAS 1.2 campaign meets a LAS 1.4 one, e.g. north of "
                 f"Würzburg. To measure them, {nb} blocks of 2 × 2 km were picked across Bavaria. In each, two forest tiles of "
                 f"one generation sit next to two of the other (forest by the share of multiple returns, the block north of "
                 f"Würzburg included). Every tile is rendered with the set of its own generation. Each side’s green share (green "
                 f"area over non-open area) is then compared. Forest does change across any line, but not systematically "
                 f"with the scanning campaign, so the mean step over many blocks estimates the seam a parameter set leaves.</p>"
                 f"<p>With kp’s defaults the LAS 1.4 side is {m0 * 100:+.0f} ± {se0 * 100:.0f} percentage points greener on "
                 f"average (typical absolute step {a0 * 100:.0f} points). With the recommended pair it is {m1 * 100:+.0f} ± "
                 f"{se1 * 100:.0f} points (absolute {a1 * 100:.0f}). This was only measured, not optimised: the sets were "
                 f"chosen for agreement with the maps.</p></div>")
        names = [n for n in BORDER_LABEL if n in set(bd.set)]
        h.append(f"<figure>{border_strip(bd, names, 'green_share', 'green share, LAS 1.4 side minus LAS 1.2 side')}"
                 "<figcaption>Each dot is one block, the bar the mean. Zero means both sides equally green.</figcaption></figure>")
        rows = []
        for n in names:
            cells = []
            for key in ("green_share", "green_level", "open_share"):
                mm, se, ab = bstep(n, key)
                cells.append(f'<td class="num">{mm:+.3f} ± {se:.3f}</td><td class="num">{ab:.3f}</td>')
            rows.append(f'<tr><th scope="row">{esc(BORDER_LABEL.get(n, n))}</th>{"".join(cells)}</tr>')
        h.append('<div class="tablewrap"><table><caption>Step across the border (LAS 1.4 side minus LAS 1.2 side), mean ± '
                 'standard error, and mean absolute step. Green level is the mean ISOM level over non-open area '
                 '(0 white … 3 = 410).</caption><thead><tr><th>set</th><th>green share</th><th>|·|</th><th>green level</th>'
                 '<th>|·|</th><th>open share</th><th>|·|</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")
        md, sed, _ = bstep("gen:las12-detail,las14-balanced") if "gen:las12-detail,las14-balanced" in set(bd.set) else (float("nan"),) * 3
        h.append(f"<div class='col'><p>Round 1’s pair left a smaller step ({bstep('gen:las12-r1,las14-r1')[0] * 100:+.0f} points) "
                 f"than round 2’s, because round 2’s LAS 1.4 set draws more green. Pairing it with <code>las12-detail</code> "
                 f"closes the seam ({md * 100:+.0f} ± {sed * 100:.0f} points), but that set agrees less with the LAS 1.2 "
                 f"holdout maps. Agreement with the maps was given priority, so the recommendation stays; "
                 f"<code>las12-detail</code> is the option if the seam matters more.</p></div>")
        bshots = sorted((ROOT / "work/e2e").glob("border_*/*/shot_*.png"))
        if bshots:
            h.append("<div class='col'><p>Production-path renders of blocks (kp batch → tippecanoe → viewer style). The "
                     "border runs through the middle of each image.</p></div>")
            notes = {"b567_5528v": " North of Würzburg, where the first map version shows the seam. OSM maps 45 % of the "
                                   "LAS 1.4 half as forest and 18 % of the LAS 1.2 half, so much of this contrast is "
                                   "land cover."}
            order = {"b744_5457v": 0, "b606_5528v": 1, "b567_5528v": 2}
            for bdir in sorted({p.parents[1] for p in bshots},
                               key=lambda d: order.get(d.name.removeprefix("border_"), 9)):
                pair = [bdir / lab / f for lab in ("default", "tuned") for f in
                        sorted(p.name for p in (bdir / lab).glob("shot_*.png"))[:1]]
                if len(pair) < 2:
                    continue
                bname = bdir.name.removeprefix("border_")
                b = yaml.safe_load((ROOT / "border.yaml").read_text())[bname]
                (x14, y14), (x12, y12) = (tuple(map(int, b[g][0].split("_"))) for g in ("las14", "las12"))
                where = (f"LAS 1.4 {'north' if y14 > y12 else 'south'}" if bname.endswith("v")
                         else f"LAS 1.4 {'east' if x14 > x12 else 'west'}")
                h.append('<div class="figs">')
                for p, lab in zip(pair, ("kp default", "recommended, per generation")):
                    h.append(f"<figure>{IM.tag(p, f'{bname} {lab}', 760, name=f'border_{bname}_{p.parent.name}')}"
                             f"<figcaption>Block {esc(bname)} ({where}), {lab}.{notes.get(bname, '') if lab == 'kp default' else ''}</figcaption></figure>")
                h.append("</div>")

    # yellow
    h.append("<h2>Open land</h2><div class='col'>")
    y0, y1 = delta("las14-balanced", tr14 + ho14, "open_f1")
    z0, z1 = delta("las12-balanced", tr12 + ho12, "open_f1")
    yl = sets["las14-balanced"]
    h.append(f"<p>Open land is well detected with the defaults. Round 1 found a lower <code>yellowheight</code> "
             f"({esc(yl.get('yellowheight', '0.9'))} m instead of 0.9 m), a similar <code>yellowthresold</code> and a median "
             f"filter on the yellow (<code>yellowmedianboxsize</code> {esc(yl.get('yellowmedianboxsize', '-'))}), which remove "
             f"the thin yellow strings along forest roads. Round 2 searched open land again per generation, with the Alpine "
             f"ski-O map included, and found nothing better in F1: the trials with higher balanced accuracy all draw about "
             f"1.4 times the maps’ open land. So round 1’s yellow settings stay. Open-land F1: LAS 1.4 {y0:.2f} → {y1:.2f}, "
             f"LAS 1.2 {z0:.2f} → {z1:.2f}. Open land that OSM maps as fields or meadows is drawn from OSM in production "
             f"and was not scored.</p></div>")
    h.append('<div class="figs">')
    for gen in ("las14", "las12"):
        h.append(f"<figure>{scatter(fronts['yellow-' + gen], 'open_f1', 'open_ba', 'open land F1', 'open land balanced accuracy', {'kp default': 0, 'chosen': choices['yellow-' + gen]['trial']}, 'Open land trials ' + gen)}"
                 f"{legend()}<figcaption>{gen.replace('las', 'LAS ').replace('14', '1.4').replace('12', '1.2')} open-land search.</figcaption></figure>")
    h.append("</div>")

    # cliffs
    cl_sites = [x for x in all_sites if x not in NO_CLIFFS]
    cr0, cr1 = delta("las14-balanced", ["fuerstenhaenge", "stubenthal", "fuerstenschlag", "tyrolsberg"], "cliff_recall")
    h.append("<h2>Cliffs</h2><div class='col'>")
    h.append(f"<p>Map cliffs are the elongated black features of 9 m or more, after removing OSM ways and straight lines "
             f"(rides, fences). Boulders are not compared, as karttapullautin does not draw them. The search "
             f"({len(fronts['cliffs'])} trials, both generations pooled, since cliffs come from the ground model) lowered the "
             f"steepness thresholds and raised <code>cliffnosmallciffs</code>. More real faces are drawn and isolated single "
             f"dashes are suppressed. Recall on the Jura rock sites: {cr0:.2f} → {cr1:.2f}. Some stream cutbanks, which maps "
             f"draw as brown earth banks, come with it.</p></div>")
    h.append(f"<figure style='max-width:560px'>{scatter(fronts['cliffs'], 'cliff_recall', 'cliff_precision', 'cliff recall', 'cliff precision', {'kp default': 0, 'chosen': choices['cliffs']['trial']}, 'Cliff trials')}{legend()}</figure>")
    h.append(metric_table(ev, [x for x in ["kp_default", "las14-r1", "las14-balanced", "las12-balanced"] if x in have], cl_sites,
                          [("cliff_precision", "precision", 2), ("cliff_recall", "recall", 2), ("open_f1", "open F1", 2)],
                          "Cliffs and open land, training mean / <b>holdout mean</b> over all sites with a usable cliff "
                          "reference (both generations)."))

    # what did not work
    h.append("<h2>Undergrowth and dot knolls: left at the defaults</h2><div class='col'>")
    h.append("<p><b>Undergrowth.</b> The stripes mappers draw (407/409) and the areas where karttapullautin finds many "
             "returns 0.25–1.2 m above ground hardly overlap. No threshold reached an undergrowth F1 above 0.11, and the best "
             "ones painted 7–22 times the mapped area. A threshold matching the mapped amount on average "
             "(<code>undergrowth=0.27</code>) adds undergrowth where the maps have none and still finds almost none where "
             "they have a lot. Better undergrowth likely needs a different feature, not a threshold.</p>")
    h.append("<p><b>Dot knolls.</b> <code>knolls</code>, <code>smoothing</code> and <code>curviness</code> barely change what "
             "is drawn (19–23 knolls per km² in every trial), and positions agree with the maps’ dots only at chance level. "
             "On rocky ground karttapullautin draws 10–24 times as many knolls as the maps, most of them in the "
             "<code>uglydotknoll</code>/<code>uglyudepression</code> classes (63 % and 71 %). Leaving those two classes out of "
             "the style would thin them out without re-rendering.</p></div>")

    # production renders
    shots = [p for p in sorted((ROOT / "work/e2e").glob("*/*/shot_z16.png")) if not p.parents[1].name.startswith("border_")]
    if shots:
        h.append("<h2>In the production viewer</h2><div class='col'><p>Rendered end to end as mapant-nf#2 does: "
                 "karttapullautin batch with the pipeline’s owned keys, <code>make_vector_tiles.py</code> (tippecanoe), "
                 "<code>make_viewer.py</code> and the viewer style. Zoom 16, no OSM layer.</p></div>")
        h.append('<div class="figs">')
        for site in sorted({p.parents[1].name for p in shots}):
            for label in ("default", "tuned"):
                p = ROOT / f"work/e2e/{site}/{label}/shot_z16.png"
                if p.exists():
                    h.append(f"<figure>{IM.tag(p, f'{site} {label}', 700, name=f'e2e_{site}_{label}')}<figcaption>"
                             f"{SITE_LABEL.get(site, site)}, {'kp default' if label == 'default' else 'recommended'}"
                             f"</figcaption></figure>")
        h.append("</div>")

    # parameters
    h.append("<h2>Parameter sets</h2>")
    h.append(param_table(sets, [x for x in ["las14-balanced", "las14-clean", "las12-balanced", "las12-lessgreen",
                                            "las12-clean", "las12-detail"] if x in sets]))
    h.append("<div class='col'><h3>Caveats</h3><ul>"
             "<li>omaps.me dates are event or upload dates, not survey dates. Most references are within about 2 years of "
             "the flight; Schaufling is 8 years off.</li>"
             "<li>References are 3 m/px web tiles, several of them photos of printed maps. Thin symbols (stripes, knolls, "
             "small cliffs) are partly lost.</li>"
             "<li>The only Alpine reference is a ski-O map, which maps open land but not vegetation density. The green "
             "sets are not tested in the Alps.</li>"
             "<li>The border check assumes forest does not change systematically with the scanning campaign. The campaign "
             "blocks follow administrative and flight boundaries, not landscape, so this should hold on average.</li></ul>"
             "<p class='muted'>Code, inputs and per-site metrics: <code>processing_pipeline/optimize_params/</code> "
             "(<code>results/eval.csv</code>, <code>results/border.csv</code>, <code>results/fronts/</code>, "
             "<code>README.md</code>).</p></div>")
    h.append("</main>")
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / ("index.html" if mode == "offline" else "report.html")
    p.write_text(page("\n".join(h), mode))
    if mode == "offline":
        gallery_page(IM, gal)
    return p


def page(body: str, mode: str) -> str:
    """The artifact host adds its own skeleton; the offline file needs a full document."""
    if mode == "artifact":
        return body
    return f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n</head>\n<body>\n{body}\n</body>\n</html>\n'


def gallery_page(IM: Images, gal: list[dict]) -> Path:
    h = ['<title>Mapant Bayern Parameter Study · Gallery</title>',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f"<style>{CSS}</style><main>",
         '<p class="kicker" style="margin-top:48px"><a href="index.html">← report</a></p>',
         "<h1>Gallery</h1>",
         f"<div class='col'><p>Every scored 1 km tile of every reference site ({len(gal)} tiles). Left to right: the omaps.me map, "
         "its classification (grey is not scored), kp default, round 1’s set and the recommended set of the tile’s point "
         "generation. Click a sheet for full size.</p></div>", KEY]
    by_site: dict[str, list[dict]] = {}
    for g in gal:
        by_site.setdefault(g["site"], []).append(g)
    h.append("<nav class='col'><p>" + " · ".join(f'<a href="#{s}">{esc(SITE_LABEL[s])}</a>' for s in by_site) + "</p></nav>")
    for site, gs in by_site.items():
        g0 = gs[0]
        h.append(f'<h2 id="{site}">{esc(SITE_LABEL[site])}</h2><p class="muted">'
                 f"{'training' if g0['split'] == 'train' else 'holdout'} · LAS {g0['generation']}</p>")
        for g in gs:
            src = OFFLINE / g["file"]
            h.append(f'<figure class="wide"><a href="{g["file"]}"><img src="{g["file"]}" alt="{esc(site)} {g["tile"]}" '
                     f'loading="lazy"></a><figcaption>Tile {g["tile"]}: {esc(", ".join(g["panels"]))}.</figcaption></figure>')
    h.append("</main>")
    p = OFFLINE / "gallery.html"
    p.write_text(page("\n".join(h), "offline"))
    return p


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "offline"))
