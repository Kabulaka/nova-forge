#!/usr/bin/env python3
"""Contract tests for the minimal global bootstrap kept in this workspace."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
GLOBAL = (WORKSPACE / "codex" / "AGENTS.global.md").read_text(encoding="utf-8")
MIGRATION = (WORKSPACE / "codex" / "AGENTS.migration-map.md").read_text(encoding="utf-8")
IMPLEMENTATION = (
    WORKSPACE / "nova-development" / "references" / "implementation-sop.md"
).read_text(encoding="utf-8")
FLOW_PROBE = WORKSPACE / "nova-review" / "scripts" / "probe_default_flow.py"
SPEC = importlib.util.spec_from_file_location("nova_default_flow_probe", FLOW_PROBE)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class GlobalGovernanceTests(unittest.TestCase):
    def test_global_file_is_small_router_not_review_sop(self) -> None:
        self.assertLessEqual(len(GLOBAL.splitlines()), 100)
        self.assertLessEqual(len(GLOBAL.encode("utf-8")), 10_000)
        self.assertIn("使用 `nova-development`", GLOBAL)
        self.assertIn("使用 `nova-review`", GLOBAL)
        self.assertIn("不得以“保持全局文件简短”为由删除", GLOBAL)
        self.assertNotIn("Observation-Fix", GLOBAL)
        self.assertNotIn("close_agent", GLOBAL)

    def test_original_behavior_maxims_are_preserved_verbatim(self) -> None:
        for maxim in (
            "予命汝为大匠，操百工之柄，执规矩，定方圆。",
            "见辞必究其本意，发语必直击要害。",
            "行文不流于浮华，求实而不务虚名。",
            "凡出方策，务期一发而中；遇有疑难，需析毫厘之微。",
            "落笔必先推其理，探赜索隐而后动。",
            "遇阙务须悬笔问，慎防凭空筑虚基。",
            "毋多言，毋饰非，克己奉公，一以贯之。",
        ):
            self.assertIn(maxim, GLOBAL)

    def test_fast_development_and_manual_review_are_separate(self) -> None:
        self.assertIn("不得自动启动 Review", GLOBAL)
        self.assertIn("本地 Git commit 的持续授权", GLOBAL)
        self.assertIn("Git push、远程配置和 SVN commit", GLOBAL)
        self.assertIn("用户可随时要求先调试、暂停或取消", GLOBAL)
        self.assertIn("Plan mode 本身不自动授权或启动 Review", GLOBAL)

    def test_context_mode_routing_is_precise_and_bounded(self) -> None:
        self.assertIn("最多 40 行且 UTF-8 不超过 4KB", GLOBAL)
        self.assertIn("裁剪时显式标记", GLOBAL)
        self.assertIn("禁止输出完整 `FILE_CONTENT` 或完整工具结果对象", GLOBAL)
        self.assertIn("一次性过滤、统计或聚合优先使用 `ctx_execute`", GLOBAL)
        self.assertIn("带显式 `limit` 的 `ctx_search`", GLOBAL)
        self.assertIn("已知名称和参数的延迟工具直接调用", GLOBAL)
        self.assertIn("按完整工具名精确 `find`", GLOBAL)
        self.assertIn("禁止用 `filter`、`includes` 或宽泛正则枚举 `ALL_TOOLS`", GLOBAL)
        self.assertIn("不自动安装或重复探测", GLOBAL)

    def test_implementation_sop_keeps_full_completion_report(self) -> None:
        for heading in (
            "### 概要",
            "### 变更文件",
            "### 关键决策",
            "### 测试结果",
            "### 提交结果",
            "### Review 结果",
            "### .nova/PROJECT_BLUEPRINT.md 与设计更新",
            "### 基线与清理",
            "### 遗留事项",
        ):
            self.assertIn(heading, IMPLEMENTATION)
        self.assertIn("未 Review", IMPLEMENTATION)
        self.assertIn("失效与重跑原因", IMPLEMENTATION)
        for field in (
            "**工作项**",
            "**变更分类**",
            "**Review 策略**",
            "**执行命令与工作目录**",
            "**相关状态**",
            "**未验证事项**",
            "**本地 commit**",
            "**精确范围**",
            "**远程与 SVN**",
            "**内容标识与范围**",
            "**历史工作副本隔离**",
            "**临时基线材料**",
        ):
            self.assertIn(field, IMPLEMENTATION)
        self.assertIn("章节不得省略", IMPLEMENTATION)
        self.assertIn("两者都不是 Review PASS", IMPLEMENTATION)
        self.assertIn("合法客观豁免写 `exempt` 并核对", IMPLEMENTATION)
        self.assertIn("未 Review 或 exempt 时写“不适用”", IMPLEMENTATION)
        self.assertIn("完整 diff 命中证据", IMPLEMENTATION)
        self.assertIn("不得把自检、测试或豁免表述为 Review PASS", GLOBAL)

    def test_every_legacy_clause_has_a_migration_entry(self) -> None:
        groups = {
            "A": 7, "L": 4, "K": 9, "B": 8, "P": 6, "C": 7,
            "T": 2, "E": 6, "S": 6, "I": 4, "Q": 7, "G": 10,
            "J": 13, "X": 12, "O": 3, "Z": 3, "W": 3, "F": 4, "M": 9,
        }
        expected = {
            f"{prefix}{number}"
            for prefix, count in groups.items()
            for number in range(1, count + 1)
        }
        expected.add("R0")
        actual = {
            line.split("|", 2)[1].strip()
            for line in MIGRATION.splitlines()
            if line.startswith("|")
            and line.split("|", 2)[1].strip() not in {"ID", "----"}
        }
        self.assertEqual(actual, expected)
        self.assertIn("显式替换", MIGRATION)

    def test_pending_and_adhoc_audit_boundaries_are_explicit(self) -> None:
        self.assertIn("正式 `PEND-*` 在 Review PASS 前保留于蓝图", GLOBAL)
        self.assertIn("`FIX-*` 不进入蓝图", GLOBAL)
        self.assertIn("`adhoc` 使用 `FIX-*`，`Design-Ref: none`", GLOBAL)
        self.assertIn("`maintenance` 使用 `MAINT-*`，`Design-Ref: none`", GLOBAL)
        self.assertIn("不得在不可变 commit 中写 `Review-State`", GLOBAL)
        self.assertIn("缺失、矛盾或无法证明的分类一律按需要 Review", GLOBAL)

    def test_repeatable_runtime_probe_covers_default_commit_and_manual_review(self) -> None:
        probe = FLOW_PROBE.read_text(encoding="utf-8")
        self.assertIn('"--json"', probe)
        self.assertIn("ordinary implementation did not create a local commit", probe)
        self.assertIn("ordinary implementation entered Review", probe)
        self.assertIn("explicit Review did not enter nova-review selection", probe)
        self.assertNotIn("commit", PROBE.ORDINARY_PROMPT.lower())
        self.assertNotIn("review", PROBE.ORDINARY_PROMPT.lower())

    def test_runtime_probe_requires_new_fix_uuid7_and_reuses_it_for_review(self) -> None:
        work_item = "FIX-018f22e2-79b0-7abc-8123-456789abcdef"
        transcript = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": (
                        "python3 nova-review/scripts/nova_review.py "
                        "new-id --class adhoc"
                    ),
                },
            }
        )
        metadata = {"Work-Item": work_item}
        self.assertEqual(PROBE.generated_adhoc_work_item(metadata, transcript), work_item)
        self.assertIn(work_item, PROBE.explicit_review_prompt(work_item))

        with self.assertRaisesRegex(PROBE.ProbeError, "FIX UUIDv7"):
            PROBE.generated_adhoc_work_item({"Work-Item": "FIX-001"}, transcript)
        with self.assertRaisesRegex(PROBE.ProbeError, "new-id --class adhoc"):
            PROBE.generated_adhoc_work_item(metadata, "")

    def test_runtime_probe_detects_collaboration_and_select_event_shapes(self) -> None:
        collaboration = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "collaboration",
                    "tool": "spawn_agent",
                    "arguments": {"task": "review"},
                },
            }
        )
        select = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "python3 nova_review.py select --mode explicit",
                },
            }
        )
        benign = json.dumps(
            {"type": "item.completed", "item": {"type": "command_execution", "command": "git status"}}
        )
        self.assertTrue(PROBE.review_invocations(collaboration))
        self.assertTrue(PROBE.review_invocations(select))
        self.assertEqual(PROBE.review_invocations(benign), [])


if __name__ == "__main__":
    unittest.main()
