// Opens every view of the built site (dist/) in headless Chrome and fails if
// any page throws, logs an error, renders nothing, or prints NaN / undefined.
// Unit tests cover the browser-side maths; this covers what a reader sees.
//
//   node scripts/smoke.mjs [dist]        (make smoke)
//   node scripts/smoke.mjs dist overview sectors positioning   (focused QA)
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
  out.push('sectors', 'kshape', 'kshape/cruise', 'sizek', 'sizek/uk', 'valuation', 'technicals/SPY', 'trade/SPY', 'dcf', 'chain/NVDA', 'chain/000660.KS', 'chain/8035.T');
  const sectors = await artifact('sectors');
  if (sectors?.sectors?.[0]) out.push(`sectors/${sectors.sectors[0].key}`);
  tickers.forEach((t) => out.push(`ticker/${encodeURIComponent(t)}`));
  (themes?.groups || []).forEach((g) => out.push(`themes/${g.key.toUpperCase()}`));
  return out;
}

const server = await serve(ROOT);
const base = `http://127.0.0.1:${server.address().port}/`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
// Simulate a returning reader who selected the now-retired light theme.
await page.addInitScript(() => { try { localStorage.setItem('mr-theme', 'light'); } catch { /* unavailable storage */ } });
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

const requested = process.argv.slice(3);
const knownRoutes = await routes();
const unknown = requested.filter((route) => !knownRoutes.includes(route));
if (unknown.length) throw new Error(`Unknown smoke views: ${unknown.join(', ')}`);
const list = knownRoutes.filter((route) => !requested.length || requested.includes(route));
if (!list.length) throw new Error('No known views selected for smoke testing');
await page.goto(base, { waitUntil: 'networkidle', timeout: PAGE_TIMEOUT_MS });
if (await page.locator('html').getAttribute('data-theme') !== 'dark') problems.push('Retired light preference was not migrated to dark');
if (await page.locator('#theme-select').count()) problems.push('Retired theme selector is still rendered');
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
  try {
    if (route === 'sectors') {
      for (const name of ['Industry & valuation', 'Rotation & sectors']) {
        await page.getByRole('tab', { name, exact: true }).click();
        const panel = page.getByRole('tabpanel', { name, exact: true });
        await panel.waitFor({ state: 'visible', timeout: RENDER_WAIT_MS });
        await page.waitForFunction((name) => {
          const button = [...document.querySelectorAll('.view-switch button')].find((b) => b.textContent === name);
          const panel = document.getElementById(button?.getAttribute('aria-controls'));
          return panel && panel.innerText.length > 120 && !panel.querySelector('.loading');
        }, name, { timeout: RENDER_WAIT_MS });
        if (BAD_TEXT.test(await panel.innerText())) throw new Error(`${name} shows invalid text`);
      }
    }
    if (route === 'rates') {
      // Each of the three views must draw its own content, not just switch on.
      for (const name of ['Treasury rates', 'CPI & macro', 'PPI · AI prices']) {
        await page.getByRole('tab', { name, exact: true }).click();
        const panel = page.getByRole('tabpanel', { name, exact: true });
        await panel.waitFor({ state: 'visible', timeout: RENDER_WAIT_MS });
        await page.waitForFunction((name) => {
          const button = [...document.querySelectorAll('.view-switch button')].find((b) => b.textContent === name);
          const panel = document.getElementById(button?.getAttribute('aria-controls'));
          return panel && panel.innerText.length > 120 && !panel.querySelector('.loading');
        }, name, { timeout: RENDER_WAIT_MS });
        if (BAD_TEXT.test(await panel.innerText())) throw new Error(`${name} shows invalid text`);
      }
    }
    if (route === 'positioning' && (await artifact('positioning'))?.index_put_call) {
      const pc = page.locator('.card').filter({ hasText: 'INDEX OPTIONS · PUT / CALL VOLUME' });
      for (const window of ['1D', '1W', '1M']) {
        await pc.locator('.card-head').getByRole('button', { name: window, exact: true }).click();
        if (BAD_TEXT.test(await pc.innerText())) throw new Error(`${window} P/C shows invalid text`);
        if (!await pc.locator('.pc-readings').innerText()) throw new Error(`${window} P/C has no readings`);
      }
      for (const range of ['1M', '3M', '6M', 'YTD', '1Y', 'MAX']) {
        const button = pc.locator('.range-switch').getByRole('button', { name: range, exact: true });
        if (!await button.count()) continue;
        await button.click();
        const text = await pc.locator('.pc-readings').innerText();
        if (!text.includes(`${range}:`)) throw new Error(`${range} did not update P/C statistics`);
      }
    }
    if (route === 'markets') {
      const index = page.locator('.card').filter({ has: page.locator('.index-history') }).first();
      const choices = await index.locator('.card-head button').all();
      for (const button of choices) {
        await button.click();
        if (await index.locator('.index-history .chart').count() !== 2) throw new Error('Index switch should show one price / breadth pair');
      }
      if (await page.locator('#main').innerText().then((text) => text.includes('overnight.json'))) throw new Error('Indices should not request overnight history');
      const markets = await artifact('markets');
      if (markets?.indices) {
        const indices = markets.index_order || Object.keys(markets.indices);
        if (await page.locator('table.index-compare tbody tr').count() !== indices.length) throw new Error('Index comparison should show one row per index');
      }
      const state = await artifact('market_state');
      if (state?.states) {
        if (await page.locator('.ms-chip').count() !== state.states.filter((s) => s.active_now).length) throw new Error('Compact list should contain active conditions only');
        if (await page.locator('.ms-chip[data-risk-level="inactive"]').count()) throw new Error('Inactive conditions should be folded');
        const labels = await page.locator('.ms-chip-status').allInnerTexts();
        if (labels.some((label) => !['ACTIVE', 'CAUTION'].includes(label))) throw new Error(`Unexpected condition label: ${labels.join(', ')}`);
        for (const condition of state.states.filter((s) => s.active_now)) {
          const chip = page.locator('.ms-chip').filter({ has: page.locator('.ms-chip-name', { hasText: condition.label }) });
          // Match by the exact name: some longer state names share a prefix.
          const namedChip = chip.filter({ has: page.getByText(condition.label, { exact: true }) });
          if (await namedChip.locator('.ms-chip-rule').innerText() !== condition.rule) throw new Error('Condition definition should be visible without opening history');
          const type = await namedChip.locator('.ms-chip-name').evaluate((node) => ({ size: parseFloat(getComputedStyle(node).fontSize), weight: parseInt(getComputedStyle(node).fontWeight, 10) }));
          if (type.size < 13 || type.weight < 600) throw new Error('State names should be readable and bold');
        }
        const fold = page.locator('details').filter({ hasText: 'Historical context · next' });
        if (await fold.getAttribute('open') !== null) throw new Error('State history should start folded');
        if (await page.locator('.ms-chip').count()) {
          await page.locator('.ms-chip').first().click();
          if (await fold.getAttribute('open') === null) throw new Error('Condition chip did not open history');
          // Smooth scrolling takes a moment; the opened fold must end up near the top of the view.
          const scrolled = await page.waitForFunction(() => {
            const top = document.querySelector('details.ms-history').getBoundingClientRect().top;
            return top >= 0 && top < window.innerHeight / 2;
          }, null, { timeout: RENDER_WAIT_MS }).then(() => true, () => false);
          if (!scrolled) throw new Error('Condition chip did not scroll history into view');
          await page.locator('.ms-chip').first().click();
          if (await fold.getAttribute('open') !== null) throw new Error('Condition chip did not close history');
        }
        await fold.locator('summary').click();
        if (!await fold.locator('table').count()) throw new Error('State history did not expand');
        if (/\bWATCH\b/.test(await fold.innerText())) throw new Error('WATCH label should be retired; active conditions read ACTIVE');
        if (await fold.locator('tbody tr').count() !== state.states.length) throw new Error('Folded history must retain every state');
      }
    }
    if (route === 'positioning' && (await artifact('positioning'))?.blackout?.as_of) {
      const block = page.locator('.blackout-section');
      if (!(await block.locator('.blackout-momentum').innerText()).includes('IN BLACKOUT NOW')) throw new Error('Blackout strip should show the current blackout share');
      if (BAD_TEXT.test(await block.innerText())) throw new Error('Blackout section shows invalid text');
    }
    if (route === 'europe') {
      const maps = page.locator('.card').filter({ has: page.locator('.eu-heatmap') });
      for (const map of await maps.all()) {
        await map.locator('.card-head').getByRole('button', { name: 'YTD', exact: true }).click();
        if (!await map.locator('.eu-heat-tile').count()) throw new Error('Empty Europe heatmap');
        await map.getByRole('button', { name: /USD|VS STOXX 600/, exact: true }).click();
        if (BAD_TEXT.test(await map.innerText())) throw new Error('Europe currency / relative toggle shows invalid text');
      }
    }
    if (route === 'heatmaps' && (await artifact('heatmaps'))?.index_maps?.length) {
      const map = page.locator('.card').filter({ has: page.locator('.treemap') }).first();
      for (const m of (await artifact('heatmaps')).index_maps) {
        await map.locator('.card-head').getByRole('button', { name: m.label, exact: true }).click();
        if (!(await map.locator('.card-title').innerText()).includes(`(${m.constituents.length} NAMES)`)) throw new Error(`${m.label} heat map did not switch`);
      }
    }
    if (route === 'overview') {
      const context = page.locator('details.ov-context');
      if (await context.getAttribute('open') !== null) throw new Error('Overview context should start collapsed');
      await context.locator('summary').click();
      if (await context.getAttribute('open') === null) throw new Error('Overview context did not expand');
    }
    if (route.startsWith('trade')) {
      await page.getByRole('button', { name: 'OVERNIGHT', exact: true }).click();
      const fold = page.locator('details').filter({ hasText: 'Historical research · overnight vs intraday returns' });
      if (await fold.getAttribute('open') !== null) throw new Error('Overnight history should be collapsed by default');
      // Missing history is a valid partial preview; production/full builds
      // exercise the actual decomposition and fund/range controls here.
      if (await artifact('overnight')) {
        await fold.locator('summary').first().click();
        await fold.locator('canvas').first().waitFor({ state: 'visible', timeout: RENDER_WAIT_MS });
        if (BAD_TEXT.test(await fold.innerText())) throw new Error('Overnight history shows invalid text');
      }
    }
  } catch (error) {
    problems.push(`${route}: interaction: ${error.message}`);
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
