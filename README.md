# Nova Forge

Nova Forge 是面向 Codex 和 Claude Code 的高效率开发辅助 SOP。它保留项目架构、证据先行的必要澄清、直接开发和严格人工 Review，不再运行需求访谈流水线、审计台账或会话状态框架。

## 核心技能

| 技能 | 何时使用 | 默认结果 |
|---|---|---|
| `nova-architecture` | 项目没有蓝图，或用户主动要求修改共享架构 | 创建或更新蓝图及必要架构文档 |
| `nova-development` | 普通功能、修复和维护 | 必要澄清、编码、测试、本地提交 |
| `nova-review` | 用户明确要求 Review | 独立审查、统一修复、复测复审 |

普通开发不会自动创建设计、启动 Review、push 或发布。只有影响当前交付并阻塞实现的真实歧义才会触发 Architecture 与 Development 共用的单问题澄清；Review 仍保留独立 reviewer、显式思考度、七维检查、问题分级、证据复用和最多三轮规则。

## 最小项目约定

- `.nova/PROJECT_BLUEPRINT.md` 是唯一固定项目文档。
- 蓝图缺失时由 `nova-architecture` 初始化；存在后，普通开发只读取和遵循，只有用户主动调用架构技能才能修改架构。
- `.nova/architecture/` 和 `.nova/design/` 都按需存在。
- AI 不得扫描 `.nova/design/`；只能读取蓝图为当前待办精确链接的设计。
- 完成的待办从蓝图删除，设计文档保留；不维护 Review 状态、审计或台账。

## 安装

需要 Node.js 22.5 或更高版本来运行 SessionStart Hook 和仓库工具。

### Codex

```bash
codex plugin marketplace add Kabulaka/nova-forge --ref v0.3.2
codex plugin add nova-forge@nova-forge
```

### Claude Code

```text
/plugin marketplace add Kabulaka/nova-forge
/plugin install nova-forge@nova-forge
```

插件只在 `SessionStart` 的 `startup`、`resume`、`clear` 和 `compact` 事件注入核心 `codex/AGENTS.global.md`。没有 MCP 服务、后台状态或其他生命周期 Hook。

## 本地开发安装

```bash
npm run codex:dev:install
npm run claude:dev:install
```

卸载：

```bash
npm run codex:dev:uninstall
npm run claude:dev:uninstall
```

可用绝对路径 `CODEX_HOME`、`CLAUDE_CONFIG_DIR` 和 `NOVA_HOME` 隔离本地开发安装；`NOVA_HOME` 在这里仅保存开发版 marketplace 快照，不保存会话或项目状态。

## 使用

- 普通请求：调用 `$nova-forge:nova-development`。
- 初始化蓝图或主动调整共享架构：调用 `$nova-forge:nova-architecture`。
- 人工审查指定 Git 范围：调用 `$nova-forge:nova-review`。

## 验证

```bash
npm run check
```

该命令检查版本同步、三技能结构、单 Hook 清单、发布工作流、测试和最终 npm 包内容。报告文本不参与代码校验。
