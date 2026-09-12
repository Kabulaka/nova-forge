#!/usr/bin/env node
process.argv.push("--host", "codex");
await import("./install-dev-plugin.mjs");
