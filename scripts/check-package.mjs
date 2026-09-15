#!/usr/bin/env node
import { spawnSync } from "node:child_process";

const result = spawnSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {
  encoding: "utf8",
  shell: process.platform === "win32",
});
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout);
  process.exit(result.status || 1);
}

const report = JSON.parse(result.stdout)[0];
const files = new Set(report.files.map((entry) => entry.path));
const expectedSkills = new Set([
  "nova-architecture",
  "nova-development",
  "nova-review",
  "nova-commit",
]);
const removedReferences = new Set([
  "skills/nova-architecture/references/architecture-standard.md",
  "skills/nova-architecture/assets/SHARED_CAPABILITIES.template.md",
  "skills/nova-development/references/implementation-sop.md",
  "skills/nova-review/references/review-sop.md",
]);
const required = [
  "package.json",
  ".codex-plugin/plugin.json",
  ".claude-plugin/plugin.json",
  "hooks/hooks.json",
  "hooks/run.mjs",
  "codex/AGENTS.global.md",
  "skills/nova-architecture/SKILL.md",
  "skills/nova-architecture/assets/PROJECT_BLUEPRINT.template.md",
  "skills/nova-development/SKILL.md",
  "skills/nova-development/assets/DESIGN.template.md",
  "skills/nova-development/references/conversation-sop.md",
  "skills/nova-development/references/design-document-standard.md",
  "skills/nova-development/references/reference-research-sop.md",
  "skills/nova-review/SKILL.md",
  "skills/nova-commit/SKILL.md",
  "skills/nova-commit/agents/openai.yaml",
];
const missing = required.filter((file) => !files.has(file));
const packagedSkills = new Set(
  [...files]
    .filter((file) => file.startsWith("skills/"))
    .map((file) => file.split("/")[1])
    .filter(Boolean),
);
const missingSkills = [...expectedSkills].filter((name) => !packagedSkills.has(name));
const unexpectedSkills = [...packagedSkills].filter((name) => !expectedSkills.has(name));
const forbidden = [...files].filter(
  (file) =>
    file === ".mcp.json" ||
    removedReferences.has(file) ||
    file.startsWith(".nova/") ||
    file.startsWith("runtime/") ||
    file.startsWith("tests/") ||
    file.startsWith("scripts/") ||
    file.startsWith("skills/nova-requirements/") ||
    file.startsWith("skills/nova-doctor/") ||
    file.includes("/__pycache__/") ||
    /\.py[cod]$/.test(file),
);

if (missing.length || missingSkills.length || unexpectedSkills.length || forbidden.length) {
  if (missing.length) process.stderr.write(`Missing package files: ${missing.join(", ")}\n`);
  if (missingSkills.length) {
    process.stderr.write(`Missing package skills: ${missingSkills.join(", ")}\n`);
  }
  if (unexpectedSkills.length) {
    process.stderr.write(`Unexpected package skills: ${unexpectedSkills.join(", ")}\n`);
  }
  if (forbidden.length) process.stderr.write(`Forbidden package files: ${forbidden.join(", ")}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write(`PASS: package contains ${files.size} files (${report.size} bytes)\n`);
}
