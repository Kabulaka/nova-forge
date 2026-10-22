// Runs inside the real DSH loader. Only the model transport is synthetic.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
import { LlmAdapter, createUserMessage } from "@deepseek-ai/dsh-llm";
import { SessionId } from "@deepseek-ai/dsh-session";

export const inject = ["skills", "agentLoop", "llm"];

export async function apply(ctx, config) {
  try {
    await probe(ctx, config);
    console.log("NOVA_DSH_PROBE_PASS");
    process.exit(0);
  } catch (error) {
    console.error(error);
    process.exit(1);
  }
}

async function probe(ctx, config) {
  const sessionId = (label) => SessionId(`${label}-${randomUUID()}`);
  const workspace = process.cwd();
  const novaSkills = async () => (await ctx.skills.list({ cwd: workspace })).filter((skill) => skill.provider === "nova-forge");
  if (!config.enabled) {
    assert.equal((await novaSkills()).length, 0);
    const agent = await ctx.agentLoop.create(sessionId("nova-disabled"), { provider: "nova-mock", model: "probe" }, { cwd: workspace });
    assert.equal(agent.inbox.nextStep.filter((m) => JSON.stringify(m).includes("全局工作约定")).length, 0);
    return;
  }
  const skills = await novaSkills();
  assert.deepEqual(skills.map((s) => s.name).sort(), ["nova-architecture", "nova-commit", "nova-development", "nova-requirements", "nova-review"]);
  for (const skill of skills) {
    const loaded = await ctx.skills.get(skill.name, { cwd: workspace });
    assert.ok(loaded.content.length > 100);
    assert.ok(path.isAbsolute(loaded.path));
    assert.ok(fs.existsSync(loaded.path));
    // Check local and cross-skill references against the packaged skill's base.
    for (const [, link] of loaded.content.matchAll(/\]\(([^)]+)\)/g)) {
      if (/^[a-z]+:|^#/.test(link)) continue;
      assert.ok(fs.existsSync(path.resolve(path.dirname(loaded.path), link.split("#")[0])), `${skill.name}: ${link}`);
    }
  }
  const requests = [];
  class Model extends LlmAdapter {
    async resolveModel(provider, model) { return { provider, id: model, name: model }; }
    async *stream(options) {
      requests.push(options);
      yield { type: "block-start", index: 0, blockType: "text" };
      yield { type: "text-delta", index: 0, text: "ok" };
      yield { type: "block-end", index: 0, block: { type: "text", text: "ok" } };
      yield { type: "usage", usage: { inputTokens: 1, outputTokens: 1 } };
      yield { type: "finish", reason: { kind: "stop" } };
    }
  }
  ctx.llm.registerAdapter(["nova-mock"], new Model());
  const root = path.resolve(path.dirname(skills[0].path), "../..");
  const hookPath = path.join(root, "hooks/run.mjs");
  const original = fs.readFileSync(hookPath, "utf8");
  fs.writeFileSync(hookPath, original.replace("if (isMain) await main();", "if (isMain) { await new Promise(r => setTimeout(r, 180)); await main(); }"));
  const start = Date.now();
  const agent = await ctx.agentLoop.create(sessionId("nova-probe"), { provider: "nova-mock", model: "probe" }, { cwd: workspace });
  assert.ok(Date.now() - start >= 150, "creation must await the deliberately delayed hook");
  const pending = () => agent.inbox.nextStep.filter((m) => JSON.stringify(m).includes("全局工作约定"));
  assert.equal(pending().length, 1, "startup must finish exactly one injection before create resolves");
  agent.followup(createUserMessage({ content: [{ type: "text", text: "probe" }], source: { kind: "user" } }));
  await agent.whenIdle();
  assert.ok(requests.length >= 1);
  const first = JSON.stringify(requests[0].messages);
  assert.ok(first.includes("全局工作约定"));
  assert.ok(first.includes("DeepSeek Harness 的 Nova Forge 包内资源根目录"));
  assert.equal((first.match(/# 全局工作约定/g) || []).length, 1);
  // Forward all four official sources through the REAL bridge and process.
  // This exercises the event contract, not the host's clear/compact UI commands.
  for (const source of ["resume", "clear", "compact"]) {
    const start = Date.now();
    await ctx.serial(agent.ctx, "agent/created", { agent, source });
    assert.ok(Date.now() - start >= 150, `${source} must await the delayed hook`);
    assert.equal(pending().length, 1, `${source} must await exactly one injection`);
    agent.followup(createUserMessage({ content: [{ type: "text", text: source }], source: { kind: "user" } }));
    await agent.whenIdle();
  }
  fs.writeFileSync(hookPath, original);
  assert.ok(!process.env.NOVA_PLUGIN_ROOT, "bridge must not mutate the process environment");

  const rulesPath = path.join(root, "codex/AGENTS.global.md");
  fs.renameSync(rulesPath, `${rulesPath}.hidden`);
  try {
    const missingRules = await ctx.agentLoop.create(sessionId("nova-fail-open"), { provider: "nova-mock", model: "probe" }, { cwd: workspace });
    assert.equal(missingRules.inbox.nextStep.filter((m) => JSON.stringify(m).includes("全局工作约定")).length, 0);
  } finally { fs.renameSync(`${rulesPath}.hidden`, rulesPath); }

  // Exercise the actual parent fiber's disposal, beyond a profile restart.
  const Nova = await import(pathToFileURL(path.join(root, "dsh/index.mjs")).href);
  const runtime = ctx.registry.get(Nova);
  assert.equal(runtime.fibers.length, 1);
  const otherSkills = (await ctx.skills.list({ cwd: workspace })).filter((s) => s.provider !== "nova-forge").map((s) => s.name);
  await [...runtime.fibers][0].dispose();
  assert.equal((await novaSkills()).length, 0);
  assert.deepEqual((await ctx.skills.list({ cwd: workspace })).map((s) => s.name), otherSkills);
  const afterDispose = await ctx.agentLoop.create(sessionId("nova-after-dispose"), { provider: "nova-mock", model: "probe" }, { cwd: workspace });
  assert.equal(afterDispose.inbox.nextStep.filter((m) => JSON.stringify(m).includes("全局工作约定")).length, 0);

  const replacement = await ctx.plugin(Nova);
  assert.equal((await novaSkills()).length, 5);
  const marker = path.join(workspace, "hook-pid");
  // Only the test-installed copy is delayed. Production resources are untouched.
  fs.writeFileSync(hookPath, original.replace("if (isMain) await main();", `if (isMain) { fs.writeFileSync(${JSON.stringify(marker)}, String(process.pid)); await new Promise(r => setTimeout(r, 30000)); await main(); }`));
  try {
    const creating = ctx.agentLoop.create(sessionId("nova-cancel-hook"), { provider: "nova-mock", model: "probe" }, { cwd: workspace });
    const deadline = Date.now() + 5000;
    while (!fs.existsSync(marker)) {
      if (Date.now() > deadline) throw new Error("slow hook never started");
      await new Promise((r) => setTimeout(r, 10));
    }
    const pid = Number(fs.readFileSync(marker, "utf8"));
    await replacement.dispose();
    const cancelled = await creating;
    assert.throws(() => process.kill(pid, 0), { code: "ESRCH" });
    assert.equal((await novaSkills()).length, 0);
    assert.equal(cancelled.inbox.nextStep.filter((m) => JSON.stringify(m).includes("全局工作约定")).length, 0);
  } finally { fs.writeFileSync(hookPath, original); }

  const reenabled = await ctx.plugin(Nova);
  assert.equal((await novaSkills()).length, 5);
  const fresh = await ctx.agentLoop.create(sessionId("nova-reenabled"), { provider: "nova-mock", model: "probe" }, { cwd: workspace });
  assert.equal(fresh.inbox.nextStep.filter((m) => JSON.stringify(m).includes("全局工作约定")).length, 1);
  await reenabled.dispose();
}
