import {expect, test, devices, type Page} from '@playwright/test';

/**
 * Touch gestures on a phone-sized viewport. OpenLayers builds its default
 * interactions with `onFocusOnly: true`, which – because the map container has a
 * `tabindex` – used to swallow every gesture until something focused the map, so
 * the first swipe of a visit did nothing. See src/map.ts.
 */
test.use({...devices['Pixel 7']});

async function stubTiles(page: Page): Promise<void> {
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
    'base64',
  );
  await page.route(/tile\.openstreetmap\.org|tiles\.mapterhorn\.com/, (route) =>
    route.fulfill({status: 200, contentType: 'image/png', body: png}),
  );
  await page.route(/mapant-tiles\.orienteering-allgaeu\.de/, (route) => route.abort());
}

type Point = {x: number; y: number};

/**
 * Playwright's touchscreen can only tap, so the gestures go through the DevTools
 * protocol. `frames` are the successive positions of every finger involved.
 */
async function gesture(page: Page, frames: Point[][]): Promise<void> {
  const client = await page.context().newCDPSession(page);
  const points = (frame: Point[]) => frame.map((point, id) => ({...point, id}));
  await client.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: points(frames[0])});
  for (const frame of frames.slice(1)) {
    await client.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: points(frame)});
    // A frame's worth of pause: OpenLayers measures the drag speed to decide how
    // far to fling the map afterwards, and instant moves read as an infinite one.
    await page.waitForTimeout(16);
  }
  await client.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  await client.detach();
}

function steps(count: number, position: (fraction: number) => Point[]): Point[][] {
  return Array.from({length: count + 1}, (_, index) => position(index / count));
}

async function mapCentre(page: Page): Promise<Point> {
  const box = (await page.locator('#map').boundingBox())!;
  return {x: box.x + box.width / 2, y: box.y + box.height / 2};
}

/** The view the app has written to the URL: `#map=zoom/lat/lon`. */
async function view(page: Page): Promise<{zoom: number; lat: number; lon: number}> {
  const [zoom, lat, lon] = new URL(page.url()).hash
    .replace(/^#map=/, '')
    .split('&')[0]
    .split('/')
    .map(Number);
  return {zoom, lat, lon};
}

test.beforeEach(async ({page}) => {
  await stubTiles(page);
  await page.goto('/#map=13/47.5635/10.2142&layers=l&lang=en');
  await expect(page.locator('#map canvas')).toBeVisible();
});

test('the first swipe of a visit pans the map', async ({page}) => {
  const start = await mapCentre(page);
  const before = await view(page);

  await gesture(
    page,
    steps(12, (fraction) => [{x: start.x, y: start.y - 80 * fraction}]),
  );

  // The finger drags the map upwards, so the view moves south.
  await expect.poll(async () => (await view(page)).lat).toBeLessThan(before.lat - 0.005);
  expect((await view(page)).lon).toBeCloseTo(before.lon, 3);
});

test('the first pinch of a visit zooms the map', async ({page}) => {
  const start = await mapCentre(page);
  const before = await view(page);

  await gesture(
    page,
    steps(12, (fraction) => {
      const spread = 40 + 120 * fraction;
      return [
        {x: start.x - spread, y: start.y},
        {x: start.x + spread, y: start.y},
      ];
    }),
  );

  await expect.poll(async () => (await view(page)).zoom).toBeGreaterThan(before.zoom + 0.5);
});

test('the map still pans with the keyboard once it has the focus', async ({page}) => {
  const before = await view(page);
  await page.locator('#map').focus();
  await page.keyboard.press('ArrowUp');

  await expect.poll(async () => (await view(page)).lat).toBeGreaterThan(before.lat);
});
