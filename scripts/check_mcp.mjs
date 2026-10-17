// Contract check for the MCP server (functions/mcp.js): runs every tool with
// representative arguments against the built site's own artifacts and fails if
// an adapter no longer matches the panel it reads.
//
//   node scripts/check_mcp.mjs [dist]        (make smoke runs it)
//
// What it asserts for each call: the call succeeds; the structured result
// matches the tool's outputSchema; its text is the same object and fits the
// size limit; as_of is the manifest's; and the parts the call is about are
// present, not silently null. A panel whose fields were renamed makes its
// adapter return null for them, which is exactly what this catches -- change
// a panel and its adapter in the same commit (docs/mcp.md).
//
// The slices (artifacts/mcp/, src/market_recap/mcp_slices.py) are checked too:
// every call is run once from the slices and once without them (what an older
// deploy serves), the two results must be the same JSON, and the slice run may
// parse at most BYTES_LIMIT bytes. The index's source hashes must match the
// artifacts beside it, or the slices were cut from another build.

import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { counting, directoryAssets, withoutSlices } from '../mcp/fake-assets.mjs';
import { validate } from '../mcp/schema.mjs';
import { handleMcp } from '../mcp/server.mjs';
import { TOOLS } from '../mcp/tools.mjs';

const ROOT = resolve(process.argv[2] || 'dist');
const ORIGIN = 'https://market-recap-b5p.pages.dev';
const SIZE_LIMIT = 20480;
// JSON parsed per call on the slice path. Measured: ~4 ms per MB of JSON, so
// 600 KB is ~2.5 ms against the free plan's ~10 ms CPU per request.
const BYTES_LIMIT = 600000;

async function artifact(name) {
  return JSON.parse(await readFile(join(ROOT, 'artifacts', `${name}.json`), 'utf8'));
}

// The arguments a reader would plausibly use, taken from the build itself.
// Every ticker, sector, theme and macro kind the build has is called too.
async function plan(manifest) {
  const [heat, catalysts, sectors, themes, tickers] = await Promise.all([
    artifact('heatmaps'), artifact('catalysts'), artifact('sectors'), artifact('themes'), artifact('mcp/ticker/index'),
  ]);
  const top = [...heat.constituents].filter((r) => r.ticker).sort((a, b) => (b.weight || 0) - (a.weight || 0))[0].ticker;
  const upcoming = catalysts.events.filter((e) => e.date >= manifest.as_of).sort((a, b) => a.date.localeCompare(b.date));
  const from = upcoming.length ? upcoming[0].date : manifest.as_of;
  const sector = sectors.sectors[0];
  const sub = sectors.sub_industries.find((s) => s.sector_key === sector.key) || sectors.sub_industries[0];
  const calls = [
    { tool: 'market_snapshot', args: {}, paths: ['indices.0.last', 'breadth.0.above_200d_pct', 'risk.core_tiles.0.value', 'index_put_call.series.0.daily.value', 'buyback_blackout.level_pct', 'buyback_blackout.next_7d_schedule_change_pp', 'sector_rotation.sectors.0.quadrant'], expect: ['indices', 'breadth', 'market_state', 'risk', 'index_put_call', 'buyback_blackout', 'sector_rotation'] },
    { tool: 'catalysts', args: { from, to: addDays(from, 7) }, paths: ['recent_session.session', 'events.0.title'], expect: ['events', 'recent_session'], nonEmpty: ['events'] },
    { tool: 'ticker', args: { symbol: top }, paths: ['valuation.price', 'valuation.pe_percentile_own_10y', 'monitor.price_state', 'reports.last.date', 'moves.parts.own_z', 'moves.range.bands.0.price'], expect: ['valuation', 'monitor', 'moves'] },
    { tool: 'unusual_moves', args: {}, paths: ['threshold_sigma', 'technology_selloff.active'], expect: ['technology_selloff'] },
    { tool: 'sector', args: { key: sector.key }, paths: ['summary.returns_pct.1M', 'valuation_strip.current'], expect: ['valuation_strip'], nonEmpty: ['sub_industries'] },
    { tool: 'sector', args: { key: sub.key }, expect: ['parent'] },
    ...['cpi', 'ppi'].map((kind) => ({ tool: 'macro', args: { kind }, paths: ['release.release_vs_consensus.0.actual', 'release.components.0.mom_pct'], expect: ['release'] })),
    { tool: 'macro', args: { kind: 'rates' }, paths: ['curve.curves.0.yields_pct.10Y', 'curve.spreads_bp.0.bps'], expect: ['curve'] },
    { tool: 'macro', args: { kind: 'commodities' }, paths: ['commodities.0.price'], expect: ['commodities'] },
    { tool: 'search', args: { query: top }, expect: ['results'], nonEmpty: ['results'] },
    { tool: 'fetch', args: { id: `ticker:${top}` }, expect: ['text'] },
    { tool: 'fetch', args: { id: `macro:cpi` }, expect: ['text'] },
    { tool: 'fetch', args: { id: `sector:${sector.key}` }, expect: ['text'] },
  ];
  themes.groups.forEach((g) => calls.push({ tool: 'theme', args: { key: g.key }, expect: ['bellwethers'], nonEmpty: ['bellwethers'] }));
  [...sectors.sectors, ...sectors.sub_industries].forEach((s) => calls.push({ tool: 'sector', args: { key: s.key } }));
  ['cpi', 'ppi', 'rates', 'commodities'].forEach((kind) => calls.push({ tool: 'macro', args: { kind } }));
  for (const symbol of [...new Set([...tickers.rows, ...tickers.events])]) calls.push({ tool: 'ticker', args: { symbol } });
  for (const query of ['semis', 'cpi', sector.label, top]) calls.push({ tool: 'search', args: { query } });
  if (upcoming.length) calls.push({ tool: 'fetch', args: { id: `event:${upcoming[0].event_key}` }, expect: ['text'] });
  // A share class typed the exchange's way must reach the build's key.
  const dashed = heat.constituents.map((r) => r.ticker).find((t) => /^[A-Z]+-[A-Z]$/.test(t || ''));
  if (dashed) calls.push({ tool: 'ticker', args: { symbol: dashed.replace('-', '.') }, expect: ['valuation'] });
  return calls;
}

// 'risk.core_tiles.0.value' -> data.risk.core_tiles[0].value
function valueAt(data, path) {
  return path.split('.').reduce((node, key) => (node === null || node === undefined ? undefined : node[key]), data);
}

function addDays(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

// JSON with object keys sorted: the same value however the adapter ordered them.
const canonical = (text) => JSON.stringify(JSON.parse(text), (k, v) => (v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map((key) => [key, v[key]])) : v));

// One call, through the given assets, and the bytes of JSON it parsed.
async function rpc(assets, body) {
  const meter = counting(assets);
  const request = new Request(`${ORIGIN}/mcp`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const response = await handleMcp(request, { ASSETS: meter.assets });
  return { status: response.status, body: response.status === 202 ? null : await response.json(), bytes: meter.meter.bytes };
}

function problemsFor(call, tool, result, manifest) {
  const problems = [];
  if (result.isError) return [`tool error: ${result.content[0].text}`];
  const data = result.structuredContent;
  problems.push(...validate(tool.outputSchema, data).slice(0, 5));
  if (result.content[0].text !== JSON.stringify(data)) problems.push('content text is not the structuredContent');
  if (result.content[0].text.length > SIZE_LIMIT) problems.push(`${result.content[0].text.length} chars is over the ${SIZE_LIMIT} limit`);
  if (data.as_of !== manifest.as_of) problems.push(`as_of ${data.as_of} is not the manifest's ${manifest.as_of}`);
  if (data.generated_at !== manifest.generated_at) problems.push('generated_at is not the manifest\'s');
  (call.expect || []).forEach((part) => { if (data[part] === null || data[part] === undefined) problems.push(`${part} is null (${data.unavailable.map((u) => u.part).join('; ') || 'no reason given'})`); });
  // A single value can be missing on a day the data has a gap (the page shows a
  // dash then too), so a missing path warns; a broken shape, a whole section
  // gone or an oversized call still fails.
  (call.paths || []).forEach((path) => { if (valueAt(data, path) === null || valueAt(data, path) === undefined) problems.push(`WARN ${path} is missing (${data.unavailable.map((u) => u.part).join('; ') || 'no reason given'})`); });
  (call.nonEmpty || []).forEach((part) => { if (!Array.isArray(data[part]) || !data[part].length) problems.push(`${part} is empty`); });
  return problems;
}

// The slices must be the artifacts beside them: each source's sha256 in the index
// is the hash of the file in this build, or the server would mix two builds.
async function sliceProblems() {
  let index;
  try {
    index = await artifact('mcp/index');
  } catch {
    return ['artifacts/mcp/index.json is not published: run make site'];
  }
  const problems = [];
  for (const [name, sha] of Object.entries(index.sources || {})) {
    const bytes = await readFile(join(ROOT, 'artifacts', `${name}.json`)).catch(() => null);
    const now = bytes ? createHash('sha256').update(bytes).digest('hex') : null;
    if (now !== sha) problems.push(`${name}.json is not the file the slices were cut from (${now ? 'different bytes' : 'missing'})`);
  }
  return problems;
}

async function main() {
  const manifest = await artifact('manifest');
  const sliced = directoryAssets(ROOT);
  const plain = withoutSlices(directoryAssets(ROOT));
  const failures = [];
  const report = (label, problems, note = '') => {
    const hard = problems.filter((p) => !p.startsWith('WARN '));
    console.log(`${hard.length ? 'FAIL' : problems.length ? 'warn' : 'ok  '}  ${label}${note}`);
    problems.forEach((p) => console.log(`        ${p}`));
    if (hard.length) failures.push(label);
  };

  // The protocol itself, as a client would start: initialize, then list.
  const init = await rpc(sliced, { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'check', version: '1' } } });
  report('initialize', init.body?.result?.serverInfo?.name === 'market-recap' ? [] : ['no serverInfo'], ` (version ${init.body?.result?.serverInfo?.version})`);
  const list = await rpc(sliced, { jsonrpc: '2.0', id: 2, method: 'tools/list' });
  const listed = (list.body?.result?.tools || []).map((t) => t.name).sort();
  const wanted = TOOLS.map((t) => t.name).sort();
  report('tools/list', JSON.stringify(listed) === JSON.stringify(wanted) ? [] : [`listed ${listed.join(',')}`], ` (${listed.length} tools)`);
  report('slices match this build', await sliceProblems());

  // Each tool's calls, summarised: the worst bytes parsed with and without slices.
  const perTool = new Map();
  for (const call of await plan(manifest)) {
    const tool = TOOLS.find((t) => t.name === call.tool);
    const body = { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: call.tool, arguments: call.args } };
    const fromSlices = await rpc(sliced, body);
    const fromFull = await rpc(plain, body);
    const label = `${call.tool} ${JSON.stringify(call.args)}`;
    const stat = perTool.get(call.tool) || { calls: 0, failed: 0, worstSlices: 0, worstFull: 0 };
    stat.calls += 1;
    stat.worstSlices = Math.max(stat.worstSlices, fromSlices.bytes);
    stat.worstFull = Math.max(stat.worstFull, fromFull.bytes);
    perTool.set(call.tool, stat);
    const result = fromSlices.body?.result;
    if (!result) { stat.failed += 1; report(label, [`protocol error: ${JSON.stringify(fromSlices.body?.error)}`]); continue; }
    const problems = problemsFor(call, tool, result, manifest);
    const other = fromFull.body?.result;
    if (!other || other.isError !== result.isError || (result.isError ? other.content[0].text !== result.content[0].text : canonical(other.content[0].text) !== canonical(result.content[0].text))) {
      problems.push('the slice result differs from the full-artifact result');
    }
    if (fromSlices.bytes > BYTES_LIMIT) problems.push(`${fromSlices.bytes} bytes of JSON parsed on the slice path is over ${BYTES_LIMIT}`);
    if (problems.length) {
      if (problems.some((p) => !p.startsWith('WARN '))) stat.failed += 1;
      report(label, problems);
    }
  }
  for (const [tool, stat] of perTool) {
    const ok = stat.failed === 0;
    console.log(`${ok ? 'ok  ' : 'FAIL'}  ${tool}: ${stat.calls} calls, worst ${stat.worstSlices} B parsed from slices (${stat.worstFull} B from full artifacts)`);
    if (!ok) failures.push(tool);
  }
  if (failures.length) {
    console.error(`\nmcp contract check failed: ${failures.length} check(s). A panel and its adapter in mcp/ must change together, and the slices must be cut from this build.`);
    process.exit(1);
  }
  console.log('\nmcp contract check passed');
}

main().catch((error) => { console.error(error); process.exit(1); });
