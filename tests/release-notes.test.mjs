import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { validateReleaseNotes } from "../scripts/validate-release-notes.mjs";

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-release-notes-"));
  fs.mkdirSync(path.join(root, "docs", "release-notes"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "package.json"),
    JSON.stringify({
      name: "nova-forge",
      version: "1.2.3",
      repository: { url: "https://github.com/Kabulaka/nova-forge.git" },
    }),
  );
  const notes = `# Nova Forge v1.2.3

> Baseline

## Overview

Overview.

## Highlights

- Highlight.

## Installation

\`codex plugin marketplace add Kabulaka/nova-forge --ref v1.2.3\`

\`/plugin marketplace add Kabulaka/nova-forge\`

\`/plugin install nova-forge@nova-forge\`

## Requirements

- Node.js.

## Upgrade Notes

- None.

---

**Full Changelog**: https://github.com/Kabulaka/nova-forge/commits/v1.2.3
`;
  fs.writeFileSync(path.join(root, "docs", "release-notes", "v1.2.3.md"), notes);
  return { root, notes };
}

test("accepts a complete version-pinned release note", () => {
  const { root } = fixture();
  try {
    assert.deepEqual(validateReleaseNotes({ root, tag: "v1.2.3" }).errors, []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("rejects a tag that differs from package version", () => {
  const { root } = fixture();
  try {
    assert.match(validateReleaseNotes({ root, tag: "v1.2.4" }).errors.join("\n"), /does not match/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("rejects missing sections and unresolved placeholders", () => {
  const { root, notes } = fixture();
  try {
    fs.writeFileSync(
      path.join(root, "docs", "release-notes", "v1.2.3.md"),
      notes.replace("## Upgrade Notes", "## TODO"),
    );
    const errors = validateReleaseNotes({ root, tag: "v1.2.3" }).errors.join("\n");
    assert.match(errors, /missing required heading: Upgrade Notes/);
    assert.match(errors, /unresolved placeholder/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("accepts a comparison changelog for a later release", () => {
  const { root, notes } = fixture();
  try {
    fs.writeFileSync(
      path.join(root, "docs", "release-notes", "v1.2.3.md"),
      notes.replace("commits/v1.2.3", "compare/v1.2.2...v1.2.3"),
    );
    assert.deepEqual(validateReleaseNotes({ root, tag: "v1.2.3" }).errors, []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
