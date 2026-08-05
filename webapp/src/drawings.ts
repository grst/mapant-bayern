import {deflateSync, inflateSync, strFromU8, strToU8} from 'fflate';

/** 'l' = line string, 'p' = polygon (outer ring only). */
export type DrawingType = 'l' | 'p';

export interface Drawing {
  t: DrawingType;
  /** lon/lat pairs, rounded to 5 decimals (~1 m). */
  c: [number, number][];
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
