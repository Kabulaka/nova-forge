#!/usr/bin/env node
import { detectHost, handleHook } from "../runtime/adapters/hook.mjs";
import { HOOK_INPUT_LIMIT } from "../runtime/core/constants.mjs";
import { resolveHostProcessId } from "../runtime/core/rendezvous.mjs";
import { isMainModule, NovaError, redactError } from "../runtime/core/util.mjs";

export async function readHookInput(stream, inputLimit = HOOK_INPUT_LIMIT) {
  if (!Number.isSafeInteger(inputLimit) || inputLimit <= 0) {
    throw new NovaError("INVALID_HOOK_INPUT_LIMIT", "hook input limit must be a positive integer");
  }
  const chunks = [];
  let totalBytes = 0;
  for await (const value of stream) {
    const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
    if (chunk.length > inputLimit - totalBytes) {
      throw new NovaError(
        "HOOK_INPUT_LIMIT",
        `hook input exceeds the ${inputLimit}-byte safety limit`,
      );
    }
    totalBytes += chunk.length;
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks, totalBytes).toString("utf8"));
}

export async function main({
  inputStream = process.stdin,
  outputStream = process.stdout,
  errorStream = process.stderr,
  environment = process.env,
  inputLimit = HOOK_INPUT_LIMIT,
} = {}) {
  try {
    const input = await readHookInput(inputStream, inputLimit);
    const host = detectHost(environment);
    const output = handleHook(input, environment, { hostPid: resolveHostProcessId(host) });
    if (Object.keys(output).length > 0) outputStream.write(`${JSON.stringify(output)}\n`);
  } catch (error) {
    const reason = `Nova hook failed: ${redactError(error)}`;
    errorStream.write(
      `${reason}. Nova checkpoint continuity is degraded; the host operation was allowed to continue.\n`,
    );
  }
}

if (isMainModule(import.meta.url, process.argv[1])) await main();
