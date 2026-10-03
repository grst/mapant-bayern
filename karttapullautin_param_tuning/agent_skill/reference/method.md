# Method details

## How kp is run

- `kp.prepare`: one kp batch run per site (core tiles; halo tiles lend points, as in mapant-nf's
  `run_pullauta.py`), keeping each core tile's buffered point cloud `xyztemp.xyz.bin` (tile + 127 m)
  in `<work>/cache/full/`. Format: `XYZB`, u64 count, then 24-byte records (f64 x, f64 y, f32 z,
  u8 class, u8 number of returns, u8 return number, u8 pad).
- `kp.run_stage`: `vegeonly=1` from that cloud with kp's default ini + overrides; results cached by
  a hash of the tile and the parameters the stage reads (`STAGE_KEYS`). A vege run takes 2–9 s.
- Stage outputs are uncropped (they include the 127 m buffer) and in the index CRS. Scoring clips
  each tile to its own square. The viewer path crops and reprojects with `kpcrop.py`, a line-by-line
  port of kp's `crop_geojson` (Liang–Barsky for lines, Sutherland–Hodgman for rings).

## Scoring (`score.py`)

The reference map is classified (CIELAB nearest ink after per-map white balance) into
0 unknown, 1 white, 2 open 401, 3 rough open 403, 4/5/6 green 406/408/410; line inks take the class
of the nearest area pixel. Masked: outside the map, purple overprint (dilated), olive, water, OSM
buildings/settlements/water, OSM farmland/meadow/grass, and corridors of OSM ways.

Both are compared on the reference's 1 m grid in **10 m cells** (majority class; cells ≥ 80 %
unmasked): green balanced accuracy and green bias over reference forest cells, quadratic-weighted
kappa over {white, 406, 408, 410}, open-land F1/BA/bias. Readability = −|log(kp / reference
green-white boundary length)| on the 1 m rasters. Means over sites; the green amount constraint
uses the **geometric** mean of per-site bias (one map drawing little green would dominate an
arithmetic mean).

Registration: shift within ±40 m maximising the cross-correlation of an open/forest signal,
reference and kp each masked by their own coverage (a shared mask pins the peak at zero). A shift
is rejected if it reaches 60 % of the window or lowers green BA by > 0.005.

## Searches

- Green: 23 parameters (zones, thresholds, greenground/high, topweight, point volume, first/last
  return factors and ground handling, detect/box/median sizes, 3 greenshades, vegesimplify),
  bounds in `optimize.space_green`. Objectives green_ba, green_kappa, readability. Optuna TPE
  (multivariate, 20 startup trials), trial 0 = kp default, then the Bavarian seeds.
  `greenshadeisom` is fixed to `406|408|410`; a 7-shade variant (`subshades` in the Bavarian code)
  scored about the same and renders 406 darker in production's style, so it is optional.
- Yellow: yellowheight, yellowthresold, yellowfirstlast, yellowmedianboxsize; objectives open_f1,
  open_ba; pick F1-max (the BA-best trials draw ~1.4× the maps' open land).
- Seam matching: see `scripts/seams.py` docstring. One study per target set; each render is scored
  for all targets and added to the other studies (`add_trial`), with distinct sampler seeds per
  study (identical seeds made the studies propose identical trials).

## Pitfalls (each cost hours in Bavaria)

1. **IO.** Unpatched kp copies the point cloud into every stage run's temp folder: on ext4 the
   search stalled at ~45 % IO pressure. Use `patches/kp-hardlink.patch` (output byte-identical). No
   tmpfs in the container (`/dev/shm` 63 MB); kp's in-memory mode cannot read `.xyz.bin`.
2. **Reading point clouds per trial.** 70 tile clouds per trial (≈ 70 GB) do not fit the page
   cache; the seam search crops each block's clouds to a 300 m strip (`seams.strip_cloud`).
3. **GEOS clipping of kp polygons.** kp's simplification leaves invalid polygons; `clip_by_rect`
   is undefined for them and produced tile-sized fills in ~200 tiles. Use `kpcrop` (kp's own
   algorithm). Zero-area slivers on the tile edge are dropped (production has none). Residual
   difference to production: ≤ 0.5 % of vertices, identical features.
4. **Degenerate rings** (3 positions) crash shapely; `kpcrop` does not use shapely.
5. **Silent worker failures.** Exceptions in a thread pool surface only when results are
   collected — at the end. `render_area.py` reports each failed tile at once and a rerun picks it
   up; tiles resume from their kept cloud.
6. **Download look-ahead deadlock.** A look-ahead limit must count skipped/failed tiles as done.
7. **tippecanoe exit 110** = no feature in that z12 parent (only a buffer edge); remove the empty
   output or `tile-join` segfaults. Compute parents per tile, not from a bbox (group areas are
   ragged). tippecanoe is single-threaded: parallelise over (archive, parent).
8. **Viewer shows nothing** below z12: the pyramid starts at z12 as in production. Open areas at a
   start view; a `#zoom/lat/lon` link must select the area it points into.
9. **`pkill -f pattern`** kills the shell running it. Kill by PID.
10. **zsh** aborts a whole command when one glob has no match (`rm -f a/*.x b/*.x`); use `find -delete`.
11. **Overpass** answers 504/429 under load: retry with backoff, alternate endpoints.
12. **omaps.me dates** are event/upload dates (upper bound of the survey); photos of printed maps
    shift colours (greens read as yellow/white) — check every classification PNG.
13. **Mapping style differs between maps** of the same area type (one map 3× the green of
    another). Train/holdout by whole map; report per-site numbers, not only means.
14. **Header `creation_year`** is the processing date, not the flight; GPS time (adjusted standard
    time, LAS global-encoding bit 0) gives the flight date, and season matters for vegetation.
15. **The machine is shared.** Long renders: 6 workers × 4 threads used 16 cores well; the Alpine
    tiles' single-threaded steps left cores idle — a second pass from the other end of the queue
    helped, but must stop short of tiles the first pass has started.
