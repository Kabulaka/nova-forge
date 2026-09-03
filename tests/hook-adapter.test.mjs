import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { detectHost, handleHook, resolvePluginPaths } from "../runtime/adapters/hook.mjs";
import { getCheckpoint, saveCheckpoint } from "../runtime/core/state-machine.mjs";
import { cwdKey, scopeKey } from "../runtime/core/util.mjs";
import { pluginRoot, saveInput, temporaryDirectory } from "./helpers.mjs";

function environment(dataRoot, host = "codex") {
  return {
    NOVA_HOST: host,
    NOVA_PLUGIN_ROOT: pluginRoot,
    NOVA_PLUGIN_DATA: dataRoot,
  };
}

function input(event, overrides = {}) {
  return {
    session_id: "hook-session",
    cwd: pluginRoot,
    hook_event_name: event,
    turn_id: "turn-1",
    ...overrides,
  };
}

function currentBinding(host = "codex") {
  return {
    host,
    sessionKey: scopeKey(host, "hook-session"),
    cwdHash: cwdKey(pluginRoot),
  };
}

test("host-native plugin variables resolve to the same shared runtime paths", () => {
  const codexData = path.join(pluginRoot, ".codex-data");
  const claudeData = path.join(pluginRoot, ".claude-data");
  assert.equal(detectHost({ PLUGIN_ROOT: pluginRoot, PLUGIN_DATA: codexData }), "codex");
  assert.deepEqual(
    resolvePluginPaths({ PLUGIN_ROOT: pluginRoot, PLUGIN_DATA: codexData }),
    { pluginRoot, dataRoot: codexData },
  );
  assert.equal(
    detectHost({ CLAUDE_PLUGIN_ROOT: pluginRoot, CLAUDE_PLUGIN_DATA: claudeData }),
    "claude-code",
  );
  assert.deepEqual(
    resolvePluginPaths({
      CLAUDE_PLUGIN_ROOT: pluginRoot,
      CLAUDE_PLUGIN_DATA: claudeData,
    }),
    { pluginRoot, dataRoot: claudeData },
  );
});

test("startup injects static rules without inventing a checkpoint", () => {
  const temp = temporaryDirectory();
  try {
    const output = handleHook(input("SessionStart", { source: "startup" }), environment(temp.directory));
    assert.match(output.hookSpecificOutput.additionalContext, /全局工作约定/);
    assert.doesNotMatch(output.hookSpecificOutput.additionalContext, /nova-recovery-capsule/);
    const state = getCheckpoint(temp.directory, currentBinding()).envelope;
    assert.equal(state.taskCapsule, null);
  } finally {
    temp.cleanup();
  }
});

test("prompt and tool hooks mark dirty while the checkpoint MCP tool is excluded", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory);
    handleHook(input("SessionStart", { source: "startup" }), env);
    handleHook(input("UserPromptSubmit"), env);
    handleHook(
      input("PostToolUse", { turn_id: "turn-2", tool_use_id: "tool-1", tool_name: "Bash" }),
      env,
    );
    handleHook(
      input("PostToolUse", {
        turn_id: "turn-2",
        tool_use_id: "tool-2",
        tool_name: "mcp__nova-forge__nova_checkpoint_save",
      }),
      env,
    );
    const state = getCheckpoint(temp.directory, currentBinding()).envelope;
    assert.equal(state.eventWatermark, 2);
    assert.equal(state.dirty, true);
    const stop = handleHook(input("Stop", { stop_hook_active: false }), env);
    assert.equal(stop.decision, "block");
  } finally {
    temp.cleanup();
  }
});

test("covered checkpoint passes Stop and completes the compact handshake", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory);
    handleHook(input("SessionStart", { source: "startup" }), env, { now: 1_000 });
    handleHook(input("UserPromptSubmit"), env, { now: 2_000 });
    saveCheckpoint(temp.directory, currentBinding(), "0.1.0", saveInput(1), { now: 3_000 });
    assert.deepEqual(handleHook(input("Stop"), env, { now: 4_000 }), {});
    assert.deepEqual(
      handleHook(input("PreCompact", { trigger: "auto" }), env, { now: 5_000 }),
      {},
    );
    assert.deepEqual(
      handleHook(input("PostCompact", { trigger: "auto" }), env, { now: 6_000 }),
      {},
    );
    const resumed = handleHook(
      input("SessionStart", { source: "compact", turn_id: "turn-2" }),
      env,
      { now: 7_000 },
    );
    assert.match(resumed.hookSpecificOutput.additionalContext, /nova-recovery-capsule/);
    assert.match(resumed.hookSpecificOutput.additionalContext, /Same-session only/);
    const state = getCheckpoint(temp.directory, currentBinding(), { now: 8_000 }).envelope;
    assert.equal(state.compactionHandshake.status, "injected");
  } finally {
    temp.cleanup();
  }
});

test("resume without a valid checkpoint stops instead of injecting defaults", () => {
  const temp = temporaryDirectory();
  try {
    const output = handleHook(
      input("SessionStart", { source: "resume" }),
      environment(temp.directory),
    );
    assert.equal(output.continue, false);
    assert.match(output.stopReason, /CHECKPOINT_NOT_COVERED/);
  } finally {
    temp.cleanup();
  }
});

test("Codex UserPromptSubmit failures use the supported continue false gate", () => {
  const temp = temporaryDirectory();
  try {
    const output = handleHook(
      input("UserPromptSubmit", { turn_id: "" }),
      environment(temp.directory),
    );
    assert.equal(output.continue, false);
    assert.match(output.stopReason, /EVENT_ID_UNAVAILABLE/);
    assert.equal(Object.hasOwn(output, "decision"), false);
  } finally {
    temp.cleanup();
  }
});

test("Claude Code records a PostCompact mismatch even though the event cannot block", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory, "claude-code");
    handleHook(input("SessionStart", { source: "startup" }), env, { now: 1_000 });
    const output = handleHook(input("PostCompact", { trigger: "manual" }), env, { now: 2_000 });
    assert.deepEqual(output, {});
    const state = getCheckpoint(temp.directory, currentBinding("claude-code"), { now: 3_000 }).envelope;
    assert.equal(state.compactionHandshake.status, "failed");
  } finally {
    temp.cleanup();
  }
});
