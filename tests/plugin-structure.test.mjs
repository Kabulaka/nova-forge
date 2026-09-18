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

test("plugin exposes exactly five skills, one hook event, and no MCP", () => {
  const expectedSkills = [
    "nova-architecture",
    "nova-commit",
    "nova-development",
    "nova-requirements",
    "nova-review",
  ];
  const actualSkills = fs
    .readdirSync(path.join(pluginRoot, "skills"), { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  assert.deepEqual(actualSkills, expectedSkills);
  for (const name of expectedSkills) {
    assert.equal(fs.existsSync(path.join(pluginRoot, "skills", name, "SKILL.md")), true);
  }
  for (const name of ["nova-doctor"]) {
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
  const projectRules = read("AGENTS.md");
  for (const phrase of [
    "nova-requirements",
    "不得主动发现、读取、索引、校验或同步需求文档",
    "明确要求改变技术栈、运行形态、基础设施职责",
    "业务 API、业务 schema、DTO、数据库表、业务事件和端到端功能流程",
    "只有其中确实改变系统骨架的最小差量",
    "Architecture 只维护系统骨架",
    "Development 在当前任务实际交付并验证通用组件时",
    "Review 只在最终结论后登记符合准入的技术债务",
    "任何代码、配置或测试",
    "只有用户明确要求 Review",
    "只有用户明确要求创建本地提交",
    "不主动扫描、枚举、通配匹配或索引",
    "直接检查固定路径",
    "Architecture、Development 与 Review 不得创建提交",
    "只能消费进入技能前已有且有效的验证证据",
    "不得自行调用其他技能制造证据后继续提交",
    "蓝图“已实现可复用能力”是通用组件的唯一发现入口",
    "兼容旧标题“开发导航”",
    "每次新的用户请求均重新判断技能路由",
    "同一内聚任务再次命中同一技能",
    "项目根目录之外",
    "原生只读方式",
  ]) {
    assert.equal(rules.includes(phrase), true, `missing global boundary: ${phrase}`);
  }
  assert.match(projectRules, /系统骨架、已实现可复用能力和待开发工作同处一份文件/);
  assert.match(projectRules, /业务 schema、业务接口和端到端功能流程不得借“跨模块”或“共享”/);
  assert.doesNotMatch(rules, /行为准则（强制）|Context-mode 可选路由|显式思考度/);
  assert.doesNotMatch(rules, /type\(scope\)|BREAKING CHANGE:|`feat`|`fix`|all\/misc\/core/);
  assert.doesNotMatch(rules, /默认快速开发|implementation-sop|五至七个执行项/);
});

test("requirements remains a standalone manually requested business-outline skill", () => {
  const requirements = read("skills/nova-requirements/SKILL.md");
  const template = read("skills/nova-requirements/assets/PRODUCT_REQUIREMENTS.template.md");
  const example = read("skills/nova-requirements/references/examples/AI_GATEWAY_REQUIREMENTS.md");
  const metadata = read("skills/nova-requirements/agents/openai.yaml");

  for (const phrase of [
    "只有用户当前明确要求",
    "不主动扫描、发现、索引或校验项目中的需求文档",
    "共享澄清 SOP",
    "业务责任链",
    "不强制先选择 `MVP / 完整系统 / 自定义范围`",
    "不要求固定栏目全部得出结论",
    "精确状态名称和数量",
    "业务与实现的分界",
    "系统存在多条相对独立的业务主线",
    "单一主线、能力可直接从流程看出或分组只会重复流程时省略",
    "连续调整后续章节编号",
    "不得为了保留模板章节而制造能力分组",
    "不拆成编号化需求块",
    "不记录实现状态",
    "用户未指定目标文件时，需求文档默认保存到目标项目的 `.nova/PRODUCT_REQUIREMENTS.md`",
    "不得建议或自动启动后续架构、开发、Review 或提交",
  ]) {
    assert.equal(requirements.includes(phrase), true, `missing requirements boundary: ${phrase}`);
  }
  assert.match(requirements, /\.\.\/nova-development\/references\/conversation-sop\.md/);
  assert.doesNotMatch(requirements, /自动调用或转交.*nova-(architecture|development|review|commit)/);
  assert.doesNotMatch(requirements, /REQ-|待实现|开发中|已实现|Requirement-Ref/);
  assert.doesNotMatch(requirements, /disable-model-invocation/);
  assert.doesNotMatch(metadata, /allow_implicit_invocation|policy:/);
  assert.match(template, /## 3\. 业务能力与边界/);
  assert.match(template, /\| 业务能力 \| 负责的业务结果 \| 不负责的边界 \|/);
  assert.match(template, /## 4\. 业务如何运转/);
  assert.match(template, /以下章节和表格按实际业务保留/);
  assert.doesNotMatch(template, /需求索引|实现依据|技术栈|API|数据库/);
  assert.match(example, /# AI 模型网关 — 业务需求/);
  assert.match(example, /\| 上游与模型供给 \|/);
  assert.match(example, /\| 模型调用治理 \|/);
  assert.match(example, /\| 步骤 \| 参与者 \| 触发或输入 \| 业务行为 \| 业务结果 \|/);
  assert.match(example, /RPM、TPM 与并发/);
  assert.doesNotMatch(example, /Redis|令牌桶|滑动窗口|数据库表|\/v1\//);

  for (const relative of [
    "skills/nova-architecture/SKILL.md",
    "skills/nova-development/SKILL.md",
    "skills/nova-review/SKILL.md",
    "skills/nova-commit/SKILL.md",
  ]) {
    assert.doesNotMatch(read(relative), /nova-requirements/);
  }
});

test("requirements, architecture, and development share one complete clarification SOP", () => {
  const requirements = read("skills/nova-requirements/SKILL.md");
  const architecture = read("skills/nova-architecture/SKILL.md");
  const development = read("skills/nova-development/SKILL.md");
  const conversation = read("skills/nova-development/references/conversation-sop.md");
  assert.match(requirements, /\.\.\/nova-development\/references\/conversation-sop\.md/);
  assert.match(architecture, /\.\.\/nova-development\/references\/conversation-sop\.md/);
  assert.match(development, /references\/conversation-sop\.md/);
  assert.match(conversation, /Requirements 在用户明确要求需求澄清.*Architecture 与 Development/);
  assert.match(conversation, /不得为澄清而自行扫描蓝图、设计、代码或测试/);
  assert.match(conversation, /阻塞首次编辑/);
  assert.match(conversation, /即使仍可先写脚手架、局部代码或测试/);
  assert.match(conversation, /能够自洽说明系统如何运转的业务大纲/);
  assert.match(conversation, /共享 SOP 不提供固定覆盖矩阵/);
  assert.match(conversation, /Requirements 只有在用户明确要求参考研究时才取得外部证据/);
  assert.doesNotMatch(conversation, /澄清需要围绕当前范围检查：为什么需要/);
  assert.doesNotMatch(conversation, /无法从代码、配置、测试、蓝图/);
  assert.doesNotMatch(conversation, /从摘要和项目事实恢复/);
  assert.doesNotMatch(conversation, /可从项目查明/);
  assert.doesNotMatch(conversation, /沿直接关系检查功能、权限、数据、架构和验收/);
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

test("clarification and architecture gates distinguish the three observed behavior cases", () => {
  const rules = read("codex/AGENTS.global.md");
  const requirements = read("skills/nova-requirements/SKILL.md");
  const architecture = read("skills/nova-architecture/SKILL.md");
  const development = read("skills/nova-development/SKILL.md");
  const conversation = read("skills/nova-development/references/conversation-sop.md");

  // Clear implementation: research first, then proceed without a ceremonial question.
  assert.match(development, /请求和证据足够时不得形式性提问/);
  assert.match(development, /无阻塞时直接继续/);

  // User-visible ambiguity: every unresolved behavioral choice blocks the first edit.
  assert.match(development, /首次编辑前重新计算待确认差量/);
  assert.match(development, /符合这些条件的差量一律阻塞首次编辑/);
  assert.match(development, /不得以仍可先写脚手架、局部代码或测试为由继续/);

  // Only a system-skeleton change can stop Development; business contracts stay local.
  assert.match(architecture, /稳定服务及项目级模块的新增、删除、拆分、合并/);
  assert.match(architecture, /任一普通开发任务不能在局部实现中自行改变/);
  assert.match(architecture, /业务 API、OpenAPI 业务字段、DTO、schema 和数据库表/);
  assert.match(architecture, /不能单独构成架构准入/);
  assert.match(development, /当前需求是否必然改变：技术栈、运行\/部署形态、基础设施选型或介质职责/);
  assert.match(development, /业务 API、schema、DTO、数据库表、业务事件和端到端功能流程.*仍由 Development 直接处理/);
  assert.match(development, /不得由 Development 自行修改蓝图第一至第五章/);
  assert.doesNotMatch(architecture, /两个以上能够独立变化的项目内参与方/);
  assert.doesNotMatch(development, /两个以上能够独立变化的当前参与方/);

  // Explicit requirement clarification loads the SOP before discovering the first question.
  assert.match(requirements, /在判断第一个待确认差量或首次提问前完整读取/);
  assert.match(requirements, /成功完整读取且工具未明确截断后，本轮不得重复读取/);
  assert.match(rules, /Requirements 在用户明确要求需求澄清或创建、修改内容不足时使用/);
  assert.match(requirements, /不得等到已经发现歧义后才加载/);
  assert.match(requirements, /查看或删除不加载/);
  assert.match(requirements, /由谁触发、谁接手、责任如何转移/);
  assert.match(requirements, /只提供系统名称、业务领域或抽象目标/);
  assert.match(requirements, /第一问必须使用开放式文本询问现实中要解决的业务问题/);
  assert.match(requirements, /不得先生成结构化方案、产品模式或互斥选项/);
  assert.match(requirements, /不预先维护固定问题队列/);
  assert.match(requirements, /剩余未知只影响实现或低风险细节时，立即停止提问/);
  assert.doesNotMatch(requirements, /只有出现真实业务歧义时完整读取/);

  // A host capability failure means the question was never shown and must fall back immediately.
  assert.match(conversation, /unsupported.*not supported.*unavailable.*能力错误/);
  assert.match(conversation, /当前轮立即改用普通文本/);
  assert.match(conversation, /完整呈现同一问题、原选项及其影响/);
  assert.match(conversation, /不得称为“用户未回答”或“未收到选择”/);
  assert.match(conversation, /工具名称出现在本轮列表中不等于当前交互通道可用/);
  assert.match(conversation, /`codex exec`、批处理.*非交互通道必须直接使用普通文本/);
  assert.match(conversation, /明确报告超时、取消或未提交，并同时确认问题已成功呈现/);
  assert.match(conversation, /只返回空答案或 `0\/1 answered`、没有成功呈现标记/);
});

test("architecture owns only the lightweight system skeleton", () => {
  const architecture = read("skills/nova-architecture/SKILL.md");
  const blueprint = read("skills/nova-architecture/assets/PROJECT_BLUEPRINT.template.md");
  for (const phrase of [
    "轻量系统骨架",
    "架构不是“重要设计”的集合",
    "只有系统骨架属于 Architecture",
    "不创建 ADR、索引、审计、状态机",
    "系统骨架准入",
    "只有下列封闭集合",
    "业务 API、OpenAPI 业务字段、DTO、schema 和数据库表",
    "业务事件及其载荷",
    "端到端工作流",
    "不能单独构成架构准入",
    "保存用户提交或确认的权威事实、当前有效结果",
    "缓存丢失、过期或清空不得改变业务结果",
    "日志与指标",
    "Architecture 维护第一至第五章",
    "第六章由 Development",
    "第七章由 Architecture、Development 和 Review",
    "不创建新的详细架构文档",
    "潜在复用、单一业务工作流、业务 API/schema/事件",
    "旧蓝图标题“开发导航”在读取时保持兼容",
    "用户明确要求升级、迁移或整体精简",
    "旧待开发工作原样保留",
    "设计入口为“无”表示尚未沉淀设计",
    "不自动调用或制造额外技能往返",
    "业务设计差量不由 Architecture 澄清",
    "用户已经批准覆盖同一范围的具体方案时不重复确认",
    "结果保持未提交",
  ]) {
    assert.equal(architecture.includes(phrase), true, `missing architecture contract: ${phrase}`);
  }
  assert.equal(
    fs.existsSync(path.join(pluginRoot, "skills/nova-architecture/references/architecture-standard.md")),
    false,
  );
  assert.match(blueprint, /## 2\. 技术栈与系统形态/);
  assert.match(blueprint, /## 4\. 服务与模块骨架/);
  assert.match(blueprint, /## 5\. 系统基础边界/);
  assert.match(blueprint, /## 6\. 已实现可复用能力/);
  assert.match(blueprint, /## 7\. 待开发工作/);
  assert.ok(
    blueprint.indexOf("## 6. 已实现可复用能力") < blueprint.indexOf("## 7. 待开发工作"),
    "reusable capabilities must precede pending work",
  );
  assert.match(blueprint, /复用时机 \| 能力 \| 实现入口 \| 复用边界 \| 验证入口/);
  assert.match(blueprint, /何时处理 \| 待开发工作 \| 交付结果 \| 设计入口/);
  assert.match(blueprint, /不能只写“业务状态”或“临时状态”/);
  assert.match(blueprint, /缓存丢失不得改变业务结果/);
  assert.match(blueprint, /单一业务工作流.*不得登记/);
  assert.match(blueprint, /“无”表示尚未沉淀设计/);
  assert.match(blueprint, /没有条目时删除表格并写“当前无待开发工作”/);
  assert.doesNotMatch(blueprint, /详细共享契约|OpenAPI 3\.0|AsyncAPI|info\.version/);
  assert.equal(
    fs.existsSync(
      path.join(pluginRoot, "skills/nova-architecture/assets/SHARED_CAPABILITIES.template.md"),
    ),
    false,
  );
  assert.match(architecture, /才检查固定旧入口 `\.nova\/SHARED_CAPABILITIES\.md`/);
  assert.doesNotMatch(architecture, /创建 Conventional Commit|type\(scope\)/);
});

test("development keeps business work local and synchronizes only proven reusable capabilities", () => {
  const development = read("skills/nova-development/SKILL.md");
  for (const phrase of [
    "所有具体功能、局部调整、缺陷恢复和维护",
    "接口契约",
    "核心不变量",
    "失败语义",
    "测试与证据复用",
    "兼容新标题“已实现可复用能力”和旧标题“开发导航”",
    "普通 Development 不因旧标题停止或强制迁移",
    "业务 API、schema、DTO、数据库表、业务事件和端到端功能流程",
    "首次编辑前，使用已经读取的蓝图和本次定向研究结果完成一次封闭判断",
    "跨模块、公共、共享、版本化、多个消费者或可能不兼容",
    "不得在结论已由蓝图确定后读取设计以补充说明",
    "Development 不修改蓝图第一至第五章",
    "蓝图同步",
    "不得为此扫描仓库、调用 Architecture、增加用户确认轮次或运行额外全量测试",
    "离开当前单一业务工作流后仍能被无关功能直接复用",
    "证据不明确时默认不登记，也不询问用户",
    "设计入口写“无”",
    "无设计链接表示尚未持久化设计",
    "必要事实未知",
    "不得为此新增目录扫描、MCP、外部研究或独立技能调用",
    "涉及持久化时从最终生效配置解析存储位置",
    "一个准备批次",
    "一个模型工具回合",
    "事实未变时不重读技能、蓝图、基线或任务事实",
    "一个失败即停的验证批次",
    "批次指一次模型往返，不强求单个 shell 命令",
    "同任务续改",
    "原任务范围",
    "不重建任务基线",
    "只更新本轮差量",
    "从最早受影响环节恢复正常 Development",
    "不暂存、不提交",
    "简单示例",
  ]) {
    assert.equal(development.includes(phrase), true, `missing development contract: ${phrase}`);
  }
  assert.equal(
    fs.existsSync(path.join(pluginRoot, "skills/nova-development/references/implementation-sop.md")),
    false,
  );
  assert.match(development, /普通 Development 不检查 `\.nova\/SHARED_CAPABILITIES\.md`/);
  assert.doesNotMatch(development, /Development 更新导航|两个以上能够独立变化的当前参与方/);
  assert.doesNotMatch(development, /命中或未知都必须在编码前中断/);
  assert.doesNotMatch(development, /潜在复用场景.*必须.*中断/);
  assert.doesNotMatch(development, /^## Plan mode$/m);
  assert.doesNotMatch(development, /提交首行|提交批次|五至七个执行项|本地提交 hash/);
  assert.equal(
    (development.match(/当前需求是否必然改变：技术栈、运行\/部署形态、基础设施选型或介质职责/g) ?? [])
      .length,
    1,
  );
  assert.match(
    development,
    /清空后、形成整份摘要前，完整读取.*design-document-standard\.md/,
  );
  assert.match(development, /只登记待开发工作时不读取两者/);
  assert.match(development, /只有目标性描述时.*仍存在多种会改变结果的合理语义.*属于阻塞差量/);
  assert.match(development, /不得用常见做法或 AI 自选默认值补齐整份设计/);
  assert.match(development, /不得在该差量确认前读取设计规范或模板/);
});

test("external reference research fails closed on missing transport or evidence", () => {
  const research = read("skills/nova-development/references/reference-research-sop.md");
  for (const phrase of [
    "只有实际创建并到达完成状态、且返回非空可定位证据的代理才算独立研究",
    "接收者为空",
    "响应正文非空",
    "进程退出码为零本身不证明证据有效",
    "pipefail",
    "不得让末端筛选、格式化或截断命令的成功掩盖",
    "映射到实际取得的证据",
    "未验证标准兼容性",
    "不声称已经独立研究、交叉核对或验证兼容性",
  ]) {
    assert.equal(research.includes(phrase), true, `missing external evidence gate: ${phrase}`);
  }
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
    "技术债务登记",
    "不影响本次任务的正确性、数据安全或必要验收",
    "不能以债务逃避修复",
    "不是所有合法 Observation-Defer 都是技术债务",
    "设计入口写“无”",
    "不触发新的 Reviewer 轮次或业务测试",
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
  assert.doesNotMatch(review, /Observation-Defer.*不自动扩展当前任务或创建待办/);
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
    "skills/nova-requirements/SKILL.md",
    "skills/nova-architecture/SKILL.md",
    "skills/nova-development/SKILL.md",
    "skills/nova-review/SKILL.md",
    "skills/nova-commit/SKILL.md",
  ].map(read).join("\n");
  assert.doesNotMatch(controls, /FEAT-|FIX-|PATCH-|MAINT-|Work-Item:|Review-Policy:|Nova-Schema:/);
  assert.doesNotMatch(controls, /validate-report|report-template|Schema 校验器/);
  assert.equal(fs.existsSync(path.join(pluginRoot, "skills/nova-commit/references")), false);
});
