import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { mountNova } from "../dsh/mount.mjs";
import { pluginRoot } from "./helpers.mjs";

test("incomplete DSH packages fail before any plugin is registered", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-missing-dsh-"));
  try {
    const ctx = { plugin() { assert.fail("partial registration"); } };
    await assert.rejects(mountNova(ctx, {}, {}, root), /installation is incomplete: hooks\/run.mjs/);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("missing linked resources and invalid hook configuration cannot partially mount Nova", async () => {
  for (const failure of ["asset", "json", "event"]) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-invalid-dsh-"));
    try {
      for (const directory of ["hooks", "skills", "codex"]) {
        fs.cpSync(path.join(pluginRoot, directory), path.join(root, directory), { recursive: true });
      }
      if (failure === "asset") fs.unlinkSync(path.join(root, "skills/nova-development/assets/DESIGN.template.md"));
      if (failure === "json") fs.writeFileSync(path.join(root, "hooks/hooks.json"), "{");
      if (failure === "event") fs.writeFileSync(path.join(root, "hooks/hooks.json"), '{"hooks":{}}');
      const ctx = { plugin() { assert.fail("partial registration"); } };
      const expected = failure === "asset" ? /installation is incomplete: skills\/nova-development\/assets\/DESIGN.template.md/ : failure === "json" ? SyntaxError : /no SessionStart hook/;
      await assert.rejects(mountNova(ctx, {}, {}, root), expected);
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  }
});

test("invalid runnable groups and matchers fail before any DSH registration", async () => {
  const command = { type: "command", command: 'node "${CLAUDE_PLUGIN_ROOT}/hooks/run.mjs"' };
  const cases = [
    { groups: "startup", error: /no SessionStart hook/ },
    { groups: [null], error: /invalid SessionStart hook/ },
    { groups: [{ hooks: [] }], error: /invalid SessionStart hook/ },
    { groups: [{ hooks: {} }], error: /invalid SessionStart hook/ },
    { groups: [{ hooks: [null] }], error: /invalid SessionStart hook/ },
    { groups: [{ hooks: [{ ...command, type: "prompt" }] }], error: /invalid SessionStart hook/ },
    { groups: [{ hooks: [{ ...command, command: 42 }] }], error: /invalid SessionStart hook/ },
    { groups: [{ hooks: [{ ...command, command: "  " }] }], error: /invalid SessionStart hook/ },
    { groups: [{ matcher: 42, hooks: [command] }], error: /invalid SessionStart hook/ },
    { groups: [{ matcher: "[", hooks: [command] }], error: /invalid SessionStart matcher/ },
    { groups: [{ matcher: "startup|resume|clear", hooks: [command] }], error: /uncovered SessionStart sources: compact/ },
    // A later malformed group must fail even after an earlier group covers all sources.
    { groups: [{ hooks: [command] }, { matcher: "[", hooks: [command] }], error: /invalid SessionStart matcher/ },
  ];
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-invalid-dsh-hooks-"));
  try {
    for (const directory of ["hooks", "skills", "codex"]) {
      fs.cpSync(path.join(pluginRoot, directory), path.join(root, directory), { recursive: true });
    }
    const ctx = {
      isolate() { assert.fail("partial shell scope registration"); },
      plugin() { assert.fail("partial plugin registration"); },
    };
    for (const { groups, error } of cases) {
      fs.writeFileSync(path.join(root, "hooks/hooks.json"), JSON.stringify({ hooks: { SessionStart: groups } }));
      await assert.rejects(mountNova(ctx, {}, {}, root), error);
    }
    // Preserve all official match-all, literal-alternative and regex forms.
    for (const groups of [
      [{ hooks: [command] }],
      [{ matcher: "", hooks: [command] }],
      [{ matcher: "*", hooks: [command] }],
      [{ matcher: "^(startup|resume|clear|compact)$", hooks: [command] }],
      ["startup|resume", "clear|compact"].map((matcher) => ({ matcher, hooks: [command] })),
    ]) {
      fs.writeFileSync(path.join(root, "hooks/hooks.json"), JSON.stringify({ hooks: { SessionStart: groups } }));
      let registrations = 0;
      const scope = { async plugin() { registrations++; } };
      await mountNova({ isolate: () => scope, async plugin() { registrations++; } }, {}, {}, root);
      assert.equal(registrations, 3);
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("DSH hook environment stays inside its shell scope and preserves request options", async () => {
  const skill = {};
  const bridge = {};
  const calls = [];
  const parentShell = { resolve: (request) => request, execute: (spec) => spec };
  let scopedShell;
  const scoped = {
    async plugin(plugin, config) {
      if (plugin.apply) plugin.apply({ provide(_name, value) { scopedShell = value; } });
      else calls.push({ plugin, config, scope: "hook" });
    },
  };
  const ctx = {
    shell: parentShell,
    isolate(service) { assert.equal(service, "shell"); return scoped; },
    async plugin(plugin, config) { calls.push({ plugin, config, scope: "parent" }); },
  };
  const before = { ...process.env };
  await mountNova(ctx, skill, bridge);
  const request = { command: "node", cwd: "/project", env: { CUSTOM: "kept", NOVA_PLUGIN_ROOT: "stale" }, signal: new AbortController().signal };
  const resolved = scopedShell.resolve(request);
  assert.equal(resolved.cwd, request.cwd);
  assert.equal(resolved.signal, request.signal);
  assert.deepEqual(resolved.env, { CUSTOM: "kept", NOVA_PLUGIN_ROOT: pluginRoot, NOVA_DSH_ROOT: pluginRoot });
  assert.equal(scopedShell.execute(resolved), resolved);
  assert.equal(parentShell.resolve(request), request);
  assert.equal(request.env.NOVA_PLUGIN_ROOT, "stale");
  const changedKeys = [...new Set([...Object.keys(process.env), ...Object.keys(before)])]
    .filter((key) => process.env[key] !== before[key]);
  assert.deepEqual(changedKeys, []);
  assert.deepEqual(calls, [
    { plugin: bridge, config: { configPath: path.join(pluginRoot, "hooks/hooks.json"), pluginRoot }, scope: "hook" },
    { plugin: skill, config: { providerName: "nova-forge", includeDefaultRoots: false, customSkillDirs: [path.join(pluginRoot, "skills")], watch: false }, scope: "parent" },
  ]);
});
