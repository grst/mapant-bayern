/**
 * The orienteering map in a rectangle, as features: what the PDF and the OCD export are both made
 * from.
 *
 * Always read from the archive's **deepest** zoom, the only level that carries the map as
 * karttapullautin rendered it. Every level above it is generalised for the screen -- form lines and
 * knolls left off, the vegetation traced from a coarser grid -- which is right for an overview and
 * wrong for a page or a map you are going to survey from.
 *
 * A tile carries a buffer of its neighbours' geometry, so the same feature arrives once per tile
 * it touches. Lines and points are cut back to their own tile's square, and the line pieces that
 * met at a border stitched back into one line (geometry.ts). Areas are cut back too for an OCD
 * file, where each would otherwise be two objects on top of each other; a drawing keeps them as
 * they are (`buffered`), since an area drawn twice in the same place looks like one, while two
 * that merely abut show a hairline seam in most PDF viewers.
 */

import {clipLine, clipRing, contains, stitch} from './geometry';
import type {VectorSource} from './source';
import {decodeTile, tileRect, tilesCovering, type Geometry, type Rect, type TileFeature, type XY} from './tiles';

export interface MapFeature {
  /** The tile layer, e.g. `contours`. */
  layer: string;
  properties: TileFeature['properties'];
  /** In EPSG:3857, inside the rectangle. */
  geometry: Geometry;
}

export interface AreaTiles {
  zoom: number;
  tiles: {x: number; y: number; features: TileFeature[]}[];
  /**
   * Tiles that answered with something that is not a vector tile. A host that serves its index
   * page instead of a 404 for a tile the pyramid does not have is the usual reason, and it would
   * otherwise end an export with a parser error rather than a map with a hole in it.
   */
  unreadable: number;
}

/**
 * How close two line ends have to be to count as the same point, in metres on the ground. The
 * deepest zoom is simplified far below this, so ends that were one line land together.
 */
const STITCH_TOLERANCE_M = 0.25;

/** The deepest tiles under a rectangle in EPSG:3857, decoded. Tiles the archive lacks are left out. */
export async function readTiles(source: VectorSource, area: Rect): Promise<AreaTiles> {
  const zoom = source.maxZoom;
  let unreadable = 0;
  const decoded = await Promise.all(
    tilesCovering(area, zoom).map(async ({x, y}) => {
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
  return {zoom, tiles: decoded.filter((tile) => tile !== null), unreadable};
}

export interface AreaOptions {
  /** Keep areas whole across tile borders, buffers included (see above), rather than cut back. */
  buffered?: boolean;
}

/** The features of the tiles inside a rectangle, once each. */
export function areaFeatures({zoom, tiles}: AreaTiles, area: Rect, options: AreaOptions = {}): MapFeature[] {
  const out: MapFeature[] = [];
  // Line pieces, to be stitched with the other pieces of features just like them: the same layer
  // and attributes, so a contour only ever joins a contour of its own height.
  const pieces = new Map<string, {layer: string; properties: TileFeature['properties']; lines: XY[][]}>();

  for (const tile of tiles) {
    const own = tileRect(zoom, tile.x, tile.y);
    for (const {layer, properties, geometry} of tile.features) {
      if (geometry.kind === 'point') {
        if (contains(own, geometry.point) && contains(area, geometry.point)) {
          out.push({layer, properties, geometry});
        }
      } else if (geometry.kind === 'line') {
        const key = `${layer}\u0000${JSON.stringify(properties)}`;
        let entry = pieces.get(key);
        if (!entry) {
          entry = {layer, properties, lines: []};
          pieces.set(key, entry);
        }
        for (const inTile of clipLine(own, geometry.line)) {
          entry.lines.push(...clipLine(area, inTile));
        }
      } else {
        // A polygon's rings are clipped independently: the window is convex, so each comes back
        // as one ring, and a hole that falls entirely outside simply disappears.
        const rings = geometry.rings
          .map((ring) => clipRing(area, options.buffered ? ring : clipRing(own, ring)))
          .filter((ring) => ring.length >= 3);
        if (rings.length > 0) {
          out.push({layer, properties, geometry: {kind: 'polygon', rings}});
        }
      }
    }
  }

  for (const {layer, properties, lines} of pieces.values()) {
    for (const line of stitch(lines, STITCH_TOLERANCE_M)) {
      out.push({layer, properties, geometry: {kind: 'line', line}});
    }
  }
  return out;
}
