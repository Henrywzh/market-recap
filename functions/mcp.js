// Remote MCP server: POST /mcp. A thin route over mcp/server.mjs, which lives
// outside functions/ so node can import and test it; wrangler bundles it into
// this function. Read-only: it answers from the files the site itself publishes.

import { handleMcp } from '../mcp/server.mjs';

export const onRequest = ({ request, env }) => handleMcp(request, env);
