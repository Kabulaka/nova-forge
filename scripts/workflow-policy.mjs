function jobBlock(workflow, jobName) {
  const lines = workflow.split(/\r?\n/);
  const start = lines.findIndex((line) => line === `  ${jobName}:`);
  if (start === -1) return "";
  let end = start + 1;
  while (end < lines.length && !/^  [A-Za-z_][A-Za-z0-9_-]*\s*:/.test(lines[end])) end += 1;
  return lines.slice(start, end).join("\n");
}

export function validateCiWorkflow(workflow) {
  const errors = [];
  const plugin = jobBlock(workflow, "plugin");
  if (!plugin) return ["CI is missing the plugin job"];
  if (!/^        os: \[ubuntu-latest, macos-latest, windows-latest\]\s*$/m.test(plugin)) {
    errors.push("plugin CI must cover Ubuntu, macOS, and Windows");
  }
  if (!/^    runs-on: \$\{\{ matrix\.os \}\}\s*$/m.test(plugin)) {
    errors.push("plugin CI must run on matrix.os");
  }
  if (!/^      - run: npm run check\s*$/m.test(plugin)) {
    errors.push("plugin CI must run npm run check");
  }
  if (jobBlock(workflow, "governance")) {
    errors.push("CI must not contain a governance job");
  }
  if (/python -m unittest|nova-(?:requirements|doctor)/.test(workflow)) {
    errors.push("CI must not run removed governance suites");
  }
  return errors;
}
