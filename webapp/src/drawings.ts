import {deflateSync, inflateSync, strFromU8, strToU8} from 'fflate';
// Explicit .js: this module is also imported outside the bundler, by the tests.
import {fromLonLat, toLonLat} from 'ol/proj.js';

/** 'l' = line string, 'p' = polygon (outer ring only). */
export type DrawingType = 'l' | 'p';

export interface Drawing {
  t: DrawingType;
  /** lon/lat pairs on the share grid (see DECIMALS). */
  c: [number, number][];
}

/**
 * Coordinates are rounded before they go into the URL, which would otherwise
 * carry 17 digits per number. 6 decimals is ~10 cm – far finer than anyone can
 * draw, and short enough to keep links manageable.
 */
const DECIMALS = 6;

/** Map coordinate (EPSG:3857) -> the rounded lon/lat pair stored in the URL. */
export function toShareCoordinate(coordinate: number[]): [number, number] {
  const [lon, lat] = toLonLat(coordinate);
  return [round(lon), round(lat)];
}

/** The inverse: a stored lon/lat pair -> map coordinate. */
export function fromShareCoordinate(pair: number[]): number[] {
  return fromLonLat(pair);
}

/**
 * Snaps a map coordinate onto the share grid. Finished drawings are snapped
 * immediately, so the length or area shown on screen is exactly the one a shared
 * link reproduces – rounding on the way out would otherwise change it slightly.
 */
export function snapToShareGrid(coordinate: number[]): number[] {
  return fromShareCoordinate(toShareCoordinate(coordinate));
}

function round(value: number): number {
  const factor = 10 ** DECIMALS;
  return Math.round(value * factor) / factor;
}

/** Polygon rings are stored without their repeated closing coordinate. */
export function closeRing(coordinates: number[][]): number[][] {
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  if (first && last && (first[0] !== last[0] || first[1] !== last[1])) {
    return [...coordinates, first];
  }
  return coordinates;
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(value: string): Uint8Array {
  const binary = atob(value.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/** Deflated JSON in base64url – compact enough to live in a shareable URL. */
export function encodeDrawings(drawings: Drawing[]): string {
  if (drawings.length === 0) {
    return '';
  }
  return toBase64Url(deflateSync(strToU8(JSON.stringify(drawings)), {level: 9}));
}

function isDrawing(value: unknown): value is Drawing {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const {t, c} = value as Partial<Drawing>;
  return (
    (t === 'l' || t === 'p') &&
    Array.isArray(c) &&
    c.length >= 2 &&
    c.every((pair) => Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite))
  );
}

/** Never throws: a corrupt payload yields no drawings rather than a broken map. */
export function decodeDrawings(payload: string): Drawing[] {
  if (!payload) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(strFromU8(inflateSync(fromBase64Url(payload))));
    return Array.isArray(parsed) ? parsed.filter(isDrawing) : [];
  } catch (error) {
    console.warn('Ignoring unreadable drawings in the URL', error);
    return [];
  }
}
