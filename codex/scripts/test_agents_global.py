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
        self.assertIn("属于指令加载，不按普通大文件分析处理", AGENTS)
        self.assertIn("不得先 `wc`、预设固定行窗口", AGENTS)
        self.assertIn("用 `ctx_execute_file` 摘要替代正文", AGENTS)
        self.assertIn("只有工具明确截断时才从未返回位置续读", AGENTS)
        self.assertIn("资源绝对路径与 SHA-256", AGENTS)
        self.assertIn("不得因 UI 的重复 `Read` 或 `PostToolUse` 展示再次读取", AGENTS)


if __name__ == "__main__":
    unittest.main()
