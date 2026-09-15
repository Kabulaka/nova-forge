#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const skills = ["nova-architecture", "nova-development", "nova-review", "nova-commit"];
const removed = ["nova-requirements", "nova-doctor"];
const removedReferences = [
  "skills/nova-architecture/references/architecture-standard.md",
  "skills/nova-development/references/implementation-sop.md",
  "skills/nova-review/references/review-sop.md",
];
const errors = [];

const readJson = (relative) =>
  JSON.parse(fs.readFileSync(path.join(root, relative), "utf8"));
const requireValue = (condition, message) => {
  if (!condition) errors.push(message);
};

const packageJson = readJson("package.json");
const codex = readJson(".codex-plugin/plugin.json");
const claude = readJson(".claude-plugin/plugin.json");
const codexMarketplace = readJson(".agents/plugins/marketplace.json");
const claudeMarketplace = readJson(".claude-plugin/marketplace.json");
const hooks = readJson("hooks/hooks.json");

requireValue(packageJson.name === "nova-forge", "package name must be nova-forge");
requireValue(/^\d+\.\d+\.\d+$/.test(packageJson.version), "package version must be stable SemVer");
requireValue(packageJson.type === "module", "package type must be module");
requireValue(packageJson.engines?.node === ">=22.5.0", "Node engine must be >=22.5.0");
requireValue(!packageJson.dependencies && !packageJson.devDependencies, "dependencies are forbidden");

for (const [label, manifest] of [["Codex", codex], ["Claude Code", claude]]) {
  requireValue(manifest.name === packageJson.name, `${label} manifest name mismatch`);
  requireValue(manifest.version === packageJson.version, `${label} manifest version mismatch`);
  requireValue(manifest.skills === "./skills/", `${label} skills path mismatch`);
  requireValue(!Object.hasOwn(manifest, "mcpServers"), `${label} manifest must not register MCP`);
  requireValue(!Object.hasOwn(manifest, "hooks"), `${label} must use hooks/hooks.json discovery`);
}

requireValue(
  codexMarketplace.plugins?.[0]?.source?.url === "https://github.com/Kabulaka/nova-forge.git" &&
    codexMarketplace.plugins?.[0]?.source?.ref === `v${packageJson.version}`,
  "Codex marketplace source mismatch",
);
requireValue(
  claudeMarketplace.metadata?.version === packageJson.version &&
    claudeMarketplace.plugins?.[0]?.version === packageJson.version &&
    claudeMarketplace.plugins?.[0]?.source === "./",
  "Claude Code marketplace mismatch",
);

requireValue(
  JSON.stringify(Object.keys(hooks.hooks || {})) === JSON.stringify(["SessionStart"]),
  "only SessionStart hook is allowed",
);
const session = hooks.hooks?.SessionStart?.[0];
requireValue(session?.matcher === "startup|resume|clear|compact", "SessionStart matcher mismatch");
requireValue(session?.hooks?.length === 1, "SessionStart must have one command");
requireValue(
  session?.hooks?.[0]?.command === 'node "${CLAUDE_PLUGIN_ROOT}/hooks/run.mjs"',
  "SessionStart command mismatch",
);

for (const name of skills) {
  const skillFile = path.join(root, "skills", name, "SKILL.md");
  requireValue(fs.existsSync(skillFile), `missing skill ${name}`);
  if (fs.existsSync(skillFile)) {
    const text = fs.readFileSync(skillFile, "utf8");
    requireValue(new RegExp(`^name:\\s*${name}\\s*$`, "m").test(text), `skill name mismatch ${name}`);
  }
}
const actualSkills = fs
  .readdirSync(path.join(root, "skills"), { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .sort();
requireValue(
  JSON.stringify(actualSkills) === JSON.stringify([...skills].sort()),
  `skills must be exactly ${skills.join(", ")}; found ${actualSkills.join(", ")}`,
);
for (const name of removed) {
  requireValue(!fs.existsSync(path.join(root, "skills", name)), `removed skill still exists: ${name}`);
}
for (const relative of [".mcp.json", "runtime", "codex/scripts", ...removedReferences]) {
  requireValue(!fs.existsSync(path.join(root, relative)), `removed component still exists: ${relative}`);
}
for (const relative of [
  "codex/AGENTS.global.md",
  "hooks/run.mjs",
  "skills/nova-architecture/assets/PROJECT_BLUEPRINT.template.md",
  "skills/nova-architecture/assets/SHARED_CAPABILITIES.template.md",
  "skills/nova-development/assets/DESIGN.template.md",
  "skills/nova-development/references/conversation-sop.md",
  "skills/nova-development/references/design-document-standard.md",
  "skills/nova-development/references/reference-research-sop.md",
]) {
  requireValue(fs.existsSync(path.join(root, relative)), `missing component ${relative}`);
}

const rules = fs.readFileSync(path.join(root, "codex", "AGENTS.global.md"), "utf8");
for (const phrase of [
  "nova-architecture",
  "蓝图存在后，只有用户主动调用",
  "不主动扫描、枚举、通配匹配或索引",
  "只有用户明确要求 Review",
  "只有用户明确要求创建本地提交",
]) {
  requireValue(rules.includes(phrase), `global rules missing: ${phrase}`);
}

if (errors.length) {
  errors.forEach((error) => process.stderr.write(`ERROR: ${error}\n`));
  process.exitCode = 1;
} else {
  process.stdout.write("PASS: lightweight dual-host plugin structure\n");
}
