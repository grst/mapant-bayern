/**
 * Reading the vector pyramid: which tiles cover an area, and what is in them.
 *
 * Everything here works in EPSG:3857 metres, because that is the only projection in which both a
 * tile and the print rectangle are axis-aligned rectangles – which is what makes clipping a
 * comparison rather than a reprojection. The conversion from a tile's own integer grid to 3857 is
 * linear and exact, so nothing is lost on the way.
 */

import {VectorTile} from '@mapbox/vector-tile';
import {PbfReader} from 'pbf';

/** Half the circumference of the earth at the equator: the edge of the web-mercator square. */
const WORLD = 20037508.342789244;

export type XY = [number, number];

export type Geometry =
  | {kind: 'point'; point: XY}
  | {kind: 'line'; line: XY[]}
  | {kind: 'polygon'; rings: XY[][]};

export interface TileFeature {
  layer: string;
  properties: Record<string, string | number | boolean>;
  geometry: Geometry;
}

export interface Rect {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export function tileRect(z: number, x: number, y: number): Rect {
  const span = (2 * WORLD) / 2 ** z;
  const minX = -WORLD + x * span;
  const maxY = WORLD - y * span;
  return {minX, minY: maxY - span, maxX: minX + span, maxY};
}

/** Every tile of the given zoom that touches the rectangle. */
export function tilesCovering(rect: Rect, z: number): {x: number; y: number}[] {
  const span = (2 * WORLD) / 2 ** z;
  const count = 2 ** z;
  const clamp = (value: number) => Math.min(count - 1, Math.max(0, value));
  const first = {
    x: clamp(Math.floor((rect.minX + WORLD) / span)),
    y: clamp(Math.floor((WORLD - rect.maxY) / span)),
  };
  const last = {
    x: clamp(Math.floor((rect.maxX + WORLD) / span)),
    y: clamp(Math.floor((WORLD - rect.minY) / span)),
  };

  const tiles: {x: number; y: number}[] = [];
  for (let x = first.x; x <= last.x; x++) {
    for (let y = first.y; y <= last.y; y++) {
      tiles.push({x, y});
    }
  }
  return tiles;
}

/**
 * Decode one tile into simple geometries in EPSG:3857.
 *
 * One feature out per geometry, not per encoded feature: the pyramid is cut with tippecanoe's
 * `--coalesce`, which merges features sharing their attributes into multi-geometries, so a single
 * encoded feature routinely holds thousands of cliff ticks. They are separate objects on a map.
 */
export function decodeTile(data: ArrayBuffer, z: number, x: number, y: number): TileFeature[] {
  const tile = new VectorTile(new PbfReader(data));
  const {minX, maxY} = tileRect(z, x, y);
  const span = (2 * WORLD) / 2 ** z;

  const out: TileFeature[] = [];
  for (const layerName of Object.keys(tile.layers)) {
    const layer = tile.layers[layerName];
    const scale = span / layer.extent;
    const toWorld = (point: {x: number; y: number}): XY => [
      minX + point.x * scale,
      maxY - point.y * scale,
    ];

    for (let i = 0; i < layer.length; i++) {
      const feature = layer.feature(i);
      const properties = feature.properties as Record<string, string | number | boolean>;
      const parts = feature.loadGeometry();

      if (feature.type === 1) {
        for (const part of parts) {
          for (const point of part) {
            out.push({layer: layerName, properties, geometry: {kind: 'point', point: toWorld(point)}});
          }
        }
      } else if (feature.type === 2) {
        for (const part of parts) {
          if (part.length >= 2) {
            out.push({
              layer: layerName,
              properties,
              geometry: {kind: 'line', line: part.map(toWorld)},
            });
          }
        }
      } else if (feature.type === 3) {
        for (const rings of classifyRings(parts)) {
          out.push({
            layer: layerName,
            properties,
            geometry: {kind: 'polygon', rings: rings.map((ring) => ring.map(toWorld))},
          });
        }
      }
    }
  }
  return out;
}

/**
 * Group a polygon feature's flat list of rings into polygons.
 *
 * The vector tile spec winds an outer ring one way and the holes inside it the other, and gives no
 * other marker, so a ring whose signed area has the same sign as the first one starts a new
 * polygon and the opposite sign is a hole in the current one.
 */
function classifyRings(parts: {x: number; y: number}[][]): {x: number; y: number}[][][] {
  if (parts.length === 0) {
    return [];
  }
  const outerSign = Math.sign(signedArea(parts[0]));
  const polygons: {x: number; y: number}[][][] = [];
  for (const ring of parts) {
    if (ring.length < 3) {
      continue;
    }
    if (polygons.length === 0 || Math.sign(signedArea(ring)) === outerSign) {
      polygons.push([ring]);
    } else {
      polygons[polygons.length - 1].push(ring);
    }
  }
  return polygons;
}

function signedArea(ring: {x: number; y: number}[]): number {
  let sum = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    sum += (ring[j].x - ring[i].x) * (ring[j].y + ring[i].y);
  }
  return sum;
}
