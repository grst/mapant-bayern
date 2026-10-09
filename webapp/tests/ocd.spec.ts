import {readFileSync, writeFileSync} from 'node:fs';
import {expect, test, type Page, type TestInfo} from '@playwright/test';
import {unzipSync} from 'fflate';
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

async function openOcdPanel(page: Page): Promise<void> {
  await page.goto('/#map=15/47.5635/10.2142&layers=l&lang=en');
  await expect(page.locator('#map canvas').first()).toBeVisible();
  await page.getByRole('button', {name: 'Export as OCAD file'}).first().click();
  // The fixture covers an A4 page at 1:4000, which is the smallest scale on offer.
  await page.selectOption('.ocd-panel select', '4000');
}

/** Exports with the panel as it is set, and returns the download. */
async function exportFile(page: Page, testInfo: TestInfo): Promise<{name: string; path: string}> {
  const downloadPromise = page.waitForEvent('download', {timeout: 120_000});
  await page.locator('.ocd-panel .print-export').click();
  const download = await downloadPromise;
  const path = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(path);
  return {name: download.suggestedFilename(), path};
}

test('exports the print area as an OCAD file built on the ISOM symbol set', async ({page}, testInfo) => {
  await stubTiles(page);
  await openOcdPanel(page);

  // Without a background map, the OCD file alone.
  const {name, path: file} = await exportFile(page, testInfo);
  expect(name).toBe('mapant-germany_1-4000.ocd');

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
  // Cliffs as plain lines: the impassable cliff's top line (201.3) rather than 201 with its tags.
  expect([...symbols].some((symbol) => symbol === 201003 || symbol === 202000)).toBe(true);
  expect(symbols).not.toContain(201000);
  expect([...symbols].some((symbol) => Math.floor(symbol / 1000) >= 401 && Math.floor(symbol / 1000) <= 410)).toBe(true); // vegetation
  // The OpenStreetMap shapes, in ISOM 2017-2 as mapant-nf translated them.
  expect(symbols).toContain(521000); // building
  expect([...symbols].some((symbol) => symbol >= 502000 && symbol <= 506000)).toBe(true); // roads and paths

  // Every object references a symbol the file actually defines; a dangling reference is what OCAD
  // reports as a damaged object.
  const defined = new Set(ocad.symbols.map((symbol) => symbol.symNum));
  // One assertion over all of them: an expect() per object takes longer than the export.
  expect([...symbols].filter((symbol) => !defined.has(symbol))).toEqual([]);

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
  await page.getByRole('button', {name: 'Export as OCAD file'}).first().click();

  const download = page.waitForEvent('download', {timeout: 5_000}).catch(() => null);
  await page.locator('.ocd-panel .print-export').click();

  await expect(page.locator('.toast')).toContainText('no map data');
  expect(await download).toBeNull();
});

test('writes only the feature groups that are ticked', async ({page}, testInfo) => {
  await stubTiles(page);
  await openOcdPanel(page);
  for (const group of ['vegetation', 'landforms', 'cliffs', 'water', 'paths', 'manmade', 'private']) {
    await page.locator(`input[data-objects="${group}"]`).uncheck();
  }

  const ocad = await readOcad((await exportFile(page, testInfo)).path);
  const symbols = new Set((ocad.objects as unknown as {sym: number}[]).map((object) => Math.floor(object.sym / 1000)));
  expect([...symbols].sort()).toEqual([101, 102, 103]);
});

test('bundles a georeferenced background map with the OCD file that opens it', async ({page}, testInfo) => {
  await stubTiles(page);
  await openOcdPanel(page);
  // Vegetation as a background map instead of as objects.
  await page.locator('input[data-objects="vegetation"]').uncheck();
  await page.locator('.ocd-background summary').click();
  await page.locator('input[data-background="vegetation"]').check();

  const {name, path} = await exportFile(page, testInfo);
  expect(name).toBe('mapant-germany_1-4000.zip');
  const files = unzipSync(readFileSync(path));
  expect(Object.keys(files).sort()).toEqual([
    'mapant-germany_1-4000.ocd',
    'mapant-germany_1-4000_background.pgw',
    'mapant-germany_1-4000_background.png',
  ]);

  // A PNG of about an A4 page at 300 dpi.
  const png = Buffer.from(files['mapant-germany_1-4000_background.png']);
  expect(png.subarray(1, 4).toString()).toBe('PNG');
  expect(png.readUInt32BE(16)).toBeGreaterThan(2400);
  expect(png.readUInt32BE(20)).toBeGreaterThan(3300);

  // The world file: pixels of 0.0847 mm at 1:4000, north up, the top left corner west and north
  // of the georeferencing point in UTM 32N.
  const world = new TextDecoder().decode(files['mapant-germany_1-4000_background.pgw']).trim().split('\n').map(Number);
  expect(world[0]).toBeCloseTo(0.33867, 4);
  expect(world.slice(1, 3)).toEqual([0, 0]);
  expect(world[3]).toBeCloseTo(-0.33867, 4);
  expect(world[4]).toBeGreaterThan(590_000);
  expect(world[5]).toBeLessThan(5_272_000);

  const ocdPath = testInfo.outputPath('bundled.ocd');
  writeFileSync(ocdPath, files['mapant-germany_1-4000.ocd']);
  const ocad = await readOcad(ocdPath);
  // The OCD names the image beside it, in the type-8 string OCAD and Mapper read background maps from.
  const background = JSON.stringify(ocad.parameterStrings['8']);
  expect(background).toContain('"_first":"mapant-germany_1-4000_background.png"');
  expect(background).toContain('"code":"u","value":"0.0846666667"');
  // And the vegetation is not among the objects.
  const symbols = (ocad.objects as unknown as {sym: number}[]).map((object) => Math.floor(object.sym / 1000));
  expect(symbols.some((symbol) => symbol >= 401 && symbol <= 410)).toBe(false);
  expect(symbols).toContain(101);
});
