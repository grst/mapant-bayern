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
| `src/draw.ts` | measure/draw interactions and the drawing codec |
| `src/i18n.ts`, `src/i18n/*.ts` | DE/EN strings, applied via `data-i18n` attributes |
| `src/ui/*.ts` | navbar, layer panel, draw toolbar, share button, zoom hint |
| `public/places.geojson` | town names overlay (generated, committed) |
| `public/CNAME` | custom domain, copied into `dist/` by Vite |

The about page renders the repository's root `README.md` (imported with Vite's `?raw`), and the
screenshots it links to are served from `../img` by a small plugin in `vite.config.ts`.

## Data sources

| Layer | Source | Zoom levels |
| --- | --- | --- |
| Background | OpenStreetMap standard tiles | 0–11 (overzoomed above) |
| Orienteering map | `mapant-bayern.pmtiles` over HTTP range requests | 12–18 |
| Hill shading | Mapterhorn terrarium DEM, shaded in WebGL | 0–16 (overzoomed above) |
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
