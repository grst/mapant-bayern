/**
 * Clipping to a rectangle, and putting back together what tiling took apart.
 *
 * A vector tile carries a buffer of its neighbours' geometry so a renderer can draw lines whose
 * ends fall outside, which means the same feature arrives more than once when several tiles are
 * read at once. Clipping each tile's features to that tile's own square removes the duplication
 * exactly – the pieces then abut instead of overlapping – and stitching joins the pieces that met
 * at a tile border back into one line.
 *
 * The alternative, deduplicating by feature identity, does not work here: a vector tile keeps no
 * identity across tiles, and with `--coalesce` a feature is not even one object.
 */

import type {Rect, XY} from './tiles';

/** Is a point inside the rectangle? */
export function contains(rect: Rect, [x, y]: XY): boolean {
  return x >= rect.minX && x <= rect.maxX && y >= rect.minY && y <= rect.maxY;
}

/**
 * Clip a polyline to a rectangle, returning the pieces that fall inside.
 *
 * Liang–Barsky per segment, with consecutive segments that stay inside kept as one piece rather
 * than being emitted one by one.
 */
export function clipLine(rect: Rect, line: XY[]): XY[][] {
  const pieces: XY[][] = [];
  let current: XY[] = [];

  for (let i = 0; i + 1 < line.length; i++) {
    const clipped = clipSegment(rect, line[i], line[i + 1]);
    if (!clipped) {
      if (current.length >= 2) {
        pieces.push(current);
      }
      current = [];
      continue;
    }
    const [from, to] = clipped;
    if (current.length === 0) {
      current.push(from);
    } else if (!same(current[current.length - 1], from)) {
      // The line left the rectangle and came back: that is a new piece.
      if (current.length >= 2) {
        pieces.push(current);
      }
      current = [from];
    }
    current.push(to);
  }

  if (current.length >= 2) {
    pieces.push(current);
  }
  return pieces;
}

const EPSILON = 1e-9;

function same(a: XY, b: XY): boolean {
  return Math.abs(a[0] - b[0]) < EPSILON && Math.abs(a[1] - b[1]) < EPSILON;
}

function clipSegment(rect: Rect, from: XY, to: XY): [XY, XY] | null {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  let t0 = 0;
  let t1 = 1;

  const edges: [number, number][] = [
    [-dx, from[0] - rect.minX],
    [dx, rect.maxX - from[0]],
    [-dy, from[1] - rect.minY],
    [dy, rect.maxY - from[1]],
  ];

  for (const [p, q] of edges) {
    if (p === 0) {
      if (q < 0) {
        return null; // parallel to this edge and outside it
      }
      continue;
    }
    const t = q / p;
    if (p < 0) {
      if (t > t1) return null;
      if (t > t0) t0 = t;
    } else {
      if (t < t0) return null;
      if (t < t1) t1 = t;
    }
  }

  return [
    [from[0] + t0 * dx, from[1] + t0 * dy],
    [from[0] + t1 * dx, from[1] + t1 * dy],
  ];
}

/**
 * Clip a polygon ring to a rectangle (Sutherland–Hodgman).
 *
 * The window is convex and the ring is clipped against one edge at a time, so a ring comes back as
 * a single ring. Holes are clipped the same way and independently, which is correct as long as
 * they are handed over separately.
 */
export function clipRing(rect: Rect, ring: XY[]): XY[] {
  let output = ring;
  const inside: ((p: XY) => boolean)[] = [
    (p) => p[0] >= rect.minX,
    (p) => p[0] <= rect.maxX,
    (p) => p[1] >= rect.minY,
    (p) => p[1] <= rect.maxY,
  ];
  const intersect: ((a: XY, b: XY) => XY)[] = [
    (a, b) => interpolateX(a, b, rect.minX),
    (a, b) => interpolateX(a, b, rect.maxX),
    (a, b) => interpolateY(a, b, rect.minY),
    (a, b) => interpolateY(a, b, rect.maxY),
  ];

  for (let edge = 0; edge < 4 && output.length > 0; edge++) {
    const input = output;
    output = [];
    for (let i = 0, j = input.length - 1; i < input.length; j = i++) {
      const current = input[i];
      const previous = input[j];
      const currentIn = inside[edge](current);
      if (currentIn !== inside[edge](previous)) {
        output.push(intersect[edge](previous, current));
      }
      if (currentIn) {
        output.push(current);
      }
    }
  }
  return output;
}

function interpolateX(a: XY, b: XY, x: number): XY {
  const t = (x - a[0]) / (b[0] - a[0]);
  return [x, a[1] + t * (b[1] - a[1])];
}

function interpolateY(a: XY, b: XY, y: number): XY {
  const t = (y - a[1]) / (b[1] - a[1]);
  return [a[0] + t * (b[0] - a[0]), y];
}

/**
 * Join line pieces whose ends meet, so a contour cut at a tile border is one line again.
 *
 * `tolerance` is in the same units as the coordinates; at the deepest zoom the tiles were
 * simplified far below a metre, so ends that belong together land on the border together.
 * Only pieces already known to belong to the same feature should be handed in.
 */
export function stitch(pieces: XY[][], tolerance: number): XY[][] {
  const remaining = pieces.filter((piece) => piece.length >= 2);
  const key = (point: XY) =>
    `${Math.round(point[0] / tolerance)},${Math.round(point[1] / tolerance)}`;

  // Which pieces still start or end at a given point.
  const ends = new Map<string, number[]>();
  const add = (point: XY, index: number) => {
    const k = key(point);
    const list = ends.get(k);
    if (list) {
      list.push(index);
    } else {
      ends.set(k, [index]);
    }
  };
  remaining.forEach((piece, index) => {
    add(piece[0], index);
    add(piece[piece.length - 1], index);
  });

  const used = new Array<boolean>(remaining.length).fill(false);
  const joined: XY[][] = [];

  const takeAt = (point: XY, exclude: number): number | null => {
    for (const index of ends.get(key(point)) ?? []) {
      if (index !== exclude && !used[index]) {
        return index;
      }
    }
    return null;
  };

  for (let start = 0; start < remaining.length; start++) {
    if (used[start]) {
      continue;
    }
    used[start] = true;
    let line = [...remaining[start]];

    // Extend forwards, then backwards, until nothing meets the ends any more.
    for (const direction of [0, 1]) {
      for (;;) {
        const tip = direction === 0 ? line[line.length - 1] : line[0];
        const next = takeAt(tip, -1);
        if (next === null) {
          break;
        }
        used[next] = true;
        const piece = remaining[next];
        const forwards = same(tip, piece[0]) || key(tip) === key(piece[0]);
        const tail = forwards ? piece.slice(1) : piece.slice(0, -1).reverse();
        line = direction === 0 ? [...line, ...tail] : [...tail.reverse(), ...line];
      }
    }

    joined.push(line);
  }
  return joined;
}
