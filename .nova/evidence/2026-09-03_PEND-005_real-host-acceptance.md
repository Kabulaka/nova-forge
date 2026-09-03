# PEND-005 真实宿主验收证据

> 验收时间：2026-09-03（Asia/Shanghai）
> 规则源：`codex/AGENTS.global.md`
> 规则 SHA-256：`13ea1d715f397d5daa9328c1bec16c44f5104bda4ae350f8be2145502c30f1fd`

## 1. 安装与发现

- Codex：`codex-cli 0.152.1`
- Claude Code：`2.1.233`
- `~/.codex/AGENTS.md` 与 `~/.claude/CLAUDE.md` 均解析到当前工作区的 `codex/AGENTS.global.md`。
- `python3 nova-review/scripts/validate_discovery.py --workspace "$PWD" --codex-home ~/.codex --claude-home ~/.claude`：`PASS`。
- Claude Code 中的失效 `project-brainstorming` 旧别名软链接已由安装器解除，链接原目标未删除。

## 2. 双宿主真实规则加载

在无项目规则的临时目录启动两个宿主，要求在不读文件、不调用工具的前提下复述全局规则中的行为准则第 1 条与压缩续接第 6 条的三级优先级。

Codex 输出：

```text
予命汝为大匠，操百工之柄，执规矩，定方圆。
当前用户明确指令 > 项目规则 > 本文件全局默认规则
```

Claude Code 输出的两项内容逐字相同。这两句均为当前规则源的专有文本，证明两个宿主在真实启动中加载了安装后的用户级入口。

## 3. Codex 真实压缩续接

- 会话 ID：`01a064de-1074-7550-b247-17334d319ed0`
- 原始 JSONL：`/home/nika/.codex/sessions/2026/09/03/rollout-2026-09-03T09-24-29-01a064de-1074-7550-b247-17334d319ed0.jsonl`
- JSONL SHA-256：`ddcfd51eaa037dbf1c8f43060c3492df4ba7b98f6afcc049c9af9ecc99de7cf7`
- 压缩事件：JSONL `ordinal=21`，`type=compacted`，`window_number=1`。
- 续接结果：JSONL `ordinal=40` 的 `AgentMessage`。
- 定向解析校验：`compacted=1 window=1 state_checks=13/13 continuation=PASS`。

压缩前注入的全部值均为合成非秘密验收数据。执行真实 `/compact` 后，宿主摘要显式保留了：

- 当前目标与阶段、用户已确认决定、明确排除、委托范围、AI 候选身份、未决差量和当前问题；
- 活动交付范围、有效证据、文件与提交状态、下一动作；
- 控制文档绝对路径与 64 位 SHA-256。

续接回答逐项复述了上述值，并明确输出：

```text
AI候选身份=候选“添加索引”，未确认
未决差量=Claude压缩行为
候选是否已被提升为确认=否
```

## 4. 能力边界

本证据证明当前版本的两个宿主加载同一规则，且 Codex 的一次真实压缩成功续接全部验收状态。它不证明任何宿主、模型或后续版本在每次压缩中绝不遗漏，也不代表 Claude Code 的压缩行为已单独验收。
