/**
 * Regenerates src/basemap/liberty.json – the OpenFreeMap style drawn below the orienteering map.
 *
 * Stored as OpenFreeMap publishes it; basemap.ts adapts it to the app (zooms, fonts, names). The
 * file is committed, so the build does not depend on openfreemap.org and a style change upstream
 * reaches the site only through a reviewed update.
 *
 * Usage: npm run fetch-basemap
 */
import {writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';

const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';
const OUTPUT = join(dirname(import.meta.dirname), 'src', 'basemap', 'liberty.json');

const response = await fetch(STYLE_URL);
if (!response.ok) {
  throw new Error(`OpenFreeMap returned ${response.status} ${response.statusText}`);
}
const style = await response.json();
if (style.version !== 8 || !Array.isArray(style.layers) || style.layers.length === 0) {
  throw new Error('OpenFreeMap returned no style – refusing to overwrite the existing file');
}
writeFileSync(OUTPUT, `${JSON.stringify(style, null, 2)}\n`);
console.log(`${style.layers.length} layers -> ${OUTPUT}`);
