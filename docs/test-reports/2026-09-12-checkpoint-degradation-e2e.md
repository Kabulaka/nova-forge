# Nova Forge checkpoint 异常降级与升级兼容实测报告

- 测试时间：2026-09-11 至 2026-09-12（Asia/Shanghai）
- 宿主：Codex CLI `0.154.0`、Claude Code `2.1.233`
- 架构契约：`ARCH-01a0911a-d22d-7220-826f-4cc801422f77`
- 修复工作项：`FIX-01a09114-bc2e-7c83-8eff-78dcdf9002a6`
- 被测代码：提交 `d296e95`（测试发生在提交前的同内容 staged 快照）
- Review 状态：`exempt`，规则 `EX-FIX`；未启动人工 Review
- 总体结论：**Codex 与 Claude Code 的 checkpoint 正常路径和异常降级路径均通过真实宿主测试；checkpoint 故障不再阻断宿主对话或原生压缩。**

## 1. 修正后的契约

旧设计把 checkpoint 连续性和宿主可用性绑定为同一个 fail-closed 门禁。首次升级、老会话、损坏状态、不可写数据目录、MCP 启动失败或 Claude 压缩 Hook 乱序时，Nova 会通过 `decision=block`、`continue=false` 或非零退出码停止宿主操作。

当前契约拆分为两个边界：

1. 宿主可用性始终放行。任何 Nova Hook、状态或 MCP 异常只能输出降级诊断，不得停止回答、会话恢复或原生压缩。
2. checkpoint 权威性仍失败封闭。缺失、损坏、过期或未覆盖的状态不得作为恢复胶囊注入；只能从可见会话和已验证工作区事实重建，未知项保持 pending。

因此“失败开放”只针对宿主操作，“失败封闭”仍适用于 Nova 状态权威。

## 2. 升级与异常矩阵

| 场景 | Codex | Claude Code | 权威保护 | 宿主结果 |
| --- | --- | --- | --- | --- |
| 首次安装，无历史 Nova 状态 | PASS | PASS | 不伪造历史胶囊 | 正常启动 |
| 安装前创建的真实旧会话再 resume | PASS | PASS | 仅注入静态规则和无权威恢复提示 | 正常回答，退出 0 |
| 当前水位未被 checkpoint 覆盖 | PASS | PASS | 不注入旧胶囊 | Stop 仅告警，不阻断 |
| checkpoint JSON 损坏 | PASS | PASS | 损坏内容不成为 authority | Hook 仅降级 |
| `NOVA_HOME` 不可初始化 | PASS | PASS | 不创建或猜测状态 | Hook 退出 0 |
| MCP 因状态根错误连接关闭 | PASS | PASS | 无 MCP 时不宣称已保存 | 宿主仍可回答 |
| Hook 输入非法 JSON | PASS | PASS | 不推进水位 | stderr 诊断，退出 0 |
| Hook 输入超过 256 MiB | PASS | PASS | 不推进水位 | stderr 诊断，退出 0 |
| Session ID、cwd 或事件 ID 缺失 | PASS | PASS | 不产生错误绑定 | 仅降级告警 |
| 安装路径含空格/Unicode/软链接 | PASS | PASS | 不改变状态契约 | 入口正常降级 |
| Claude `PreCompact → SessionStart(compact) → PostCompact` 乱序 | 不适用 | PASS | 早到的 SessionStart 不消费未完成状态 | 原生 compact 完成 |

所有降级输出均不含 `decision=block`、`continue=false` 或 `stopReason`。

## 3. Codex 真实宿主结果

### 3.1 状态根与 MCP 同时失败

将 `NOVA_HOME` 指向普通文件，使 Hook 状态初始化和 MCP 初始化同时失败。真实 Codex 会话中：

- `SessionStart`、`UserPromptSubmit`、`Stop` 均完成；
- 没有 `Hook stopped`；
- 模型返回 `CODEX_FAILOPEN_OK`；
- Codex 进程退出码为 0。

### 3.2 正常 MCP 往返

通过正式插件 MCP 完成 `nova_checkpoint_get → nova_checkpoint_save → nova_checkpoint_get`：

```text
eventWatermark=2
coveredEventWatermark=2
dirty=false
```

### 3.3 真实旧会话升级

先在未安装 Nova 的隔离 Codex 环境创建会话，再安装当前开发快照并 resume 同一会话：

```text
session_id=01a0913c-4512-74b2-8517-31fa2acf3249
result=CODEX_LEGACY_RESUME_OK
exit_code=0
```

旧会话没有历史 checkpoint 时不会被阻断，也不会获得伪造的恢复权威。

## 4. Claude Code 真实宿主结果

### 4.1 状态根与 MCP 同时失败

将 `NOVA_HOME` 指向普通文件后，Claude debug 日志明确记录：

```text
STATE_ROOT_UNAVAILABLE
MCP server "nova-checkpoint": Connection failed
```

同一会话中 `SessionStart`、`UserPromptSubmit`、`Stop` 均 success，模型返回 `CLAUDE_FAILOPEN_OK`，进程退出码为 0。

### 4.2 正常 MCP 往返

使用 Claude 正式插件 MCP 工具前缀完成 get/save/get：

```text
eventWatermark=1
coveredEventWatermark=1
dirty=false
```

### 4.3 真实旧会话升级

先用 `--safe-mode` 创建无 Nova 会话，再启用当前插件并 resume：

```text
session_id=f20455fb-97b9-41c4-996b-fc4e4409d5e2
result=CLAUDE_LEGACY_RESUME_OK
exit_code=0
```

SessionStart 注入静态规则和无权威恢复提示；Stop 只返回降级 `systemMessage`，不含阻断字段。

### 4.4 真实 `/compact`

Claude Code `2.1.233` 的真实顺序为：

```text
PreCompact → SessionStart(source=compact) → PostCompact
```

早到的 SessionStart 返回 `<nova-checkpoint-degraded>`，没有 `continue=false`；随后 PostCompact 正常完成。最终状态为：

```text
eventWatermark=1
coveredEventWatermark=1
dirty=false
compactionHandshake.status=completed
exit_code=0
```

## 5. 仓库级回归覆盖

定向测试覆盖：首次安装、不可用状态根、未覆盖水位、损坏状态、旧会话 resume、Claude 压缩乱序、PostCompact 不匹配、缺失绑定字段、非法输入、超限输入和特殊安装路径。

本报告形成时的定向结果：

```text
node --test tests/hook-adapter.test.mjs  # 20/20 PASS
node scripts/validate-plugin.mjs         # PASS
node scripts/sync-version.mjs --check    # PASS
```

FIX 提交前最终校验：

```text
npm run check                                                     # PASS, 102/102 tests
node scripts/check-package.mjs                                    # PASS, 108 files, 698986 bytes
python3 skills/nova-development/scripts/validate_blueprint.py ... # PASS
python3 skills/nova-architecture/scripts/validate_architecture.py --ready ... # PASS
python3 .../plugin-creator/scripts/validate_plugin.py .            # PASS
git diff --check                                                   # PASS
```

## 6. 结论边界

本轮证明的是当前开发快照在隔离的真实 Codex 和 Claude Code 宿主中可用。它不等于：

- 用户当前已安装该快照；
- GitHub Marketplace 已发布新版本；
- 已启动或通过人工 Review；
- `/tmp` 原始日志属于长期归档。

本轮没有修改真实宿主的启用状态。收尾检查时，Codex 开发插件
`0.2.0+codex.local-20260911t150353z` 为禁用；Claude Code 仍启用了旧的
`nova-forge@nova-forge-local-e2e 0.2.0` 测试副本，该副本不含本 FIX，不能代表本报告被测快照。

## 7. 原始证据

临时证据根：`/tmp/nova-failopen-e2e.xYrTPb`

- Codex 失败降级结果：`codex-invalid-root-final.txt`
- Codex 正常 MCP 结果：`codex-valid-final.txt`
- Codex 旧会话创建记录：`codex-legacy-created.txt`
- Claude 状态根/MCP 失败：`claude-invalid-root.debug`
- Claude 正常 MCP：`claude-valid-prefixed.debug`
- Claude 旧会话升级：`claude-legacy-resume.debug`
- Claude 真实压缩：`claude-compact-current.debug`

`/tmp` 证据可能被系统清理；发布或外部审计前应复制到受控位置，并先检查日志是否包含宿主上下文。
