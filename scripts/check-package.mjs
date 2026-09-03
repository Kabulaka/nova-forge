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
const required = [
  "package.json",
  ".codex-plugin/plugin.json",
  ".claude-plugin/plugin.json",
  "hooks/hooks.json",
  "hooks/run.mjs",
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
    /^nova-(?:requirements|architecture|development|doctor|review)(?:\/|$)/.test(file),
);
if (missing.length || forbidden.length) {
  if (missing.length) process.stderr.write(`Missing package files: ${missing.join(", ")}\n`);
  if (forbidden.length) process.stderr.write(`Forbidden package files: ${forbidden.join(", ")}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write(`PASS: package contains ${files.size} files (${report.size} bytes)\n`);
}
