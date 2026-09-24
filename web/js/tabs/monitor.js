// MONITOR: a static, prospective drawdown queue.  The artifact is the only
// data source for this tab; there are deliberately no browser feed requests.

import { el, card, table, num, pct, sectionTitle, notice, gap, DASH } from '../fmt.js';
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

function factCell(value, label) {
  const known = value === true || value === false;
  const text = known ? (value ? 'YES' : 'NO') : UNKNOWN;
  const box = el('input', {
    type: 'checkbox',
    disabled: '',
    tabindex: '-1',
    'aria-label': `${label}: ${text}`,
  });
  box.checked = value === true;
  box.indeterminate = !known;
  return el('span', { class: `monitor-fact ${known ? (value ? 'is-yes' : 'is-no') : 'is-unknown'}` }, [
    box,
    el('span', { text }),
  ]);
}

function statusClass(status) {
  return `monitor-status-${String(status || 'unknown').replaceAll(' ', '-')}`;
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
  return el('div', { class: 'monitor-meta' }, [
    el('div', { class: 'monitor-meta-line', text: [
      `INDEX ${index} · ${label} · MONITOR OBSERVED TO ${data.as_of || UNKNOWN} · `,
      `TRACKING STARTED ${data.tracking_started || UNKNOWN} · `,
      `DRAWDOWN ${drawdownPeriod} / ${drawdownSessions} SESSIONS · `,
      `RELATIVE ${relativePeriod} / ${relativeSessions} SESSIONS · `,
      `MA ${maSessions} SESSIONS · EARNINGS NEXT ${earningsDays} DAYS · `,
      `HOLDINGS AS OF ${universe.holdings_as_of || UNKNOWN}`,
    ].join(' ') }),
  ]);
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
  root.append(artifactNote(artifact));

  const noticesHost = el('div', { class: 'monitor-notices' });
  const controlsHost = el('div');
  const methodHost = el('div', { class: 'monitor-method-host' });
  const messageHost = el('div', { class: 'monitor-messages' });
  const statsHost = el('div');
  const tableHost = el('div');
  const detailHost = el('div');
  root.append(noticesHost, controlsHost, methodHost, messageHost, statsHost, detailHost, tableHost);

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
    const importButton = el('button', { type: 'button', class: 'monitor-tool', text: 'IMPORT FOLLOWS' });
    importButton.addEventListener('click', () => fileInput.click());
    const exportButton = el('button', { type: 'button', class: 'monitor-tool', text: 'EXPORT FOLLOWS' });
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
      el('div', { class: 'monitor-storage-note' }, [storageNote()]),
    ]));
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
    const details = el('details', { class: 'monitor-method' }, [
      el('summary', { text: 'METHOD & DATA' }),
      artifact.note
        ? el('div', { class: 'monitor-method-copy', text: String(artifact.note) })
        : el('div', { class: 'monitor-method-copy', text: 'No additional artifact method note was supplied.' }),
    ]);
    methodHost.replaceChildren(
      details,
      el('div', { class: 'monitor-plain-note', text: 'No score and no buy/sell label. Evidence for and against is listed side by side; UNKNOWN is never read as steady.' }),
    );
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
    statsHost.replaceChildren(el('div', { class: 'stat-strip monitor-stat-strip' }, [
      stat('IN QUEUE', String(queued.length), `≤ −${threshold} from high, or ${configValue(artifact, 'peer_excess_pp', '?')} pp behind peers`),
      stat('TODAY', `+${count('entered') + count('first_observed')} / −${count('left')}`, 'entered / left the queue'),
      stat('STABILISING', String(count('stabilising')), `evidence weaker: ${count('evidence_down')}`),
      stat('WEAK SECTORS', String(events.length), events.map((sector) => sector.sector).join(', ') || 'none'),
      stat('UNKNOWN DRAWDOWN', String(coverage.unknown), `${coverage.known} of ${coverage.universe} known`),
      stat('OBSERVED TO', artifact.as_of || UNKNOWN, artifact.previous_as_of ? `previous build ${artifact.previous_as_of}` : `tracking from ${artifact.tracking_started || UNKNOWN}`),
    ]));
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
    const statusNode = el('td', { class: `monitor-status ${statusClass(view.status)}` }, [
      el('span', { text: view.status.toUpperCase() }),
      changed
        ? el('span', { class: 'sub', text: `since previous observation ${view.previousDate || UNKNOWN}` })
        : null,
    ]);
    const tr = el('tr', {
      class: `monitor-row ${state.selected === ticker ? 'is-selected' : ''}`,
      tabindex: '0',
      'aria-selected': String(state.selected === ticker),
    });
    const select = () => {
      state.selected = ticker;
      renderData();
      requestAnimationFrame(() => {
        if (typeof detailHost.scrollIntoView === 'function') {
          detailHost.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    };
    tr.addEventListener('click', select);
    tr.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        select();
      }
    });
    const exp = row.expectations || null;
    const quadrant = quadrantOf(row);
    tr.append(
      el('td', { class: 'wrap-cell monitor-ticker-cell' }, [
        el('span', { class: 'monitor-ticker', text: ticker }),
        el('span', { class: 'sub', text: [row.name || DASH, row.membership === 'watchlist' ? ' · WATCHLIST' : '',
          row.note ? ` · ${String(row.note.status).toUpperCase()}` : ''].join('') }),
      ]),
      el('td', { class: 'wrap-cell dim', text: row.sector || UNKNOWN }),
      el('td', { class: 'wrap-cell monitor-anomaly' }, [
        el('span', { text: ANOMALY_TEXT[row.anomaly] || (row.candidate === false ? DASH : UNKNOWN) }),
        el('span', { class: 'sub', text: (row.reasons || []).map((r) => REASON_SHORT[r] || r).join(' · ') }),
      ]),
      el('td', { class: view.currentQualifies === null ? 'dim' : view.currentQualifies ? 'down' : 'flat', text: formatPct(view.currentValue) }),
      el('td', { class: `wrap-cell ${directionClass(row.peer_excess_pct)}` }, [
        el('span', { text: formatPp(row.peer_excess_pct) }),
        el('span', { class: 'sub', text: row.peer_count ? `vs ${row.peer_count} peers` : '' }),
      ]),
      el('td', { class: directionClass(row.sector_excess_pct), text: formatPp(row.sector_excess_pct) }),
      el('td', { class: `monitor-price-${row.price_state || 'unknown'}`, text: (row.price_state || UNKNOWN).toUpperCase() }),
      el('td', { class: 'wrap-cell' }, [
        el('span', { class: `monitor-evidence-${row.evidence_state || 'unknown'}`, text: (row.evidence_state || UNKNOWN).toUpperCase() }),
        el('span', { class: 'sub', text: `${(row.evidence_for || []).length} for · ${(row.evidence_against || []).length} against` }),
      ]),
      el('td', { class: 'wrap-cell' }, [
        el('span', { class: directionClass(exp?.change_30d_pct), text: exp ? formatPct(exp.change_30d_pct) : UNKNOWN }),
        el('span', { class: 'sub', text: exp ? `${EXPECTATION_TEXT[exp.state] || UNKNOWN} · ${exp.analysts ?? '?'} an.` : '' }),
      ]),
      el('td', { text: formatPercentile(row.pe_percentile) }),
      el('td', { class: 'wrap-cell monitor-earnings-cell' }, [
        el('span', { text: row.earnings_date || (row.earnings_status === 'not_scheduled' ? DASH : UNKNOWN) }),
        el('span', { class: 'sub', text: row.earnings_date ? (row.earnings_status || '') : (row.earnings_status === 'not_scheduled' ? `none in ${configValue(artifact, 'earnings_days', '?')}d` : '') }),
      ]),
      el('td', { class: 'wrap-cell' }, [
        el('span', { class: directionClass(row.since_first_seen_pct), text: formatPct(row.since_first_seen_pct) }),
        el('span', { class: 'sub', text: row.first_seen ? `since ${row.first_seen.date}${row.peers_since_first_seen_pct !== null && row.peers_since_first_seen_pct !== undefined ? ` · peers ${pct(row.peers_since_first_seen_pct, 1)}` : ''}` : '' }),
      ]),
      el('td', { class: 'monitor-follow-cell' }, [followButton(ticker)]),
    );
    if (quadrant) tr.dataset.quadrant = quadrant;
    return tr;
  }

  const columns = [
    { key: 'ticker', label: 'TICKER / NAME' },
    { key: 'sector', label: 'SECTOR' },
    { key: 'anomaly', label: 'ANOMALY' },
    { key: 'drawdown_pct', label: 'DRAWDOWN' },
    { key: 'peer_excess_pct', label: `VS PEERS ${relativePeriod}` },
    { key: 'sector_excess_pct', label: `VS SECTOR ETF ${relativePeriod}` },
    { key: 'price_state', label: 'PRICE' },
    { key: 'evidence_state', label: 'EVIDENCE' },
    { key: 'estimate_revision', label: 'FY1 EPS 30D' },
    { key: 'pe_percentile', label: 'P/E PCTL' },
    { key: 'earnings_date', label: 'NEXT EARNINGS' },
    { key: 'since_first_seen_pct', label: 'SINCE FIRST SEEN' },
    { key: 'followed', label: 'FOLLOW' },
  ];

  function quadrantBar(views) {
    const queued = views.filter(inQueue);
    const counts = new Map(QUADRANTS.map((q) => [q.key, 0]));
    queued.forEach((view) => {
      const key = quadrantOf(view.row);
      if (counts.has(key)) counts.set(key, counts.get(key) + 1);
    });
    const unknownCount = queued.length - [...counts.values()].reduce((a, b) => a + b, 0);
    const buttons = QUADRANTS.map((q) => {
      const button = el('button', {
        type: 'button',
        class: `monitor-quadrant q-${q.key}`,
        'aria-pressed': String(state.quadrant === q.key),
      }, [el('span', { class: 'monitor-quadrant-count', text: String(counts.get(q.key)) }), el('span', { text: q.label })]);
      button.addEventListener('click', () => {
        state.quadrant = state.quadrant === q.key ? '' : q.key;
        if (state.mode !== 'queue' && state.mode !== 'following' && state.mode !== 'all') state.mode = 'queue';
        renderControls();
        renderData();
      });
      return button;
    });
    return el('div', { class: 'monitor-quadrants' }, [
      ...buttons,
      el('div', { class: 'monitor-quadrant-note', text: `Queue names by price state × evidence state. ${unknownCount} without a price state. Click to filter; none of the four is a buy box.` }),
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
    const open = () => { state.selected = change.ticker; renderData(); detailHost.scrollIntoView?.({ behavior: 'smooth', block: 'start' }); };
    tr.addEventListener('click', open);
    tr.addEventListener('keydown', (event) => { if (event.key === 'Enter') open(); });
    return tr;
  }

  function sectorEventCard(sector, items) {
    const repair = sector.above_ma_share !== null && sector.above_ma_share_before !== null
      ? `${pct(sector.above_ma_share * 100, 0)} above MA${maSessions} (${pct(sector.above_ma_share_before * 100, 0)} on ${sector.repair_since})`
      : `above MA${maSessions}: ${UNKNOWN}`;
    return el('div', { class: 'monitor-sector-event' }, [
      el('div', { class: 'monitor-sector-head' }, [
        el('span', { class: 'monitor-ticker', text: sector.sector.toUpperCase() }),
        el('span', { class: 'dim', text: ` ${sector.etf || ''} ${formatPp(sector.etf_excess_pct)} vs market · median member ${formatPp(sector.median_excess_pct)} vs all members · ${sector.down_share !== null ? pct(sector.down_share * 100, 0) : UNKNOWN} of ${sector.members} down over ${relativePeriod} · ${repair}` }),
      ]),
      el('div', { class: 'monitor-sector-names', text: items.length
        ? `Entered today as part of it: ${items.map((c) => c.ticker).join(', ')}`
        : `${sector.candidates} of ${sector.members} members in the queue` }),
    ]);
  }

  function breadthNote() {
    const market = artifact.market_return_pct;
    const median = artifact.members_median_return_pct;
    if (!present(market) || !present(median) || Math.abs(market - median) < 3) return null;
    return `NARROW MARKET: over ${relativePeriod} the market proxy is ${pct(market, 1)} and the median member ${pct(median, 1)}. `
      + 'Much of the drawdown queue is market-wide weakness under a few large winners, not a sector or company event.';
  }

  function renderToday() {
    tableHost.replaceChildren();
    const groups = todayChanges(artifact, [...state.followed]);
    const events = (artifact.sectors || []).filter((sector) => sector.event);
    const breadth = breadthNote();
    if (breadth) tableHost.append(notice(breadth));
    if (!artifact.previous_as_of) {
      tableHost.append(notice(`First MONITOR build (${artifact.as_of || UNKNOWN}): everything in the queue is a baseline observation, not a new entry. Changes are listed from the next session. See QUEUE.`));
    }
    if (events.length) {
      const sectorEntries = new Map();
      groups.forEach((group) => group.items
        .filter((c) => c.anomaly === 'sector' && (c.kind === 'entered' || c.kind === 'first_observed'))
        .forEach((c) => { if (!sectorEntries.has(c.sector)) sectorEntries.set(c.sector, []); sectorEntries.get(c.sector).push(c); }));
      tableHost.append(card('SECTOR EVENTS', el('span', { class: 'dim', text: `trailing by ≥ ${configValue(artifact, 'sector_event_pp', '?')} pp over ${relativePeriod}, cap- and equal-weighted` }),
        events.map((sector) => sectorEventCard(sector, sectorEntries.get(sector.sector) || []))));
    }
    const shown = groups.map((group) => ({
      ...group,
      // Sector-wide entries are listed once, under their sector event above.
      items: group.items.filter((c) => !(c.anomaly === 'sector' && events.some((e) => e.sector === c.sector)
        && (c.kind === 'entered' || c.kind === 'first_observed'))),
    })).filter((group) => group.items.length);
    if (!shown.length) {
      tableHost.append(el('div', { class: 'monitor-detail-empty', text: artifact.previous_as_of
        ? `No queue changes between ${artifact.previous_as_of} and ${artifact.as_of}.`
        : 'Nothing to compare against yet.' }));
    }
    for (const group of shown) {
      tableHost.append(card(group.label, el('span', { class: 'dim', text: String(group.items.length) }),
        table(['TICKER', 'SECTOR', 'ANOMALY', 'WHY TODAY', 'DRAWDOWN', `VS PEERS ${relativePeriod}`, 'PRICE · EVIDENCE', 'NEXT EARNINGS'],
          group.items.map(changeRow), { class: 'monitor-change-table' })));
    }
    tableHost.append(quadrantBar(deriveMonitorRows(artifact, state.threshold, [...state.followed])));
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
    tableHost.append(el('div', { class: 'note-text monitor-table-note', text: `Over ${relativePeriod}: market proxy ${formatPct(artifact.market_return_pct)}, median member ${formatPct(artifact.members_median_return_pct)}. The ETF is compared with the market (both cap-weighted), the median member with the median of all members (both equal-weight); a sector is weak as a whole only when it trails on both. ABOVE MA now against 5 sessions ago is the internal repair check.` }));
  }

  function renderTable(filtered) {
    tableHost.replaceChildren();
    if (!filtered.length) {
      const modeLabel = MODES.find(([mode]) => mode === state.mode)?.[1] || state.mode.toUpperCase();
      tableHost.append(gap(`No rows match ${modeLabel} at ≤ −${formatThreshold(state.threshold)} with the current filters.`));
      if (state.quadrant) tableHost.append(quadrantBar(deriveMonitorRows(artifact, state.threshold, [...state.followed])));
      return;
    }
    const node = el('table', { class: 'data monitor-table' }, [
      tableHeader(columns),
      el('tbody', {}, filtered.map(displayRow)),
    ]);
    if (state.mode === 'queue' || state.quadrant) tableHost.append(quadrantBar(deriveMonitorRows(artifact, state.threshold, [...state.followed])));
    tableHost.append(el('div', { class: 'table-scroll' }, [node]));
    tableHost.append(el('div', { class: 'note-text monitor-table-note' }, [
      'Click a row for raw values, dates, gaps and observed history. UNKNOWN is neutral; it is never a zero and never an inferred exit.',
    ]));
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

  function renderDetail(view) {
    detailHost.replaceChildren();
    if (!view) {
      detailHost.append(el('div', { class: 'monitor-detail-empty', text: 'Select a row to inspect raw metrics, provenance, gaps and observed history.' }));
      return;
    }
    const row = view.row;
    const ticker = row.ticker || UNKNOWN;
    const statusNote = view.status === MONITOR_STATUSES.NEWLY_ENTERED
      || view.status === MONITOR_STATUSES.EXITED
      ? `since previous observation ${view.previousDate || UNKNOWN}; exact crossing date is not known`
      : view.status === MONITOR_STATUSES.BASELINE
        ? 'first qualifying observation in the tracked history'
        : view.status === MONITOR_STATUSES.UNKNOWN
          ? (view.stale ? `no observation on artifact as-of ${artifact.as_of || UNKNOWN}` : 'latest observed value is unknown')
          : 'derived from observed history';
    const heading = el('div', { class: 'monitor-detail-heading' }, [
      el('div', {}, [
        el('div', { class: 'monitor-detail-ticker', text: ticker }),
        el('div', { class: 'monitor-detail-name', text: row.name || UNKNOWN }),
      ]),
      followButton(ticker),
    ]);
    const summary = el('div', { class: 'stat-strip monitor-detail-stats' }, [
      stat(`DRAWDOWN AT ≤ −${formatThreshold(state.threshold)}`, formatPct(view.currentValue), view.stale ? `last observed ${view.latestDate}; current observation unknown` : view.latestDate || UNKNOWN),
      stat('STATUS', view.status.toUpperCase(), statusNote),
            stat('PRICE SOURCE DATE', raw(row.price_as_of), 'adjusted-close source date from artifact'),
      stat(`VS PEERS ${relativePeriod}`, formatPp(row.peer_excess_pct), row.peer_count ? `${row.peer_count} sector peers, equal weight, company excluded` : 'peer basket unavailable'),
      stat(`VS MARKET ${relativePeriod}`, formatPp(row.market_excess_pct), `${row.market_benchmark || UNKNOWN}; ${row.sector_benchmark || 'sector ETF'} ${formatPp(row.sector_excess_pct)}`),
      stat('PRICE STATE', (row.price_state || UNKNOWN).toUpperCase(), `RS vs peers improving: ${raw(row.rs_improving)} · above MA${maSessions}: ${raw(row.above_ma)}`),
    ]);
    const links = el('div', { class: 'monitor-detail-links' }, [
      el('span', { class: 'dim', text: 'OPEN COMPANY PANELS: ' }),
      linkTo('technicals', ticker),
      el('span', { class: 'dim', text: ' · ' }),
      linkTo('valuation', ticker),
      el('span', { class: 'dim', text: ' · ' }),
      linkTo('financials', ticker),
    ]);
    const exp = row.expectations || null;
    const evidenceCard = card('EVIDENCE', el('span', { class: `monitor-evidence-${row.evidence_state || 'unknown'}`, text: (row.evidence_state || UNKNOWN).toUpperCase() }), [
      el('div', { class: 'grid two monitor-evidence' }, [
        el('div', {}, [
          el('div', { class: 'monitor-detail-label', text: 'FOR' }),
          (row.evidence_for || []).length
            ? el('ul', { class: 'monitor-gap-list' }, row.evidence_for.map((item) => el('li', { text: item })))
            : el('div', { class: 'dim', text: 'NOTHING RECORDED' }),
        ]),
        el('div', {}, [
          el('div', { class: 'monitor-detail-label', text: 'AGAINST' }),
          (row.evidence_against || []).length
            ? el('ul', { class: 'monitor-gap-list' }, row.evidence_against.map((item) => el('li', { class: 'down', text: item })))
            : el('div', { class: 'dim', text: 'NOTHING RECORDED' }),
        ]),
      ]),
      el('div', { class: 'note-text', text: 'Listed, not weighed. DETERIORATING = anything against; STEADY = nothing against and a live FY1 estimate; otherwise UNKNOWN.' }),
    ]);
    const fmtEps = (value) => (value === null || value === undefined ? UNKNOWN : num(value, 2));
    const expectationCard = card('FY1 CONSENSUS EPS', el('span', { class: 'dim', text: 'Yahoo earningsTrend · same fiscal period' }), exp
      ? table(['', 'VALUE'], [
        ['FISCAL YEAR ENDING', exp.fiscal_year_end || UNKNOWN],
        ['NOW', fmtEps(exp.eps)],
        ['30 DAYS AGO', `${fmtEps(exp.eps_30d)} (${formatPct(exp.change_30d_pct)})`],
        ['90 DAYS AGO', `${fmtEps(exp.eps_90d)} (${formatPct(exp.change_90d_pct)})`],
        ['REVISIONS 30D', `${exp.up_30d ?? '?'} up · ${exp.down_30d ?? '?'} down`],
        ['ANALYSTS', exp.analysts ?? UNKNOWN],
        ['RANGE', `${fmtEps(exp.low)} – ${fmtEps(exp.high)}`],
        ['READING', EXPECTATION_TEXT[exp.state] || UNKNOWN],
      ].map(([label, value]) => el('tr', {}, [el('td', { class: 'dim', text: label }), el('td', { text: String(value) })])))
      : el('div', { class: 'dim', text: 'No estimates for this name in this build. Unknown, not unchanged.' }));
    const log = Array.isArray(row.state_log) ? row.state_log : [];
    const reported = row.reported;
    const historyCard = card('CANDIDATE HISTORY', null, [
      el('div', { class: 'monitor-timeline' }, [
        el('div', { text: row.first_seen
          ? `FIRST SEEN ${row.first_seen.date}${row.first_seen.baseline ? ' (baseline: already there when tracking began)' : ''} · ${(row.first_seen.reasons || []).map((r) => REASON_TEXT[r] || r).join(', ')}`
          : 'Never in the queue since tracking began.' }),
        row.first_seen ? el('div', { class: 'dim', text: row.first_seen.date === artifact.as_of ? 'First seen in this build; the outcome is measured from the next one.' : `Since then: ${formatPct(row.since_first_seen_pct)} (adjusted) · sector peers ${formatPct(row.peers_since_first_seen_pct)} median` }) : null,
        reported ? el('div', { class: 'dim', text: `Last reported ${reported.date}${reported.fiscal_quarter ? ` (${reported.fiscal_quarter})` : ''}: EPS ${reported.eps ?? '?'} vs ${reported.eps_forecast ?? '?'} expected${reported.return_1d !== null && reported.return_1d !== undefined ? `, stock ${pct(reported.return_1d, 1)} next session` : ''}` }) : null,
        row.note ? el('div', { class: row.note.status === 'exclude' ? 'down' : 'up', text: `${String(row.note.status).toUpperCase()}${row.note.since ? ` since ${row.note.since}` : ''}: ${row.note.reason}${row.note.outcome ? ` → ${row.note.outcome}` : ''}` }) : null,
      ]),
      log.length ? table(['FROM', 'IN QUEUE', 'PRICE', 'EVIDENCE'], [...log].reverse().map((entry) => el('tr', {}, [
        el('td', { text: entry[0] }),
        el('td', { text: entry[1] === null ? UNKNOWN : entry[1] ? 'YES' : 'NO' }),
        el('td', { text: (entry[2] || UNKNOWN).toUpperCase() }),
        el('td', { text: (entry[3] || UNKNOWN).toUpperCase() }),
      ]))) : null,
      el('div', { class: 'note-text', text: 'A new line only when a state changes; a day with an unknown reading keeps the last known state. Watch/exclude reasons live in config/monitor_notes.toml.' }),
    ]);
    detailHost.append(
      el('div', { class: 'monitor-detail' }, [
        heading,
        summary,
        el('div', { class: 'grid two monitor-detail-grid' }, [evidenceCard, expectationCard]),
        historyCard,
        el('div', { class: 'grid two monitor-detail-grid' }, [
          card('RAW MONITOR METRICS', null, rawMetricsTable(row)),
          card('PROVENANCE / COVERAGE', null, [provenanceTable(row), gapsBlock(row)]),
        ]),
        card(`OBSERVED HISTORY — THRESHOLD VIEW`, null, [
          historyTable(view),
          el('div', { class: 'note-text' }, [
            'History is daily observed since MONITOR feature start only. Same-day observations replace earlier prints; missing dates stay UNKNOWN. ',
            'The FIRST OBSERVED label is derived from this history and is not a claim about actual historical entry.',
          ]),
        ]),
        links,
      ]),
    );
  }

  function renderData() {
    const views = deriveMonitorRows(artifact, state.threshold, [...state.followed]);
    const selected = state.selected ? views.find((view) => view.row.ticker === state.selected) : null;
    renderStats(views);
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
}
