#!/usr/bin/env node
import {
  HOST_CLAUDE_CODE,
  HOST_CODEX,
  SUPPORTED_HOSTS,
  uninstallClaudeDevelopmentPlugin,
  uninstallDevelopmentPlugin,
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

try {
  const { dryRun, hosts } = parseArguments(process.argv.slice(2));
  const removeBoth = hosts.length === SUPPORTED_HOSTS.length;
  if (hosts.includes(HOST_CLAUDE_CODE)) {
    uninstallClaudeDevelopmentPlugin({
      dryRun,
      preserveSnapshot: !removeBoth || hosts.includes(HOST_CODEX),
    });
  }
  if (hosts.includes(HOST_CODEX)) {
    uninstallDevelopmentPlugin({ dryRun, preserveSnapshot: !removeBoth });
  }
} catch (error) {
  process.stderr.write(`ERROR: ${error.message}\n`);
  process.exit(1);
}
