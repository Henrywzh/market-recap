// The tool registry and the one place a tool call is run: validate the
// arguments, give the adapter a Context, wrap what it returns in the envelope.
// Adapters live in ./tools/ and know nothing about HTTP or JSON-RPC.

import { Context } from './context.mjs';
import { validate } from './schema.mjs';
import { catalystsTool } from './tools/catalysts.mjs';
import { macroTool } from './tools/macro.mjs';
import { marketSnapshotTool } from './tools/market.mjs';
import { unusualMovesTool } from './tools/moves.mjs';
import { fetchTool, searchTool } from './tools/search.mjs';
import { sectorTool, themeTool } from './tools/sector.mjs';
import { tickerTool } from './tools/ticker.mjs';

export const TOOLS = [
  marketSnapshotTool, catalystsTool, tickerTool, unusualMovesTool, sectorTool, themeTool, macroTool, searchTool, fetchTool,
];

const ANNOTATIONS = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };

export const toolList = () => TOOLS.map(({ name, title, description, inputSchema, outputSchema }) => ({
  name, title, description, inputSchema, outputSchema, annotations: ANNOTATIONS,
}));

export const findTool = (name) => TOOLS.find((t) => t.name === name) || null;

const failure = (message) => ({ content: [{ type: 'text', text: message }], isError: true });

// Runs one tool and returns the MCP tool result. A problem with the arguments
// or the request is a result with isError, not a protocol error, so the model
// calling the tool can read it and try again.
export async function runTool(tool, args, { assets, origin, now }) {
  const problems = validate(tool.inputSchema, args || {});
  if (problems.length) return failure(`Invalid arguments: ${problems.join('; ')}`);
  const ctx = new Context({ assets, origin, now });
  try {
    await ctx.loadManifest();
    const structured = ctx.finish(await tool.run(ctx, args || {}));
    return { content: [{ type: 'text', text: JSON.stringify(structured) }], structuredContent: structured };
  } catch (error) {
    return failure(error instanceof Error ? error.message : 'The tool failed.');
  }
}
