# Tuning karttapullautin for Bavaria

This directory holds a study of karttapullautin's (kp) parameters for the Bavarian LiDAR data. It
covers undergrowth, vegetation (white forest vs. green, and the three ISOM green levels),
yellow vs. white, cliffs and dot knolls. It scores the **vector output** of
[grst/karttapullautin#3](https://github.com/grst/karttapullautin/pull/3) (`c2a060f`), the version
mapant-nf#2 uses, against real orienteering maps from [omaps.me](https://omaps.me).

Results, recommended parameter sets and visual comparisons are in the report (see "Results" below).
This file documents the method and how to re-run it.

## Layout

| path | what |
| --- | --- |
| `sites.yaml` | study sites: reference map, core tiles (scored), halo tiles (only lend points), train/holdout split |
| `scripts/laz_header_survey.py` | LAS header of all 71,979 tiles via HTTP range requests → `results/density.parquet` |
| `scripts/density_map.py` | statewide pulse-density and point-generation maps |
| `scripts/omaps_scrape.py` | georeferenced omaps.me maps around Bavaria → `results/omaps_maps.json` |
| `scripts/make_sites.py` | picks the tiles each reference map covers best |
| `scripts/ref_fetch.py` | reference tiles → GeoTIFF on the EPSG:25832 1 m grid |
| `scripts/osm_fetch.py` | OSM ways/areas per site from Overpass (masks) |
| `scripts/ref_classify.py` | reference image → vegetation classes, undergrowth, cliffs, knolls, mask |
| `scripts/register.py` | per-reference georeferencing offset |
| `scripts/kp.py` | kp harness: cached point clouds, per-stage runs, content-addressed result cache |
| `scripts/score.py` | kp GeoJSON vs. reference, at perception scale |
| `scripts/optimize.py` | multi-objective optuna studies, one per feature group |
| `scripts/thin_laz.py` | pulse-thinned copies of sites (density experiment) |
| `scripts/evaluate.py` | named parameter sets on all sites and variants → `results/eval.csv` |
| `scripts/e2e.py`, `scripts/shot.mjs` | production path: kp batch → tippecanoe (mapant-nf `make_vector_tiles.py`) → viewer style → screenshot |
| `scripts/viz.py` | side-by-side panels |
| `scripts/choose_sets.py` | picks points from the Pareto fronts → `work/sets.json`, `results/choices.json`, `results/fronts/` |
| `scripts/write_inis.py` | sets → full ini files in `params/` |
| `border.yaml`, `scripts/border.py` | blocks on the LAS 1.2 / LAS 1.4 border; the step in green share across it → `results/border.csv` |
| `scripts/gallery.py` | a comparison sheet for every scored tile → `report/img/gallery/` |
| `scripts/report.py` | the report: `offline` → `report/index.html` + `report/gallery.html`; `artifact` → one self-contained page |
| `scripts/samplesheet_ini.py` | adds `las_version` and `pullauta_ini` to `../input/laz_tiles.csv` |
| `scripts/prune_runs.py` | deletes cached stage runs of search trials (disk) |
| `params/` | the recommended ini files |

Bulk data (laz, point-cloud caches, run outputs, reference tiles) lives in `work/`, which is not
tracked. Neither is `report/`, the offline report: it shows crops of third-party orienteering maps.

## Method

### Data and references

* **Density survey.** The header of every tile is read with an HTTP range request. Point
  density alone mixes pulse density with vegetation (more returns in forest). The first-return
  count is a pulse count, so the study stratifies by **first returns per m²**. There are two
  point-record generations: LAS 1.2/format 1 (older campaigns, ~1.4 returns per pulse) and
  LAS 1.4/format 6 (~1.6 returns per pulse).
* **References.** omaps.me exposes georeferenced XYZ tiles for many maps. Forest maps at
  1:7 500–1:15 000 were kept if they are clean enough to classify by colour and within about
  ±2 years of the LiDAR flight. Photos of printed maps with strong colour casts were dropped.
  Maps are split into training and holdout **by whole map**.
* **Classification of the reference.** The steps are:
  1. White balance per map.
  2. Assign each pixel the nearest ISOM ink in CIELAB.
  3. Fill line work (contours, paths, north lines) with the area symbol underneath.
  4. Detect undergrowth from vertical stripe texture.
  5. Take knolls as compact brown dots and cliffs as elongated black features of 9 m or more,
     after removing OSM ways and straight lines (rides, fences).

  Course overprint, water, settlements, OSM farmland/meadows (drawn from OSM in production) and
  OSM way corridors are masked out.
* **Registration.** For each site, the shift within ±40 m that best aligns open land and green
  between the reference and kp's default output, each image masked by its own coverage. Shifts
  came out at 0–11 m. A shift that runs to the edge of the window or lowers green agreement is
  rejected (Tyrolsberg, Hechenberg: most of their open land is masked). Round 1 masked both images
  with the reference's mask, which pinned every shift to zero; round 2 re-scored everything.
* **Generation border.** 21 blocks of 2 × 2 km, each two tiles of one generation next to two of
  the other, both sides mostly forest by the share of multiple returns (plus the block north of
  Würzburg). Every tile is rendered with its generation's set, and the step in green share (green
  over non-open area) from the LAS 1.2 to the LAS 1.4 side is averaged over the blocks. This is
  measured only; it was not an objective.

### Running kp fast

Every core tile is batch-rendered once, with its neighbours as halo, as mapant-nf's
`run_pullauta.py` does. The buffered point cloud (`xyztemp.xyz.bin`) is cached. Every
experiment then runs a single stage (`vegeonly`, `cliffsonly` or `contoursonly`) from that cache
in a few seconds, with results cached by a hash of the parameters that stage reads.

### Metrics (perception scale)

The metrics are computed on 10 m cells for vegetation, 20 m cells for undergrowth and 25 m cells
for rock, i.e. roughly the detail a runner reads at 1:10 000:

* **green vs. white**: balanced accuracy over reference forest; green area bias.
* **green levels**: quadratic-weighted kappa over {white, 406, 408, 410}.
* **readability**: `-|log(boundary length kp / reference)|` (speckle and ragged edges cost),
  plus patches under 100 m² per km².
* **yellow vs. white**: F1 and balanced accuracy of open land.
* **undergrowth**: F1 and balanced accuracy.
* **cliffs**: cells with kp cliffs vs. cells with reference cliffs, with one cell of slack
  (precision and recall).
* **dot knolls**: matched within 15 m (Hungarian assignment); precision and recall.

### Search

The feature groups read disjoint parameters, so there is one optuna study per group
(multivariate TPE, kp's default as trial 0) on the training sites:

| study | parameters | objectives |
| --- | --- | --- |
| green | zones, thresholds, greenground/high, topweight, pointvolumefactor, return weights, greendetectsize, groundboxsize, median filters, 3 greenshades → 406/408/410, vegesimplify | green balanced accuracy, green kappa, readability |
| yellow | yellowheight, yellowthresold, yellowfirstlast, yellowmedianboxsize | open F1, open balanced accuracy |
| ug | undergrowth, undergrowth2 | undergrowth F1, balanced accuracy |
| cliffs | cliff1/2, cliffthin, cliffsteepfactor, cliffflatplace, cliffnosmallciffs | precision, recall |
| knolls | knolls, smoothing, curviness | precision, recall |

Several points of each Pareto front are then evaluated on the holdout maps and on
pulse-thinned copies of three training sites (50 % and 25 % of the pulses). The thinned copies
test whether the optimum depends on density.

## Re-running

```sh
uv sync
.venv/bin/python scripts/laz_header_survey.py
.venv/bin/python scripts/omaps_scrape.py
.venv/bin/python scripts/make_sites.py          # after editing SITES
# download core+halo laz of sites.yaml into work/laz/, build work/kp/pullauta (see scripts/kp.py)
.venv/bin/python scripts/ref_fetch.py <omaps ids>
.venv/bin/python scripts/osm_fetch.py
.venv/bin/python scripts/ref_classify.py
.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import kp; [kp.prepare(s) for s in kp.sites()]"
.venv/bin/python scripts/register.py
scripts/run_night.sh                             # round 1 studies
scripts/run_round2.sh; scripts/run_round2_studies.sh   # round 2: new sites, border blocks, studies
.venv/bin/python scripts/choose_sets.py && .venv/bin/python scripts/evaluate.py work/sets.json
.venv/bin/python scripts/border.py eval kp_default gen:las12-balanced,las14-balanced
.venv/bin/python scripts/write_inis.py las14-balanced las12-balanced ...   # then rename to params/pullauta.bayern-las1x.ini
.venv/bin/python scripts/gallery.py && .venv/bin/python scripts/report.py offline
.venv/bin/python scripts/samplesheet_ini.py
```

## Results (round 2, 2026-09-29)

The report is `report/index.html` (offline, with `report/gallery.html`: every scored tile of every
site) and a private claude.ai artifact; both are rebuilt by `scripts/report.py`.

* **Recommended:** `params/pullauta.bayern-las14.ini` for tiles delivered as LAS 1.4 / format 6
  (processed 2023 and later), and `params/pullauta.bayern-las12.ini` for LAS 1.2 / format 1 tiles
  (processed 2015–2022). `../input/laz_tiles.csv` carries the matching `pullauta_ini` per tile.
* **Alternatives** from the same Pareto fronts: `las14-clean`, `las12-lessgreen` (best on the two
  LAS 1.2 holdout maps, weaker on training), `las12-clean`, `las12-detail` (greenest; pairs best with
  the LAS 1.4 set at the border).
* **16 reference maps** (9 in round 1), incl. an Alpine ski-O map used for open land only.
  omaps.worldofo.com only answers with a Cloudflare bot challenge and could not be used.
* **LAS 1.4 holdout** (Stubenthal, Schneckenberg, Tyrolsberg): green-level kappa 0.34 (default) →
  0.43 (round 1) → 0.47. **LAS 1.2 holdout** (Schaufling, Hechenberg): 0.41 → 0.45 → 0.46.
* **Border:** the LAS 1.4 side is +19 ± 5 percentage points greener with kp's defaults, +11 ± 6 with
  the recommended pair (+4 with round 1's, +3 with `las12-detail`).
* **Open land** keeps round 1's settings (round 2 found nothing better in F1). **Cliffs** from the
  pooled round-2 search. **Pulse density** (down to 25 % of the pulses) does not change the optimum.
* **Undergrowth and knoll** parameters stay at kp's defaults. See the report for why.
* Per-site metrics: `results/eval.csv`, border: `results/border.csv`, trials: `results/fronts/`,
  choices: `results/choices.json`.
