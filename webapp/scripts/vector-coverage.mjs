#!/usr/bin/env node
/**
 * Writes the footprint of a vector pyramid as `coverage.geojson` next to its
 * tiles, for the white paper the app draws under the vector map.
 *
 *   node scripts/vector-coverage.mjs <tiles_vector dir> [zoom]
 *
 * The footprint is the union of the tiles present at `zoom` (default: the
 * deepest level in the directory), as one MultiPolygon in lon/lat. One feature
 * rather than one per tile, so the paper is filled in a single pass and the
 * seams between neighbouring squares cannot show through antialiasing.
 */
import {readdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';

const [dir, zoomArg] = process.argv.slice(2);
if (!dir) {
  console.error('usage: vector-coverage.mjs <tiles dir> [zoom]');
  process.exit(1);
}

const numeric = (name) => /^\d+$/.test(name);
const zoom = zoomArg ?? String(Math.max(...readdirSync(dir).filter(numeric).map(Number)));

// Columns of present tiles per row.
const rows = new Map();
for (const x of readdirSync(join(dir, zoom)).filter(numeric)) {
  for (const file of readdirSync(join(dir, zoom, x))) {
    const y = Number(file.replace(/\.pbf$/, ''));
    if (!rows.has(y)) rows.set(y, []);
    rows.get(y).push(Number(x));
  }
}

// Runs of consecutive columns, then runs that repeat in the next row are merged
// into one rectangle, which turns thousands of squares into a few hundred.
const open = new Map(); // "x0:x1" -> {x0, x1, y0, y1}
const rectangles = [];
for (const y of [...rows.keys()].sort((a, b) => a - b)) {
  const xs = rows.get(y).sort((a, b) => a - b);
  const runs = [];
  for (const x of xs) {
    const last = runs.at(-1);
    if (last && last[1] === x) last[1] = x + 1;
    else runs.push([x, x + 1]);
  }
  const seen = new Set();
  for (const [x0, x1] of runs) {
    const key = `${x0}:${x1}`;
    seen.add(key);
    const rectangle = open.get(key);
    if (rectangle && rectangle.y1 === y) rectangle.y1 = y + 1;
    else open.set(key, {x0, x1, y0: y, y1: y + 1});
  }
  for (const [key, rectangle] of open) {
    if (!seen.has(key)) {
      rectangles.push(rectangle);
      open.delete(key);
    }
  }
}
rectangles.push(...open.values());

const n = 2 ** Number(zoom);
const lon = (x) => +((x / n) * 360 - 180).toFixed(7);
const lat = (y) => +((Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI).toFixed(7);

const coverage = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: {zoom: Number(zoom)},
      geometry: {
        type: 'MultiPolygon',
        coordinates: rectangles.map(({x0, x1, y0, y1}) => [
          [
            [lon(x0), lat(y1)],
            [lon(x1), lat(y1)],
            [lon(x1), lat(y0)],
            [lon(x0), lat(y0)],
            [lon(x0), lat(y1)],
          ],
        ]),
      },
    },
  ],
};

const out = join(dir, 'coverage.geojson');
writeFileSync(out, JSON.stringify(coverage));
console.log(`${out}: ${rectangles.length} rectangles from z${zoom}`);
