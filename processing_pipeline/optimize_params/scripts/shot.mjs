// Screenshot the mapant viewer once MapLibre has drawn everything.
//   node shot.mjs <url> <out.png> [size]
// Uses the webapp's Playwright with the system Chromium.
import {createRequire} from 'module';
const require = createRequire('/workspace/webapp/package.json');
const {chromium} = require('playwright');

const [url, out, size = '1000'] = process.argv.slice(2);
const browser = await chromium.launch({
  executablePath: '/usr/local/bin/chromium',
  args: ['--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--no-sandbox'],
});
const page = await browser.newPage({viewport: {width: +size, height: +size}});
page.on('pageerror', (e) => console.error('pageerror', e.message));
await page.goto(url);
await page.waitForFunction(() => window.map && typeof window.map.loaded === 'function' && window.map.loaded() && window.map.areTilesLoaded(), null,
  {timeout: 120000, polling: 500});
await page.evaluate(() => new Promise((r) => { if (window.map.loaded()) r(); else window.map.once('idle', r); }));
await page.evaluate(() => { for (const el of document.querySelectorAll('.legend,.maplibregl-control-container')) el.remove(); });
await page.waitForTimeout(500);
await page.screenshot({path: out});
await browser.close();
