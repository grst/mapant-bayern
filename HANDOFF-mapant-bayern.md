# Hand-off: OCAD export in the mapant-bayern webapp

> **Superseded.** This describes the first, bitmap-based prototype. The current plan builds on
> @malpou's karttapullautin fork -- see `HANDOFF-malpou-stack.md` next to the repositories.

This describes the "download this area as an editable OCAD file" feature, as prototyped on the
branch **`feature/ocd-export`** in this working copy and validated against real vector tiles from
`mapant-nf -profile test_immenstadt`.

It depends on a vector pyramid existing, which depends on karttapullautin gaining `output_geojson`.
See `HANDOFF-mapant-nf.md` and `HANDOFF-karttapullautin.md`.

**Two things changed in the pipeline after this was written, neither of which touches the export.**
The pipeline no longer builds a raster pyramid at all, and the OSM shapes are now matched to their
ISOM codes by the pipeline rather than by karttapullautin. The tiles are unchanged -- same layers,
same `isom` and `k` properties, same zoom plan -- so `src/ocd/` and its fixtures are unaffected, and
the feature-by-feature comparison behind that claim is in `HANDOFF-mapant-nf.md` §4. What *is*
affected is the webapp's existing **raster** basemap: nothing produces `tiles/` any more, so a
deployment that shows the rendered map alongside the vector one needs either a kept copy of the old
pyramid or a decision to drop it. That is a mapant-bayern deployment question, not an export one.

---

## 1. What it does

Next to "Export as PDF" in the print panel there is a second button. Same rectangle, same scale and
orientation choice; it saves `mapant-bayern_1-<scale>.ocd`, georeferenced in the LiDAR's own
projected system, built on the ISOM 2017-2 symbol set.

The whole conversion happens in the browser. **No backend and no WebAssembly**: an A4 page is a few
dozen vector tiles and a few megabytes of `DataView` writes. Measured on this hardware:

| page | objects | time | file |
| --- | --- | --- | --- |
| A4 at 1:4000 | 64,995 | 1.9 s | 9.7 MB |
| A4 at 1:10000 | 216,684 | 5.3 s | 33 MB |

About two thirds of either is cliff hatching, which karttapullautin draws as individual ticks. WASM
would add a toolchain and a payload to solve a problem that is not there.

## 2. Files

**New** — `src/ocd/`, 1,262 lines in eight modules:

| file | what |
| --- | --- |
| `index.ts` | `exportOcd(request)`: the whole pipeline — cover the print rectangle with tiles, clip, stitch, symbolise, write |
| `source.ts` | `xyzSource` (a `{z}/{x}/{y}.pbf` directory) and `pmtilesSource` (an archive over range requests) |
| `tiles.ts` | which tiles cover the extent, and decoding one into features |
| `geometry.ts` | Liang–Barsky line clipping, Sutherland–Hodgman ring clipping, and `stitch` |
| `isom.ts` | karttapullautin's classes and ISOM 2000 codes → ISOM 2017-2 symbols |
| `ocdwriter.ts` | the OCD 12 binary writer |
| `proj.ts` | web mercator → the projected CRS, and OCAD's code for it |
| `config.ts` | the tile URL, zoom range, CRS and template path, all `VITE_`-prefixed build settings |

Plus `tests/ocd.spec.ts` (3 tests), `tests/fixtures/vtiles/` (nine real z16 tiles, 3.3 MB, with a
README explaining why they are real), and `public/templates/isom2017-2_10000.ocd`.

**Changed**: `src/main.ts` (wires the button to `exportOcd` and saves the blob),
`src/ui/printpanel.ts` (the button), `src/i18n/{en,de}.ts`, `README.md`, `package.json`.

**Dependencies added**: `@mapbox/vector-tile`, `pbf`, `proj4`, `@types/proj4` — all MIT, all small.
Dev only: `ocad2geojson` (**AGPL**, used in the test to read back what the writer produced; it must
never be bundled).

## 3. How the OCD file is built, and why that way

**From a template.** An OCD object can only reference a symbol defined in the same file, and a
symbol definition is a large binary record with its own colour table. Writing 170 ISOM symbols from
scratch would be the bulk of the work and would drift from the standard. Instead the app fetches
`public/templates/isom2017-2_10000.ocd` (192 KB: OCD version 12, 170 symbols, 36 colours, **zero
objects**) and copies its bytes verbatim — so every offset in it stays valid — then:

* walks the string index chain to the **type-1039** entry and repoints it at a replacement appended
  at the end (`m` scale, `g` paper grid, `r1`, `x`/`y` the map origin in whole metres, `a` the angle
  to grid north, `d` the terrain grid, `i` the coded coordinate system, e.g. `i63005` for ETRS89 /
  UTM 32N);
* fills the template's own empty object index block, then appends as many 256-entry blocks as it
  needs, chained from the last one;
* appends the objects themselves.

Facts that cost time and are worth not rediscovering, all pinned by the test:

* An index entry's size field is **bytes, padded to 8** — the published documentation says it counts
  coordinates for version 9 and up, and following that makes OCAD report damaged objects. Mapper's
  own exporter carries the same note.
* A coordinate is a 24-bit value in 0.01 mm paper units **shifted left 8**, with flags in the low
  byte, y up. Negative values are the low 23 bits of the two's complement, not sign-and-magnitude —
  getting that wrong puts objects 8.4 million units off the page, which is how it was found.
* A symbol number is `code * 1000 + sub`: 101.1 is 101001, not 101100.
* A code with no symbol in the template is **dropped with a warning**, never written as a dangling
  reference, which OCAD reports as a damaged file.

**Reading the deepest zoom only.** That is the level that carries the map as karttapullautin
rendered it; every level above it is deliberately generalised for the screen.

**Clipping twice.** A vector tile carries a buffer of its neighbours' geometry, so each feature is
first cut to its own tile square — pieces from adjacent tiles then abut instead of overlapping — and
then to the print rectangle. Lines that met at a tile border are stitched back into one line with a
0.25 m tolerance.

**A tile that is not a tile costs its own square.** A host that answers a missing tile with its index
page instead of a 404 used to end the export in the protobuf parser; unreadable tiles are now
counted and reported.

## 4. What production still has to do

1. **Point at the production pyramid.** `config.ts` defaults to `/vtiles/{z}/{x}/{y}.pbf`, which is
   what a local copy of `tiles_vector/` gives you. Production should use `pmtilesSource` against an
   archive next to `MAPANT_PMTILES` in `src/layers.ts` — `source.ts` already has it, and the archive
   itself is a mapant-nf item (`bin/pack_pmtiles.py`, not written yet). Set `VITE_MAPANT_VECTOR_*`
   accordingly, including the real zoom range.
2. **Decide the template's licence.** The one committed here was exported from OpenOrienteering
   Mapper's ISOM 2017-2 symbol set, which is **GPLv3**; this app is MIT. Shipping it inside the app
   needs a decision, or a symbol set of different provenance (one made in OCAD, say). It is a
   drop-in replacement: fetched at runtime, and nothing but the symbol numbers is assumed. **Do this
   before release, not after.**
3. **Handle more than one CRS.** `proj.ts` knows EPSG:25832 and 25833 and their OCAD grid codes
   (63005, 63006); `MAP_CRS` is a single build setting. Bavaria is one zone, so this is fine today
   and wrong the moment a region spans two. The pyramid's `metadata.json` should carry the CRS and
   the app should read it rather than be told.
4. **Decide about magnetic declination.** The export writes `a0.00000000`: north on the page is grid
   north. An orienteering map is drawn with magnetic north up, so either the export should rotate
   and set the declination, or the UI should say plainly that it does not and leave it to the
   mapper's first act in OCAD. This is a mapping decision, not a technical one.
5. **Think about the 1:10 000 file.** 217k objects opens slowly in Mapper and OCAD. Nothing is wrong
   with it, but the UI could say what is coming, or offer to leave the cliff hatching out — it is
   two thirds of the objects and the one layer a surveyor will redraw anyway. Worth asking a mapper
   before building either.
6. **Consider a worker.** Five seconds on the main thread is a frozen tab. A `Worker` around
   `exportOcd` would need the tile fetching and the writer moved across, both of which are already
   pure functions over `ArrayBuffer`s.

## 5. How to verify

```sh
npx tsc --noEmit
npx playwright test          # 23, of which 3 are the OCD export
```

`tests/ocd.spec.ts` exports a page from the nine committed tiles and reads the result back with
`ocad2geojson` — a different implementation of the format — asserting the version, that every object
references a symbol the template defines, that the georeferencing string names the right UTM zone,
and that every object falls inside the page. It also covers an area with no tiles under it, and a
host that serves rubbish for a tile.

To look at a real file: copy a `tiles_vector/` tree into `public/vtiles/` (gitignored), `npm run
build`, `npm run preview`, and export from the print panel. Open the result in Mapper or OCAD and
check the georeferencing dialog says ETRS89 / UTM 32N and that the map lands on an OSM background
template.

## 6. Gaps that affect this repo

* **Two mappings are judgement, not translation**, and are marked as such in `isom.ts`: which green
  shade counts as slow running, walk or fight, and what undergrowth means. A mapper should be asked.
* **Areas are not merged across tiles.** Polygons clipped at a tile border are written as separate
  abutting areas; the user merges them in Mapper. Doing it properly means a polygon union in the
  browser.
* **Cliff hatching is exported as karttapullautin draws it** — individual ticks, not cliff lines.
  The fix is upstream (see `HANDOFF-karttapullautin.md`).
* **No elevation labels**, though contours carry `e` and the symbol exists.

See `HANDOFF-known-gaps.md` next to the repositories for the list that spans all three.
