# Nova Forge

面向 Codex 与 Claude Code 的版本化项目治理插件，覆盖“总体需求 → 并行架构契约 → 功能开发与本地提交 → 人工 Review → 审计关闭”，并以本机结构化检查点保护同一会话的压缩续接。

本仓库坚持分层事实来源：总体业务以 `.nova/PRODUCT_REQUIREMENTS.md` 与需求块为准，公共技术约束以 [.nova/PROJECT_BLUEPRINT.md](.nova/PROJECT_BLUEPRINT.md) 与架构契约为准，已实现复用入口以 `.nova/SHARED_CAPABILITIES.md` 为索引，目标方案以 `.nova/design/` 为准，当前实现以技能源码、脚本和测试为准。

## 核心技能

| 技能 | 用途 | 触发边界 |
|------|------|----------|
| [`nova-requirements`](./skills/nova-requirements/) | 总体业务、业务模块和可独立交付需求块 | 绿地项目、新需求或业务语义变化 |
| [`nova-architecture`](./skills/nova-architecture/) | 技术栈、七章蓝图与 API/数据/事件/Mock 并行契约 | 绿地初始化或共享架构变化 |
| [`nova-development`](./skills/nova-development/) | 功能设计、`FEAT-*` / `PATCH-*` / `FIX-*` / `MAINT-*` 的实施、测试与本地提交 | 已确认需求下的功能和普通开发 |
| [`nova-doctor`](./skills/nova-doctor/) | 只读检查当前项目的 Nova 数据、引用、审计与迁移状态 | 项目健康检查、校验失败诊断或迁移判断 |
| [`nova-review`](./skills/nova-review/) | 按稳定工作项选择已提交变更，复用测试证据，执行独立 Review，并在 PASS 后写入分片审计 | 仅在用户明确提出 Review、复审、补审、全部未审项或查询 Review 状态时触发 |

默认流程：

```text
总体需求与独立需求块
   ↓
必要的项目蓝图与并行架构契约（零差量不制造架构成果）
   ↓
功能设计 → 编码 → 测试 → 精确范围本地提交
   ↓
用户明确启动 Review
   ↓
独立审查 → REJECT 修正不提交 → PASS 时一次关闭与审计
```

默认开发不会自动启动 Review。Git push、远程配置和 SVN commit 也不会从本地提交授权中自动推导。

## 目录结构

```text
.
├── .nova/
│   ├── PRODUCT_REQUIREMENTS.md # 总体业务与需求索引（按需）
│   ├── PROJECT_BLUEPRINT.md    # 公共技术契约与待办索引
│   ├── SHARED_CAPABILITIES.md  # 已实现共享能力及源码位置（按需）
│   ├── requirements/           # 长期需求块（按需）
│   ├── architecture/           # 并行开发前置契约（按需）
│   ├── design/                 # 功能设计与稳定工作包锚点
│   └── audit/                  # 功能、Review 与工作项索引审计
├── codex/
│   ├── AGENTS.global.md        # Codex 与 Claude Code 共用的全局治理权威文件
│   └── scripts/                # 双宿主安装器及全局规则契约测试
├── skills/nova-*/              # 五个技能的唯一权威源码
├── hooks/                      # 双宿主生命周期声明与入口
├── runtime/
│   ├── adapters/               # Codex、Claude Code 薄适配器
│   ├── core/                   # 检查点、隔离、原子持久化和恢复胶囊
│   └── mcp/                    # 结构化检查点 MCP
├── .codex-plugin/              # Codex manifest
├── .claude-plugin/             # Claude Code manifest 与 marketplace
├── .agents/plugins/            # Codex marketplace
└── .github/workflows/          # 三平台 CI 与人工标签发布
```

每个技能以 `SKILL.md` 保存触发规则和核心路由，详细流程按需从 `references/` 加载；确定性操作集中在 `scripts/`，仅依赖 Python 3 标准库。

## 安装

### 1. 安装版本化插件（推荐，无需克隆）

运行时要求 Node.js 22.5 或更高版本；插件不会自动安装 Node.js 或 Bun。正式版本只在仓库出现与 `package.json.version` 一致的人工 `vX.Y.Z` 标签后发布。

Codex 可添加固定标签的仓库 marketplace，再从 `/plugins` 安装并启用 `nova-forge`：

```bash
codex plugin marketplace add Kabulaka/nova-forge --ref v0.3.1
codex plugin add nova-forge@nova-forge
```

Claude Code 可添加同一仓库 marketplace，再从插件管理器安装 `nova-forge@nova-forge`：

```text
/plugin marketplace add Kabulaka/nova-forge
/plugin install nova-forge@nova-forge
```

安装后必须审阅并信任插件 Hook；未启用或未信任时，不得认为自动检查点和压缩恢复已经生效。Codex IDE 当前不提供插件入口，应使用下面的兼容方式。

插件的持久状态不再写入版本缓存中的 `${PLUGIN_DATA}` 或 `${CLAUDE_PLUGIN_DATA}`。默认状态根是 `~/.nova`，如需改到其他磁盘，只支持在启动宿主前设置绝对路径 `NOVA_HOME`：

```bash
export NOVA_HOME=/absolute/path/to/nova-state
```

安装器可执行时会尽力预建状态根；无论安装阶段是否能够写入，首次 Hook `SessionStart` 和 MCP `initialize` 都会再次幂等创建，并通过实际写入、同步、原子替换和删除探针确认可用。旧插件数据只作为当前宿主的迁移来源：有效检查点按 `host → scopeKey` 非破坏复制，旧根不会被删除，rendezvous、锁和能力文件不会迁移。相对 `NOVA_HOME`、不可写目录或迁移冲突会明确失败并提示目标路径，不会改用工作区或 `/tmp`。

动态检查点把一个宿主进程的首个可信 `SessionStart` 作为唯一会话 owner；同一进程若出现第二个会话或第二个 MCP instance，会持久撤销该进程的 Nova MCP 绑定并让后续状态调用失败封闭，普通对话仍可继续。当前宿主没有向 Hook 与 stdio MCP 同时提供会话 nonce，因此同一长生命周期宿主进程内的 Nova 多会话并发不受支持；应为每个需要动态检查点的会话启动独立 Codex/Claude Code 进程。

#### 从旧版兼容链接迁移

旧版通过 `install_global_rules.py` 把全局规则和五个技能链接到用户目录。迁移前先结束相关宿主的当前会话，并逐项确认入口类型和实际目标：

```bash
ls -ld ~/.codex/AGENTS.md ~/.codex/skills/nova-* 2>/dev/null
readlink -f ~/.codex/AGENTS.md

ls -ld ~/.claude/CLAUDE.md ~/.claude/skills/nova-* 2>/dev/null
readlink -f ~/.claude/CLAUDE.md
```

- 只有确认解析到旧版或当前 Nova Forge 工作区的软链接才属于兼容入口；解除时只删除链接本身，不得删除其指向的仓库文件或目录。只迁移一个宿主时，不要改动另一个宿主。
- `~/.codex/AGENTS.md` 或 `~/.claude/CLAUDE.md` 如果是普通文件，应作为用户自己的规则保留，不得为了安装插件删除。普通个人规则文件可以与插件并存，不属于 Nova 兼容软链接。
- 兼容安装器不备份个人规则，插件安装也不会自动还原这些文件。如果更早的手工安装曾移走个人 `AGENTS.md` 或 `CLAUDE.md`，应先解除 Nova 软链接，再从自己的备份恢复；没有可信备份时只能人工重建，不得把软链接目标或其他文件猜作备份覆盖回来。
- 五个 `nova-*` 技能链接及旧的 `project-brainstorming`、`nova-brainstorming` 别名采用相同规则：只解除已确认属于 Nova 的软链接，普通文件或真实目录留给用户人工处理。
- 清理兼容入口后再安装并启用插件、审阅并信任 Hook，最后新开会话。不要在仍加载旧软链接的会话中直接叠加插件。

例如，已确认下面两个入口确实是 Nova 软链接时，可以只解除链接本身：

```bash
unlink ~/.codex/AGENTS.md
unlink ~/.claude/CLAUDE.md
```

技能链接也必须逐项确认后再解除；不要用递归删除或未经检查的通配符清理用户目录。

### 2. 离线安装本地开发版本（需提前克隆）

本地开发插件与 GitHub 正式插件不能在同一宿主中同时启用。开发版安装脚本会先读取 Codex 和 Claude Code 的 JSON 状态，并把当前工作区中 `npm pack` 会包含的文件复制、校验为隔离快照；快照就绪后才替换两个宿主中已安装的 `nova-forge@...`（包括 GitHub 正式版、旧开发版和 E2E 版）。它不会直接从脏工作区加载 Hook，也不会把测试、`.nova/` 或未打包文件带入插件；快照会分别生成 Codex 和 Claude Code cachebuster，并且只允许 `hooks/hooks.json` 这一份 Hook 声明。

仓库已经克隆到本机，并且 Node.js 22.5+、Codex CLI、Claude Code CLI 均已安装时，这套开发版安装流程不需要联网下载 Nova Forge、npm 依赖或 marketplace 内容。`npm run dev:install` 是同时安装 Codex 和 Claude Code 的双宿主入口；`npm run codex:dev:install` 只安装 Codex，`npm run claude:dev:install` 只安装 Claude Code。这里的“离线”仅指插件安装过程，安装后的模型对话是否需要网络仍由各宿主及其模型提供方决定。

先预览将卸载和替换的精确对象：

```bash
npm run dev:install -- --dry-run
```

确认后安装：

```bash
npm run dev:install
```

开发 marketplace 固定写入 `~/.nova/marketplaces/nova-forge-dev`（设置了绝对 `NOVA_HOME` 时位于该根下），两个宿主中的插件 ID 都是 `nova-forge@nova-forge-dev`。脚本会验证每个宿主最终只有这一份 Nova 插件处于已安装、已启用且无加载错误的状态；`~/.nova` 中的检查点数据不会被删除。

Codex CLI 在重装插件时会清理旧版本缓存，但活动会话的 Hook 仍可能引用旧缓存路径。安装器会在 CLI 操作前保存 Nova 缓存并在操作后恢复旧版本目录，因此正在运行的旧会话不会再因 `MODULE_NOT_FOUND` 中断；Claude Code 的原生更新流程本身会保留旧版本缓存。旧会话继续使用其启动时加载的版本，新会话使用新快照。安装后不再要求为了避免 Hook 崩溃而强制退出旧会话，但要验收新代码仍应新开会话。

只操作单个宿主时可使用：

```bash
npm run codex:dev:install
npm run claude:dev:install
```

#### 用独立宿主目录做隔离开发

`CODEX_HOME` 只切换 Codex CLI 的独立状态根；开发安装器会把它传给 Codex，并只在该根中处理 Nova 插件缓存。Claude Code 使用 `CLAUDE_CONFIG_DIR`，Nova Forge 的检查点与开发 marketplace 快照使用 `NOVA_HOME`。因此，只设置 `CODEX_HOME` 只能隔离 Codex，不能同时隔离 Claude Code 和 Nova 状态。三个变量都必须是绝对路径，并且安装、启动宿主、验证和卸载时必须保持同一组值。

完整双宿主隔离可在新终端中执行：

```bash
export NOVA_DEV_ROOT="$(mktemp -d)"
export CODEX_HOME="$NOVA_DEV_ROOT/codex"
export CLAUDE_CONFIG_DIR="$NOVA_DEV_ROOT/claude"
export NOVA_HOME="$NOVA_DEV_ROOT/nova"
mkdir -p "$CODEX_HOME" "$CLAUDE_CONFIG_DIR" "$NOVA_HOME"

npm run dev:install -- --dry-run
npm run dev:install
```

这不是把现有 `~/.codex` 或 `~/.claude` 复制到新目录。安装器只把当前仓库中 `npm pack` 会包含的 Nova Forge 文件复制到 `$NOVA_HOME/marketplaces/nova-forge-dev`，随后让两个宿主在各自的新根中登记插件；原宿主目录、个人配置、历史会话和其他插件都不会被复制。不要整体复制旧宿主目录，否则旧缓存、旧插件登记和其他本机状态会重新进入测试环境，失去隔离意义。

如果新宿主根没有可用的登录状态，应在保持上述变量的同一终端中按宿主正常流程重新登录。安装完成后，也必须从该终端启动 `codex` 或 `claude`；换到未设置这些变量的终端会重新使用默认的 `~/.codex`、`~/.claude` 和 `~/.nova`。只隔离 Codex 时可以仅设置绝对 `CODEX_HOME` 与 `NOVA_HOME`，然后运行 `npm run codex:dev:install`。

测试结束后，在同一终端按下文先预览再卸载；确认 `NOVA_DEV_ROOT` 确实是本次创建的临时目录后，才按需删除该目录。

卸载开发版前可预览：

```bash
npm run dev:uninstall -- --dry-run
```

卸载开发版及其本地 marketplace 快照：

```bash
npm run dev:uninstall
```

完整卸载脚本只注销两个宿主中的 `nova-forge@nova-forge-dev` 和精确的开发 marketplace 目录，不删除 `~/.nova` 状态，也不会静默重装 GitHub 正式版。为保证仍在运行的会话不崩溃，宿主缓存中的旧版本目录会保留，但它们不再是已安装插件；关闭旧会话后可按宿主自己的缓存管理策略清理。单宿主卸载使用 `codex:dev:uninstall` 或 `claude:dev:uninstall`，此时共享快照会保留，避免破坏另一宿主。需要恢复正式版时，先执行第 1 小节对应宿主的 marketplace 和安装命令。

### 3. 本地兼容发现链接（需要克隆）

支持插件且已经启用 Nova 版本化插件的宿主，以插件入口为唯一发现权威，不要同时保留本节兼容链接。Codex IDE、旧版宿主或需要显式故障恢复时，才使用下述兼容安装器；两种入口即使解析到同一工作区源码也不能在同一宿主并存。

兼容模式只提供用户级规则与五个技能，不注册插件 Hook 或结构化检查点 MCP；安装器仍会尽力预建与插件共用的 `~/.nova` 状态根。需要修改源码、使用 Codex IDE、兼容旧宿主或执行故障回退时，先克隆仓库：

```bash
git clone https://github.com/Kabulaka/nova-forge.git
cd nova-forge
```

Codex 从 `~/.codex/AGENTS.md` 加载用户级规则，Claude Code 从 `~/.claude/CLAUDE.md` 加载用户级规则；两者都指向本仓库唯一的 `codex/AGENTS.global.md`。五个 Nova 技能也会分别链接到两个宿主的用户级技能目录。

运行统一安装器：

```bash
python codex/scripts/install_global_rules.py
```

安装器会先检查全部目标，再开始修改：

- 已存在的正常或失效软链接会先解除链接本身，再指向当前仓库；不会删除原链接指向的文件或目录。
- 两个宿主中的 `project-brainstorming` 和 `nova-brainstorming` 旧别名如为软链接会被移除；若为普通文件或真实目录，安装整体拒绝且零写入。
- 任一目标是普通文件或真实目录时，安装整体失败且不修改其他入口；请先核对其用途，再自行决定是否迁移或合并。
- 仓库迁移或更换克隆目录后，重新执行同一命令即可刷新全部链接。
- 工作区目录始终是唯一实体源码，两个宿主的用户目录只保存发现链接。
- 安装器输出 `STATE:` 表示 `~/.nova`（或绝对 `NOVA_HOME`）已完成真实写验证；输出 `WARN:` 时链接安装仍可完成，首次 Hook/MCP 会重试。重试仍失败时，Hook 会显示诊断并放行普通对话与宿主原生压缩，只有 checkpoint 权威状态保持失败封闭；MCP 状态调用会按错误中的路径和 `NOVA_HOME` 提示明确拒绝。

链接更新后请分别新开 Codex 和 Claude Code 会话，使用户级规则与技能重新加载。

确认两个用户级规则入口都解析到当前仓库：

```bash
readlink -f ~/.codex/AGENTS.md
readlink -f ~/.claude/CLAUDE.md
```

两个输出都应为当前仓库下 `codex/AGENTS.global.md` 的绝对路径，而不是旧克隆目录。

安装后验证：

```bash
python skills/nova-review/scripts/validate_discovery.py --workspace "$PWD" --codex-home ~/.codex --claude-home ~/.claude
```

### 4. 升级与回退注意事项

- **版本化插件升级**：先结束当前会话并阅读目标版本 Release Notes，确认 Node.js 要求和升级说明；Codex 的 Git marketplace 使用固定标签，升级到新版本时按目标 Release Notes 重新配置对应 `vX.Y.Z`，不要把 `main` 当作正式版本。刷新或重新安装后，如 Hook 定义发生变化，必须重新审阅并信任，再新开会话验证。
- **状态迁移与卸载**：升级时只迁移同宿主可验证的旧检查点，原插件数据根保持不变；禁用、卸载、版本缓存清理和兼容链接切换都不会删除 `~/.nova`。当前版本不提供自动清理入口，需要删除时必须由用户另行明确选择范围并自行操作。
- **旧兼容版升级为插件**：先按“从旧版兼容链接迁移”核对并解除 Nova 软链接，恢复或保留个人 `~/.codex/AGENTS.md`、`~/.claude/CLAUDE.md`，再启用插件。插件与兼容入口不能同时生效。
- **插件回退到兼容模式**：先在宿主中禁用或卸载 Nova Forge 插件并结束当前会话，再克隆目标版本、处理用户级规则文件冲突并运行兼容安装器。若 `~/.codex/AGENTS.md` 或 `~/.claude/CLAUDE.md` 是普通文件，安装器会拒绝覆盖；应先自行备份、迁移或合并，不能强制删除。
- **仓库路径迁移**：仅兼容模式依赖克隆目录。移动或重新克隆后再次运行安装器，并用 `readlink -f` 和 `validate_discovery.py` 确认所有入口都指向新目录；版本化插件不依赖工作区克隆路径。
- **失败恢复**：任何一步发现目标类型或来源无法确认时立即停止。不要一边保留已启用插件，一边运行兼容安装器；回退完成后必须执行 discovery 校验并新开会话。

## 版本发布

正式版本使用仓库内版本化 Release Notes，GitHub Actions 只负责校验、打包并原样发布正文，不根据提交标题自动编写版本说明。每个标签 `vX.Y.Z` 必须同时满足：

- 与 `package.json.version`、双宿主 manifest 和 marketplace 版本完全一致；
- 存在 `docs/release-notes/vX.Y.Z.md`，且包含 Overview、Highlights、安装、运行要求和升级说明；
- `npm run check` 全部通过；
- 标签由维护者人工创建，主分支推送不会创建 Release。

发布前本地校验：

```bash
npm run check:release-notes
npm run check
```

推送匹配标签后，[Release workflow](.github/workflows/release.yml) 会重新执行完整校验，生成不可变的 `nova-forge-X.Y.Z.tgz` 与 `SHA256SUMS`，并使用对应 Markdown 创建 GitHub Release。首个基线版本说明见 [v0.1.0](docs/release-notes/v0.1.0.md)。工作流失败不会删除标签；修复后必须遵守同一版本不可变原则，不得静默替换已经发布的资产。

## 使用

可以在 Codex 或 Claude Code 中直接描述目标，也可以显式点名技能：

```text
使用 $nova-requirements，帮我逐步澄清这个项目的总体业务和需求块。
```

```text
使用 $nova-architecture，基于已确认需求生成最小架构和并行开发契约。
```

```text
使用 $nova-development，实施 FEAT-019a1234-5678-7abc-8def-0123456789ab。
```

```text
使用 $nova-doctor，只读检查当前项目的 Nova 健康状态。
```

```text
使用 $nova-review，Review FEAT-019a1234-5678-7abc-8def-0123456789ab。
```

需求澄清每轮只确认一个会改变结果的信息维度；能够从代码、配置、测试或文档查明的事实会先研究，不要求用户重复提供。

## 本地验证

在仓库根目录执行：

```bash
# 示例使用 python；若环境只提供 python3，或 Windows 使用 py -3，请替换为对应 Python 3 启动器；Windows 不要求 WSL

# 校验版本 3 项目蓝图
python skills/nova-development/scripts/validate_blueprint.py .nova/PROJECT_BLUEPRINT.md

# 共享能力目录存在时，校验登记项及源码位置
python skills/nova-architecture/scripts/validate_shared_capabilities.py --if-present .nova/SHARED_CAPABILITIES.md

# 运行各技能测试
python -m unittest discover -s codex/scripts -p 'test_*.py'
python -m unittest discover -s skills/nova-requirements/scripts -p 'test_*.py'
python -m unittest discover -s skills/nova-architecture/scripts -p 'test_*.py'
python -m unittest discover -s skills/nova-development/scripts -p 'test_*.py'
python -m unittest discover -s skills/nova-doctor/scripts -p 'test_*.py'
python -m unittest discover -s skills/nova-review/scripts -p 'test_*.py'

# 校验插件版本、结构、运行时和发布包
npm run check

# 只读检查当前项目的 Nova 数据
python skills/nova-doctor/scripts/nova_doctor.py

# 校验技能与全局治理文件的发现链接
python skills/nova-review/scripts/validate_discovery.py --workspace "$PWD" --codex-home ~/.codex --claude-home ~/.claude
```

Windows 原生 Review 关闭可在 PowerShell 中按以下顺序执行（尖括号内容替换为本轮实际文件或编号）：

```powershell
$ReviewFixPaths = @("<review_fix_scope-path-1>", "<review_fix_scope-path-2>")
git add -- $ReviewFixPaths
py -3 skills/nova-review/scripts/nova_review.py check-manifest --repo . --manifest <review-manifest.json>
py -3 skills/nova-review/scripts/nova_review.py record-pass --repo . --manifest <review-manifest.json>
$ClosureOutputPaths = @("<record-pass-output-path-1>", "<record-pass-output-path-2>")
git add -- $ClosureOutputPaths
git diff --cached --binary --output=<closure.diff>
py -3 skills/nova-review/scripts/nova_review.py validate-audit-message --repo . --message-file <closure-message.txt> --diff-file <closure.diff>
git commit -F <closure-message.txt>
py -3 skills/nova-review/scripts/nova_review.py query --repo . --work-item <FEAT-...>
```

`check-manifest` 前必须仅暂存 manifest 的 `review_fix_scope` 所列实际路径；`record-pass` 写出确定性审计与关闭投影后，再把它实际生成的每个精确路径加入暂存区，与 Review 修正形成同一暂存闭包。`record-pass` 只能在用户已授权的 Review PASS 闭环中执行。`check-manifest` 与 `query` 是只读检查；若读取检测到未完成事务会失败封闭，应使用相同 manifest 重新运行 `record-pass` 持锁恢复，成功后再读取。无法安全判定的事务仍保持失败封闭。Windows 支持基线限定为本机 NTFS；SMB 网络共享、ReFS、同步盘，以及突然断电后的物理落盘原子性或持久性不在承诺范围内。

设计文档可单独校验：

```bash
python skills/nova-development/scripts/validate_blueprint.py --design .nova/design/YYYY-MM-DD_example.md
```

## 关键约束

- 蓝图保存项目级公共事实，设计文档保存目标，代码、测试和配置证明当前实现。
- 开发澄清先查共享能力目录与实际代码；新增共享能力由用户确认，最低验收后才登记。
- 模块业务表、查询和 Repository 归模块所有，但代码落位和依赖方向必须服从蓝图分层。
- 已实现或已废弃的设计是不可变历史；后续演进必须新建设计并链接来源。
- 需求、架构检查点和交付分别使用 `REQ-*`、`ARCH-*` 与 `FEAT-*`/`PATCH-*`/`FIX-*`/`MAINT-*`；历史 `PEND-*` 仅兼容，不再新建。
- schema 2 提交首行使用 `type(scope): 中文结果摘要`；工作项默认一个实现结果 commit，Review 最终只产生一个 closure commit。
- 本地提交必须包含 Nova trailers；人工 Review 结论不得伪造进不可变开发提交。
- 校验器必须只读、确定性执行，并在失败时返回非零状态。

详细项目边界见 [.nova/PROJECT_BLUEPRINT.md](.nova/PROJECT_BLUEPRINT.md)。
