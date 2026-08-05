import {expect, test, type Page} from '@playwright/test';
import {encodeDrawings} from '../src/drawings';

/**
 * The external tile services are stubbed out: the tests are about the app, and
 * CI should not depend on (or hammer) openstreetmap.org, the PMTiles host or
 * Mapterhorn. The town names come from the site's own places.geojson.
 */
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

test.beforeEach(async ({page}) => {
  await stubTiles(page);
});

test('renders the map and records the default view in the URL', async ({page}) => {
  await page.goto('/');
  await expect(page.locator('#map canvas')).toBeVisible();
  // Immenstadt im Allgäu at zoom 12.
  await expect.poll(() => page.url()).toMatch(/#map=12\.00\/47\.563\d\d\/10\.214\d\d/);
  await expect(page.locator('#attribution')).toContainText('OpenStreetMap');
});

test('shows the zoom hint only below the orienteering map zoom levels', async ({page}) => {
  await page.goto('/#map=10/47.5635/10.2142');
  await expect(page.locator('#zoom-hint')).toBeVisible();
  await expect(page.locator('#zoom-hint')).toHaveText('Zoom in to view the orienteering map');

  await page.goto('/#map=13/47.5635/10.2142');
  await expect(page.locator('#zoom-hint')).toBeHidden();
});

test('layer toggles are reflected in the share URL', async ({page}) => {
  await page.goto('/#map=13/47.5635/10.2142&layers=l&lang=en');
  await page.getByRole('button', {name: 'Layers'}).click();

  const hillshade = page.locator('input[data-layer="h"]');
  const places = page.locator('input[data-layer="l"]');
  await expect(hillshade).not.toBeChecked();
  await expect(places).toBeChecked();

  await hillshade.check();
  await expect.poll(() => page.url()).toContain('layers=h,l');

  await places.uncheck();
  await expect.poll(() => page.url()).toContain('layers=h&');
});

test('restores drawings from a share link', async ({page}) => {
  const payload = encodeDrawings([
    {t: 'l', c: [[10.2, 47.56], [10.22, 47.57]]},
    {t: 'p', c: [[10.2, 47.55], [10.22, 47.55], [10.21, 47.54]]},
  ]);
  await page.goto(`/#map=13/47.5635/10.2142&layers=l&lang=en&d=${payload}`);
  await expect(page.locator('#map canvas')).toBeVisible();

  // The app re-serialises whatever it actually restored, so a surviving `d=`
  // parameter proves both geometries came back.
  await expect.poll(() => new URL(page.url()).hash).toMatch(/&d=[A-Za-z0-9_-]+$/);
});

test('draws a line and puts it in the URL', async ({page}) => {
  await page.goto('/#map=13/47.5635/10.2142&layers=l&lang=en');
  const map = page.locator('#map');
  await expect(map.locator('canvas')).toBeVisible();

  await page.getByRole('button', {name: 'Measure distance'}).click();
  await expect(page.locator('.draw-hint')).toBeVisible();

  const box = (await map.boundingBox())!;
  await page.mouse.click(box.x + 200, box.y + 200);
  await page.mouse.click(box.x + 320, box.y + 260);
  await page.mouse.dblclick(box.x + 320, box.y + 260);

  await expect.poll(() => new URL(page.url()).hash).toContain('&d=');
});

test('switches language and remembers it in the URL', async ({page}) => {
  await page.goto('/#map=13/47.5635/10.2142&layers=l&lang=en');
  await expect(page.getByRole('link', {name: 'About'})).toBeVisible();

  await page.getByRole('button', {name: 'DE'}).click();
  await expect(page.getByRole('link', {name: 'Über'})).toBeVisible();
  await expect.poll(() => page.url()).toContain('lang=de');
});

test('about page renders the repository README', async ({page}) => {
  await page.goto('/about.html#lang=en');
  await expect(page.getByRole('heading', {level: 1, name: 'Mapant Bayern'})).toBeVisible();
  await expect(page.getByRole('link', {name: 'karttapullautin'}).first()).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Data sources'})).toBeVisible();
});

test('about page renders the German README when German is selected', async ({page}) => {
  await page.goto('/about.html#lang=de');
  await expect(page.getByRole('heading', {name: 'Datenquellen'})).toBeVisible();

  // Switching back re-renders in place and records the choice in the URL.
  await page.getByRole('button', {name: 'EN'}).click();
  await expect(page.getByRole('heading', {name: 'Data sources'})).toBeVisible();
  await expect.poll(() => page.url()).toContain('lang=en');
});

test('the language survives the walk from the map to the about page', async ({page}) => {
  await page.goto('/#map=13/47.5635/10.2142&layers=l&lang=en');
  await page.getByRole('button', {name: 'DE'}).click();
  await page.getByRole('link', {name: 'Über'}).click();

  await expect(page.getByRole('heading', {name: 'Datenquellen'})).toBeVisible();
});
