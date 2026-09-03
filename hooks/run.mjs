#!/usr/bin/env node
import { handleHook } from "../runtime/adapters/hook.mjs";
import { redactError } from "../runtime/core/util.mjs";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);

try {
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const output = handleHook(input);
  if (Object.keys(output).length > 0) process.stdout.write(`${JSON.stringify(output)}\n`);
} catch (error) {
  process.stdout.write(
    `${JSON.stringify({
      continue: false,
      stopReason: `Nova hook failed: ${redactError(error)}`,
      systemMessage: "Nova hook failed before lifecycle state could be verified.",
    })}\n`,
  );
}
