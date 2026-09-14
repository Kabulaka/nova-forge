import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { validateCiWorkflow } from "../scripts/workflow-policy.mjs";
import { pluginRoot } from "./helpers.mjs";

const ci = fs.readFileSync(path.join(pluginRoot, ".github", "workflows", "ci.yml"), "utf8");

test("CI runs the complete check on all supported platforms", () => {
  assert.deepEqual(validateCiWorkflow(ci), []);
});

test("CI rejects removed governance jobs", () => {
  const changed = `${ci}\n  governance:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python -m unittest\n`;
  assert.match(validateCiWorkflow(changed).join("\n"), /governance/);
});

test("CI requires the three-platform matrix and complete check", () => {
  assert.match(
    validateCiWorkflow(ci.replace("windows-latest", "ubuntu-latest")).join("\n"),
    /Ubuntu, macOS, and Windows/,
  );
  assert.match(
    validateCiWorkflow(ci.replace("npm run check", "npm test")).join("\n"),
    /npm run check/,
  );
});
