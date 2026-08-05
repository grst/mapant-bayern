import {expect, test} from '@playwright/test';
import Polygon from 'ol/geom/Polygon.js';
import LineString from 'ol/geom/LineString.js';
import {getArea, getLength} from 'ol/sphere.js';
import {
  closeRing,
  decodeDrawings,
  encodeDrawings,
  fromShareCoordinate,
  snapToShareGrid,
  toShareCoordinate,
  type Drawing,
} from '../src/drawings';

/** Raw map coordinates, as they come out of a mouse-drawn geometry. */
const DRAWN = [
  [1137412.3419283, 6042318.9284712],
  [1139887.7712389, 6043102.1129384],
  [1138204.9917253, 6040091.4471933],
];

/** What the app stores in the drawing layer once a sketch is finished. */
const SNAPPED = DRAWN.map(snapToShareGrid);

function roundTrip(drawing: Drawing): number[][] {
  const restored = decodeDrawings(encodeDrawings([drawing]));
  expect(restored).toHaveLength(1);
  return restored[0].c.map(fromShareCoordinate);
}

test('a share link reproduces a polygon exactly, area included', () => {
  const restored = roundTrip({t: 'p', c: SNAPPED.map(toShareCoordinate)});

  expect(restored).toEqual(SNAPPED);
  const area = (coordinates: number[][]) => getArea(new Polygon([closeRing(coordinates)]));
  expect(area(restored)).toBe(area(SNAPPED));
});

test('a share link reproduces a line exactly, length included', () => {
  const restored = roundTrip({t: 'l', c: SNAPPED.map(toShareCoordinate)});

  expect(restored).toEqual(SNAPPED);
  const length = (coordinates: number[][]) => getLength(new LineString(coordinates));
  expect(length(restored)).toBe(length(SNAPPED));
});

test('snapping stays put once applied', () => {
  // The invariant the fix rests on: snapping is idempotent, so serialising an
  // already-snapped geometry cannot move it again.
  expect(SNAPPED.map(snapToShareGrid)).toEqual(SNAPPED);
});

test('snapping a drawing moves it by less than a decimetre', () => {
  for (const [index, coordinate] of DRAWN.entries()) {
    const snapped = SNAPPED[index];
    expect(Math.hypot(snapped[0] - coordinate[0], snapped[1] - coordinate[1])).toBeLessThan(0.1);
  }
});

test('unreadable payloads are ignored rather than thrown', () => {
  expect(decodeDrawings('not-a-payload')).toEqual([]);
  expect(decodeDrawings('')).toEqual([]);
});
