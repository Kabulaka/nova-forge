import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const DEV_MARKETPLACE_NAME = "nova-forge-dev";
export const PLUGIN_NAME = "nova-forge";
export const DEV_PLUGIN_ID = `${PLUGIN_NAME}@${DEV_MARKETPLACE_NAME}`;
export const HOST_CODEX = "codex";
export const HOST_CLAUDE_CODE = "claude-code";
export const SUPPORTED_HOSTS = [HOST_CODEX, HOST_CLAUDE_CODE];

function executable(name, override) {
  if (override) return override;
  if (process.platform === "win32") return `${name}.cmd`;
  return name;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    encoding: "utf8",
    env: options.env || process.env,
    maxBuffer: 16 * 1024 * 1024,
    shell: process.platform === "win32",
    windowsHide: true,
  });
  if (result.error) {
    throw new Error(`cannot run ${command}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "no diagnostic output").trim();
    throw new Error(`${command} ${args.join(" ")} failed (${result.status}): ${detail}`);
  }
  return result.stdout;
}

function parseJsonOutput(label, output) {
  try {
    return JSON.parse(output);
  } catch (error) {
    throw new Error(`${label} returned invalid JSON: ${error.message}`);
  }
}

export function resolveNovaHome(environment = process.env, home = os.homedir()) {
  if (Object.hasOwn(environment, "NOVA_HOME")) {
    const configured = environment.NOVA_HOME;
    if (typeof configured !== "string" || configured.trim() === "") {
      throw new Error("NOVA_HOME is set but empty");
    }
    if (!path.isAbsolute(configured)) {
      throw new Error(`NOVA_HOME must be an absolute path: ${configured}`);
    }
    return path.resolve(configured);
  }
  if (!home) throw new Error("cannot determine the current user home directory");
  return path.resolve(home, ".nova");
}

export function marketplaceRoot(novaHome) {
  return path.join(novaHome, "marketplaces", DEV_MARKETPLACE_NAME);
}

function resolveHostHome(environment, variable, home, fallback) {
  if (Object.hasOwn(environment, variable)) {
    const configured = environment[variable];
    if (typeof configured !== "string" || configured.trim() === "") {
      throw new Error(`${variable} is set but empty`);
    }
    if (!path.isAbsolute(configured)) {
      throw new Error(`${variable} must be an absolute path: ${configured}`);
    }
    return path.resolve(configured);
  }
  if (!home) throw new Error("cannot determine the current user home directory");
  return path.resolve(home, fallback);
}

export function resolveCodexHome(environment = process.env, home = os.homedir()) {
  return resolveHostHome(environment, "CODEX_HOME", home, ".codex");
}

export function resolveClaudeConfigDir(environment = process.env, home = os.homedir()) {
  return resolveHostHome(environment, "CLAUDE_CONFIG_DIR", home, ".claude");
}

export function listInstalledPlugins(codexBin, environment = process.env) {
  const payload = parseJsonOutput(
    "codex plugin list --json",
    run(codexBin, ["plugin", "list", "--json"], { env: environment }),
  );
  if (!Array.isArray(payload.installed)) {
    throw new Error("codex plugin list --json did not return an installed array");
  }
  return payload.installed;
}

export function listMarketplaces(codexBin, environment = process.env) {
  const payload = parseJsonOutput(
    "codex plugin marketplace list --json",
    run(codexBin, ["plugin", "marketplace", "list", "--json"], { env: environment }),
  );
  if (!Array.isArray(payload.marketplaces)) {
    throw new Error("codex plugin marketplace list --json did not return a marketplaces array");
  }
  return payload.marketplaces;
}

export function listClaudeInstalledPlugins(claudeBin, environment = process.env) {
  const payload = parseJsonOutput(
    "claude plugin list --json",
    run(claudeBin, ["plugin", "list", "--json"], { env: environment }),
  );
  if (!Array.isArray(payload)) {
    throw new Error("claude plugin list --json did not return an array");
  }
  return payload;
}

export function listClaudeMarketplaces(claudeBin, environment = process.env) {
  const payload = parseJsonOutput(
    "claude plugin marketplace list --json",
    run(claudeBin, ["plugin", "marketplace", "list", "--json"], { env: environment }),
  );
  if (!Array.isArray(payload)) {
    throw new Error("claude plugin marketplace list --json did not return an array");
  }
  return payload;
}

export function packageFiles(repoRoot, environment = process.env) {
  const npmBin = executable("npm", environment.NOVA_NPM_BIN);
  const payload = parseJsonOutput(
    "npm pack --dry-run --json",
    run(npmBin, ["pack", "--dry-run", "--json", "--ignore-scripts"], {
      cwd: repoRoot,
      env: environment,
    }),
  );
  const files = payload?.[0]?.files;
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error("npm pack --dry-run returned no package files");
  }
  return files.map((entry) => entry.path);
}

function safeRelativePath(relative) {
  const normalized = path.normalize(relative);
  if (
    !relative ||
    path.isAbsolute(relative) ||
    normalized === ".." ||
    normalized.startsWith(`..${path.sep}`)
  ) {
    throw new Error(`unsafe package path: ${relative}`);
  }
  return normalized;
}

function copyPackageFile(repoRoot, pluginRoot, relative) {
  const safe = safeRelativePath(relative);
  const source = path.join(repoRoot, safe);
  const target = path.join(pluginRoot, safe);
  const stat = fs.lstatSync(source);
  if (!stat.isFile()) {
    throw new Error(`package entry is not a regular file: ${relative}`);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
  fs.chmodSync(target, stat.mode & 0o777);
}

function cachebuster(now = new Date()) {
  const digits = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  return `local-${digits.toLowerCase()}`;
}

function updateManifestVersion(pluginRoot, manifestDirectory, hostLabel, now) {
  const manifestPath = path.join(pluginRoot, manifestDirectory, "plugin.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (manifest.name !== PLUGIN_NAME || typeof manifest.version !== "string") {
    throw new Error(`invalid ${hostLabel} plugin manifest: ${manifestPath}`);
  }
  const baseVersion = manifest.version.split("+", 1)[0];
  manifest.version = `${baseVersion}+${hostLabel}.${cachebuster(now)}`;
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return manifest.version;
}

function writeCodexMarketplace(stageRoot) {
  const marketplacePath = path.join(stageRoot, ".agents", "plugins", "marketplace.json");
  const payload = {
    name: DEV_MARKETPLACE_NAME,
    interface: { displayName: "Nova Forge (Local Development)" },
    plugins: [
      {
        name: PLUGIN_NAME,
        source: { source: "local", path: `./plugins/${PLUGIN_NAME}` },
        policy: { installation: "AVAILABLE", authentication: "ON_INSTALL" },
        category: "Productivity",
      },
    ],
  };
  fs.mkdirSync(path.dirname(marketplacePath), { recursive: true });
  fs.writeFileSync(marketplacePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function writeClaudeMarketplace(stageRoot, version) {
  const marketplacePath = path.join(stageRoot, ".claude-plugin", "marketplace.json");
  const payload = {
    name: DEV_MARKETPLACE_NAME,
    owner: { name: "Nova Forge contributors" },
    metadata: {
      description: "Local Nova Forge development snapshot",
      version,
    },
    plugins: [
      {
        name: PLUGIN_NAME,
        source: `./plugins/${PLUGIN_NAME}`,
        description: "Nova workflows with authority-safe checkpoint recovery.",
        version,
        category: "development",
      },
    ],
  };
  fs.mkdirSync(path.dirname(marketplacePath), { recursive: true });
  fs.writeFileSync(marketplacePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function validateSnapshot(pluginRoot) {
  const required = [
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "hooks/hooks.json",
    "hooks/run.mjs",
    "runtime/mcp/server.mjs",
    "skills/nova-requirements/SKILL.md",
    "skills/nova-architecture/SKILL.md",
    "skills/nova-development/SKILL.md",
    "skills/nova-doctor/SKILL.md",
    "skills/nova-review/SKILL.md",
  ];
  const missing = required.filter((relative) => !fs.existsSync(path.join(pluginRoot, relative)));
  if (missing.length) throw new Error(`development snapshot is missing: ${missing.join(", ")}`);
  const duplicateHook = path.join(pluginRoot, ".codex-plugin", "hooks.json");
  if (fs.existsSync(duplicateHook)) {
    throw new Error("development snapshot contains forbidden duplicate .codex-plugin/hooks.json");
  }
  const codexManifest = JSON.parse(
    fs.readFileSync(path.join(pluginRoot, ".codex-plugin", "plugin.json"), "utf8"),
  );
  const claudeManifest = JSON.parse(
    fs.readFileSync(path.join(pluginRoot, ".claude-plugin", "plugin.json"), "utf8"),
  );
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\+codex\.local-[0-9tz-]+$/.test(codexManifest.version)) {
    throw new Error(
      `Codex development manifest has an invalid cachebuster version: ${codexManifest.version}`,
    );
  }
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\+claude\.local-[0-9tz-]+$/.test(claudeManifest.version)) {
    throw new Error(
      `Claude development manifest has an invalid cachebuster version: ${claudeManifest.version}`,
    );
  }
}

function snapshotDigest(pluginRoot, files) {
  const hash = crypto.createHash("sha256");
  for (const relative of [...files, ".codex-plugin/plugin.json"].sort()) {
    const safe = safeRelativePath(relative);
    const file = path.join(pluginRoot, safe);
    if (!fs.existsSync(file)) continue;
    hash.update(relative);
    hash.update("\0");
    hash.update(fs.readFileSync(file));
    hash.update("\0");
  }
  return hash.digest("hex");
}

export function buildSnapshot(repoRoot, novaHome, environment = process.env, now = new Date()) {
  const parent = path.join(novaHome, "marketplaces");
  fs.mkdirSync(parent, { recursive: true, mode: 0o700 });
  const stageRoot = fs.mkdtempSync(path.join(parent, `.${DEV_MARKETPLACE_NAME}-`));
  const pluginRoot = path.join(stageRoot, "plugins", PLUGIN_NAME);
  try {
    const files = packageFiles(repoRoot, environment);
    for (const relative of files) copyPackageFile(repoRoot, pluginRoot, relative);
    const codexVersion = updateManifestVersion(pluginRoot, ".codex-plugin", "codex", now);
    const claudeVersion = updateManifestVersion(pluginRoot, ".claude-plugin", "claude", now);
    writeCodexMarketplace(stageRoot);
    writeClaudeMarketplace(stageRoot, claudeVersion);
    validateSnapshot(pluginRoot);
    return {
      stageRoot,
      pluginRoot,
      version: codexVersion,
      codexVersion,
      claudeVersion,
      digest: snapshotDigest(pluginRoot, files),
    };
  } catch (error) {
    fs.rmSync(stageRoot, { recursive: true, force: true });
    throw error;
  }
}

function removePlugin(codexBin, pluginId, environment) {
  run(codexBin, ["plugin", "remove", pluginId], { env: environment });
}

function removeMarketplace(codexBin, name, environment) {
  run(codexBin, ["plugin", "marketplace", "remove", name], { env: environment });
}

function addMarketplace(codexBin, root, environment) {
  run(codexBin, ["plugin", "marketplace", "add", root], { env: environment });
}

function addPlugin(codexBin, pluginId, environment) {
  run(codexBin, ["plugin", "add", pluginId], { env: environment });
}

function removeClaudePlugin(claudeBin, pluginId, environment) {
  run(
    claudeBin,
    ["plugin", "uninstall", pluginId, "--scope", "user", "--keep-data"],
    { env: environment },
  );
}

function addClaudeMarketplace(claudeBin, root, environment) {
  run(claudeBin, ["plugin", "marketplace", "add", root, "--scope", "user"], {
    env: environment,
  });
}

function removeClaudeMarketplace(claudeBin, name, environment) {
  run(claudeBin, ["plugin", "marketplace", "remove", name], { env: environment });
}

function installClaudePlugin(claudeBin, environment) {
  run(claudeBin, ["plugin", "install", DEV_PLUGIN_ID, "--scope", "user"], {
    env: environment,
  });
}

function updateClaudePlugin(claudeBin, environment) {
  run(claudeBin, ["plugin", "update", DEV_PLUGIN_ID], { env: environment });
}

function hostCacheRoot(hostHome) {
  return path.join(hostHome, "plugins", "cache");
}

function cacheDirectoriesForPlugin(hostHome) {
  const root = hostCacheRoot(hostHome);
  if (!fs.existsSync(root)) return [];
  const directories = [];
  for (const marketplace of fs.readdirSync(root, { withFileTypes: true })) {
    if (!marketplace.isDirectory() || marketplace.isSymbolicLink()) continue;
    const pluginRoot = path.join(root, marketplace.name, PLUGIN_NAME);
    let versions;
    try {
      if (fs.lstatSync(pluginRoot).isSymbolicLink()) continue;
      versions = fs.readdirSync(pluginRoot, { withFileTypes: true });
    } catch (error) {
      if (error?.code === "ENOENT" || error?.code === "ENOTDIR") continue;
      throw error;
    }
    for (const version of versions) {
      if (!version.isDirectory() || version.isSymbolicLink()) continue;
      directories.push({
        relative: path.join(marketplace.name, PLUGIN_NAME, version.name),
        source: path.join(pluginRoot, version.name),
      });
    }
  }
  return directories;
}

export function captureHostCaches(hostHome, novaHome) {
  const directories = cacheDirectoriesForPlugin(hostHome);
  if (directories.length === 0) return { hostHome, backupRoot: null, entries: [] };
  const backupRoot = fs.mkdtempSync(path.join(novaHome, ".host-cache-backup-"));
  try {
    for (const entry of directories) {
      const backup = path.join(backupRoot, entry.relative);
      fs.mkdirSync(path.dirname(backup), { recursive: true });
      fs.cpSync(entry.source, backup, { recursive: true, dereference: false });
    }
    return { hostHome, backupRoot, entries: directories.map((entry) => entry.relative) };
  } catch (error) {
    fs.rmSync(backupRoot, { recursive: true, force: true });
    throw error;
  }
}

export function restoreHostCaches(snapshot) {
  if (!snapshot.backupRoot) return 0;
  let restored = 0;
  let completed = false;
  try {
    for (const relative of snapshot.entries) {
      const source = path.join(snapshot.backupRoot, relative);
      const target = path.join(hostCacheRoot(snapshot.hostHome), relative);
      if (fs.existsSync(target)) continue;
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.cpSync(source, target, { recursive: true, dereference: false });
      restored += 1;
    }
    completed = true;
    return restored;
  } finally {
    if (completed) fs.rmSync(snapshot.backupRoot, { recursive: true, force: true });
  }
}

function safeRemoveDevelopmentRoot(root, novaHome) {
  const expected = path.resolve(marketplaceRoot(novaHome));
  const actual = path.resolve(root);
  if (actual !== expected || path.basename(actual) !== DEV_MARKETPLACE_NAME) {
    throw new Error(`refusing to remove unexpected development marketplace path: ${actual}`);
  }
  fs.rmSync(actual, { recursive: true, force: true });
}

export function installDevelopmentPlugin({
  repoRoot,
  environment = process.env,
  home = os.homedir(),
  dryRun = false,
  now = new Date(),
  output = process.stdout,
}) {
  const codexBin = executable("codex", environment.NOVA_CODEX_BIN);
  const novaHome = resolveNovaHome(environment, home);
  const codexHome = resolveCodexHome(environment, home);
  const targetRoot = marketplaceRoot(novaHome);
  const installed = listInstalledPlugins(codexBin, environment);
  const novaPlugins = installed.filter((plugin) => plugin.name === PLUGIN_NAME && plugin.installed);
  const marketplaces = listMarketplaces(codexBin, environment);
  const priorDevMarketplace = marketplaces.find((item) => item.name === DEV_MARKETPLACE_NAME);

  output.write(`Source: ${repoRoot}\n`);
  output.write(`Development marketplace: ${targetRoot}\n`);
  for (const plugin of novaPlugins) output.write(`Will uninstall conflict: ${plugin.pluginId}\n`);
  if (priorDevMarketplace) output.write(`Will replace marketplace: ${DEV_MARKETPLACE_NAME}\n`);
  if (dryRun) {
    output.write("DRY-RUN: no plugin, marketplace, or Nova state was changed.\n");
    return { dryRun: true, targetRoot, conflicts: novaPlugins.map((plugin) => plugin.pluginId) };
  }

  const snapshot = buildSnapshot(repoRoot, novaHome, environment, now);
  const cacheSnapshot = captureHostCaches(codexHome, novaHome);
  let backupRoot;
  const removedPluginIds = [];
  let removedDevMarketplace = false;
  try {
    for (const plugin of novaPlugins) {
      removePlugin(codexBin, plugin.pluginId, environment);
      removedPluginIds.push(plugin.pluginId);
    }
    if (priorDevMarketplace) {
      removeMarketplace(codexBin, DEV_MARKETPLACE_NAME, environment);
      removedDevMarketplace = true;
    }
    if (fs.existsSync(targetRoot)) {
      backupRoot = `${targetRoot}.backup-${process.pid}-${Date.now()}`;
      fs.renameSync(targetRoot, backupRoot);
    }
    fs.renameSync(snapshot.stageRoot, targetRoot);
    addMarketplace(codexBin, targetRoot, environment);
    addPlugin(codexBin, DEV_PLUGIN_ID, environment);

    const after = listInstalledPlugins(codexBin, environment).filter(
      (plugin) => plugin.name === PLUGIN_NAME && plugin.installed,
    );
    if (after.length !== 1 || after[0].pluginId !== DEV_PLUGIN_ID || !after[0].enabled) {
      throw new Error(`expected one enabled ${DEV_PLUGIN_ID}, found ${JSON.stringify(after)}`);
    }
    const restoredCacheVersions = restoreHostCaches(cacheSnapshot);
    if (backupRoot) fs.rmSync(backupRoot, { recursive: true, force: true });
    output.write(`Installed: ${DEV_PLUGIN_ID} ${snapshot.version}\n`);
    output.write(`Snapshot SHA-256: ${snapshot.digest}\n`);
    output.write(`Nova state preserved at: ${novaHome}\n`);
    output.write(`Retained old Codex cache versions for live sessions: ${restoredCacheVersions}\n`);
    output.write("Existing sessions remain executable; start a new session to load the new snapshot.\n");
    return { ...snapshot, targetRoot, removedPluginIds, restoredCacheVersions };
  } catch (error) {
    try {
      const current = listInstalledPlugins(codexBin, environment);
      if (current.some((plugin) => plugin.pluginId === DEV_PLUGIN_ID && plugin.installed)) {
        removePlugin(codexBin, DEV_PLUGIN_ID, environment);
      }
    } catch {}
    try {
      const current = listMarketplaces(codexBin, environment);
      if (current.some((item) => item.name === DEV_MARKETPLACE_NAME)) {
        removeMarketplace(codexBin, DEV_MARKETPLACE_NAME, environment);
      }
    } catch {}
    if (fs.existsSync(targetRoot)) safeRemoveDevelopmentRoot(targetRoot, novaHome);
    if (backupRoot && fs.existsSync(backupRoot)) fs.renameSync(backupRoot, targetRoot);
    if (fs.existsSync(snapshot.stageRoot)) {
      fs.rmSync(snapshot.stageRoot, { recursive: true, force: true });
    }
    if (removedDevMarketplace && fs.existsSync(targetRoot)) {
      try {
        addMarketplace(codexBin, targetRoot, environment);
      } catch {}
    }
    for (const pluginId of removedPluginIds) {
      try {
        addPlugin(codexBin, pluginId, environment);
      } catch {}
    }
    try {
      restoreHostCaches(cacheSnapshot);
    } catch (cacheError) {
      throw new AggregateError(
        [error, cacheError],
        "Codex development install failed and its live-session cache could not be restored",
      );
    }
    throw error;
  }
}

export function uninstallDevelopmentPlugin({
  environment = process.env,
  home = os.homedir(),
  dryRun = false,
  preserveSnapshot = false,
  output = process.stdout,
}) {
  const codexBin = executable("codex", environment.NOVA_CODEX_BIN);
  const novaHome = resolveNovaHome(environment, home);
  const codexHome = resolveCodexHome(environment, home);
  const targetRoot = marketplaceRoot(novaHome);
  const installed = listInstalledPlugins(codexBin, environment);
  const hasPlugin = installed.some(
    (plugin) => plugin.pluginId === DEV_PLUGIN_ID && plugin.installed,
  );
  const marketplaces = listMarketplaces(codexBin, environment);
  const hasMarketplace = marketplaces.some((item) => item.name === DEV_MARKETPLACE_NAME);

  output.write(`${hasPlugin ? "Will uninstall" : "Not installed"}: ${DEV_PLUGIN_ID}\n`);
  output.write(`${hasMarketplace ? "Will remove" : "Not configured"}: ${DEV_MARKETPLACE_NAME}\n`);
  output.write(`${preserveSnapshot ? "Will preserve shared" : "Will remove development"} snapshot: ${targetRoot}\n`);
  output.write(`Will preserve Nova state: ${novaHome}\n`);
  if (dryRun) {
    output.write("DRY-RUN: no plugin, marketplace, or Nova state was changed.\n");
    return { dryRun: true, targetRoot, hasPlugin, hasMarketplace };
  }

  const cacheSnapshot = captureHostCaches(codexHome, novaHome);
  let restoredCacheVersions;
  try {
    if (hasPlugin) removePlugin(codexBin, DEV_PLUGIN_ID, environment);
    if (hasMarketplace) removeMarketplace(codexBin, DEV_MARKETPLACE_NAME, environment);
    if (!preserveSnapshot && fs.existsSync(targetRoot)) {
      safeRemoveDevelopmentRoot(targetRoot, novaHome);
    }
  } finally {
    restoredCacheVersions = restoreHostCaches(cacheSnapshot);
  }

  const pluginStillInstalled = listInstalledPlugins(codexBin, environment).some(
    (plugin) => plugin.pluginId === DEV_PLUGIN_ID && plugin.installed,
  );
  const marketplaceStillConfigured = listMarketplaces(codexBin, environment).some(
    (item) => item.name === DEV_MARKETPLACE_NAME,
  );
  if (pluginStillInstalled || marketplaceStillConfigured) {
    throw new Error("Codex still reports the development plugin or marketplace after uninstall");
  }
  output.write(`Uninstalled: ${DEV_PLUGIN_ID}\n`);
  output.write(`Nova state preserved at: ${novaHome}\n`);
  output.write(`Retained old Codex cache versions for live sessions: ${restoredCacheVersions}\n`);
  return { targetRoot, removed: true, restoredCacheVersions };
}

export function installClaudeDevelopmentPlugin({
  repoRoot,
  environment = process.env,
  home = os.homedir(),
  dryRun = false,
  now = new Date(),
  output = process.stdout,
}) {
  const claudeBin = executable("claude", environment.NOVA_CLAUDE_BIN);
  const novaHome = resolveNovaHome(environment, home);
  const claudeHome = resolveClaudeConfigDir(environment, home);
  const targetRoot = marketplaceRoot(novaHome);
  const installed = listClaudeInstalledPlugins(claudeBin, environment);
  const novaPlugins = installed.filter((plugin) => plugin.id?.startsWith(`${PLUGIN_NAME}@`));
  const marketplaces = listClaudeMarketplaces(claudeBin, environment);
  const priorDevMarketplace = marketplaces.find((item) => item.name === DEV_MARKETPLACE_NAME);
  if (
    priorDevMarketplace &&
    path.resolve(priorDevMarketplace.installLocation || priorDevMarketplace.path || "") !==
      path.resolve(targetRoot)
  ) {
    throw new Error(
      `Claude marketplace ${DEV_MARKETPLACE_NAME} points outside the Nova development root`,
    );
  }

  output.write(`Source: ${repoRoot}\n`);
  output.write(`Claude development marketplace: ${targetRoot}\n`);
  for (const plugin of novaPlugins) output.write(`Will replace Claude plugin: ${plugin.id}\n`);
  if (dryRun) {
    output.write("DRY-RUN: no Claude plugin, marketplace, or Nova state was changed.\n");
    return { dryRun: true, targetRoot, conflicts: novaPlugins.map((plugin) => plugin.id) };
  }

  const snapshot = buildSnapshot(repoRoot, novaHome, environment, now);
  const cacheSnapshot = captureHostCaches(claudeHome, novaHome);
  let backupRoot;
  const removedPluginIds = [];
  let addedMarketplace = false;
  try {
    if (fs.existsSync(targetRoot)) {
      backupRoot = `${targetRoot}.backup-${process.pid}-${Date.now()}`;
      fs.renameSync(targetRoot, backupRoot);
    }
    fs.renameSync(snapshot.stageRoot, targetRoot);
    if (!priorDevMarketplace) {
      addClaudeMarketplace(claudeBin, targetRoot, environment);
      addedMarketplace = true;
    }
    const priorDevPlugin = novaPlugins.find((plugin) => plugin.id === DEV_PLUGIN_ID);
    if (priorDevPlugin) updateClaudePlugin(claudeBin, environment);
    else installClaudePlugin(claudeBin, environment);

    for (const plugin of novaPlugins) {
      if (plugin.id === DEV_PLUGIN_ID) continue;
      removeClaudePlugin(claudeBin, plugin.id, environment);
      removedPluginIds.push(plugin.id);
    }

    const after = listClaudeInstalledPlugins(claudeBin, environment).filter((plugin) =>
      plugin.id?.startsWith(`${PLUGIN_NAME}@`),
    );
    if (
      after.length !== 1 ||
      after[0].id !== DEV_PLUGIN_ID ||
      !after[0].enabled ||
      after[0].version !== snapshot.claudeVersion ||
      (after[0].errors && after[0].errors.length > 0)
    ) {
      throw new Error(`expected one healthy enabled ${DEV_PLUGIN_ID}, found ${JSON.stringify(after)}`);
    }

    for (const marketplace of marketplaces) {
      const brokenLocalNovaMarketplace =
        marketplace.name !== DEV_MARKETPLACE_NAME &&
        marketplace.name.startsWith(`${PLUGIN_NAME}-`) &&
        marketplace.source === "directory" &&
        (!marketplace.installLocation || !fs.existsSync(marketplace.installLocation));
      if (brokenLocalNovaMarketplace) {
        removeClaudeMarketplace(claudeBin, marketplace.name, environment);
      }
    }

    const restoredCacheVersions = restoreHostCaches(cacheSnapshot);
    if (backupRoot) fs.rmSync(backupRoot, { recursive: true, force: true });
    output.write(`Installed for Claude Code: ${DEV_PLUGIN_ID} ${snapshot.claudeVersion}\n`);
    output.write(`Snapshot SHA-256: ${snapshot.digest}\n`);
    output.write(`Nova state preserved at: ${novaHome}\n`);
    output.write(`Retained old Claude cache versions for live sessions: ${restoredCacheVersions}\n`);
    output.write("Existing sessions remain executable; start a new session to load the new snapshot.\n");
    return { ...snapshot, targetRoot, removedPluginIds, restoredCacheVersions };
  } catch (error) {
    const priorDevPlugin = novaPlugins.find((plugin) => plugin.id === DEV_PLUGIN_ID);
    try {
      const current = listClaudeInstalledPlugins(claudeBin, environment);
      if (current.some((plugin) => plugin.id === DEV_PLUGIN_ID)) {
        removeClaudePlugin(claudeBin, DEV_PLUGIN_ID, environment);
      }
    } catch {}
    if (addedMarketplace) {
      try {
        removeClaudeMarketplace(claudeBin, DEV_MARKETPLACE_NAME, environment);
      } catch {}
    }
    if (fs.existsSync(targetRoot)) safeRemoveDevelopmentRoot(targetRoot, novaHome);
    if (backupRoot && fs.existsSync(backupRoot)) fs.renameSync(backupRoot, targetRoot);
    if (fs.existsSync(snapshot.stageRoot)) {
      fs.rmSync(snapshot.stageRoot, { recursive: true, force: true });
    }
    if (priorDevPlugin) {
      try {
        installClaudePlugin(claudeBin, environment);
      } catch {}
    }
    for (const pluginId of removedPluginIds) {
      try {
        run(claudeBin, ["plugin", "install", pluginId, "--scope", "user"], {
          env: environment,
        });
      } catch {}
    }
    try {
      restoreHostCaches(cacheSnapshot);
    } catch (cacheError) {
      throw new AggregateError(
        [error, cacheError],
        "Claude development install failed and its live-session cache could not be restored",
      );
    }
    throw error;
  }
}

export function uninstallClaudeDevelopmentPlugin({
  environment = process.env,
  home = os.homedir(),
  dryRun = false,
  preserveSnapshot = false,
  output = process.stdout,
}) {
  const claudeBin = executable("claude", environment.NOVA_CLAUDE_BIN);
  const novaHome = resolveNovaHome(environment, home);
  const claudeHome = resolveClaudeConfigDir(environment, home);
  const targetRoot = marketplaceRoot(novaHome);
  const installed = listClaudeInstalledPlugins(claudeBin, environment);
  const hasPlugin = installed.some((plugin) => plugin.id === DEV_PLUGIN_ID);
  const marketplaces = listClaudeMarketplaces(claudeBin, environment);
  const hasMarketplace = marketplaces.some((item) => item.name === DEV_MARKETPLACE_NAME);

  output.write(`${hasPlugin ? "Will uninstall" : "Not installed"}: ${DEV_PLUGIN_ID}\n`);
  output.write(`${hasMarketplace ? "Will remove" : "Not configured"}: ${DEV_MARKETPLACE_NAME}\n`);
  output.write(`${preserveSnapshot ? "Will preserve shared" : "Will remove"} snapshot: ${targetRoot}\n`);
  output.write(`Will preserve Nova state: ${novaHome}\n`);
  if (dryRun) {
    output.write("DRY-RUN: no Claude plugin, marketplace, or Nova state was changed.\n");
    return { dryRun: true, targetRoot, hasPlugin, hasMarketplace };
  }

  const cacheSnapshot = captureHostCaches(claudeHome, novaHome);
  let restoredCacheVersions;
  try {
    if (hasPlugin) removeClaudePlugin(claudeBin, DEV_PLUGIN_ID, environment);
    if (hasMarketplace) removeClaudeMarketplace(claudeBin, DEV_MARKETPLACE_NAME, environment);
    if (!preserveSnapshot && fs.existsSync(targetRoot)) {
      safeRemoveDevelopmentRoot(targetRoot, novaHome);
    }
  } finally {
    restoredCacheVersions = restoreHostCaches(cacheSnapshot);
  }

  const pluginStillInstalled = listClaudeInstalledPlugins(claudeBin, environment).some(
    (plugin) => plugin.id === DEV_PLUGIN_ID,
  );
  const marketplaceStillConfigured = listClaudeMarketplaces(claudeBin, environment).some(
    (item) => item.name === DEV_MARKETPLACE_NAME,
  );
  if (pluginStillInstalled || marketplaceStillConfigured) {
    throw new Error("Claude still reports the development plugin or marketplace after uninstall");
  }
  output.write(`Uninstalled from Claude Code: ${DEV_PLUGIN_ID}\n`);
  output.write(`Nova state preserved at: ${novaHome}\n`);
  output.write(`Retained old Claude cache versions for live sessions: ${restoredCacheVersions}\n`);
  return { targetRoot, removed: true, restoredCacheVersions };
}
