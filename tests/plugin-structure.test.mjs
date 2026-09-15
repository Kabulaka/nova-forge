import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { pluginRoot } from "./helpers.mjs";

const readJson = (relative) =>
  JSON.parse(fs.readFileSync(path.join(pluginRoot, relative), "utf8"));

test("marketplaces use host-native versioned sources", () => {
  const version = readJson("package.json").version;
  assert.deepEqual(readJson(".agents/plugins/marketplace.json").plugins[0].source, {
    source: "url",
    url: "https://github.com/Kabulaka/nova-forge.git",
    ref: `v${version}`,
  });
  const claude = readJson(".claude-plugin/marketplace.json");
  assert.equal(claude.plugins[0].source, "./");
  assert.equal(claude.plugins[0].version, version);
});

test("plugin exposes exactly three skills, one hook event, and no MCP", () => {
  for (const name of ["nova-architecture", "nova-development", "nova-review"]) {
    assert.equal(fs.existsSync(path.join(pluginRoot, "skills", name, "SKILL.md")), true);
  }
  for (const name of ["nova-requirements", "nova-doctor"]) {
    assert.equal(fs.existsSync(path.join(pluginRoot, "skills", name)), false);
  }
  const hooks = readJson("hooks/hooks.json");
  assert.deepEqual(Object.keys(hooks.hooks), ["SessionStart"]);
  assert.equal(hooks.hooks.SessionStart[0].matcher, "startup|resume|clear|compact");
  assert.equal(fs.existsSync(path.join(pluginRoot, ".mcp.json")), false);
  assert.equal(fs.existsSync(path.join(pluginRoot, "runtime")), false);
  assert.equal(Object.hasOwn(readJson(".codex-plugin/plugin.json"), "mcpServers"), false);
  assert.equal(Object.hasOwn(readJson(".claude-plugin/plugin.json"), "mcpServers"), false);
});

test("global rules preserve core governance and low-overhead routing", () => {
  const rules = fs.readFileSync(path.join(pluginRoot, "codex", "AGENTS.global.md"), "utf8");
  assert.match(rules, /行为准则（强制）/);
  assert.match(rules, /技能控制文档加载/);
  assert.match(rules, /上下文压缩与续接/);
  assert.match(rules, /蓝图存在后，只有用户主动调用/);
  assert.match(rules, /不主动扫描、枚举、通配匹配或索引/);
  assert.match(rules, /只有用户明确要求 Review/);
  assert.match(rules, /显式思考度/);
  assert.match(rules, /type\(scope\): 中文结果摘要/);
  for (const type of ["feat", "fix", "refactor", "perf", "test", "docs", "build", "ci", "chore", "revert"]) {
    assert.equal(rules.includes("`" + type + "`"), true, `missing commit type: ${type}`);
  }
  assert.match(rules, /all\/misc\/core/);
});

test("architecture and development share one complete clarification SOP", () => {
  const architecture = fs.readFileSync(
    path.join(pluginRoot, "skills", "nova-architecture", "SKILL.md"),
    "utf8",
  );
  const development = fs.readFileSync(
    path.join(pluginRoot, "skills", "nova-development", "SKILL.md"),
    "utf8",
  );
  const conversation = fs.readFileSync(
    path.join(
      pluginRoot,
      "skills",
      "nova-development",
      "references",
      "conversation-sop.md",
    ),
    "utf8",
  );
  assert.match(architecture, /\.\.\/nova-development\/references\/conversation-sop\.md/);
  assert.match(development, /references\/conversation-sop\.md/);
  for (const phrase of [
    "先研究，再决定是否提问",
    "单问题闸门",
    "委托只能免除形式性问题",
    "0/1 answered",
    "输出净化",
  ]) {
    assert.equal(conversation.includes(phrase), true, `missing clarification rule: ${phrase}`);
  }
});

test("review preserves the accumulated independent-review rules", () => {
  const skill = fs.readFileSync(
    path.join(pluginRoot, "skills", "nova-review", "SKILL.md"),
    "utf8",
  );
  const review = fs.readFileSync(
    path.join(pluginRoot, "skills", "nova-review", "references", "review-sop.md"),
    "utf8",
  );
  for (const phrase of [
    "显式 `reasoning_effort`",
    "默认与主代理当前思考度一致",
    "七个维度",
    "Observation-Defer",
    "followup_task",
    "初审 + 两次复审",
    "第 3 轮仍 REJECT",
    "不得创建空提交",
  ]) {
    assert.equal(review.includes(phrase), true, `missing review rule: ${phrase}`);
  }
  assert.match(skill, /\.\.\/nova-development\/references\/conversation-sop\.md/);
  assert.doesNotMatch(review, /允许进入关闭|closure commit|closure transaction/);
});

test("architecture preserves shared capability and protocol contracts", () => {
  const standard = fs.readFileSync(
    path.join(pluginRoot, "skills", "nova-architecture", "references", "architecture-standard.md"),
    "utf8",
  );
  const development = fs.readFileSync(
    path.join(pluginRoot, "skills", "nova-development", "SKILL.md"),
    "utf8",
  );
  for (const phrase of [
    "OpenAPI 3.0.x/3.1.x",
    "AsyncAPI 2.x/3.x",
    "必须与契约的 `info.version` 一致",
    ".nova/SHARED_CAPABILITIES.md",
    "不是架构索引",
  ]) {
    assert.equal(standard.includes(phrase), true, `missing architecture rule: ${phrase}`);
  }
  assert.match(development, /目录缺失或未命中不能直接断言不存在/);
});

test("development preserves Conventional Commit classification without Nova trailers", () => {
  const implementation = fs.readFileSync(
    path.join(
      pluginRoot,
      "skills",
      "nova-development",
      "references",
      "implementation-sop.md",
    ),
    "utf8",
  );
  for (const phrase of [
    "type(scope): 中文结果摘要",
    "| `feat` |",
    "| `fix` |",
    "| `refactor` |",
    "| `perf` |",
    "小写 kebab-case",
    "BREAKING CHANGE:",
  ]) {
    assert.equal(implementation.includes(phrase), true, `missing commit rule: ${phrase}`);
  }
  assert.match(implementation, /不添加 FEAT\/FIX\/MAINT 编号、Nova trailers/);
  assert.doesNotMatch(implementation, /Work-Item:|Review-Policy:|Nova-Schema:/);
});

test("explicit development uses one bounded fast path without weakening fallbacks", () => {
  const rules = fs.readFileSync(path.join(pluginRoot, "codex", "AGENTS.global.md"), "utf8");
  const development = fs.readFileSync(
    path.join(pluginRoot, "skills", "nova-development", "SKILL.md"),
    "utf8",
  );
  const implementation = fs.readFileSync(
    path.join(
      pluginRoot,
      "skills",
      "nova-development",
      "references",
      "implementation-sop.md",
    ),
    "utf8",
  );

  for (const phrase of [
    "明确开发快速路径",
    "资格在首次准备批次中一次判定",
    "完整加载实施 SOP",
    "验证批次",
    "提交批次",
    "五至七个执行项",
  ]) {
    assert.equal(
      rules.includes(phrase) || development.includes(phrase) || implementation.includes(phrase),
      true,
      `missing fast-path contract: ${phrase}`,
    );
  }

  for (const phrase of [
    "真实歧义使用共享澄清 SOP",
    "蓝图缺失或共享架构不足进入 Architecture",
    "用户明确要求时才进入设计、Plan mode、参考研究或 Review",
    "不得为了留在快速路径而推断用户决定",
  ]) {
    assert.equal(development.includes(phrase), true, `missing fast-path fallback: ${phrase}`);
  }

  assert.match(implementation, /不是正确性门禁/);
  assert.match(implementation, /不得为满足数量目标少读必要事实、跳过测试或隐瞒失败/);
  assert.doesNotMatch(development, /自动启动 Review|自动扫描.*\.nova\/design/);
});

test("clear single-scope development stays on the global path without loading a skill", () => {
  const readme = fs.readFileSync(path.join(pluginRoot, "README.md"), "utf8");
  const rules = fs.readFileSync(path.join(pluginRoot, "codex", "AGENTS.global.md"), "utf8");
  const development = fs.readFileSync(
    path.join(pluginRoot, "skills", "nova-development", "SKILL.md"),
    "utf8",
  );

  assert.match(rules, /请求明确、单一范围且不改变共享架构/);
  assert.match(rules, /直接检查固定路径.*PROJECT_BLUEPRINT\.md/);
  assert.match(rules, /禁止用.*rg --files.*代替存在性检查/);
  assert.match(rules, /不加载技能或实施 SOP/);
  assert.match(rules, /不加载 `nova-development` 或其实施 SOP/);
  assert.match(rules, /存在真实歧义、用户要求设计或沉淀待办/);
  assert.match(development, /明确单范围请求由全局快速路径直接处理/);
  assert.match(development, /不应自动加载本技能/);
  assert.match(readme, /明确单范围请求：直接描述需求/);
  assert.doesNotMatch(readme, /普通请求：调用.*nova-development/);
});
