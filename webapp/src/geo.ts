/**
 * The bits of geodesy the app needs outside the map: web mercator for the print and OCD maths,
 * which work in EPSG:3857 metres, and lengths and areas on the sphere for the measuring tools.
 * The formulas are the ones OpenLayers uses (`ol/proj/epsg3857`, `ol/sphere`), so measurements
 * come out as they did before the switch to MapLibre.
 */

export type LonLat = [number, number];
/** EPSG:3857 metres. */
export type XY = [number, number];

/** Half the circumference of the earth at the equator: the edge of the web-mercator square. */
export const HALF_WORLD = 20037508.342789244;
const EARTH_RADIUS_3857 = 6378137;

/** Mean earth radius, as `ol/sphere` measures with. */
const EARTH_RADIUS = 6371008.8;

const toRadians = (degrees: number) => (degrees * Math.PI) / 180;

export function fromLonLat([lon, lat]: LonLat): XY {
  const y = EARTH_RADIUS_3857 * Math.log(Math.tan(Math.PI / 4 + toRadians(lat) / 2));
  return [EARTH_RADIUS_3857 * toRadians(lon), Math.max(-HALF_WORLD, Math.min(HALF_WORLD, y))];
}

export function toLonLat([x, y]: XY): LonLat {
  const lon = (x / EARTH_RADIUS_3857) * (180 / Math.PI);
  const lat = (2 * Math.atan(Math.exp(y / EARTH_RADIUS_3857)) - Math.PI / 2) * (180 / Math.PI);
  return [lon, lat];
}

/**
 * Ground metres per EPSG:3857 unit at a point: web mercator stretches everything by 1/cos(lat).
 * `ol/proj`'s getPointResolution for 3857 is the same factor.
 */
export function mercatorDistortion([, y]: XY): number {
  return 1 / Math.cosh(y / EARTH_RADIUS_3857);
}

/** Great-circle distance between two points, in metres. */
export function distance(a: LonLat, b: LonLat): number {
  const lat1 = toRadians(a[1]);
  const lat2 = toRadians(b[1]);
  const deltaLatBy2 = (lat2 - lat1) / 2;
  const deltaLonBy2 = toRadians(b[0] - a[0]) / 2;
  const h =
    Math.sin(deltaLatBy2) ** 2 + Math.sin(deltaLonBy2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * EARTH_RADIUS * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

export function lineLength(line: LonLat[]): number {
  let length = 0;
  for (let i = 1; i < line.length; i++) {
    length += distance(line[i - 1], line[i]);
  }
  return length;
}

/** Area of a ring on the sphere, in square metres; open or closed, either winding. */
export function ringArea(ring: LonLat[]): number {
  let area = 0;
  let [x1, y1] = ring[ring.length - 1];
  for (const [x2, y2] of ring) {
    area += toRadians(x2 - x1) * (2 + Math.sin(toRadians(y1)) + Math.sin(toRadians(y2)));
    x1 = x2;
    y1 = y2;
  }
  return Math.abs((area * EARTH_RADIUS * EARTH_RADIUS) / 2);
}

/**
 * A point inside a ring, for a label: the middle of the widest stretch of a horizontal line
 * through the ring's vertical middle. Unlike the centroid it cannot fall outside a concave shape.
 * The same idea as OpenLayers' `getInteriorPoint`.
 */
export function interiorPoint(ring: LonLat[]): LonLat {
  const ys = ring.map(([, y]) => y);
  const y = (Math.min(...ys) + Math.max(...ys)) / 2;
  const crossings: number[] = [];
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi <= y !== yj <= y) {
      crossings.push(xi + ((y - yi) / (yj - yi)) * (xj - xi));
    }
  }
  crossings.sort((a, b) => a - b);
  let best: LonLat = ring[0];
  let widest = -1;
  for (let i = 0; i + 1 < crossings.length; i += 2) {
    const width = crossings[i + 1] - crossings[i];
    if (width > widest) {
      widest = width;
      best = [(crossings[i] + crossings[i + 1]) / 2, y];
    }
  }
  return best;
}
