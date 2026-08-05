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

/**
 * Background map. Capped at z11 so nothing is fetched from openstreetmap.org
 * once the orienteering map takes over; the overzoomed z11 tiles still give
 * context outside the archive's coverage.
 */
function createOsmLayer(): TileLayer<OSM> {
  return new TileLayer({
    // Same string as the other layers use, so the footer lists it only once.
    source: new OSM({maxZoom: 11, attributions: OSM_ATTRIBUTION}),
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
function createMapantLayer(): TileLayer<ImageTileSource> {
  const archive = new PMTiles(MAPANT_PMTILES);
  return new TileLayer({
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
function createHillshadeLayer(): WebGLTileLayer {
  const elevation = (xOffset: number, yOffset: number) => [
    '+',
    ['*', 255 * 256, ['band', 1, xOffset, yOffset]],
    ['*', 255, ['band', 2, xOffset, yOffset]],
    ['*', 255 / 256, ['band', 3, xOffset, yOffset]],
    -32768,
  ];

  // Horizontal distance between the two sampled texels. The tiles are 512 px
  // for the same extent a 256 px tile would cover, so one texel is half a view
  // pixel and two texels add up to a single view resolution.
  const dp = ['resolution'];
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

  return new WebGLTileLayer({
    opacity: 0.35,
    visible: false,
    source: new ImageTileSource({
      url: 'https://tiles.mapterhorn.com/{z}/{x}/{y}.webp',
      tileSize: 512,
      maxZoom: 16,
      // Explicit: ol/source/ImageTile leaves crossOrigin unset by default, and
      // WebGL cannot upload a non-CORS image as a texture.
      crossOrigin: 'anonymous',
      attributions: MAPTERHORN_ATTRIBUTION,
    }),
    style: {
      variables: {sunEl: 45, sunAz: 315},
      color: ['color', ['*', 255, cosIncidence]],
    },
  });
}

const PLACE_STYLES: Record<string, {minZoom: number; style: Style}> = {
  city: {minZoom: MAPANT_MIN_ZOOM, style: placeStyle('bold 15px', '#1b1b1b')},
  town: {minZoom: MAPANT_MIN_ZOOM, style: placeStyle('bold 13px', '#1b1b1b')},
  village: {minZoom: 13, style: placeStyle('12px', '#333333')},
};

function placeStyle(font: string, color: string): Style {
  return new Style({
    text: new Text({
      font: `${font} system-ui, sans-serif`,
      fill: new Fill({color}),
      stroke: new Stroke({color: 'rgba(255, 255, 255, 0.9)', width: 3.5}),
      overflow: true,
    }),
  });
}

/** Rough zoom level for a resolution in EPSG:3857, enough to pick a label size. */
function zoomFor(resolution: number): number {
  return Math.log2(156543.03392804097 / resolution);
}

/**
 * Town names, so the label-free orienteering map can be located. Generated from
 * OpenStreetMap by scripts/fetch-places.mjs. Only shown where the orienteering
 * map is – below that the OSM background brings its own labels.
 */
function createPlacesLayer(): VectorLayer<VectorSource> {
  return new VectorLayer({
    minZoom: MAPANT_MIN_ZOOM - 0.001,
    declutter: true,
    source: new VectorSource({
      url: 'places.geojson',
      format: new GeoJSON(),
      attributions: OSM_ATTRIBUTION,
    }),
    style: (feature: FeatureLike, resolution: number) => {
      const entry = PLACE_STYLES[feature.get('place') as string];
      if (!entry || zoomFor(resolution) < entry.minZoom) {
        return undefined;
      }
      entry.style.getText()?.setText(feature.get('name') as string);
      return entry.style;
    },
  });
}

/** Tile boundaries of the orienteering map, as in the original prototype. */
function createGridLayer(): TileLayer<TileDebug> {
  return new TileLayer({
    visible: false,
    source: new TileDebug({
      tileGrid: createXYZ({maxZoom: MAPANT_MAX_ZOOM}),
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

export function createLayers(): AppLayers {
  return {
    osm: createOsmLayer(),
    mapant: createMapantLayer(),
    hillshade: createHillshadeLayer(),
    places: createPlacesLayer(),
    grid: createGridLayer(),
  };
}
