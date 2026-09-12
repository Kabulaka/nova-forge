#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  HOST_CLAUDE_CODE,
  HOST_CODEX,
  installClaudeDevelopmentPlugin,
  installDevelopmentPlugin,
  SUPPORTED_HOSTS,
} from "./codex-dev-plugin-lib.mjs";

function parseArguments(argv) {
  const hosts = [];
  let dryRun = false;
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--dry-run") {
      dryRun = true;
      continue;
    }
    if (argument === "--host") {
      const host = argv[index + 1];
      if (!SUPPORTED_HOSTS.includes(host)) throw new Error(`unsupported host: ${host || "missing"}`);
      hosts.push(host);
      index += 1;
      continue;
    }
    throw new Error(`unknown argument: ${argument}`);
  }
  return { dryRun, hosts: hosts.length ? [...new Set(hosts)] : [...SUPPORTED_HOSTS] };
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

try {
  const { dryRun, hosts } = parseArguments(process.argv.slice(2));
  const now = new Date();
  if (hosts.includes(HOST_CODEX)) {
    installDevelopmentPlugin({ repoRoot, dryRun, now });
  }
  if (hosts.includes(HOST_CLAUDE_CODE)) {
    installClaudeDevelopmentPlugin({ repoRoot, dryRun, now });
  }
} catch (error) {
  process.stderr.write(`ERROR: ${error.message}\n`);
  process.exit(1);
}
