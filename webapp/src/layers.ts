import {addProtocol} from 'maplibre-gl';
import type {
  ExpressionSpecification,
  GeoJSONSourceSpecification,
  LayerSpecification,
  SourceSpecification,
  StyleSpecification,
} from 'maplibre-gl';
import {ARCHIVE, ARCHIVES, fetchTile, intersects, isMapped} from './archive';
import {basemap, BASEMAP_ATTRIBUTION} from './basemap';
import {isomLayers} from './isomstyle';
import {t} from './i18n';
import type {Key} from './i18n/en';
import {STATE_LABELS_URL, STATES, STATES_URL, STATUS_COLORS, STATUSES, type LidarStatus} from './states';
import {registerMergedTiles} from './tilemerge';

/** The archive's tile levels. The deepest is the only one that carries the full map. */
export const TILES_MIN_ZOOM = ARCHIVE.minZoom;
export const TILES_MAX_ZOOM = ARCHIVE.maxZoom;

/** The map's tiles at their own level, from whichever state archives hold them (archive.ts). */
addProtocol('mapant-tiles', async (request, abortController) => {
  const [z, x, y] = request.url.replace('mapant-tiles://', '').split('/').map(Number);
  return {data: (await fetchTile(z, x, y, abortController.signal)) ?? new ArrayBuffer(0)};
});

/**
 * For a print: the deepest level, whatever the zoom. MapLibre picks the tile level from the zoom
 * alone, so a print map -- at the zoom of its scale and a high pixel ratio -- would otherwise get
 * the tiles a screen at that scale does, generalised for 96 dpi. Each tile it asks for is merged
 * from the deepest tiles under it (tilemerge.ts).
 */
registerMergedTiles({
  scheme: 'mapant-print-tiles',
  fetchTile: (z, x, y, signal) => {
    // Which level a print reads, where the tests can see it: the archive's range requests do not say.
    performance.mark('mapant-print-tile', {detail: {z}});
    return fetchTile(z, x, y, signal);
  },
  levels: (z) => Math.max(0, TILES_MAX_ZOOM - z),
});

/** The print map's source, as TileJSON: the archive's zooms and bounds, read through the merge. */
addProtocol('mapant-print', async () => ({
  data: {
    tilejson: '3.0.0',
    tiles: ['mapant-print-tiles://{z}/{x}/{y}'],
    minzoom: TILES_MIN_ZOOM,
    maxzoom: TILES_MAX_ZOOM,
    ...(ARCHIVE.bounds ? {bounds: ARCHIVE.bounds} : {}),
  },
}));

/** Map zoom from which the orienteering map is shown, and below which the OpenFreeMap basemap is. */
export const MAP_MIN_ZOOM = TILES_MIN_ZOOM;

/** Deepest map zoom. Beyond the archive's last level the tiles are drawn overzoomed. */
export const MAP_MAX_ZOOM = 17;

/** Highest zoom level Mapterhorn's terrain tiles are available at. */
const MAPTERHORN_MAX_ZOOM = 16;

/** Town names, generated from OpenStreetMap by scripts/fetch-places.mjs and served with the site. */
const PLACES_URL = new URL('places.geojson', location.href).href;

/** Self-hosted, see public/fonts/README.md. Concatenated: URL() would encode the placeholders. */
const GLYPHS_URL = `${location.origin}/fonts/{fontstack}/{range}.pbf`;

const OSM_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>';

const MAPANT_ATTRIBUTION =
  '© Gregor Sturm (<a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noopener">CC-BY-NC-4.0</a>)';

const MAPTERHORN_ATTRIBUTION =
  '© <a href="https://mapterhorn.com/attribution" target="_blank" rel="noopener">Mapterhorn</a>';

/** The layers a visitor can switch on and off. */
export type OptionalLayer = 'hillshade' | 'places';

export type Visibility = Record<OptionalLayer, boolean>;

/** Style layers behind each switchable layer. */
export const OPTIONAL_STYLE_LAYERS: Record<OptionalLayer, string> = {
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

  // At every zoom, wherever there is no orienteering map: a tile wholly under the map is not even
  // fetched (isMapped), and the map's white paper (`coverage`) hides the rest where they overlap.
  // Not on a print, which would pull its tiles at 600 dpi.
  const background = options.print ? basemap(MAP_MIN_ZOOM) : basemap(Infinity, isMapped);
  const sources: Record<string, SourceSpecification> = {
    ...background.sources,
    mapant: options.print
      ? {type: 'vector', url: 'mapant-print://'}
      : {
          type: 'vector',
          tiles: ['mapant-tiles://{z}/{x}/{y}'],
          minzoom: TILES_MIN_ZOOM,
          maxzoom: TILES_MAX_ZOOM,
          ...(ARCHIVE.bounds ? {bounds: ARCHIVE.bounds} : {}),
        },
    states: geojson(STATES_URL),
    'state-labels': geojson(STATE_LABELS_URL),
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

  // The state shading goes between the basemap's ground and its labels, so the names stay legible.
  // The basemap's own state names are left out: the shading's labels carry them.
  const labels = background.layers.filter(
    (layer) => layer.type === 'symbol' && (options.print || layer.id !== 'basemap-label_state'),
  );
  const ground = background.layers.filter((layer) => layer.type !== 'symbol');
  const layers: LayerSpecification[] = [
    // Below the orienteering map, which covers it with its paper where there is map. Its labels
    // too: where they name the same place as the town names on top, collision keeps only those.
    ...ground,
    ...(options.print ? [] : stateLayers()),
    ...labels,
    ...(options.print ? [] : [stateLabelLayer()]),
    ...isomLayers({source: 'mapant', minZoom: MAP_MIN_ZOOM}),
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

  return {version: 8, glyphs: GLYPHS_URL, sprite: background.sprite, sources, layers};
}

/**
 * What each state publishes of its LiDAR, as a tint over the basemap below the orienteering map's
 * zooms: rendered, free, against a fee, or not at all (states.ts).
 */
function stateLayers(): LayerSpecification[] {
  const statusOf = ['match', ['get', 'id'], ...STATES.flatMap((s) => [s.id, s.status]), 'none'];
  const color = [
    'match',
    statusOf,
    ...STATUSES.flatMap((status) => [status, STATUS_COLORS[status]]),
    STATUS_COLORS.none,
  ] as ExpressionSpecification;
  return [
    {
      id: 'states-fill',
      type: 'fill',
      source: 'states',
      maxzoom: MAP_MIN_ZOOM,
      paint: {'fill-color': color, 'fill-opacity': 0.32},
    },
    {
      id: 'states-outline',
      type: 'line',
      source: 'states',
      maxzoom: MAP_MIN_ZOOM,
      paint: {'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.75, 9, 2]},
    },
  ];
}

const STATUS_KEYS: Record<LidarStatus, Key> = {
  rendered: 'status.rendered',
  free: 'status.free',
  fee: 'status.fee',
  none: 'status.none',
};

/** A darker shade of each status colour, legible as text on the tinted basemap. */
const STATUS_TEXT_COLORS: Record<LidarStatus, string> = {
  rendered: '#0f4d26',
  free: '#123f6b',
  fee: '#6b4204',
  none: '#3a3a3a',
};

/**
 * Each state's name with its status beneath it, in the status colour: the shading labelled where it
 * is rather than in a legend. In the current language; set again when it changes (main.ts).
 */
export function stateLabelText(): ExpressionSpecification {
  const status = ['match', ['get', 'id'], ...STATES.flatMap((s) => [s.id, s.status]), 'none'];
  const byStatus = (pick: (status: LidarStatus) => string) =>
    ['match', status, ...STATUSES.flatMap((s) => [s, pick(s)]), pick('none')] as unknown as ExpressionSpecification;
  return [
    'format',
    ['get', 'name'],
    {},
    '\n',
    {},
    byStatus((s) => t(STATUS_KEYS[s])),
    {'font-scale': 0.9, 'text-font': ['literal', ['Noto Sans Medium']], 'text-color': byStatus((s) => STATUS_TEXT_COLORS[s])},
  ];
}

export const STATE_LABEL_LAYER = 'states-label';

function stateLabelLayer(): LayerSpecification {
  return {
    id: STATE_LABEL_LAYER,
    type: 'symbol',
    source: 'state-labels',
    maxzoom: MAP_MIN_ZOOM,
    layout: {
      'text-field': stateLabelText(),
      'text-font': ['literal', ['Noto Sans Medium']],
      'text-size': ['interpolate', ['linear'], ['zoom'], 4, 12, 7, 16],
      'text-max-width': 8,
      // City states are small: their label may stand over the state around them.
      'text-padding': 1,
    },
    paint: {
      'text-color': '#000000',
      'text-halo-color': 'rgba(255, 255, 255, 0.95)',
      'text-halo-width': 2,
      'text-halo-blur': 0.5,
    },
  };
}

/**
 * Town names, so the label-free orienteering map can be located. Only where the orienteering map
 * is -- below it the basemap brings its own labels.
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
 * The notices for what is on screen: the orienteering map's sources from the zoom it is shown at
 * -- the LiDAR of each state whose archive the view touches -- and the terrain model's while the
 * hill shading is on.
 */
export function attributions(
  zoom: number,
  visible: Visibility,
  view?: [number, number, number, number],
  {basemap = true} = {},
): string[] {
  const notices = [OSM_ATTRIBUTION];
  // The basemap shows wherever there is no orienteering map, at every zoom -- but not on a print.
  if (basemap) {
    notices.push(BASEMAP_ATTRIBUTION);
  }
  if (zoom >= MAP_MIN_ZOOM) {
    for (const {state, info} of ARCHIVES) {
      if (state.attribution && (!view || intersects(view, info.bounds))) {
        notices.push(state.attribution);
      }
    }
    notices.push(MAPANT_ATTRIBUTION);
  }
  if (visible.hillshade) {
    notices.push(MAPTERHORN_ATTRIBUTION);
  }
  return notices;
}

/** The same notices as plain text, for the PDF footer. */
export function attributionText(
  zoom: number,
  visible: Visibility,
  view?: [number, number, number, number],
  options: {basemap?: boolean} = {},
): string {
  return attributions(zoom, visible, view, options)
    .map((notice) => notice.replace(/<[^>]*>/g, ''))
    .join(' | ');
}
