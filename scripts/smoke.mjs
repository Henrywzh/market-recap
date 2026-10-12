// Opens every view of the built site (dist/) in headless Chrome and fails if
// any page throws, logs an error, renders nothing, or prints NaN / undefined.
// Unit tests cover the browser-side maths; this covers what a reader sees.
//
//   node scripts/smoke.mjs [dist]        (make smoke)
//
// Uses the Chrome already installed (GitHub's runners carry one) through
// playwright-core, so no browser is downloaded.

import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, resolve } from 'node:path';
import { chromium } from 'playwright-core';
import { VIEWS } from '../web/js/routes.js';

const ROOT = resolve(process.argv[2] || 'dist');
const SETTLE_MS = 600;
const RENDER_WAIT_MS = 8000;
const PAGE_TIMEOUT_MS = 30000;
const MIN_TEXT = 120;
// The last: app.js's sentence for a view that failed to load or render.
const BAD_TEXT = /\bNaN\b|\bundefined\b|\[object Object\]|is unavailable: .*Run the refresh command/;
const TYPES = {
  '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
  '.woff2': 'font/woff2', '.txt': 'text/plain',
};

function serve(root) {
  const server = createServer(async (req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname));
    let file = join(root, path);
    if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
    try {
      if ((await stat(file)).isDirectory()) file = join(file, 'index.html');
      const body = await readFile(file);
      res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' }).end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok(server)));
}

async function artifact(name) {
  try {
    const text = await readFile(join(ROOT, 'artifacts', `${name}.json`), 'utf8');
    const parsed = JSON.parse(text);
    return parsed.data || parsed;
  } catch {
    return null;
  }
}

// Every view, plus the arguments that change what a page draws: the largest
// names, a share class typed the exchange's way, a fund, an index, and each
// theme.
async function routes() {
  const valuation = await artifact('valuation');
  const themes = await artifact('themes');
  const top = (valuation?.rows || []).filter((r) => r.weight !== undefined)
    .sort((a, b) => (b.weight || 0) - (a.weight || 0)).slice(0, 6).map((r) => r.ticker);
  const tickers = [...new Set([...top, 'BRK.B', 'SPY', '^GSPC'])];
  const out = VIEWS.filter((v) => !v.takesArg).map((v) => v.id);
  out.push('kshape', 'kshape/cruise', 'sizek', 'sizek/uk', 'valuation', 'technicals/SPY', 'trade/SPY', 'dcf', 'chain/NVDA', 'chain/000660.KS', 'chain/8035.T');
  tickers.forEach((t) => out.push(`ticker/${encodeURIComponent(t)}`));
  (themes?.groups || []).forEach((g) => out.push(`themes/${g.key.toUpperCase()}`));
  return out;
}

const server = await serve(ROOT);
const base = `http://127.0.0.1:${server.address().port}/`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const problems = [];
let current = '';
page.on('pageerror', (err) => problems.push(`${current}: page error: ${err.message}`));
// A missing file is judged by its response below; Chrome's own "Failed to
// load resource" line would count it twice and cannot say which file.
page.on('console', (msg) => {
  if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) {
    problems.push(`${current}: console.error: ${msg.text().slice(0, 300)}`);
  }
});
// The build's own files only. /api/ is the Cloudflare Function behind live
// quotes, absent from a static server; a fund or an index has no event file
// by design, and the page says so.
const OPTIONAL = [/\/api\//, /\/artifacts\/events\/[^/]+\.json$/];
page.on('response', (res) => {
  const url = res.url();
  if (res.status() >= 400 && url.startsWith(base) && !OPTIONAL.some((re) => re.test(url))) {
    problems.push(`${current}: ${res.status()} for ${url.slice(base.length - 1)}`);
  }
});
page.on('requestfailed', (req) => {
  const url = req.url();
  if (url.startsWith(base) && !OPTIONAL.some((re) => re.test(url))) problems.push(`${current}: request failed: ${url.slice(base.length - 1)}`);
});

const list = await routes();
await page.goto(base, { waitUntil: 'networkidle', timeout: PAGE_TIMEOUT_MS });
for (const route of list) {
  current = route;
  await page.evaluate((hash) => { window.location.hash = hash; }, route);
  await page.waitForLoadState('networkidle', { timeout: PAGE_TIMEOUT_MS }).catch(() => {});
  // A heavy view (heat maps, a ticker's charts) can still be drawing after
  // the network goes quiet: wait for its text, up to RENDER_WAIT_MS, before
  // judging it empty -- a fixed pause flagged a different page each run.
  await page.waitForFunction((min) => ((document.querySelector('main') || document.body).innerText || '').trim().length >= min,
    MIN_TEXT, { timeout: RENDER_WAIT_MS }).catch(() => {});
  await page.waitForTimeout(SETTLE_MS);
  const text = await page.evaluate(() => (document.querySelector('main') || document.body).innerText);
  if (text.trim().length < MIN_TEXT) problems.push(`${route}: rendered almost nothing (${text.trim().length} characters)`);
  const bad = text.match(BAD_TEXT);
  if (bad) {
    const at = text.indexOf(bad[0]);
    problems.push(`${route}: shows "${bad[0]}" in "${text.slice(Math.max(0, at - 60), at + 40).replace(/\s+/g, ' ')}"`);
  }
}
await browser.close();
server.close();

console.log(`smoke: ${list.length} pages opened from ${ROOT}`);
// One missing file shows as a response and a failed request: report it once.
const unique = [...new Set(problems.map((p) => p.replace(/: (?:404 for|request failed:) /, ': missing ')))];
problems.length = 0;
problems.push(...unique);
if (problems.length) {
  console.error(`smoke: ${problems.length} problem(s)`);
  problems.forEach((p) => console.error(`  - ${p}`));
  process.exit(1);
}
console.log('smoke: no errors');
