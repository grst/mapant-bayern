# Mapant Bayern webapp

The map viewer at [mapant.orienteering-allgaeu.de](https://mapant.orienteering-allgaeu.de): a static
site built with [Vite](https://vite.dev/) and [MapLibre GL JS](https://maplibre.org/), deployed to
GitHub Pages by `.github/workflows/webapp.yml` on every push to `main`.

## Development

```bash
npm install
npm run dev         # dev server with hot reload
npm run typecheck   # tsc --noEmit
npm run build       # -> dist/
npm run preview     # serve dist/ on http://localhost:4173
npm test            # Playwright smoke tests (run `npm run build` first)
```

The first test run needs the browser: `npx playwright install --with-deps chromium`.

## Layout

| Path | What it is |
| --- | --- |
| `index.html`, `about.html` | the two pages; no client-side routing |
| `src/layers.ts` | the map's style (sources and layers) and the copyright notices |
| `src/isomstyle.ts` | the ISOM style of isom-maplibre, bridged onto mapant-nf's tiles |
| `src/tilemerge.ts` | serves the pyramid to MapLibre one level deeper than it would read it |
| `src/map.ts` | map, controls and the switchable layers |
| `src/geo.ts` | web mercator and the sphere maths for measuring |
| `src/urlstate.ts` | the share link: `#map=zoom/lat/lon&layers=…&lang=…&d=…` |
| `src/draw.ts`, `src/drawings.ts` | measure/draw interactions, and the codec that puts them in the URL |
| `src/print.ts` | PDF export: scale maths and the off-screen print map |
| `src/i18n.ts`, `src/i18n/*.ts` | DE/EN strings, applied via `data-i18n` attributes |
| `src/ui/*.ts` | navbar, layer panel, print panel, draw toolbar, share button, zoom hint |
| `public/places.geojson` | town names overlay (generated, committed) |
| `public/fonts/` | glyphs for the town names and measurements (Noto Sans, OFL) |
| `public/CNAME` | custom domain, copied into `dist/` by Vite |

The about page renders the repository's root `README.md` – or `README.de.md` when German is selected –
imported with Vite's `?raw`. The screenshots those files link to are served from `../img` by a small
plugin in `vite.config.ts`.

## PDF export

`src/print.ts` builds a second, off-screen map at paper size and saves it through
[jsPDF](https://github.com/parallax/jsPDF) (loaded on demand – it is larger than the rest of the app).

* A4, portrait or landscape, at 1:4000 / 1:7500 / 1:10 000 / 1:15 000.
* 600 dpi, losslessly compressed. The map is drawn from vector tiles, so the density is limited by
  the canvas, not by the data.
* The print map is laid out at the paper's size in CSS pixels, at the zoom of the requested scale,
  and drawn at `pixelRatio = dpi / 96` – a 4961 × 6850 canvas for an A4 page at 600 dpi. Vector
  tiles are drawn anew at that density rather than magnified, and every size the styles give in CSS
  pixels comes out on paper at its size on screen.
* What the pixel ratio does not change is which tiles MapLibre reads: it picks them from the zoom
  alone, which would give a page the tiles a screen at that scale gets. The print style therefore
  reads the orienteering map from the pyramid's deepest level at any scale (`mapant-print-tiles` in
  `src/layers.ts`), and declares the terrain tiles smaller than they are to get the finest ones.
* Safari caps a canvas at about 16.7 million pixels, well under an A4 page at 600 dpi, and silently
  ignores drawing beyond it; WebGL has a limit of its own on the drawing buffer. The export probes
  both and steps down to 400 or 300 dpi if the browser will not hand out what it needs.
* The scale is exact: the view resolution is derived from the paper size and corrected for the local
  Web Mercator distortion, so a ruler on the print agrees with the stated scale.
* A footer strip carries the scale and the copyright notices of the layers that were printed.

MapLibre reports a map finished (`idle`) only after a frame, and a last request that fails does not
ask for one; the export gives the print map another frame while it waits, or it could wait forever.

## The orienteering map

The map is drawn from the vector pyramid that mapant-nf publishes as `tiles_vector/`
(`--vector_tiles true`), served as static files from an R2 bucket (`MAPANT_TILES_URL` in
`src/layers.ts`), in the ISOM 2017-2 style of [isom-maplibre](https://github.com/MetsaApp/isom-maplibre).

* **The style does not fit the tiles as they are.** isom-maplibre expects one source per table
  (`contours`, `vegetation_areas`, `paths`, …) with an `isom_code` such as `"403.000"`; the pyramid is
  one source whose layers are karttapullautin's outputs, with karttapullautin's `isom` – ISOM 2017-2
  for the terrain, ISOM 2000 for the OpenStreetMap shapes. `src/isomstyle.ts` repeats each of the
  style's layers for every tile layer that can hold its symbol, with a lookup from `isom` to the style's
  code. The translation is the OCAD export's, so the two agree. `HANDOFF-isom-maplibre.md` in the
  repository root lists what mapant-nf would change so this goes away.
* **The pyramid is cut for 256 px tiles; MapLibre only takes 512.** Read as they are, every level would
  show one zoom later than it is generalised for – form lines and knolls only at about 1:3000. So
  `src/tilemerge.ts` answers each tile MapLibre asks for with the pyramid's four tiles one level deeper,
  merged by rewriting the protobuf (tag tables joined, geometry offset into its quadrant). All zooms in
  the code are MapLibre's; the share link keeps the 256 px convention OpenStreetMap uses, one higher.
* Fills draw polygons only and lines draw lines only: MapLibre would otherwise fill an open line, and
  trace the edges the merged children were cut at.
* The style's background is not used, and white paper is drawn only where the pyramid has tiles, from
  a `coverage.geojson` next to them; `node scripts/vector-coverage.mjs <tiles_vector dir>` writes it,
  and it is uploaded with the tiles. The tile bounds come from the pyramid's `metadata.json`.
* The style's pattern and symbol images are rasterised from isom-maplibre's SVGs as MapLibre asks for
  them, at the screen's or the print's pixel ratio.
* The bucket has to send CORS headers for any origin that serves the app other than the bucket
  itself (the GitHub Pages domain, `localhost` during development).

## OCAD export

The same print rectangle can be saved as an editable OCAD file, as a starting point for someone who
is going to survey the area. `src/ocd/` does the whole conversion in the browser; there is no
backend and no WebAssembly, because an A4 page is a few dozen vector tiles and a few megabytes of
`DataView` writes.

* The data comes from the same vector pyramid the map is drawn from (`MAPANT_TILES_URL` in
  `src/layers.ts`), read directly rather than through the tile merging above. `src/ocd/config.ts` holds the template URL and the target coordinate system.
* It always reads the **deepest** zoom, the only level that carries the map as karttapullautin
  rendered it. Every level above it is deliberately generalised for the screen -- form lines and
  knolls left off, the vegetation traced from a coarser grid, the cliff hatching sampled -- which is
  right for an overview and wrong for a map to survey from.
* A tile that answers with something that is not a vector tile costs its own square and no more. A
  host that serves its index page instead of a 404 for a tile the pyramid does not have is the
  usual reason, and it used to end the export in the protobuf parser.
* Tiles carry a buffer of their neighbours' geometry, so every feature is first clipped to its own
  tile square -- the pieces from adjacent tiles then abut instead of overlapping -- and the line
  pieces that met at a border are stitched back into one line (`src/ocd/geometry.ts`).
* karttapullautin's classes are translated to ISOM 2017-2 symbols in `src/ocd/isom.ts`. Where it
  emits ISOM 2000 codes for OpenStreetMap shapes, the translation is OpenOrienteering Mapper's own
  crosswalk table. Two mappings are judgement rather than translation and are marked as such: which
  green shade counts as slow running, walk or fight, and what undergrowth means.
* The file is written by appending to `public/templates/isom2017-2_10000.ocd`
  (`src/ocd/ocdwriter.ts`). An OCD object can only reference a symbol defined in the same file, so
  the template supplies the symbol set and colour table; the writer keeps its bytes verbatim,
  repoints the georeferencing string, and appends object index blocks and objects. That is also why
  a code with no symbol in the template is dropped with a warning rather than written as a
  reference to nothing, which OCAD reports as a damaged object.
* The result is georeferenced in the LiDAR's own projected system (ETRS89 / UTM zone 32N for
  Bavaria), so coordinates are the surveyor's own rather than Web Mercator's stretched ones.

`tests/ocd.spec.ts` exports a page from nine real vector tiles and reads the result back with
[ocad2geojson](https://github.com/perliedman/ocad2geojson) -- a different implementation of the
format -- checking the version, that every object references a defined symbol, and that the
georeferencing lands in the right UTM range.

An A4 at 1:10 000 over this terrain is around 220 000 objects and 30 MB, written in some five
seconds; at 1:4000 it is 65 000 objects in under two. Two thirds of either is the cliff hatching,
which karttapullautin draws as individual ticks.

**The template's licence needs a decision before release.** It was exported from OpenOrienteering
Mapper's ISOM 2017-2 symbol set, which is GPLv3, and this app is MIT. Replacing it with a symbol set
of known provenance (one made in OCAD, say) is a drop-in change: it is fetched at runtime and
nothing but the symbol numbers is assumed.

## Drawings in the share link

Finished sketches are snapped onto the ~10 cm grid the URL stores (`src/drawings.ts`), so the length or
area shown on screen is exactly the one a shared link reproduces. `tests/drawings.spec.ts` pins that
round trip.

## Data sources

Zoom levels as in the share link (256 px tiles, OpenStreetMap's convention).

| Layer | Source | Zoom levels |
| --- | --- | --- |
| Background | OpenStreetMap standard tiles | below 12 only – nothing is fetched once the orienteering map takes over |
| Orienteering map | mapant-nf vector tiles (`{z}/{x}/{y}.pbf`) on R2, in isom-maplibre's ISOM 2017-2 style | 12–16 (overzoomed to 18) |
| Hill shading | Mapterhorn terrarium DEM, MapLibre's hillshade layer (shadows only) | 0–16 (overzoomed above) |
| Town names | OpenStreetMap via Overpass | cities and towns 12+, villages 13+ |

## Refreshing the town names

```bash
npm run fetch-places   # queries Overpass, rewrites public/places.geojson
```

Commit the result – the build and the site never talk to Overpass. It is currently ~10,600 places
(1.4 MB, ~140 kB gzipped); if that ever gets too heavy, drop `village` from the query in
`scripts/fetch-places.mjs`.

## Deployment notes

Pages must be configured once in the repository settings: **Source = GitHub Actions**, and
**Custom domain = mapant.orienteering-allgaeu.de** with a `mapant` CNAME record pointing at
`grst.github.io.` in DNS.
