#!/usr/bin/env python3
"""
Build the study report as one self-contained HTML page (images inlined), work/report/report.html.

Inputs: results/eval.csv, results/fronts/*.csv, results/choices.json, results/density.parquet,
work/sets.json, work/viz/*.png (made here via viz.panels), work/e2e/*/*/shot_*.png.
"""

from __future__ import annotations

import base64
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
OUT = ROOT / "work/report"

GEN = {"las14": ["fuerstenhaenge", "ochsenkopf", "raffawald", "stubenthal", "schneckenberg", "doebraberg"],
       "las12": ["auerbach", "kastensee", "schaufling"]}
REC = {"las14": "las14-balanced", "las12": "las12-balanced"}
SITE_LABEL = {
    "fuerstenhaenge": "Fürstenhänge", "ochsenkopf": "Ochsenkopf", "raffawald": "Raffawald", "auerbach": "Auerbach",
    "kastensee": "Kastensee", "stubenthal": "Stubenthal", "schneckenberg": "Schneckenberg",
    "doebraberg": "Döbraberg", "schaufling": "Schaufling",
}


def img_tag(path: Path | Image.Image, alt: str, width: int | None = None, quality: int = 82) -> str:
    im = path if isinstance(path, Image.Image) else Image.open(path)
    im = im.convert("RGB")
    if width and im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=6)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return (f'<img src="data:image/webp;base64,{b64}" alt="{html.escape(alt)}" '
            f'width="{im.width}" height="{im.height}" loading="lazy">')


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


def mean(ev, s, sites, m, variant="full"):
    d = ev[(ev.set == s) & (ev.variant == variant) & ev.site.isin(sites)]
    return d[m].mean()


def build() -> Path:
    ev = pd.read_csv(ROOT / "results/eval.csv")
    sets = json.loads((ROOT / "work/sets.json").read_text())
    choices = json.loads((ROOT / "results/choices.json").read_text())
    fronts = {k: pd.read_csv(ROOT / f"results/fronts/{k}.csv") for k in
              ("green-las14", "green-las12", "yellow", "cliffs")}
    ho14 = ["stubenthal", "schneckenberg", "doebraberg"]
    ho14c = ["stubenthal", "schneckenberg"]  # Doebraberg's scan carries almost no green
    tr14 = ["fuerstenhaenge", "ochsenkopf", "raffawald"]
    s12 = ["auerbach", "kastensee", "schaufling"]

    def delta(s, sites, m):
        return mean(ev, "kp_default", sites, m), mean(ev, s, sites, m)

    k0, k1 = delta("las14-balanced", ho14c, "green_kappa")
    b0, b1 = delta("las14-balanced", ho14c, "green_ba")
    kb0, kb1 = delta("las12-balanced", ["auerbach", "kastensee"], "green_kappa")
    cr0, cr1 = delta("las14-balanced", ["fuerstenhaenge", "stubenthal"], "cliff_recall")
    cross = mean(ev, "las14-balanced", s12, "green_kappa")
    cross0 = mean(ev, "kp_default", s12, "green_kappa")

    h = []
    h.append('<title>Mapant Bayern Parameter Study</title>')
    h.append('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600&'
             'family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">')
    h.append(f"<style>{CSS}</style><main>")
    h.append('<p class="kicker" style="margin-top:48px">mapant-bayern · karttapullautin #3 (c2a060f) · vector output</p>')
    h.append("<h1>Mapant Bayern Parameter Study</h1>")
    h.append('<div class="col">')
    h.append(f'<p class="lede">Karttapullautin’s defaults were tuned elsewhere, and in Bavaria they get the amount of green '
             f'wrong in opposite directions depending on which LiDAR campaign a tile comes from. Tuned separately for the two '
             f'point-record generations, the vegetation agrees clearly better with real orienteering maps. On LAS 1.4 holdout '
             f'maps, green-level kappa goes from {k0:.2f} to {k1:.2f} and green-vs-white balanced accuracy from {b0:.2f} to {b1:.2f}. '
             f'Cliff recall rises by about half, at somewhat lower precision on holdout. Pulse density does not need its own sets.</p>')
    h.append("</div>")

    # recommendations
    def rec_card(name, file, gen_label, tiles, sites, s):
        k0, k1 = delta(s, sites, "green_kappa")
        g0, g1 = delta(s, sites, "green_bias")
        c0, c1 = delta(s, sites, "cliff_recall")
        return (f'<div class="rec"><p class="kicker">{esc(gen_label)}</p><h3>{esc(name)}</h3>'
                f'<p class="file">params/{esc(file)}</p><p style="margin:10px 0 0;font-size:.95rem">For the {tiles}.</p>'
                f'<dl><dt>green kappa</dt><dd>{k0:.2f} → {k1:.2f}</dd><dt>green amount vs. map</dt><dd>{g0:.2f}× → {g1:.2f}×</dd>'
                f'<dt>cliff recall</dt><dd>{c0:.2f} → {c1:.2f}</dd></dl>'
                f'<p class="muted" style="font-size:.8rem;margin:8px 0 0">means over {", ".join(SITE_LABEL[x] for x in sites)}</p></div>')

    n14 = (pd.read_parquet(ROOT / "results/density.parquet").las_version == "1.4").sum()
    h.append('<div class="recs">')
    h.append(rec_card("las14", "pullauta.bayern-las14.ini", "recommended · LAS 1.4 tiles",
                      f"{n14:,} tiles delivered as LAS 1.4 / point format 6 (processed 2023 and later)",
                      tr14 + ho14c, "las14-balanced"))
    h.append(rec_card("las12", "pullauta.bayern-las12.ini", "recommended · LAS 1.2 tiles",
                      f"{71979 - n14:,} tiles delivered as LAS 1.2 / point format 1 (processed 2015–2022)",
                      s12, "las12-balanced"))
    h.append("</div>")
    h.append('<div class="col"><p>The generation is in every tile’s LAS header (version and point format), so the pipeline '
             'can choose the ini per grid without extra data. Alternatives on the same Pareto fronts are shown below: '
             '<code>las14-lessgreen</code> (about the reference’s green amount, a little less agreement), '
             '<code>las14-clean</code> (fewer, simpler patches), and <code>las12-detail</code> (more mid-green, but more green than '
             'the maps overall).</p></div>')

    # density
    h.append("<h2>Density and campaign across Bavaria</h2><div class='col'>")
    dd = pd.read_parquet(ROOT / "results/density.parquet")
    dd = dd[dd.n_points > 0]
    h.append(f"<p>The LAS header of all {len(dd):,} tiles was read with HTTP range requests. Total point density mixes "
             f"pulse density with vegetation (a forest returns more echoes per pulse), so the survey uses first returns as "
             f"a pulse count. Median pulse density is {dd.pulse_density.median():.1f}/m² (10th–90th percentile "
             f"{dd.pulse_density.quantile(.1):.1f}–{dd.pulse_density.quantile(.9):.1f}). The Alpine strip in the south "
             f"is much denser.</p>")
    rpp = (dd.n_points / dd.n_first).groupby(dd.las_version).median()
    h.append(f"<p>The sharper divide is the point-record generation: LAS 1.2 tiles record {rpp['1.2']:.2f} returns per "
             f"pulse, LAS 1.4 tiles {rpp['1.4']:.2f}. Karttapullautin’s vegetation model counts returns by height, so "
             f"with default parameters every LAS 1.4 map came out too green and every LAS 1.2 map too white (tables below). "
             f"A single set tuned on LAS 1.4 makes LAS 1.2 worse than the default (kappa {cross0:.2f} → {cross:.2f}), which "
             f"is why there are two.</p></div>")
    h.append(f'<figure class="wide">{img_tag(ROOT / "results/density_map.png", "Maps of Bavaria: pulse density and point generation per 1 km tile", 1400)}'
             f"<figcaption>Left: first returns per m² per tile. Right: point-record generation. Triangles: reference sites "
             f"(red training, magenta holdout).</figcaption></figure>")
    # thinning
    th = ev[ev.variant != "full"]
    rows = []
    for site, s in (("fuerstenhaenge", "las14-balanced"), ("raffawald", "las14-balanced"), ("auerbach", "las12-balanced")):
        cells = []
        for var in ("full", "thin50", "thin25"):
            a = ev[(ev.site == site) & (ev.variant == var) & (ev.set == "kp_default")].green_kappa.mean()
            b = ev[(ev.site == site) & (ev.variant == var) & (ev.set == s)].green_kappa.mean()
            cells.append(f'<td class="num">{a:.2f}<span class="sep">→</span><b>{b:.2f}</b></td>')
        rows.append(f'<tr><th scope="row">{SITE_LABEL[site]}</th><td class="code">{s}</td>{"".join(cells)}</tr>')
    h.append("<div class='col'><h3>Does density need its own parameters?</h3><p>Three training sites were re-rendered from "
             "copies with half and a quarter of their laser pulses dropped (whole pulses, chosen by GPS time, so the "
             "return mix stays realistic). That spans roughly the 5th percentile of Bavaria and below. The tuned sets keep "
             "their advantage at every density, and the default barely changes either. The 3 m analysis cells of the "
             "vegetation model are well above the point spacing even at a quarter of the pulses.</p></div>")
    h.append('<div class="tablewrap"><table><caption>Green-level kappa, kp default → tuned set, at full, 50 % and 25 % of the '
             'pulses.</caption><thead><tr><th>site</th><th>set</th><th>100 %</th><th>50 %</th><th>25 %</th></tr></thead><tbody>'
             + "".join(rows) + "</tbody></table></div>")

    # sites and method
    h.append("<h2>Reference maps</h2><div class='col'><p>Georeferenced maps on omaps.me were filtered to forest maps "
             "at 1:7 500–1:15 000 whose date is close to the LiDAR flight, and that are clean enough to classify by "
             "colour. Most of Bavaria’s maps on omaps.me are older event maps. Photos of printed maps with colour casts "
             "were dropped, and so were ski-O maps. Training and holdout are split by whole map. No reference covers the "
             "Alps.</p></div>")
    h.append(site_table(ev))
    h.append("<div class='col'><p>Each reference was converted into area classes, undergrowth, cliffs and knolls. First "
             "each map is white-balanced. Then every pixel gets the nearest ISOM ink in CIELAB, and line work is filled "
             "with the area symbol underneath it. Course overprint, water, settlements, OSM fields and meadows, and OSM "
             "way corridors are masked out, since production draws those from OSM. kp’s GeoJSON is rasterised on the "
             "same grid and compared at a reading scale:</p><ul>"
             "<li><b>green vs. white:</b> balanced accuracy over forest, in 10 m cells</li>"
             "<li><b>green levels:</b> quadratic-weighted kappa over white/406/408/410</li>"
             "<li><b>readability:</b> boundary length relative to the map</li>"
             "<li><b>open land:</b> F1</li><li><b>undergrowth:</b> F1 in 20 m cells</li>"
             "<li><b>cliffs:</b> 25 m cells, one cell of slack</li><li><b>knolls:</b> matched within 15 m</li></ul></div>")
    h.append(KEY)
    h.append(f'<figure class="wide">{img_tag(ROOT / "work/viz/final_raffawald.png", "Raffawald: reference, classification and kp outputs", 1560)}'
             "<figcaption>Raffawald (training, flat pine forest), 800 m window. Top: the omaps.me map, its classification, "
             "kp default. Bottom: the recommended LAS 1.4 set and two alternatives. Grey in the classification is not "
             "scored.</figcaption></figure>")

    # green
    h.append("<h2>Vegetation</h2><div class='col'><p>One multi-objective search per generation (multivariate TPE, "
             f"{len(fronts['green-las14'])} and {len(fronts['green-las12'])} trials) over the vegetation stage. It "
             "covers the height zones, the hit-ratio thresholds, the ground and top weights, the return weights, "
             "<code>greendetectsize</code>, both median filters, three greenshades mapped to 406/408/410 with "
             "<code>greenshadeisom</code>, and <code>vegesimplify</code>. Objectives were green-vs-white balanced "
             "accuracy, green-level kappa and readability. Sets were chosen on the front with the green amount held "
             "within ±25 % of the maps.</p></div>")
    marks14 = {"kp default": 0, "las14 (balanced)": choices["green-las14-balanced"]["trial"],
               "lessgreen": choices["green-las14-lessgreen"]["trial"], "clean": choices["green-las14-clean"]["trial"]}
    marks12 = {"kp default": 0, "las12 (balanced)": choices["green-las12-balanced"]["trial"],
               "detail": choices["green-las12-detail"]["trial"]}
    h.append('<div class="figs">')
    h.append(f"<figure>{scatter(fronts['green-las14'], 'green_ba', 'green_kappa', 'green vs. white, balanced accuracy', 'green-level kappa', marks14, 'LAS 1.4 vegetation trials')}"
             f"{legend()}<figcaption>LAS 1.4 search (Fürstenhänge, Ochsenkopf, Raffawald). Hover a point for its trial.</figcaption></figure>")
    h.append(f"<figure>{scatter(fronts['green-las12'], 'green_ba', 'green_kappa', 'green vs. white, balanced accuracy', 'green-level kappa', marks12, 'LAS 1.2 vegetation trials')}"
             f"{legend()}<figcaption>LAS 1.2 search (Auerbach, Kastensee). The highest-agreement trials are too green overall; "
             f"the chosen set keeps the green amount near the maps.</figcaption></figure>")
    h.append("</div>")
    metrics = [("green_ba", "green BA", 2), ("green_kappa", "kappa", 2), ("green_bias", "green ×", 2),
               ("boundary_ratio", "edges ×", 2), ("speckle", "specks/km²", 0)]
    h.append(metric_table(ev, ["kp_default", "las14-balanced", "las14-lessgreen", "las14-clean", "las14-balanced-sub3", "las12-balanced"],
                          tr14 + ho14, metrics,
                          "LAS 1.4 sites. Each cell is training mean / <b>holdout mean</b> (holdout: Stubenthal, Schneckenberg, "
                          "Döbraberg). Green × and edges × are kp relative to the map (1 is ideal). Döbraberg’s scanned map shows "
                          "very little green, which inflates its ratios for every set."))
    h.append(metric_table(ev, ["kp_default", "las12-balanced", "las12-detail", "las14-balanced"], s12, metrics,
                          "LAS 1.2 sites. Training: Auerbach, Kastensee; <b>holdout</b>: Schaufling (map from 2026 on LiDAR "
                          "from 2018, so its forest may have changed)."))
    h.append("<div class='col'><h3>More greenshades than ISOM levels</h3><p>karttapullautin median-filters and dissolves "
             "small patches on the shade index before <code>greenshadeisom</code> maps it to ISOM codes, so splitting each "
             "level into two or three shades does change the output. Tried on the balanced sets, it lowers speckle by about "
             "a tenth and leaves agreement unchanged (<code>las14-balanced-sub3</code> above). It is optional.</p></div>")
    for site in ("stubenthal", "schneckenberg", "fuerstenhaenge", "ochsenkopf", "auerbach", "schaufling", "kastensee"):
        cap = {"stubenthal": "Stubenthal (holdout, Franconian Jura)", "schneckenberg": "Schneckenberg (holdout, Oberpfalz)",
               "fuerstenhaenge": "Fürstenhänge (training, Jura rock)", "ochsenkopf": "Ochsenkopf (training, Fichtelgebirge; photo reference)",
               "auerbach": "Auerbach (training, LAS 1.2)", "schaufling": "Schaufling (holdout, LAS 1.2, low density)",
               "kastensee": "Kastensee (training, LAS 1.2; faded photo reference)"}[site]
        h.append(f'<figure class="wide">{img_tag(ROOT / f"work/viz/final_{site}.png", cap, 1560)}<figcaption>{cap}: '
                 "reference, classification, kp default / recommended set and two alternatives.</figcaption></figure>")

    # yellow
    h.append("<h2>Open land</h2><div class='col'>")
    y0, y1 = delta("las14-balanced", list(SITE_LABEL), "open_f1")
    h.append(f"<p>Open land is well detected with the defaults. The search ({len(fronts['yellow'])} trials) "
             f"found a lower <code>yellowheight</code> (0.24 m instead of 0.9 m), about the same <code>yellowthresold</code>, and a median filter on "
             f"the yellow (<code>yellowmedianboxsize</code> 13). These remove the thin yellow strings along forest roads and "
             f"rides and smooth the edges of clearings. Open-land F1 over all sites: {y0:.2f} → {y1:.2f}. Open land that OSM "
             f"maps as fields or meadows is drawn from OSM in production and was not scored.</p></div>")
    h.append(f"<figure style='max-width:560px'>{scatter(fronts['yellow'], 'open_f1', 'open_ba', 'open land F1', 'open land balanced accuracy', {'kp default': 0, 'chosen': choices['yellow']['trial']}, 'Open land trials')}{legend()}</figure>")

    # cliffs
    h.append("<h2>Cliffs</h2><div class='col'>")
    h.append(f"<p>Map cliffs are the elongated black features of 9 m or more, with OSM ways and straight lines "
             f"(rides, fences) removed. Boulders are not compared, because karttapullautin does not draw them. The search "
             f"({len(fronts['cliffs'])} trials) lowered <code>cliff1</code>/<code>cliff2</code> and "
             f"<code>cliffsteepfactor</code> and raised <code>cliffnosmallciffs</code>. More real faces are drawn, and "
             f"isolated single dashes are suppressed. Recall on the rock sites: {cr0:.2f} → {cr1:.2f}. Precision holds on "
             f"training and drops somewhat on holdout (table below). The price is some cutbanks along streams, which maps draw "
             f"as brown earth banks (Auerbach panel above).</p></div>")
    h.append(f"<figure style='max-width:560px'>{scatter(fronts['cliffs'], 'cliff_recall', 'cliff_precision', 'cliff recall', 'cliff precision', {'kp default': 0, 'chosen': choices['cliffs-precise']['trial']}, 'Cliff trials')}{legend()}</figure>")
    h.append(metric_table(ev, ["kp_default", "las14-balanced", "las12-balanced"], list(SITE_LABEL),
                          [("cliff_precision", "precision", 2), ("cliff_recall", "recall", 2), ("open_f1", "open F1", 2)],
                          "Cliffs and open land, training mean / <b>holdout mean</b> over all sites."))

    # what did not work
    h.append("<h2>Undergrowth and dot knolls: left at the defaults</h2><div class='col'>")
    h.append("<p><b>Undergrowth.</b> The stripes mappers draw (407/409) and the areas where karttapullautin finds many "
             "returns 0.25–1.2 m above ground hardly overlap. No threshold setting reached an undergrowth F1 above 0.11, and "
             "the best ones painted 7–22 times the mapped area. A threshold that matches the mapped amount on average "
             "(<code>undergrowth=0.27</code>) was tested and rejected. It adds undergrowth where the maps have none (Döbraberg "
             "14×, Kastensee 4×) and still almost none in Raffawald’s mapped undergrowth. So the defaults stay. Better "
             "undergrowth likely needs a different feature, e.g. canopy openness above low returns, not a threshold.</p>")
    h.append("<p><b>Dot knolls.</b> <code>knolls</code>, <code>smoothing</code> and <code>curviness</code> barely change "
             "what is drawn (19–23 knolls per km² in every trial). Positions agree with the maps’ brown dots only at chance "
             "level, in part because knolls extracted from 3 m/px map images are incomplete. One pattern is clear: on rocky "
             "ground (Fürstenhänge, Ochsenkopf) karttapullautin draws 10–24 times as many knolls as the map, most of them "
             "in the <code>uglydotknoll</code>/<code>uglyudepression</code> classes (63 % and 71 %). Leaving those two classes out in the "
             "style would thin them without re-rendering.</p></div>")

    # production renders
    shots = sorted((ROOT / "work/e2e").glob("*/*/shot_z16.png"))
    if shots:
        h.append("<h2>In the production viewer</h2><div class='col'><p>Rendered end to end the way mapant-nf#2 does it: "
                 "karttapullautin batch run with the pipeline’s owned keys, <code>make_vector_tiles.py</code> "
                 "(tippecanoe), <code>make_viewer.py</code> and the viewer style. Screenshots at zoom 16 (no OSM layer).</p></div>")
        h.append('<div class="figs">')
        for site in ("stubenthal", "raffawald", "auerbach"):
            for label in ("default", "tuned"):
                p = ROOT / f"work/e2e/{site}/{label}/shot_z16.png"
                if p.exists():
                    h.append(f"<figure>{img_tag(p, f'{site} {label}', 700)}<figcaption>{SITE_LABEL[site]}, "
                             f"{'kp default' if label == 'default' else 'tuned'}</figcaption></figure>")
        h.append("</div>")

    # parameters + applying
    h.append("<h2>Parameter sets</h2>")
    h.append(param_table(sets, ["las14-balanced", "las14-lessgreen", "las14-clean", "las12-balanced", "las12-detail"]))
    h.append("<div class='col'><h3>Using two inis in mapant-nf</h3><p>RENDER_INI renders one effective ini per run. "
             "The smallest change is to plan grids per generation: tag each grid with the LAS version of its tiles, which "
             "comes in large contiguous campaign blocks (see the map), and pass the matching ini to PULLAUTA_GRID. Where a grid straddles both, the neighbouring blocks differ in green density "
             "at the seam either way. The LAS 1.4 set is the safer single choice if only one ini can be used: it helps "
             "every LAS 1.4 site and costs LAS 1.2 sites a little.</p>")
    h.append("<h3>Caveats</h3><ul>"
             "<li>omaps.me dates are event or upload dates, not survey dates. Most references are within about 2 years of "
             "the flight; Schaufling is 8 years off.</li>"
             "<li>References are 3 m/px web tiles. Thin symbols (single stripes, knolls, small cliffs) are partly lost, "
             "which is why undergrowth and knolls could not be scored reliably.</li>"
             "<li>Ochsenkopf and Kastensee are photos of printed maps; their colours are less reliable.</li>"
             "<li>No reference covers the Alps or the Alpine foreland near Allgäu, where density is highest; the LAS 1.4 set "
             "there is an extrapolation.</li>"
             "<li>The search stopped at 87 (LAS 1.4) and 116 (LAS 1.2) trials. The fronts were still moving slowly.</li></ul>"
             "<p class='muted'>Code, inputs and the full per-site metrics: <code>processing_pipeline/optimize_params/</code> "
             "(<code>results/eval.csv</code>, <code>results/fronts/</code>, <code>README.md</code>).</p></div>")
    h.append("</main>")
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "report.html"
    p.write_text("\n".join(h))
    return p


if __name__ == "__main__":
    print(build())
