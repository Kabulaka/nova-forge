#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const checking = process.argv.includes("--check");

function read(relative) {
  return JSON.parse(fs.readFileSync(path.join(root, relative), "utf8"));
}

function write(relative, value) {
  fs.writeFileSync(path.join(root, relative), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

const packageJson = read("package.json");
const version = packageJson.version;
if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version)) {
  throw new Error(`package.json.version is not strict SemVer: ${version}`);
}
const tag = `v${version}`;

const documents = [
  [".codex-plugin/plugin.json", (value) => (value.version = version)],
  [".claude-plugin/plugin.json", (value) => (value.version = version)],
  [".agents/plugins/marketplace.json", (value) => (value.plugins[0].source.ref = tag)],
  [
    ".claude-plugin/marketplace.json",
    (value) => {
      value.metadata.version = version;
      value.plugins[0].version = version;
      value.plugins[0].source.ref = tag;
    },
  ],
];

const mismatches = [];
for (const [relative, update] of documents) {
  const before = read(relative);
  const after = structuredClone(before);
  update(after);
  if (JSON.stringify(before) !== JSON.stringify(after)) {
    if (checking) mismatches.push(relative);
    else write(relative, after);
  }
}

if (mismatches.length) {
  process.stderr.write(`Version mismatch: ${mismatches.join(", ")}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write(`${checking ? "PASS" : "UPDATED"}: version ${version}\n`);
}
