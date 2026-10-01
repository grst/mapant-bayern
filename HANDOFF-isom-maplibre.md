# Handoff: mapant-nf tiles for isom-maplibre

**Status (2026-09-28):** the mapant-bayern webapp now draws the orienteering map with MapLibre and the
[isom-maplibre](https://github.com/MetsaApp/isom-maplibre) style (`@metsa/isom-maplibre` 0.1.0), reading
the Allgäu pyramid on R2 as it is. The pyramid does not match the schema the style expects. The webapp
bridges the gap at load time in two modules, `webapp/src/isomstyle.ts` and `webapp/src/tilemerge.ts`.
This note lists what mapant-nf would have to change for the tiles to work with the style directly, so
that both modules can go.

Everything below is about `bin/make_vector_tiles.py` (the tile schema and the zoom plan) and the files
published next to the pyramid. karttapullautin itself needs one change (cliffs, §4). None of it may
assume Bavaria: codes come from the run's own ini and vectorconf, and the geography comes from the run.

## 1. What the style expects

isom-maplibre's `style.json` reads **one vector source per table**, each a TileJSON at `/tiles/<table>`.
The layer inside each source has the same name as the table:

| Table              | Geometry        | `isom_code` (string)                                                   |
|--------------------|-----------------|------------------------------------------------------------------------|
| `contours`         | lines           | 101.000, 101.001 (slope line), 102.000, 103.000, 104.000, 105.000      |
| `cliffs`           | lines, polygons | 201.000, 202.000, 206.000                                              |
| `knolls_points`    | points          | 109.000, 111.000                                                       |
| `vegetation_areas` | polygons, lines | 401.000–410.000, 412.000, 413.000, 415.000                             |
| `water`            | lines, polygons | 301.000, 302.000, 304.000, 305.000, 306.000, 308.000                   |
| `paths`            | lines           | 502.000–507.000                                                        |
| `manmade`          | lines, polygons | 501.000, 509.000, 510.000, 511.000, 515.000, 516.000, 520.000, 521.000, 521.001, 529.000 |

There are also two optional sources:
- `coverage`: polygons of where there is data.
- `overview`: a lighter single source for below zoom 13.

The style is sized for MapLibre's 512 px zoom: dimensions are constant up to z15, then double per zoom.

## 2. What the pyramid has today

There is one source. Its layers are karttapullautin's outputs: `yellow`, `vegetation`, `undergrowth`,
`osm_areas`, `contours`, `formlines`, `dotknolls`, `cliffs` and `osm_lines`. Every feature carries two
properties:
- `layer`: karttapullautin's class.
- `isom`: the symbol number. For the terrain it is ISOM 2017-2 (`403`, `406`, …). For the OpenStreetMap
  shapes it is **ISOM 2000**, because that is what the vectorconf (`assets/osm.txt`) numbers them in:
  `503`, `526`, `301.1`, … plus a `T` suffix for bridges and tunnels.

The zoom plan (`ZoomPlan`, `LAYERS`, `OSM_LEVELS`) generalises each level for **256 px** tiles. The
deepest level, z16, is the only one with form lines, knolls and fences.

## 3. Changes to the tile schema (`make_vector_tiles.py`)

1. **Name the layers after the tables.** tippecanoe's `--named-layer` can put several input files into
   one layer. The mapping the webapp uses today:

   | Now (layer: `isom`)                                           | Table                           |
   |---------------------------------------------------------------|---------------------------------|
   | `contours`: 101, 102; `formlines`: 103                        | `contours`                      |
   | `cliffs`: 201, 202                                            | `cliffs`                        |
   | `dotknolls`: 109, 111                                         | `knolls_points`                 |
   | `yellow`, `vegetation`, `undergrowth`: 403–410                | `vegetation_areas`              |
   | `osm_areas` / `osm_lines`: 401, 401.1, 414                    | `vegetation_areas`              |
   | `osm_areas` / `osm_lines`: 301, 301.1, 306, 310               | `water`                         |
   | `osm_lines`: 503, 504, 505, 507                               | `paths`                         |
   | `osm_areas` / `osm_lines`: 515, 516, 526, 527, 529            | `manmade`                       |

   The OSM layers have to be split by code. That is a job for a small preprocessing step, or a
   `--feature-filter` per named layer: the same input file is given twice, once per table, each with a
   filter on `isom`.
2. **Write `isom_code` in ISOM 2017-2, formatted `NNN.NNN`.**
   - The terrain codes only need the formatting (`403` → `403.000`).
   - The OSM codes need a translation from ISOM 2000. The webapp uses OpenOrienteering Mapper's
     crosswalk (`symbol sets/ISOM2000-ISOM 2017-2.crt`), in `webapp/src/ocd/isom.ts` (`OSM_CODES`) plus
     the aliases in `webapp/src/isomstyle.ts` (`STYLE_CODES`):
     - 301 → 301.000 (the area), 301.1 → 301.000 (the bank line)
     - 306 → 305.000, 310 → 308.000, 401 → 401.000
     - 401.1 and 414 → 415.000
     - 503 → 502.000, 504 → 503.000, 505 → 504.000, 507 → 506.000
     - 515 → 509.000, 516 → 510.000
     - 526 → 521.000, 527 → 520.000, 529 → 501.000
     - `T` variants map like their base code.
     - 524 (impassable fence, 518 in 2017-2) and 529.1 (501.2) have no symbol in the style yet.

   The table has to follow the codes a run's vectorconf actually uses. Key it on the vectorconf's codes,
   not on a fixed list, so a region with its own `osm.txt` still maps.
3. **Keep `layer` and `isom`** alongside `isom_code` until the OCAD export (`webapp/src/ocd/isom.ts`) is
   switched over to `isom_code`. It reads them today.
4. **Feature geometry must match the table's conventions:**
   - Slope lines (101.001) are two-point lines drawn from the contour downhill.
   - Small depressions (111) are points. karttapullautin already writes them to `dotknolls`, so there
     is no change here.
   - A line symbol that bounds an area (301 bank, 501 edge) comes as its own line feature. Today it
     arrives as `osm_lines` 301.1 and 529.1. The webapp keeps each layer type to its own geometry: fills
     draw polygons only, lines draw lines only. A line layer applied to a polygon would trace the tile
     clip edges as well.

## 4. Cliffs (karttapullautin)

karttapullautin writes cliffs (201/202) as its **tick hatching**, thousands of short segments. The style
draws 201/202 as a solid cliff line (it notes "plain line without its ornament: 201 tags"), so the ticks
come out as heavy black blobs. It is the most visible difference from the old rendering. This needs one of
two changes:
- karttapullautin exports the cliff **top edge** as the 201/202 line, which the style is built for; or
- the ticks get a code of their own that the style draws as thin ticks.

That needs a change upstream in the style.

## 5. Zoom plan: cut for 512 px tiles

MapLibre refuses vector tiles that aren't 512 px ("vector tile sources must have a tileSize of 512"). If it
reads today's pyramid as it is, every level shows one zoom later than it was generalised for: form lines
and knolls would appear only at about 1:3000 on screen. So `webapp/src/tilemerge.ts` serves each tile
merged from the pyramid's four tiles one level deeper, rewriting the protobuf in the browser's main
thread.

To make that unnecessary, cut the pyramid so level *z* holds what level *z + 1* holds now:
- `--maximum-zoom` one lower (15 for today's 16).
- `--full-detail=13` (an 8192 extent), so the deepest level keeps the precision four 4096 tiles have now.
- The same shift in `ZoomPlan`: `minzoom(levels)` counted from the new maximum.
- `--buffer`, given in 1/256 of a tile, halved to cover the same ground.

A print still wants the deepest level at any scale. Today the webapp gets it by merging a whole block of
the deepest tiles (`mapant-print-tiles` in `layers.ts`). With 512 px tiles the print map would need that
same trick, or a style `minzoom` on the detail layers low enough that the deepest tiles are used. So keep
`tilemerge.ts`'s print path in mind when this changes.

## 6. Files next to the pyramid

- **TileJSON.** `metadata.json` is MBTiles-style (`bounds` as a string, no `tiles`). The webapp builds
  TileJSON from it through a custom protocol. Publish a real TileJSON (`tilejson`, `tiles`, `bounds`,
  `minzoom`, `maxzoom`), per table if the per-table sources are kept (§7).
- **Coverage.** The webapp needs `coverage.geojson` for the white paper under the map. Today it is
  written by `webapp/scripts/vector-coverage.mjs` after the run. Make it a pipeline output: as GeoJSON,
  or as the style's `coverage` vector layer.
- **Style.** The pipeline's own `style.json` (`assets/viewer/style.json`) sizes lines in ground metres
  from the run's ini. isom-maplibre sizes them from the ISOM dimensions instead, so the ini's colours and
  widths no longer reach the webapp. If the ini's appearance should still govern the map (it is meant to,
  for any region), that has to be decided between the two styles: either the pipeline generates its
  style with isom-maplibre's generator (`cmd/genstyle`, `isom.yaml`) from values taken from the ini, or
  the webapp keeps the pipeline's style.

## 7. Per-table sources, or one source

The style's per-table sources suit a tile server that serves each table separately. A static pyramid is
simpler as **one** source holding the seven layers. The only adaptation that leaves in the webapp is
pointing every style layer's `source` at it, which is a few lines rather than today's bridge. Several
static pyramids (one per table) would work too, at the price of seven times the tile requests.

## 8. Rendering order and water

The style stacks symbols in ISOM colour order, so brown contours draw above blue water. karttapullautin
traces contours across lakes (the LiDAR water surface), and on the Alpsee these now show as brown
streaks. The old style hid them under the lake fill. Clip contours, form lines and the green screens
against 301 areas in the pipeline.

## What goes away in the webapp once this is done

- `src/isomstyle.ts`: the code lookup and the per-tile-layer layer copies. What remains is dropping the
  background and overview pass and pointing sources.
- `src/tilemerge.ts`, if §5 is done and print gets its detail another way.
- The `mapant://` TileJSON protocol in `src/layers.ts`, once §6 is done.
- `scripts/vector-coverage.mjs`, once §6 is done.
