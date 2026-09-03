import assert from "node:assert/strict";
import test from "node:test";
import { McpRuntime, handleRpc } from "../runtime/mcp/server.mjs";
import { claimSession } from "../runtime/core/rendezvous.mjs";
import { markEvent, startSession } from "../runtime/core/state-machine.mjs";
import { cwdKey, scopeKey } from "../runtime/core/util.mjs";
import { pluginRoot, saveInput, temporaryDirectory } from "./helpers.mjs";

test("MCP tools expose no host or session selector and use the bound scope", () => {
  const temp = temporaryDirectory();
  try {
    const now = Date.now();
    const sessionKey = scopeKey("codex", "mcp-session");
    const binding = { host: "codex", sessionKey, cwdHash: cwdKey(pluginRoot) };
    startSession(temp.directory, binding, "0.1.0", "startup", { now });
    markEvent(temp.directory, binding, "0.1.0", "prompt:1", { now: now + 1 });
    claimSession(temp.directory, { host: "codex", cwd: pluginRoot, sessionKey, now: now + 2 });
    const runtime = new McpRuntime({
      dataRoot: temp.directory,
      pluginRoot,
      host: "codex",
      cwd: pluginRoot,
    });
    const tools = runtime.listTools();
    const schemaText = JSON.stringify(tools);
    assert.doesNotMatch(schemaText, /sessionId|session_id|"host"/);
    const saved = runtime.callTool("nova_checkpoint_save", saveInput(1));
    assert.equal(saved.saved, true);
    assert.equal(saved.dirty, false);
    const current = runtime.callTool("nova_checkpoint_get", {});
    assert.equal(current.authorityGeneration, 1);
    assert.equal(current.taskCapsule.stageProjection.inheritedContracts[0].value, "Same-session only");
  } finally {
    temp.cleanup();
  }
});

test("unbound MCP instance fails closed", () => {
  const temp = temporaryDirectory();
  try {
    const runtime = new McpRuntime({
      dataRoot: temp.directory,
      pluginRoot,
      host: "claude-code",
      cwd: pluginRoot,
    });
    assert.throws(() => runtime.callTool("nova_checkpoint_get", {}), {
      code: "BINDING_UNAVAILABLE",
    });
  } finally {
    temp.cleanup();
  }
});

test("JSON-RPC initialize and tool errors follow MCP result shape", () => {
  const runtime = {
    pluginVersion: "0.1.0",
    listTools: () => [],
    callTool: () => {
      throw new Error("failure");
    },
  };
  const initialized = handleRpc(runtime, {
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: { protocolVersion: "2025-06-18" },
  });
  assert.equal(initialized.result.serverInfo.name, "nova-checkpoint");
  const failed = handleRpc(runtime, {
    jsonrpc: "2.0",
    id: 2,
    method: "tools/call",
    params: { name: "nova_checkpoint_get", arguments: {} },
  });
  assert.equal(failed.result.isError, true);
  assert.match(failed.result.content[0].text, /INTERNAL_ERROR/);
});
