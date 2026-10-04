"""
sets.html for the sweep viewer (compare.py build --sweep): every set of sweep_sets.py, with the
tables of the plan generated from the same definitions the render used.
"""

from __future__ import annotations

import html

import sweep_sets

GROUPS = [
    ("anchor", "Anchor"),
    ("base", "Base"),
    ("green", "Green detail: one or two knobs of B"),
    ("yellow", "Yellow: one knob of B"),
    ("combined", "Green and yellow combined"),
]

GLOSSARY = {
    "vegesimplify": "Simplification of the vector vegetation polygons. Higher means simpler outlines. "
                    "kp's default is 2.0; below 1.5 is not useful.",
    "medianboxsize": "Median filter over the green raster. Larger means smoother green with fewer small patches.",
    "medianboxsize2": "Second median filter on the green levels. Larger removes more small patches.",
    "greendetectsize": "Size of the window in which green hits are counted.",
    "yellowheight": "A return lower than this above ground counts as a low hit (open land).",
    "yellowthresold": "A cell is yellow when its share of low hits is above this.",
    "yellowfirstlast": "A single return (first = last) above yellowheight counts this many times against yellow.",
    "yellowmedianboxsize": "Median filter over the yellow raster. 0 means off; larger removes small yellow patches.",
    "greenshades": "Green value at which each shade starts. Mapped to ISOM 406/408/410 by greenshadeisom.",
    "thresold1": "roof low | roof high | green hits / ground ratio that gives green factor 1 (same for 2–5)",
    "zone1": "low | high | roof | factor: returns between low and high above ground count as green hits (same for 2–3)",
}

CSS = """
:root { --bg: #fff; --fg: #1d1d1f; --muted: #6b6b70; --line: #d8d8dc; --soft: #f4f4f6; --accent: #b0006e; --hl: #fde7f3; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg: #1b1b1d; --fg: #ececf0; --muted: #a0a0a8; --line: #3a3a3f; --soft: #242427; --accent: #ff5cb8; --hl: #4a1f38; }
}
:root[data-theme="dark"] { --bg: #1b1b1d; --fg: #ececf0; --muted: #a0a0a8; --line: #3a3a3f; --soft: #242427; --accent: #ff5cb8; --hl: #4a1f38; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.5 system-ui, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 16px 16px 64px; }
h1 { font-size: 22px; margin: 8px 0 4px; }
h2 { font-size: 17px; margin: 32px 0 8px; border-bottom: 1px solid var(--line); padding-bottom: 4px; }
h3 { font-size: 14px; margin: 20px 0 6px; }
p, li { max-width: 75ch; }
a { color: var(--accent); }
.muted { color: var(--muted); }
.scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; }
table { border-collapse: collapse; font-size: 13px; width: max-content; min-width: 100%; }
th, td { padding: 4px 8px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; vertical-align: top; }
th { background: var(--soft); font-weight: 600; position: sticky; top: 0; }
td.k, th.k { position: sticky; left: 0; background: var(--bg); font-family: ui-monospace, monospace; }
th.k { background: var(--soft); z-index: 1; }
td.wrap { white-space: normal; min-width: 260px; }
td.num { font-family: ui-monospace, monospace; }
.hl { background: var(--hl); font-weight: 600; }
code { font-family: ui-monospace, monospace; font-size: 12.5px; }
nav { display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; margin: 8px 0 0; }
"""


def _e(s) -> str:
    return html.escape(str(s))


def _table(head: list[str], rows: list[list[str]], first_key: bool = True) -> str:
    h = "".join(f'<th class="{"k" if i == 0 and first_key else ""}">{c}</th>' for i, c in enumerate(head))
    return f'<div class="scroll"><table><tr>{h}</tr>{"".join(rows)}</table></div>'


def overview_html(sw: dict[str, dict]) -> str:
    D = sweep_sets.default_vege()
    prod = {**D, **sweep_sets.production()}
    B = {**D, **sw["sw-vs2.0"]["params"]}
    keys = sweep_sets.GRADIENT_KEYS
    eff = {name: {**D, **s["params"]} for name, s in sw.items()}

    # 1: default / production / B
    rows = []
    for k in keys:
        cls = ' class="num hl"' if prod[k] != B[k] else ' class="num"'
        rows.append(f'<tr><td class="k">{k}</td><td class="num">{_e(D[k])}</td><td class="num">{_e(prod[k])}</td>'
                    f'<td{cls}>{_e(B[k])}</td></tr>')
    t_base = _table(["key", "kp default", "production ini (prod-las14)", "B (sw-vs2.0)"], rows)

    # 2: the one-knob sets
    sections = []
    n = 0
    for g, title in GROUPS:
        rows = []
        for name, s in sw.items():
            if s["group"] != g:
                continue
            n += 1
            rows.append(f'<tr><td class="k">{_e(name)}</td><td class="num">{n}</td><td class="wrap">{_e(s["change"])}</td>'
                        f'<td class="wrap">{_e(s["question"])}</td></tr>')
        sections.append(f"<h3>{_e(title)}</h3>" + _table(["set", "#", "change", "question it answers"], rows))
    t_sets = "".join(sections)

    # 3: gradient
    grad = [name for name, s in sw.items() if s["group"] == "gradient"]
    rows = []
    for k in keys:
        cells = "".join(f'<td class="num">{_e(eff[g][k])}</td>' for g in grad)
        rows.append(f'<tr><td class="k">{k}</td><td class="num">{_e(D[k])}</td>{cells}<td class="num">{_e(B[k])}</td></tr>')
    t_grad = _table(["key", "kp default (t=0)", *[f"{g}<br><span class='muted'>t={sw[g]['t']:.2f}</span>" for g in grad],
                     "B (t=1)"], rows)

    # 4: everything
    all_keys = sorted(set(D) | {k for e in eff.values() for k in e})
    names = list(sw)
    rows = []
    for k in all_keys:
        cells = ""
        for name in names:
            v = eff[name].get(k, "")
            cells += f'<td class="num{" hl" if v != B.get(k, "") else ""}">{_e(v)}</td>'
        rows.append(f'<tr><td class="k">{k}</td><td class="num">{_e(D.get(k, ""))}</td>{cells}</tr>')
    t_all = _table(["key", "kp default", *[_e(x) for x in names]], rows)

    gloss = "".join(f"<li><code>{_e(k)}</code>: {_e(v)}</li>" for k, v in GLOSSARY.items())
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sweep parameter sets</title><link rel="icon" href="data:,"><style>{CSS}</style></head>
<body><main>
<p><a href="index.html">← back to the map viewer</a></p>
<h1>Parameter sets of the sweep</h1>
<p class="muted">Allgäu, all 621 tiles (LAS 1.2 and LAS 1.4 alike: every set is used on both). Every set renders vegetation, yellow and undergrowth from the same point cloud.
Contours, knolls and cliffs are kp's defaults and the same in every set. {len(sw)} sets, plus <code>kp_default</code> from the earlier render.</p>
<nav><a href="#base">Production vs. B</a><a href="#sets">One-knob sets</a><a href="#gradient">Gradient</a>
<a href="#keys">What the keys do</a><a href="#all">All values</a></nav>

<h2 id="base">Production ini vs. B</h2>
<p><b>B</b> (<code>sw-vs2.0</code>) is the production ini <code>params/pullauta.bayern-las14.ini</code> with
<code>vegesimplify</code> at kp's default of 2.0 instead of 1.31, because values below 1.5 are not useful. Every one-knob set below is B
with the listed change. <code>prod-las14</code> is the production ini unchanged, for comparison. A highlighted cell differs from production.</p>
<p class="muted">The earlier Allgäu render <code>las14-balanced</code> is not the production ini: it had yellowheight 0.24,
yellowmedianboxsize 13 and tuned cliffs. This sweep therefore uses the production ini itself.</p>
{t_base}

<h2 id="sets">One-knob sets</h2>
<p>Each set moves one or two keys of B toward kp's default (or past it) to see which key costs the green detail and the yellow.</p>
{t_sets}

<h2 id="gradient">Gradient from kp default to B (production candidates)</h2>
<p>These sets move every key at once, at t = 1/6 … 5/6 of the way from kp's default (t = 0) to B (t = 1).</p>
<ul>
<li>Interpolation is linear, except the green-hit ratio in <code>thresold1–5</code>: it spans a decade, so it is interpolated geometrically.</li>
<li>Integer keys are rounded.</li>
<li><code>vegesimplify</code> is 2.0 at both ends.</li>
<li>Green shades: kp's default 11 <code>greenshades</code> with <code>greenshadeisom=406|406|408|408|410</code> start
406 at 0.2, 408 at 0.5 and 410 at 1.3. Those three start values are interpolated toward B's 0.644 / 2.356 / 4.828, with
<code>greenshadeisom=406|408|410</code>.</li>
</ul>
{t_grad}

<h2 id="keys">What the keys do</h2>
<p>Yellow in kp: a cell is yellow when its share of low hits is above <code>yellowthresold</code>. So more yellow comes from a higher
<code>yellowheight</code>, a lower <code>yellowthresold</code>, a lower <code>yellowfirstlast</code> and a smaller
<code>yellowmedianboxsize</code>.</p>
<ul>{gloss}</ul>

<h2 id="all">All vegetation values per set</h2>
<p>The effective value of every key that kp's vegetation step reads. Highlighted: differs from B.</p>
{t_all}
</main></body></html>
"""
