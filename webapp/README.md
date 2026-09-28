# Mapant Bayern webapp

The map viewer at [mapant.orienteering-allgaeu.de](https://mapant.orienteering-allgaeu.de): a static
site built with [Vite](https://vite.dev/) and [OpenLayers](https://openlayers.org/), deployed to
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
| `src/layers.ts` | all map layers and their copyright notices |
| `src/map.ts` | map, view and OpenLayers controls |
| `src/urlstate.ts` | the share link: `#map=zoom/lat/lon&layers=…&lang=…&d=…` |
| `src/draw.ts`, `src/drawings.ts` | measure/draw interactions, and the codec that puts them in the URL |
| `src/print.ts` | PDF export: scale maths and the off-screen print map |
| `src/i18n.ts`, `src/i18n/*.ts` | DE/EN strings, applied via `data-i18n` attributes |
| `src/ui/*.ts` | navbar, layer panel, print panel, draw toolbar, share button, zoom hint |
| `public/places.geojson` | town names overlay (generated, committed) |
| `public/CNAME` | custom domain, copied into `dist/` by Vite |

The about page renders the repository's root `README.md` – or `README.de.md` when German is selected –
imported with Vite's `?raw`. The screenshots those files link to are served from `../img` by a small
plugin in `vite.config.ts`.

## PDF export

`src/print.ts` builds a second, off-screen map at paper size and saves it through
[jsPDF](https://github.com/parallax/jsPDF) (loaded on demand – it is larger than the rest of the app).

* A4, portrait or landscape, at 1:4000 / 1:7500 / 1:10 000 / 1:15 000.
* 600 dpi, losslessly compressed. That is roughly where the archive runs out of detail: at 1:10 000 the
  page asks for 0.42 m per pixel and the z18 tiles hold about 0.4 m.
* The print map renders at `pixelRatio = 1` into a viewport the size of the paper *in output pixels* –
  4961 × 6850 for an A4 page. This is what makes the print sharp, and it is easy to get wrong:
  OpenLayers picks the tile zoom level from the view resolution alone and then scales the tiles up by
  the pixel ratio, so a map at `pixelRatio = dpi/96` fetches the tiles a *screen* would use and
  magnifies them – 600 dpi of paper carrying 96 dpi of map. The price is that style sizes given in CSS
  pixels no longer scale by themselves, so the layers are handed a `styleScale` to multiply fonts,
  stroke widths and symbol radii by (`PrintLayerOptions` in `src/print.ts`).
* Safari caps a canvas at about 16.7 million pixels, well under an A4 page at 600 dpi, and silently
  ignores drawing beyond it. The export probes a canvas of the size it needs and steps down to 400 or
  300 dpi if the browser will not hand one out.
* The scale is exact: the view resolution is derived from the paper size and corrected for the local
  Web Mercator distortion, so a ruler on the print agrees with the stated scale.
* A footer strip carries the scale and the copyright notices of the layers that were printed.

A full page is 300 to 650 tiles, around 20 MB from the archive, and lands at 25–45 MB of PDF. Expect
some seconds on a fast connection and a couple of minutes on a slow one; the tile cache of the print
layers is sized for the page, since the 512 tiles OpenLayers keeps by default are not enough to hold
one.

## Vector map

Built with `VITE_MAPANT_STYLE` set to the `style.json` that mapant-nf publishes next to a vector
pyramid, the app draws the orienteering map from those tiles instead of the WebP archive, with the
pipeline's own MapLibre style applied by `ol-mapbox-style`. Everything else -- print, OCAD export,
places, hill shading -- stays as it is.

* The style's background is not used: OpenLayers would paint it across the whole viewport. White
  paper is drawn only where the pyramid has tiles, from a `coverage.geojson` next to the style;
  `node scripts/vector-coverage.mjs <tiles_vector dir>` writes it.
* The tiles are read as 256 px tiles, like the raster pyramid: zoom z shows tile level z, so all
  contours are on screen from z15 and the full detail from z16. MapLibre, which takes them as
  512 px, shows each level one zoom later. Line widths are unaffected; they follow the style's zoom.
* Print needs nothing extra. The style sizes its lines in ground metres, so the finer resolution of
  the print map already draws them at the right width on paper.

```sh
VITE_MAPANT_STYLE=/vtiles/style.json VITE_MAPANT_VECTOR_TILES='/vtiles/{z}/{x}/{y}.pbf' \
VITE_MAPANT_VECTOR_MIN_ZOOM=12 VITE_MAPANT_VECTOR_MAX_ZOOM=16 npm run build
```

## OCAD export

The same print rectangle can be saved as an editable OCAD file, as a starting point for someone who
is going to survey the area. `src/ocd/` does the whole conversion in the browser; there is no
backend and no WebAssembly, because an A4 page is a few dozen vector tiles and a few megabytes of
`DataView` writes.

* The data comes from a **vector** pyramid (`tiles_vector/` from `mapant-nf --vector_tiles true`),
  not from the WebP archive, since an image cannot be turned back into objects. `src/ocd/config.ts`
  holds its URL and zoom range; both are `VITE_`-prefixed build settings.
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

| Layer | Source | Zoom levels |
| --- | --- | --- |
| Background | OpenStreetMap standard tiles | below 12 only – nothing is fetched once the orienteering map takes over |
| Orienteering map | `mapant-bayern.pmtiles` over HTTP range requests | 12–18 |
| Hill shading | Mapterhorn terrarium DEM, shaded in WebGL, multiplied over the map | 0–16 (overzoomed above, with the slope held at its z16 value) |
| Town names | OpenStreetMap via Overpass | cities 7+, towns 10+, villages 13+ |

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
