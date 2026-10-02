// Screenshot the comparison app once both maps have drawn.
//   node compare_shot.mjs <url> <out.png> [width] [height] [json: {A:{v14,v12},B:{v14,v12}}]
import {createRequire} from 'module';
const require = createRequire('/workspace/webapp/package.json');
const {chromium} = require('playwright');

const [url, out, w = '1600', h = '900', sel = ''] = process.argv.slice(2);
const browser = await chromium.launch({
  executablePath: '/usr/local/bin/chromium',
  args: ['--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--no-sandbox'],
});
const page = await browser.newPage({viewport: {width: +w, height: +h}});
page.on('pageerror', (e) => console.error('pageerror', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.error('console', m.text()); });
await page.goto(url);
const ready = () => page.waitForFunction(() => ['A', 'B'].every((p) => {
  const m = window.panes?.[p]?.map;
  return m && m.loaded() && m.areTilesLoaded();
}), null, {timeout: 180000, polling: 500});
await ready();
if (sel) {
  await page.evaluate((s) => {
    for (const [p, v] of Object.entries(s)) {
      const P = window.panes[p];
      P.v14.value = v.v14; P.v12.value = v.v12; P.v14.onchange();
    }
  }, JSON.parse(sel));
  await page.waitForTimeout(1000);
  await ready();
}
await page.waitForTimeout(800);
await page.screenshot({path: out});
await browser.close();
