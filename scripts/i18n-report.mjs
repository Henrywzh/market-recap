// What the Chinese page still shows in English: opens every view of the built
// site (dist/) with ?lang=zh&i18n=report, opens its folds, and lists each
// untranslated string with how often and where it appeared.
//
//   node scripts/i18n-report.mjs [dist] [view ...] > report.json

import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, resolve } from 'node:path';
import { chromium } from 'playwright-core';
import { VIEWS } from '../web/js/routes.js';

const ROOT = resolve(process.argv[2] || 'dist');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };

function serve(root) {
  const server = createServer(async (req, res) => {
    let file = join(root, normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)));
    try {
      if ((await stat(file)).isDirectory()) file = join(file, 'index.html');
      res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' }).end(await readFile(file));
    } catch { res.writeHead(404).end(); }
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok(server)));
}

const requested = process.argv.slice(3);
const views = requested.length ? requested
  : ['overview', ...VIEWS.filter((v) => v.id !== 'overview').filter((v) => !v.takesArg).map((v) => v.id), 'sectors', 'themes', 'kshape', 'sizek', 'valuation', 'technicals/SPY',
    'movecheck/SPY', 'trade/SPY', 'dcf', 'ticker/NVDA', 'ticker/SPY', 'chain/NVDA', 'sectors/XLK', 'themes/SEMIS'];
const server = await serve(ROOT);
const base = `http://127.0.0.1:${server.address().port}/?lang=zh&i18n=report#rates`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
await page.goto(base, { waitUntil: 'networkidle' });
const all = new Map();
const errors = [];
let current = '';
page.on('pageerror', (err) => errors.push(`${current}: ${err.message}`));
page.on('console', (msg) => { if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) errors.push(`${current}: ${msg.text().slice(0, 200)}`); });
for (const view of views) {
  current = view;
  await page.evaluate((hash) => { window.__i18nMisses?.clear(); window.location.hash = hash; }, view);
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1500);
  // Folds and view switches hold text too: open every fold, then click each switch button once.
  await page.evaluate(async () => {
    document.querySelectorAll('details').forEach((d) => { d.open = true; });
    const buttons = [...document.querySelectorAll('#main .period-switch button, #main .view-switch button, #main [role=tab]')].slice(0, 60);
    for (const b of buttons) { b.click(); await new Promise((r) => setTimeout(r, 60)); }
  });
  await page.waitForTimeout(800);
  const misses = await page.evaluate(() => [...(window.__i18nMisses || new Map()).entries()]);
  for (const [text, count] of misses) {
    const entry = all.get(text) || { count: 0, views: new Set() };
    entry.count += count; entry.views.add(view.split('/')[0]);
    all.set(text, entry);
  }
  process.stderr.write(`${view}: ${misses.length}\n`);
}
await browser.close();
server.close();
const out = [...all.entries()].map(([text, e]) => ({ text, count: e.count, views: [...e.views] }))
  .sort((a, b) => b.views.length - a.views.length || b.count - a.count);
errors.forEach((e) => process.stderr.write(`ERROR ${e}\n`));
process.stdout.write(JSON.stringify(out, null, 1));
