import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  buildSnapshot,
  captureHostCaches,
  DEV_MARKETPLACE_NAME,
  installClaudeDevelopmentPlugin,
  installDevelopmentPlugin,
  marketplaceRoot,
  resolveClaudeConfigDir,
  resolveCodexHome,
  resolveNovaHome,
  restoreHostCaches,
  uninstallClaudeDevelopmentPlugin,
  uninstallDevelopmentPlugin,
  windowsCommandInvocation,
} from "../scripts/codex-dev-plugin-lib.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packageVersionPattern = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "package.json"), "utf8"),
).version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function createFakeCodex(root, initialState) {
  const stateFile = path.join(root, "codex-state.json");
  const driver = path.join(root, "fake-codex.mjs");
  fs.writeFileSync(stateFile, `${JSON.stringify(initialState)}\n`);
  fs.writeFileSync(
    driver,
    `import fs from "node:fs";
import path from "node:path";
const file = process.env.FAKE_CODEX_STATE;
const state = JSON.parse(fs.readFileSync(file, "utf8"));
const args = process.argv.slice(2);
const save = () => fs.writeFileSync(file, JSON.stringify(state));
if (args.join(" ") === "plugin list --json") {
  process.stdout.write(JSON.stringify({ installed: state.installed }));
} else if (args.join(" ") === "plugin marketplace list --json") {
  process.stdout.write(JSON.stringify({ marketplaces: state.marketplaces }));
} else if (args[0] === "plugin" && args[1] === "marketplace" && args[2] === "add") {
  const root = path.resolve(args[3]);
  const payload = JSON.parse(fs.readFileSync(path.join(root, ".agents", "plugins", "marketplace.json"), "utf8"));
  state.marketplaces = state.marketplaces.filter((item) => item.name !== payload.name);
  state.marketplaces.push({ name: payload.name, root, marketplaceSource: { sourceType: "local", source: root } });
  save();
} else if (args[0] === "plugin" && args[1] === "marketplace" && args[2] === "remove") {
  state.marketplaces = state.marketplaces.filter((item) => item.name !== args[3]);
  save();
} else if (args[0] === "plugin" && args[1] === "add") {
  if (state.failPluginAddRemaining > 0) {
    state.failPluginAddRemaining -= 1;
    save();
    process.stderr.write("injected plugin add failure");
    process.exit(23);
  }
  const [name, marketplaceName] = args[2].split("@");
  const marketplace = state.marketplaces.find((item) => item.name === marketplaceName);
  const pluginRoot = path.join(marketplace.root, "plugins", name);
  const manifest = JSON.parse(fs.readFileSync(path.join(pluginRoot, ".codex-plugin", "plugin.json"), "utf8"));
  state.installed = state.installed.filter((item) => item.pluginId !== args[2]);
  state.installed.push({ pluginId: args[2], name, marketplaceName, version: manifest.version, installed: true, enabled: true, source: { source: "local", path: pluginRoot }, marketplaceSource: { sourceType: "local", source: marketplace.root } });
  save();
} else if (args[0] === "plugin" && args[1] === "remove") {
  state.installed = state.installed.filter((item) => item.pluginId !== args[2]);
  save();
} else {
  process.stderr.write("unsupported fake Codex command: " + args.join(" "));
  process.exit(2);
}
`,
  );
  let executable;
  if (process.platform === "win32") {
    executable = path.join(root, "fake codex.cmd");
    fs.writeFileSync(executable, `@echo off\r\n"${process.execPath}" "${driver}" %*\r\n`);
  } else {
    executable = path.join(root, "fake-codex");
    fs.writeFileSync(executable, `#!/bin/sh\nexec "${process.execPath}" "${driver}" "$@"\n`);
    fs.chmodSync(executable, 0o755);
  }
  return { executable, stateFile };
}

function createFakeClaude(root) {
  const stateFile = path.join(root, "claude-state.json");
  const driver = path.join(root, "fake-claude.mjs");
  fs.writeFileSync(stateFile, JSON.stringify({ marketplaces: [], installed: [] }));
  fs.writeFileSync(
    driver,
    `import fs from "node:fs";
import path from "node:path";
const file = process.env.FAKE_CLAUDE_STATE;
const state = JSON.parse(fs.readFileSync(file, "utf8"));
const args = process.argv.slice(2);
const save = () => fs.writeFileSync(file, JSON.stringify(state));
if (args.join(" ") === "plugin list --json") {
  process.stdout.write(JSON.stringify(state.installed));
} else if (args.join(" ") === "plugin marketplace list --json") {
  process.stdout.write(JSON.stringify(state.marketplaces));
} else if (args[0] === "plugin" && args[1] === "marketplace" && args[2] === "add") {
  const root = path.resolve(args[3]);
  const payload = JSON.parse(fs.readFileSync(path.join(root, ".claude-plugin", "marketplace.json"), "utf8"));
  state.marketplaces = state.marketplaces.filter((item) => item.name !== payload.name);
  state.marketplaces.push({ name: payload.name, source: "directory", installLocation: root });
  save();
} else if (args[0] === "plugin" && args[1] === "marketplace" && args[2] === "remove") {
  state.marketplaces = state.marketplaces.filter((item) => item.name !== args[3]);
  save();
} else if (args[0] === "plugin" && (args[1] === "install" || args[1] === "update")) {
  const id = args[2];
  const [name, marketplaceName] = id.split("@");
  const marketplace = state.marketplaces.find((item) => item.name === marketplaceName);
  const pluginRoot = path.join(marketplace.installLocation, "plugins", name);
  const manifest = JSON.parse(fs.readFileSync(path.join(pluginRoot, ".claude-plugin", "plugin.json"), "utf8"));
  state.installed = state.installed.filter((item) => item.id !== id);
  state.installed.push({ id, version: manifest.version, enabled: true, errors: [] });
  save();
} else if (args[0] === "plugin" && args[1] === "uninstall") {
  state.installed = state.installed.filter((item) => item.id !== args[2]);
  save();
} else {
  process.stderr.write("unsupported fake Claude command: " + args.join(" "));
  process.exit(2);
}
`,
  );
  let executable;
  if (process.platform === "win32") {
    executable = path.join(root, "fake claude.cmd");
    fs.writeFileSync(executable, `@echo off\r\n"${process.execPath}" "${driver}" %*\r\n`);
  } else {
    executable = path.join(root, "fake-claude");
    fs.writeFileSync(executable, `#!/bin/sh\nexec "${process.execPath}" "${driver}" "$@"\n`);
    fs.chmodSync(executable, 0o755);
  }
  return { executable, stateFile };
}

test("development marketplace stays under the stable Nova home", () => {
  const home = path.join(path.parse(repoRoot).root, "users", "tester");
  assert.equal(resolveNovaHome({}, home), path.join(home, ".nova"));
  assert.equal(
    marketplaceRoot(path.join(home, ".nova")),
    path.join(home, ".nova", "marketplaces", DEV_MARKETPLACE_NAME),
  );
  assert.throws(
    () => resolveNovaHome({ NOVA_HOME: "relative/nova" }, home),
    /NOVA_HOME must be an absolute path/,
  );
  assert.throws(() => resolveNovaHome({ NOVA_HOME: "" }, home), /NOVA_HOME is set but empty/);
  assert.equal(resolveCodexHome({}, home), path.join(home, ".codex"));
  assert.equal(resolveClaudeConfigDir({}, home), path.join(home, ".claude"));
  assert.throws(
    () => resolveCodexHome({ CODEX_HOME: "relative/codex" }, home),
    /CODEX_HOME must be an absolute path/,
  );
  assert.throws(
    () => resolveClaudeConfigDir({ CLAUDE_CONFIG_DIR: "" }, home),
    /CLAUDE_CONFIG_DIR is set but empty/,
  );
});

test("development snapshot uses package contents, one hook manifest, and a fresh cachebuster", () => {
  const novaHome = fs.mkdtempSync(path.join(os.tmpdir(), "nova-dev-snapshot-"));
  try {
    const snapshot = buildSnapshot(
      repoRoot,
      novaHome,
      process.env,
      new Date("2026-09-11T12:34:56.000Z"),
    );
    const manifest = JSON.parse(
      fs.readFileSync(path.join(snapshot.pluginRoot, ".codex-plugin", "plugin.json"), "utf8"),
    );
    const claudeManifest = JSON.parse(
      fs.readFileSync(path.join(snapshot.pluginRoot, ".claude-plugin", "plugin.json"), "utf8"),
    );
    const codexMarketplace = JSON.parse(
      fs.readFileSync(
        path.join(snapshot.stageRoot, ".agents", "plugins", "marketplace.json"),
        "utf8",
      ),
    );
    const claudeMarketplace = JSON.parse(
      fs.readFileSync(
        path.join(snapshot.stageRoot, ".claude-plugin", "marketplace.json"),
        "utf8",
      ),
    );

    assert.match(
      manifest.version,
      new RegExp(
        `^${packageVersionPattern}\\+codex\\.local-20260911t123456000z-\\d+-[0-9a-f]{8}$`,
      ),
    );
    assert.match(
      claudeManifest.version,
      new RegExp(
        `^${packageVersionPattern}\\+claude\\.local-20260911t123456000z-\\d+-[0-9a-f]{8}$`,
      ),
    );
    assert.equal(snapshot.version, manifest.version);
    assert.equal(snapshot.codexVersion, manifest.version);
    assert.equal(snapshot.claudeVersion, claudeManifest.version);
    assert.match(snapshot.digest, /^[a-f0-9]{64}$/);
    assert.equal(fs.existsSync(path.join(snapshot.pluginRoot, "hooks", "hooks.json")), true);
    assert.equal(
      fs.existsSync(path.join(snapshot.pluginRoot, ".codex-plugin", "hooks.json")),
      false,
    );
    assert.equal(fs.existsSync(path.join(snapshot.pluginRoot, "tests")), false);
    assert.equal(fs.existsSync(path.join(snapshot.pluginRoot, ".nova")), false);
    assert.equal(codexMarketplace.name, DEV_MARKETPLACE_NAME);
    assert.deepEqual(codexMarketplace.plugins[0].source, {
      source: "local",
      path: "./plugins/nova-forge",
    });
    assert.equal(claudeMarketplace.name, DEV_MARKETPLACE_NAME);
    assert.equal(claudeMarketplace.metadata.version, claudeManifest.version);
    assert.equal(claudeMarketplace.plugins[0].source, "./plugins/nova-forge");
    assert.equal(claudeMarketplace.plugins[0].version, claudeManifest.version);
  } finally {
    fs.rmSync(novaHome, { recursive: true, force: true });
  }
});

test("host cache restore keeps old live-session paths beside the new version", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-dev-cache-"));
  const hostHome = path.join(root, "host");
  const novaHome = path.join(root, "nova");
  const oldRoot = path.join(
    hostHome,
    "plugins",
    "cache",
    DEV_MARKETPLACE_NAME,
    "nova-forge",
    "0.2.0-old",
  );
  const newRoot = path.join(
    hostHome,
    "plugins",
    "cache",
    DEV_MARKETPLACE_NAME,
    "nova-forge",
    "0.2.0-new",
  );
  try {
    fs.mkdirSync(path.join(oldRoot, "hooks"), { recursive: true });
    fs.writeFileSync(path.join(oldRoot, "hooks", "run.mjs"), "old hook\n");
    fs.mkdirSync(novaHome, { recursive: true });
    const snapshot = captureHostCaches(hostHome, novaHome);

    fs.rmSync(path.join(hostHome, "plugins", "cache"), { recursive: true, force: true });
    fs.mkdirSync(path.join(newRoot, "hooks"), { recursive: true });
    fs.writeFileSync(path.join(newRoot, "hooks", "run.mjs"), "new hook\n");

    assert.equal(restoreHostCaches(snapshot), 1);
    assert.equal(fs.readFileSync(path.join(oldRoot, "hooks", "run.mjs"), "utf8"), "old hook\n");
    assert.equal(fs.readFileSync(path.join(newRoot, "hooks", "run.mjs"), "utf8"), "new hook\n");
    assert.equal(fs.existsSync(snapshot.backupRoot), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("Windows command transport keeps paths and shell metacharacters out of command text", () => {
  const command = "C:\\Users\\Jane Doe\\bin & tools\\codex.cmd";
  const args = ["plugin", "marketplace", "add", "C:\\Users\\Jane Doe\\nova & ^ % root"];
  const invocation = windowsCommandInvocation(command, args, { BASE: "kept" }, "win32");
  assert.equal(invocation.command, "powershell.exe");
  assert.equal(invocation.args.includes(command), false);
  assert.equal(invocation.args.some((value) => value.includes("nova & ^ % root")), false);
  const spec = JSON.parse(
    Buffer.from(invocation.environment.NOVA_DEV_COMMAND_SPEC_BASE64, "base64").toString("utf8"),
  );
  assert.deepEqual(spec, { command, args });
  assert.equal(invocation.environment.BASE, "kept");
});

test("all development installers share one live cross-process lock", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-dev-lock-"));
  try {
    const novaHome = path.join(root, ".nova");
    const lockFile = path.join(novaHome, "marketplaces", ".nova-forge-dev.lock");
    fs.mkdirSync(path.dirname(lockFile), { recursive: true });
    fs.writeFileSync(lockFile, JSON.stringify({ pid: process.pid, token: "live-owner" }));
    assert.throws(
      () =>
        installDevelopmentPlugin({
          repoRoot,
          environment: { NOVA_HOME: novaHome },
          home: root,
          lockTimeoutMs: 20,
          output: { write() {} },
        }),
      { code: "DEVELOPMENT_INSTALL_LOCK_TIMEOUT" },
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("Codex development install verifies the snapshot and uninstall removes only development state", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-dev-cli-"));
  try {
    const novaHome = path.join(root, "nova home");
    const codexHome = path.join(root, "codex home");
    const fake = createFakeCodex(root, {
      marketplaces: [],
      installed: [],
      failPluginAddRemaining: 0,
    });
    const environment = {
      ...process.env,
      NOVA_HOME: novaHome,
      CODEX_HOME: codexHome,
      NOVA_CODEX_BIN: fake.executable,
      FAKE_CODEX_STATE: fake.stateFile,
    };
    const installed = installDevelopmentPlugin({
      repoRoot,
      environment,
      home: root,
      output: { write() {} },
    });
    const state = JSON.parse(fs.readFileSync(fake.stateFile, "utf8"));
    assert.equal(state.installed[0].version, installed.codexVersion);
    assert.equal(state.marketplaces[0].root, installed.targetRoot);
    assert.equal(state.installed[0].source.path, path.join(installed.targetRoot, "plugins", "nova-forge"));

    uninstallDevelopmentPlugin({ environment, home: root, output: { write() {} } });
    const removed = JSON.parse(fs.readFileSync(fake.stateFile, "utf8"));
    assert.deepEqual(removed.installed, []);
    assert.deepEqual(removed.marketplaces, []);
    assert.equal(fs.existsSync(installed.targetRoot), false);
    assert.equal(fs.existsSync(novaHome), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("Codex failed replacement restores an identically named marketplace at its original root", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-dev-rollback-"));
  try {
    const novaHome = path.join(root, "nova");
    const codexHome = path.join(root, "codex");
    const oldRoot = path.join(root, "old marketplace");
    const oldPluginRoot = path.join(oldRoot, "plugins", "nova-forge");
    fs.mkdirSync(path.join(oldRoot, ".agents", "plugins"), { recursive: true });
    fs.mkdirSync(path.join(oldPluginRoot, ".codex-plugin"), { recursive: true });
    fs.writeFileSync(
      path.join(oldRoot, ".agents", "plugins", "marketplace.json"),
      JSON.stringify({ name: DEV_MARKETPLACE_NAME }),
    );
    fs.writeFileSync(
      path.join(oldPluginRoot, ".codex-plugin", "plugin.json"),
      JSON.stringify({ name: "nova-forge", version: "0.1.9+old" }),
    );
    const priorPlugin = {
      pluginId: "nova-forge@nova-forge-dev",
      name: "nova-forge",
      marketplaceName: DEV_MARKETPLACE_NAME,
      version: "0.1.9+old",
      installed: true,
      enabled: true,
      source: { source: "local", path: oldPluginRoot },
      marketplaceSource: { sourceType: "local", source: oldRoot },
    };
    const fake = createFakeCodex(root, {
      marketplaces: [{ name: DEV_MARKETPLACE_NAME, root: oldRoot }],
      installed: [priorPlugin],
      failPluginAddRemaining: 1,
    });
    const environment = {
      ...process.env,
      NOVA_HOME: novaHome,
      CODEX_HOME: codexHome,
      NOVA_CODEX_BIN: fake.executable,
      FAKE_CODEX_STATE: fake.stateFile,
    };
    assert.throws(
      () =>
        installDevelopmentPlugin({
          repoRoot,
          environment,
          home: root,
          output: { write() {} },
        }),
      /injected plugin add failure/,
    );
    const restored = JSON.parse(fs.readFileSync(fake.stateFile, "utf8"));
    assert.equal(restored.marketplaces.length, 1);
    assert.equal(restored.marketplaces[0].root, oldRoot);
    assert.equal(restored.installed.length, 1);
    assert.equal(restored.installed[0].version, "0.1.9+old");
    assert.equal(restored.installed[0].source.path, oldPluginRoot);
    assert.equal(fs.existsSync(oldRoot), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("Claude Code development install and uninstall execute the full CLI transaction", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-dev-claude-cli-"));
  try {
    const novaHome = path.join(root, "nova home");
    const claudeHome = path.join(root, "claude home");
    const fake = createFakeClaude(root);
    const environment = {
      ...process.env,
      NOVA_HOME: novaHome,
      CLAUDE_CONFIG_DIR: claudeHome,
      NOVA_CLAUDE_BIN: fake.executable,
      FAKE_CLAUDE_STATE: fake.stateFile,
    };
    const installed = installClaudeDevelopmentPlugin({
      repoRoot,
      environment,
      home: root,
      output: { write() {} },
    });
    const state = JSON.parse(fs.readFileSync(fake.stateFile, "utf8"));
    assert.equal(state.installed.length, 1);
    assert.equal(state.installed[0].version, installed.claudeVersion);
    assert.equal(state.marketplaces[0].installLocation, installed.targetRoot);

    uninstallClaudeDevelopmentPlugin({ environment, home: root, output: { write() {} } });
    const removed = JSON.parse(fs.readFileSync(fake.stateFile, "utf8"));
    assert.deepEqual(removed.installed, []);
    assert.deepEqual(removed.marketplaces, []);
    assert.equal(fs.existsSync(installed.targetRoot), false);
    assert.equal(fs.existsSync(novaHome), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
