// Pure helpers for the RISK matrix: how its cells group, count and read.
// No DOM here, so the page's rules can be tested in node. The build decides
// each cell's state and percentile; these only arrange and describe them.

const STATE_WORDS = {
  calm: 'calm', elevated: 'elevated', stressed: 'stressed', unrated: 'not coloured', grey: 'no reading',
  cheap: 'cheap', fair: 'fair', rich: 'rich', very_rich: 'very rich',
};
// The VALUATION column's words: how thin the compensation is, not how stressed
// the market is. They are counted on a line of their own.
export const VALUATION_STATES = ['very_rich', 'rich', 'fair', 'cheap'];

// A cell with no lead is a placeholder: its series is still to come.
export function isPlaceholder(cell) {
  return !cell || cell.lead === null || cell.lead === undefined;
}

// The state the page paints. Anything the build did not name as a colour,
// and any placeholder, reads as "no reading" rather than as calm.
export function stateOf(cell) {
  if (isPlaceholder(cell)) return 'grey';
  return Object.hasOwn(STATE_WORDS, cell.state) ? cell.state : 'grey';
}

export function stateWord(state) {
  return STATE_WORDS[state] || STATE_WORDS.grey;
}

// Rows in the order the config gives them, each with its cells in column order.
// A cell the build left out becomes null, so its neighbours keep their columns.
export function cellsByRow(matrix) {
  const columns = matrix?.columns || [];
  const cells = matrix?.cells || [];
  return (matrix?.rows || []).map((row) => ({
    key: row.key,
    label: row.label,
    cells: columns.map((column) => cells.find((c) => c.row === row.key && c.column === column.key) || null),
  }));
}

// Counts for the summary line. Every cell lands in exactly one bucket, so the
// numbers add up to the matrix's cell count.
export function stateCounts(cells) {
  const counts = { stressed: 0, elevated: 0, calm: 0, unrated: 0, grey: 0, very_rich: 0, rich: 0, fair: 0, cheap: 0 };
  for (const cell of cells) counts[stateOf(cell)] += 1;
  return counts;
}

// The lead's one-month move: an arrow for the direction of the value, toned by
// whether that move is toward risk. Null when the build has no 1M change.
export function arrowFor(cell) {
  if (!cell || !Number.isFinite(cell.change_1m)) return null;
  // Unchanged has no direction, so it needs no worse-or-better flag.
  if (cell.change_1m === 0) return { arrow: '→', tone: 'flat', word: 'unchanged over the month' };
  if (typeof cell.worse_1m !== 'boolean') return null;
  const arrow = cell.change_1m > 0 ? '↑' : '↓';
  return cell.worse_1m
    ? { arrow, tone: 'worse', word: 'worse over the month' }
    : { arrow, tone: 'better', word: 'better over the month' };
}

const EVIDENCE_TAGS = { tested: ['TESTED', 'info'], candidate: ['CANDIDATE', 'dim'] };

// A caution is shown in its short form; the full sentence goes in the title.
function shortCaution(text) {
  return /failed out of sample/i.test(text) ? 'FAILED OOS' : String(text).toUpperCase().slice(0, 24);
}

// The tags a cell carries: its evidence (none for a plain description), then
// any caution. Each is { text, tone, title }.
export function tagFor(cell) {
  if (!cell) return [];
  const tags = [];
  const evidence = EVIDENCE_TAGS[cell.evidence];
  if (evidence) tags.push({ text: evidence[0], tone: evidence[1], title: null });
  if (cell.caution) tags.push({ text: shortCaution(cell.caution), tone: 'warn', title: cell.caution });
  return tags;
}

// How a cell's colour was decided, in one line: the fixed lines it is read
// against, or the percentile rule, or neither. ``fmt`` prints a line in the
// lead's unit; the percentile rule's numbers come from the matrix.
export function scaleText(cell, matrix, fmt = String) {
  if (!cell || isPlaceholder(cell)) return null;
  if (cell.scale === 'bands' && cell.bands) {
    const dir = cell.risk_when === 'low' ? '≤' : '≥';
    return `Colour: fixed lines, elevated ${dir} ${fmt(cell.bands.elevated)}, stressed ${dir} ${fmt(cell.bands.stressed)}, `
      + 'set from where this series stood in past S&P 500 drawdowns (Treasury series: in past Treasury drawdowns) '
      + 'or from a line with its own meaning. The percentile is a description only.';
  }
  if (cell.scale === 'valuation') {
    const since = cell.since ? cell.since.slice(0, 4) : 'the start of its history';
    const v = matrix?.valuation || {};
    return `Colour: how thin the premium is against its whole history since ${since}: `
      + `rich when thinner than ${v.rich ?? 75}% of it, very rich from ${v.very_rich ?? 90}%, cheap when wider than ${100 - (v.cheap ?? 25)}%. `
      + 'It describes the cushion, not the timing: a thin premium has not told the next three months apart.';
  }
  if (cell.scale === 'none') return 'Not coloured: this lead failed its out-of-sample test, so it is shown as a description only.';
  const th = matrix?.thresholds || {};
  return `Colour: the lead's percentile in its own last ${matrix?.years ?? 10} years, in its risk direction; `
    + `elevated from the ${th.elevated ?? 75}th, stressed from the ${th.stressed ?? 95}th. Used for changes and spreads with no outside anchor.`;
}

// The next scheduled events that hit a row's channel, from the calendar's tags:
// macro events of medium importance or more, and only the largest earnings.
export function upcomingFor(events, channel, asOf, limit = 3) {
  return (events || [])
    .filter((e) => (e.channels || []).includes(channel) && (!asOf || e.date >= asOf))
    .filter((e) => (e.lane === 'single_name' ? e.importance === 'high' : e.importance !== 'low'))
    .sort((a, b) => a.date.localeCompare(b.date) || (a.importance === 'high' ? -1 : 1))
    .slice(0, limit);
}

// The short word in a cell's corner: the same state words as the summary line,
// in capitals, so a cell and the count that includes it always agree.
export function chipWord(cell) {
  return stateWord(stateOf(cell)).toUpperCase();
}

// The summary line's counts as parts, each with the tone its state earns:
// stressed red, elevated and rich amber, very rich red; everything else plain.
// The caller picks the states, so the order and the zero-count rules stay there.
const COUNT_TONE = { stressed: 'down', very_rich: 'down', elevated: 'amber', rich: 'amber' };
export function countParts(counts, states) {
  return states.map((state) => ({ text: `${counts[state]} ${stateWord(state)}`, tone: COUNT_TONE[state] || '' }));
}
