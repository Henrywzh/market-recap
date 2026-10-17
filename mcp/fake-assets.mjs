// Stand-ins for the Pages ASSETS binding, for node tests and the contract
// check. Never imported by the function itself.

import { readFile } from 'node:fs/promises';
import { join, normalize } from 'node:path';

const notFound = () => new Response('not found', { status: 404 });

// Serves files from a built site directory (dist/).
export function directoryAssets(root) {
  return {
    async fetch(request) {
      const path = normalize(decodeURIComponent(new URL(request.url).pathname));
      if (path.includes('..')) return notFound();
      try {
        return new Response(await readFile(join(root, path)), { status: 200, headers: { 'Content-Type': 'application/json' } });
      } catch {
        return notFound();
      }
    },
  };
}

// Serves an object of { '/artifacts/x.json': value } as JSON; anything else is a 404.
export function memoryAssets(files) {
  return {
    async fetch(request) {
      const path = new URL(request.url).pathname;
      return path in files ? new Response(JSON.stringify(files[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }) : notFound();
    },
  };
}

// Counts the bytes of JSON a call reads through the wrapped assets: the number
// the size budget is about (what the adapter parses), measured at the boundary.
export function counting(assets) {
  const meter = { bytes: 0, paths: [] };
  return {
    meter,
    assets: {
      async fetch(request) {
        const response = await assets.fetch(request);
        if (!response.ok) return response;
        const text = await response.text();
        meter.bytes += Buffer.byteLength(text);
        meter.paths.push(new URL(request.url).pathname);
        return new Response(text, { status: response.status, headers: response.headers });
      },
    },
  };
}

// The same site as the wrapped assets, without the slices in artifacts/mcp/:
// what the server does on a deploy that predates them.
export function withoutSlices(assets) {
  return {
    fetch(request) {
      return new URL(request.url).pathname.startsWith('/artifacts/mcp/') ? notFound() : assets.fetch(request);
    },
  };
}
