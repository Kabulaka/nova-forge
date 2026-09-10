const GOVERNANCE_HISTORY_ERROR = "governance checkout must fetch complete review history";

function jobBlock(workflow, jobName) {
  const lines = workflow.split(/\r?\n/);
  const start = lines.findIndex((line) => line === `  ${jobName}:`);
  if (start === -1) return "";
  let end = start + 1;
  while (end < lines.length && !/^  [A-Za-z_][A-Za-z0-9_-]*\s*:/.test(lines[end])) end += 1;
  return lines.slice(start, end).join("\n");
}

export function validateGovernanceCheckout(workflow) {
  const governance = jobBlock(workflow, "governance");
  const completeCheckout =
    /^      - uses: actions\/checkout@v4\s*$\n^        with:\s*$\n^          fetch-depth:\s*0\s*$/m;
  return completeCheckout.test(governance) ? [] : [GOVERNANCE_HISTORY_ERROR];
}
