import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { validateCiWorkflow, validateGovernanceCheckout } from "../scripts/workflow-policy.mjs";
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

test("CI policy binds both platform matrices and runners to their jobs", () => {
  const ci = fs.readFileSync(ciPath, "utf8");
  assert.deepEqual(validateCiWorkflow(ci), []);

  const missingGovernanceMatrix = ci
    .replace(
      "        os: [ubuntu-latest, macos-latest, windows-latest]\n    runs-on: ${{ matrix.os }}\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0",
      "        os: [ubuntu-latest]\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0",
    )
    .concat("\n# os: [ubuntu-latest, macos-latest, windows-latest]\n");
  const errors = validateCiWorkflow(missingGovernanceMatrix).join("\n");
  assert.match(errors, /governance CI must cover Ubuntu, macOS, and Windows/);
  assert.match(errors, /governance CI must run on matrix\.os/);
});

test("CI policy rejects job and matrix filters that cancel Windows", () => {
  const ci = fs.readFileSync(ciPath, "utf8");
  const jobFiltered = ci.replace(
    "  governance:\n    env:",
    "  governance:\n    if: runner.os != 'Windows'\n    env:",
  );
  assert.match(
    validateCiWorkflow(jobFiltered).join("\n"),
    /governance CI must not filter platforms at job level/,
  );

  const matrixExcluded = ci.replace(
    "        os: [ubuntu-latest, macos-latest, windows-latest]\n    runs-on: ${{ matrix.os }}\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0",
    "        os: [ubuntu-latest, macos-latest, windows-latest]\n        exclude:\n          - os: windows-latest\n    runs-on: ${{ matrix.os }}\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0",
  );
  assert.match(
    validateCiWorkflow(matrixExcluded).join("\n"),
    /governance CI must not exclude required matrix platforms/,
  );
});

test("CI policy requires every Nova skill test on Windows", () => {
  const ci = fs.readFileSync(ciPath, "utf8");
  const missing = ci.replace(
    "      - run: python -m unittest discover -s skills/nova-doctor/scripts -p 'test_*.py'",
    "      - if: runner.os != 'Windows'\n        run: python -m unittest discover -s skills/nova-doctor/scripts -p 'test_*.py'",
  );
  assert.match(
    validateCiWorkflow(missing).join("\n"),
    /governance CI must run on every platform: .*nova-doctor/,
  );
});

test("CI policy rejects broad or missing Windows codex coverage", () => {
  const ci = fs.readFileSync(ciPath, "utf8");
  const missingPortableTest = ci.replace(
    "      - if: runner.os == 'Windows'\n        run: python -m unittest discover -s codex/scripts -p 'test_context_mode_audit.py'\n",
    "",
  );
  assert.match(
    validateCiWorkflow(missingPortableTest).join("\n"),
    /test_context_mode_audit\.py/,
  );

  const extraBroadStep = ci.replace(
    "      - if: runner.os == 'Windows'\n        run: python -m unittest discover -s codex/scripts -p 'test_agents_global.py'",
    "      - if: runner.os == 'Windows'\n        run: python -m unittest discover -s codex/scripts -p 'test_*.py'",
  );
  const errors = validateCiWorkflow(extraBroadStep).join("\n");
  assert.match(errors, /test_agents_global\.py/);
  assert.match(errors, /only the three approved codex script steps/);
});
