import {decodeDrawings, encodeDrawings, type Drawing} from './drawings';
import {detectLang, isLang, type Lang} from './i18n';

/** Short codes for the optional layers, kept terse because they live in the URL. */
export type LayerCode = 'h' | 'l' | 'g';
export const LAYER_CODES: LayerCode[] = ['h', 'l', 'g'];

/** Immenstadt im Allgäu, at the first zoom level the orienteering map covers. */
export const DEFAULT_VIEW = {zoom: 12, lat: 47.5635, lon: 10.2142};
const DEFAULT_LAYERS: LayerCode[] = ['l'];

/** Browsers cope with far more, but a link this long is no longer shareable in practice. */
const HASH_WARN_LENGTH = 8000;

export interface AppState {
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
      ? {zoom, lat, lon}
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
    `map=${round(state.zoom, 2)}/${round(state.lat, 5)}/${round(state.lon, 5)}`,
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
