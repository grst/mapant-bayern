import {readFileSync} from 'node:fs';
import {expect, test, type Page} from '@playwright/test';

/** Same stubs as the smoke tests: the app is what is under test, not the tile hosts. */
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
  await page.goto('/#map=14/47.5635/10.2142&layers=l&lang=en');
  await expect(page.locator('#map canvas')).toBeVisible();
  await page.getByRole('button', {name: 'Export as PDF'}).first().click();
});

test('states the ground area a print will cover, per scale and format', async ({page}) => {
  // A4 portrait at 1:10 000: 210 mm x 290 mm of paper.
  await expect(page.locator('.print-area')).toHaveText('Covers 2.1 × 2.9 km');

  await page.locator('.print-orientation button[data-orientation="landscape"]').click();
  await page.selectOption('.print-panel-body select', '7500');
  await expect(page.locator('.print-area')).toHaveText('Covers 2.2 × 1.5 km');
});

test('exports an A4 PDF of the centred area at 300 dpi', async ({page}, testInfo) => {
  const downloadPromise = page.waitForEvent('download', {timeout: 120_000});
  await page.locator('.print-export').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('mapant-bayern_1-10000.pdf');

  const file = testInfo.outputPath('export.pdf');
  await download.saveAs(file);
  const pdf = readFileSync(file).toString('latin1');

  // A4 portrait in PDF points (210 x 297 mm).
  expect(pdf).toMatch(/\/MediaBox\s*\[0 0 595\.\d+ 841\.\d+\]/);
  // 210 mm x 290 mm of map at 300 dpi, losslessly compressed.
  expect(pdf).toMatch(/\/Width 2481\b/);
  expect(pdf).toMatch(/\/Height 342[45]\b/);
  expect(pdf).toContain('/Filter /FlateDecode');
});
