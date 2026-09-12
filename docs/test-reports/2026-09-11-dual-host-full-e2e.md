# Nova Forge Codex / Claude Code 双宿主完整实测报告

> 历史报告说明：本报告记录的是提交 `f030bd8` 的原始行为，其中“checkpoint 异常必须阻断宿主”的结论已被 2026-09-12 的架构契约和 `FIX-01a09114-bc2e-7c83-8eff-78dcdf9002a6` 取代。当前兼容性复测见 `2026-09-12-checkpoint-degradation-e2e.md`。本报告保留为缺陷复现证据，不再代表当前设计或发布判断。

- 测试日期：2026-09-11（Asia/Shanghai）
- 被测版本：`nova-forge 0.2.0`
- 被测提交：`f030bd8d868a048bbde22de5fd69ca7feabbdaef`
- 总体结论：**部分通过，存在 1 个阻断缺陷**
- 发布判断：**当前不能宣称 Codex 与 Claude Code 的全部插件功能均可正常执行**

## 1. 结论摘要

Codex 端的 Marketplace 安装、五个 Skill、MCP、六类 Hook、默认 `~/.nova` 初始化、Stop 安全门禁和同会话 `/compact` 恢复均通过真实宿主测试。

Claude Code 端的 Marketplace 安装、五个 Skill、MCP、默认 `~/.nova` 初始化、事件水位、Stop 阻断与恢复，以及 PreCompact、PostCompact 两个 Hook 的独立执行均通过；但真实 `/compact` 生命周期中，Claude Code 会先执行 `SessionStart(compact)`，随后才完成 `PostCompact`。Nova 在前一步按安全契约找不到已完成的压缩检查点，返回：

```text
COMPACTION_HANDSHAKE_MISMATCH: SessionStart(compact) has no matching completed checkpoint
```

该问题在仅启用 Nova Forge 的 Claude 隔离环境中仍然稳定复现，因此不是其他插件干扰。它阻断 Claude Code 压缩后的即时检查点注入与同会话无缝续接。

## 2. 测试环境与隔离

| 项目 | 值 |
| --- | --- |
| 操作系统 | Linux 6.6.87.2-microsoft-standard-WSL2 x86_64 |
| Codex | `codex-cli 0.154.0` |
| Claude Code | `2.1.233` |
| Node.js | `v22.18.0` |
| 测试根目录 | `/tmp/nova-forge-full-e2e.pYYfxI` |
| Marketplace | `nova-forge-full-e2e` |
| Codex 隔离目录 | `/tmp/nova-forge-full-e2e.pYYfxI/codex-home` |
| Claude 隔离目录 | `/tmp/nova-forge-full-e2e.pYYfxI/claude-config` |

被测插件快照中的 237 个 Git 跟踪文件均与上述提交的 blob 一致：缺失 0、内容不一致 0。

Codex 隔离配置中只有 `nova-forge@nova-forge-full-e2e` 处于已安装、启用状态。Claude 最终压缩复测前禁用了旧的 Nova 测试副本和全部其他已安装插件，最终仅保留 `nova-forge@nova-forge-full-e2e` 启用。所有禁用操作只发生在 `/tmp` 隔离配置中。

## 3. 插件能力清单

仓库声明并纳入本次测试的能力为：

- 5 个 Skill：`nova-requirements`、`nova-architecture`、`nova-development`、`nova-review`、`nova-doctor`
- 1 个 MCP Server：`nova-checkpoint`
- 2 个 MCP Tool：`nova_checkpoint_get`、`nova_checkpoint_save`
- 6 类 Hook：`SessionStart`、`UserPromptSubmit`、`PostToolUse`、`Stop`、`PreCompact`、`PostCompact`
- 默认用户数据根：`~/.nova`
- 同会话压缩握手与恢复注入

## 4. 结果矩阵

| 功能 | Codex | Claude Code | 真实宿主证据摘要 |
| --- | --- | --- | --- |
| Marketplace 安装与启用 | PASS | PASS | 两端 CLI 均显示 `nova-forge 0.2.0` 已启用 |
| 插件结构校验 | PASS | PASS | Codex validator 与 `claude plugin validate .` 均退出 0 |
| 5 个 Skill 加载/调用 | PASS | PASS | Codex 返回五项职责；Claude stream-json 记录 5 次 `Skill` tool_use |
| MCP 注册与启动 | PASS | PASS | 两端真实模型会话均成功调用 `get/save/get` |
| `nova_checkpoint_get` | PASS | PASS | 返回绑定会话的结构化状态 |
| `nova_checkpoint_save` | PASS | PASS | 保存完整 taskCapsule 并返回 `saved=true` |
| 默认 `~/.nova` 自动初始化 | PASS | PASS | 根目录 `0700`，全部目录 `0700`、文件 `0600` |
| `UserPromptSubmit` 事件推进 | PASS | PASS | 水位随用户输入推进；Claude 单 Nova 实测首轮总水位符合 1 次 Prompt 加 5 次 Skill 工具事件 |
| `PostToolUse` 事件推进 | PASS | PASS | 工具调用推进水位；checkpoint MCP 自身不递归计数 |
| Stop 正常放行 | PASS | PASS | 检查点覆盖当前水位后宿主正常结束 |
| Stop 未覆盖时 fail-closed | PASS | PASS | 两端均返回 `CHECKPOINT_NOT_COVERED`；Claude 随后保存最新水位并恢复结束 |
| 陈旧水位拒绝 | 未单独做宿主冲突用例 | PASS | Claude 使用水位 6 保存时返回 `WATERMARK_MISMATCH`，读取水位 7 后重试成功 |
| PreCompact Hook | PASS | PASS | 两端真实 `/compact` 均成功执行 |
| PostCompact Hook | PASS | PASS | 两端 Hook 自身退出 0，状态完成落盘 |
| 压缩后即时 SessionStart 恢复注入 | PASS | **FAIL** | Codex 注入 generation 1；Claude 在 PostCompact 完成前检查，返回握手不匹配 |
| 压缩前后上下文标记恢复 | PASS | **BLOCKED** | Codex 压缩后返回 `COMPACT_SENTINEL`；Claude 即时恢复被上述安全门禁阻断 |

## 5. Codex 真实测试详情

### 5.1 安装与 Skill

- Skill 会话：`01a09040-09e6-7240-a650-fad87d464ffc`
- 五个 Skill 均按指定顺序加载，真实模型返回各自职责。
- 该组合会话中的 MCP 首次因测试夹具把 Hook 与 MCP 指向不同状态根而返回 `BINDING_UNAVAILABLE`；没有伪造水位，也没有执行非法保存。随后在与宿主进程一致的隔离 `HOME` 下单独重测 MCP，结果通过。

### 5.2 MCP 与默认数据目录

- MCP 会话：`01a09044-04d6-77d2-a5aa-05287d44a575`
- 实际流程：`get -> save -> get`
- 保存结果：`saved=true`
- 最终状态：`eventWatermark=1`、`coveredEventWatermark=1`、`dirty=false`
- 自动创建 `/tmp/nova-forge-full-e2e.pYYfxI/home-codex/.nova`
- 权限核验：根与 12 个子目录全部 `0700`，7 个文件全部 `0600`

### 5.3 Hook 与压缩恢复

- 压缩会话：`01a0904e-7ce2-7f10-b15d-f5fe3f3631fa`
- `SessionStart`、`UserPromptSubmit`、`PostToolUse`、`Stop`、`PreCompact`、`PostCompact` 均被真实宿主触发。
- 未覆盖检查点时 Stop 返回 `CHECKPOINT_NOT_COVERED`；覆盖后正常放行。
- 手工 `/compact` 后握手状态：

```text
trigger=manual
status=injected
frozenWatermark=4
completedWatermark=4
injectedGeneration=1
```

- 压缩后恢复胶囊包含 `objective.value=COMPACT_SENTINEL`，模型最终正确返回 `COMPACT_SENTINEL`。
- 结束后的 `eventWatermark=5`、`dirty=true` 来自压缩恢复后的新一轮用户事件，不否定已经完成的 `4/4` 压缩握手。

## 6. Claude Code 真实测试详情

### 6.1 单一 Nova 实例的 Skill、MCP 与 Hook

- 会话：`698891f5-7a8b-4db3-a054-de51b028b170`
- stream-json 明确记录 8 次工具调用：5 次 `Skill`、2 次 `nova_checkpoint_get`、1 次 `nova_checkpoint_save`。
- 最终模型输出：

```text
SINGLE_FULL_OK
eventWatermark=6
coveredEventWatermark=6
dirty=false
```

- Debug 记录 Stop 正常放行：`Hook Stop (Stop) success: {}`。
- 水位 6 与本轮 1 次 UserPromptSubmit、5 次 Skill 的 PostToolUse 一致；checkpoint MCP 调用未递归制造事件。

### 6.2 Stop fail-closed 与恢复

- 会话：`b8237ddb-255b-41df-8a98-ca3839ea0434`
- 模型先在不调用工具的情况下输出 `STOP_DIRTY_SENTINEL`。
- Stop Hook 真实返回：

```text
decision=block
CHECKPOINT_NOT_COVERED: checkpoint does not cover current event watermark 1
```

- 宿主继续运行模型；模型随后调用 `get`、按最新水位调用 `save`，最终输出 `STOP_RECOVERED`。
- Debug 随后记录 Stop 正常放行，进程退出 0。

### 6.3 陈旧水位冲突恢复

- 会话：`9b0edc2a-5e01-4d1b-a730-1469a9f0a913`
- 使用旧的 `coveredEventWatermark=6` 保存时，MCP 返回 `WATERMARK_MISMATCH`，当前事件水位为 7。
- 再次 `get` 得到 `eventWatermark=7`、`coveredEventWatermark=6`、`dirty=true`。
- 使用最新水位 7 重试成功，最终为 `7/7`、`dirty=false`。

### 6.4 默认数据目录

- 会话：`eab14ba0-efe8-4a2f-9816-c81022c8f979`
- 未设置 `NOVA_HOME`，真实 MCP 自动创建 `/tmp/nova-forge-full-e2e.pYYfxI/home-claude-single/.nova`。
- 最终状态：`eventWatermark=1`、`coveredEventWatermark=1`、`dirty=false`。
- 权限核验：根与 11 个子目录全部 `0700`，3 个文件全部 `0600`。

## 7. 阻断缺陷：Claude `/compact` 生命周期竞态

### 7.1 仅启用 Nova Forge 的复现结果

复现会话：`698891f5-7a8b-4db3-a054-de51b028b170`。Claude 隔离配置中仅启用 `nova-forge@nova-forge-full-e2e` 后再次执行 `/compact`，仍复现相同错误。

关键时间线：

| UTC 时间 | 事件 |
| --- | --- |
| `12:30:39.835` | Nova 状态记录 `frozenAt`，水位 6 |
| `12:30:39.855` | `PreCompact:manual` 完成，退出 0 |
| `12:32:20.211` | `SessionStart(compact)` 读取状态并生成 `COMPACTION_HANDSHAKE_MISMATCH` |
| `12:32:20.215` | `SessionStart(compact)` 返回 `continue=false` |
| `12:32:20.268` | 状态才记录 `completedAt`，水位 6 |
| `12:32:20.288` | `PostCompact:manual` 完成，退出 0 |

最终状态本身完整：

```text
trigger=manual
status=completed
frozenWatermark=6
completedWatermark=6
eventWatermark=6
coveredEventWatermark=6
dirty=false
```

问题在于 `SessionStart(compact)` 比 `completedAt` 早约 57 ms，比 PostCompact Hook 完成早约 73 ms。Nova 当前契约要求 SessionStart 只能消费已经完成的压缩检查点，因此会正确地 fail-closed，但无法适配 Claude Code 2.1.233 的实际 Hook 顺序。

### 7.2 影响

- PreCompact 和 PostCompact 单独执行均成功。
- Claude Code 自身报告 `compact_result=success`，CLI 进程也退出 0。
- 但 Nova 的压缩恢复胶囊没有在压缩后的即时 SessionStart 中注入。
- 用户会看到 Nova checkpoint safety gate 报错，无法获得承诺的同会话无缝续接。

### 7.3 建议验收门槛

在修复前，不应发布“Codex 与 Claude Code 全功能通过”的结论。修复后至少需要在 Claude Code 真实宿主中重新证明：

1. PreCompact 冻结检查点；
2. PostCompact 完成状态与 SessionStart(compact) 的顺序兼容；
3. SessionStart 注入正确 generation；
4. 压缩前标记可在压缩后立即恢复；
5. Stop 门禁仍保持 fail-closed，不因兼容修复而放宽。

## 8. 仓库级最终校验

| 校验 | 结果 |
| --- | --- |
| `validate_architecture.py --ready .nova/architecture/ARCHITECTURE_CONTRACTS.md` | PASS |
| `npm run check` | PASS，95/95 tests |
| Codex `validate_plugin.py .` | PASS |
| `claude plugin validate .` | PASS |
| `check:package` | PASS，108 files，697747 bytes |

## 9. 测试过程中的非产品问题

以下问题由隔离夹具或本机配置造成，不计为产品缺陷：

1. Codex 隔离目录起初只复制认证信息、未复制自定义 provider，误连官方端点并返回 401；补齐隔离 provider 配置后恢复。
2. 外层 `NOVA_HOME` 没有进入 Codex MCP 子进程，曾导致 Hook 与 MCP 状态根分裂并出现 `BINDING_UNAVAILABLE`；改用隔离 `HOME` 验证产品默认 `~/.nova` 路径后通过。
3. Claude 隔离配置中发现旧的 `nova-forge-local-e2e` 测试副本。禁用该副本后重跑 Skill/MCP/Stop；再禁用全部其他插件后重跑 `/compact`，阻断仍可复现。

## 10. 原始证据

完整证据保留在 `/tmp/nova-forge-full-e2e.pYYfxI`，本报告生成时未清理。关键文件：

- Codex Skill：`logs/codex-full-skills.jsonl`
- Codex MCP：`logs/codex-home-mcp.jsonl`
- Codex 压缩会话：`codex-home/sessions/2026/09/11/rollout-2026-09-11T19-50-58-01a0904e-7ce2-7f10-b15d-f5fe3f3631fa.jsonl`
- Claude 单 Nova Skill/MCP：`logs/claude-single-full.jsonl`
- Claude Stop：`logs/claude-single-stop.jsonl`、`logs/claude-single-stop.debug`
- Claude 默认 home：`logs/claude-single-home.jsonl`
- Claude 仅启用 Nova 的压缩复现：`logs/claude-only-compact.jsonl`、`logs/claude-only-compact.debug`
- Claude 水位恢复：`logs/claude-resume.jsonl`

`/tmp` 证据不是长期归档；如需提交缺陷或做发布门禁，应在清理前把相关日志复制到受控的外部归档位置，并按安全要求检查是否含有宿主上下文。
