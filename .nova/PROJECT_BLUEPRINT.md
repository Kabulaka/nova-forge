# Nova Forge — 项目蓝图

## 1. 项目定位

Nova Forge 是面向 Codex 与 Claude Code 的低干扰开发辅助 SOP。它帮助开发者遵循项目架构、直接完成开发，并在人工要求时执行 Review；它不是需求管理、审计或自动化开发框架。

## 2. 技术栈

| 类别 | 选择 | 约束 |
|---|---|---|
| 技能 | Markdown 与 YAML frontmatter | 只保留 architecture、development、review、commit |
| Hook 与工具 | Node.js 22.5+ ESM、仅标准库 | 只在 SessionStart 注入静态规则 |
| 插件 | Codex 与 Claude Code 原生 manifest/marketplace | 共享同一份 skills、hooks 与规则 |
| 发布 | npm pack、GitHub Actions、SemVer 标签 | `package.json` 是版本单一来源 |

## 3. 代码结构

| 路径 | 职责 |
|---|---|
| `codex/AGENTS.global.md` | SessionStart 注入的最小路由与开发约定 |
| `skills/` | 四个按需加载的技能 |
| `hooks/` | 单一 SessionStart Hook |
| `.codex-plugin/`、`.claude-plugin/`、`.agents/plugins/` | 双宿主插件与 marketplace 清单 |
| `scripts/`、`tests/` | 本地安装、结构、打包与发布验证 |
| `.nova/design/` | 保留的设计文档；禁止主动扫描 |
| `.nova/architecture/` | 蓝图精确引用的必要共享架构文档 |

## 4. 模块职责

| 模块 | 职责 | 依赖边界 |
|---|---|---|
| Architecture | 初始化蓝图，或按人工指令修改共享架构 | 不实现普通功能，不扫描设计目录，不提交 |
| Development | 承接全部具体开发、必要澄清和测试 | 只读蓝图精确链接的上下文，不自动 Review 或提交 |
| Review | 人工触发的独立审查与修复，初审和复审总计最多三次结论 | 不维护持久状态，不扩展审查范围，不提交 |
| Commit | 仅在人工明确要求时精确创建本地 Conventional Commit | 不改代码、不测试、不 Review、不执行远程操作 |
| Hook | 注入全局开发约定 | 不保存状态，不处理其他生命周期事件 |
| Distribution | 双宿主安装、检查与标签发布 | 不定义开发流程语义 |

## 5. 公共约束

- 默认路径是“Development 理解与调查 → 必要澄清 → 实现 → 测试 → 按需继续修改”；用户明确要求后才由 Commit 创建本地提交。
- 不维护需求块、交付台账、审计、检查点、迁移或 Review 状态。
- 设计只在用户明确要求时创建；AI 不得扫描 `.nova/design/`，只能读取本蓝图针对当前待办的精确链接。
- 完成报告由提示词约束，不通过程序或 Schema 校验。
- Review、Commit、push、发布和远程写操作都不会由普通开发自动触发。

## 6. 待开发工作

当前无待开发工作。

## 7. 架构文档

- [双宿主插件边界](architecture/foundation/dual-host-plugin.md)
