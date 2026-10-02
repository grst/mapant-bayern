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
| `src/archive.ts` | the map's PMTiles archive: where it is, its header, its tiles |
| `src/isomstyle.ts` | the ISOM style of isom-maplibre, pointed at the archive |
| `src/tilemerge.ts` | serves a print map the archive's deepest tiles at any zoom |
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
  reads the orienteering map from the archive's deepest level at any scale (`mapant-print-tiles` in
  `src/layers.ts`: each tile merged from the deepest tiles under it by `src/tilemerge.ts`, which
  rewrites the protobuf -- tag tables joined, geometry offset into its quadrant), and declares the
  terrain tiles smaller than they are to get the finest ones.
* Safari caps a canvas at about 16.7 million pixels, well under an A4 page at 600 dpi, and silently
  ignores drawing beyond it; WebGL has a limit of its own on the drawing buffer. The export probes
  both and steps down to 400 or 300 dpi if the browser will not hand out what it needs.
* The scale is exact: the view resolution is derived from the paper size and corrected for the local
  Web Mercator distortion, so a ruler on the print agrees with the stated scale.
* A footer strip carries the scale and the copyright notices of the layers that were printed.

MapLibre reports a map finished (`idle`) only after a frame, and a last request that fails does not
ask for one; the export gives the print map another frame while it waits, or it could wait forever.

## The orienteering map

The map is drawn from the PMTiles archive mapant-nf publishes (`map/mapant.pmtiles`), read with HTTP
range requests from an R2 bucket (`MAPANT_PMTILES_URL` in `src/archive.ts`), in the ISOM 2017-2 style
of [isom-maplibre](https://github.com/MetsaApp/isom-maplibre).

* **The style is a fork of isom-maplibre** (branch `fix/iof-colour-order` on top of upstream
  `3c8ee09`), packed into `vendor/metsa-isom-maplibre-0.1.1-mapant.2.tgz` so the build needs nothing
  outside this repository. It stacks the symbols in the IOF colour order for ISOM 2017-2 ("IOF Map
  Specifications – Printing and Colour Definitions", 2022, §7), where upstream 0.1.0 did not: olive
  (520) above the greens, streams above the contours, lake fill below wide roads and large buildings.
  Contours stay above lakes, as in the standard; karttapullautin leaves them out under lakes instead
  (`contour_mask`). The fork also keeps every symbol sharp at any zoom: the depression (111) and
  slope tick are signed distance fields (`isomImage()` in the package; MapLibre draws them like
  text), and the fill patterns come once per zoom at their true ground spacing. To update it, rebuild the fork (`go generate ./... && npm run build && npm pack`)
  and replace the tarball.
* **The archive is in the style's schema**: a layer per table (`contours`, `vegetation_areas`,
  `paths`, …), each feature with its ISOM 2017-2 `isom_code` (`"403.000"`), 512 px tiles. The style's
  layers are used as they are; `src/isomstyle.ts` only points all of them at the one source, where the
  style expects one source per table.
* Below z13 the style draws its overview pass, from the same source. The archive's shallowest level is
  an overview without contours; below it OpenStreetMap's raster takes over (`MAP_MIN_ZOOM`, from the
  archive's header, which `src/archive.ts` reads before the style is built).
* Fills draw polygons only and lines draw lines only: MapLibre would otherwise fill an open line, and
  trace the edges a polygon was clipped at.
* The style's background is not used: the white paper is the archive's `coverage` layer, the footprint
  of the tiles that were rendered, so the rest of the viewport stays empty.
* The style's pattern and symbol images are rasterised from isom-maplibre's SVGs as MapLibre asks for
  them, at the screen's or the print's pixel ratio.
* The bucket has to send CORS headers, including `Range` and `ETag`, for any origin that serves the
  app other than the bucket itself (the GitHub Pages domain, `localhost` during development).
* To look at another archive -- a test run of mapant-nf, say -- put it in `public/` and start the dev
  server with `VITE_MAPANT_PMTILES=/mapant.pmtiles npm run dev`. Vite's dev server answers range
  requests.

## OCAD export

The same print rectangle can be saved as an editable OCAD file, as a starting point for someone who
is going to survey the area. `src/ocd/` does the whole conversion in the browser; there is no
backend and no WebAssembly, because an A4 page is a few dozen vector tiles and a few megabytes of
`DataView` writes.

* The data comes from the same archive the map is drawn from (`src/archive.ts`), read directly
  rather than through the tile merging above. `src/ocd/config.ts` holds the template URL and the
  target coordinate system.
* It always reads the **deepest** zoom, the only level that carries the map as karttapullautin
  rendered it. Every level above it is deliberately generalised for the screen -- form lines and
  knolls left off, the vegetation traced from a coarser grid, the cliff hatching sampled -- which is
  right for an overview and wrong for a map to survey from.
* A tile that does not decode as a vector tile costs its own square and no more.
* Tiles carry a buffer of their neighbours' geometry, so every feature is first clipped to its own
  tile square -- the pieces from adjacent tiles then abut instead of overlapping -- and the line
  pieces that met at a border are stitched back into one line (`src/ocd/geometry.ts`).
* Every feature carries its ISOM 2017-2 symbol as `isom_code`; mapant-nf has already translated the
  OpenStreetMap shapes from ISOM 2000 with OpenOrienteering Mapper's crosswalk. `src/ocd/isom.ts`
  only spells it the template's way (`"521.001"` is 521.1) and splits what the style draws as one by
  geometry: a lake (301.1) and its bank line (301.4).
* The file is written by appending to `public/templates/isom2017-2_10000.ocd`
  (`src/ocd/ocdwriter.ts`). An OCD object can only reference a symbol defined in the same file, so
  the template supplies the symbol set and colour table; the writer keeps its bytes verbatim,
  repoints the georeferencing string, and appends object index blocks and objects. That is also why
  a code with no symbol in the template is dropped with a warning rather than written as a
  reference to nothing, which OCAD reports as a damaged object.
* The result is georeferenced in the LiDAR's own projected system (ETRS89 / UTM zone 32N for
  Bavaria), so coordinates are the surveyor's own rather than Web Mercator's stretched ones.

`tests/ocd.spec.ts` exports a page from a small real archive and reads the result back with
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
