import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { pluginRoot } from "./helpers.mjs";

const readJson = (relative) =>
  JSON.parse(fs.readFileSync(path.join(pluginRoot, relative), "utf8"));
const read = (relative) => fs.readFileSync(path.join(pluginRoot, relative), "utf8");

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

test("plugin exposes exactly four skills, one hook event, and no MCP", () => {
  const expectedSkills = ["nova-architecture", "nova-commit", "nova-development", "nova-review"];
  const actualSkills = fs
    .readdirSync(path.join(pluginRoot, "skills"), { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  assert.deepEqual(actualSkills, expectedSkills);
  for (const name of expectedSkills) {
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

test("global rules are a compact router rather than duplicated skill SOPs", () => {
  const rules = read("codex/AGENTS.global.md");
  for (const phrase of [
    "任何代码、配置或测试",
    "只有用户明确要求 Review",
    "只有用户明确要求创建本地提交",
    "不主动扫描、枚举、通配匹配或索引",
    "直接检查固定路径",
    "Architecture、Development 与 Review 不得创建提交",
    "只能消费进入技能前已有且有效的验证证据",
    "不得自行调用其他技能制造证据后继续提交",
    "蓝图“开发导航”是唯一发现入口",
  ]) {
    assert.equal(rules.includes(phrase), true, `missing global boundary: ${phrase}`);
  }
  assert.doesNotMatch(rules, /行为准则（强制）|Context-mode 可选路由|显式思考度/);
  assert.doesNotMatch(rules, /type\(scope\)|BREAKING CHANGE:|`feat`|`fix`|all\/misc\/core/);
  assert.doesNotMatch(rules, /默认快速开发|implementation-sop|五至七个执行项/);
});

test("architecture and development share one complete clarification SOP", () => {
  const architecture = read("skills/nova-architecture/SKILL.md");
  const development = read("skills/nova-development/SKILL.md");
  const conversation = read("skills/nova-development/references/conversation-sop.md");
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

test("architecture keeps its full contract in one skill and leaves changes uncommitted", () => {
  const architecture = read("skills/nova-architecture/SKILL.md");
  const blueprint = read("skills/nova-architecture/assets/PROJECT_BLUEPRINT.template.md");
  for (const phrase of [
    "OpenAPI 3.0.x/3.1.x",
    "AsyncAPI 2.x/3.x",
    "必须与契约的 `info.version` 一致",
    "开发触发条件",
    "维护多人长期并行开发共同遵守的主体技术架构",
    "架构决定与蓝图影响闭包",
    "七章完整有序",
    "结果保持未提交",
    "简单示例",
  ]) {
    assert.equal(architecture.includes(phrase), true, `missing architecture contract: ${phrase}`);
  }
  assert.equal(
    fs.existsSync(path.join(pluginRoot, "skills/nova-architecture/references/architecture-standard.md")),
    false,
  );
  assert.match(blueprint, /## 6\. 开发导航/);
  assert.match(blueprint, /## 7\. 待开发工作/);
  assert.ok(
    blueprint.indexOf("## 6. 开发导航") < blueprint.indexOf("## 7. 待开发工作"),
    "development navigation must precede pending work",
  );
  assert.match(blueprint, /开发触发条件 \| 名称 \| 类别 \| 精确入口 \| 复用或遵循边界 \| 验证入口/);
  assert.match(blueprint, /开发触发条件 \| 待开发内容 \| 交付结果 \| 设计入口/);
  assert.match(blueprint, /没有条目时删除表格并写“当前无待开发工作”/);
  assert.equal(
    fs.existsSync(
      path.join(pluginRoot, "skills/nova-architecture/assets/SHARED_CAPABILITIES.template.md"),
    ),
    false,
  );
  assert.match(architecture, /旧蓝图缺少“开发导航”.*\.nova\/SHARED_CAPABILITIES\.md/);
  assert.doesNotMatch(architecture, /创建 Conventional Commit|type\(scope\)/);
});

test("development owns all implementation constraints in one skill without committing", () => {
  const development = read("skills/nova-development/SKILL.md");
  for (const phrase of [
    "所有具体功能、局部调整、缺陷恢复和维护",
    "接口契约",
    "核心不变量",
    "失败语义",
    "测试与证据复用",
    "第六章“开发导航”的触发条件",
    "命中 / 不命中 / 未知",
    "不得以“当前没有第二个消费者”",
    "不得为此新增目录扫描、MCP、外部研究或独立技能调用",
    "涉及持久化时从最终生效配置解析存储位置",
    "一个准备批次",
    "一个失败即停的验证批次",
    "不暂存、不提交",
    "简单示例",
  ]) {
    assert.equal(development.includes(phrase), true, `missing development contract: ${phrase}`);
  }
  assert.equal(
    fs.existsSync(path.join(pluginRoot, "skills/nova-development/references/implementation-sop.md")),
    false,
  );
  assert.match(development, /固定旧入口 `\.nova\/SHARED_CAPABILITIES\.md`/);
  assert.doesNotMatch(development, /Development 更新导航/);
  assert.doesNotMatch(development, /^## Plan mode$/m);
  assert.doesNotMatch(development, /提交首行|提交批次|五至七个执行项|本地提交 hash/);
});

test("review keeps accumulated rules in one skill and never commits", () => {
  const review = read("skills/nova-review/SKILL.md");
  for (const phrase of [
    "显式 `reasoning_effort`",
    "默认与主代理当前思考度一致",
    "七维检查清单",
    "Observation-Defer",
    "followup_task",
    "初审 + 两次复审",
    "第 3 轮仍 REJECT",
    "等待超时只表示等待窗口结束",
    "复审通过后仍保持未提交",
  ]) {
    assert.equal(review.includes(phrase), true, `missing review rule: ${phrase}`);
  }
  assert.equal(
    fs.existsSync(path.join(pluginRoot, "skills/nova-review/references/review-sop.md")),
    false,
  );
  assert.doesNotMatch(
    review,
    /创建 Conventional Commit|创建一个普通.*提交|git commit|closure commit|closure transaction/,
  );
});

test("commit is the sole owner of local commit behavior", () => {
  const commit = read("skills/nova-commit/SKILL.md");
  for (const phrase of [
    "只有用户明确",
    "type(scope): 中文结果摘要",
    "| `feat` |",
    "| `fix` |",
    "| `refactor` |",
    "| `perf` |",
    "小写 kebab-case",
    "BREAKING CHANGE:",
    "git diff --cached --check",
    "禁止 `git add .`",
    "不得自行测试、修复或放宽门禁",
    "进入本技能之前已经存在",
    "当前 Commit 调用立即结束",
    "不得自动调用 `nova-development`",
    "新的明确 Commit 请求",
    "候选提交内容标识",
    "最终 staged 内容",
    "即使路径集合不变",
    "不添加工作项、Review、审计或其他流程 trailers",
    "宿主自身的提交归属信息服从宿主设置",
  ]) {
    assert.equal(commit.includes(phrase), true, `missing commit rule: ${phrase}`);
  }
  assert.match(commit, /不得 amend/);
  assert.match(commit, /不得修改代码或文档、运行测试、启动 Review/);
  assert.doesNotMatch(commit, /返回 Development/);
});

test("obsolete workflow identifiers and report validators stay removed", () => {
  const controls = [
    "codex/AGENTS.global.md",
    "skills/nova-architecture/SKILL.md",
    "skills/nova-development/SKILL.md",
    "skills/nova-review/SKILL.md",
    "skills/nova-commit/SKILL.md",
  ].map(read).join("\n");
  assert.doesNotMatch(controls, /FEAT-|FIX-|PATCH-|MAINT-|Work-Item:|Review-Policy:|Nova-Schema:/);
  assert.doesNotMatch(controls, /validate-report|report-template|Schema 校验器/);
  assert.equal(fs.existsSync(path.join(pluginRoot, "skills/nova-commit/references")), false);
});
