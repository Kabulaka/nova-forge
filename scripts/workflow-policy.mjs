const GOVERNANCE_HISTORY_ERROR = "governance checkout must fetch complete review history";

function jobBlock(workflow, jobName) {
  const lines = workflow.split(/\r?\n/);
  const start = lines.findIndex((line) => line === `  ${jobName}:`);
  if (start === -1) return "";
  let end = start + 1;
  while (end < lines.length && !/^  [A-Za-z_][A-Za-z0-9_-]*\s*:/.test(lines[end])) end += 1;
  return lines.slice(start, end).join("\n");
}

const PLATFORM_MATRIX = /^        os: \[ubuntu-latest, macos-latest, windows-latest\]\s*$/m;
const MATRIX_RUNNER = /^    runs-on: \$\{\{ matrix\.os \}\}\s*$/m;
const PLUGIN_COMMANDS = [
  "npm test",
  "npm run check:version",
  "npm run check:plugin",
  "npm run check:release-notes",
  "npm run check:workflow",
  "npm run check:package",
];
const GOVERNANCE_COMMANDS = [
  "python -m unittest discover -s skills/nova-requirements/scripts -p 'test_*.py'",
  "python -m unittest discover -s skills/nova-architecture/scripts -p 'test_*.py'",
  "python -m unittest discover -s skills/nova-development/scripts -p 'test_*.py'",
  "python -m unittest discover -s skills/nova-doctor/scripts -p 'test_*.py'",
  "python -m unittest discover -s skills/nova-review/scripts -p 'test_*.py'",
];
const CODEX_STEPS = [
  {
    condition: "runner.os != 'Windows'",
    command: "python -m unittest discover -s codex/scripts -p 'test_*.py'",
  },
  {
    condition: "runner.os == 'Windows'",
    command: "python -m unittest discover -s codex/scripts -p 'test_agents_global.py'",
  },
  {
    condition: "runner.os == 'Windows'",
    command: "python -m unittest discover -s codex/scripts -p 'test_context_mode_audit.py'",
  },
];

function escapePattern(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function hasRunStep(job, command) {
  return new RegExp(`^      - run: ${escapePattern(command)}\\s*$`, "m").test(job);
}

function hasConditionalRunStep(job, condition, command) {
  return new RegExp(
    `^      - if: ${escapePattern(condition)}\\s*\\n        run: ${escapePattern(command)}\\s*$`,
    "m",
  ).test(job);
}

export function validateCiWorkflow(workflow) {
  const errors = [];
  const plugin = jobBlock(workflow, "plugin");
  const governance = jobBlock(workflow, "governance");
  for (const [name, job] of [["plugin", plugin], ["governance", governance]]) {
    if (!job) {
      errors.push(`CI is missing the ${name} job`);
      continue;
    }
    if (!PLATFORM_MATRIX.test(job)) {
      errors.push(`${name} CI must cover Ubuntu, macOS, and Windows`);
    }
    if (!MATRIX_RUNNER.test(job)) {
      errors.push(`${name} CI must run on matrix.os`);
    }
    if (/^    if:\s*/m.test(job)) {
      errors.push(`${name} CI must not filter platforms at job level`);
    }
    if (/^        exclude:\s*$/m.test(job)) {
      errors.push(`${name} CI must not exclude required matrix platforms`);
    }
  }
  for (const command of PLUGIN_COMMANDS) {
    if (!hasRunStep(plugin, command)) errors.push(`plugin CI missing ${command}`);
  }
  for (const command of GOVERNANCE_COMMANDS) {
    if (!hasRunStep(governance, command)) {
      errors.push(`governance CI must run on every platform: ${command}`);
    }
  }
  for (const { condition, command } of CODEX_STEPS) {
    if (!hasConditionalRunStep(governance, condition, command)) {
      errors.push(`governance CI missing ${condition}: ${command}`);
    }
  }
  const actualCodexCommands = governance
    .split(/\r?\n/)
    .filter((line) => /^        run: .*codex\/scripts/.test(line))
    .map((line) => line.trim())
    .sort();
  const approvedCodexCommands = CODEX_STEPS
    .map(({ command }) => `run: ${command}`)
    .sort();
  if (JSON.stringify(actualCodexCommands) !== JSON.stringify(approvedCodexCommands)) {
    errors.push("governance CI must use only the three approved codex script steps");
  }
  return errors;
}

export function validateGovernanceCheckout(workflow) {
  const governance = jobBlock(workflow, "governance");
  const completeCheckout =
    /^      - uses: actions\/checkout@v4\s*$\n^        with:\s*$\n^          fetch-depth:\s*0\s*$/m;
  return completeCheckout.test(governance) ? [] : [GOVERNANCE_HISTORY_ERROR];
}
