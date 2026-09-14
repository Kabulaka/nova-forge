# 双宿主插件边界

## 目标

同一发布包为 Codex 和 Claude Code 提供相同的三个 Nova 技能与 SessionStart 规则注入，不引入常驻服务或项目状态。

## 组件

| 组件 | 权威入口 | 约束 |
|---|---|---|
| 技能 | `skills/nova-*/SKILL.md` | 两个宿主共享，不复制规则正文 |
| 全局规则 | `codex/AGENTS.global.md` | 由 Hook 读取并原样注入 |
| Hook | `hooks/hooks.json`、`hooks/run.mjs` | 只处理 SessionStart 的四个来源 |
| Codex 分发 | `.codex-plugin/plugin.json`、`.agents/plugins/marketplace.json` | 使用版本化 Git URL |
| Claude Code 分发 | `.claude-plugin/plugin.json`、`.claude-plugin/marketplace.json` | marketplace source 保持 `./` |

## 运行边界

- Hook 从宿主提供的绝对插件根读取规则，输出 `hookSpecificOutput.additionalContext`。
- 输入无效、插件根缺失或规则不可读时 fail open：写一条不含路径和输入内容的错误码，不阻断宿主。
- 插件不注册 MCP，不保存 checkpoint、会话、审计或项目状态，不接管宿主压缩与恢复。
- 发布包不包含仓库自身的 `.nova/`、测试或维护脚本。
