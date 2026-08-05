import GeoJSON from 'ol/format/GeoJSON';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import WebGLTileLayer from 'ol/layer/WebGLTile';
import {transformExtent} from 'ol/proj';
import ImageTileSource from 'ol/source/ImageTile';
import OSM from 'ol/source/OSM';
import TileDebug from 'ol/source/TileDebug';
import VectorSource from 'ol/source/Vector';
import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import Text from 'ol/style/Text';
import {createXYZ} from 'ol/tilegrid';
import {PMTiles} from 'pmtiles';
import type {FeatureLike} from 'ol/Feature';

/** The orienteering map archive. Its own header reports minzoom 12 / maxzoom 18. */
const MAPANT_PMTILES = 'https://mapant-tiles.orienteering-allgaeu.de/mapant-bayern.pmtiles';
export const MAPANT_MIN_ZOOM = 12;
export const MAPANT_MAX_ZOOM = 18;

/**
 * Coverage of the archive (Bavaria). Hardcoded on purpose: the PMTiles header
 * carries the whole-world bounds (-180,-85,180,85) and empty metadata, so there
 * is nothing to read it from.
 */
const MAPANT_EXTENT = transformExtent([8.96484, 47.21957, 13.88672, 50.62507], 'EPSG:4326', 'EPSG:3857');

const OSM_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>';

const MAPANT_ATTRIBUTION = [
  OSM_ATTRIBUTION,
  '© <a href="https://geodaten.bayern.de/opengeodata/" target="_blank" rel="noopener">Bayerische Vermessungsverwaltung</a> ' +
    '(<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC-BY-4.0</a>)',
  '© Gregor Sturm (<a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noopener">CC-BY-NC-4.0</a>)',
];

const MAPTERHORN_ATTRIBUTION =
  '© <a href="https://mapterhorn.com/attribution" target="_blank" rel="noopener">Mapterhorn</a>';

/** Highest zoom level Mapterhorn's terrain tiles are available at. */
const MAPTERHORN_MAX_ZOOM = 16;

/** EPSG:3857 resolutions: one 256 px tile at zoom 0 spans the whole world. */
const MAX_RESOLUTION = 156543.03392804097;

/**
 * View resolution at which the DEM stops gaining detail. The tiles are 512 px, so
 * two texels span one 256 px-tile resolution at the same zoom level.
 */
const MAPTERHORN_MIN_RESOLUTION = MAX_RESOLUTION / 2 ** MAPTERHORN_MAX_ZOOM;

/**
 * Background map, shown only below the orienteering map's zoom levels. The layer
 * hands over at exactly the same threshold the orienteering map takes over at
 * (maxZoom is inclusive, minZoom exclusive), so nothing is ever fetched from
 * openstreetmap.org while the orienteering map is on screen.
 */
function createOsmLayer(): TileLayer<OSM> {
  return new TileLayer({
    maxZoom: MAPANT_MIN_ZOOM - 0.001,
    // Same string as the other layers use, so the footer lists it only once.
    source: new OSM({maxZoom: MAPANT_MIN_ZOOM - 1, attributions: OSM_ATTRIBUTION}),
  });
}

/** Stand-in for the parts of Bavaria the archive does not cover. */
const TRANSPARENT_TILE = (() => {
  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;
  return canvas;
})();

function decodeImage(blob: Blob): Promise<HTMLImageElement> {
  const url = URL.createObjectURL(blob);
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.addEventListener('load', () => {
      URL.revokeObjectURL(url);
      resolve(image);
    });
    image.addEventListener('error', () => {
      URL.revokeObjectURL(url);
      reject(new Error('Could not decode tile image'));
    });
    image.src = url;
  });
}

/**
 * The orienteering map itself: WebP tiles read straight out of the PMTiles
 * archive over HTTP range requests.
 */
function createMapantLayer(cacheSize?: number): TileLayer<ImageTileSource> {
  const archive = new PMTiles(MAPANT_PMTILES);
  return new TileLayer({
    cacheSize,
    // Zoom range and extent are hardcoded rather than read from the archive: the
    // layer's minZoom is exclusive, so without the epsilon z12 itself would be
    // dropped, and OpenLayers would otherwise clamp to the lowest available zoom
    // level and request z12 tiles for the whole viewport at z2.
    minZoom: MAPANT_MIN_ZOOM - 0.001,
    extent: MAPANT_EXTENT,
    source: new ImageTileSource({
      minZoom: MAPANT_MIN_ZOOM,
      maxZoom: MAPANT_MAX_ZOOM,
      attributions: MAPANT_ATTRIBUTION,
      loader: async (z, x, y) => {
        const tile = await archive.getZxy(z, x, y);
        // The archive is sparse: no LIDAR, no tile.
        return tile ? decodeImage(new Blob([tile.data], {type: 'image/webp'})) : TRANSPARENT_TILE;
      },
    }),
  });
}

/**
 * Hill shading computed in the browser from Mapterhorn's terrarium-encoded DEM,
 * following the OpenLayers "Shaded Relief (with WebGL)" example.
 */
function createHillshadeLayer(cacheSize?: number): WebGLTileLayer {
  const elevation = (xOffset: number, yOffset: number) => [
    '+',
    ['*', 255 * 256, ['band', 1, xOffset, yOffset]],
    ['*', 255, ['band', 2, xOffset, yOffset]],
    ['*', 255 / 256, ['band', 3, xOffset, yOffset]],
    -32768,
  ];

  // Horizontal distance between the two sampled texels. The tiles are 512 px for
  // the same extent a 256 px tile would cover, so one texel is half a view pixel
  // and two texels add up to one view resolution.
  //
  // Clamped at the resolution of the DEM's highest zoom level: above z16 the
  // tiles are overzoomed, so the sampled texels stay the same distance apart on
  // the ground while the view resolution keeps halving. Without the clamp the
  // terrain would look twice as steep at z17 and four times as steep at z18.
  const dp = ['clamp', ['resolution'], MAPTERHORN_MIN_RESOLUTION, MAX_RESOLUTION];
  const dzdx = ['/', ['-', elevation(1, 0), elevation(-1, 0)], dp];
  const dzdy = ['/', ['-', elevation(0, 1), elevation(0, -1)], dp];
  const slope = ['atan', ['sqrt', ['+', ['^', dzdx, 2], ['^', dzdy, 2]]]];
  const aspect = ['clamp', ['atan', ['-', 0, dzdx], dzdy], -Math.PI, Math.PI];
  const sunEl = ['*', Math.PI / 180, ['var', 'sunEl']];
  const sunAz = ['*', Math.PI / 180, ['var', 'sunAz']];
  const cosIncidence = [
    '+',
    ['*', ['sin', sunEl], ['cos', slope]],
    ['*', ['cos', sunEl], ['sin', slope], ['cos', ['-', sunAz, aspect]]],
  ];

  // Normalised so flat ground comes out at 1: dividing by the incidence on a
  // horizontal surface (sin of the sun elevation) means level terrain is left
  // untouched instead of being greyed over.
  const shade = ['clamp', ['/', cosIncidence, ['sin', sunEl]], 0, 1];

  // Painting black with alpha = 1 - shade is exactly a multiply blend: the
  // result is base * shade. Slopes facing away from the sun darken, everything
  // else keeps its colour, and the orienteering map stays saturated. Doing it
  // in the shader rather than with mix-blend-mode keeps the layer composited
  // together with all the others.
  const multiply = ['color', 0, ['*', ['var', 'strength'], ['-', 1, shade]]];

  return new WebGLTileLayer({
    visible: false,
    cacheSize,
    source: new ImageTileSource({
      url: 'https://tiles.mapterhorn.com/{z}/{x}/{y}.webp',
      tileSize: 512,
      maxZoom: MAPTERHORN_MAX_ZOOM,
      // Explicit: ol/source/ImageTile leaves crossOrigin unset by default, and
      // WebGL cannot upload a non-CORS image as a texture.
      crossOrigin: 'anonymous',
      attributions: MAPTERHORN_ATTRIBUTION,
    }),
    style: {
      // sunAz 315 = light from the north west, the cartographic convention.
      // strength scales the shading from 0 (off) to 1 (full multiply).
      variables: {sunEl: 45, sunAz: 315, strength: 0.45},
      color: multiply,
    },
  });
}

/** Label sizes in CSS pixels, multiplied by `scale` for print (see print.ts). */
function placeStyles(scale: number): Record<string, {minZoom: number; style: Style}> {
  return {
    city: {minZoom: MAPANT_MIN_ZOOM, style: placeStyle('bold', 15, '#1b1b1b', scale)},
    town: {minZoom: MAPANT_MIN_ZOOM, style: placeStyle('bold', 13, '#1b1b1b', scale)},
    village: {minZoom: 13, style: placeStyle('normal', 12, '#333333', scale)},
  };
}

function placeStyle(weight: string, sizePx: number, color: string, scale: number): Style {
  return new Style({
    text: new Text({
      font: `${weight} ${sizePx * scale}px system-ui, sans-serif`,
      fill: new Fill({color}),
      stroke: new Stroke({color: 'rgba(255, 255, 255, 0.9)', width: 3.5 * scale}),
      overflow: true,
    }),
  });
}

/** Rough zoom level for a resolution in EPSG:3857, enough to pick a label size. */
function zoomFor(resolution: number): number {
  return Math.log2(MAX_RESOLUTION / resolution);
}

/**
 * Town names, so the label-free orienteering map can be located. Generated from
 * OpenStreetMap by scripts/fetch-places.mjs. Only shown where the orienteering
 * map is – below that the OSM background brings its own labels.
 */
function createPlacesLayer(styleScale: number): VectorLayer<VectorSource> {
  const styles = placeStyles(styleScale);
  return new VectorLayer({
    minZoom: MAPANT_MIN_ZOOM - 0.001,
    declutter: true,
    source: new VectorSource({
      url: 'places.geojson',
      format: new GeoJSON(),
      attributions: OSM_ATTRIBUTION,
    }),
    style: (feature: FeatureLike, resolution: number) => {
      const entry = styles[feature.get('place') as string];
      // Which labels are shown follows the zoom the paper shows, not the finer
      // resolution the print map renders at.
      if (!entry || zoomFor(resolution * styleScale) < entry.minZoom) {
        return undefined;
      }
      entry.style.getText()?.setText(feature.get('name') as string);
      return entry.style;
    },
  });
}

/**
 * Tile boundaries of the orienteering map, as in the original prototype. Which
 * level is drawn follows the view resolution, so a print – which renders finer
 * than the paper reads – is capped at the level its scale shows on screen.
 */
function createGridLayer(screenResolution?: number): TileLayer<TileDebug> {
  const maxZoom = screenResolution
    ? Math.min(MAPANT_MAX_ZOOM, Math.round(zoomFor(screenResolution)))
    : MAPANT_MAX_ZOOM;
  return new TileLayer({
    visible: false,
    source: new TileDebug({
      tileGrid: createXYZ({maxZoom}),
    }),
  });
}

export interface AppLayers {
  osm: TileLayer<OSM>;
  mapant: TileLayer<ImageTileSource>;
  hillshade: WebGLTileLayer;
  places: VectorLayer<VectorSource>;
  grid: TileLayer<TileDebug>;
}

/**
 * The notices that apply to what is currently drawn, as plain text for the PDF
 * footer. Same strings as the on-screen attribution, with the links removed.
 */
export function attributionText(layers: AppLayers): string {
  const notices = [...MAPANT_ATTRIBUTION];
  if (layers.hillshade.getVisible()) {
    notices.push(MAPTERHORN_ATTRIBUTION);
  }
  return notices.map((notice) => notice.replace(/<[^>]*>/g, '')).join(' | ');
}

/**
 * Everything the print map has to pass down to render for paper instead of a
 * screen; see `PrintLayerOptions` in print.ts.
 */
export interface LayerOptions {
  styleScale?: number;
  screenResolution?: number;
  tileCacheSize?: number;
}

export function createLayers(options: LayerOptions = {}): AppLayers {
  const styleScale = options.styleScale ?? 1;
  return {
    osm: createOsmLayer(),
    mapant: createMapantLayer(options.tileCacheSize),
    hillshade: createHillshadeLayer(options.tileCacheSize),
    places: createPlacesLayer(styleScale),
    grid: createGridLayer(options.screenResolution),
  };
}
