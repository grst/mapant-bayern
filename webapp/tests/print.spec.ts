import {readFileSync} from 'node:fs';
import {expect, test, type Page} from '@playwright/test';

/** Same stubs as the smoke tests: the app is what is under test, not the tile hosts. */
async function stubTiles(page: Page, terrainZooms?: number[]): Promise<void> {
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
    'base64',
  );
  await page.route(/tile\.openstreetmap\.org|tiles\.mapterhorn\.com/, (route) => {
    const zoom = /tiles\.mapterhorn\.com\/(\d+)\//.exec(route.request().url())?.[1];
    if (zoom) {
      terrainZooms?.push(Number(zoom));
    }
    return route.fulfill({status: 200, contentType: 'image/png', body: png});
  });
  await page.route(/mapant-tiles\.orienteering-allgaeu\.de/, (route) => route.abort());
}

/** Loads the map with the given layers and opens the print panel. */
async function openPrintPanel(page: Page, layers: string): Promise<void> {
  await page.goto(`/#map=14/47.5635/10.2142&layers=${layers}&lang=en`);
  // Every visible layer brings a canvas of its own.
  await expect(page.locator('#map canvas').first()).toBeVisible();
  await page.getByRole('button', {name: 'Export as PDF'}).first().click();
}

test('states the ground area a print will cover, per scale and format', async ({page}) => {
  await stubTiles(page);
  await openPrintPanel(page, 'l');

  // A4 portrait at 1:10 000: 210 mm x 290 mm of paper.
  await expect(page.locator('.print-area')).toHaveText('Covers 2.1 × 2.9 km');

  await page.locator('.print-orientation button[data-orientation="landscape"]').click();
  await page.selectOption('.print-panel-body select', '7500');
  await expect(page.locator('.print-area')).toHaveText('Covers 2.2 × 1.5 km');
});

test('exports an A4 PDF of the centred area at print density', async ({page}, testInfo) => {
  await stubTiles(page);
  await openPrintPanel(page, 'l');

  const downloadPromise = page.waitForEvent('download', {timeout: 120_000});
  await page.locator('.print-export').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('mapant-bayern_1-10000.pdf');

  const file = testInfo.outputPath('export.pdf');
  await download.saveAs(file);
  const pdf = readFileSync(file).toString('latin1');

  // A4 portrait in PDF points (210 x 297 mm).
  expect(pdf).toMatch(/\/MediaBox\s*\[0 0 595\.\d+ 841\.\d+\]/);
  // 210 mm x 290 mm of map at 600 dpi, losslessly compressed. One image pixel per
  // pixel of paper: at 1:10 000 that is 0.42 m of ground, which the z18 tiles fill.
  expect(pdf).toMatch(/\/Width 4961\b/);
  expect(pdf).toMatch(/\/Height 6850\b/);
  expect(pdf).toContain('/Filter /FlateDecode');
});

/**
 * The print map renders one canvas pixel per pixel of paper, which is what makes
 * OpenLayers pick a tile zoom level for the print rather than for the screen. The
 * terrain layer is the one whose tiles are plain URLs, so it is where that choice
 * can be observed: a 1:10 000 page asks for 0.64 m per pixel, so the DEM is read
 * at its finest level (z16) instead of the z14 a 96 dpi view would settle for.
 */
test('fetches tiles at the density of the paper, not of the screen', async ({page}) => {
  const zooms: number[] = [];
  await stubTiles(page, zooms);
  await openPrintPanel(page, 'h');

  // Once the live map has its own tiles, only the print map's requests are left.
  await page.waitForTimeout(500);
  zooms.length = 0;
  await page.locator('.print-export').click();

  // A page holds around fifty terrain tiles; a dozen is enough to see which level
  // they come from. The export is left to run on: compositing a 600 dpi page of
  // shaded relief takes minutes in a headless browser and the zoom level – all
  // this test is about – has been decided by now.
  await expect.poll(() => zooms.length, {timeout: 60_000}).toBeGreaterThan(12);
  expect([...new Set(zooms)]).toEqual([16]);
});
