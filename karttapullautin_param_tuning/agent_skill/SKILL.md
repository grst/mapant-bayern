---
name: kp-tuning
description: Tune karttapullautin (pullauta) vegetation and open-land parameters — white vs. green, the three ISOM green levels, yellow — for a new LiDAR region (e.g. another German state for mapant) against real orienteering maps from omaps.me. Starts with a batch-effect check of the LAZ deliveries (LAS version, campaign, season, sensor), searches a parameter set per tile group, optionally matches groups across their borders, and renders comparison areas in a local MapLibre viewer for the final visual judgement. Use when asked to optimize, tune or calibrate pullauta/karttapullautin parameters for a region, or to check LiDAR tiles for batch effects.
---

# Tuning karttapullautin for a LiDAR region

This is the procedure from the mapant-bayern parameter study
(`processing_pipeline/bayern/kp_param_tuning/`, three rounds, 2026-09/10) packaged for reuse. All scripts
are in `scripts/`; every one takes `--config <region.yaml>` (or `KPT_CONFIG`) and has its details
in its docstring (`python scripts/X.py -h`). Method details: `reference/method.md`. What Bavaria
found (use it as the prior): `reference/bavaria.md`.

**Scope.** Tune only vegetation (white / 406 / 408 / 410) and open land (401/403). Leave cliffs,
dot knolls, contours and undergrowth at kp's defaults: in Bavaria the reference maps could not
support tuning them (few mapped rock features, knolls lost in 3 m/px photos, undergrowth F1 ≤ 0.1),
and the user chose the defaults for production after looking at the results.

**What counts is the map a person sees**: scores are at perception scale (10 m cells), there is a
readability objective, and the final decision is a visual one in the comparison viewer. Report
progress, findings and time estimates to the user regularly; the whole thing takes 1–3 days of
mostly unattended compute.

## 0. Setup

- Region index: a CSV in mapant's samplesheet format (`tile,url,size_bytes,sha256,crs,min_x,...`).
  The `mapant-germany` branch has indices and a survey of open LiDAR per state
  (`processing_pipeline/input/laz_tiles_*.csv`, `docs/lidar_open_data_germany.md`): Bayern and
  Rheinland-Pfalz with sha256, NRW without, Thüringen/Brandenburg/Sachsen/Berlin as ZIPs (the
  scripts unpack a ZIP per tile; Berlin's 8 bundles need unpacking to `file://` URLs first).
  CRS is EPSG:25832 or 25833; tiles are 1 km (2 km in Sachsen) — all read from the index.
- Config: copy `config/region.example.yaml` next to the study (outside the skill folder), fill in
  paths. Bulk data goes to `work:` (git-ignore it).
- Python: `uv sync` in this folder (or any env with the `pyproject.toml` deps).
- karttapullautin: the vector-output build (grst/karttapullautin#3 or later) **with
  `patches/kp-hardlink.patch`** — without it every stage run copies a 1+ GB point cloud and the
  search becomes IO-bound (terabytes of writes). Build in the rust image:
  `podman run --rm -v $PWD:/src -w /src docker.io/library/rust:1.97-bookworm cargo build --release`.
- mapant-nf checkout (`bin/make_vector_tiles.py`, `bin/make_viewer.py`, `assets/viewer`) and its
  tiler image (tippecanoe) for the viewer; Playwright + Chromium for screenshots (`PLAYWRIGHT_ROOT`,
  `CHROMIUM`).
- Budget (16 cores, 31 GB RAM): disk ~1 GB per cached point cloud (×5 the LAZ), plan 150–300 GB
  free; downloads ~25 MB/s.

## 1. Batch effects (always first)

Tiles of one region often come from several campaigns, sensors, seasons or processing lines. kp's
vegetation depends on the return structure, so such a change becomes a visible seam in the map
(Bavaria: LAS 1.2 vs 1.4, ~13 points more green on the 1.4 side with kp's defaults).

```sh
python scripts/survey.py --config c.yaml            # all headers by HTTP range (~70k tiles/40 min)
python scripts/sample_points.py --config c.yaml     # point stats of ~4 forest tiles per header stratum
python scripts/batch_effects.py --config c.yaml     # report + maps in <results>/batch/
```

Read `batch/report.md` and look at the maps. For each header field that varies, the report gives
the seam length and the jump in returns per pulse across it vs. within (ratio ≫ 1 along a long seam =
batch effect; ≈ 1 = label only). The point sample adds season (GPS time → month; leaf-off vs
leaf-on matters a lot), canopy penetration (`canopy_ground_share`), undergrowth returns
(`canopy_low_share` — what kp turns into green), classification scheme and intensity scaling.
`creation_year` is the processing date, not the flight. The report also lists **straight edges** in
the multi-return share along the tile grid — level shifts of ≥ 8 km, with the header fields that
change across them. Edges no field explains are candidates for unlabelled campaign boundaries (or
straight landscape edges: military areas, valley floors); check them with a point sample on both
sides (`sample_points.py --tiles a,b,...`) and on the maps before splitting a group. In Bavaria the
scan found the LAS 1.2/1.4 seams and the software string turned out to be a label only (ratio 0.98). Decide the grouping, ideally ≤ 3 groups
of ≥ 10 % of the tiles each (each group needs its own reference maps). If the evidence is
ambiguous, show the user the maps and the table and ask. Then write the groups:

```sh
python scripts/batch_effects.py --config c.yaml --group-by las_version   # or e.g. las_version,point_format; or none
```

Also flag tiles that are outliers within their group (very few multiple returns in forest, like
north of Würzburg: 0.9 M vs. 20 M third-or-later returns per km²) — no set will fix those, but the
user should know.

## 2. Reference maps

```sh
python scripts/omaps.py scrape --config c.yaml
python scripts/omaps.py candidates --config c.yaml   # -> results/omaps_candidates.csv
python scripts/omaps.py preview --config c.yaml ID ...   # look at them
```

Pick per group 4–8 forest maps (digital > scan > photo), map date within ~2 years of the flight
(the page date is an upper bound), covering ≥ 2 tiles at ≥ 60 %, spread over the group's
landscapes; split **by whole map** into train (~2/3) and holdout. Reject: ski-O/MTBO maps for
vegetation (`skip: [green]` — still fine for open land), faded photos, heavy course overprint,
sheets with legends inside the map (or mask with `keep_rows`), maps far from the LiDAR date.
omaps.worldofo.com sits behind a Cloudflare challenge — do not try to bypass it.

Write `sites_input.yaml` (format in `scripts/sites.py`), then:

```sh
python scripts/sites.py --config c.yaml
python scripts/refs.py fetch --config c.yaml && python scripts/refs.py osm --config c.yaml
python scripts/refs.py classify --config c.yaml     # LOOK at work/ref/<site>.png for every site
python scripts/refs.py register --config c.yaml     # runs kp once per site (downloads the tiles)
```

Check each classification PNG against the map preview: the greens must come out as greens (photos
can shift them to yellow or white), overprint/legends masked. Drop sites whose classification is
wrong rather than letting them steer the search.

## 3. Baseline

Score the Bavarian production sets (the prior) next to kp's default:

```sh
python scripts/sets.py import-bavaria --config c.yaml
python scripts/sets.py evaluate --config c.yaml kp_default bayern-las14 bayern-las12
python scripts/viz.py SITE --config c.yaml --sets kp_default,bayern-las14
```

If the Bavarian sets already beat the default clearly on the holdout maps, say so — a full search
may still help, but the user may prefer to stop here.

## 4. Search per group

```sh
nohup python scripts/optimize.py green --config c.yaml --group G --trials 160 > work/logs/green-G.log 2>&1 &
python scripts/sets.py choose --config c.yaml --group G && python scripts/sets.py export --config c.yaml G-balanced work/green-G.json
nohup python scripts/optimize.py yellow --config c.yaml --group G --trials 60 --fixed work/green-G.json > ... &
python scripts/sets.py choose --config c.yaml --group G
python scripts/sets.py evaluate --config c.yaml
```

The green study maximises green balanced accuracy, green-level kappa (quadratic-weighted) and
readability; trial 0 is kp's default, then the Bavarian optima, then TPE. Runs resume after
interruption. Watch the constrained best (`sets.py choose` prints it); expect gains to flatten after
100–150 trials. `choose` picks `G-balanced` (the default recommendation), `-clean`, `-lessgreen`,
`-detail` from the Pareto front, constrained to a geometric-mean green amount within ±25 % of the
maps. Judge on the **holdout** maps, look at `viz.py` sheets, and tell the user where maps disagree
with each other (mapping style varies by region and mapper; one map drawing 3× the green of
another is common).

## 5. Seam matching (optional)

When one group (R) has clearly better references, or seams stay visible with each group's own
set, match the other group (G) to R across their border:

```sh
python scripts/seams.py select  --config c.yaml --ref R --other G
python scripts/seams.py prepare --config c.yaml --other G --targets R-balanced,R-clean
python scripts/seams.py forest  --config c.yaml --other G
nohup python scripts/seams.py search --config c.yaml --other G --targets R-balanced,R-clean --trials 50 > ... &
python scripts/seams.py choose  --config c.yaml --other G --targets R-balanced,R-clean
python scripts/sets.py evaluate --config c.yaml G-match-R-balanced     # the price on G's maps
```

Report both sides: the seam mismatch on held-out blocks and what the matched set costs in
agreement with G's own maps (Bavaria: −20…−48 % mismatch, kappa 0.42 → 0.39).

## 6. Visual check

Agree with the user on 1–2 areas (one with a group border, ~100–600 km²), add them to the
config (`areas`, `render_sets`, `presets`), then:

```sh
nohup python scripts/render_area.py run AREA --config c.yaml > work/logs/render.log 2>&1 &
python scripts/render_area.py check AREA TILE --set G-balanced --config c.yaml   # = production?
python scripts/render_area.py tile AREA --config c.yaml
python scripts/compare.py build --config c.yaml && python work/compare/serve.py   # http://localhost:8765/
python scripts/compare.py shot --config c.yaml "http://127.0.0.1:8765/#14/LAT/LON" out.png '{"A": {...}, "B": {...}}'
```

Look at the screenshots yourself before handing over (empty map below z12 is expected — the tiles
start at z12; flat tile-sized fills would mean a broken crop). The user makes the final choice.

## 7. Deliver

- `python scripts/sets.py inis --config c.yaml SET ...` → `results/params/` (each file is checked to
  parse back to the set); `sets.py samplesheet --map G=set,...` → the index with `group` and
  `pullauta_ini` columns.
- A report (HTML; make available locally, additionally publish as an artifact if available) with: the batch-effect findings, the
  reference maps (and which were dropped, why), metric tables kp default vs. sets on train and
  holdout, `viz.py` sheets, the seam result, viewer screenshots, caveats, and how to rerun.
- Commit scripts' outputs that are small (configs, `sites*.yaml`, results tables, inis) on a branch;
  never commit `work/` or crops of third-party maps; don't push unless asked.

## Running it well

- Everything long runs under `nohup` with a log; watch the logs for `Traceback`/`FAILED` and
  progress lines, and give the user time estimates. Scripts skip what is done, so rerunning after a
  crash is the recovery.
- Kill by PID (`common.kill_by_pattern`), never `pkill -f` — it matches its own shell.
- Disk: point clouds are ~5× the LAZ. Delete `work/cache/strip` after seam matching, the R-side
  clouds after `seams.py prepare`, LAZ after `prepare`; `render_area.py` deletes LAZ as it goes and
  pauses downloads below `min_free_gb`. Ask before deleting anything the user might want.
- Pitfalls that cost hours in Bavaria are listed in `reference/method.md` § Pitfalls — read them
  before changing a script.
