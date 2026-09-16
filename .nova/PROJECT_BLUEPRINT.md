# Nova Forge — 项目蓝图

## 1. 项目定位

Nova Forge 是面向 Codex 与 Claude Code 的低干扰开发辅助 SOP。它在人工要求时帮助用户澄清整体业务需求、维护共享架构、直接完成开发、执行 Review 或创建本地提交；它不是需求生命周期管理、审计或自动化开发框架。

## 2. 技术栈

| 类别 | 选择 | 约束 |
|---|---|---|
| 技能 | Markdown 与 YAML frontmatter | 只保留 requirements、architecture、development、review、commit |
| Hook 与工具 | Node.js 22.5+ ESM、仅标准库 | 只在 SessionStart 注入静态规则 |
| 插件 | Codex 与 Claude Code 原生 manifest/marketplace | 共享同一份 skills、hooks 与规则 |
| 发布 | npm pack、GitHub Actions、SemVer 标签 | `package.json` 是版本单一来源 |

## 3. 代码结构

| 路径 | 职责 |
|---|---|
| `codex/AGENTS.global.md` | SessionStart 注入的最小路由与开发约定 |
| `skills/` | 五个按需加载的技能 |
| `hooks/` | 单一 SessionStart Hook |
| `.codex-plugin/`、`.claude-plugin/`、`.agents/plugins/` | 双宿主插件与 marketplace 清单 |
| `scripts/`、`tests/` | 本地安装、结构、打包与发布验证 |
| `.nova/design/` | 保留的设计文档；禁止主动扫描 |
| `.nova/architecture/` | 蓝图精确引用的必要共享架构文档 |

## 4. 模块职责

| 模块 | 职责 | 依赖边界 |
|---|---|---|
| Requirements | 仅按人工指令澄清、查看、新增、修改或删除整体业务需求 | 不主动读取项目需求，不维护开发状态，不转入其他技能 |
| Architecture | 初始化蓝图，或按人工指令修改共享架构 | 不实现普通功能，不扫描设计目录，不提交 |
| Development | 承接全部具体开发、必要澄清和测试 | 只读蓝图精确链接的上下文，不自动 Review 或提交 |
| Review | 人工触发的独立审查与修复，初审和复审总计最多三次结论 | 不维护持久状态，不扩展审查范围，不提交 |
| Commit | 仅在人工明确要求时精确创建本地 Conventional Commit | 不改代码、不测试、不 Review、不执行远程操作 |
| Hook | 注入全局开发约定 | 不保存状态，不处理其他生命周期事件 |
| Distribution | 双宿主安装、检查与标签发布 | 不定义开发流程语义 |

## 5. 公共约束

- 默认路径是“Development 理解与调查 → 必要澄清 → 实现 → 测试 → 按需继续修改”；用户明确要求后才由 Commit 创建本地提交。
- 需求只描述整体业务如何运转，由 Requirements 按人工指令独立维护；不建立需求块、状态、版本、实现依据或与其他技能的结构化关联。
- Architecture、Development、Review 与 Commit 不主动发现、读取、索引、校验或同步需求文档；用户本次明确提供的需求内容或精确路径除外。
- 新增、删除项目级技能或改变插件对外能力集合、技能职责属于 Architecture；Architecture 先更新共享边界，Development 只实现已经确认的边界，不直接修改蓝图架构事实。
- 设计只在用户明确要求时创建；AI 不得扫描 `.nova/design/`，只能读取本蓝图针对当前待办的精确链接。
- 完成报告由提示词约束，不通过程序或 Schema 校验。
- Review、Commit、push、发布和远程写操作都不会由普通开发自动触发。

## 6. 开发导航

| 开发触发条件 | 名称 | 类别 | 精确入口 | 复用或遵循边界 | 验证入口 |
|---|---|---|---|---|---|
| 修改 Codex/Claude Code 插件结构、manifest 或宿主差异 | 双宿主插件边界 | 详细共享契约 | [双宿主插件边界](architecture/foundation/dual-host-plugin.md)、`.codex-plugin/`、`.claude-plugin/` | 两个宿主共享同一份 skills、hooks 与规则，不复制流程语义 | `scripts/validate-plugin.mjs`、`tests/plugin-structure.test.mjs` |
| 修改 SessionStart 规则注入或 Hook 失败语义 | 双宿主插件边界 | 详细共享契约 | [双宿主插件边界](architecture/foundation/dual-host-plugin.md)、`hooks/run.mjs` | 只处理四个 SessionStart 来源；无效输入或规则不可读时受控 fail open | `tests/hook-adapter.test.mjs` |
| 修改开发安装、快照、包内容或双宿主分发 | 双宿主插件边界 | 详细共享契约 | [双宿主插件边界](architecture/foundation/dual-host-plugin.md)、`scripts/codex-dev-plugin-lib.mjs`、`scripts/check-package.mjs` | 不引入常驻服务或项目状态，开发快照与发布包必须包含完整权威资源 | `tests/codex-dev-plugin.test.mjs`、`scripts/check-package.mjs` |

## 7. 待开发工作

当前无待开发工作。
