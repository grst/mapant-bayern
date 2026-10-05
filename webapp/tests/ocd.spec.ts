import {expect, test, type Page} from '@playwright/test';
// The reference reader for the format, used here to check the writer against something that is not
// itself. AGPL, so it stays a test dependency and is never bundled into the app.
import {ocadToGeoJson, readOcad} from 'ocad2geojson';
import {serveArchive} from './archive';
import {stubBasemap} from './basemap';

async function stubTiles(page: Page): Promise<void> {
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
    'base64',
  );
  await stubBasemap(page);
  await page.route(/tiles\.mapterhorn\.com/, (route) =>
    route.fulfill({status: 200, contentType: 'image/png', body: png}),
  );
  // The map's archive is not part of the built site, so it is served from the fixture, which
  // covers an A4 page at 1:4000 around Immenstadt and nothing else -- outside it the archive has
  // no tiles, exactly as the real one has none outside the mapped area.
  await serveArchive(page);
}

async function openPrintPanel(page: Page): Promise<void> {
  await page.goto('/#map=15/47.5635/10.2142&layers=l&lang=en');
  await expect(page.locator('#map canvas').first()).toBeVisible();
  await page.getByRole('button', {name: 'Export as PDF'}).first().click();
  // The fixture covers an A4 page at 1:4000, which is the smallest scale on offer.
  await page.selectOption('.print-panel-body select', '4000');
}

test('exports the print area as an OCAD file built on the ISOM symbol set', async ({page}, testInfo) => {
  await stubTiles(page);
  await openPrintPanel(page);

  const downloadPromise = page.waitForEvent('download', {timeout: 120_000});
  await page.locator('.print-export-ocd').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('mapant-germany_1-4000.ocd');

  const file = testInfo.outputPath('export.ocd');
  await download.saveAs(file);

  const ocad = await readOcad(file);

  // Version 12 is what OCAD 12 and 2018 both open, and what Mapper reads without a warning.
  expect(ocad.header.version).toBe(12);
  // The symbol set and its colours come from the template untouched.
  expect(ocad.symbols.length).toBeGreaterThan(150);
  expect(ocad.colors.length).toBeGreaterThan(30);

  // Real content: contours, vegetation and cliffs all reach the file.
  expect(ocad.objects.length).toBeGreaterThan(100);
  // The package declares two different TObject types and the one it puts on `objects` is the
  // GeoJSON-side one, which has no symbol number; the reader's records do carry it.
  const objects = ocad.objects as unknown as {sym: number}[];
  const symbols = new Set(objects.map((object) => object.sym));
  expect(symbols).toContain(101000); // contour
  expect(symbols).toContain(102000); // index contour
  expect([...symbols].some((symbol) => symbol === 201000 || symbol === 202000)).toBe(true); // cliff
  expect([...symbols].some((symbol) => Math.floor(symbol / 1000) >= 401 && Math.floor(symbol / 1000) <= 410)).toBe(true); // vegetation
  // The OpenStreetMap shapes, in ISOM 2017-2 as mapant-nf translated them.
  expect(symbols).toContain(521000); // building
  expect([...symbols].some((symbol) => symbol >= 502000 && symbol <= 506000)).toBe(true); // roads and paths

  // Every object references a symbol the file actually defines; a dangling reference is what OCAD
  // reports as a damaged object.
  const defined = new Set(ocad.symbols.map((symbol) => symbol.symNum));
  for (const object of objects) {
    expect(defined).toContain(object.sym);
  }

  // Georeferenced in the LiDAR's own system: 63005 is ETRS89 / UTM zone 32N, and the reference
  // point is the centre of the print area, so the map lands where the terrain is.
  const scalePar = JSON.stringify(ocad.parameterStrings['1039']);
  expect(scalePar).toContain('"code":"i","value":"63005"');
  expect(scalePar).toContain('"code":"r","value":"1"');
  expect(scalePar).toContain('"code":"m","value":"4000"');
  const easting = Number(/"code":"x","value":"(-?\d+)"/.exec(scalePar)?.[1]);
  const northing = Number(/"code":"y","value":"(-?\d+)"/.exec(scalePar)?.[1]);
  expect(easting).toBeGreaterThan(590_000);
  expect(easting).toBeLessThan(595_000);
  expect(northing).toBeGreaterThan(5_265_000);
  expect(northing).toBeLessThan(5_272_000);

  // And it converts back to geometry, which is the reader's own check that the records are sound.
  const geojson = ocadToGeoJson(ocad);
  expect(geojson.features.length).toBeGreaterThan(100);

  // Every coordinate has to land inside the page, which is the check that a georeferenced file is
  // actually georeferenced rather than merely claiming to be. An A4 page at 1:4000 is 840 x 1160 m,
  // so nothing may be more than a kilometre from the reference point; encoding a negative
  // coordinate the wrong way puts it 8.4 million units out and passes every other assertion here.
  // Folded rather than spread into Math.min: there are hundreds of thousands of coordinates, and
  // Math.min(...array) blows the call stack well before that.
  const extent = {minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity};
  for (const object of objects as unknown as {coordinates: [number, number][]}[]) {
    for (const [x, y] of object.coordinates) {
      // Paper units are hundredths of a millimetre, so this is metres of ground at 1:4000.
      const east = ((x / 100) * 4000) / 1000;
      const north = ((y / 100) * 4000) / 1000;
      extent.minX = Math.min(extent.minX, east);
      extent.maxX = Math.max(extent.maxX, east);
      extent.minY = Math.min(extent.minY, north);
      extent.maxY = Math.max(extent.maxY, north);
    }
  }
  expect(extent.minX).toBeGreaterThan(-600);
  expect(extent.maxX).toBeLessThan(600);
  expect(extent.minY).toBeGreaterThan(-800);
  expect(extent.maxY).toBeLessThan(800);
  // ...and both sides of the origin are actually used, or the bounds above prove nothing.
  expect(extent.minX).toBeLessThan(0);
  expect(extent.minY).toBeLessThan(0);
});

test('an area with no tiles under it says so rather than saving an empty file', async ({page}) => {
  await stubTiles(page);
  // Far outside the fixture: the archive has no tile there.
  await page.goto('/#map=15/47.9000/11.5000&layers=l&lang=en');
  await expect(page.locator('#map canvas').first()).toBeVisible();
  await page.getByRole('button', {name: 'Export as PDF'}).first().click();

  const download = page.waitForEvent('download', {timeout: 5_000}).catch(() => null);
  await page.locator('.print-export-ocd').click();

  await expect(page.locator('.toast')).toContainText('no map data');
  expect(await download).toBeNull();
});
