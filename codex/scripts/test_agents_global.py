#!/usr/bin/env python3
"""Contract tests for global Codex context and resource routing."""

from __future__ import annotations

import unittest
from pathlib import Path


AGENTS = (Path(__file__).resolve().parents[1] / "AGENTS.global.md").read_text(
    encoding="utf-8"
)


class AgentsGlobalContractTests(unittest.TestCase):
    def test_required_control_documents_are_not_prechunked_or_summarized(self) -> None:
        control_section = self._section("技能控制文档加载")
        context_mode_section = self._section("Context-mode 可选路由")

        self.assertIn("属于指令加载，不按普通大文件分析处理", control_section)
        self.assertIn("不得先 `wc`、预设固定行窗口", control_section)
        self.assertIn("摘要替代正文", control_section)
        self.assertIn("只有工具明确截断时才从未返回位置续读", control_section)
        self.assertIn("资源绝对路径与 SHA-256", control_section)
        self.assertIn(
            "不得因 UI 的重复 `Read` 或 `PostToolUse` 展示再次读取",
            control_section,
        )
        self.assertNotIn("仅当当前会话提供 context-mode", control_section)
        self.assertNotIn("已命中技能后必须完整读取", context_mode_section)

    def test_compaction_contract_preserves_state_and_reuses_control_documents(self) -> None:
        section = self._section("上下文压缩与续接")

        for required in (
            "当前目标与阶段",
            "用户已确认决定",
            "明确排除",
            "委托范围",
            "AI 候选身份",
            "未决差量",
            "当前问题",
            "活动交付范围",
            "有效证据",
            "文件与提交状态",
            "下一动作",
            "控制文档的绝对路径与 SHA-256",
        ):
            self.assertIn(required, section)
        self.assertIn("不得把已回答事项重置为待确认", section)
        self.assertIn("不得把候选决定提升为用户确认", section)
        self.assertIn("不得把暂存范围提升为当前范围", section)
        self.assertIn("不得为了保险重复全文读取", section)
        self.assertIn("逐字模板、提交契约、Review 状态格式", section)
        self.assertIn("只询问缺失的具体差量", section)
        self.assertIn("秘密不得写入压缩摘要", section)
        self.assertIn("新会话不自动继承旧会话任务", section)
        self.assertIn("提示约束下的尽力保证", section)
        self.assertIn(
            "当前用户明确指令 > 项目规则 > 本文件全局默认规则", section
        )
        self.assertIn("不得阻断更高优先级的明确选择", section)

    def test_fix_defaults_to_exempt_and_keeps_explicit_review_available(self) -> None:
        section = self._section("工作项与提交")

        self.assertIn("默认 exempt + EX-FIX", section)
        self.assertIn("提交前指定 Review 用 required + none", section)
        self.assertIn("已提交未归档 EX-FIX 可按编号 Review", section)
        self.assertIn("current/all", self._section("人工 Review"))
        self.assertIn("PASS 生成审计", self._section("人工 Review"))

    def _section(self, title: str) -> str:
        marker = f"## {title}\n"
        self.assertIn(marker, AGENTS)
        section = AGENTS.split(marker, 1)[1]
        return section.split("\n## ", 1)[0]


if __name__ == "__main__":
    unittest.main()
