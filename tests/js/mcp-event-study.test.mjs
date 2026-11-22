// event_study: the MCP form of TRADE DESK -> EVENT LAB. It must give the page's
// numbers for the page's settings (its readings are sessions() column by column;
// its events and statistics are study()'s), and add only the custom filters.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { memoryAssets } from '../../mcp/fake-assets.mjs';
import { handleMcp } from '../../mcp/server.mjs';
import { TOOLS } from '../../mcp/tools.mjs';
import { validate } from '../../mcp/schema.mjs';
import { outcomeColumns, readings } from '../../mcp/tools/event_study.mjs';
import { EXCLUSION_PRESETS, sessions, study } from '../../web/js/event-lab-model.js';
import { randomDrawShare } from '../../web/js/trade-conditions.js';
import { rsi } from '../../web/js/technicals-math.js';

globalThis.fetch = () => { throw new Error('the MCP server must not call fetch()'); };

// A seeded random walk on weekdays, with a missing close and a missing low.
function makeBars(n = 900, seed = 7, start = '2019-01-02') {
  let a = seed;
  const rnd = () => { a = (a * 1103515245 + 12345) % 2147483648; return a / 2147483648; };
  const dates = []; const open = []; const high = []; const low = []; const close = []; const volume = [];
  const d = new Date(`${start}T00:00:00Z`); let px = 100;
  while (dates.length < n) {
    if (d.getUTCDay() % 6 !== 0) {
      const shock = (rnd() - 0.5) * (rnd() < 0.05 ? 14 : 4);
      const o = px * (1 + (rnd() - 0.5) / 100); px = Math.max(1, px * (1 + shock / 100));
      dates.push(d.toISOString().slice(0, 10)); open.push(o); close.push(px);
      high.push(Math.max(o, px) * (1 + rnd() / 100)); low.push(Math.min(o, px) * (1 - rnd() * 3 / 100)); volume.push(1e6);
    }
    d.setUTCDate(d.getUTCDate() + 1);
  }
  close[300] = null; low[420] = null;
  return { ticker: 'TEST', dates, open, high, low, close, volume };
}

const BARS = makeBars();
const CONDITIONS = {
  as_of: '2022-06-15', settings: { min_trades: 30, min_stretches: 5, stretch_gap_days: 91 }, notes: ['Each condition is read at the signal session\'s close.'],
  conditions: [
    { key: 'trend', label: 'MARKET TREND', options: ['ABOVE 200D', 'BELOW 200D'], today: 'BELOW 200D', runs: [['2019-01-02', 'ABOVE 200D'], ['2020-02-24', 'BELOW 200D'], ['2020-07-01', 'ABOVE 200D'], ['2022-01-20', 'BELOW 200D']] },
    { key: 'vix', label: 'VIX', options: ['CALM', 'STRESSED'], today: 'STRESSED', runs: [['2019-01-02', 'CALM'], ['2020-03-01', 'STRESSED'], ['2020-09-01', 'CALM'], ['2022-02-01', 'STRESSED']] },
  ],
};
const FILES = {
  '/artifacts/manifest.json': { as_of: BARS.dates.at(-1), generated_at: '2022-06-15T22:00:00Z' },
  '/artifacts/bars/TEST.json': BARS,
  '/artifacts/bars/BRK-B.json': { ...makeBars(400, 3), ticker: 'BRK-B' },
  '/artifacts/trade_conditions.json': CONDITIONS,
};

async function call(args, files = FILES) {
  const body = JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'event_study', arguments: args } });
  const response = await handleMcp(new Request('https://market-recap-b5p.pages.dev/mcp', { method: 'POST', body }), { ASSETS: memoryAssets(files) });
  return (await response.json()).result;
}
const r3 = (v) => (Number.isFinite(v) ? Math.round(v * 1000) / 1000 : null);

test('readings() is sessions() row for row, gaps included', () => {
  assert.deepEqual(readings(BARS), sessions(BARS));
  const short = makeBars(30, 11);
  assert.deepEqual(readings(short), sessions(short));
});

test('outcome columns are the model\'s long outcomes', async () => {
  const { outcomes } = await import('../../web/js/event-lab-model.js');
  const cols = outcomeColumns(BARS);
  for (const i of [0, 299, 300, 500, BARS.dates.length - 3, BARS.dates.length - 1]) {
    const o = outcomes(BARS, i);
    for (const [k, v] of Object.entries(o)) assert.equal(Number.isNaN(cols[k][i]) ? null : cols[k][i], v, `${k} at ${i}`);
  }
});

// The page's settings and the tool's spelling of them.
const CASES = [
  [{ trigger: { kind: 'intraday', dir: -1, size: 3 } }, { trigger: { kind: 'intraday', direction: 'down', size: 3 } }],
  [{ trigger: { kind: 'close', dir: -1, size: 1 }, filters: { rsi: { op: 'le', value: 45 }, trend: 'above200' } },
    { trigger: { kind: 'close', direction: 'down', size: 1 }, filters: { rsi: { max: 45 }, ma: [{ period: 200, side: 'above' }] } }],
  [{ trigger: { kind: 'sigma', dir: 1, size: 0.8 }, filters: { fromHigh: { op: 'ge', value: -40 }, trend: 'below50' }, gap: 0, costBps: 10, side: -1 },
    { trigger: { kind: 'sigma', direction: 'up', size: 0.8 }, filters: { from_high: { min: -40 }, ma: [{ period: 50, side: 'below' }] }, gap: 0, cost_bps: 10, side: 'short' }],
  [{ trigger: { kind: 'gap', dir: -1, size: 0.3 }, filters: { conditions: CONDITIONS.conditions, backdrop: { trend: 'BELOW 200D' } }, gap: 3 },
    { trigger: { kind: 'gap', direction: 'down', size: 0.3 }, backdrop: { trend: 'BELOW 200D' }, gap: 3 }],
  [{ trigger: { kind: 'close', dir: -1, size: 1 }, filters: { conditions: CONDITIONS.conditions, backdrop: { trend: 'BELOW 200D', vix: 'STRESSED' } }, gap: 2 },
    { trigger: { kind: 'close', direction: 'down', size: 1 }, like_today: true, gap: 2 }],
];

test('for the page\'s settings the tool reports the page\'s events and statistics', async () => {
  let exactDraws = 0;
  for (const [page, tool] of CASES) {
    const exclude = EXCLUSION_PRESETS.filter((p) => p.on);
    const r = study(BARS, { gap: 5, exclude, ...page });
    const result = await call({ symbol: 'TEST', ...tool });
    assert.notEqual(result.isError, true, result.content[0].text);
    const d = result.structuredContent;
    const label = JSON.stringify(tool);
    assert.ok(r.events.length >= 3, `${label}: the case must produce events to compare (${r.events.length})`);
    assert.equal(d.counts.events, r.events.length, label);
    assert.equal(d.counts.trigger_days, r.raw, label);
    assert.equal(d.counts.sessions_in_window, r.eligible, label);
    assert.equal(d.counts.touched_intraday_only, r.touchedOnly, label);
    for (const row of d.outcomes) {
      const s = r.summary[row.at]; const b = r.baseline[row.at];
      assert.deepEqual([row.events.n, row.events.mean_pct, row.events.median_pct, row.events.p25_pct, row.events.worst_pct, row.events.share_positive],
        [s.n, r3(s.mean), r3(s.median), r3(s.p25), r3(s.min), r3(s.hit)], `${label} ${row.at}`);
      assert.deepEqual([row.every_session.n, row.every_session.mean_pct, row.every_session.median_pct, row.every_session.share_positive],
        [b.n, r3(b.mean), r3(b.median), r3(b.hit)], `${label} baseline ${row.at}`);
    }
    // Small samples get the page's exact random-draw check.
    const k = r.summary.close5.n;
    if (k > 0 && k <= 60) {
      exactDraws += 1;
      assert.equal(d.focus.random_draw_share, r3(randomDrawShare(r.baseValues.close5, k, r.summary.close5.mean)), label);
    }
    assert.deepEqual(d.recent_events.map((e) => e.date), r.events.slice(-10).reverse().map((e) => e.date), label);
  }
  assert.ok(exactDraws >= 1, 'at least one case must use the exact random-draw check');
});

test('custom filters: RSI of another period, a distance band from an average, a shorter high', async () => {
  const base = { symbol: 'TEST', trigger: { kind: 'close', direction: 'down', size: 1 }, gap: 0, exclude: [] };
  const rsi14 = rsi(BARS.close.map((v) => (Number.isFinite(v) ? v : NaN)), 14);
  const d1 = (await call({ ...base, filters: { rsi: { period: 14, min: 30, max: 45 } } })).structuredContent;
  const rows = sessions(BARS);
  const want = rows.filter((s) => s.i > 0 && Number.isFinite(s.closeRet) && s.closeRet <= -1 && rsi14[s.i] >= 30 && rsi14[s.i] <= 45).length;
  assert.equal(d1.counts.events, want);
  assert.ok(want > 0);

  const d2 = (await call({ ...base, filters: { ma: [{ period: 20, min_pct: -8, max_pct: -2 }] } })).structuredContent;
  assert.ok(d2.counts.events > 0 && d2.counts.events < d1.counts.events + 1000);
  assert.equal(d2.latest_session.custom.ma[0].period, 20);

  const d3 = (await call({ ...base, filters: { from_high: { window: 63, max: -15 } } })).structuredContent;
  const d4 = (await call({ ...base, filters: { from_high: { window: 252, max: -15 } } })).structuredContent;
  assert.notEqual(d3.counts.events, d4.counts.events);
  assert.equal(d3.latest_session.custom.from_high.window, 63);
});

test('the result names the last session\'s readings, whether it fires, and the sample-size verdict', async () => {
  const result = await call({ symbol: 'TEST', trigger: { kind: 'close', direction: 'down', size: 9 } });
  const d = result.structuredContent;
  assert.deepEqual(validate(TOOLS.find((t) => t.name === 'event_study').outputSchema, d), []);
  assert.equal(d.latest_session.date, BARS.dates.at(-1));
  assert.equal(typeof d.latest_session.fires_trigger, 'boolean');
  assert.equal(d.focus.enough_sample, false);
  assert.ok(d.focus.warnings[0].startsWith('only '));
  assert.ok(d.caveats.some((c) => c.startsWith('Small sample')));
  assert.deepEqual(d.applied.exclude.map((p) => p.key), EXCLUSION_PRESETS.filter((p) => p.on).map((p) => p.key));
  assert.equal(d.outcomes.length, 14);
  assert.ok(result.content[0].text.length <= 20480);
});

test('a dotted share class reaches the dashed bars file', async () => {
  const d = (await call({ symbol: 'brk.b', trigger: { kind: 'close', direction: 'down', size: 1 } })).structuredContent;
  assert.equal(d.symbol, 'BRK-B');
});

test('bad requests are tool errors that say what to fix', async () => {
  const msg = async (args) => (await call(args)).content[0].text;
  assert.match(await msg({ symbol: 'ZZZZ', trigger: { kind: 'close', direction: 'down', size: 2 } }), /No daily bars for "ZZZZ"/);
  assert.match(await msg({ symbol: 'TEST', trigger: { kind: 'close', direction: 'down', size: 2 }, backdrop: { vix: 'PANIC' } }), /vix is one of CALM, STRESSED/);
  assert.match(await msg({ symbol: 'TEST', trigger: { kind: 'close', direction: 'down', size: 2 }, backdrop: { moon: 'FULL' } }), /Unknown backdrop condition "moon"/);
  assert.match(await msg({ symbol: 'TEST', trigger: { kind: 'close', direction: 'down', size: 2 }, filters: { rsi: { period: 14 } } }), /filters.rsi needs min, max or both/);
  assert.match(await msg({ symbol: 'TEST', trigger: { kind: 'close', direction: 'down', size: 2 }, filters: { ma: [{ period: 50 }] } }), /filters.ma\[0\] needs side/);
  assert.match(await msg({ symbol: 'TEST', trigger: { kind: 'wobble', direction: 'down', size: 2 } }), /Invalid arguments/);
});

test('without the backdrop artifact, a study with no backdrop still runs; one that asks for it says why it cannot', async () => {
  const files = { ...FILES }; delete files['/artifacts/trade_conditions.json'];
  const plain = await call({ symbol: 'TEST', trigger: { kind: 'close', direction: 'down', size: 2 } }, files);
  assert.notEqual(plain.isError, true);
  const asked = await call({ symbol: 'TEST', trigger: { kind: 'close', direction: 'down', size: 2 }, backdrop: { vix: 'CALM' } }, files);
  assert.match(asked.content[0].text, /Unknown backdrop condition "vix". Conditions: none in this build/);
});
