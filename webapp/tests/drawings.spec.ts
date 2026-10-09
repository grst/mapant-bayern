import {expect, test} from '@playwright/test';
import {closeRing, decodeDrawings, encodeDrawings, snapToShareGrid, type Drawing} from '../src/drawings';
import {distance, lineLength, ringArea, type LonLat} from '../src/geo';

/** Raw lon/lat, as they come out of a mouse-drawn geometry. */
const DRAWN: LonLat[] = [
  [10.217531128462, 47.563218476129],
  [10.239765112398, 47.568002917734],
  [10.224648229351, 47.549716338402],
];

/** What the app stores in the drawing layer once a sketch is finished. */
const SNAPPED = DRAWN.map(snapToShareGrid);

function roundTrip(drawing: Drawing): LonLat[] {
  const restored = decodeDrawings(encodeDrawings([drawing]));
  expect(restored).toHaveLength(1);
  return restored[0].c;
}

test('a share link reproduces a polygon exactly, area included', () => {
  const restored = roundTrip({t: 'p', c: SNAPPED});

  expect(restored).toEqual(SNAPPED);
  const area = (coordinates: LonLat[]) => ringArea(closeRing(coordinates) as LonLat[]);
  expect(area(restored)).toBe(area(SNAPPED));
});

test('a share link reproduces a line exactly, length included', () => {
  const restored = roundTrip({t: 'l', c: SNAPPED});

  expect(restored).toEqual(SNAPPED);
  const length = (coordinates: LonLat[]) => lineLength(coordinates);
  expect(length(restored)).toBe(length(SNAPPED));
});

test('snapping stays put once applied', () => {
  // The invariant the fix rests on: snapping is idempotent, so serialising an
  // already-snapped geometry cannot move it again.
  expect(SNAPPED.map(snapToShareGrid)).toEqual(SNAPPED);
});

test('snapping a drawing moves it by less than a decimetre', () => {
  for (const [index, coordinate] of DRAWN.entries()) {
    expect(distance(SNAPPED[index], coordinate)).toBeLessThan(0.1);
  }
});

test('unreadable payloads are ignored rather than thrown', () => {
  expect(decodeDrawings('not-a-payload')).toEqual([]);
  expect(decodeDrawings('')).toEqual([]);
});
