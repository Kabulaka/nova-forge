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
  marketplaceRoot,
  resolveClaudeConfigDir,
  resolveCodexHome,
  resolveNovaHome,
  restoreHostCaches,
} from "../scripts/codex-dev-plugin-lib.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

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

    assert.equal(manifest.version, "0.2.0+codex.local-20260911t123456z");
    assert.equal(claudeManifest.version, "0.2.0+claude.local-20260911t123456z");
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
