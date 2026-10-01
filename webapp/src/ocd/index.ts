/**
 * Export the print area as an editable OCAD file.
 *
 * The whole conversion happens in the browser, from the same vector tiles the map is drawn from:
 * read the tiles covering the print rectangle at the deepest zoom, clip them to it, put back
 * together the lines that tiling cut apart, translate karttapullautin's classes into ISOM symbols,
 * and write an OCD 12 file around a template that supplies the symbol set.
 *
 * Reading the *deepest* zoom matters: that is the only level the pyramid is guaranteed complete at.
 * Above it tippecanoe thins the densest features to keep tiles small, which is right for a screen
 * and wrong for a map you are going to survey from.
 */

import type {Orientation} from '../print';
import {printExtent} from '../print';
import {clipLine, clipRing, contains, stitch} from './geometry';
import {symbolFor, type Symbolisation} from './isom';
import {OBJECT_TYPE_AREA, OBJECT_TYPE_LINE, OBJECT_TYPE_POINT, writeOcd} from './ocdwriter';
import type {GeorefOptions, OcdObject} from './ocdwriter';
import {toProjected} from './proj';
import type {VectorSource} from './source';
import {decodeTile, tileRect, tilesCovering, type Rect, type XY} from './tiles';

export interface OcdExportRequest {
  /** Centre of the print area, in EPSG:3857, as the map view has it. */
  center: XY;
  scale: number;
  orientation: Orientation;
  source: VectorSource;
  /** An OCD file holding the symbol set and colours to build on. */
  template: ArrayBuffer;
  /** Projected CRS to georeference the map in, and OCAD's code for it. */
  crs: string;
  gridZone: number;
}

export interface OcdExportResult {
  file: Uint8Array;
  objects: number;
  tiles: number;
  /** Codes that had no symbol in the template, and how many objects were dropped with them. */
  skipped: Map<string, number>;
  /**
   * Tiles that answered with something that is not a vector tile. A host that serves its index
   * page instead of a 404 for a tile the pyramid does not have is the usual reason, and it would
   * otherwise end the export with a parser error rather than a map with a hole in it.
   */
  unreadable: number;
}

/** 0.01 mm units per metre of paper: a metre is 1000 mm, and each unit is a hundredth of one. */
const PAPER_UNITS_PER_MM = 100;

/**
 * How close two line ends have to be to count as the same point, in metres on the ground. The
 * deepest zoom is simplified far below this, so ends that were one line land together.
 */
const STITCH_TOLERANCE_M = 0.25;

export async function exportOcd(request: OcdExportRequest): Promise<OcdExportResult> {
  const {center, scale, orientation, source, template, crs, gridZone} = request;
  const [minX, minY, maxX, maxY] = printExtent(center, scale, orientation);
  const area: Rect = {minX, minY, maxX, maxY};
  const zoom = source.maxZoom;

  // ---- read ---------------------------------------------------------------
  // Grouped by symbol and, for lines, kept as pieces to be stitched afterwards.
  const lines = new Map<string, {symbol: Symbolisation; pieces: XY[][]}>();
  const others: OcdObject[] = [];
  const originProjected = toProjected(crs, center);
  const origin: XY = [Math.round(originProjected[0]), Math.round(originProjected[1])];

  const toPaper = (point: XY): [number, number] => {
    const [easting, northing] = toProjected(crs, point);
    // Ground metres to millimetres of paper is a division by the scale; the y axis points up in
    // an OCD file, which is also the direction northing runs.
    return [
      ((easting - origin[0]) * 1000 * PAPER_UNITS_PER_MM) / scale,
      ((northing - origin[1]) * 1000 * PAPER_UNITS_PER_MM) / scale,
    ];
  };

  const tiles = tilesCovering(area, zoom);
  let unreadable = 0;
  const decoded = await Promise.all(
    tiles.map(async ({x, y}) => {
      const data = await source.fetchTile(zoom, x, y);
      if (!data) {
        return null;
      }
      try {
        return {x, y, features: decodeTile(data, zoom, x, y)};
      } catch {
        // Counted rather than thrown: one tile that is not a tile should cost its own square,
        // not the whole export.
        unreadable++;
        return null;
      }
    }),
  );

  let read = 0;
  for (const tile of decoded) {
    if (!tile) {
      continue;
    }
    read++;
    // A tile carries a buffer of its neighbours' geometry, so everything is first cut back to the
    // tile's own square: the pieces from adjacent tiles then abut instead of overlapping.
    const own = tileRect(zoom, tile.x, tile.y);

    for (const feature of tile.features) {
      const symbol = symbolFor(feature.layer, feature.properties);
      if (!symbol) {
        continue;
      }

      if (feature.geometry.kind === 'point') {
        const {point} = feature.geometry;
        if (contains(own, point) && contains(area, point)) {
          others.push({code: symbol.code, type: OBJECT_TYPE_POINT, rings: [[toPaper(point)]]});
        }
        continue;
      }

      if (feature.geometry.kind === 'line') {
        for (const inTile of clipLine(own, feature.geometry.line)) {
          for (const piece of clipLine(area, inTile)) {
            if (symbol.type === OBJECT_TYPE_POINT) {
              others.push(pointFromLine(symbol, piece, toPaper));
            } else {
              const key = symbol.code;
              const entry = lines.get(key) ?? {symbol, pieces: []};
              entry.pieces.push(piece);
              lines.set(key, entry);
            }
          }
        }
        continue;
      }

      // A polygon's rings are clipped independently: the window is convex, so each comes back as
      // one ring, and a hole that falls entirely outside simply disappears.
      const rings = feature.geometry.rings
        .map((ring) => clipRing(area, clipRing(own, ring)))
        .filter((ring) => ring.length >= 3);
      if (rings.length > 0) {
        others.push({
          code: symbol.code,
          type: OBJECT_TYPE_AREA,
          rings: rings.map((ring) => ring.map(toPaper)),
        });
      }
    }
  }

  // ---- stitch and write ---------------------------------------------------
  const objects: OcdObject[] = [];
  for (const {symbol, pieces} of lines.values()) {
    for (const joined of stitch(pieces, STITCH_TOLERANCE_M)) {
      objects.push({code: symbol.code, type: OBJECT_TYPE_LINE, rings: [joined.map(toPaper)]});
    }
  }
  objects.push(...others);

  const georef: GeorefOptions = {scale, easting: origin[0], northing: origin[1], gridZone};
  const {file, written, skipped} = writeOcd(template, objects, georef);
  return {file, objects: written, tiles: read, skipped, unreadable};
}

/**
 * The point symbol a short line stands for: karttapullautin draws a slope line as a tick across
 * the contour, and ISOM's symbol for it is a rotatable point.
 */
function pointFromLine(
  symbol: Symbolisation,
  line: XY[],
  toPaper: (point: XY) => [number, number],
): OcdObject {
  if (symbol.pointFrom === 'centroid') {
    const sum = line.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y] as XY, [0, 0] as XY);
    const centre: XY = [sum[0] / line.length, sum[1] / line.length];
    return {code: symbol.code, type: OBJECT_TYPE_POINT, rings: [[toPaper(centre)]]};
  }

  const [from] = line;
  const to = line[line.length - 1];
  // OCAD measures a symbol's rotation counter-clockwise from east, which is what atan2 gives.
  const angle = (Math.atan2(to[1] - from[1], to[0] - from[0]) * 180) / Math.PI;
  return {
    code: symbol.code,
    type: OBJECT_TYPE_POINT,
    rings: [[toPaper(from)]],
    angle: angle < 0 ? angle + 360 : angle,
  };
}

export {xyzSource} from './source';
export type {VectorSource} from './source';
