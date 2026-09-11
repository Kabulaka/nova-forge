# Nova Forge 双宿主插件工程骨架契约

> 工程骨架契约版本：2

## 1. 技术与运行

| 语言 | 框架 | 运行形态 | 持久化 | 缓存 | 消息 | 鉴权 | 部署 |
|------|------|----------|--------|------|------|------|------|
| Node.js 22.5+、ESM、仅标准库 | Codex 与 Claude Code 原生插件、生命周期 Hook、stdio MCP | 双宿主薄适配器调用同一状态核心；不自动安装 Node.js 或 Bun | 用户主目录下稳定 Nova 私有根中的原子 JSON 检查点；默认 `~/.nova`，可由绝对路径 `NOVA_HOME` 覆盖 | 只缓存当前会话最近有效代及其上一有效备份 | 不使用远程消息系统 | 由宿主插件启用与信任边界控制，状态根可写性单独验证 | GitHub 仓库 marketplace；人工 `vX.Y.Z` 标签发布 |

## 2. 目录与依赖

| 代码区域 | 职责 | 允许依赖 | 禁止依赖 |
|----------|------|----------|----------|
| `skills/nova-*/` | 五个 Nova 技能的唯一权威源码 | 各技能显式路由的 `references/`、`assets/`、`scripts/` | 根目录第二份技能源码或安装目录实体副本 |
| `codex/AGENTS.global.md` | 双宿主静态治理规则的权威载荷及兼容安装源 | 项目规则与已确认全局契约 | 会话检查点、秘密、宿主专属可变状态 |
| `.codex-plugin/plugin.json`、`.claude-plugin/plugin.json` | 分别声明 Codex 与 Claude Code 插件身份、同一版本及组件入口 | `package.json` 的版本与插件根相对路径 | 各自维护不一致的规则或技能副本 |
| `.agents/plugins/marketplace.json`、`.claude-plugin/marketplace.json` | 提供两个宿主可安装的 GitHub 仓库 marketplace 入口 | 同一插件根、发布版本与展示元数据 | 官方公共目录、主分支未标记版本自动发布 |
| `hooks/` | 声明宿主事件并把输入、阻断和上下文输出映射到共享运行时 | `runtime/adapters/` 与宿主提供的会话 ID、事件来源和插件根 | 从 transcript 或压缩摘要推断正式决定 |
| `runtime/adapters/` | Codex、Claude Code 薄适配器、路径解析及当前会话可信作用域建立 | `runtime/core/`、宿主事件 JSON 和注入根路径 | 在适配器中复制状态机、持久化或业务规则，或允许模型选择 host/sessionId |
| `runtime/core/` | 状态根解析、幂等初始化、旧状态迁移，以及检查点 schema、校验、原子读写、代际、校验和、TTL 与恢复胶囊 | Node.js 22.5+ 标准库、默认用户私有根或绝对 `NOVA_HOME` | 网络、数据库、原生扩展、插件安装/缓存目录或项目工作区持久化 |
| `runtime/mcp/` | 暴露最小的结构化检查点写入和查询工具；进程绑定宿主适配器建立的当前会话能力，工具参数不暴露 host/sessionId | `runtime/core/` 与只读可信作用域 | 接受无 authority 标记的自由文本作为正式状态，或按调用参数切换会话作用域 |
| `compat/` | Codex IDE、旧版宿主和故障恢复的软链接安装、互斥迁移、检查与回滚 | 工作区权威文件及显式目标路径 | 覆盖普通文件、真实目录、成为插件宿主默认入口或与已启用插件形成重复发现 |
| `.github/workflows/` | 三平台 CI、版本一致性检查、打包及人工标签发布 | Ubuntu、macOS、Windows；`package.json` SemVer | 主分支自动发布、自动创建版本标签或写官方目录 |

### 2.1 状态根、初始化与迁移

| 对象 | 共享契约 | 验证 |
|------|----------|------|
| 根路径解析 | 未显式配置时以当前用户主目录下 `.nova` 为 `NOVA_HOME`；显式 `NOVA_HOME` 必须是规范化绝对路径，空值、相对路径或无法确定用户主目录时失败封闭 | Ubuntu、macOS、Windows 默认路径、绝对覆盖、空值和相对路径正反用例 |
| 宿主隔离 | 权威状态固定落于 `state/<host>/<scopeKey>`，运行期 rendezvous 固定落于 `rendezvous/<host>`；`scopeKey` 继续同时绑定宿主与原始会话 ID 的不可逆摘要，任何宿主不得枚举、读取或回退到另一宿主分区 | 双宿主同项目、同名会话、并发启动、错配和模糊回退负例 |
| 双层初始化 | 兼容安装器在可执行时尽力预建；Hook 的首次 `SessionStart` 与 MCP 返回 `initialize` 前都调用同一幂等 bootstrap，递归创建私有目录并通过创建、写入、同步、原子替换和删除临时探针证明真实可写 | 全新安装、重复初始化、安装阶段不可写而首次启用可写、只读挂载和中途失败测试 |
| 升级迁移 | Codex 只接收原 Codex 插件数据根，Claude Code 只接收原 Claude Code 插件数据根；旧 envelope 先按现有 schema、校验和、宿主和会话作用域验证，再跨根复制并用迁移记录原子发布；旧根不删除、不覆盖，中断后可幂等重试 | 双宿主旧根、损坏状态、跨根中断、重复迁移、目标冲突和部分成功负例 |
| 权威切换 | 单个宿主迁移记录提交后，新根才成为该宿主唯一写入权威；读取不得长期双写或在新旧根间模糊选择，未完成迁移只报告阻断并保留旧数据 | 权威切换、重复启动、旧新冲突和回退拒绝测试 |
| 卸载与清理 | 禁用、卸载和版本缓存清理均不删除 `NOVA_HOME`；删除只能由后续定义的显式清理入口按用户选择范围执行 | 卸载重装、缓存升级、禁用和无清理授权负例 |

### 2.2 宿主生命周期映射

| 语义事件 | Codex | Claude Code | 共享行为 |
|----------|-------|-------------|----------|
| 会话启动或恢复 | `SessionStart` 的 `startup`、`resume` | `SessionStart` 的 `startup`、`resume` | 从宿主事件建立不可由模型选择的当前会话作用域；加载静态规则，且仅 `resume` 查询该作用域检查点并记录 `injectedGeneration` |
| 输入与工具事件 | `UserPromptSubmit`、`PostToolUse` | `UserPromptSubmit`、`PostToolUse` | 不分析自然语言，按可信宿主事件递增 `eventWatermark` 并置 dirty；检查点 MCP 自身事件不重复置 dirty |
| 回合结束 | `Stop` | `Stop` | dirty 未被当前检查点覆盖时报告降级但放行宿主回答；不得依赖 Stop 阻断后由 AI 自救，也不得把旧代冒充最新权威 |
| 压缩前 | `PreCompact` 的 `manual`、`auto` | `PreCompact` 的 `manual`、`auto` | 只有检查点 `coveredEventWatermark` 等于当前水位且 dirty=false 时才冻结 `attemptId + generation + watermark`；缺失、未覆盖或状态故障时不冻结 Nova authority，报告降级并放行宿主原生压缩 |
| 压缩完成 | `PostCompact` | `PostCompact` | 匹配已冻结 attempt 时记录 completed generation/watermark；无冻结、错配或重复冲突时不得提升宿主摘要或写入 `injectedGeneration`，但必须放行宿主完成压缩 |
| 压缩后续接 | `SessionStart` 的 `compact` | `SessionStart` 的 `compact` | 匹配已完成 attempt 时注入同一 generation 的有界胶囊并原子记录 `injectedGeneration`；缺少有效完成记录时只注入静态规则和降级上下文，不得阻断宿主会话 |
| 权威状态变化 | AI 调用插件 MCP 工具 | AI 调用插件 MCP 工具 | 工具使用隐式可信作用域，以明确字段和 authority 类型绑定当前 `eventWatermark` 创建新 authority generation；持久化成功后才清除 dirty |

生命周期 Hook 遵循“宿主可用性放行、checkpoint 权威性失败封闭”：首次安装、从无检查点版本升级、老会话恢复、MCP 不可用、状态根不可写、状态缺失/损坏/schema 不兼容或 Hook 输入异常，均不得通过非零退出、`continue:false` 或 `decision:block` 锁死普通对话与原生压缩；失败时只允许注入静态规则、无权威恢复提示或可见诊断，任何无效状态仍不得成为恢复 authority。

### 2.3 发现入口权威、迁移与回退

| 场景 | 唯一规则 | 验证 |
|------|----------|------|
| 权威优先级 | 支持且已启用版本化插件的宿主只以插件入口为发现权威；兼容软链接仅服务 Codex IDE、旧版宿主和显式故障恢复，同一宿主不得同时加载两种入口 | 插件启用态、宿主发现路径与可发现实体数量检查 |
| 安装或启用插件 | 激活前先预检该宿主全部规范兼容链接和旧别名；已有正常或失效软链接只解除链接本身，再激活插件，普通文件或真实目录冲突使整次切换零写入失败 | 同源链接、失效链接、普通文件、真实目录与中途失败回滚测试 |
| 重复入口 | 即使插件与软链接解析到同一工作区源码，也不得视为可并存；发现重复时不得加载第二份规则或技能，插件入口保持权威并要求完成原子去重后新开会话 | 规则哈希、技能名称、解析目标和重复加载负例 |
| 禁用或卸载 | 先完成插件禁用或卸载，再显式运行兼容安装器原子恢复经验证的软链接；切换完成并通过 discovery 校验后新开会话，不在活动会话内静默改变入口 | 禁用、卸载、兼容恢复、discovery 与新会话验收 |
| 启用或运行失败 | 激活失败回滚为切换前链接状态；插件已启用后的运行故障不得在同一会话自动叠加兼容入口，必须先禁用插件再按上一行恢复 | 激活失败、运行故障、回滚与无双入口检查 |
| 源码与语义 | 插件包和兼容链接都只能来源于同一版本的工作区权威源码或其不可变发布产物；用户目录不复制实体源码，不维护宿主专属规则分叉 | manifest 版本、发布校验和、链接目标、实体数量与规则哈希检查 |

### 2.4 版本与发布

| 对象 | 唯一规则 | 验证 |
|------|----------|------|
| 版本权威 | `package.json.version` 是 SemVer 单一来源；双 manifest、双 marketplace 和发布产物必须与其一致 | 版本同步脚本及 CI 负例 |
| 主分支 | pull request 与主分支只执行结构、单元、打包和三平台兼容校验 | GitHub Actions 触发条件检查 |
| 正式发布 | 维护者人工创建与 `package.json.version` 一致的 `vX.Y.Z` 标签后，Action 才构建不可变归档、校验内容并创建 GitHub Release | 标签/版本失配失败、产物清单及校验和 |
| 宿主验收 | 发布候选必须在 Codex 与 Claude Code 的受支持版本中验证安装、启用、检查点、手动/自动压缩、恢复、禁用和卸载 | 两宿主 E2E 证据；未执行不得宣称恢复生效 |
