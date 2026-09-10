import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { validateGovernanceCheckout } from "../scripts/workflow-policy.mjs";
import { pluginRoot } from "./helpers.mjs";

const ciPath = path.join(pluginRoot, ".github", "workflows", "ci.yml");

test("accepts complete history on the governance checkout", () => {
  const ci = fs.readFileSync(ciPath, "utf8");
  assert.deepEqual(validateGovernanceCheckout(ci), []);
});

test("governance cannot borrow complete checkout history from a later job", () => {
  const ci = fs
    .readFileSync(ciPath, "utf8")
    .replace(
      /      - uses: actions\/checkout@v4\r?\n        with:\r?\n          fetch-depth: 0\r?\n/,
      "      - uses: actions/checkout@v4\n",
    )
    .concat(
      "\n  later-job: # platform validation\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n",
    );
  assert.match(
    validateGovernanceCheckout(ci).join("\n"),
    /governance checkout must fetch complete review history/,
  );
});
