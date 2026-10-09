import {readFileSync} from 'node:fs';
import {inflateSync} from 'node:zlib';
import {expect, test, type Page} from '@playwright/test';
import {serveArchive} from './archive';
import {stubBasemap} from './basemap';

/** Same stubs as the smoke tests: the app is what is under test, not the tile hosts. */
async function stubTiles(page: Page, terrainZooms?: number[]): Promise<void> {
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
    'base64',
  );
  await stubBasemap(page);
  await page.route(/tiles\.mapterhorn\.com/, (route) => {
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

/** The PDF's content streams, inflated: what is drawn on the page. */
function pageContent(pdf: Buffer): string {
  const text = pdf.toString('latin1');
  const streams: string[] = [];
  for (const match of text.matchAll(/\/FlateDecode[^>]*>>\s*stream\r?\n/g)) {
    const start = match.index! + match[0].length;
    const end = text.indexOf('endstream', start);
    try {
      streams.push(inflateSync(pdf.subarray(start, end)).toString('latin1'));
    } catch {
      // An image's samples, or a stream cut short by the search: not page content.
    }
  }
  return streams.join('\n');
}

test('states the ground area a print will cover, per scale and format', async ({page}) => {
  await stubTiles(page);
  await openPrintPanel(page, 'l');

  // A4 portrait at 1:10 000: 210 mm x 290 mm of paper.
  await expect(page.locator('.pdf-panel .print-area')).toHaveText('Covers 2.1 × 2.9 km');

  await page.locator('.pdf-panel .print-orientation button[data-orientation="landscape"]').click();
  await page.selectOption('.pdf-panel select', '7500');
  await expect(page.locator('.pdf-panel .print-area')).toHaveText('Covers 2.2 × 1.5 km');
});

test('exports the orienteering map as vectors, not as a picture of it', async ({page}, testInfo) => {
  await stubTiles(page);
  await serveArchive(page);
  await openPrintPanel(page, 'l,p');
  // The fixture covers an A4 page at 1:4000.
  await page.selectOption('.pdf-panel select', '4000');

  const downloadPromise = page.waitForEvent('download', {timeout: 120_000});
  await page.locator('.pdf-panel .print-export').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('mapant-germany_1-4000.pdf');

  const file = testInfo.outputPath('export.pdf');
  await download.saveAs(file);
  const pdf = readFileSync(file);
  const text = pdf.toString('latin1');

  // A4 portrait in PDF points (210 x 297 mm).
  expect(text).toMatch(/\/MediaBox\s*\[0 0 595\.\d+ 841\.\d+\]/);
  // No image without hill shading: the map is paths.
  expect(text).not.toContain('/Subtype /Image');
  const content = pageContent(pdf);
  // Contours in ISOM brown (#D15C00), stroked; the yellow of rough open land (#FFDD9B), filled.
  // Colour components are written to two decimals.
  expect(content).toMatch(/^0\.82 0\.36 0\.? RG$/m);
  expect(content).toMatch(/^1\.? 0\.87 0\.61 rg$/m);
  // Thousands of path segments, the deepest tiles' detail.
  expect(content.match(/ l\n/g)?.length ?? 0).toBeGreaterThan(10_000);
});

/**
 * MapLibre picks tile levels from the zoom alone, and the hill shading's map sits at the zoom of
 * its scale, so the print style declares the terrain tiles smaller than they are to get the finest
 * ones: at 1:10 000 the DEM is read at z16 instead of the z14 a 96 dpi view would settle for. The
 * shading is the page's one image.
 */
test('lays the hill shading over the map as an image of the terrain at paper density', async ({page}, testInfo) => {
  const zooms: number[] = [];
  await stubTiles(page, zooms);
  await openPrintPanel(page, 'h');

  // Once the live map has its own tiles, only the print map's requests are left.
  await page.waitForLoadState('networkidle');
  zooms.length = 0;
  const downloadPromise = page.waitForEvent('download', {timeout: 300_000});
  await page.locator('.pdf-panel .print-export').click();

  // Counted by level rather than in total: the live map may still be fetching its own tiles on a
  // busy machine, and those say nothing about the print.
  await expect.poll(() => zooms.filter((z) => z === 16).length, {timeout: 60_000}).toBeGreaterThan(12);
  expect(Math.max(...zooms)).toBe(16);

  const file = testInfo.outputPath('shaded.pdf');
  await (await downloadPromise).saveAs(file);
  const text = readFileSync(file).toString('latin1');
  // 210 mm x 290 mm of shading at 200 dpi.
  expect(text).toMatch(/\/Width 1654\b/);
  expect(text).toMatch(/\/Height 2283\b/);
});
