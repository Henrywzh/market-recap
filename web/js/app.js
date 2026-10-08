// Shell: artifact loading, tab routing, theme, clock and the provenance footer.

import { el } from './fmt.js';
import { slowestParts } from './timings.js';
import { resizeAll, disposeAll } from './charts.js';
import { GROUPS, parseHash, hashFor, viewById, viewsIn } from './routes.js';

// View modules load on demand, stamped with the build they belong to. A
// browser keeps an ES module in memory under its URL, so an unversioned
// module survives a reload, a new tab and a no-store response alike: the page
// then renders last build's code against this build's data, which is far
// harder to spot than a plain failure. The views and their grouping live in
// routes.js.
const lastInGroup = new Map();

const renderers = new Map();

async function rendererFor(view) {
  if (renderers.has(view.id)) return renderers.get(view.id);
  const module = await import(`./tabs/${view.module}.js?v=${encodeURIComponent(state.version)}`);
  renderers.set(view.id, module.default);
  return module.default;
}

const ARTIFACT_BASE = 'artifacts';
const cache = new Map();
const state = { manifest: null, active: null, arg: null, version: 'dev' };

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
  if (state.active) select(state.active, { silent: true, arg: state.arg });
}

function buildTabs() {
  const nav = document.getElementById('tabs');
  nav.innerHTML = '';
  GROUPS.forEach((group) => {
    const views = viewsIn(group.id);
    nav.append(el('button', {
      class: 'tab',
      role: 'tab',
      id: `tab-${group.id}`,
      text: group.label,
      'aria-selected': 'false',
      onclick: () => select(lastInGroup.get(group.id) || views[0].id),
    }));
  });
}

function subTabs(view) {
  const views = viewsIn(view.group);
  if (views.length < 2) return null;
  return el('div', { class: 'subtabs', role: 'tablist' }, views.map((item) => el('button', {
    class: 'subtab',
    role: 'tab',
    text: item.label,
    'aria-selected': String(item.id === view.id),
    onclick: () => select(item.id),
  })));
}

// A view built from several artifacts gets each one, or `{ unavailable }` in
// its place, so one missing file does not blank the others.
function loadPayload(view) {
  return Array.isArray(view.artifact)
    ? Promise.all(view.artifact.map((name) => loadArtifact(name).catch((error) => ({ unavailable: error.message }))))
    : loadArtifact(view.artifact);
}

// What a view module receives besides its artifact: the argument from the
// hash, the shared artifact loader, and a way to move to another view.
function context(view, arg) {
  return {
    arg,
    loadArtifact,
    navigate: (id, next = null) => select(id, { arg: next }),
    setArg: (next) => {
      // A view that changes its own subject (the ticker page's search box)
      // records it in the hash without re-rendering itself.
      state.arg = next;
      history.replaceState(null, '', `#${hashFor(view.id, next)}`);
    },
  };
}

async function select(id, { silent = false, arg = null } = {}) {
  const view = viewById(id);
  if (!view) return;
  state.active = id;
  state.arg = view.takesArg ? arg : null;
  const hash = hashFor(id, state.arg);
  if (!silent && location.hash.replace('#', '') !== hash) {
    // Setting the hash fires hashchange; the handler sees the same view and
    // argument and returns, so this does not render twice.
    location.hash = hash;
  }
  lastInGroup.set(view.group, id);

  document.querySelectorAll('.tab').forEach((node) => {
    node.setAttribute('aria-selected', String(node.id === `tab-${view.group}`));
  });

  const main = document.getElementById('main');
  const host = document.getElementById('subtabs');
  host.replaceChildren(...[subTabs(view)].filter(Boolean));
  disposeAll();
  main.innerHTML = '';
  main.append(el('div', { class: 'loading', text: `Loading ${view.label}…` }));

  try {
    if (view.id === 'monitor' && !state.manifest?.panels?.includes('monitor')) {
      throw new Error('monitor was not built for this session');
    }
    const [payload, render] = await Promise.all([loadPayload(view), rendererFor(view)]);
    if (state.active !== id) return;
    main.innerHTML = '';
    await render(main, payload, state.manifest, context(view, state.arg));
  } catch (error) {
    if (state.active !== id) return;
    // The reader gets a sentence; the console (and the smoke test) the error.
    console.error(`${view.id} failed to render:`, error);
    main.innerHTML = '';
    main.append(el('div', { class: 'gap' }, [
      `${view.label} is unavailable: ${error.message}. `,
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
    el('span', { title: slowestParts(manifest.timings) }, `Generated ${manifest.generated_at} in ${manifest.build_seconds}s`),
    ' · ',
    // One line per index the build actually covered, named by the build.
    ...(manifest.indices || []).map((index) => (
      `${index.label}: ${index.members} members (${index.priced} priced) · `
    )),
    `Session: ${manifest.as_of} · Holdings file: ${manifest.holdings_as_of}`,
  ]));

  const sources = (manifest.sources || []).map((source) => {
    const cls = source.status === 'ok' ? 'src-ok' : source.status === 'partial' ? 'src-partial' : source.status === 'skipped' ? 'dim' : 'src-error';
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
  // The close edition is out half an hour after the bell; the evening build
  // adds what posts later (Treasury's curve, fund NAVs and flows, Cboe).
  const edition = manifest.edition === 'close' ? ' · close edition, evening data to follow' : '';
  document.getElementById('updated').textContent = `Built ${manifest.generated_at} · session ${manifest.as_of}${edition}`;
  startBuildAge(manifest.generated_at, manifest.build_age_hours);
  document.title = `${brand.title || 'Market Recap'} · ${manifest.as_of || ''}`;
  renderFooter(manifest);

  // An old hash (#financials, #fixed-income) or a ?ticker= link is rewritten
  // to the view it now names, so the address bar shows where the reader is.
  const initial = parseHash(location.hash, location.search);
  const canonical = `#${hashFor(initial.id, initial.arg)}`;
  if (location.hash !== canonical || location.search) {
    history.replaceState(null, '', `${location.pathname}${canonical}`);
  }
  select(initial.id, { silent: true, arg: initial.arg });

  window.addEventListener('hashchange', () => {
    const next = parseHash(location.hash);
    const canonicalNext = `#${hashFor(next.id, next.arg)}`;
    if (location.hash !== canonicalNext) history.replaceState(null, '', canonicalNext);
    if (next.id !== state.active || next.arg !== state.arg) select(next.id, { silent: true, arg: next.arg });
  });
  window.addEventListener('resize', () => requestAnimationFrame(resizeAll));
}
