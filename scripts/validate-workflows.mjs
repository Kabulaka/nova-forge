#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { validateGovernanceCheckout } from "./workflow-policy.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ci = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
const release = fs.readFileSync(path.join(root, ".github/workflows/release.yml"), "utf8");
const errors = [];

function requirePattern(text, pattern, message) {
  if (!pattern.test(text)) errors.push(message);
}

function forbidPattern(text, pattern, message) {
  if (pattern.test(text)) errors.push(message);
}

requirePattern(ci, /^\s{2}pull_request:\s*$/m, "CI must run for pull requests");
requirePattern(ci, /^\s{2}push:\s*\n\s{4}branches:\s*\[main\]\s*$/m, "CI push must target main only");
requirePattern(
  ci,
  /os:\s*\[ubuntu-latest,\s*macos-latest,\s*windows-latest\]/,
  "CI must cover Ubuntu, macOS, and Windows",
);
for (const command of [
  "npm test",
  "npm run check:version",
  "npm run check:plugin",
  "npm run check:release-notes",
  "npm run check:workflow",
  "npm run check:package",
]) {
  requirePattern(ci, new RegExp(command.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `CI missing ${command}`);
}
forbidPattern(ci, /^\s{4}tags:/m, "CI workflow must not publish from tags");
errors.push(...validateGovernanceCheckout(ci));

requirePattern(release, /^\s{2}push:\s*\n\s{4}tags:\s*\["v\*\.\*\.\*"\]\s*$/m, "release must be tag-only");
forbidPattern(release, /^\s{2}(pull_request|workflow_dispatch):/m, "release must not have non-tag triggers");
forbidPattern(release, /^\s{4}branches:/m, "release must not run for branch pushes");
requirePattern(release, /^\s{2}contents:\s*write\s*$/m, "release requires contents: write");
requirePattern(release, /fetch-depth:\s*0/, "release checkout must fetch complete tag history");
requirePattern(
  release,
  /test "\$\{GITHUB_REF_NAME\}" = "v\$\{VERSION\}"/,
  "release must reject a tag that differs from package version",
);
for (const command of [
  "scripts/validate-release-notes.mjs",
  "npm run check",
  "npm pack --ignore-scripts",
  "scripts/checksum.mjs",
  "gh release create",
]) {
  requirePattern(
    release,
    new RegExp(command.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    `release missing ${command}`,
  );
}
requirePattern(release, /--notes-file/, "release must publish committed release notes");
requirePattern(release, /docs\/release-notes\/\$\{GITHUB_REF_NAME\}\.md/, "release notes must be selected by tag");
forbidPattern(release, /--generate-notes/, "release must not replace curated notes with generated notes");

if (errors.length) {
  errors.forEach((error) => process.stderr.write(`ERROR: ${error}\n`));
  process.exitCode = 1;
} else {
  process.stdout.write("PASS: CI and tag-only release workflows\n");
}
