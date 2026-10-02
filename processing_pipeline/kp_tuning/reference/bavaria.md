# What Bavaria found (prior for other regions)

Source: `processing_pipeline/optimize_params/` (README, report), karttapullautin #3 (c2a060f),
vector output, 2026-09/10. 71,979 tiles of 1 km², EPSG:25832.

## Batch effect

| group | tiles | delivery | flights | returns/pulse | kp default vs. maps |
|---|---|---|---|---|---|
| LAS 1.2 / point format 1 | 40,401 | processed 2015–2022 | mostly leaf-off | 1.38 | too white |
| LAS 1.4 / point format 6 | 31,578 | processed 2023– | leaf-off | 1.64 | too green, speckled |

With kp's defaults the LAS 1.4 side of a generation border was ~13 points greener (52 blocks).
Inside the LAS 1.2 generation, tiles with few multiple returns in forest (north of Würzburg: 0.9 M
third-or-later returns per km² vs. 20 M on the LAS 1.4 side; canopy multi-return share 0.40 vs.
0.72–0.77) stay nearly white with any parameter set. Intensity scaling differs between the
generations (16-bit vs. ~10-bit) — a cheap batch indicator.

Point density (25 %, 50 % thinning) did not change the optimum: one set per generation, not per
density class.

## References

16 omaps.me maps (12 train, 4+ holdout; digital maps, scans, photos), 42 core tiles. Two maps
were dropped (pale photo; a ski-O map is open-land-only). Maps of the same region disagreed
strongly in green amount (per-site green bias of one set 0.9–2.6×).

## Results (holdout maps, green-level kappa)

| | kp default | tuned (round 2) |
|---|---|---|
| LAS 1.4 | 0.34 | 0.47 (Stubenthal 0.31 → 0.53, Schneckenberg 0.35 → 0.63; Tyrolsberg 0.36 → 0.24) |
| LAS 1.2 | 0.41 | 0.46 |

Open land F1 0.62 → 0.64 (LAS 1.4), 0.56 → 0.60 (LAS 1.2) with round 1's yellow keys
(`yellowheight 0.24, yellowthresold 0.891, yellowfirstlast 3, yellowmedianboxsize 13`), which no
later search beat.

Round 3 matched LAS 1.2 to LAS 1.4 across the border: forest mismatch on held-out blocks −20…−48 %,
mostly patchiness (LAS 1.4 had ~1.35× the class edges); price on the LAS 1.2 maps kappa 0.42 → 0.39.

## Production choice

`las14-balanced` for LAS 1.4 tiles, `las12-match-balanced` for LAS 1.2 tiles, both without cliff
keys (cliffs, knolls, contours, undergrowth at kp defaults) — chosen visually in the comparison
viewer. The overrides are in `bavaria_seeds.json` → `production`, the Optuna parameters of all
Bavarian picks in `green_params`/`yellow_params` (enqueued as seeds by `optimize.py`).

Typical character of the tuned sets vs. default: fewer, larger, smoother green patches
(medianboxsize 15–23, greendetectsize 2, vegesimplify 0.9–1.3 for LAS 1.4), green thresholds lower
for LAS 1.2 than for LAS 1.4.

## Effort

Header survey 72k tiles: ~40 min. Site preparation ~1 min per tile. Green search 160 trials on
16 tiles: ~5 h. Seam search (52 blocks, 3 targets × 50 trials): ~3 h. Area renders: ~1.5–2.5 min
per tile with 12 sets (621 km² ≈ 5 h at 6 workers), tiling ~1.5 h, ~25 MB vector tiles per km²
for 17 sets.
