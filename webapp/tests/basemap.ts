import type {Page} from '@playwright/test';

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);

/**
 * Stands in for openfreemap.org, so the tests neither depend on nor hammer it: a TileJSON whose
 * tiles are empty, an empty sprite, and a blank image for the shaded relief.
 */
export async function stubBasemap(page: Page): Promise<void> {
  await page.route(/tiles\.openfreemap\.org/, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/planet') {
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          tilejson: '3.0.0',
          tiles: ['https://tiles.openfreemap.org/planet/test/{z}/{x}/{y}.pbf'],
          minzoom: 0,
          maxzoom: 14,
        }),
      });
    }
    if (url.pathname.endsWith('.pbf')) {
      return route.fulfill({contentType: 'application/x-protobuf', body: Buffer.alloc(0)});
    }
    if (url.pathname.endsWith('.json')) {
      return route.fulfill({contentType: 'application/json', body: '{}'});
    }
    return route.fulfill({contentType: 'image/png', body: PNG});
  });
}
