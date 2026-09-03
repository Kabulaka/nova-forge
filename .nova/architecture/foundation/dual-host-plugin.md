# Nova Forge 双宿主插件工程骨架契约

> 工程骨架契约版本：1

## 1. 技术与运行

| 语言 | 框架 | 运行形态 | 持久化 | 缓存 | 消息 | 鉴权 | 部署 |
|------|------|----------|--------|------|------|------|------|
| Node.js 22.5+、ESM、仅标准库 | Codex 与 Claude Code 原生插件、生命周期 Hook、stdio MCP | 双宿主薄适配器调用同一状态核心；不自动安装 Node.js 或 Bun | 宿主私有本机状态目录中的原子 JSON 检查点 | 只缓存当前会话最近有效代及其上一有效备份 | 不使用远程消息系统 | 由宿主插件启用与信任边界控制 | GitHub 仓库 marketplace；人工 `vX.Y.Z` 标签发布 |

## 2. 目录与依赖

| 代码区域 | 职责 | 允许依赖 | 禁止依赖 |
|----------|------|----------|----------|
| `skills/nova-*/` | 五个 Nova 技能的唯一权威源码 | 各技能显式路由的 `references/`、`assets/`、`scripts/` | 根目录第二份技能源码或安装目录实体副本 |
| `codex/AGENTS.global.md` | 双宿主静态治理规则的权威载荷及兼容安装源 | 项目规则与已确认全局契约 | 会话检查点、秘密、宿主专属可变状态 |
| `.codex-plugin/plugin.json`、`.claude-plugin/plugin.json` | 分别声明 Codex 与 Claude Code 插件身份、同一版本及组件入口 | `package.json` 的版本与插件根相对路径 | 各自维护不一致的规则或技能副本 |
| `.agents/plugins/marketplace.json`、`.claude-plugin/marketplace.json` | 提供两个宿主可安装的 GitHub 仓库 marketplace 入口 | 同一插件根、发布版本与展示元数据 | 官方公共目录、主分支未标记版本自动发布 |
| `hooks/` | 声明宿主事件并把输入、阻断和上下文输出映射到共享运行时 | `runtime/adapters/` 与宿主提供的会话 ID、事件来源和插件根 | 从 transcript 或压缩摘要推断正式决定 |
| `runtime/adapters/` | Codex、Claude Code 薄适配器及路径解析 | `runtime/core/`、宿主事件 JSON 和注入根路径 | 在适配器中复制状态机、持久化或业务规则 |
| `runtime/core/` | 检查点 schema、校验、原子读写、代际、校验和、TTL 与恢复胶囊 | Node.js 22.5+ 标准库与注入的状态根 | 网络、数据库、原生扩展、插件缓存目录持久化 |
| `runtime/mcp/` | 暴露最小的结构化检查点写入和查询工具 | `runtime/core/` | 接受无 authority 标记的自由文本作为正式状态 |
| `compat/` | Codex IDE、旧版宿主和故障恢复的软链接安装、检查与回滚 | 工作区权威文件及显式目标路径 | 覆盖普通文件、真实目录或成为插件宿主默认入口 |
| `.github/workflows/` | 三平台 CI、版本一致性检查、打包及人工标签发布 | Ubuntu、macOS、Windows；`package.json` SemVer | 主分支自动发布、自动创建版本标签或写官方目录 |

### 2.1 宿主生命周期映射

| 语义事件 | Codex | Claude Code | 共享行为 |
|----------|-------|-------------|----------|
| 会话启动或恢复 | `SessionStart` 的 `startup`、`resume` | `SessionStart` 的 `startup`、`resume` | 加载静态治理规则；仅 `resume` 查询同宿主同会话检查点并注入有界恢复胶囊 |
| 压缩前 | `PreCompact` 的 `manual`、`auto` | `PreCompact` 的 `manual`、`auto` | 校验最近结构化检查点；没有有效检查点时返回宿主支持的阻断结果并显式报错 |
| 压缩后续接 | `SessionStart` 的 `compact` | `SessionStart` 的 `compact` | 在下一次模型请求前注入静态规则标识、最近有效检查点和下一动作 |
| 压缩后核验 | `PostCompact` | `PostCompact` | 记录成功事件并核对会话代际；不把宿主生成的压缩摘要提升为权威状态 |
| 权威状态变化 | AI 调用插件 MCP 工具 | AI 调用插件 MCP 工具 | 以明确字段和 authority 类型创建新代检查点，用户无需手工保存 |

### 2.2 版本与发布

| 对象 | 唯一规则 | 验证 |
|------|----------|------|
| 版本权威 | `package.json.version` 是 SemVer 单一来源；双 manifest、双 marketplace 和发布产物必须与其一致 | 版本同步脚本及 CI 负例 |
| 主分支 | pull request 与主分支只执行结构、单元、打包和三平台兼容校验 | GitHub Actions 触发条件检查 |
| 正式发布 | 维护者人工创建与 `package.json.version` 一致的 `vX.Y.Z` 标签后，Action 才构建不可变归档、校验内容并创建 GitHub Release | 标签/版本失配失败、产物清单及校验和 |
| 宿主验收 | 发布候选必须在 Codex 与 Claude Code 的受支持版本中验证安装、启用、检查点、手动/自动压缩、恢复、禁用和卸载 | 两宿主 E2E 证据；未执行不得宣称恢复生效 |
