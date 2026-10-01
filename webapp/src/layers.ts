import {addProtocol} from 'maplibre-gl';
import type {
  ExpressionSpecification,
  GeoJSONSourceSpecification,
  LayerSpecification,
  SourceSpecification,
  StyleSpecification,
} from 'maplibre-gl';
import {isomLayers} from './isomstyle';
import {registerMergedTiles} from './tilemerge';

/**
 * The orienteering map: the vector pyramid mapant-nf publishes as `tiles_vector/`, with the
 * footprint `scripts/vector-coverage.mjs` adds next to it.
 */
const MAPANT_TILES_BASE = 'https://pub-77421d3fb5d34fc09d670e81f6c2dadf.r2.dev/vtiles/';
export const MAPANT_TILES_URL = `${MAPANT_TILES_BASE}{z}/{x}/{y}.pbf`;
const MAPANT_METADATA_URL = `${MAPANT_TILES_BASE}metadata.json`;

/**
 * Where the pyramid has tiles, as one MultiPolygon in lon/lat. The paper is drawn only there, so
 * the rest of the viewport stays empty.
 */
const MAPANT_COVERAGE_URL = `${MAPANT_TILES_BASE}coverage.geojson`;

/** The pyramid's tile levels. The deepest is the only one that carries the full map. */
export const TILES_MIN_ZOOM = 12;
export const TILES_MAX_ZOOM = 16;

/**
 * MapLibre is handed each tile merged from the pyramid's four one level deeper (see
 * tilemerge.ts), so map zoom z shows tile level z + 1, the way a 256 px tile map would. All map
 * zooms in the app are MapLibre's; only the share link keeps the 256 px convention (urlstate.ts).
 */
registerMergedTiles({scheme: 'mapant-tiles', template: MAPANT_TILES_URL, levels: () => 1});

/**
 * For a print: the deepest level, whatever the zoom. MapLibre picks the tile level from the zoom
 * alone, so a print map -- at the zoom of its scale and a high pixel ratio -- would otherwise get
 * the tiles a screen at that scale does, generalised for 96 dpi.
 */
registerMergedTiles({
  scheme: 'mapant-print-tiles',
  template: MAPANT_TILES_URL,
  levels: (z) => Math.max(1, TILES_MAX_ZOOM - z),
});

/** Map zoom from which the orienteering map is shown, and below which OpenStreetMap is. */
export const MAP_MIN_ZOOM = TILES_MIN_ZOOM - 1;

/** Deepest map zoom. Beyond the pyramid's last level the tiles are drawn overzoomed. */
export const MAP_MAX_ZOOM = 17;

/** Highest zoom level Mapterhorn's terrain tiles are available at. */
const MAPTERHORN_MAX_ZOOM = 16;

/** Town names, generated from OpenStreetMap by scripts/fetch-places.mjs and served with the site. */
const PLACES_URL = new URL('places.geojson', location.href).href;

/** Self-hosted, see public/fonts/README.md. Concatenated: URL() would encode the placeholders. */
const GLYPHS_URL = `${location.origin}/fonts/{fontstack}/{range}.pbf`;

const OSM_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>';

const MAPANT_ATTRIBUTION = [
  '© <a href="https://geodaten.bayern.de/opengeodata/" target="_blank" rel="noopener">Bayerische Vermessungsverwaltung</a> ' +
    '(<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC-BY-4.0</a>)',
  '© Gregor Sturm (<a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noopener">CC-BY-NC-4.0</a>)',
];

const MAPTERHORN_ATTRIBUTION =
  '© <a href="https://mapterhorn.com/attribution" target="_blank" rel="noopener">Mapterhorn</a>';

/**
 * The pyramid as TileJSON, with the bounds from the `metadata.json` mapant-nf writes next to it.
 * They keep the map from asking for tiles outside the mapped area, each of which would be a 404.
 * Served through a custom protocol because the style has to be built before the metadata has
 * arrived; if it never does, the tiles are still read, just without the bounds.
 */
let bounds: Promise<number[] | undefined> | undefined;
addProtocol('mapant', async (request) => {
  bounds ??= fetch(MAPANT_METADATA_URL)
    .then((response) => (response.ok ? response.json() : {}))
    .catch(() => ({}))
    .then((metadata: {bounds?: string}) => {
      const parsed = metadata.bounds?.split(',').map(Number);
      return parsed?.length === 4 && parsed.every(Number.isFinite) ? parsed : undefined;
    });
  const known = await bounds;
  const scheme = request.url === 'mapant://print' ? 'mapant-print-tiles' : 'mapant-tiles';
  return {
    data: {
      tilejson: '3.0.0',
      tiles: [`${scheme}://{z}/{x}/{y}`],
      // One level up, since each tile is read from the level below it.
      minzoom: TILES_MIN_ZOOM - 1,
      maxzoom: TILES_MAX_ZOOM - 1,
      ...(known ? {bounds: known} : {}),
    },
  };
});

/** The layers a visitor can switch on and off. The tile grid is not a layer but a debug view. */
export type OptionalLayer = 'hillshade' | 'places' | 'grid';

export type Visibility = Record<OptionalLayer, boolean>;

/** Style layers behind each switchable layer. */
export const OPTIONAL_STYLE_LAYERS: Partial<Record<OptionalLayer, string>> = {
  hillshade: 'hillshade',
  places: 'places',
};

export interface StyleOptions {
  visible: Visibility;
  /** For a print: read the deepest tiles whatever the zoom (see `mapant-print-tiles`). */
  print?: boolean;
  drawings?: GeoJSON.FeatureCollection;
  drawingLabels?: GeoJSON.FeatureCollection;
}

export const EMPTY_COLLECTION: GeoJSON.FeatureCollection = {type: 'FeatureCollection', features: []};

export const DRAWING_ACCENT = '#e2136e';

export function createStyle(options: StyleOptions): StyleSpecification {
  const visibility = (layer: OptionalLayer) => (options.visible[layer] ? 'visible' : 'none');
  const geojson = (data: GeoJSON.FeatureCollection | string): GeoJSONSourceSpecification => ({
    type: 'geojson',
    data,
  });

  const sources: Record<string, SourceSpecification> = {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
    },
    mapant: {type: 'vector', url: options.print ? 'mapant://print' : 'mapant://screen'},
    coverage: geojson(MAPANT_COVERAGE_URL),
    dem: {
      type: 'raster-dem',
      tiles: ['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp'],
      // For a print, declared smaller than they are so the finest terrain is read (see above).
      tileSize: options.print ? 128 : 512,
      maxzoom: MAPTERHORN_MAX_ZOOM,
      encoding: 'terrarium',
    },
    places: geojson(PLACES_URL),
    drawings: geojson(options.drawings ?? EMPTY_COLLECTION),
    'drawing-labels': geojson(options.drawingLabels ?? EMPTY_COLLECTION),
  };

  const layers: LayerSpecification[] = [
    // Only below the orienteering map (a layer's maxzoom is exclusive, its minzoom inclusive),
    // so nothing is ever fetched from openstreetmap.org while the orienteering map is on screen.
    {id: 'osm', type: 'raster', source: 'osm', maxzoom: MAP_MIN_ZOOM},
    ...isomLayers({source: 'mapant', coverageSource: 'coverage', minZoom: MAP_MIN_ZOOM}),
    {
      id: 'hillshade',
      type: 'hillshade',
      source: 'dem',
      layout: {visibility: visibility('hillshade')},
      // Light from the north west, the cartographic convention, and only the shadows: the
      // orienteering map keeps its colours on the sunny side, as a multiply blend would.
      paint: {
        'hillshade-illumination-direction': 315,
        'hillshade-illumination-anchor': 'map',
        'hillshade-exaggeration': 0.45,
        'hillshade-shadow-color': '#000000',
        'hillshade-highlight-color': 'rgba(0, 0, 0, 0)',
        'hillshade-accent-color': 'rgba(0, 0, 0, 0)',
      },
    },
    placesLayer(visibility('places')),
    ...drawingLayers(),
  ];

  return {version: 8, glyphs: GLYPHS_URL, sources, layers};
}

/**
 * Town names, so the label-free orienteering map can be located. Only where the orienteering map
 * is -- below it the OSM background brings its own labels.
 */
function placesLayer(visibility: 'visible' | 'none'): LayerSpecification {
  const place = ['get', 'place'] as ExpressionSpecification;
  return {
    id: 'places',
    type: 'symbol',
    source: 'places',
    minzoom: MAP_MIN_ZOOM,
    // Villages from one zoom level deeper, where there is room for them.
    filter: ['any', ['in', place, ['literal', ['city', 'town']]], ['>=', ['zoom'], MAP_MIN_ZOOM + 1]],
    layout: {
      visibility,
      'text-field': ['get', 'name'],
      'text-font': [
        'match',
        place,
        'village',
        ['literal', ['Noto Sans Regular']],
        ['literal', ['Noto Sans Medium']],
      ],
      'text-size': ['match', place, 'city', 15, 'town', 13, 12],
      'symbol-sort-key': ['match', place, 'city', 0, 'town', 1, 2],
    },
    paint: {
      'text-color': ['match', place, 'village', '#333333', '#1b1b1b'],
      'text-halo-color': 'rgba(255, 255, 255, 0.9)',
      'text-halo-width': 1.75,
    },
  };
}

/** Finished sketches and their measurements; see draw.ts. */
function drawingLayers(): LayerSpecification[] {
  return [
    {
      id: 'drawings-fill',
      type: 'fill',
      source: 'drawings',
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: {'fill-color': 'rgba(226, 19, 110, 0.12)'},
    },
    {
      id: 'drawings-line',
      type: 'line',
      source: 'drawings',
      layout: {'line-join': 'round', 'line-cap': 'round'},
      paint: {'line-color': DRAWING_ACCENT, 'line-width': 3},
    },
    {
      id: 'drawings-label',
      type: 'symbol',
      source: 'drawing-labels',
      layout: {
        'text-field': ['get', 'text'],
        'text-font': ['literal', ['Noto Sans Medium']],
        'text-size': 12,
        'text-offset': [0, -1.2],
        'text-allow-overlap': true,
        'text-ignore-placement': true,
      },
      paint: {'text-color': '#1b1b1b', 'text-halo-color': 'rgba(255, 255, 255, 0.9)', 'text-halo-width': 2},
    },
  ];
}

/**
 * The notices for what is on screen: the orienteering map's sources from the zoom it is shown at,
 * and the terrain model's while the hill shading is on.
 */
export function attributions(zoom: number, visible: Visibility): string[] {
  const notices = [OSM_ATTRIBUTION];
  if (zoom >= MAP_MIN_ZOOM) {
    notices.push(...MAPANT_ATTRIBUTION);
  }
  if (visible.hillshade) {
    notices.push(MAPTERHORN_ATTRIBUTION);
  }
  return notices;
}

/** The same notices as plain text, for the PDF footer. */
export function attributionText(zoom: number, visible: Visibility): string {
  return attributions(zoom, visible)
    .map((notice) => notice.replace(/<[^>]*>/g, ''))
    .join(' | ');
}
