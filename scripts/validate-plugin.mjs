#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const skillNames = [
  "nova-requirements",
  "nova-architecture",
  "nova-development",
  "nova-doctor",
  "nova-review",
];

function readJson(relative) {
  return JSON.parse(fs.readFileSync(path.join(root, relative), "utf8"));
}

function requireValue(condition, message, errors) {
  if (!condition) errors.push(message);
}

const errors = [];
const packageJson = readJson("package.json");
const codex = readJson(".codex-plugin/plugin.json");
const claude = readJson(".claude-plugin/plugin.json");
const codexMarketplace = readJson(".agents/plugins/marketplace.json");
const claudeMarketplace = readJson(".claude-plugin/marketplace.json");
const hooks = readJson("hooks/hooks.json");

requireValue(packageJson.name === "nova-forge", "package name must be nova-forge", errors);
requireValue(/^\d+\.\d+\.\d+$/.test(packageJson.version), "package version must be stable SemVer", errors);
requireValue(packageJson.type === "module", "package type must be module", errors);
requireValue(packageJson.engines?.node === ">=22.5.0", "Node engine must be >=22.5.0", errors);
requireValue(!packageJson.dependencies, "runtime dependencies are forbidden", errors);
requireValue(!packageJson.devDependencies, "development dependencies are forbidden", errors);

for (const [label, manifest, host] of [
  ["Codex", codex, "codex"],
  ["Claude Code", claude, "claude-code"],
]) {
  requireValue(manifest.name === packageJson.name, `${label} manifest name mismatch`, errors);
  requireValue(manifest.version === packageJson.version, `${label} manifest version mismatch`, errors);
  requireValue(manifest.skills === "./skills/", `${label} skills path mismatch`, errors);
  const server = manifest.mcpServers?.["nova-checkpoint"];
  requireValue(server?.command === "node", `${label} MCP command must use node`, errors);
  requireValue(server?.args?.includes(host), `${label} MCP host binding mismatch`, errors);
  requireValue(!Object.hasOwn(manifest, "hooks"), `${label} manifest must use default hooks/hooks.json discovery`, errors);
}

requireValue(
  codexMarketplace.plugins?.[0]?.source?.ref === `v${packageJson.version}`,
  "Codex marketplace ref mismatch",
  errors,
);
requireValue(
  claudeMarketplace.metadata?.version === packageJson.version &&
    claudeMarketplace.plugins?.[0]?.version === packageJson.version &&
    claudeMarketplace.plugins?.[0]?.source?.ref === `v${packageJson.version}`,
  "Claude Code marketplace version mismatch",
  errors,
);

const expectedEvents = [
  "SessionStart",
  "UserPromptSubmit",
  "PostToolUse",
  "Stop",
  "PreCompact",
  "PostCompact",
];
requireValue(
  JSON.stringify(Object.keys(hooks.hooks || {}).sort()) === JSON.stringify(expectedEvents.sort()),
  "hook event set mismatch",
  errors,
);

for (const name of skillNames) {
  const skillFile = path.join(root, "skills", name, "SKILL.md");
  requireValue(fs.existsSync(skillFile), `missing skill ${name}`, errors);
  if (fs.existsSync(skillFile)) {
    const text = fs.readFileSync(skillFile, "utf8");
    requireValue(new RegExp(`^name:\\s*["']?${name}["']?\\s*$`, "m").test(text), `skill name mismatch ${name}`, errors);
  }
}

for (const relative of [
  "codex/AGENTS.global.md",
  "hooks/run.mjs",
  "runtime/adapters/hook.mjs",
  "runtime/core/schema.mjs",
  "runtime/core/storage.mjs",
  "runtime/core/rendezvous.mjs",
  "runtime/mcp/server.mjs",
]) {
  requireValue(fs.existsSync(path.join(root, relative)), `missing plugin component ${relative}`, errors);
}

if (errors.length) {
  errors.forEach((error) => process.stderr.write(`ERROR: ${error}\n`));
  process.exitCode = 1;
} else {
  process.stdout.write("PASS: dual-host plugin structure\n");
}
