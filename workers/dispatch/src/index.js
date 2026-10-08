// Dispatches the refresh workflow's two editions a weekday: "close" at 16:20
// New York (Yahoo's closes have settled by 16:15; the recap is up about half an
// hour after the bell) and "evening" at 18:35. No routes, no fetch handler.

const EDITIONS = { '16:20': 'close', '18:35': 'evening' };

// New York wall-clock time of an instant, "HH:MM".
export function newYorkClock(ms) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(new Date(ms));
}

// The edition a cron firing at `ms` stands for, or null for the other
// daylight-saving candidate.
export function editionAt(ms) {
  return EDITIONS[newYorkClock(ms)] ?? null;
}

export async function dispatch(env, edition, fetcher = fetch) {
  const url = `https://api.github.com/repos/${env.REPO}/actions/workflows/${env.WORKFLOW}/dispatches`;
  const body = JSON.stringify({ ref: 'main', inputs: { deploy: 'true', edition } });
  let last = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await fetcher(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'market-recap-dispatch',
        'Content-Type': 'application/json',
      },
      body,
    });
    if (response.status === 204) return { ok: true, status: 204 };
    last = { ok: false, status: response.status, text: (await response.text()).slice(0, 300) };
    if (response.status < 500) break;              // a refused token will not improve on retry
  }
  return last;
}

export default {
  async scheduled(event, env, ctx) {
    const edition = editionAt(event.scheduledTime);
    if (!edition) return;
    if (!env.GITHUB_TOKEN) {
      console.error('GITHUB_TOKEN is not set: nothing dispatched');
      return;
    }
    ctx.waitUntil(dispatch(env, edition).then((result) => {
      if (result.ok) console.log(`dispatched refresh · ${edition}`);
      else console.error(`dispatch refresh · ${edition} failed: HTTP ${result.status} ${result.text}`);
    }));
  },
};
