#!/usr/bin/env node
import { bootstrapStateRoot } from "./core/state-root.mjs";
import { isMainModule, NovaError, redactError } from "./core/util.mjs";

function parseHosts(argv) {
  const hosts = [];
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] !== "--host" || !argv[index + 1]) {
      throw new NovaError("INVALID_ARGUMENT", "usage: bootstrap.mjs --host codex [--host claude-code]");
    }
    hosts.push(argv[index + 1]);
    index += 1;
  }
  if (hosts.length === 0) {
    throw new NovaError("INVALID_ARGUMENT", "at least one --host is required");
  }
  return [...new Set(hosts)];
}

export function main(argv = process.argv.slice(2), environment = process.env) {
  const results = parseHosts(argv).map((host) =>
    bootstrapStateRoot({ environment, host, legacyRoots: [] }),
  );
  process.stdout.write(`${results[0].dataRoot}\n`);
}

if (isMainModule(import.meta.url, process.argv[1])) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${redactError(error)}\n`);
    process.exitCode = 1;
  }
}
