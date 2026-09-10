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

test("rejects a missing release note", () => {
  const { root } = fixture();
  try {
    fs.rmSync(path.join(root, "docs", "release-notes", "v1.2.3.md"));
    assert.match(validateReleaseNotes({ root, tag: "v1.2.3" }).errors.join("\n"), /release notes are missing/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

const invalidCases = [
  {
    name: "title mismatch",
    transform: (notes) => notes.replace("# Nova Forge v1.2.3", "# Nova Forge v9.9.9"),
    expected: /must start with/,
  },
  {
    name: "missing required heading",
    transform: (notes) => notes.replace("## Upgrade Notes", "## Notes"),
    expected: /missing required heading: Upgrade Notes/,
  },
  {
    name: "unresolved placeholder",
    transform: (notes) => notes.replace("- None.", "- TODO"),
    expected: /unresolved placeholder/,
  },
  {
    name: "missing Codex install command",
    transform: (notes) => notes.replace("codex plugin marketplace add", "codex plugin marketplace remove"),
    expected: /missing pinned Codex install command/,
  },
  {
    name: "missing Claude marketplace command",
    transform: (notes) => notes.replace("/plugin marketplace add", "/plugin marketplace remove"),
    expected: /missing Claude Code install command: \/plugin marketplace add/,
  },
  {
    name: "missing Claude install command",
    transform: (notes) => notes.replace("/plugin install", "/plugin uninstall"),
    expected: /missing Claude Code install command: \/plugin install/,
  },
  {
    name: "missing changelog",
    transform: (notes) => notes.replace("**Full Changelog**", "**Changes**"),
    expected: /need a baseline or comparison changelog/,
  },
  {
    name: "wrong changelog target",
    transform: (notes) => notes.replace("commits/v1.2.3", "commits/v1.2.2"),
    expected: /ending at v1.2.3/,
  },
  {
    name: "heading only in an HTML comment",
    transform: (notes) => notes.replace("## Overview", "<!-- ## Overview -->"),
    expected: /missing required heading: Overview/,
  },
  {
    name: "heading only in a fenced block",
    transform: (notes) => notes.replace("## Overview", "```md\n## Overview\n```"),
    expected: /missing required heading: Overview/,
  },
  {
    name: "heading after a non-closing fence marker",
    transform: (notes) => notes.replace("## Overview", "```md\n```not-a-close\n## Overview\n```"),
    expected: /missing required heading: Overview/,
  },
  {
    name: "install command only in an HTML comment",
    transform: (notes) =>
      notes.replace(
        "`codex plugin marketplace add Kabulaka/nova-forge --ref v1.2.3`",
        "<!-- codex plugin marketplace add Kabulaka/nova-forge --ref v1.2.3 -->",
      ),
    expected: /missing pinned Codex install command/,
  },
  {
    name: "install command outside Installation",
    transform: (notes) =>
      notes
        .replace("`codex plugin marketplace add Kabulaka/nova-forge --ref v1.2.3`", "Install Codex from the marketplace.")
        .replace("Overview.", "Overview. codex plugin marketplace add Kabulaka/nova-forge --ref v1.2.3"),
    expected: /missing pinned Codex install command/,
  },
  {
    name: "changelog only in an HTML comment",
    transform: (notes) =>
      notes.replace(
        "**Full Changelog**: https://github.com/Kabulaka/nova-forge/commits/v1.2.3",
        "<!-- **Full Changelog**: https://github.com/Kabulaka/nova-forge/commits/v1.2.3 -->",
      ),
    expected: /need a baseline or comparison changelog/,
  },
  {
    name: "changelog only in a fenced block",
    transform: (notes) =>
      notes.replace(
        "**Full Changelog**: https://github.com/Kabulaka/nova-forge/commits/v1.2.3",
        "```text\n**Full Changelog**: https://github.com/Kabulaka/nova-forge/commits/v1.2.3\n```",
      ),
    expected: /need a baseline or comparison changelog/,
  },
];

for (const invalidCase of invalidCases) {
  test(`rejects ${invalidCase.name}`, () => {
    const { root, notes } = fixture();
    try {
      fs.writeFileSync(
        path.join(root, "docs", "release-notes", "v1.2.3.md"),
        invalidCase.transform(notes),
      );
      assert.match(validateReleaseNotes({ root, tag: "v1.2.3" }).errors.join("\n"), invalidCase.expected);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
}

test("does not treat a four-space indented marker as a fence", () => {
  const { root, notes } = fixture();
  try {
    fs.writeFileSync(
      path.join(root, "docs", "release-notes", "v1.2.3.md"),
      notes.replace("## Overview", "    ```md\n## Overview\n    ```"),
    );
    assert.deepEqual(validateReleaseNotes({ root, tag: "v1.2.3" }).errors, []);
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
