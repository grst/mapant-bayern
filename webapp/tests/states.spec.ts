import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {expect, test} from '@playwright/test';

/**
 * A tile finds the archives it may be in by each state's `reach`, before any header is read
 * (archive.ts); a reach that missed part of its state would leave that part without a map.
 */
test("each mapped state's reach takes in its whole outline, with room for the border tiles", async () => {
  // states.ts resolves its URLs against the page's; this runs in Node.
  (globalThis as {location?: unknown}).location ??= {href: 'http://localhost/'};
  const {STATES} = await import('../src/states');
  const outlines = JSON.parse(readFileSync(join(import.meta.dirname, '..', 'public', 'states.geojson'), 'utf8')) as GeoJSON.FeatureCollection;
  for (const state of STATES.filter((s) => s.archive)) {
    expect(state.reach, state.id).toBeDefined();
    const [west, south, east, north] = state.reach!;
    const feature = outlines.features.find((f) => f.properties?.id === state.id)!;
    const points = (JSON.stringify(feature.geometry).match(/-?\d+\.?\d*,-?\d+\.?\d*/g) ?? []).map((p) => p.split(',').map(Number));
    for (const [lon, lat] of points) {
      expect(lon - west, state.id).toBeGreaterThanOrEqual(0.05);
      expect(east - lon, state.id).toBeGreaterThanOrEqual(0.05);
      expect(lat - south, state.id).toBeGreaterThanOrEqual(0.05);
      expect(north - lat, state.id).toBeGreaterThanOrEqual(0.05);
    }
  }
});
