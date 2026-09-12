import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { Readable } from "node:stream";
import { pathToFileURL } from "node:url";
import test from "node:test";
import { readHookInput } from "../hooks/run.mjs";
import { detectHost, handleHook, resolvePluginPaths } from "../runtime/adapters/hook.mjs";
import { HOOK_INPUT_LIMIT } from "../runtime/core/constants.mjs";
import { getCheckpoint, saveCheckpoint } from "../runtime/core/state-machine.mjs";
import { cwdKey, scopeKey } from "../runtime/core/util.mjs";
import { pluginRoot, saveInput, temporaryDirectory } from "./helpers.mjs";

function environment(dataRoot, host = "codex") {
  return {
    NOVA_HOST: host,
    NOVA_PLUGIN_ROOT: pluginRoot,
    NOVA_HOME: dataRoot,
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

function runHookProcessWithLimit(dataRoot, host, inputValue, inputLimit) {
  const moduleUrl = pathToFileURL(path.join(pluginRoot, "hooks", "run.mjs")).href;
  const script = `import { main } from ${JSON.stringify(moduleUrl)}; await main({ inputLimit: ${inputLimit} });`;
  return spawnSync(process.execPath, ["--input-type=module", "--eval", script], {
    cwd: pluginRoot,
    input: inputValue,
    encoding: "utf8",
    env: {
      ...process.env,
      NOVA_HOST: host,
      NOVA_PLUGIN_ROOT: pluginRoot,
      NOVA_HOME: dataRoot,
    },
  });
}

test("host-native plugin variables are legacy sources while NOVA_HOME is authoritative", () => {
  const codexData = path.join(pluginRoot, ".codex-data");
  const claudeData = path.join(pluginRoot, ".claude-data");
  const codexHome = path.join(pluginRoot, ".nova-codex");
  const claudeHome = path.join(pluginRoot, ".nova-claude");
  assert.equal(detectHost({ PLUGIN_ROOT: pluginRoot, PLUGIN_DATA: codexData }), "codex");
  assert.deepEqual(
    resolvePluginPaths({ PLUGIN_ROOT: pluginRoot, PLUGIN_DATA: codexData, NOVA_HOME: codexHome }),
    { pluginRoot, dataRoot: codexHome, legacyRoots: [codexData] },
  );
  assert.equal(
    detectHost({ CLAUDE_PLUGIN_ROOT: pluginRoot, CLAUDE_PLUGIN_DATA: claudeData }),
    "claude-code",
  );
  assert.deepEqual(
    resolvePluginPaths({
      CLAUDE_PLUGIN_ROOT: pluginRoot,
      CLAUDE_PLUGIN_DATA: claudeData,
      NOVA_HOME: claudeHome,
    }),
    { pluginRoot, dataRoot: claudeHome, legacyRoots: [claudeData] },
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

test("SessionStart keeps static rules and allows startup when the state root cannot initialize", () => {
  const temp = temporaryDirectory();
  try {
    const unavailableRoot = path.join(temp.directory, "not-a-directory");
    fs.writeFileSync(unavailableRoot, "occupied");
    const output = handleHook(
      input("SessionStart", { source: "startup" }),
      environment(unavailableRoot),
    );
    assert.match(output.hookSpecificOutput.additionalContext, /全局工作约定/);
    assert.match(output.hookSpecificOutput.additionalContext, /nova-checkpoint-degraded/);
    assert.match(output.systemMessage, /NOVA_HOME|not-a-directory/);
    assert.equal(Object.hasOwn(output, "decision"), false);
    assert.equal(Object.hasOwn(output, "continue"), false);
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
        tool_name: "mcp__nova_checkpoint__nova_checkpoint_save",
      }),
      env,
    );
    handleHook(
      input("PostToolUse", {
        turn_id: "turn-2",
        tool_use_id: "tool-3",
        tool_name: "mcp__other__nova_checkpoint_save",
      }),
      env,
    );
    const state = getCheckpoint(temp.directory, currentBinding()).envelope;
    assert.equal(state.eventWatermark, 3);
    assert.equal(state.dirty, true);
    const stop = handleHook(input("Stop", { stop_hook_active: false }), env);
    assert.match(stop.systemMessage, /CHECKPOINT_NOT_COVERED/);
    assert.match(stop.systemMessage, /host operation was allowed to continue/);
    assert.equal(Object.hasOwn(stop, "decision"), false);
    assert.equal(Object.hasOwn(stop, "continue"), false);

    const repeatedStop = handleHook(input("Stop", { stop_hook_active: true }), env);
    assert.deepEqual(repeatedStop, {});

    saveCheckpoint(temp.directory, currentBinding(), "0.1.0", saveInput(3));
    assert.deepEqual(handleHook(input("Stop"), env), {});
    handleHook(input("UserPromptSubmit", { turn_id: "turn-3" }), env);
    const nextUncoveredGeneration = handleHook(input("Stop"), env);
    assert.match(nextUncoveredGeneration.systemMessage, /CHECKPOINT_NOT_COVERED/);
    assert.deepEqual(handleHook(input("Stop", { stop_hook_active: true }), env), {});

    handleHook(input("SessionStart", { source: "clear", turn_id: "turn-4" }), env);
    const afterClear = handleHook(input("Stop"), env);
    assert.match(afterClear.systemMessage, /CHECKPOINT_NOT_COVERED/);
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

test("Claude Code early compact SessionStart degrades while a later PostCompact completes", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory, "claude-code");
    handleHook(input("SessionStart", { source: "startup" }), env, { now: 1_000 });
    handleHook(input("UserPromptSubmit", { turn_id: undefined }), env, { now: 2_000 });
    saveCheckpoint(temp.directory, currentBinding("claude-code"), "0.1.0", saveInput(1), {
      now: 3_000,
    });
    assert.deepEqual(
      handleHook(input("PreCompact", { trigger: "manual" }), env, { now: 4_000 }),
      {},
    );

    const earlyResume = handleHook(
      input("SessionStart", { source: "compact", turn_id: "turn-compact" }),
      env,
      { now: 5_000 },
    );
    assert.match(earlyResume.hookSpecificOutput.additionalContext, /nova-checkpoint-degraded/);
    assert.doesNotMatch(earlyResume.hookSpecificOutput.additionalContext, /nova-recovery-capsule/);
    assert.match(earlyResume.systemMessage, /COMPACTION_HANDSHAKE_MISMATCH/);
    assert.equal(Object.hasOwn(earlyResume, "decision"), false);
    assert.equal(Object.hasOwn(earlyResume, "continue"), false);

    assert.deepEqual(
      handleHook(input("PostCompact", { trigger: "manual" }), env, { now: 6_000 }),
      {},
    );
    const state = getCheckpoint(temp.directory, currentBinding("claude-code"), { now: 7_000 }).envelope;
    assert.equal(state.compactionHandshake.status, "completed");
    assert.equal(state.compactionHandshake.completedWatermark, 1);
  } finally {
    temp.cleanup();
  }
});

test("resume without a covered checkpoint enters explicit recovery without injecting defaults", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory);
    const output = handleHook(
      input("SessionStart", { source: "resume" }),
      env,
    );
    assert.match(output.hookSpecificOutput.additionalContext, /全局工作约定/);
    assert.match(output.hookSpecificOutput.additionalContext, /nova-checkpoint-recovery-required/);
    assert.match(output.hookSpecificOutput.additionalContext, /"eventWatermark":0/);
    assert.doesNotMatch(output.hookSpecificOutput.additionalContext, /nova-recovery-capsule/);
    assert.match(output.systemMessage, /without injecting an authoritative checkpoint/);

    handleHook(input("UserPromptSubmit"), env, { now: 2_000 });
    saveCheckpoint(temp.directory, currentBinding(), "0.1.0", saveInput(1), { now: 3_000 });
    assert.deepEqual(handleHook(input("Stop"), env, { now: 4_000 }), {});
  } finally {
    temp.cleanup();
  }
});

test("dirty resume never injects the stale task capsule as authority", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory);
    handleHook(input("SessionStart", { source: "startup" }), env, { now: 1_000 });
    handleHook(input("UserPromptSubmit"), env, { now: 2_000 });
    const saved = saveInput(1);
    saved.taskCapsule.objective.value = "STALE_CAPSULE_SENTINEL";
    saveCheckpoint(temp.directory, currentBinding(), "0.1.0", saved, { now: 3_000 });
    handleHook(input("UserPromptSubmit", { turn_id: "turn-2" }), env, { now: 4_000 });

    const output = handleHook(
      input("SessionStart", { source: "resume", turn_id: "turn-3" }),
      env,
      { now: 5_000 },
    );
    assert.match(output.hookSpecificOutput.additionalContext, /"eventWatermark":2/);
    assert.match(output.hookSpecificOutput.additionalContext, /"coveredEventWatermark":1/);
    assert.doesNotMatch(output.hookSpecificOutput.additionalContext, /STALE_CAPSULE_SENTINEL/);
    assert.doesNotMatch(output.hookSpecificOutput.additionalContext, /nova-recovery-capsule/);
  } finally {
    temp.cleanup();
  }
});

test("compact without a covered checkpoint degrades without blocking or injecting authority", () => {
  const temp = temporaryDirectory();
  try {
    const output = handleHook(
      input("SessionStart", { source: "compact" }),
      environment(temp.directory),
    );
    assert.match(output.hookSpecificOutput.additionalContext, /全局工作约定/);
    assert.match(output.hookSpecificOutput.additionalContext, /nova-checkpoint-degraded/);
    assert.doesNotMatch(output.hookSpecificOutput.additionalContext, /nova-recovery-capsule/);
    assert.match(output.systemMessage, /CHECKPOINT_NOT_COVERED/);
    assert.equal(Object.hasOwn(output, "decision"), false);
    assert.equal(Object.hasOwn(output, "continue"), false);
  } finally {
    temp.cleanup();
  }
});

test("Codex UserPromptSubmit failures report degradation without blocking conversation", () => {
  const temp = temporaryDirectory();
  try {
    const output = handleHook(
      input("UserPromptSubmit", { turn_id: "" }),
      environment(temp.directory),
    );
    assert.match(output.systemMessage, /EVENT_ID_UNAVAILABLE/);
    assert.match(output.systemMessage, /host operation was allowed to continue/);
    assert.equal(Object.hasOwn(output, "continue"), false);
    assert.equal(Object.hasOwn(output, "decision"), false);
  } finally {
    temp.cleanup();
  }
});

test("corrupt checkpoint state cannot block Stop or become recovery authority", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory);
    handleHook(input("SessionStart", { source: "startup" }), env);
    const currentFile = path.join(
      temp.directory,
      "state",
      "codex",
      currentBinding().sessionKey,
      "current.json",
    );
    fs.writeFileSync(currentFile, "{not-json");

    const stop = handleHook(input("Stop"), env);
    assert.match(stop.systemMessage, /CHECKPOINT|JSON|parse|corrupt|invalid/i);
    assert.match(stop.systemMessage, /host operation was allowed to continue/);
    assert.equal(Object.hasOwn(stop, "decision"), false);
    assert.equal(Object.hasOwn(stop, "continue"), false);

    const resumed = handleHook(input("SessionStart", { source: "resume" }), env);
    assert.match(resumed.hookSpecificOutput.additionalContext, /nova-checkpoint-degraded/);
    assert.doesNotMatch(resumed.hookSpecificOutput.additionalContext, /nova-recovery-capsule/);
  } finally {
    temp.cleanup();
  }
});

test("Claude Code records a PostCompact mismatch and reports it without blocking", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory, "claude-code");
    handleHook(input("SessionStart", { source: "startup" }), env, { now: 1_000 });
    const output = handleHook(input("PostCompact", { trigger: "manual" }), env, { now: 2_000 });
    assert.match(output.systemMessage, /COMPACTION_HANDSHAKE_MISMATCH/);
    assert.equal(Object.hasOwn(output, "decision"), false);
    assert.equal(Object.hasOwn(output, "continue"), false);
    const state = getCheckpoint(temp.directory, currentBinding("claude-code"), { now: 3_000 }).envelope;
    assert.equal(state.compactionHandshake.status, "failed");
  } finally {
    temp.cleanup();
  }
});

test("Claude Code UserPromptSubmit does not require Codex turn ids", () => {
  const temp = temporaryDirectory();
  try {
    const env = environment(temp.directory, "claude-code");
    handleHook(input("SessionStart", { source: "startup" }), env, { now: 1_000 });
    const prompt = input("UserPromptSubmit", { prompt: "same prompt", turn_id: undefined });
    assert.deepEqual(handleHook(prompt, env, { now: 2_000 }), {});
    assert.deepEqual(handleHook(prompt, env, { now: 3_000 }), {});
    handleHook(
      input("PostToolUse", {
        tool_use_id: "claude-own-tool",
        tool_name: "mcp__plugin_nova-forge_nova-checkpoint__nova_checkpoint_save",
      }),
      env,
      { now: 3_500 },
    );
    handleHook(
      input("PostToolUse", {
        tool_use_id: "claude-other-tool",
        tool_name: "mcp__other__nova_checkpoint_save",
      }),
      env,
      { now: 3_600 },
    );
    const state = getCheckpoint(temp.directory, currentBinding("claude-code"), { now: 4_000 }).envelope;
    assert.equal(state.eventWatermark, 3);
  } finally {
    temp.cleanup();
  }
});

test("Claude Code PreCompact setup failures report degradation without blocking", () => {
  const temp = temporaryDirectory();
  try {
    const output = handleHook(
      input("PreCompact", { trigger: "auto", session_id: "" }),
      environment(temp.directory, "claude-code"),
    );
    assert.match(output.systemMessage, /SESSION_ID_UNAVAILABLE/);
    assert.equal(Object.hasOwn(output, "decision"), false);
    assert.equal(Object.hasOwn(output, "continue"), false);
  } finally {
    temp.cleanup();
  }
});

test("malformed hook input reports diagnostics but exits successfully for both hosts", () => {
  for (const host of ["codex", "claude-code"]) {
    const temp = temporaryDirectory();
    try {
      const result = spawnSync(process.execPath, [path.join(pluginRoot, "hooks", "run.mjs")], {
        cwd: pluginRoot,
        input: "{not-json",
        encoding: "utf8",
        env: {
          ...process.env,
          NOVA_HOST: host,
          NOVA_PLUGIN_ROOT: pluginRoot,
          NOVA_HOME: temp.directory,
        },
      });
      assert.equal(result.status, 0);
      assert.match(result.stderr, /host operation was allowed to continue/);
      assert.equal(result.stdout, "");
    } finally {
      temp.cleanup();
    }
  }
});

test("hook input accepts the exact byte boundary and keeps 1M-context headroom", async () => {
  assert.equal(HOOK_INPUT_LIMIT, 256 * 1024 * 1024);
  const json = '{"padding":"0123456789"}';
  assert.equal(Buffer.byteLength(json), 24);
  assert.deepEqual(await readHookInput(Readable.from([json]), 24), { padding: "0123456789" });
});

test("oversized hook input does not advance state or block either host", () => {
  for (const host of ["codex", "claude-code"]) {
    const temp = temporaryDirectory();
    try {
      const result = runHookProcessWithLimit(temp.directory, host, 'x'.repeat(65), 64);
      assert.deepEqual(fs.readdirSync(temp.directory), []);
      assert.equal(result.status, 0);
      assert.equal(result.stdout, "");
      assert.match(result.stderr, /hook input exceeds the 64-byte safety limit/);
      assert.match(result.stderr, /host operation was allowed to continue/);
    } finally {
      temp.cleanup();
    }
  }
});

test("hook entrypoint degrades safely from installation paths requiring URL escaping", () => {
  const temp = temporaryDirectory("nova 插件 ");
  try {
    const copiedRoot = path.join(temp.directory, "Plugin With 空格");
    fs.mkdirSync(copiedRoot);
    fs.cpSync(path.join(pluginRoot, "hooks"), path.join(copiedRoot, "hooks"), { recursive: true });
    fs.cpSync(path.join(pluginRoot, "runtime"), path.join(copiedRoot, "runtime"), { recursive: true });
    const result = spawnSync(process.execPath, [path.join(copiedRoot, "hooks", "run.mjs")], {
      cwd: copiedRoot,
      input: "{not-json",
      encoding: "utf8",
      env: {
        ...process.env,
        NOVA_HOST: "claude-code",
        NOVA_PLUGIN_ROOT: copiedRoot,
        NOVA_HOME: path.join(temp.directory, "data"),
      },
    });
    assert.equal(result.status, 0);
    assert.match(result.stderr, /Nova hook failed/);
    assert.match(result.stderr, /host operation was allowed to continue/);
    assert.equal(result.stdout, "");
  } finally {
    temp.cleanup();
  }
});

test(
  "hook entrypoint degrades safely when the invoked path resolves through a filesystem alias",
  { skip: process.platform === "win32" },
  () => {
    const temp = temporaryDirectory("nova-alias-");
    try {
      const copiedRoot = path.join(temp.directory, "plugin-root");
      const aliasRoot = path.join(temp.directory, "plugin-alias");
      fs.mkdirSync(copiedRoot);
      fs.cpSync(path.join(pluginRoot, "hooks"), path.join(copiedRoot, "hooks"), { recursive: true });
      fs.cpSync(path.join(pluginRoot, "runtime"), path.join(copiedRoot, "runtime"), { recursive: true });
      fs.symlinkSync(copiedRoot, aliasRoot, "dir");
      const result = spawnSync(process.execPath, [path.join(aliasRoot, "hooks", "run.mjs")], {
        cwd: aliasRoot,
        input: "{not-json",
        encoding: "utf8",
        env: {
          ...process.env,
          NOVA_HOST: "claude-code",
          NOVA_PLUGIN_ROOT: aliasRoot,
          NOVA_HOME: path.join(temp.directory, "data"),
        },
      });
      assert.equal(result.status, 0);
      assert.match(result.stderr, /Nova hook failed/);
      assert.match(result.stderr, /host operation was allowed to continue/);
      assert.equal(result.stdout, "");
    } finally {
      temp.cleanup();
    }
  },
);

test("hook entrypoint path resolution failures cannot exit successfully without output", () => {
  const moduleUrl = pathToFileURL(path.join(pluginRoot, "hooks", "run.mjs")).href;
  const missingPath = path.join(os.tmpdir(), `missing-nova-hook-${process.pid}-${Date.now()}.mjs`);
  const result = spawnSync(
    process.execPath,
    ["--input-type=module", "--eval", `await import(${JSON.stringify(moduleUrl)})`, missingPath],
    {
      cwd: pluginRoot,
      encoding: "utf8",
    },
  );
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, "");
  assert.match(result.stderr, /ENOENT|realpath/i);
});
