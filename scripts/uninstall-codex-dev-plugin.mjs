#!/usr/bin/env node
process.argv.push("--host", "codex");
await import("./uninstall-dev-plugin.mjs");
