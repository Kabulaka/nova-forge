import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pluginRoot } from "./helpers.mjs";

test("native DSH package install, shared resources, model request, disable, re-enable and remove", { timeout: 180_000 }, () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nova-dsh-native-"));
  const environment = { ...process.env, DSH_HOME: path.join(root, "dsh"), DSH_AGENTS_HOME: path.join(root, "agents"), DSH_TELEMETRY_MODE: "OFF", DSH_PERMISSION_MODE: "danger-full-access" };
  for (const key of Object.keys(environment)) {
    if (/API_KEY|TOKEN|SECRET|NOVA_PLUGIN_ROOT|PLUGIN_ROOT|CLAUDE_PLUGIN_ROOT|NOVA_DSH_ROOT/.test(key)) delete environment[key];
  }
  const cwd = path.join(root, "project");
  fs.mkdirSync(cwd);
  fs.mkdirSync(path.join(environment.DSH_AGENTS_HOME, "skills/unrelated"), { recursive: true });
  fs.writeFileSync(path.join(cwd, "AGENTS.md"), "Project sentinel rules.\n");
  fs.writeFileSync(path.join(environment.DSH_AGENTS_HOME, "AGENTS.md"), "User sentinel rules.\n");
  fs.writeFileSync(path.join(environment.DSH_AGENTS_HOME, "skills/unrelated/SKILL.md"), "---\nname: unrelated\ndescription: Preserved external skill\n---\nUnrelated skill.\n");
  let diagnostics = "";
  const run = (bin, args, working = cwd) => {
    const result = spawnSync(bin, args, { cwd: working, env: environment, encoding: "utf8", timeout: 60_000, maxBuffer: 8 * 1024 * 1024 });
    assert.equal(result.status, 0, `${bin} ${args.join(" ")}\n${result.error || ""}\n${result.stderr}\n${result.stdout}`);
    diagnostics = result.stderr;
    return result.stdout;
  };
  try {
    assert.equal(run("dsh", ["--version"]).trim(), "0.2.1-rc.2");
    const report = JSON.parse(run("npm", ["pack", "--json", "--ignore-scripts", "--pack-destination", root], pluginRoot))[0];
    const archive = path.join(root, report.filename);
    const probeRoot = path.join(root, "probe");
    fs.mkdirSync(probeRoot);
    fs.copyFileSync(path.join(pluginRoot, "tests/fixtures/dsh-probe.mjs"), path.join(probeRoot, "index.mjs"));
    fs.writeFileSync(path.join(probeRoot, "package.json"), JSON.stringify({
      name: "nova-dsh-probe", version: "1.0.0", type: "module", exports: "./index.mjs",
      dsh: { bundle: { patch: "./cordis.patch.yml" } },
      peerDependencies: { "@deepseek-ai/dsh-llm": "0.2.1-rc.2", "@deepseek-ai/dsh-session": "0.2.1-rc.2" },
    }));
    fs.writeFileSync(path.join(probeRoot, "cordis.patch.yml"), "[]\n");
    run("dsh", ["plugin", "--profile", "headless", "add", probeRoot]);
    run("dsh", ["plugin", "--profile", "unaffected", "add", probeRoot]);
    const otherProfile = path.join(environment.DSH_HOME, "profiles/unaffected");
    const snapshot = () => Object.fromEntries(fs.readdirSync(otherProfile, { withFileTypes: true }).filter((e) => e.isFile()).map((e) => [e.name, fs.readFileSync(path.join(otherProfile, e.name), "utf8")]));
    const otherBaseline = snapshot();
    const profile = path.join(environment.DSH_HOME, "profiles/headless");
    const userPatch = path.join(profile, "cordis.patch.yml");
    const install = () => run("dsh", ["plugin", "--profile", "headless", "add", archive]);
    install();
    install(); // repeated native add must not duplicate bundle or registration
    const config = run("dsh", ["--profile", "headless", "--dump-config"]);
    assert.equal((config.match(/id: nova-forge\b/g) || []).length, 1);
    const probePatch = path.join(root, "probe.yml");
    const probe = (enabled) => {
      fs.writeFileSync(probePatch, [
        "- id: headless-startup\n  disabled: true",
        "- id: headless-runner\n  disabled: true",
        "- id: session-title-llm\n  disabled: true",
        "- id: session-telemetry-otel\n  disabled: true",
        `- insert:\n    - id: nova-probe\n      name: nova-dsh-probe\n      config:\n        enabled: ${enabled}`,
      ].join("\n") + "\n");
      const output = run("dsh", ["--profile", "headless", "--patch", probePatch]);
      assert.match(output, /NOVA_DSH_PROBE_PASS/, diagnostics || "DSH exited without executing the probe");
    };
    probe(true);
    const originalPatch = fs.readFileSync(userPatch, "utf8");
    fs.writeFileSync(userPatch, originalPatch.replace(/^\[\]\s*$/m, "") + "\n- id: nova-forge\n  disabled: true\n");
    install(); // update must preserve the user's disabled override
    probe(false);
    fs.writeFileSync(userPatch, originalPatch);
    probe(true);
    run("dsh", ["plugin", "--profile", "headless", "remove", "nova-forge"]);
    assert.doesNotMatch(run("dsh", ["--profile", "headless", "--dump-config"]), /id: nova-forge\b/);
    probe(false);
    assert.equal(fs.readFileSync(path.join(cwd, "AGENTS.md"), "utf8"), "Project sentinel rules.\n");
    assert.equal(fs.readFileSync(path.join(environment.DSH_AGENTS_HOME, "AGENTS.md"), "utf8"), "User sentinel rules.\n");
    assert.deepEqual(fs.readdirSync(path.join(environment.DSH_AGENTS_HOME, "skills")), ["unrelated"]);
    assert.deepEqual(snapshot(), otherBaseline);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
