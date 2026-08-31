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

    def _section(self, title: str) -> str:
        marker = f"## {title}\n"
        self.assertIn(marker, AGENTS)
        section = AGENTS.split(marker, 1)[1]
        return section.split("\n## ", 1)[0]


if __name__ == "__main__":
    unittest.main()
