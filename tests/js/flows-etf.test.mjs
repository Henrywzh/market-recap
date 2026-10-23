// The ETF flows section, rendered under a small fake DOM and a stub ECharts.
// The checks: the signed dollar and percent text, the percentile suffixes, the
// headline line, the absent and unavailable states, the table and its stale
// tag, the aggregate chart's series and colours, and that no page text carries
// NaN, undefined or [object Object].
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { section, dollars, pctOfAssets, rankText, headlineText, aggregateLine } from '../../web/js/flows-etf.js';

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.style = {};
    this.hidden = false;
    this.classList = { add() {} };
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelectorAll() { return []; }
  get isConnected() { return true; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createElementNS: (ns, tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  documentElement: new FakeNode('html'),
  body: { contains: () => true },
});

// All text on the page, in order: element text plus every text node beneath it.
function allText(node) {
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(allText)].join(' ');
}

function findAll(node, predicate, out = []) {
  if (node.nodeType !== 1) return out;
  if (predicate(node)) out.push(node);
  for (const child of node.children || []) findAll(child, predicate, out);
  return out;
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

// Installs the fake DOM and a stub ECharts that records each option it is given.
async function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  const options = [];
  globalThis.document = fakeDocument();
  // Each colour variable reads back as its own name, so a test can tell which colour a chart asked for.
  globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => name });
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.window = {
    echarts: {
      init: () => ({
        setOption(option) { options.push(option); }, resize() {}, dispose() {}, on() {}, getModel() {},
      }),
    },
  };
  try {
    const result = await run(options);
    await flush();
    await flush();
    return result;
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

const fund = (over) => ({
  ticker: 'SPY', label: 'S&P 500', group: 'US equity', source: 'State Street', source_id: 'ssga_nav_history',
  as_of: '2026-10-22', history_start: '2003-12-01', sessions: 5763, aum: 8e11,
  flow_1d: -267e6, flow_1w: -4.07e9, flow_1m: 10.6e9, flow_3m: 20e9, flow_1m_pct_aum: 0.0132,
  pct_rank_1w: 24, stale: false, shares_unchanged_since: null, note: null, ...over,
});

const aggregate = (name, funds) => ({
  name, members: funds, funds, excluded: [], latest_date: '2026-10-22',
  dates: ['2026-10-20', '2026-10-21', '2026-10-22'], flow: [1e9, -2e9, 3e9],
  rolling_20: [null, null, 2e9], count: [2, 2, 2],
  latest: { flow_1d: 3e9, flow_1w: -4e9, flow_1m: 10e9, pct_rank_1w: 11, rolling_20: 2e9 },
});

const payload = {
  as_of: '2026-10-22',
  headline: {
    date: '2026-10-22', us_equity_1d: 3e9, us_equity_1w: -11.38e9, us_equity_1w_pct_rank: 11,
    top_in: [['SOXX', 4.39e9], ['RSP', 8.2e8]], top_out: [['IWM', -5.07e9]],
  },
  funds: [
    fund({}),
    fund({ ticker: 'QQQ', label: 'Nasdaq-100', group: 'US equity', source: 'Invesco recorded', source_id: 'invesco_recorded',
      flow_1m: null, flow_1m_pct_aum: null, pct_rank_1w: null, stale: true, note: 'share count unchanged since 2026-10-05' }),
    fund({ ticker: 'XLK', label: 'Technology', group: 'Sectors', flow_1m_pct_aum: 0.0128, pct_rank_1w: 36 }),
    fund({
      ticker: 'EFA', label: 'Developed ex-US', group: 'International', flow_1d: 0, flow_1w: 0,
      note: 'share count unchanged for 13 sessions; the issuer may be lagging, so recent flows may read low',
    }),
  ],
  aggregates: [aggregate('US equity', ['SPY', 'QQQ']), aggregate('Treasuries', ['SHY']), aggregate('Credit', []), aggregate('Gold', ['GLD'])],
  sectors: [
    { ticker: 'XLK', label: 'Technology', flow_1m: 1.5e9, flow_1m_pct_aum: 0.0128 },
    { ticker: 'XLB', label: 'Materials', flow_1m: -3e8, flow_1m_pct_aum: -0.042 },
  ],
  not_covered: [{ ticker: 'VOO', label: 'Vanguard S&P 500', reason: 'no share history' }],
  excluded_days: [{ ticker: 'XLK', date: '2025-12-05', reason: 'split' }],
  invesco_recorded_since: '2026-09-28',
  lag: 'Each fund\'s as-of date is its issuer\'s own last date.',
};

test('signed dollars use the unit that keeps three figures', () => {
  assert.equal(dollars(7.7e9), '+$7.7bn');
  assert.equal(dollars(-310e6), '−$310m');
  assert.equal(dollars(0), '$0');
  assert.equal(dollars(null), '—');
  assert.equal(dollars(undefined), '—');
  assert.equal(dollars(Number.NaN), '—');
});

test('percent of assets is signed and carries two decimals', () => {
  assert.equal(pctOfAssets(0.0131), '+1.31%');
  assert.equal(pctOfAssets(-0.0254), '−2.54%');
  assert.equal(pctOfAssets(null), '—');
});

test('percentile ranks take their ordinal suffix', () => {
  assert.equal(rankText(97), '97th pct');
  assert.equal(rankText(1), '1st pct');
  assert.equal(rankText(2), '2nd pct');
  assert.equal(rankText(3), '3rd pct');
  assert.equal(rankText(11), '11th pct');
  assert.equal(rankText(12), '12th pct');
  assert.equal(rankText(13), '13th pct');
  assert.equal(rankText(21), '21st pct');
  assert.equal(rankText(null), '—');
});

test('the headline line names the week, its rank and the largest moves', () => {
  const line = headlineText(payload.headline);
  assert.equal(line, 'US equity ETFs −$11.4bn over a week, 11th pct of three years; in: SOXX +$4.4bn, RSP +$820m; out: IWM −$5.1bn');
  assert.equal(headlineText(null), null);
  assert.equal(headlineText({ us_equity_1w: null }), null);
});

test('a missing or unavailable build says so in words', async () => {
  await withBrowser(async () => {
    const absent = section(null);
    assert.match(allText(absent[0]), /not built this session/);
    const down = section({ unavailable: 'no ETF share-count history could be read this build' });
    assert.match(allText(down[0]), /not available: no ETF share-count history/);
    const empty = section({ funds: [] });
    assert.match(allText(empty[0]), /No ETF share history/);
  });
});

test('the section renders its table, chips, stale tag and method, with no leaked tokens', async () => {
  await withBrowser(async () => {
    const [card] = section(payload);
    const text = allText(card);
    for (const bad of ['NaN', 'undefined', '[object Object]']) assert.equal(text.includes(bad), false, bad);

    assert.match(text, /ETF FLOWS · CREATIONS AND REDEMPTIONS/);
    assert.match(text, /SPY/);
    assert.match(text, /\+\$10\.6bn/);
    assert.match(text, /24th pct/);
    assert.match(text, /Method & limits/);
    assert.match(text, /Not covered: VOO/);

    const chips = findAll(card, (n) => n.tagName === 'BUTTON').map((b) => b.textContent);
    assert.deepEqual(chips, ['US equity', 'Treasuries', 'Credit', 'Gold']);

    const stale = findAll(card, (n) => n.className.includes('tag-warn'));
    assert.equal(stale.length, 1);
    assert.equal(stale[0].textContent, 'STALE');

    const groups = findAll(card, (n) => n.className === 'flow-group').map((n) => n.children[0].textContent);
    assert.deepEqual(groups, ['US equity', 'Sectors', 'International']);
  });
});

test('the aggregate chart draws daily bars in up and down colours with the rolling line', async () => {
  const options = await withBrowser(async (recorded) => {
    section(payload);
    await flush();
    return recorded;
  });
  const first = options.find((o) => o.series?.[0]?.type === 'bar');
  assert.ok(first, 'a bar chart was drawn');
  const [bars, line] = first.series;
  assert.equal(bars.type, 'bar');
  assert.equal(line.type, 'line');
  assert.deepEqual(line.data, [null, null, 2]);
  assert.deepEqual(bars.data, [1, -2, 3]);
  // The colour callback reads the sign of each bar.
  assert.equal(bars.itemStyle.color({ value: 1 }), '--up');
  assert.equal(bars.itemStyle.color({ value: -1 }), '--down');
});

test('an aggregate line names its coverage, the funds in the week and the funds behind the rank', () => {
  const agg = {
    name: 'S&P 500', latest_date: '2026-10-22', funds: ['SPY', 'IVV'], latest_funds: ['SPY', 'IVV', 'SPYM'],
    latest: { flow_1w: -4.1e9, flow_1m: 1.06e10, pct_rank_1w: 24 },
    coverage: { pct: 65, missing: ['VOO'] },
  };
  const line = aggregateLine(agg);
  assert.match(line, /^S&P 500: 1W −\$4\.1bn · 1M \+\$10\.6bn · 1W rank 24th pct \(rank on SPY, IVV\) · covers ~65% of assets \(not VOO\) · SPY, IVV, SPYM · as of 2026-10-22$/);
  assert.equal(aggregateLine({ name: 'Nasdaq-100', latest: { flow_1w: null } }), null);
  const bare = aggregateLine({ name: 'Gold', funds: ['GLD'], latest_funds: ['GLD'], latest: { flow_1w: 1e9, flow_1m: null, pct_rank_1w: null } });
  assert.doesNotMatch(bare, /NaN|undefined|null|covers/);
});
