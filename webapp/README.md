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
