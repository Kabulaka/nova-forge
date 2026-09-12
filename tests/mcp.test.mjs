import assert from "node:assert/strict";
import test from "node:test";
import {
  McpRuntime,
  handleRpc,
  resolveMcpPluginRoot,
} from "../runtime/mcp/server.mjs";
import { SCOPE_PROOF_TTL_MS } from "../runtime/core/constants.mjs";
import { issueScopeProof } from "../runtime/core/scope-proof.mjs";
import { markEvent, startSession } from "../runtime/core/state-machine.mjs";
import { binding, capsule, pluginRoot, saveInput, temporaryDirectory } from "./helpers.mjs";

function proof(dataRoot, scopeBinding, toolName, toolUseId, now) {
  return issueScopeProof(
    dataRoot,
    { ...scopeBinding, toolName, toolUseId },
    { now },
  );
}

test("Codex MCP resolves plugin root from its configured cwd without placeholder env", () => {
  assert.equal(resolveMcpPluginRoot("codex", {}, pluginRoot), pluginRoot);
  assert.equal(
    resolveMcpPluginRoot("codex", { NOVA_PLUGIN_ROOT: pluginRoot }, "/ignored"),
    pluginRoot,
  );
  assert.throws(
    () => resolveMcpPluginRoot("codex", {}, "relative"),
    /absolute plugin root is unavailable/,
  );
  assert.throws(
    () => resolveMcpPluginRoot("claude-code", {}, pluginRoot),
    /absolute plugin root is unavailable/,
  );
});

test("MCP tools expose no selector or proof field and consume a proof for each call", () => {
  const temp = temporaryDirectory();
  try {
    const now = Date.now();
    const scopeBinding = binding("codex", "mcp-session");
    startSession(temp.directory, scopeBinding, "0.1.0", "startup", { now });
    markEvent(temp.directory, scopeBinding, "0.1.0", "prompt:1", { now: now + 1 });
    const runtime = new McpRuntime({
      dataRoot: temp.directory,
      pluginRoot,
      host: "codex",
    });
    const tools = runtime.listTools();
    const schemaText = JSON.stringify(tools);
    assert.doesNotMatch(schemaText, /sessionId|session_id|scopeProof|"host"/);
    const saveProof = proof(
      temp.directory,
      scopeBinding,
      "nova_checkpoint_save",
      "save-call",
      now + 2,
    );
    const saved = runtime.callTool(
      "nova_checkpoint_save",
      { ...saveInput(1), scopeProof: saveProof },
      { now: now + 3 },
    );
    assert.equal(saved.saved, true);
    assert.equal(saved.dirty, false);
    const getProof = proof(
      temp.directory,
      scopeBinding,
      "nova_checkpoint_get",
      "get-call",
      now + 4,
    );
    const current = runtime.callTool(
      "nova_checkpoint_get",
      { scopeProof: getProof },
      { now: now + 5 },
    );
    assert.equal(current.authorityGeneration, 1);
    assert.equal(current.taskCapsule.stageProjection.inheritedContracts[0].value, "Same-session only");
    assert.throws(() => runtime.callTool("nova_checkpoint_get", { scopeProof: getProof }), {
      code: "SCOPE_PROOF_INVALID",
    });
  } finally {
    temp.cleanup();
  }
});

test("missing, forged, expired, and mismatched proofs fail before checkpoint access", () => {
  const temp = temporaryDirectory();
  try {
    const now = Date.now();
    const scopeBinding = binding("codex", "proof-failures");
    startSession(temp.directory, scopeBinding, "0.1.0", "startup", { now });
    const runtime = new McpRuntime({
      dataRoot: temp.directory,
      pluginRoot,
      host: "codex",
    });
    assert.throws(() => runtime.callTool("nova_checkpoint_get", {}), {
      code: "SCOPE_PROOF_REQUIRED",
    });
    assert.throws(
      () => runtime.callTool("nova_checkpoint_get", { scopeProof: "f".repeat(64) }),
      { code: "SCOPE_PROOF_INVALID" },
    );
    const expired = proof(
      temp.directory,
      scopeBinding,
      "nova_checkpoint_get",
      "expired-call",
      now,
    );
    assert.throws(
      () => runtime.callTool(
        "nova_checkpoint_get",
        { scopeProof: expired },
        { now: now + SCOPE_PROOF_TTL_MS },
      ),
      { code: "SCOPE_PROOF_EXPIRED" },
    );
    const mismatched = proof(
      temp.directory,
      scopeBinding,
      "nova_checkpoint_get",
      "wrong-tool-call",
      now + 1,
    );
    assert.throws(
      () => runtime.callTool(
        "nova_checkpoint_save",
        { ...saveInput(0), scopeProof: mismatched },
        { now: now + 2 },
      ),
      { code: "SCOPE_PROOF_MISMATCH" },
    );
    assert.throws(
      () => runtime.callTool(
        "nova_checkpoint_get",
        { scopeProof: mismatched },
        { now: now + 3 },
      ),
      { code: "SCOPE_PROOF_INVALID" },
    );
  } finally {
    temp.cleanup();
  }
});

test("one MCP runtime routes same-directory sessions only by per-call proofs", () => {
  const temp = temporaryDirectory();
  try {
    const now = Date.now();
    const first = binding("codex", "first-session");
    const second = binding("codex", "second-session");
    for (const scopeBinding of [first, second]) {
      startSession(temp.directory, scopeBinding, "0.1.0", "startup", { now });
      markEvent(temp.directory, scopeBinding, "0.1.0", "prompt:1", { now: now + 1 });
    }
    const runtime = new McpRuntime({
      dataRoot: temp.directory,
      pluginRoot,
      host: "codex",
    });
    const firstInput = saveInput(1, {
      idempotencyKey: "first-save",
      taskCapsule: capsule({ objective: { value: "first", authorityState: "user-confirmed", source: "test" } }),
      scopeProof: proof(temp.directory, first, "nova_checkpoint_save", "first-save", now + 2),
    });
    const secondInput = saveInput(1, {
      idempotencyKey: "second-save",
      taskCapsule: capsule({ objective: { value: "second", authorityState: "user-confirmed", source: "test" } }),
      scopeProof: proof(temp.directory, second, "nova_checkpoint_save", "second-save", now + 2),
    });
    runtime.callTool("nova_checkpoint_save", firstInput, { now: now + 3 });
    runtime.callTool("nova_checkpoint_save", secondInput, { now: now + 3 });
    const firstValue = runtime.callTool(
      "nova_checkpoint_get",
      { scopeProof: proof(temp.directory, first, "nova_checkpoint_get", "first-get", now + 4) },
      { now: now + 5 },
    );
    const secondValue = runtime.callTool(
      "nova_checkpoint_get",
      { scopeProof: proof(temp.directory, second, "nova_checkpoint_get", "second-get", now + 4) },
      { now: now + 5 },
    );
    assert.equal(firstValue.taskCapsule.objective.value, "first");
    assert.equal(secondValue.taskCapsule.objective.value, "second");
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
  assert.equal(initialized.result.protocolVersion, "2025-06-18");
  const future = handleRpc(runtime, {
    jsonrpc: "2.0",
    id: "future",
    method: "initialize",
    params: { protocolVersion: "future-unsupported" },
  });
  assert.equal(future.result.protocolVersion, "2025-06-18");
  const failed = handleRpc(runtime, {
    jsonrpc: "2.0",
    id: 2,
    method: "tools/call",
    params: { name: "nova_checkpoint_get", arguments: {} },
  });
  assert.equal(failed.result.isError, true);
  assert.match(failed.result.content[0].text, /INTERNAL_ERROR/);
});

test("JSON-RPC notifications are silent and invalid request fields are rejected", () => {
  const runtime = {
    pluginVersion: "0.1.0",
    listTools: () => [],
    callTool: () => ({}),
  };
  assert.equal(
    handleRpc(runtime, { jsonrpc: "2.0", method: "tools/list", params: {} }),
    null,
  );
  assert.equal(
    handleRpc(runtime, { jsonrpc: "2.0", method: "unknown/notification" }),
    null,
  );
  assert.equal(
    handleRpc(runtime, { jsonrpc: "2.0", id: true, method: "ping" }).error.code,
    -32600,
  );
  assert.equal(
    handleRpc(runtime, { jsonrpc: "2.0", id: 1, method: "tools/call", params: [] }).error.code,
    -32602,
  );
  assert.equal(
    handleRpc(runtime, {
      jsonrpc: "2.0",
      id: 2,
      method: "initialize",
      params: { protocolVersion: 42 },
    }).error.code,
    -32602,
  );
});
