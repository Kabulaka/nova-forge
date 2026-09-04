# Codex与Claude Code插件运行时实现设计

> 设计规范版本：5
> 设计状态：已实现
> 收敛确认：用户明确确认@sha256:823de4a29ba38babf467468a301e78227a45b5918032cebb7733f6f121df2bda
> 演进来源：[Codex与Claude Code插件分发及同会话压缩续接架构](2026-09-03_Codex与Claude_Code插件分发及同会话压缩续接架构.md)
> Requirement-Ref：REQ-01a06524-60ee-7d61-a9f1-c588cd2bfdff@v1
> 工作包：WP-01

<a id="shared-context"></a>
## 1. 共享约束

### 1.1 问题与成功结果

| 问题 | 成功结果 |
|------|----------|
| Nova 只有仓库源码和兼容软链接，缺少可版本化的双宿主插件、结构化会话检查点和压缩生命周期闭环 | Codex 与 Claude Code 可从同一版本化插件加载唯一规则和五个技能，并以失败封闭的本机会话检查点在同一宿主、同一会话内完成压缩续接 |

### 1.2 共享契约

| 契约 | 语义键 | 唯一规则 |
|------|--------|----------|
| S-01 | 共享/架构依据 | 实现以 `dual-host-plugin.md` 与 `session-checkpoint.md` 已 Review PASS 的目录、生命周期、权限、容量和恢复契约为唯一共享依据，不在宿主适配器中复制或放宽状态机 |
| S-02 | 共享/权威来源 | `package.json.version` 是版本唯一来源，`codex/AGENTS.global.md` 和 `skills/nova-*/` 是规则与技能唯一源码；manifest、marketplace、兼容入口和发布产物不得形成宿主专属语义分叉 |
| S-03 | 共享/宿主事实 | Codex 与 Claude Code 均通过受信插件 Hook 获取宿主提供的会话事件；Codex `PostCompact` 可报告停止而 Claude Code `PostCompact` 不具决策控制，因此压缩后失败统一记录为不可信握手，并由下一次 `SessionStart(compact)` 阻止继续和拒绝注入 |
| S-04 | 共享/外部边界 | 本工作包不修改用户目录、不启用或卸载真实插件、不 push、不创建标签或 GitHub Release，也不宣称三平台 CI 或双宿主真实 E2E 已运行；入口原子迁移和真实宿主闭环保留给 `PEND-01a06626-fe17-7569-b31b-303218cc9c3b` |

<a id="work-package-map"></a>
## 2. 工作包地图

| 工作包 | 角色 | 状态 | 交付结果 | 前置依赖 | 设计章节 |
|--------|------|------|----------|----------|----------|
| WP-01 | 能力 | 已完成 | 交付可打包的双宿主插件、共享检查点核心、Hook/MCP 适配器、兼容源码过渡和本地可执行验证 | 无 | [双宿主插件运行时与发布工程](#wp-01-dual-host-plugin-runtime) |

<a id="wp-01-dual-host-plugin-runtime"></a>
## WP-01 双宿主插件运行时与发布工程

### 契约

| 契约 | 维度 | 语义键 | 唯一规则 |
|------|------|--------|----------|
| WP-01-C01 | 交付边界 | WP-01/工程骨架 | 新增 `package.json`、双 manifest、双 marketplace、`hooks/`、`runtime/adapters/`、`runtime/core/`、`runtime/mcp/`、版本/打包脚本和 GitHub Actions；初始版本为 `0.1.0`，只使用 Node.js 22.5+ 标准库和 ESM |
| WP-01-C02 | 参与者与权限 | WP-01/宿主权限 | 插件只有启用且 Hook 已信任时才声明自动检查点生效；宿主 Hook 输入建立作用域，模型和 MCP 参数不得选择 host/sessionId；本期不触碰当前用户入口，不允许插件与兼容软链接被当作可并存入口 |
| WP-01-C03 | 触发与输入 | WP-01/检查点与生命周期 | MCP 只暴露 `nova_checkpoint_get` 与 `nova_checkpoint_save`，保存必须提交完整 `taskCapsule`、`controlDocuments`、幂等键和当前覆盖水位；`UserPromptSubmit`、非本插件 `PostToolUse`、`Stop`、`PreCompact`、`PostCompact` 与 `SessionStart` 只按宿主事件推进共享状态机 |
| WP-01-C04 | 结果、状态与不变量 | WP-01/状态核心 | 共享核心执行 schema、字段权限、规范化 JSON、SHA-256、秘密扫描、大小/深度/数量限制、单调代际和水位、30 天租约、每宿主与全局配额、作用域锁、原子 current/backup 写入和同作用域损坏恢复；任何缺失或越界保持旧有效代且不清除 dirty |
| WP-01-C05 | 失败与恢复 | WP-01/压缩与注入 | 不读取 transcript 或 `compact_summary` 推断正式决定；检查点缺失、过期、不兼容、损坏、握手错序或注入超限时拒绝权威注入并输出具体失败，`SessionStart(compact)` 以 `continue:false` 停止继续，只有同作用域合格 backup 可回退 |
| WP-01-C06 | AI 决策边界 | WP-01/实现决策 | AI 可决定不改变公开结构、宿主行为、安全和数据语义的内部模块名、测试夹具和错误文案；改变初始版本、依赖、作用域绑定、authority、容量、失败阻断、源码迁移、发布触发或本期排除必须重新确认 |
| WP-01-C07 | 交付边界 | WP-01/技能迁移 | 五个技能以 `git mv` 迁入 `skills/nova-*/` 并更新仓库内引用；根目录只保留指向规范目录的临时兼容软链接以维持当前旧入口，发布包排除这些别名，兼容安装器改用规范源但本期不执行 |
| WP-01-C08 | 结果、状态与不变量 | WP-01/会话绑定 | Hook claim 与 MCP 实例只在同一 host、工作目录摘要、短时窗口且恰好一对一时于宿主私有数据目录内建立随机能力绑定；能力只存在于权限受限的瞬态握手文件和 MCP 内存，歧义、重放、重绑或缺失一律失败封闭，不采用“同项目最近会话”回退 |
| WP-01-C09 | 结果、状态与不变量 | WP-01/生命周期结果 | 输入与工具事件只推进水位并置 dirty；`Stop` 在未覆盖时要求结构化保存；`PreCompact` 只冻结完全覆盖的 clean 代；`PostCompact` 只完成匹配冻结；`SessionStart(compact)` 只注入同代有界胶囊，静态规则在各类 `SessionStart` 从唯一规则源加载 |
| WP-01-C10 | 结果、状态与不变量 | WP-01/版本发布 | 版本同步检查覆盖双 manifest、Claude marketplace 显式版本以及 Codex marketplace 的 `vX.Y.Z` Git ref；PR/main 只跑结构、单元、打包和 Ubuntu/macOS/Windows 矩阵，只有人工且与版本一致的标签触发归档、清单、校验和及 GitHub Release |

### 验收

| 覆盖契约 | 场景 | 预期结果 |
|----------|------|----------|
| S-01、S-02、WP-01-C01、WP-01-C07、WP-01-C10 | 校验源码树、双 manifest/marketplace、版本同步和打包清单 | 五个技能与规则只有一个权威源码，版本均解析到 `0.1.0`/`v0.1.0`，发布包含完整插件组件且不含根目录兼容别名或运行状态 |
| WP-01-C03、WP-01-C04 | 运行 MCP 协议、schema、幂等、限制、秘密、原子写入、并发与损坏用例 | 合法完整检查点创建或幂等复用正确代；非法输入在分配或替换前失败，旧有效代、backup、水位和 dirty 保持一致 |
| WP-01-C02、WP-01-C08 | 模拟同会话启动、恢复、跨宿主、跨会话、并发同目录、缺失和重放绑定 | 只有唯一可信一对一绑定可读写当前作用域，其他情况不泄露、不回退到最近会话并给出确定性失败 |
| S-03、WP-01-C03、WP-01-C05、WP-01-C09 | 以 Codex、Claude Code 事件夹具执行输入、工具、结束、手动/自动压缩和压缩后续接 | 水位与 dirty 单调推进，漏写在 `Stop`/`PreCompact` 被阻断；只有匹配握手注入完整有界胶囊，宿主差异不改变共享语义 |
| S-04、WP-01-C06、WP-01-C10 | 运行全部 Node/Python 测试、插件结构校验、打包 dry-run 和 workflow 静态检查 | 本机验证通过并明确区分尚未运行的三平台 Actions、正式 Release 和真实宿主 E2E；不产生用户目录、远端或发布写入 |
