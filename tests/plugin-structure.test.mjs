import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { pluginRoot } from "./helpers.mjs";

function readJson(relative) {
  return JSON.parse(fs.readFileSync(path.join(pluginRoot, relative), "utf8"));
}

test("Codex manifest points to the packaged MCP companion instead of an inline map", () => {
  const manifest = readJson(".codex-plugin/plugin.json");
  const mcp = readJson(".mcp.json");
  assert.equal(manifest.mcpServers, "./.mcp.json");
  assert.equal(mcp.mcpServers["nova-checkpoint"].command, "node");
  assert.deepEqual(
    mcp.mcpServers["nova-checkpoint"].args.slice(-2),
    ["--host", "codex"],
  );
  assert.equal(
    mcp.mcpServers["nova-checkpoint"].env.NOVA_LEGACY_PLUGIN_DATA,
    "${PLUGIN_DATA}",
  );
  assert.equal(
    Object.hasOwn(mcp.mcpServers["nova-checkpoint"].env, "NOVA_PLUGIN_DATA"),
    false,
  );
});
