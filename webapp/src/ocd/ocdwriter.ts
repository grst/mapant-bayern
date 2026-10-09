/**
 * Writes an OCAD 12 file in the browser, by appending to a template.
 *
 * An OCD file is a header followed by three linked lists of index blocks – symbols, parameter
 * strings, objects – whose entries point at byte offsets elsewhere in the same file. Objects can
 * only reference symbols *inside* the file, so a usable map needs the full ISOM symbol set and its
 * colour table present. Authoring those from scratch would be hundreds of records of pattern and
 * hatch geometry; instead a template exported once from OpenOrienteering Mapper is kept verbatim
 * and only added to. Every offset in it stays valid, and the symbols are the real ISOM 2017-2 ones.
 *
 * So the whole writer is: copy the template, repoint its georeferencing string at a new one, and
 * append object index blocks and objects at the end.
 *
 * Layout facts, all from OpenOrienteering Mapper's implementation (`src/fileformats/ocd_types*.h`,
 * `ocd_file_export.cpp`), which is the working reference for the format:
 *
 *   header             60 bytes; `AD 0C`, then file type, status, version 12
 *   index block        4-byte offset of the next block, then 256 entries
 *   object index entry 40 bytes: bounding box, offset, size *in bytes*, symbol, type, status
 *   object             56-byte header, then 8 bytes per coordinate
 *   coordinate         two int32; the top 24 bits are units of 0.01 mm on paper, the low 8 are
 *                      flags; y points up, the opposite of a screen
 *
 * Everything is little-endian.
 */

const OFFSET_FIRST_SYMBOL_BLOCK = 8;
const OFFSET_FIRST_OBJECT_BLOCK = 12;
const OFFSET_FIRST_STRING_BLOCK = 32;

const ENTRIES_PER_BLOCK = 256;
const OBJECT_INDEX_ENTRY_SIZE = 40;
const OBJECT_INDEX_BLOCK_SIZE = 4 + ENTRIES_PER_BLOCK * OBJECT_INDEX_ENTRY_SIZE;
const STRING_INDEX_ENTRY_SIZE = 16;
const STRING_INDEX_BLOCK_SIZE = 4 + ENTRIES_PER_BLOCK * STRING_INDEX_ENTRY_SIZE;
const OBJECT_HEADER_SIZE = 56;

/** Parameter string holding the map scale and the real-world reference point. */
const STRING_TYPE_SCALE = 1039;

/** Parameter string naming a background map (Mapper calls it a template) and placing it. */
export const STRING_TYPE_BACKGROUND_MAP = 8;

/** `status` of an object that is simply there. */
const OBJECT_STATUS_NORMAL = 1;

export const OBJECT_TYPE_POINT = 1;
export const OBJECT_TYPE_LINE = 2;
export const OBJECT_TYPE_AREA = 3;

/** Set on the *first* point of a hole, to start a new ring inside an area object. */
const FLAG_HOLE = 0x02;

/**
 * OCAD's drawing area is ±2 m of paper, and a coordinate only has 24 bits anyway. An A4 page at
 * 1:15 000 is 0.3 m, so this is a guard against a bug rather than a real limit.
 */
const MAX_PAPER_UNITS = 200_000;

/**
 * A symbol number as OCAD stores it: the ISOM code times a thousand, plus the sub-code as a plain
 * integer. `101.1` is 101001, which OCAD in turn displays as 101.001.
 */
export function symbolNumber(code: string): number {
  const [main, sub = '0'] = code.split('.');
  return Number(main) * 1000 + Number(sub);
}

export interface OcdObject {
  /** ISOM code, e.g. `"101"` or `"101.1"`. */
  code: string;
  type: typeof OBJECT_TYPE_POINT | typeof OBJECT_TYPE_LINE | typeof OBJECT_TYPE_AREA;
  /**
   * Paper coordinates in units of 0.01 mm, y already pointing up. For an area object the first
   * ring is the outline and the rest are holes.
   */
  rings: [number, number][][];
  /** Rotation of a point symbol, in degrees counter-clockwise. */
  angle?: number;
}

export interface GeorefOptions {
  /** Scale denominator, e.g. 10000 for 1:10 000. */
  scale: number;
  /** Projected coordinates of the map's origin, i.e. of paper (0, 0). */
  easting: number;
  northing: number;
  /**
   * OCAD's coded coordinate system: the grid identifier times 1000 plus the zone. 63005 is
   * ETRS89 / UTM zone 32N (EPSG:25832), which is what Bavaria's LiDAR is in.
   */
  gridZone: number;
}

/** A parameter string to add to the file: its type and its tab-separated text. */
export interface ParameterString {
  type: number;
  text: string;
}

/** Walk an index block chain, calling back with the offset of each block. */
function forEachBlock(view: DataView, first: number, visit: (block: number) => void): void {
  let block = first;
  while (block > 0 && block + 4 <= view.byteLength) {
    visit(block);
    block = view.getUint32(block, true);
  }
}

/**
 * The symbol numbers a template defines, so a code that is not in it can be reported instead of
 * being written as a reference to nothing – which OCAD shows as a damaged object.
 */
export function templateSymbolNumbers(template: ArrayBuffer): Set<number> {
  const view = new DataView(template);
  const numbers = new Set<number>();
  forEachBlock(view, view.getUint32(OFFSET_FIRST_SYMBOL_BLOCK, true), (block) => {
    for (let i = 0; i < ENTRIES_PER_BLOCK; i++) {
      const position = view.getUint32(block + 4 + i * 4, true);
      // A symbol record starts with its size, then its number.
      if (position > 0 && position + 8 <= view.byteLength) {
        numbers.add(view.getUint32(position + 4, true));
      }
    }
  });
  return numbers;
}

/** One coordinate pair, packed as OCAD stores it. */
function writeCoordinate(view: DataView, at: number, x: number, y: number, flags: number): void {
  view.setInt32(at, encodeCoordinate(x), true);
  view.setInt32(at + 4, encodeCoordinate(y) | flags, true);
}

/**
 * A coordinate value in the top 24 bits, leaving the low 8 for flags.
 *
 * A reader recovers the value with an arithmetic shift right by 8, so what has to be stored is the
 * low 23 bits of the *two's complement* plus the sign in bit 31 -- then the shift sign-extends
 * back to the original. Storing the magnitude instead looks equally plausible and puts every
 * negative coordinate about 8.4 million units away, which is to say off the page.
 */
function encodeCoordinate(value: number): number {
  const rounded = Math.round(value);
  if (rounded < 0) {
    return (0x80000000 | ((0x7fffff & rounded) << 8)) | 0;
  }
  return ((0x7fffff & rounded) << 8) | 0;
}

/** The inverse, for tests and for reading back what was written. */
export function decodeCoordinate(stored: number): number {
  return stored >> 8;
}

function toBytes(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

/**
 * The georeferencing string. Tab-separated, each field introduced by a one-letter key:
 * `m` scale, `g` paper grid spacing in mm, `r` 1 for real-world coordinates, `x`/`y` the projected
 * position of the map origin in whole metres, `a` the angle to grid north, `d` the terrain grid
 * spacing in metres, `i` the coded coordinate system.
 */
function georefString({scale, easting, northing, gridZone}: GeorefOptions): string {
  return [
    '',
    `m${scale}`,
    'g50.0000',
    'r1',
    `x${Math.round(easting)}`,
    `y${Math.round(northing)}`,
    'a0.00000000',
    'd500.000000',
    `i${gridZone}`,
    'b0.00',
    'c0.00',
  ].join('\t');
}

/**
 * Build an OCD file from a template plus a set of objects.
 *
 * The template's bytes are copied unchanged, so its symbols, colours and view settings survive;
 * only the type-1039 string index entry is repointed, at a replacement appended with everything
 * else. Objects fill the template's own (empty) object index block first and then as many new
 * blocks as they need.
 */
export function writeOcd(
  template: ArrayBuffer,
  objects: OcdObject[],
  georef: GeorefOptions,
  strings: ParameterString[] = [],
): {file: Uint8Array; written: number; skipped: Map<string, number>} {
  const known = templateSymbolNumbers(template);

  // Everything appended goes after the template, 8-byte aligned as Mapper aligns its records.
  const parts: Uint8Array[] = [new Uint8Array(template)];
  let end = template.byteLength;
  const align = () => {
    const padding = (8 - (end % 8)) % 8;
    if (padding > 0) {
      parts.push(new Uint8Array(padding));
      end += padding;
    }
  };

  const push = (bytes: Uint8Array): number => {
    align();
    const at = end;
    parts.push(bytes);
    end += bytes.byteLength;
    return at;
  };

  // The header and index blocks of the copy are edited in place; the copy is `parts[0]`.
  const head = new DataView(parts[0].buffer, parts[0].byteOffset, parts[0].byteLength);

  // ---- georeferencing -----------------------------------------------------
  const georefBytes = toBytes(georefString(georef) + '\0');
  const georefAt = push(georefBytes);
  let repointed = false;
  forEachBlock(head, head.getUint32(OFFSET_FIRST_STRING_BLOCK, true), (block) => {
    for (let i = 0; i < ENTRIES_PER_BLOCK && !repointed; i++) {
      const entry = block + 4 + i * STRING_INDEX_ENTRY_SIZE;
      if (head.getUint32(entry, true) > 0 && head.getInt32(entry + 8, true) === STRING_TYPE_SCALE) {
        head.setUint32(entry, georefAt, true);
        head.setUint32(entry + 4, georefBytes.byteLength, true);
        repointed = true;
      }
    }
  });
  if (!repointed) {
    throw new Error('the OCD template has no georeferencing string to replace');
  }

  // ---- further parameter strings ------------------------------------------
  // Into free entries of the template's string index, or a block appended to its chain.
  const freeStringSlots: {view: DataView; at: number}[] = [];
  let lastStringBlock = head.getUint32(OFFSET_FIRST_STRING_BLOCK, true);
  forEachBlock(head, lastStringBlock, (block) => {
    lastStringBlock = block;
    for (let i = 0; i < ENTRIES_PER_BLOCK; i++) {
      const entry = block + 4 + i * STRING_INDEX_ENTRY_SIZE;
      if (head.getUint32(entry, true) === 0) {
        freeStringSlots.push({view: head, at: entry});
      }
    }
  });
  if (strings.length > freeStringSlots.length) {
    const bytes = new Uint8Array(STRING_INDEX_BLOCK_SIZE);
    const view = new DataView(bytes.buffer);
    head.setUint32(lastStringBlock, push(bytes), true);
    for (let i = 0; i < ENTRIES_PER_BLOCK; i++) {
      freeStringSlots.push({view, at: 4 + i * STRING_INDEX_ENTRY_SIZE});
    }
  }
  for (const {type, text} of strings) {
    const bytes = toBytes(text + '\0');
    const slot = freeStringSlots.shift()!;
    slot.view.setUint32(slot.at, push(bytes), true);
    slot.view.setUint32(slot.at + 4, bytes.byteLength, true);
    slot.view.setInt32(slot.at + 8, type, true);
    slot.view.setInt32(slot.at + 12, 0, true);
  }

  // ---- objects ------------------------------------------------------------
  // Free slots in the template's own object index chain come first; the map it was exported from
  // has no objects, so that is a whole block.
  const freeSlots: number[] = [];
  let lastBlock = head.getUint32(OFFSET_FIRST_OBJECT_BLOCK, true);
  forEachBlock(head, lastBlock, (block) => {
    lastBlock = block;
    for (let i = 0; i < ENTRIES_PER_BLOCK; i++) {
      const entry = block + 4 + i * OBJECT_INDEX_ENTRY_SIZE;
      if (head.getUint32(entry + 16, true) === 0) {
        freeSlots.push(entry);
      }
    }
  });

  const skipped = new Map<string, number>();
  const pending: {entry: DataView | null; slot: number; record: Uint8Array; meta: EntryMeta}[] = [];
  // Index entries that land in blocks appended after the template are written into those blocks,
  // so they are collected first and the blocks built once the count is known.
  const extra: {record: Uint8Array; meta: EntryMeta}[] = [];

  for (const object of objects) {
    const number = symbolNumber(object.code);
    if (!known.has(number)) {
      skipped.set(object.code, (skipped.get(object.code) ?? 0) + 1);
      continue;
    }
    const built = buildObject(object, number);
    if (!built) {
      continue;
    }
    if (freeSlots.length > 0) {
      const slot = freeSlots.shift() as number;
      pending.push({entry: head, slot, record: built.record, meta: built.meta});
    } else {
      extra.push({record: built.record, meta: built.meta});
    }
  }

  // Append the records, then the index blocks that point at them.
  for (const item of pending) {
    const at = push(item.record);
    writeIndexEntry(item.entry as DataView, item.slot, at, item.record.byteLength, item.meta);
  }

  if (extra.length > 0) {
    const blocks = Math.ceil(extra.length / ENTRIES_PER_BLOCK);
    const blockBytes: Uint8Array[] = [];
    const blockAt: number[] = [];
    for (let b = 0; b < blocks; b++) {
      const bytes = new Uint8Array(OBJECT_INDEX_BLOCK_SIZE);
      blockBytes.push(bytes);
      blockAt.push(push(bytes));
    }
    // Chain them: the template's last block points at the first new one, and each at the next.
    head.setUint32(lastBlock, blockAt[0], true);
    for (let b = 0; b + 1 < blocks; b++) {
      new DataView(blockBytes[b].buffer).setUint32(0, blockAt[b + 1], true);
    }

    for (let i = 0; i < extra.length; i++) {
      const item = extra[i];
      const at = push(item.record);
      const block = blockBytes[Math.floor(i / ENTRIES_PER_BLOCK)];
      const slot = 4 + (i % ENTRIES_PER_BLOCK) * OBJECT_INDEX_ENTRY_SIZE;
      writeIndexEntry(new DataView(block.buffer), slot, at, item.record.byteLength, item.meta);
    }
  }

  const file = new Uint8Array(end);
  let at = 0;
  for (const part of parts) {
    file.set(part, at);
    at += part.byteLength;
  }
  return {file, written: pending.length + extra.length, skipped};
}

interface EntryMeta {
  number: number;
  type: number;
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function writeIndexEntry(
  view: DataView,
  at: number,
  position: number,
  size: number,
  meta: EntryMeta,
): void {
  writeCoordinate(view, at, meta.minX, meta.minY, 0);
  writeCoordinate(view, at + 8, meta.maxX, meta.maxY, 0);
  view.setUint32(at + 16, position, true);
  // In bytes, and padded to a multiple of 8. The published format documentation says this counts
  // coordinates for version 9 and up; following that makes OCAD report damaged objects, and
  // Mapper's exporter carries the same note.
  view.setUint32(at + 20, size + ((8 - (size % 8)) % 8), true);
  view.setInt32(at + 24, meta.number, true);
  view.setUint8(at + 28, meta.type);
  view.setUint8(at + 30, OBJECT_STATUS_NORMAL);
}

function buildObject(object: OcdObject, number: number): {record: Uint8Array; meta: EntryMeta} | null {
  // An area object holds its rings end to end, each after the first starting at a hole point.
  const points: {x: number; y: number; flags: number}[] = [];
  for (const [index, ring] of object.rings.entries()) {
    if (ring.length === 0) {
      continue;
    }
    const closed = object.type === OBJECT_TYPE_AREA;
    const ringPoints = closed ? closeRing(ring) : ring;
    for (const [i, [x, y]] of ringPoints.entries()) {
      points.push({x, y, flags: index > 0 && i === 0 ? FLAG_HOLE : 0});
    }
  }
  if (points.length === 0 || (object.type === OBJECT_TYPE_LINE && points.length < 2)) {
    return null;
  }

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const point of points) {
    if (Math.abs(point.x) > MAX_PAPER_UNITS || Math.abs(point.y) > MAX_PAPER_UNITS) {
      throw new Error('a coordinate falls outside OCAD’s drawing area');
    }
    minX = Math.min(minX, point.x);
    minY = Math.min(minY, point.y);
    maxX = Math.max(maxX, point.x);
    maxY = Math.max(maxY, point.y);
  }

  const record = new Uint8Array(OBJECT_HEADER_SIZE + points.length * 8);
  const view = new DataView(record.buffer);
  view.setInt32(0, number, true);
  view.setUint8(4, object.type);
  // Tenths of a degree, counter-clockwise.
  view.setInt16(6, Math.round(((object.angle ?? 0) * 10) % 3600), true);
  view.setUint32(44, points.length, true);

  points.forEach((point, i) => {
    writeCoordinate(view, OBJECT_HEADER_SIZE + i * 8, point.x, point.y, point.flags);
  });

  return {record, meta: {number, type: object.type, minX, minY, maxX, maxY}};
}

function closeRing(ring: [number, number][]): [number, number][] {
  const [first] = ring;
  const last = ring[ring.length - 1];
  if (first[0] === last[0] && first[1] === last[1]) {
    return ring;
  }
  return [...ring, first];
}
