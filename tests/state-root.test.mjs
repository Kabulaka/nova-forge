import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  bootstrapStateRoot,
  resolveNovaHome,
} from "../runtime/core/state-root.mjs";
import { startSession } from "../runtime/core/state-machine.mjs";
import { binding, pluginRoot, temporaryDirectory } from "./helpers.mjs";

test("Nova home defaults to the user directory and accepts only an absolute override", () => {
  const home = path.resolve("/users/nova");
  assert.equal(resolveNovaHome({}, { homeDirectory: home }), path.join(home, ".nova"));
  assert.equal(resolveNovaHome({ NOVA_HOME: path.resolve("/state/nova") }), path.resolve("/state/nova"));
  assert.throws(() => resolveNovaHome({ NOVA_HOME: "" }), { code: "NOVA_HOME_INVALID" });
  assert.throws(() => resolveNovaHome({ NOVA_HOME: "relative/nova" }), {
    code: "NOVA_HOME_INVALID",
  });
});

test("bootstrap creates host-private layout, proves writes, and is idempotent", () => {
  const temp = temporaryDirectory();
  try {
    const dataRoot = path.join(temp.directory, ".nova");
    const first = bootstrapStateRoot({ dataRoot, host: "codex", legacyRoots: [] });
    const second = bootstrapStateRoot({ dataRoot, host: "codex", legacyRoots: [] });
    assert.equal(first.dataRoot, dataRoot);
    assert.equal(second.dataRoot, dataRoot);
    for (const relative of ["state/codex", "rendezvous/codex", "migrations/codex"]) {
      assert.equal(fs.statSync(path.join(dataRoot, relative)).isDirectory(), true);
    }
    assert.deepEqual(
      fs.readdirSync(dataRoot).filter((name) => name.startsWith(".bootstrap.")),
      [],
    );
  } finally {
    temp.cleanup();
  }
});

test("Codex and Claude Code bootstrap the same root concurrently without sharing partitions", async () => {
  const temp = temporaryDirectory();
  try {
    const dataRoot = path.join(temp.directory, ".nova");
    const run = (host) =>
      new Promise((resolve) => {
        const child = spawn(
          process.execPath,
          [path.join(pluginRoot, "runtime", "bootstrap.mjs"), "--host", host],
          { env: { ...process.env, NOVA_HOME: dataRoot }, stdio: ["ignore", "pipe", "pipe"] },
        );
        let stderr = "";
        child.stderr.on("data", (chunk) => {
          stderr += chunk;
        });
        child.on("close", (status) => resolve({ status, stderr }));
      });
    const results = await Promise.all([run("codex"), run("claude-code")]);
    for (const result of results) assert.equal(result.status, 0, result.stderr);
    for (const host of ["codex", "claude-code"]) {
      assert.equal(fs.existsSync(path.join(dataRoot, "state", host)), true);
      assert.equal(fs.existsSync(path.join(dataRoot, "rendezvous", host)), true);
    }
  } finally {
    temp.cleanup();
  }
});

test("bootstrap reports the target and NOVA_HOME recovery without falling back", () => {
  const temp = temporaryDirectory();
  try {
    const blocked = path.join(temp.directory, "blocked");
    fs.writeFileSync(blocked, "not a directory\n");
    assert.throws(
      () => bootstrapStateRoot({ dataRoot: blocked, host: "codex", legacyRoots: [] }),
      (error) => {
        assert.equal(error.code, "STATE_ROOT_UNAVAILABLE");
        assert.match(error.message, new RegExp(blocked.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
        assert.match(error.message, /NOVA_HOME/);
        return true;
      },
    );
    assert.deepEqual(fs.readdirSync(temp.directory), ["blocked"]);
  } finally {
    temp.cleanup();
  }
});

test("legacy migration copies only the current host and preserves the source", () => {
  const temp = temporaryDirectory();
  try {
    const legacyRoot = path.join(temp.directory, "legacy");
    const dataRoot = path.join(temp.directory, "new");
    const codexBinding = binding("codex", "same-name");
    const claudeBinding = binding("claude-code", "same-name");
    startSession(legacyRoot, codexBinding, "0.1.0", "startup", { now: Date.now() });
    startSession(legacyRoot, claudeBinding, "0.1.0", "startup", { now: Date.now() });
    fs.mkdirSync(path.join(legacyRoot, "rendezvous"), { recursive: true });
    fs.writeFileSync(path.join(legacyRoot, "rendezvous", "do-not-copy"), "secret\n");
    const sourceFile = path.join(
      legacyRoot,
      "state",
      "codex",
      codexBinding.sessionKey,
      "current.json",
    );
    const sourceBytes = fs.readFileSync(sourceFile);

    const first = bootstrapStateRoot({
      dataRoot,
      host: "codex",
      legacyRoots: [legacyRoot],
    });
    const second = bootstrapStateRoot({
      dataRoot,
      host: "codex",
      legacyRoots: [legacyRoot],
    });

    assert.deepEqual(
      fs.readFileSync(path.join(dataRoot, "state", "codex", codexBinding.sessionKey, "current.json")),
      sourceBytes,
    );
    assert.equal(fs.existsSync(path.join(dataRoot, "state", "claude-code")), false);
    assert.equal(fs.existsSync(path.join(dataRoot, "rendezvous", "do-not-copy")), false);
    assert.deepEqual(fs.readFileSync(sourceFile), sourceBytes);
    assert.equal(first.migrations[0].idempotent, false);
    assert.equal(second.migrations[0].idempotent, true);
    const recordRoot = path.join(dataRoot, "migrations", "codex");
    const recordFiles = fs.readdirSync(recordRoot).filter((name) => name.endsWith(".json"));
    assert.equal(recordFiles.length, 1);
    const record = fs.readFileSync(path.join(recordRoot, recordFiles[0]), "utf8");
    assert.doesNotMatch(record, /same-name/);
  } finally {
    temp.cleanup();
  }
});

test("migration interruption keeps the source and resumes from equivalent published state", () => {
  const temp = temporaryDirectory();
  try {
    const legacyRoot = path.join(temp.directory, "legacy");
    const dataRoot = path.join(temp.directory, "new");
    const current = binding("codex", "interrupt");
    startSession(legacyRoot, current, "0.1.0", "startup", { now: Date.now() });
    assert.throws(
      () =>
        bootstrapStateRoot({
          dataRoot,
          host: "codex",
          legacyRoots: [legacyRoot],
          faultInjector(stage) {
            if (stage === "migration-record") throw new Error("injected migration interruption");
          },
        }),
      { code: "STATE_ROOT_UNAVAILABLE" },
    );
    assert.equal(
      fs.existsSync(path.join(dataRoot, "state", "codex", current.sessionKey, "current.json")),
      true,
    );
    const resumed = bootstrapStateRoot({ dataRoot, host: "codex", legacyRoots: [legacyRoot] });
    assert.equal(resumed.migrations[0].status, "completed");
    assert.equal(
      fs.existsSync(path.join(legacyRoot, "state", "codex", current.sessionKey, "current.json")),
      true,
    );
  } finally {
    temp.cleanup();
  }
});

test("invalid legacy state and a different valid target both fail closed", () => {
  const invalid = temporaryDirectory();
  try {
    const legacyRoot = path.join(invalid.directory, "legacy");
    const dataRoot = path.join(invalid.directory, "new");
    const scope = "a".repeat(64);
    fs.mkdirSync(path.join(legacyRoot, "state", "codex", scope), { recursive: true });
    fs.writeFileSync(path.join(legacyRoot, "state", "codex", scope, "current.json"), "{}\n");
    assert.throws(
      () => bootstrapStateRoot({ dataRoot, host: "codex", legacyRoots: [legacyRoot] }),
      { code: "STATE_ROOT_UNAVAILABLE" },
    );
    assert.equal(fs.existsSync(path.join(dataRoot, "state", "codex", scope)), false);
  } finally {
    invalid.cleanup();
  }

  const conflict = temporaryDirectory();
  try {
    const legacyRoot = path.join(conflict.directory, "legacy");
    const dataRoot = path.join(conflict.directory, "new");
    const current = binding("codex", "conflict");
    startSession(legacyRoot, current, "0.1.0", "startup", { now: Date.now() });
    startSession(dataRoot, current, "0.2.0", "startup", { now: Date.now() + 1 });
    assert.throws(
      () => bootstrapStateRoot({ dataRoot, host: "codex", legacyRoots: [legacyRoot] }),
      (error) => {
        assert.equal(error.code, "STATE_ROOT_UNAVAILABLE");
        assert.match(error.message, /different valid checkpoint/);
        return true;
      },
    );
  } finally {
    conflict.cleanup();
  }
});

test(
  "MCP initialize succeeds with a read-only plugin tree and a writable Nova home",
  { skip: process.platform === "win32" },
  () => {
    const temp = temporaryDirectory();
    try {
      const copiedRoot = path.join(temp.directory, "plugin-cache");
      fs.mkdirSync(copiedRoot);
      fs.cpSync(path.join(pluginRoot, "runtime"), path.join(copiedRoot, "runtime"), {
        recursive: true,
      });
      fs.copyFileSync(path.join(pluginRoot, "package.json"), path.join(copiedRoot, "package.json"));
      for (const entry of fs.readdirSync(copiedRoot, { recursive: true })) {
        const target = path.join(copiedRoot, entry);
        fs.chmodSync(target, fs.statSync(target).isDirectory() ? 0o555 : 0o444);
      }
      fs.chmodSync(copiedRoot, 0o555);
      const dataRoot = path.join(temp.directory, ".nova");
      const result = spawnSync(
        process.execPath,
        [path.join(copiedRoot, "runtime", "mcp", "server.mjs"), "--host", "codex"],
        {
          cwd: copiedRoot,
          input: `${JSON.stringify({
            jsonrpc: "2.0",
            id: 1,
            method: "initialize",
            params: { protocolVersion: "2025-06-18" },
          })}\n`,
          encoding: "utf8",
          env: {
            ...process.env,
            NOVA_HOME: dataRoot,
            NOVA_PLUGIN_ROOT: copiedRoot,
          },
        },
      );
      assert.equal(result.status, 0, result.stderr);
      assert.equal(JSON.parse(result.stdout).result.serverInfo.name, "nova-checkpoint");
      assert.equal(fs.existsSync(path.join(dataRoot, "rendezvous", "codex")), true);
    } finally {
      const copiedRoot = path.join(temp.directory, "plugin-cache");
      if (fs.existsSync(copiedRoot)) {
        fs.chmodSync(copiedRoot, 0o755);
        for (const entry of fs.readdirSync(copiedRoot, { recursive: true })) {
          const target = path.join(copiedRoot, entry);
          if (fs.statSync(target).isDirectory()) fs.chmodSync(target, 0o755);
        }
      }
      temp.cleanup();
    }
  },
);
