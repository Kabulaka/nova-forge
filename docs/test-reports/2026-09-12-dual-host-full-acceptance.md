# Nova Forge Codex / Claude Code 双宿主完整验收报告

- 日期：2026-09-12
- 仓库：`/home/nika/workspace/ai/nova-forge`
- 被测代码基线：`0648ff0` 加 `FIX-01a093af-b3e9-7843-9df9-fd3f3e7fa00f` 当前任务差异
- Codex：`codex-cli 0.154.0`
- Claude Code：`2.1.233`
- Node.js：`v22.18.0`
- Python：`3.13.12`
- 隔离宿主证据根：`/tmp/nova-full-e2e-20260912.QqHs7I`
- 当前默认宿主复测日志：`/tmp/nova-codex-new-repo.WFFhd1.jsonl`、`/tmp/nova-codex-resume-retry.DTlTXi.jsonl`、`/tmp/nova-claude-new.7prxWR.jsonl`、`/tmp/nova-claude-resume.eioeha.jsonl`
- 总体结论：**当前开发快照在正确安装后，可在 Codex 与 Claude Code 中正常执行本次要求覆盖的全部插件功能。**

## 1. 结论与边界

本轮完成仓库级全量回归、插件结构校验、打包校验，以及 Codex、Claude Code 两个真实 CLI 宿主中的隔离安装和端到端操作。五个 Nova Skill、checkpoint MCP 的 `get → save → get`、新会话、恢复会话、Stop 降级、原生压缩和检查点握手均通过。

这一定论适用于本轮被测的当前开发快照。默认 Codex 与 Claude Code 环境都已通过统一开发安装入口切换到 `nova-forge@nova-forge-dev`，没有 `cache-miss`；两端随后分别完成真实新会话和同一会话 resume 的 MCP 往返。

当前机器是 Linux，原生 Windows 宿主不可用；Windows 分支由单元测试和 CI 契约覆盖，但本报告不把它表述为原生 Windows Codex/Claude Code E2E。

未启动 Review，未 push，未发布 GitHub Marketplace 或 Release，未执行 SVN 操作。

## 2. 被测能力范围

| 能力 | Codex | Claude Code | 结果摘要 |
| --- | --- | --- | --- |
| `nova-requirements` Skill | PASS | PASS | 真实模型会话加载并执行 |
| `nova-architecture` Skill | PASS | PASS | 真实模型会话加载并执行 |
| `nova-development` Skill | PASS | PASS | 真实模型会话加载并执行 |
| `nova-doctor` Skill | PASS | PASS | 真实模型会话加载并执行 |
| `nova-review` Skill | PASS | PASS | 真实模型会话加载并执行；未授权实际 Review |
| `nova_checkpoint_get` | PASS | PASS | 返回绑定会话的结构化状态 |
| `nova_checkpoint_save` | PASS | PASS | 保存 task capsule 并覆盖当前事件水位 |
| MCP `get → save → get` 往返 | PASS | PASS | 保存后读取到更新后的权威状态 |
| 新会话初始化 | PASS | PASS | Hook、MCP、状态根均正常 |
| 同目录会话 resume | PASS | PASS | 恢复后继续使用插件能力 |
| 安装插件前创建的旧会话 resume | PASS | PASS | 无历史 checkpoint 时降级启动，不阻断宿主 |
| `UserPromptSubmit` / `PostToolUse` 水位推进 | PASS | PASS | checkpoint MCP 自身不递归制造工具事件 |
| checkpoint 已覆盖时 Stop | PASS | PASS | 正常结束 |
| checkpoint 未覆盖时 Stop | PASS | PASS | 输出 `CHECKPOINT_NOT_COVERED` 降级告警，但不阻断对话 |
| 损坏、缺失或不可写状态 | PASS | PASS | 不提升为权威恢复状态，宿主仍可工作 |
| `PreCompact` | PASS | PASS | 真实原生压缩触发 |
| `PostCompact` | PASS | PASS | 真实原生压缩触发并完成握手 |
| 压缩后恢复注入 | PASS | PASS | 仅在检查点完成后注入权威胶囊 |
| 宿主原生 `/compact` | PASS | PASS | 两端均不因 checkpoint 异常被阻断 |

## 3. 仓库级验证

| 验证项 | 命令 | 结果 |
| --- | --- | --- |
| Node 全量与打包检查 | `npm run check` | PASS，107/107；84 files，280079 bytes |
| Python 测试：Codex 脚本 | `python3 -m unittest discover -s codex/scripts -p 'test_*.py'` | PASS |
| Python 测试：requirements | `python3 -m unittest discover -s skills/nova-requirements/scripts -p 'test_*.py'` | PASS |
| Python 测试：architecture | `python3 -m unittest discover -s skills/nova-architecture/scripts -p 'test_*.py'` | PASS |
| Python 测试：development | `python3 -m unittest discover -s skills/nova-development/scripts -p 'test_*.py'` | PASS |
| Python 测试：doctor | `python3 -m unittest discover -s skills/nova-doctor/scripts -p 'test_*.py'` | PASS |
| Python 测试：review | `python3 -m unittest discover -s skills/nova-review/scripts -p 'test_*.py'` | PASS |
| Python 汇总 | 上述 6 组命令 | 339 项：337 PASS，2 项按环境条件预期跳过 |
| 架构 ready 门禁 | `python3 skills/nova-architecture/scripts/validate_architecture.py --ready .nova/architecture/ARCHITECTURE_CONTRACTS.md` | PASS |
| 蓝图校验 | `python3 skills/nova-development/scripts/validate_blueprint.py .nova/PROJECT_BLUEPRINT.md` | PASS |
| Claude 插件清单 | `claude plugin validate .` | PASS |
| Codex 插件清单 | `python3 /home/nika/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .` | PASS |
| 开发包内容 | `npm run check:package` | PASS，84 files |
| Git 空白错误 | `git diff --check` | PASS |
| Nova Doctor | `python3 skills/nova-doctor/scripts/nova_doctor.py` | 12 PASS，0 WARN，0 FAIL |

Node 全量检查、架构、蓝图、manifest、Doctor 和空白检查均在最后一处 Hook 入口修正后执行。Python 相关文件和环境在先前 339 项测试后未变化，因此按证据复用规则沿用该结果。生成本报告只更新 Markdown 证据，不改变运行时代码、插件清单或测试。

## 4. Codex 真实宿主结果

### 4.1 Skill 与 MCP

隔离 Codex 环境中，五个 Nova Skill 均可发现并调用。`nova-checkpoint` MCP 完成 `get → save → get`，会话绑定、事件水位、覆盖水位和 task capsule 均能正确往返。

最新默认安装复测中，新会话 `01a093ee-42ac-7e92-aa02-f7cd5354ba94` 成功调用 `nova_checkpoint_get`。同一会话 resume 后依次完成 `get → save → get`，最终 `eventWatermark=3`、`coveredEventWatermark=3`、`dirty=false`、`authorityGeneration=1`，目标值为 `codex-resume-e2e`，没有 Hook 或 MCP 失败。

### 4.2 新会话与 resume

新会话能够自动加载 Nova 静态规则并使用 MCP。对同一目录中的既有会话执行 resume 后，Skill、Hook 和 MCP 仍可继续工作。对于安装 Nova 前创建、没有任何历史 Nova 状态的旧会话，插件只给出无权威恢复信息，不阻断宿主继续回答。

### 4.3 Stop 与异常降级

当 checkpoint 覆盖当前事件水位时，Stop 正常结束。未覆盖时会输出 `CHECKPOINT_NOT_COVERED`，但 Hook 退出成功，宿主仍可继续对话；缺失、损坏、过期状态不会被注入为权威胶囊。

### 4.4 原生压缩

真实 `/compact` 中，`PreCompact` 与 `PostCompact` 均执行成功，压缩握手最终为 `completed`，冻结和完成水位为 `4/4`。压缩后会话可以继续，恢复胶囊来自已完成的检查点。

### 4.5 开发版安装生命周期

Codex 开发安装脚本通过以下真实隔离场景：首次安装、对已有开发安装的覆盖安装、卸载、重复卸载，以及安装/卸载期间保留 `~/.nova` 状态目录。开发快照排除了 `__pycache__` 和 `.pyc`，最终打包清单为 84 个文件。

## 5. Claude Code 真实宿主结果

### 5.1 Skill 与 MCP

隔离 Claude Code 配置中仅启用本轮 Nova 开发快照。五个 Nova Skill 均通过真实 `Skill` tool call 执行；正式 MCP 工具完成 `get → save → get`，并正确绑定当前 Claude 会话。

最新默认安装复测中，新会话 `77a2e53a-2eac-4d5e-a34e-7222f11f913b` 成功调用插件命名空间下的 `nova_checkpoint_get`。同一会话 resume 后依次完成 `get → save → get`，最终 `eventWatermark=2`、`coveredEventWatermark=2`、`dirty=false`、`authorityGeneration=1`，目标值为 `claude-resume-e2e`；所有可见 Hook 响应均为成功。

### 5.2 新会话与 resume

新会话和同目录 resume 均通过。安装插件前使用安全模式创建的旧会话，在启用当前快照后 resume 也能正常回答；因为不存在历史 checkpoint，Nova 不伪造恢复权威。

### 5.3 Stop 与异常降级

未覆盖 checkpoint 时，Stop 只输出降级告警，不再返回 `continue=false` 或非零退出码。模型回答与宿主会话均不被阻断，陈旧状态也不会被注入。

### 5.4 原生压缩顺序兼容

Claude Code `2.1.233` 的真实生命周期是：

```text
PreCompact → SessionStart(source=compact) → PostCompact
```

早到的 `SessionStart(compact)` 只能看到尚未完成的握手，因此输出降级提示而不注入状态，也不阻断 Claude 原生压缩。随后 `PostCompact` 完成握手，最终状态为 `completed`，事件水位与覆盖水位为 `7/7`。这是对旧版本中 `/compact` 被安全门禁阻断问题的真实回归证明。

## 6. 本轮发现并修复的问题

| 提交 | 工作项 | 问题 | 恢复结果 |
| --- | --- | --- | --- |
| `d296e95` | `FIX-01a09114-bc2e-7c83-8eff-78dcdf9002a6` | checkpoint 异常阻断宿主对话、resume 或 compact | 宿主 fail-open，恢复权威仍 fail-closed |
| `c11bb35` | `FIX-01a0932c-e77c-7206-9374-72d63688718f` | Doctor 测试从错误的技能根解析套件 | 修正测试技能根，Python 全量测试通过 |
| `0648ff0` | `FIX-01a0932e-55cf-7ee0-bf7b-0ab8bc9a9436` | 开发快照夹带 Python 字节码缓存 | 打包与校验同时排除 `__pycache__`、`.pyc` |
| 本提交 | `FIX-01a093af-b3e9-7843-9df9-fd3f3e7fa00f` | 双宿主开发安装缺少统一生命周期；Codex 重装清缓存破坏旧会话 Hook；多进程 rendezvous 串扰；迁移目标软链接可逃逸；Hook 入口宿主检测参数错误 | 提供双宿主安装/卸载脚本，保留活动会话缓存，按宿主进程绑定 claim/MCP，拒绝迁移目标软链接逃逸，并恢复真实 Hook 环境检测 |

四个 FIX 均采用 `Review-Policy: exempt`、`Exemption-Rule: EX-FIX`。本轮没有启动后置显式 Review，Review 轮次不适用。

## 7. 当前默认宿主安装状态

| 宿主 | 当前状态 | 判断 |
| --- | --- | --- |
| Codex | `nova-forge@nova-forge-dev`，`0.2.0+codex.local-20260912t044116z`，enabled；`nova-checkpoint` MCP enabled | 当前正确开发安装；旧会话所引用的 5 个历史缓存版本仍保留 |
| Claude Code | `nova-forge@nova-forge-dev`，`0.2.0+claude.local-20260912t044116z`，enabled | 当前正确开发安装；无 `cache-miss` 或 `nova-forge-local-e2e` 注册项 |

两个默认宿主均可按当前安装继续使用。Codex 配置中只剩旧隔离测试插件的非活动 Hook 信任记录，不存在对应启用插件或 MCP，不参与发现与执行。

## 8. 原始证据

当前完整隔离证据根：`/tmp/nova-full-e2e-20260912.QqHs7I`。

关键文件：

- Codex 新会话：`codex-new4-final.txt`
- Codex resume：`codex-resume-correct-final.txt`
- Codex Stop 降级：`codex-stop-final.txt`
- Claude 新会话与 Skill/MCP：`claude-new3.debug`
- Claude resume：`claude-resume.debug`
- Claude Stop 降级：`claude-stop.debug`
- Claude 原生压缩：`claude-compact-current2.debug`

当前默认安装复测：

- Codex 新会话：`/tmp/nova-codex-new-repo.WFFhd1.jsonl`
- Codex 同会话 resume：`/tmp/nova-codex-resume-retry.DTlTXi.jsonl`
- Claude Code 新会话：`/tmp/nova-claude-new.7prxWR.jsonl`
- Claude Code 同会话 resume：`/tmp/nova-claude-resume.eioeha.jsonl`

兼容性专项证据见：

- `docs/test-reports/2026-09-12-checkpoint-degradation-e2e.md`
- `docs/test-reports/2026-09-11-dual-host-full-e2e.md`（历史缺陷复现报告，不代表当前结论）

`/tmp` 原始证据可能被系统清理；若用于发布审计，应先检查是否包含宿主上下文，再复制到受控归档位置。

## 9. 最终判断

本轮目标测试全部通过。当前开发快照已经证明可在 Codex 和 Claude Code 中执行全部目标插件功能，包括真实 Skill、MCP、Hook、新会话、旧会话 resume、未覆盖 checkpoint 降级以及原生 `/compact`。没有剩余的已知实现阻断。

没有剩余的已知 Linux 实现阻断。边界事项为：本机无法执行原生 Windows 宿主 E2E；Review、push 和发布按用户要求均未执行。
