#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

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
const required = [
  "package.json",
  ".codex-plugin/plugin.json",
  ".mcp.json",
  ".claude-plugin/plugin.json",
  "hooks/hooks.json",
  "hooks/run.mjs",
  "runtime/bootstrap.mjs",
  "runtime/core/state-root.mjs",
  "runtime/mcp/server.mjs",
  "skills/nova-requirements/SKILL.md",
  "skills/nova-architecture/SKILL.md",
  "skills/nova-development/SKILL.md",
  "skills/nova-doctor/SKILL.md",
  "skills/nova-review/SKILL.md",
];
const missing = required.filter((file) => !files.has(file));
const forbidden = [...files].filter(
  (file) =>
    file.startsWith(".nova/") ||
    file.startsWith("tests/") ||
    file.includes("/__pycache__/") ||
    /\.py[cod]$/.test(file) ||
    /^nova-(?:requirements|architecture|development|doctor|review)(?:\/|$)/.test(file),
);
const invalidReferences = [...files]
  .filter((file) => file.endsWith(".md"))
  .filter((file) => {
    const text = fs.readFileSync(path.join(root, file), "utf8");
    return /(?<!skills\/)(?<!\.\.\/)nova-(?:requirements|architecture|development|doctor|review)\//.test(text);
  });
if (missing.length || forbidden.length || invalidReferences.length) {
  if (missing.length) process.stderr.write(`Missing package files: ${missing.join(", ")}\n`);
  if (forbidden.length) process.stderr.write(`Forbidden package files: ${forbidden.join(", ")}\n`);
  if (invalidReferences.length) {
    process.stderr.write(`Broken packaged root references: ${invalidReferences.join(", ")}\n`);
  }
  process.exitCode = 1;
} else {
  process.stdout.write(`PASS: package contains ${files.size} files (${report.size} bytes)\n`);
}
