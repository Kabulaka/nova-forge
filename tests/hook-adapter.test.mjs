import assert from "node:assert/strict";
import fs from "node:fs";
import { Readable, Writable } from "node:stream";
import test from "node:test";

import {
  HOOK_INPUT_LIMIT,
  HookError,
  handleHook,
  main,
  readHookInput,
  resolvePluginRoot,
} from "../hooks/run.mjs";
import { pluginRoot } from "./helpers.mjs";

const environment = { PLUGIN_ROOT: pluginRoot };

test("SessionStart injects the same lightweight rules for every supported source", () => {
  const expected = fs.readFileSync(`${pluginRoot}/codex/AGENTS.global.md`, "utf8");
  for (const source of ["startup", "resume", "clear", "compact"]) {
    const output = handleHook({ hook_event_name: "SessionStart", source }, environment);
    assert.equal(output.hookSpecificOutput.hookEventName, "SessionStart");
    assert.equal(output.hookSpecificOutput.additionalContext, expected);
  }
});

test("non-SessionStart events do not inject context", () => {
  assert.deepEqual(handleHook({ hook_event_name: "PostToolUse" }, environment), {});
});

test("plugin root accepts host variables and rejects relative or missing roots", () => {
  assert.equal(resolvePluginRoot({ NOVA_PLUGIN_ROOT: pluginRoot }), pluginRoot);
  assert.equal(resolvePluginRoot({ CLAUDE_PLUGIN_ROOT: pluginRoot }), pluginRoot);
  assert.throws(() => resolvePluginRoot({ PLUGIN_ROOT: "relative" }), HookError);
  assert.throws(() => resolvePluginRoot({}), /absolute plugin root is unavailable/);
});

test("unsupported SessionStart sources fail explicitly", () => {
  assert.throws(
    () => handleHook({ hook_event_name: "SessionStart", source: "other" }, environment),
    /unsupported SessionStart source/,
  );
});

test("hook input parser enforces JSON object and byte limits", async () => {
  assert.deepEqual(
    await readHookInput(Readable.from(['{"hook_event_name":"SessionStart"}'])),
    { hook_event_name: "SessionStart" },
  );
  await assert.rejects(() => readHookInput(Readable.from(["[]"])), /JSON object/);
  await assert.rejects(
    () => readHookInput(Readable.from(["x".repeat(HOOK_INPUT_LIMIT + 1)])),
    /safety limit/,
  );
});

test("main fails open with a bounded error code", async () => {
  let stdout = "";
  let stderr = "";
  const outputStream = new Writable({ write(chunk, _encoding, callback) { stdout += chunk; callback(); } });
  const errorStream = new Writable({ write(chunk, _encoding, callback) { stderr += chunk; callback(); } });
  await main({
    inputStream: Readable.from(['{"hook_event_name":"SessionStart","source":"startup"}']),
    outputStream,
    errorStream,
    environment: {},
  });
  assert.equal(stdout, "");
  assert.equal(stderr, "Nova SessionStart hook failed open: PLUGIN_ROOT_UNAVAILABLE\n");
});
