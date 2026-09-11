import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { pluginRoot } from "./helpers.mjs";

function readJson(relative) {
  return JSON.parse(fs.readFileSync(path.join(pluginRoot, relative), "utf8"));
}

test("Codex manifest uses the packaged MCP companion and default hook discovery", () => {
  const manifest = readJson(".codex-plugin/plugin.json");
  const mcp = readJson(".mcp.json");
  assert.equal(manifest.mcpServers, "./.mcp.json");
  assert.equal(Object.hasOwn(manifest, "hooks"), false);
  assert.equal(mcp.mcpServers["nova-checkpoint"].command, "node");
  assert.equal(mcp.mcpServers["nova-checkpoint"].args[0], "./runtime/mcp/server.mjs");
  assert.deepEqual(
    mcp.mcpServers["nova-checkpoint"].args.slice(-2),
    ["--host", "codex"],
  );
  assert.equal(mcp.mcpServers["nova-checkpoint"].cwd, ".");
  assert.equal(mcp.mcpServers["nova-checkpoint"].default_tools_approval_mode, "approve");
  assert.equal(Object.hasOwn(mcp.mcpServers["nova-checkpoint"], "env"), false);
});
