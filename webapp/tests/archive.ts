import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import type {Page} from '@playwright/test';

/**
 * A small real archive around Immenstadt, cut from a mapant-nf run; see tests/fixtures/README.md.
 * Real tiles rather than synthetic ones, because what the export has to get right is exactly what
 * mapant-nf puts in them.
 */
export const FIXTURE_ARCHIVE = join(import.meta.dirname, 'fixtures', 'mapant.pmtiles');

/** Bavaria's archive in the built app (MAPANT_TILES_BASE and states.ts). */
export const ARCHIVE_URL = /pub-77421d3fb5d34fc09d670e81f6c2dadf\.r2\.dev\/mapant\.pmtiles/;

/** Every other archive in the bucket: the other states'. */
const OTHER_ARCHIVES = /pub-77421d3fb5d34fc09d670e81f6c2dadf\.r2\.dev\/(?!mapant\.pmtiles)[^/]+\.pmtiles/;

/**
 * Answers the app's range requests for the archive from the fixture, as a static host does: a
 * 206 with the bytes asked for. PMTiles reads nothing but ranges.
 */
export async function serveArchive(page: Page, file = FIXTURE_ARCHIVE): Promise<void> {
  const bytes = readFileSync(file);
  // The other states' archives, as if not uploaded yet: the app leaves them out.
  await page.route(OTHER_ARCHIVES, (route) => route.fulfill({status: 404, body: ''}));
  await page.route(ARCHIVE_URL, (route) => {
    const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers()['range'] ?? '');
    const start = range ? Number(range[1]) : 0;
    const end = Math.min(range?.[2] ? Number(range[2]) : bytes.length - 1, bytes.length - 1);
    return route.fulfill({
      status: range ? 206 : 200,
      body: bytes.subarray(start, end + 1),
      headers: {
        'Content-Type': 'application/octet-stream',
        'Accept-Ranges': 'bytes',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Expose-Headers': 'ETag, Content-Range',
        ETag: '"fixture"',
        ...(range ? {'Content-Range': `bytes ${start}-${end}/${bytes.length}`} : {}),
      },
    });
  });
}
