// Shell: artifact loading, tab routing, theme, clock and the provenance footer.

import { el } from './fmt.js';
import { resizeAll, disposeAll } from './charts.js';

import renderMarkets from './tabs/markets.js';
import renderHeatmaps from './tabs/heatmaps.js';
import renderFixedIncome from './tabs/fixed-income.js';
import renderMacro from './tabs/macro.js';
import renderTechnicals from './tabs/technicals.js';
import renderDcf from './tabs/dcf.js';

const TABS = [
  { id: 'markets', label: 'MARKETS', artifact: 'markets', render: renderMarkets },
  { id: 'heatmaps', label: 'HEAT MAPS', artifact: 'heatmaps', render: renderHeatmaps },
  { id: 'fixed-income', label: 'FIXED INCOME', artifact: 'fixed_income', render: renderFixedIncome },
  { id: 'macro', label: 'MACRO', artifact: 'macro', render: renderMacro },
  { id: 'technicals', label: 'TECHNICALS', artifact: 'technicals', render: renderTechnicals },
  { id: 'dcf', label: 'DCF', artifact: 'dcf', render: renderDcf },
];

const ARTIFACT_BASE = '../artifacts';
const cache = new Map();
const state = { manifest: null, active: null };

export async function loadArtifact(name) {
  if (cache.has(name)) return cache.get(name);
  const promise = fetch(`${ARTIFACT_BASE}/${name}.json`, { cache: 'no-cache' }).then((response) => {
    if (!response.ok) throw new Error(`${name}.json returned ${response.status}`);
    return response.json();
  });
  cache.set(name, promise);
  return promise;
}

function startClock() {
  const node = document.getElementById('clock');
  const tick = () => {
    const now = new Date();
    node.textContent = now.toLocaleTimeString('en-GB', { hour12: false });
  };
  tick();
  setInterval(tick, 1000);
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
    const payload = await loadArtifact(tab.artifact);
    main.innerHTML = '';
    await tab.render(main, payload, state.manifest);
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
    `S&P 500 constituents: ${manifest.constituents} (${manifest.constituents_priced} priced) · `,
    `Nasdaq-100 constituents: ${manifest.ndx_constituents} · `,
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

async function boot() {
  startClock();

  const themeSelect = document.getElementById('theme-select');
  let saved = 'dark';
  try { saved = localStorage.getItem('mr-theme') || 'dark'; } catch { /* ignore */ }
  themeSelect.value = saved;
  document.documentElement.setAttribute('data-theme', saved);
  themeSelect.addEventListener('change', (event) => applyTheme(event.target.value));

  buildTabs();

  try {
    state.manifest = await loadArtifact('manifest');
  } catch (error) {
    document.getElementById('main').innerHTML = '';
    document.getElementById('main').append(el('div', { class: 'gap' }, [
      `No build manifest found (${error.message}). Run: python -m market_recap.cli refresh`,
    ]));
    return;
  }

  const manifest = state.manifest;
  const brand = manifest.brand || {};
  document.getElementById('brand').textContent = brand.title || 'MARKET RECAP';
  document.getElementById('brand-sub').textContent = brand.subtitle || '';
  document.getElementById('asof').textContent = `AS OF ${manifest.as_of || '—'}`;
  document.getElementById('updated').textContent = `Last updated ${manifest.generated_at}`;
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

boot();
