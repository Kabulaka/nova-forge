import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { pluginRoot } from "./helpers.mjs";

function readJson(relative) {
  return JSON.parse(fs.readFileSync(path.join(pluginRoot, relative), "utf8"));
}

test("marketplaces use host-native install sources", () => {
  const packageJson = readJson("package.json");
  const codexMarketplace = readJson(".agents/plugins/marketplace.json");
  const claudeMarketplace = readJson(".claude-plugin/marketplace.json");

  assert.deepEqual(codexMarketplace.plugins[0].source, {
    source: "url",
    url: "https://github.com/Kabulaka/nova-forge.git",
    ref: `v${packageJson.version}`,
  });
  assert.equal(claudeMarketplace.plugins[0].source, "./");
  assert.equal(claudeMarketplace.metadata.version, packageJson.version);
  assert.equal(claudeMarketplace.plugins[0].version, packageJson.version);
});

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

test("checkpoint tools have a narrow PreToolUse proof injector", () => {
  const hooks = readJson("hooks/hooks.json");
  const entries = hooks.hooks.PreToolUse;
  assert.equal(entries.length, 1);
  const matcher = new RegExp(entries[0].matcher);
  for (const name of [
    "mcp__nova-checkpoint__nova_checkpoint_get",
    "mcp__nova_checkpoint__nova_checkpoint_save",
    "mcp__plugin_nova-forge_nova-checkpoint__nova_checkpoint_get",
  ]) {
    assert.equal(matcher.test(name), true);
  }
  assert.equal(matcher.test("mcp__other__nova_checkpoint_get"), false);
  assert.equal(matcher.test("Bash"), false);
});
