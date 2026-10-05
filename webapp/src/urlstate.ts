import {decodeDrawings, encodeDrawings, type Drawing} from './drawings';
import {detectLang, isLang, type Lang} from './i18n';

/** Short codes for the optional layers, kept terse because they live in the URL. */
export type LayerCode = 'h' | 'l' | 'g';
export const LAYER_CODES: LayerCode[] = ['h', 'l', 'g'];

/**
 * The link counts zoom levels as OpenStreetMap does, in 256 px worlds -- one more than MapLibre's
 * 512 px zoom for the same view. Links made before the switch to MapLibre keep working, and a link
 * opens at the same place on openstreetmap.org.
 */
const LINK_ZOOM_OFFSET = 1;

/** All of Germany (map zoom), with the shading that says which states are mapped. */
export const DEFAULT_VIEW = {zoom: 5.5, lat: 51.16, lon: 10.45};
const DEFAULT_LAYERS: LayerCode[] = ['l'];

/** Browsers cope with far more, but a link this long is no longer shareable in practice. */
const HASH_WARN_LENGTH = 8000;

export interface AppState {
  /** MapLibre's zoom. */
  zoom: number;
  lat: number;
  lon: number;
  layers: Set<LayerCode>;
  lang: Lang;
  drawings: Drawing[];
}

function isLayerCode(value: string): value is LayerCode {
  return (LAYER_CODES as string[]).includes(value);
}

/** Parses the hash, falling back to defaults for anything missing or malformed. */
export function readState(): AppState {
  const params = new URLSearchParams(location.hash.replace(/^#/, ''));

  // OpenStreetMap's own convention: map=zoom/lat/lon
  const [zoom, lat, lon] = (params.get('map') ?? '').split('/').map(Number);
  const view =
    Number.isFinite(zoom) && Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 85
      ? {zoom: zoom - LINK_ZOOM_OFFSET, lat, lon}
      : DEFAULT_VIEW;

  const layersParam = params.get('layers');
  const layers =
    layersParam === null
      ? new Set(DEFAULT_LAYERS)
      : new Set(layersParam.split(',').filter(isLayerCode));

  const lang = params.get('lang');

  return {
    ...view,
    layers,
    lang: isLang(lang) ? lang : detectLang(),
    drawings: decodeDrawings(params.get('d') ?? ''),
  };
}

/**
 * Rewrites the hash in place. `replaceState` rather than assigning to
 * `location.hash`, so panning the map does not fill up the browser history.
 */
export function writeState(state: AppState): void {
  const parts = [
    `map=${round(state.zoom + LINK_ZOOM_OFFSET, 2)}/${round(state.lat, 5)}/${round(state.lon, 5)}`,
    `layers=${LAYER_CODES.filter((code) => state.layers.has(code)).join(',')}`,
    `lang=${state.lang}`,
  ];
  const drawings = encodeDrawings(state.drawings);
  if (drawings) {
    parts.push(`d=${drawings}`);
  }

  const hash = `#${parts.join('&')}`;
  if (hash.length > HASH_WARN_LENGTH) {
    console.warn(`Share link is ${hash.length} characters long – consider removing some drawings.`);
  }
  if (hash !== location.hash) {
    history.replaceState(null, '', hash);
  }
}

function round(value: number, digits: number): string {
  return value.toFixed(digits);
}
