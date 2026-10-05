// The build's own timings (manifest.timings), read for the page footer.

// Where the build's time went, slowest first, for the footer's hover text.
export function slowestParts(timings, count = 8) {
  if (!timings) return null;
  const parts = Object.entries(timings.panels || {}).map(([name, s]) => [name, s]);
  ['context', 'sec_check', 'cache_prune'].forEach((key) => {
    if (timings[key] !== undefined) parts.push([key === 'context' ? 'prices & constituents' : key.replace('_', ' '), timings[key]]);
  });
  return parts.sort((a, b) => b[1] - a[1]).slice(0, count).map(([name, s]) => `${name} ${Math.round(s)}s`).join(' · ');
}
