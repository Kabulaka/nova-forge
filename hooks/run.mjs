#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { handleHook } from "../runtime/adapters/hook.mjs";
import { HOOK_INPUT_LIMIT } from "../runtime/core/constants.mjs";
import { NovaError, redactError } from "../runtime/core/util.mjs";
import { fileURLToPath } from "node:url";

function isMainModule(moduleUrl, argumentPath) {
  if (!argumentPath) return false;
  const modulePath = fileURLToPath(moduleUrl);
  if (path.resolve(modulePath) === path.resolve(argumentPath)) return true;
  return fs.realpathSync(modulePath) === fs.realpathSync(argumentPath);
}

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
    const output = handleHook(input, environment);
    if (Object.keys(output).length > 0) outputStream.write(`${JSON.stringify(output)}\n`);
  } catch (error) {
    const reason = `Nova hook failed: ${redactError(error)}`;
    const claude =
      environment.NOVA_HOST === "claude-code" ||
      Boolean(environment.CLAUDE_PLUGIN_ROOT || environment.CLAUDE_PLUGIN_DATA);
    if (claude) {
      errorStream.write(`${reason}\n`);
      process.exitCode = 2;
    } else {
      outputStream.write(
        `${JSON.stringify({
          continue: false,
          stopReason: reason,
          systemMessage: "Nova hook failed before lifecycle state could be verified.",
        })}\n`,
      );
    }
  }
}

if (isMainModule(import.meta.url, process.argv[1])) await main();
