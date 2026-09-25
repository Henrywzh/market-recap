// MONITOR: a static, prospective drawdown queue.  Everything shown comes from
// this build's artifacts (monitor, heatmaps weights, per-ticker closes); there
// are deliberately no browser feed requests.

import { el, card, table, num, pct, sectionTitle, notice, gap, DASH } from '../fmt.js';
import { render } from '../charts.js';
import {
  FOLLOW_STORAGE_KEY,
  MONITOR_STATUSES,
  QUADRANTS,
  deriveMonitorRows,
  inQueue,
  quadrantOf,
  todayChanges,
  filterMonitorRows,
  loadFollowState,
  mergeFollowLists,
  monitorCoverage,
  normalizeThreshold,
  parseFollowImport,
  saveFollowState,
  serializeFollowList,
  sortMonitorRows,
} from '../monitor-model.js';

const UNKNOWN = 'UNKNOWN';
const MODES = [
  ['today', 'TODAY'],
  ['queue', 'QUEUE'],
  ['sectors', 'SECTORS'],
  ['following', 'FOLLOWING'],
  ['all', 'ALL'],
];

const ANOMALY_TEXT = {
  company: 'COMPANY',
  sector: 'SECTOR-WIDE',
  drawdown: 'DRAWDOWN',
};
const REASON_TEXT = {
  drawdown: 'past the drawdown threshold',
  peer_laggard: 'lagging sector peers',
};
const REASON_SHORT = {
  drawdown: 'drawdown',
  peer_laggard: 'behind peers',
};
const EXPECTATION_TEXT = {
  cut: 'CUT', raised: 'RAISED', steady: 'STEADY', stale: 'STALE', thin: 'THIN',
};
const ANOMALY_TAG = { company: 'CO', sector: 'SECTOR' };
const QUADRANT_SHORT = {
  'weak-steady': 'WEAK · STEADY',
  'weak-other': 'WEAK · AGAINST / UNKNOWN',
  'stabilising-steady': 'STABILISING · STEADY',
  'stabilising-other': 'STABILISING · AGAINST / UNKNOWN',
};
const SECTOR_SHORT = {
  'Communication Services': 'Comm Services',
  'Consumer Discretionary': 'Cons Discretionary',
  'Consumer Staples': 'Cons Staples',
  'Information Technology': 'Info Tech',
};
// Display clip for the revision axis; the tooltip keeps the true value. The
// axis is square-root scaled: most revisions sit within a few percent of zero,
// and a linear axis would draw them as one line.
const REVISION_CLIP = 10;
const rootScale = (value) => Math.sign(value) * Math.sqrt(Math.abs(value));
const REVISION_TICKS = [-10, -5, -2, 0, 2, 5, 10];

// Dot size is the S&P 500 weight HEAT MAPS already publishes. Without it the
// dots are drawn equal, which loses emphasis but no fact.
let weightsPromise = null;
function loadWeights() {
  if (!weightsPromise) {
    weightsPromise = fetch('artifacts/heatmaps.json', { cache: 'no-cache' })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => new Map((data?.constituents || []).map((c) => [c.ticker, c.weight])))
      .catch(() => new Map());
  }
  return weightsPromise;
}

const tickerPayloads = new Map();
async function loadTicker(symbol) {
  const key = String(symbol).toUpperCase();
  if (!tickerPayloads.has(key)) {
    tickerPayloads.set(key, fetch(`artifacts/tickers/${key}.json`, { cache: 'no-cache' }).then((response) => {
      if (!response.ok) throw new Error(`${key} has no price history in this build`);
      return response.json();
    }));
  }
  try {
    return await tickerPayloads.get(key);
  } catch (error) {
    tickerPayloads.delete(key);
    throw error;
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// A signed value drawn as a bar either side of a centre line, then the number.
function divergingCell(value, scale, text, title) {
  const known = value !== null && value !== undefined && Number.isFinite(value);
  const width = known ? Math.min(50, (Math.abs(value) / scale) * 50) : 0;
  const side = known && value < 0 ? `right:50%` : 'left:50%';
  return el('td', { class: `monitor-bar-cell ${directionClass(value)}`, title }, [
    el('span', { class: 'mbar' }, [
      el('span', { class: 'mbar-mid' }),
      known ? el('span', { class: `mbar-fill ${value < 0 ? 'down' : 'up'}`, style: `${side};width:${width}%` }) : null,
    ]),
    el('span', { class: 'mbar-text', text }),
  ]);
}

function drawdownCell(value, qualifies, text) {
  const known = value !== null && value !== undefined && Number.isFinite(value);
  const width = known ? Math.min(100, (Math.abs(value) / 70) * 100) : 0;
  return el('td', { class: `monitor-bar-cell ${!known ? 'dim' : qualifies ? 'down' : 'flat'}` }, [
    el('span', { class: 'mbar' }, [
      known ? el('span', { class: 'mbar-fill down', style: `right:0;width:${width}%` }) : null,
    ]),
    el('span', { class: 'mbar-text', text }),
  ]);
}

const RAW_FIELDS = [
  ['ticker', 'TICKER'],
  ['name', 'NAME'],
  ['sector', 'SECTOR'],
  ['in_universe', 'IN UNIVERSE'],
  ['drawdown_pct', 'DRAWDOWN %'],
  ['price_as_of', 'PRICE SOURCE DATE'],
  ['market_excess_pct', 'MARKET EXCESS PP'],
  ['sector_excess_pct', 'SECTOR EXCESS PP'],
  ['market_benchmark', 'MARKET BENCHMARK'],
  ['sector_benchmark', 'SECTOR BENCHMARK'],
  ['rs_improving', 'RS IMPROVING'],
  ['above_ma', 'ABOVE MA'],
  ['pe', 'P/E'],
  ['pe_percentile', 'P/E PERCENTILE'],
  ['pe_vs_median', 'P/E VS MEDIAN'],
  ['fcf_positive', 'FCF POSITIVE'],
  ['revenue_growth_pct', 'REVENUE GROWTH %'],
  ['filed', 'FILED'],
  ['period_end', 'PERIOD END'],
  ['earnings_date', 'EARNINGS DATE'],
  ['earnings_status', 'EARNINGS STATUS'],
  ['estimate_revision', 'FY1 EPS 30D CHANGE %'],
  ['membership', 'MEMBERSHIP'],
  ['return_pct', 'RETURN %'],
  ['peer_return_pct', 'PEER MEDIAN RETURN %'],
  ['peer_excess_pct', 'VS PEERS PP'],
  ['peer_count', 'PEERS'],
  ['candidate', 'IN QUEUE (BUILD THRESHOLD)'],
  ['anomaly', 'ANOMALY'],
  ['price_state', 'PRICE STATE'],
  ['evidence_state', 'EVIDENCE STATE'],
];

function present(value) {
  return value !== null && value !== undefined && value !== '';
}

function unknown(value, formatter = String) {
  return present(value) ? formatter(value) : UNKNOWN;
}

function formatPct(value, digits = 1) {
  return unknown(value, (number) => pct(number, digits));
}

function formatPp(value, digits = 1) {
  return unknown(value, (number) => `${number >= 0 ? '+' : ''}${num(number, digits)} pp`);
}

function formatPercentile(value) {
  return unknown(value, (number) => `${num(number, 0)}th`);
}

function directionClass(value) {
  if (!present(value)) return 'dim';
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return 'flat';
}

function formatThreshold(value) {
  return `${num(value, Number.isInteger(value) ? 0 : 1)}%`;
}

function raw(value) {
  if (value === null || value === undefined) return UNKNOWN;
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : UNKNOWN;
  if (typeof value === 'boolean') return value ? 'YES' : 'NO';
  if (typeof value === 'object') {
    try { return JSON.stringify(value); } catch { return UNKNOWN; }
  }
  return String(value);
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function configValue(data, key, fallback = null) {
  const settings = data?.settings || {};
  const nested = settings.config || data?.config || {};
  return settings[key] ?? nested[key] ?? fallback;
}

function safeBrowserStorage() {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

function artifactNote(data) {
  const universe = data.universe || {};
  const index = configValue(data, 'index', universe.key || UNKNOWN);
  const label = universe.label || index;
  const drawdownPeriod = configValue(data, 'drawdown_period', UNKNOWN);
  const drawdownSessions = configValue(data, 'drawdown_sessions', UNKNOWN);
  const relativePeriod = configValue(data, 'relative_period', UNKNOWN);
  const relativeSessions = configValue(data, 'relative_sessions', UNKNOWN);
  const maSessions = configValue(data, 'ma_sessions', UNKNOWN);
  const earningsDays = configValue(data, 'earnings_days', UNKNOWN);
  return [
    `INDEX ${index} · ${label} · MONITOR OBSERVED TO ${data.as_of || UNKNOWN} · `,
    `TRACKING STARTED ${data.tracking_started || UNKNOWN} · `,
    `DRAWDOWN ${drawdownPeriod} / ${drawdownSessions} SESSIONS · `,
    `RELATIVE ${relativePeriod} / ${relativeSessions} SESSIONS · `,
    `MA ${maSessions} SESSIONS · EARNINGS NEXT ${earningsDays} DAYS · `,
    `HOLDINGS AS OF ${universe.holdings_as_of || UNKNOWN}`,
  ].join(' ');
}

function metaLine(data) {
  const universe = data.universe || {};
  return [
    universe.label || universe.key || UNKNOWN,
    `${universe.members ?? '?'} MEMBERS${universe.watchlist ? ` + ${universe.watchlist} WATCHLIST` : ''}`,
    `OBSERVED TO ${data.as_of || UNKNOWN}`,
    `TRACKING SINCE ${data.tracking_started || UNKNOWN}`,
  ].join(' · ');
}

function modeButton(mode, label, state, onPick) {
  const button = el('button', {
    type: 'button',
    class: 'monitor-mode',
    text: label,
    'aria-pressed': String(state.mode === mode),
  });
  button.addEventListener('click', () => onPick(mode, button));
  return button;
}

function linkTo(tab, ticker) {
  const query = new URLSearchParams({ ticker });
  return el('a', {
    href: `?${query.toString()}#${tab}`,
    text: tab.toUpperCase(),
  });
}

export default function renderMonitor(root, data, manifest) {
  const artifact = data && typeof data === 'object' ? data : {};
  const rows = Array.isArray(artifact.rows) ? artifact.rows : [];
  const relativePeriod = configValue(artifact, 'relative_period', UNKNOWN);
  const maSessions = configValue(artifact, 'ma_sessions', UNKNOWN);
  const storage = safeBrowserStorage();
  const loaded = loadFollowState(storage, FOLLOW_STORAGE_KEY);
  const state = {
    threshold: normalizeThreshold(configValue(artifact, 'threshold_pct', 20)),
    mode: 'today',
    quadrant: '',
    sector: '',
    search: '',
    sort: { key: 'drawdown_pct', direction: 'asc' },
    selected: null,
    followed: new Set(loaded.tickers),
    storageState: loaded,
    pendingImport: null,
    message: null,
  };

  root.replaceChildren();
  root.append(sectionTitle('MONITOR', 'RESEARCH QUEUE · WHAT CHANGED TODAY'));

  const methodHost = el('div', { class: 'monitor-method-host' });
  const noticesHost = el('div', { class: 'monitor-notices' });
  const statsHost = el('div');
  const visualsHost = el('div', { class: 'monitor-visuals' });
  const detailHost = el('div');
  const controlsHost = el('div');
  const messageHost = el('div', { class: 'monitor-messages' });
  const tableHost = el('div');
  root.append(methodHost, noticesHost, statsHost, visualsHost, detailHost, controlsHost, messageHost, tableHost);
  let weights = new Map();

  function select(ticker) {
    state.selected = ticker;
    renderData();
    requestAnimationFrame(() => detailHost.scrollIntoView?.({ behavior: 'smooth', block: 'start' }));
  }

  function setMessage(text, kind = 'notice') {
    state.message = text ? { text, kind } : null;
  }

  function storageNote() {
    if (state.storageState.status === 'corrupt') {
      return 'FOLLOW LIST: saved browser data is corrupt and has been left untouched. Import is validated; repair requires an explicit action.';
    }
    if (state.storageState.status === 'unavailable') {
      return 'FOLLOW LIST: browser-local storage is unavailable. Changes last for this page; export a JSON backup if needed.';
    }
    return 'FOLLOW LIST: saved in this browser only. Following is independent of the threshold and survives outside-universe rows; export a JSON backup for recovery.';
  }

  function toggleFollow(ticker) {
    const next = new Set(state.followed);
    if (next.has(ticker)) next.delete(ticker);
    else next.add(ticker);
    state.followed = next;

    const saved = saveFollowState(storage, FOLLOW_STORAGE_KEY, [...next]);
    if (saved.ok) {
      state.storageState = { status: 'ok', tickers: saved.tickers, raw: null };
      state.pendingImport = null;
      setMessage(`${ticker} ${next.has(ticker) ? 'added to' : 'removed from'} browser-local follows.`);
    } else {
      if (saved.status === 'corrupt') state.pendingImport = new Set(next);
      setMessage(`${ticker} changed for this page, but the browser follow list was not overwritten: ${saved.error || saved.status}.`, 'gap');
    }
    renderAll();
  }

  function downloadFollows() {
    try {
      const blob = new Blob([serializeFollowList([...state.followed])], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const anchor = el('a', { href: url, download: 'market-recap-monitor-follows.json' });
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setMessage(`Exported ${state.followed.size} browser-local follow${state.followed.size === 1 ? '' : 's'}.`);
    } catch (error) {
      setMessage(`Could not export follows: ${error.message}.`, 'gap');
    }
    renderMessage();
  }

  function repairFromPending() {
    if (!state.pendingImport) return;
    const repaired = saveFollowState(
      storage,
      FOLLOW_STORAGE_KEY,
      [...state.pendingImport],
      { allowRepair: true },
    );
    if (repaired.ok) {
      state.followed = new Set(repaired.tickers);
      state.storageState = { status: 'ok', tickers: repaired.tickers, raw: null };
      state.pendingImport = null;
      setMessage('The validated import replaced the corrupt saved follow record by explicit request.');
    } else {
      setMessage(`Saved follow data remains untouched: ${repaired.error || repaired.status}.`, 'gap');
    }
    renderAll();
  }

  async function importFile(file) {
    if (!file) return;
    let parsed;
    try {
      parsed = parseFollowImport(await file.text());
    } catch (error) {
      parsed = { ok: false, error: error.message };
    }
    if (!parsed.ok) {
      setMessage(`Import rejected: ${parsed.error}. No saved data was changed.`, 'gap');
      renderMessage();
      return;
    }

    const merged = mergeFollowLists([...state.followed], parsed.tickers);
    if (state.storageState.status === 'corrupt') {
      state.followed = new Set(merged);
      state.pendingImport = new Set(merged);
      setMessage(`Validated ${parsed.tickers.length} ticker${parsed.tickers.length === 1 ? '' : 's'}; corrupt saved data remains untouched. Click REPAIR WITH IMPORT to replace it explicitly.`);
    } else if (state.storageState.status === 'unavailable') {
      state.followed = new Set(merged);
      setMessage(`Imported ${parsed.tickers.length} ticker${parsed.tickers.length === 1 ? '' : 's'} for this page; browser storage is unavailable, so nothing was persisted.`);
    } else {
      const saved = saveFollowState(storage, FOLLOW_STORAGE_KEY, merged);
      if (saved.ok) {
        state.followed = new Set(saved.tickers);
        state.storageState = { status: 'ok', tickers: saved.tickers, raw: null };
        setMessage(`Imported ${parsed.tickers.length} ticker${parsed.tickers.length === 1 ? '' : 's'} and merged them with existing follows.`);
      } else {
        state.followed = new Set(merged);
        setMessage(`Import was valid but could not be persisted: ${saved.error || saved.status}.`, 'gap');
      }
    }
    renderAll();
  }

  function renderControls() {
    const thresholdInput = el('input', {
      type: 'number',
      min: '1',
      max: '99',
      step: '0.1',
      value: String(state.threshold),
      'aria-label': 'Drawdown threshold percent',
    });
    thresholdInput.addEventListener('input', () => {
      if (thresholdInput.value === '') return;
      state.threshold = normalizeThreshold(thresholdInput.value, state.threshold);
      renderData();
    });
    thresholdInput.addEventListener('change', () => {
      state.threshold = normalizeThreshold(thresholdInput.value, state.threshold);
      thresholdInput.value = String(state.threshold);
      renderData();
    });

    const modeWrap = el('div', { class: 'monitor-modes', role: 'group', 'aria-label': 'Monitor mode' });
    MODES.forEach(([mode, label]) => modeWrap.append(modeButton(mode, label, state, (next, button) => {
      state.mode = next;
      modeWrap.querySelectorAll('button').forEach((node) => {
        node.setAttribute('aria-pressed', String(node === button));
      });
      renderData();
    })));

    const sectorValues = [...new Set(rows.map((row) => row.sector).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b)));
    if (state.sector && !sectorValues.includes(state.sector)) state.sector = '';
    const sectorSelect = el('select', { 'aria-label': 'Sector filter' }, [
      el('option', { value: '', text: 'ALL SECTORS' }),
      ...sectorValues.map((sector) => el('option', { value: sector, text: sector })),
    ]);
    sectorSelect.value = state.sector;
    sectorSelect.addEventListener('change', () => {
      state.sector = sectorSelect.value;
      renderData();
    });

    const searchInput = el('input', {
      type: 'search',
      placeholder: 'ticker / company',
      value: state.search,
      'aria-label': 'Search monitor rows',
    });
    searchInput.addEventListener('input', () => {
      state.search = searchInput.value;
      renderData();
    });

    const fileInput = el('input', { type: 'file', accept: 'application/json,.json', class: 'hidden' });
    fileInput.addEventListener('change', () => {
      const file = fileInput.files && fileInput.files[0];
      if (file) void importFile(file);
    });
    const importButton = el('button', { type: 'button', class: 'monitor-tool', text: 'IMPORT FOLLOWS', title: storageNote() });
    importButton.addEventListener('click', () => fileInput.click());
    const exportButton = el('button', { type: 'button', class: 'monitor-tool', text: 'EXPORT FOLLOWS', title: storageNote() });
    exportButton.addEventListener('click', downloadFollows);

    const actions = el('div', { class: 'monitor-actions' }, [exportButton, importButton, fileInput]);
    if (state.pendingImport && state.storageState.status === 'corrupt') {
      const repair = el('button', { type: 'button', class: 'monitor-tool monitor-repair', text: 'REPAIR WITH IMPORT' });
      repair.addEventListener('click', repairFromPending);
      actions.append(repair);
    }

    controlsHost.replaceChildren(el('div', { class: 'monitor-controls' }, [
      el('div', { class: 'field monitor-threshold' }, [
        el('label', { text: 'DRAWDOWN THRESHOLD %' }),
        thresholdInput,
      ]),
      el('div', { class: 'field monitor-mode-field' }, [
        el('label', { text: 'VIEW' }),
        modeWrap,
      ]),
      el('div', { class: 'field' }, [
        el('label', { text: 'SECTOR' }),
        sectorSelect,
      ]),
      el('div', { class: 'field monitor-search' }, [
        el('label', { text: 'SEARCH' }),
        searchInput,
      ]),
      actions,
    ]));
    if (state.storageState.status !== 'ok') {
      controlsHost.append(el('div', { class: 'monitor-storage-note gap', text: storageNote() }));
    }
  }

  function renderNotices() {
    noticesHost.replaceChildren();
    if (artifact.schema_version !== undefined && artifact.schema_version !== 1) {
      noticesHost.append(gap(`MONITOR artifact schema_version ${raw(artifact.schema_version)} is not supported by this renderer.`));
    }
    for (const message of Array.isArray(artifact.notices) ? artifact.notices : []) {
      if (message) noticesHost.append(notice(String(message)));
    }
  }

  function renderMethod() {
    const band = configValue(artifact, 'revision_pct', '?');
    const paragraphs = [
      artifactNote(artifact),
      'No score and no buy/sell label. Evidence for and against is listed side by side; UNKNOWN is never read as steady.',
      artifact.note ? String(artifact.note) : null,
      `PRICE VS ESTIMATES: each dot is a member at its drawdown from the 1Y high (x) and the 30-day change in its FY1 consensus EPS (y). `
        + `Dot size is the S&P 500 weight; names outside the queue are faint. The y axis is square-root scaled so small revisions separate; the shaded band is ±${band}%, inside which a revision reads as steady. `
        + `Revisions beyond ±${REVISION_CLIP}% are drawn at the edge; the tooltip has the true value. Colour is the price state × evidence state below the chart; none of the four is a buy box.`,
      `QUEUE BY SECTOR: share of each sector's members in the queue at the threshold set below. Red sectors are weak as a whole: the ETF trails the market (cap-weighted) and the median member trails the median of all members (equal-weight) by ≥ ${configValue(artifact, 'sector_event_pp', '?')} pp over ${relativePeriod}.`,
      'EVIDENCE: listed, not weighed. DETERIORATING = anything against; STEADY = nothing against and a live FY1 estimate; otherwise UNKNOWN.',
      'FY1 CONSENSUS EPS is Yahoo earningsTrend for the same fiscal period at each look-back. No estimate is unknown, not unchanged.',
      'HISTORY is observed daily since the MONITOR feature started. Same-day observations replace earlier prints; missing dates stay UNKNOWN; UNKNOWN is never a zero and never an inferred exit. '
        + 'The state log adds a line only when a state changes. Watch/exclude reasons live in config/monitor_notes.toml.',
      storageNote(),
    ].filter(Boolean);
    methodHost.replaceChildren(el('div', { class: 'monitor-meta-row' }, [
      el('div', { class: 'monitor-meta-line', text: metaLine(artifact) }),
      el('details', { class: 'monitor-method' }, [
        el('summary', { text: 'ⓘ METHOD & DATA' }),
        ...paragraphs.map((text) => el('div', { class: 'monitor-method-copy', text })),
      ]),
    ]));
  }

  function renderMessage() {
    messageHost.replaceChildren();
    if (!state.message) return;
    const cls = state.message.kind === 'gap' ? 'gap' : 'notice';
    messageHost.append(el('div', { class: `monitor-message ${cls}`, text: state.message.text }));
  }

  function renderStats(views) {
    const coverage = monitorCoverage(views);
    const threshold = formatThreshold(state.threshold);
    const queued = views.filter(inQueue);
    const groups = todayChanges(artifact, [...state.followed]);
    const count = (kind) => groups.find((group) => group.kind === kind)?.items.length || 0;
    const events = (artifact.sectors || []).filter((sector) => sector.event);
    const expectation = (state) => queued.filter((view) => view.row.expectations?.state === state).length;
    const market = artifact.market_return_pct;
    const median = artifact.members_median_return_pct;
    const breadth = present(market) && present(median) ? median - market : null;
    statsHost.replaceChildren(el('div', { class: 'stat-strip monitor-stat-strip' }, [
      stat('IN QUEUE', String(queued.length), `≤ −${threshold} from high, or ${configValue(artifact, 'peer_excess_pp', '?')} pp behind peers`),
      stat('TODAY', artifact.previous_as_of ? `+${count('entered')} / −${count('left')}` : 'BASELINE',
        artifact.previous_as_of ? `entered / left since ${artifact.previous_as_of}` : 'changes start next session'),
      stat('ESTIMATES CUT', String(expectation('cut')), `in the queue · raised ${expectation('raised')}`, expectation('cut') ? 'down' : ''),
      stat('STABILISING', String(count('stabilising')), `evidence weaker ${count('evidence_down')}`),
      stat('WEAK SECTORS', String(events.length), events.map((sector) => SECTOR_SHORT[sector.sector] || sector.sector).join(', ') || 'none'),
      stat(`BREADTH ${relativePeriod}`, formatPp(breadth), `median member ${formatPct(median)} · index ${formatPct(market)}`, breadth !== null && breadth <= -3 ? 'down' : ''),
      stat('UNKNOWN', String(coverage.unknown), `drawdown not observed · ${coverage.known} known`),
    ]));
  }

  function quadrantColors(p) {
    return { 'weak-steady': p.blue, 'weak-other': p.down, 'stabilising-steady': p.up, 'stabilising-other': p.accent };
  }

  function scatterChart(node, views) {
    const band = Number(configValue(artifact, 'revision_pct', 2)) || 2;
    const revision = (view) => view.row.expectations?.change_30d_pct ?? null;
    const plotted = views.filter((view) => view.inUniverse && view.currentValue !== null && revision(view) !== null);
    const queued = plotted.filter(inQueue);
    const labelled = new Set([
      ...[...queued].filter((view) => weights.has(view.row.ticker))
        .sort((a, b) => weights.get(b.row.ticker) - weights.get(a.row.ticker)).slice(0, 10).map((view) => view.row.ticker),
      ...state.followed,
      state.selected,
    ]);
    const size = (ticker) => {
      const weight = weights.get(ticker);
      return weight ? Math.min(34, 5 + 7 * Math.sqrt(weight)) : 6;
    };
    const tip = (view) => {
      const row = view.row;
      const exp = row.expectations || {};
      return `<b>${escapeHtml(row.ticker)}</b> ${escapeHtml(row.name || '')}<br>`
        + `From 1Y high ${formatPct(view.currentValue)} · vs peers ${formatPp(row.peer_excess_pct)}<br>`
        + `FY1 EPS 30D ${formatPct(exp.change_30d_pct)} (${EXPECTATION_TEXT[exp.state] || UNKNOWN}, ${exp.analysts ?? '?'} analysts)<br>`
        + `Price ${(row.price_state || UNKNOWN).toUpperCase()} · evidence ${(row.evidence_state || UNKNOWN).toUpperCase()}`
        + (weights.has(row.ticker) ? `<br>S&P weight ${num(weights.get(row.ticker), 2)}%` : '');
    };
    const clip = (value) => rootScale(Math.max(-REVISION_CLIP, Math.min(REVISION_CLIP, value)));
    return render(node, (option, p) => {
      const colors = quadrantColors(p);
      const point = (view, color, opacity) => ({
        value: [view.currentValue, clip(revision(view))],
        ticker: view.row.ticker,
        tip: tip(view),
        symbolSize: size(view.row.ticker),
        itemStyle: {
          color,
          opacity,
          borderColor: view.row.ticker === state.selected ? p.text : color,
          borderWidth: view.row.ticker === state.selected ? 2 : 0,
        },
        label: {
          show: labelled.has(view.row.ticker),
          formatter: view.row.ticker,
          position: 'right',
          color: p.text,
          fontSize: 9,
        },
      });
      const outside = plotted.filter((view) => !inQueue(view));
      const groups = QUADRANTS.map((q) => ({
        key: q.key,
        views: queued.filter((view) => quadrantOf(view.row) === q.key),
      }));
      const other = queued.filter((view) => !quadrantOf(view.row));
      const dimmed = (key) => (state.quadrant && state.quadrant !== key ? 0.12 : 0.85);
      const series = [
        {
          type: 'scatter',
          name: 'OUTSIDE',
          data: outside.map((view) => point(view, p.faint, 0.35)),
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{ xAxis: -state.threshold }],
            lineStyle: { color: p.accent, type: 'dashed', width: 1 },
            label: { formatter: `−${formatThreshold(state.threshold)}`, color: p.accent, fontSize: 10 },
          },
          markArea: {
            silent: true,
            itemStyle: { color: p.text, opacity: 0.04 },
            data: [[{ yAxis: rootScale(-band) }, { yAxis: rootScale(band) }]],
          },
        },
        ...groups.map((group) => ({
          type: 'scatter',
          name: group.key,
          labelLayout: { moveOverlap: 'shiftY' },
          data: group.views.map((view) => point(view, colors[group.key], dimmed(group.key))),
        })),
        { type: 'scatter', name: 'OTHER', data: other.map((view) => point(view, p.dim, dimmed(''))) },
      ];
      return {
        ...option,
        grid: { left: 58, right: 24, top: 14, bottom: 42 },
        tooltip: { ...option.tooltip, trigger: 'item', axisPointer: undefined, formatter: (params) => params.data?.tip || '' },
        xAxis: {
          type: 'value',
          max: 0,
          min: (extent) => Math.floor(extent.min / 10) * 10,
          name: 'FROM 1Y HIGH %',
          nameLocation: 'middle',
          nameGap: 26,
          nameTextStyle: { color: p.dim, fontSize: 10 },
          axisLine: { lineStyle: { color: p.border } },
          axisLabel: { color: p.dim, fontSize: 10 },
          splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
        },
        yAxis: {
          type: 'value',
          min: -rootScale(REVISION_CLIP) - 0.1,
          max: rootScale(REVISION_CLIP) + 0.1,
          name: 'FY1 EPS 30D % (√ SCALE)',
          nameLocation: 'middle',
          nameGap: 38,
          nameTextStyle: { color: p.dim, fontSize: 10 },
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: p.dim,
            fontSize: 10,
            customValues: REVISION_TICKS.map(rootScale),
            formatter: (value) => `${value > 0 ? '+' : ''}${Math.round(Math.sign(value) * value * value)}`,
          },
          splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
        },
        graphic: [
          { type: 'text', left: 66, top: 18, style: { text: 'ESTIMATES RAISED ↑', fill: p.faint, font: '10px ui-monospace, Menlo, monospace' } },
          { type: 'text', left: 66, bottom: 50, style: { text: 'ESTIMATES CUT ↓', fill: p.faint, font: '10px ui-monospace, Menlo, monospace' } },
        ],
        series,
      };
    });
  }

  function sectorChart(node, views) {
    const events = new Set((artifact.sectors || []).filter((s) => s.event).map((s) => s.sector));
    const bySector = new Map();
    views.filter((view) => view.inUniverse && view.row.membership === 'index').forEach((view) => {
      const sector = view.row.sector || UNKNOWN;
      const entry = bySector.get(sector) || { members: 0, queued: 0 };
      entry.members += 1;
      if (inQueue(view)) entry.queued += 1;
      bySector.set(sector, entry);
    });
    // Category axes draw bottom-up, so ascending puts the largest share on top.
    const list = [...bySector.entries()]
      .map(([sector, entry]) => ({ sector, ...entry, share: (100 * entry.queued) / entry.members }))
      .sort((a, b) => a.share - b.share);
    return render(node, (option, p) => ({
      ...option,
      grid: { left: 118, right: 52, top: 6, bottom: 24 },
      tooltip: {
        ...option.tooltip,
        trigger: 'item',
        axisPointer: undefined,
        formatter: (params) => {
          const item = list[params.dataIndex];
          return `<b>${escapeHtml(item.sector)}</b><br>${item.queued} of ${item.members} members in the queue`
            + (events.has(item.sector) ? '<br>weak as a whole' : '');
        },
      },
      xAxis: {
        type: 'value',
        max: (extent) => Math.min(100, Math.ceil(extent.max / 10) * 10 + 10),
        axisLabel: { color: p.dim, fontSize: 10, formatter: '{value}%' },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
      },
      yAxis: {
        type: 'category',
        data: list.map((item) => SECTOR_SHORT[item.sector] || item.sector),
        axisLabel: { color: p.dim, fontSize: 10 },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        barMaxWidth: 14,
        data: list.map((item) => ({
          value: Math.round(item.share * 10) / 10,
          sector: item.sector,
          itemStyle: { color: events.has(item.sector) ? p.down : p.accent, opacity: state.sector && state.sector !== item.sector ? 0.3 : 0.85 },
        })),
        label: {
          show: true,
          position: 'right',
          color: p.dim,
          fontSize: 10,
          formatter: (params) => `${list[params.dataIndex].queued}/${list[params.dataIndex].members}`,
        },
      }],
    }));
  }

  function renderVisuals(views) {
    const scatterNode = el('div', { class: 'chart tall' });
    const sectorNode = el('div', { class: 'chart tall' });
    visualsHost.replaceChildren(
      card('PRICE VS ESTIMATES', el('span', { class: 'dim', text: 'click a dot for detail' }), [scatterNode, quadrantBar(views)]),
      card('QUEUE BY SECTOR', el('span', { class: 'dim', text: 'click to filter · red = weak as a whole' }), [sectorNode]),
    );
    scatterChart(scatterNode, views)?.on('click', (params) => {
      if (params.data?.ticker) select(params.data.ticker);
    });
    sectorChart(sectorNode, views)?.on('click', (params) => {
      if (!params.data?.sector) return;
      state.sector = state.sector === params.data.sector ? '' : params.data.sector;
      if (state.sector && state.mode !== 'queue' && state.mode !== 'all') state.mode = 'queue';
      renderControls();
      renderData();
    });
  }

  function tableHeader(columns) {
    return el('thead', {}, [el('tr', {}, columns.map((column) => {
      const active = state.sort.key === column.key;
      const arrow = active ? (state.sort.direction === 'asc' ? ' ↑' : ' ↓') : '';
      const button = el('button', {
        type: 'button',
        class: 'monitor-sort',
        text: `${column.label}${arrow}`,
        'aria-label': `Sort by ${column.label}`,
      });
      button.addEventListener('click', () => {
        state.sort = state.sort.key === column.key
          ? { key: column.key, direction: state.sort.direction === 'asc' ? 'desc' : 'asc' }
          : { key: column.key, direction: 'asc' };
        renderData();
      });
      return el('th', { 'aria-sort': active ? (state.sort.direction === 'asc' ? 'ascending' : 'descending') : 'none' }, [button]);
    }))]);
  }

  function followButton(ticker) {
    const followed = state.followed.has(ticker);
    const button = el('button', {
      type: 'button',
      class: `monitor-follow ${followed ? 'is-followed' : ''}`,
      text: followed ? 'FOLLOWING' : 'FOLLOW',
      title: followed ? `Remove ${ticker} from follows` : `Follow ${ticker}`,
      'aria-pressed': String(followed),
    });
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleFollow(ticker);
    });
    return button;
  }

  function displayRow(view) {
    const row = view.row;
    const ticker = row.ticker || UNKNOWN;
    const changed = view.status === MONITOR_STATUSES.NEWLY_ENTERED
      || view.status === MONITOR_STATUSES.EXITED;
    const tr = el('tr', {
      class: `monitor-row ${state.selected === ticker ? 'is-selected' : ''}`,
      tabindex: '0',
      'aria-selected': String(state.selected === ticker),
    });
    tr.addEventListener('click', () => select(ticker));
    tr.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        select(ticker);
      }
    });
    const exp = row.expectations || null;
    const quadrant = quadrantOf(row);
    const tags = [
      ANOMALY_TAG[row.anomaly],
      row.membership === 'watchlist' ? 'WATCHLIST' : null,
      row.note ? String(row.note.status).toUpperCase() : null,
      changed ? view.status.toUpperCase() : null,
    ].filter(Boolean);
    tr.append(
      el('td', { class: 'monitor-ticker-cell', title: `${row.name || ''}${row.reasons?.length ? ` · ${row.reasons.map((r) => REASON_SHORT[r] || r).join(' · ')}` : ''}` }, [
        el('span', { class: 'monitor-ticker', text: ticker }),
        ...tags.map((tag) => el('span', { class: 'mchip', text: tag })),
        el('span', { class: 'sub monitor-name', text: row.name || DASH }),
      ]),
      el('td', { class: 'dim', text: SECTOR_SHORT[row.sector] || row.sector || UNKNOWN }),
      drawdownCell(view.currentValue, view.currentQualifies, formatPct(view.currentValue)),
      divergingCell(row.peer_excess_pct, 20, formatPp(row.peer_excess_pct), row.peer_count ? `vs ${row.peer_count} sector peers` : ''),
      divergingCell(exp?.change_30d_pct ?? null, 10, exp ? formatPct(exp.change_30d_pct) : UNKNOWN,
        exp ? `${EXPECTATION_TEXT[exp.state] || UNKNOWN} · ${exp.analysts ?? '?'} analysts` : 'no estimates'),
      el('td', { class: `monitor-price-${row.price_state || 'unknown'}`, text: (row.price_state || UNKNOWN).toUpperCase() }),
      el('td', { class: `monitor-evidence-${row.evidence_state || 'unknown'}`, title: `${(row.evidence_for || []).length} for · ${(row.evidence_against || []).length} against`, text: (row.evidence_state || UNKNOWN).toUpperCase() }),
      el('td', { text: formatPercentile(row.pe_percentile) }),
      el('td', { class: row.earnings_date ? '' : 'dim', title: row.earnings_status || '', text: row.earnings_date || DASH }),
      el('td', { class: directionClass(row.since_first_seen_pct), title: row.first_seen ? `since ${row.first_seen.date}` : '', text: present(row.since_first_seen_pct) ? pct(row.since_first_seen_pct, 1) : DASH }),
      el('td', { class: 'monitor-follow-cell' }, [followButton(ticker)]),
    );
    if (quadrant) tr.dataset.quadrant = quadrant;
    return tr;
  }

  const columns = [
    { key: 'ticker', label: 'TICKER' },
    { key: 'sector', label: 'SECTOR' },
    { key: 'drawdown_pct', label: 'FROM 1Y HIGH' },
    { key: 'peer_excess_pct', label: `VS PEERS ${relativePeriod}` },
    { key: 'estimate_revision', label: 'FY1 EPS 30D' },
    { key: 'price_state', label: 'PRICE' },
    { key: 'evidence_state', label: 'EVIDENCE' },
    { key: 'pe_percentile', label: 'P/E PCTL' },
    { key: 'earnings_date', label: 'EARNINGS' },
    { key: 'since_first_seen_pct', label: 'SINCE SEEN' },
    { key: 'followed', label: '' },
  ];

  // The scatter's legend doubles as the price × evidence filter.
  function quadrantBar(views) {
    const queued = views.filter(inQueue);
    const counts = new Map(QUADRANTS.map((q) => [q.key, 0]));
    queued.forEach((view) => {
      const key = quadrantOf(view.row);
      if (counts.has(key)) counts.set(key, counts.get(key) + 1);
    });
    const colors = { 'weak-steady': 'var(--blue)', 'weak-other': 'var(--down)', 'stabilising-steady': 'var(--up)', 'stabilising-other': 'var(--accent)' };
    const buttons = QUADRANTS.map((q) => {
      const button = el('button', {
        type: 'button',
        class: `monitor-quadrant q-${q.key}`,
        title: `${q.label} · click to filter the table`,
        'aria-pressed': String(state.quadrant === q.key),
      }, [
        el('span', { class: 'monitor-swatch', style: `background:${colors[q.key]}` }),
        el('span', { text: QUADRANT_SHORT[q.key] }),
        el('span', { class: 'monitor-quadrant-count', text: String(counts.get(q.key)) }),
      ]);
      button.addEventListener('click', () => {
        state.quadrant = state.quadrant === q.key ? '' : q.key;
        if (state.mode !== 'queue' && state.mode !== 'following' && state.mode !== 'all') state.mode = 'queue';
        renderControls();
        renderData();
      });
      return button;
    });
    return el('div', { class: 'monitor-quadrants' }, [
      el('span', { class: 'dim', text: 'PRICE · EVIDENCE' }),
      ...buttons,
    ]);
  }

  function changeRow(change) {
    const row = rows.find((candidate) => candidate.ticker === change.ticker) || {};
    const tr = el('tr', { class: 'monitor-row', tabindex: '0' }, [
      el('td', { class: 'wrap-cell monitor-ticker-cell' }, [
        el('span', { class: 'monitor-ticker', text: change.ticker }),
        el('span', { class: 'sub', text: `${row.name || ''}${change.followed ? ' · FOLLOWED' : ''}${row.note?.status === 'watch' ? ' · WATCH' : ''}` }),
      ]),
      el('td', { class: 'wrap-cell dim', text: change.sector || UNKNOWN }),
      el('td', { class: 'dim', text: ANOMALY_TEXT[change.anomaly] || DASH }),
      el('td', { class: 'wrap-cell monitor-why', text: change.text || '' }),
      el('td', { class: row.drawdown_pct === null || row.drawdown_pct === undefined ? 'dim' : 'down', text: formatPct(row.drawdown_pct) }),
      el('td', { class: directionClass(row.peer_excess_pct), text: formatPp(row.peer_excess_pct) }),
      el('td', { class: 'dim', text: `${(row.price_state || UNKNOWN).toUpperCase()} · ${(row.evidence_state || UNKNOWN).toUpperCase()}` }),
      el('td', { class: 'dim', text: row.earnings_date || DASH }),
    ]);
    const open = () => select(change.ticker);
    tr.addEventListener('click', open);
    tr.addEventListener('keydown', (event) => { if (event.key === 'Enter') open(); });
    return tr;
  }

  function renderToday() {
    tableHost.replaceChildren();
    // The first build's queue is all baseline, not news; it is under QUEUE.
    const groups = todayChanges(artifact, [...state.followed])
      .filter((group) => group.kind !== 'first_observed');
    if (!groups.length) {
      tableHost.append(el('div', { class: 'monitor-detail-empty', text: artifact.previous_as_of
        ? `No queue changes between ${artifact.previous_as_of} and ${artifact.as_of}.`
        : `Baseline build ${artifact.as_of || UNKNOWN}: changes are listed from the next session. The queue is under QUEUE.` }));
    }
    for (const group of groups) {
      tableHost.append(card(group.label, el('span', { class: 'dim', text: String(group.items.length) }),
        table(['TICKER', 'SECTOR', 'TYPE', 'WHY TODAY', 'FROM 1Y HIGH', `VS PEERS ${relativePeriod}`, 'PRICE · EVIDENCE', 'EARNINGS'],
          group.items.map(changeRow), { class: 'monitor-change-table' })));
    }
  }

  function renderSectors() {
    tableHost.replaceChildren();
    const sectors = Array.isArray(artifact.sectors) ? artifact.sectors : [];
    if (!sectors.length) { tableHost.append(gap('No sector summary in this artifact.')); return; }
    const share = (value) => (value === null || value === undefined ? UNKNOWN : pct(value * 100, 0));
    tableHost.append(table(
      ['SECTOR', 'ETF', `ETF ${relativePeriod}`, 'ETF VS MARKET', 'MEDIAN MEMBER VS ALL MEMBERS', 'MEMBERS DOWN', 'PAST THRESHOLD', 'IN QUEUE', `ABOVE MA${maSessions} NOW / 5 SESSIONS AGO`, 'EVENT'],
      sectors.map((sector) => el('tr', { class: sector.event ? 'emphasis' : '' }, [
        el('td', { text: sector.sector }),
        el('td', { class: 'dim', text: sector.etf || DASH }),
        el('td', { class: directionClass(sector.etf_return_pct), text: formatPct(sector.etf_return_pct) }),
        el('td', { class: directionClass(sector.etf_excess_pct), text: formatPp(sector.etf_excess_pct) }),
        el('td', { class: directionClass(sector.median_excess_pct), text: formatPp(sector.median_excess_pct) }),
        el('td', { text: `${share(sector.down_share)} of ${sector.members}` }),
        el('td', { text: share(sector.drawdown_share) }),
        el('td', { text: String(sector.candidates) }),
        el('td', { text: `${share(sector.above_ma_share)} / ${share(sector.above_ma_share_before)}` }),
        el('td', { class: sector.event ? 'down' : 'dim', text: sector.event ? 'WEAK AS A WHOLE' : DASH }),
      ])),
    ));
  }

  function renderTable(filtered) {
    tableHost.replaceChildren();
    if (!filtered.length) {
      const modeLabel = MODES.find(([mode]) => mode === state.mode)?.[1] || state.mode.toUpperCase();
      tableHost.append(gap(`No rows match ${modeLabel} at ≤ −${formatThreshold(state.threshold)} with the current filters.`));
      return;
    }
    const node = el('table', { class: 'data monitor-table' }, [
      tableHeader(columns),
      el('tbody', {}, filtered.map(displayRow)),
    ]);
    tableHost.append(el('div', { class: 'table-scroll' }, [node]));
  }

  function provenanceTable(row) {
    const universe = artifact.universe || {};
    const rowsForTable = [
      ['ARTIFACT AS OF', artifact.as_of],
      ['TRACKING STARTED', artifact.tracking_started],
      ['BUILD GENERATED', manifest?.generated_at],
      ['UNIVERSE', `${universe.key || UNKNOWN} · ${universe.label || UNKNOWN}`],
      ['HOLDINGS AS OF', universe.holdings_as_of],
      ['FILED', row.filed],
      ['PERIOD END', row.period_end],
      ['EARNINGS DATE', row.earnings_date],
      ['EARNINGS STATUS', row.earnings_status],
      ['ESTIMATE REVISION', row.estimate_revision],
    ];
    return table(['PROVENANCE FIELD', 'RAW VALUE'], rowsForTable.map(([label, value]) => el('tr', {}, [
      el('td', { class: 'dim', text: label }),
      el('td', { class: 'wrap-cell', text: raw(value) }),
    ])));
  }

  function rawMetricsTable(row) {
    return table(['RAW METRIC', 'VALUE'], RAW_FIELDS.map(([key, label]) => el('tr', {}, [
      el('td', { class: 'dim', text: label }),
      el('td', { class: 'wrap-cell', text: raw(row[key]) }),
    ])));
  }

  function historyTable(view) {
    const threshold = normalizeThreshold(state.threshold);
    const historyRows = view.history.map(([date, value]) => {
      const inPool = value !== null && value <= -threshold;
      return el('tr', { class: date === view.latestDate ? 'emphasis' : '' }, [
        el('td', { text: date }),
        el('td', { class: value === null ? 'dim' : inPool ? 'down' : 'flat', text: raw(value) }),
        el('td', { class: value === null ? 'dim' : inPool ? 'down' : 'flat', text: value === null ? UNKNOWN : inPool ? 'IN POOL' : 'OUTSIDE' }),
      ]);
    });
    return table(['DATE', 'DRAWDOWN % (RAW)', `AT ≤ −${formatThreshold(threshold)}`], historyRows);
  }

  function gapsBlock(row) {
    const gaps = Array.isArray(row.gaps) ? row.gaps.filter(Boolean) : [];
    return el('div', { class: 'monitor-gaps' }, [
      el('div', { class: 'monitor-detail-label', text: 'DATA GAPS / REASONS' }),
      gaps.length
        ? el('ul', { class: 'monitor-gap-list' }, gaps.map((message) => el('li', { text: String(message) })))
        : el('div', { class: 'dim', text: 'NONE RECORDED' }),
    ]);
  }

  function priceCard(row, view) {
    const node = el('div', { class: 'chart' });
    const status = el('div', { class: 'dim', text: 'Loading price history…' });
    const body = card('PRICE · 1Y', el('span', { class: 'dim', text: `close · MA${maSessions} · 1Y high · −${formatThreshold(state.threshold)} line` }), [node, status]);
    loadTicker(row.ticker).then((payload) => {
      if (!node.isConnected) return;
      const dates = (payload.dates || []).slice(-252);
      const close = (payload.close || []).slice(-252);
      if (!close.length) { status.textContent = 'No price history in this build.'; return; }
      status.remove();
      const window = Number(maSessions) || 20;
      const full = payload.close || [];
      const offset = full.length - close.length;
      const ma = close.map((_, i) => {
        const end = offset + i + 1;
        if (end < window) return null;
        const slice = full.slice(end - window, end);
        return Math.round((slice.reduce((a, b) => a + b, 0) / window) * 100) / 100;
      });
      const high = Math.max(...close.filter((v) => v !== null));
      const floor = high * (1 - state.threshold / 100);
      const firstSeen = row.first_seen?.date;
      render(node, (option, p) => ({
        ...option,
        grid: { ...option.grid, right: 56 },
        xAxis: { ...option.xAxis, data: dates },
        series: [
          {
            type: 'line', name: 'CLOSE', data: close, showSymbol: false, lineStyle: { width: 1.4, color: p.accent },
            markLine: {
              silent: true,
              symbol: 'none',
              data: [
                { yAxis: high, lineStyle: { color: p.faint, type: 'dashed' }, label: { formatter: '1Y HIGH', color: p.dim, fontSize: 9 } },
                { yAxis: floor, lineStyle: { color: p.down, type: 'dashed', opacity: 0.7 }, label: { formatter: `−${formatThreshold(state.threshold)}`, color: p.down, fontSize: 9 } },
                ...(firstSeen && dates.includes(firstSeen) ? [{ xAxis: firstSeen, lineStyle: { color: p.blue, type: 'dotted' }, label: { formatter: 'FIRST SEEN', color: p.blue, fontSize: 9 } }] : []),
              ],
            },
          },
          { type: 'line', name: `MA${window}`, data: ma, showSymbol: false, lineStyle: { width: 1, color: p.blue, opacity: 0.8 } },
        ],
      }));
    }).catch((error) => { status.textContent = error.message; });
    return body;
  }

  function epsCard(exp) {
    if (!exp) {
      return card('FY1 CONSENSUS EPS', null, el('div', { class: 'dim', text: 'No estimates for this name in this build.' }));
    }
    const points = [['90D AGO', exp.eps_90d], ['60D AGO', exp.eps_60d], ['30D AGO', exp.eps_30d], ['7D AGO', exp.eps_7d], ['NOW', exp.eps]]
      .filter(([, value]) => present(value));
    const node = el('div', { class: 'chart' });
    const state30 = EXPECTATION_TEXT[exp.state] || UNKNOWN;
    const body = card('FY1 CONSENSUS EPS', el('span', { class: `${directionClass(exp.change_30d_pct)}`, text: `${state30} · 30D ${formatPct(exp.change_30d_pct)} · 90D ${formatPct(exp.change_90d_pct)}` }), [
      node,
      el('div', { class: 'monitor-chart-foot dim', text: `FY ending ${exp.fiscal_year_end || UNKNOWN} · ${exp.up_30d ?? '?'} up / ${exp.down_30d ?? '?'} down in 30D · ${exp.analysts ?? '?'} analysts · range ${present(exp.low) ? num(exp.low, 2) : '?'}–${present(exp.high) ? num(exp.high, 2) : '?'}` }),
    ]);
    requestAnimationFrame(() => render(node, (option, p) => ({
      ...option,
      grid: { ...option.grid, top: 26, right: 30 },
      xAxis: { ...option.xAxis, boundaryGap: true, data: points.map(([label]) => label) },
      series: [{
        type: 'line',
        symbolSize: 7,
        lineStyle: { width: 1.4, color: p.accent },
        itemStyle: { color: p.accent },
        data: points.map(([, value]) => Math.round(value * 100) / 100),
        label: { show: true, position: 'top', color: p.text, fontSize: 10, formatter: (q) => num(q.value, 2) },
      }],
    })));
    return body;
  }

  function evidenceCard(row) {
    const chips = (items, cls) => (items || []).length
      ? el('div', { class: 'monitor-evidence-chips' }, items.map((item) => el('span', { class: `mchip ${cls}`, text: item })))
      : el('div', { class: 'dim', text: 'nothing recorded' });
    return card('EVIDENCE', el('span', { class: `monitor-evidence-${row.evidence_state || 'unknown'}`, text: (row.evidence_state || UNKNOWN).toUpperCase() }), [
      el('div', { class: 'grid two monitor-evidence' }, [
        el('div', {}, [el('div', { class: 'monitor-detail-label', text: 'FOR' }), chips(row.evidence_for, 'up')]),
        el('div', {}, [el('div', { class: 'monitor-detail-label', text: 'AGAINST' }), chips(row.evidence_against, 'down')]),
      ]),
    ]);
  }

  function renderDetail(view) {
    detailHost.replaceChildren();
    if (!view) return;
    const row = view.row;
    const ticker = row.ticker || UNKNOWN;
    const heading = el('div', { class: 'monitor-detail-heading' }, [
      el('div', {}, [
        el('div', { class: 'monitor-detail-ticker', text: ticker }),
        el('div', { class: 'monitor-detail-name', text: `${row.name || UNKNOWN} · ${row.sector || UNKNOWN}` }),
      ]),
      el('div', { class: 'monitor-detail-actions' }, [
        el('span', { class: 'monitor-detail-links' }, [linkTo('technicals', ticker), ' · ', linkTo('valuation', ticker), ' · ', linkTo('financials', ticker)]),
        followButton(ticker),
        el('button', { type: 'button', class: 'monitor-tool', text: 'CLOSE', onclick: () => { state.selected = null; renderData(); } }),
      ]),
    ]);
    const summary = el('div', { class: 'stat-strip monitor-detail-stats' }, [
      stat('FROM 1Y HIGH', formatPct(view.currentValue), view.stale ? `last observed ${view.latestDate}` : view.status.toUpperCase(), view.currentQualifies ? 'down' : ''),
      stat(`VS PEERS ${relativePeriod}`, formatPp(row.peer_excess_pct), row.peer_count ? `${row.peer_count} peers, equal weight` : 'no peer basket', directionClass(row.peer_excess_pct)),
      stat(`VS MARKET ${relativePeriod}`, formatPp(row.market_excess_pct), `${row.sector_benchmark || 'sector ETF'} ${formatPp(row.sector_excess_pct)}`, directionClass(row.market_excess_pct)),
      stat('PRICE', (row.price_state || UNKNOWN).toUpperCase(), `RS ${row.rs_improving === true ? 'improving' : row.rs_improving === false ? 'not improving' : UNKNOWN} · ${row.above_ma === true ? 'above' : row.above_ma === false ? 'below' : '?'} MA${maSessions}`, `monitor-price-${row.price_state || 'unknown'}`),
      stat('P/E', present(row.pe) ? num(row.pe, 1) : UNKNOWN, `${formatPercentile(row.pe_percentile)} of own 10Y`),
      stat('NEXT EARNINGS', row.earnings_date || DASH, row.earnings_status === 'not_scheduled'
        ? `none in the next ${configValue(artifact, 'earnings_days', '?')} days` : (row.earnings_status || '').replaceAll('_', ' ')),
    ]);
    const log = Array.isArray(row.state_log) ? row.state_log : [];
    const reported = row.reported;
    const historyLines = [
      row.first_seen
        ? `FIRST SEEN ${row.first_seen.date}${row.first_seen.baseline ? ' (baseline)' : ''} · ${(row.first_seen.reasons || []).map((r) => REASON_TEXT[r] || r).join(', ')}`
          + (row.first_seen.date !== artifact.as_of ? ` · since then ${formatPct(row.since_first_seen_pct)} vs peers ${formatPct(row.peers_since_first_seen_pct)}` : '')
        : 'Never in the queue since tracking began.',
      reported ? `Last reported ${reported.date}${reported.fiscal_quarter ? ` (${reported.fiscal_quarter})` : ''}: EPS ${reported.eps ?? '?'} vs ${reported.eps_forecast ?? '?'} expected${present(reported.return_1d) ? `, stock ${pct(reported.return_1d, 1)} next session` : ''}` : null,
      row.note ? `${String(row.note.status).toUpperCase()}${row.note.since ? ` since ${row.note.since}` : ''}: ${row.note.reason}${row.note.outcome ? ` → ${row.note.outcome}` : ''}` : null,
    ].filter(Boolean);
    const historyCard = card('CANDIDATE HISTORY', null, [
      el('div', { class: 'monitor-timeline' }, historyLines.map((text) => el('div', { text }))),
      log.length > 1 ? table(['FROM', 'IN QUEUE', 'PRICE', 'EVIDENCE'], [...log].reverse().map((entry) => el('tr', {}, [
        el('td', { text: entry[0] }),
        el('td', { text: entry[1] === null ? UNKNOWN : entry[1] ? 'YES' : 'NO' }),
        el('td', { text: (entry[2] || UNKNOWN).toUpperCase() }),
        el('td', { text: (entry[3] || UNKNOWN).toUpperCase() }),
      ]))) : null,
    ]);
    const rawData = el('details', { class: 'monitor-method monitor-raw' }, [
      el('summary', { text: 'RAW DATA · PROVENANCE · OBSERVED HISTORY' }),
      el('div', { class: 'grid two monitor-detail-grid' }, [
        card('RAW MONITOR METRICS', null, rawMetricsTable(row)),
        card('PROVENANCE / COVERAGE', null, [provenanceTable(row), gapsBlock(row)]),
      ]),
      card('OBSERVED HISTORY — THRESHOLD VIEW', null, historyTable(view)),
    ]);
    detailHost.append(el('div', { class: 'monitor-detail' }, [
      heading,
      summary,
      el('div', { class: 'grid two monitor-detail-grid' }, [priceCard(row, view), epsCard(row.expectations || null)]),
      el('div', { class: 'grid two monitor-detail-grid' }, [evidenceCard(row), historyCard]),
      rawData,
    ]));
  }

  function renderData() {
    const views = deriveMonitorRows(artifact, state.threshold, [...state.followed]);
    const selected = state.selected ? views.find((view) => view.row.ticker === state.selected) : null;
    renderStats(views);
    renderVisuals(views);
    if (state.mode === 'today') renderToday();
    else if (state.mode === 'sectors') renderSectors();
    else {
      const filtered = sortMonitorRows(
        filterMonitorRows(views, {
          mode: state.mode,
          sector: state.sector,
          search: state.search,
          quadrant: state.quadrant,
        }),
        state.sort.key,
        state.sort.direction,
      );
      renderTable(filtered);
    }
    renderDetail(selected || null);
  }

  function renderAll() {
    renderNotices();
    renderControls();
    renderMethod();
    renderMessage();
    renderData();
  }

  if (!rows.length) {
    setMessage('The MONITOR artifact contains no rows. No automatic pool or score is inferred.', 'gap');
  }
  renderAll();
  loadWeights().then((loaded) => {
    weights = loaded;
    if (weights.size && root.isConnected) renderData();
  });
}
