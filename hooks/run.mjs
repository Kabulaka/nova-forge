#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const HOOK_INPUT_LIMIT = 256 * 1024;
const SESSION_SOURCES = new Set(["startup", "resume", "clear", "compact"]);

export class HookError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

export async function readHookInput(stream, inputLimit = HOOK_INPUT_LIMIT) {
  if (!Number.isSafeInteger(inputLimit) || inputLimit <= 0) {
    throw new HookError("INVALID_INPUT_LIMIT", "hook input limit must be a positive integer");
  }
  const chunks = [];
  let bytes = 0;
  for await (const value of stream) {
    const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
    if (chunk.length > inputLimit - bytes) {
      throw new HookError("INPUT_TOO_LARGE", "hook input exceeds the safety limit");
    }
    bytes += chunk.length;
    chunks.push(chunk);
  }
  let input;
  try {
    input = JSON.parse(Buffer.concat(chunks, bytes).toString("utf8"));
  } catch {
    throw new HookError("INVALID_JSON", "hook input must be valid JSON");
  }
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new HookError("INVALID_INPUT", "hook input must be a JSON object");
  }
  return input;
}

export function resolvePluginRoot(environment = process.env) {
  const value =
    environment.NOVA_PLUGIN_ROOT ||
    environment.PLUGIN_ROOT ||
    environment.CLAUDE_PLUGIN_ROOT;
  if (typeof value !== "string" || !path.isAbsolute(value)) {
    throw new HookError("PLUGIN_ROOT_UNAVAILABLE", "absolute plugin root is unavailable");
  }
  return path.resolve(value);
}

export function handleHook(input, environment = process.env) {
  if (input.hook_event_name !== "SessionStart") return {};
  if (!SESSION_SOURCES.has(input.source)) {
    throw new HookError("UNSUPPORTED_SESSION_SOURCE", "unsupported SessionStart source");
  }
  const rulesPath = path.join(resolvePluginRoot(environment), "codex", "AGENTS.global.md");
  let rules;
  try {
    rules = fs.readFileSync(rulesPath, "utf8");
  } catch {
    throw new HookError("RULES_UNAVAILABLE", "global rules cannot be read");
  }
  return {
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: rules,
    },
  };
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
    const code = error instanceof HookError ? error.code : "INTERNAL_ERROR";
    errorStream.write(`Nova SessionStart hook failed open: ${code}\n`);
  }
}

function isMainModule(moduleUrl, argument) {
  if (!argument) return false;
  try {
    return fs.realpathSync(fileURLToPath(moduleUrl)) === fs.realpathSync(path.resolve(argument));
  } catch {
    return moduleUrl === pathToFileURL(path.resolve(argument)).href;
  }
}

const isMain = isMainModule(import.meta.url, process.argv[1]);
if (isMain) await main();
