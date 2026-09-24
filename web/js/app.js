// Shell: artifact loading, tab routing, theme, clock and the provenance footer.

import { el } from './fmt.js';
import { resizeAll, disposeAll } from './charts.js';

// Tab modules load on demand, stamped with the build they belong to. A
// browser keeps an ES module in memory under its URL, so an unversioned
// module survives a reload, a new tab and a no-store response alike: the page
// then renders last build's code against this build's data, which is far
// harder to spot than a plain failure.
const TABS = [
  { id: 'markets', label: 'MARKETS', artifact: 'markets', module: 'markets' },
  { id: 'monitor', label: 'MONITOR', artifact: 'monitor', module: 'monitor' },
  { id: 'catalysts', label: 'CATALYSTS', artifact: 'catalysts', module: 'catalysts' },
  { id: 'heatmaps', label: 'HEAT MAPS', artifact: 'heatmaps', module: 'heatmaps' },
  { id: 'fixed-income', label: 'FIXED INCOME', artifact: 'fixed_income', module: 'fixed-income' },
  { id: 'macro', label: 'MACRO', artifact: 'macro', module: 'macro' },
  { id: 'technicals', label: 'TECHNICALS', artifact: 'technicals', module: 'technicals' },
  { id: 'cross-listing', label: 'CROSS-LISTING', artifact: 'cross_listing', module: 'cross-listing' },
  { id: 'xray', label: 'ETF X-RAY', artifact: 'xray', module: 'xray' },
  { id: 'valuation', label: 'VALUATION & QUALITY', artifact: 'valuation', module: 'valuation' },
  { id: 'financials', label: 'FINANCIALS', artifact: 'financials', module: 'financials' },
  { id: 'dcf', label: 'DCF', artifact: 'dcf', module: 'dcf' },
];

const renderers = new Map();

async function rendererFor(tab) {
  if (renderers.has(tab.id)) return renderers.get(tab.id);
  const module = await import(`./tabs/${tab.module}.js?v=${encodeURIComponent(state.version)}`);
  renderers.set(tab.id, module.default);
  return module.default;
}

const ARTIFACT_BASE = 'artifacts';
const cache = new Map();
const state = { manifest: null, active: null, version: 'dev' };

export async function loadArtifact(name) {
  if (cache.has(name)) return cache.get(name);
  const promise = fetch(`${ARTIFACT_BASE}/${name}.json`, { cache: 'no-cache' }).then((response) => {
    if (!response.ok) throw new Error(`${name}.json returned ${response.status}`);
    return response.json();
  });
  cache.set(name, promise);
  return promise;
}

// A ticking clock beside a red dot claims a live feed. This page is a static
// build, so what it shows instead is how old that build is -- the one number
// that tells a reader whether they are looking at today's close or at
// something from last week.
function startBuildAge(generatedAt, thresholds) {
  const label = document.getElementById('build-age');
  const dot = document.getElementById('build-dot');
  if (!label) return;
  const built = generatedAt ? new Date(generatedAt) : null;
  if (!built || Number.isNaN(built.getTime())) {
    label.textContent = 'BUILD TIME UNKNOWN';
    dot.style.background = 'var(--down)';
    return;
  }
  // Thresholds come from the build, which owns the freshness policy. A second
  // copy here would drift the first time the policy changed.
  const { current = 24, recent = 72 } = thresholds || {};
  const MINUTES_PER_HOUR = 60;
  const tick = () => {
    const minutes = Math.max(0, Math.floor((Date.now() - built.getTime()) / 60000));
    const hours = minutes / MINUTES_PER_HOUR;
    const age = hours < 1
      ? `${minutes}m`
      : hours < 48
        ? `${Math.floor(hours)}h`
        : `${Math.floor(hours / 24)}d`;
    label.textContent = `BUILT ${age} AGO`;
    dot.style.background = hours < current
      ? 'var(--up)'
      : hours < recent ? 'var(--accent)' : 'var(--down)';
  };
  tick();
  setInterval(tick, 30000);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  try { localStorage.setItem('mr-theme', theme); } catch { /* private window */ }
  if (state.active) select(state.active, true);
}

function buildTabs() {
  const nav = document.getElementById('tabs');
  nav.innerHTML = '';
  TABS.forEach((tab) => {
    nav.append(el('button', {
      class: 'tab',
      role: 'tab',
      id: `tab-${tab.id}`,
      text: tab.label,
      'aria-selected': 'false',
      onclick: () => select(tab.id),
    }));
  });
}

async function select(id, silent = false) {
  const tab = TABS.find((t) => t.id === id);
  if (!tab) return;
  state.active = id;
  if (!silent) location.hash = id;

  document.querySelectorAll('.tab').forEach((node) => {
    node.setAttribute('aria-selected', String(node.id === `tab-${id}`));
  });

  const main = document.getElementById('main');
  disposeAll();
  main.innerHTML = '';
  main.append(el('div', { class: 'loading', text: `Loading ${tab.label}…` }));

  try {
    if (tab.id === 'monitor' && !state.manifest?.panels?.includes('monitor')) {
      throw new Error('monitor was not built for this session');
    }
    const [payload, render] = await Promise.all([
      loadArtifact(tab.artifact),
      rendererFor(tab),
    ]);
    main.innerHTML = '';
    await render(main, payload, state.manifest);
  } catch (error) {
    main.innerHTML = '';
    main.append(el('div', { class: 'gap' }, [
      `${tab.label} is unavailable: ${error.message}. `,
      'Run the refresh command to rebuild its artifact.',
    ]));
  }
  requestAnimationFrame(resizeAll);
}

function renderFooter(manifest) {
  const footer = document.getElementById('footer');
  footer.innerHTML = '';
  const brand = manifest.brand || {};

  footer.append(el('div', { class: 'brandline' }, [
    `${brand.title || 'MARKET RECAP'} — ${brand.disclaimer || 'Not investment advice.'}`,
  ]));
  footer.append(el('div', {}, [
    `Generated ${manifest.generated_at} in ${manifest.build_seconds}s · `,
    // One line per index the build actually covered, named by the build.
    ...(manifest.indices || []).map((index) => (
      `${index.label}: ${index.members} members (${index.priced} priced) · `
    )),
    `Session: ${manifest.as_of} · Holdings file: ${manifest.holdings_as_of}`,
  ]));

  const sources = (manifest.sources || []).map((source) => {
    const cls = source.status === 'ok' ? 'src-ok' : source.status === 'partial' ? 'src-partial' : 'src-error';
    return el('span', {}, [
      el('span', { class: cls, text: source.label }),
      el('span', { class: 'dim', text: ` (${source.freshness}${source.observed_date ? `, ${source.observed_date}` : ''})` }),
    ]);
  });
  const list = el('div', {}, ['Sources: ']);
  sources.forEach((node, index) => {
    if (index) list.append(document.createTextNode(' · '));
    list.append(node);
  });
  footer.append(list);

  const partial = (manifest.sources || []).filter((s) => s.error);
  partial.forEach((source) => {
    footer.append(el('div', { class: 'dim', text: `${source.label}: ${source.error}` }));
  });

  const errors = Object.entries(manifest.errors || {});
  if (errors.length) {
    footer.append(el('div', { class: 'src-error' }, [
      `Panels that failed this build: ${errors.map(([k, v]) => `${k} (${v})`).join('; ')}`,
    ]));
  }
}

export async function boot(manifest, version) {
  state.version = version || 'dev';

  const themeSelect = document.getElementById('theme-select');
  let saved = 'dark';
  try { saved = localStorage.getItem('mr-theme') || 'dark'; } catch { /* ignore */ }
  themeSelect.value = saved;
  document.documentElement.setAttribute('data-theme', saved);
  themeSelect.addEventListener('change', (event) => applyTheme(event.target.value));

  buildTabs();

  if (!manifest) {
    document.getElementById('main').innerHTML = '';
    document.getElementById('main').append(el('div', { class: 'gap' }, [
      'No build manifest found. Run: python -m market_recap.cli refresh',
    ]));
    return;
  }
  state.manifest = manifest;
  const brand = manifest.brand || {};
  document.getElementById('brand').textContent = brand.title || 'MARKET RECAP';
  document.getElementById('brand-sub').textContent = brand.subtitle || '';
  document.getElementById('asof').textContent = `AS OF ${manifest.as_of || '—'}`;
  document.getElementById('updated').textContent = `Built ${manifest.generated_at} · session ${manifest.as_of}`;
  startBuildAge(manifest.generated_at, manifest.build_age_hours);
  document.title = `${brand.title || 'Market Recap'} · ${manifest.as_of || ''}`;
  renderFooter(manifest);

  const initial = location.hash.replace('#', '') || 'markets';
  select(TABS.some((t) => t.id === initial) ? initial : 'markets', true);

  window.addEventListener('hashchange', () => {
    const next = location.hash.replace('#', '');
    if (next && next !== state.active) select(next, true);
  });
  window.addEventListener('resize', () => requestAnimationFrame(resizeAll));
}
