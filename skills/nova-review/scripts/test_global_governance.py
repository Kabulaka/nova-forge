#!/usr/bin/env python3
"""Contract tests for the minimal global bootstrap kept in this workspace."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[3]
GLOBAL = (WORKSPACE / "codex" / "AGENTS.global.md").read_text(encoding="utf-8")
MIGRATION = (WORKSPACE / "codex" / "AGENTS.migration-map.md").read_text(encoding="utf-8")
IMPLEMENTATION = (
    WORKSPACE / "skills" / "nova-development" / "references" / "implementation-sop.md"
).read_text(encoding="utf-8")
FLOW_PROBE = WORKSPACE / "skills" / "nova-review" / "scripts" / "probe_default_flow.py"
SPEC = importlib.util.spec_from_file_location("nova_default_flow_probe", FLOW_PROBE)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class GlobalGovernanceTests(unittest.TestCase):
    def test_global_file_is_small_router_not_review_sop(self) -> None:
        routing = GLOBAL.split("## 技能路由", 1)[1].split("\n## ", 1)[0]
        self.assertLessEqual(len(GLOBAL.splitlines()), 100)
        self.assertLessEqual(len(GLOBAL.encode("utf-8")), 10_000)
        self.assertIn("使用 `nova-development`", GLOBAL)
        self.assertIn(
            "用户要求检查当前项目的 Nova 文档、引用、审计或迁移状态时使用 "
            "`nova-doctor`；只读检查调用时所在项目，不检查全局技能安装、技能源码更新"
            "或远端版本，也不自动修复或迁移。",
            routing,
        )
        self.assertNotIn("技能源码仓库", routing)
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

    def test_implementation_sop_keeps_stage_specific_completion_reports(self) -> None:
        for stage, title in (
            ("requirement", "需求完成报告"),
            ("architecture", "架构完成报告"),
            ("feature", "FEAT 完成报告"),
            ("patch", "PATCH 完成报告"),
            ("fix", "FIX 完成报告"),
            ("maintenance", "MAINT 完成报告"),
            ("review", "Review 完成报告"),
        ):
            self.assertIn(f"| `{stage}` | {title} |", IMPLEMENTATION)
        self.assertIn("实际完成了什么", IMPLEMENTATION)
        self.assertIn("刻意没有改什么", IMPLEMENTATION)
        self.assertIn("测试命令、工作目录、结果、覆盖验收", IMPLEMENTATION)
        self.assertIn("本地 commit hash 与中文主题", IMPLEMENTATION)
        self.assertIn("Review 策略与“未 Review/待Review”", IMPLEMENTATION)
        self.assertIn("validate-report --stage <stage>", IMPLEMENTATION)
        self.assertIn("项目外", IMPLEMENTATION)
        self.assertIn("校验失败不得发送", IMPLEMENTATION)
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

    def test_feature_patch_fix_and_audit_boundaries_are_explicit(self) -> None:
        self.assertIn("正式 `FEAT-*` 在 Review PASS 前保留于蓝图", GLOBAL)
        self.assertIn("`PATCH-*`、`FIX-*`、`MAINT-*` 不进入蓝图", GLOBAL)
        self.assertIn("`patch` 使用 `PATCH-*`，`Design-Ref: none`", GLOBAL)
        self.assertIn("`fix` 使用 `FIX-*`，`Design-Ref: none`", GLOBAL)
        self.assertIn("`maintenance` 使用 `MAINT-*`，`Design-Ref: none`", GLOBAL)
        self.assertIn("禁止写 `Review-State`", GLOBAL)
        self.assertIn("缺失、矛盾或无法证明的分类一律停止并重新路由", GLOBAL)
        self.assertIn("REJECT 轮次不产生 commit", GLOBAL)
        self.assertIn("一个包含全部 Review 修正、审计和投影关闭的 closure commit", GLOBAL)

    def test_repeatable_runtime_probe_covers_default_commit_and_manual_review(self) -> None:
        probe = FLOW_PROBE.read_text(encoding="utf-8")
        self.assertIn('"--json"', probe)
        self.assertIn("ordinary implementation did not create a local commit", probe)
        self.assertIn("ordinary implementation entered Review", probe)
        self.assertIn("explicit Review did not enter nova-review selection", probe)
        self.assertNotIn("commit", PROBE.ORDINARY_PROMPT.lower())
        self.assertNotIn("review", PROBE.ORDINARY_PROMPT.lower())

    def test_runtime_probe_requires_new_patch_uuid7_and_reuses_it_for_review(self) -> None:
        work_item = "PATCH-018f22e2-79b0-7abc-8123-456789abcdef"
        transcript = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": (
                        "python3 nova-review/scripts/nova_review.py "
                        "new-id --class patch"
                    ),
                },
            }
        )
        metadata = {"Work-Item": work_item}
        self.assertEqual(PROBE.generated_patch_work_item(metadata, transcript), work_item)
        self.assertIn(work_item, PROBE.explicit_review_prompt(work_item))

        with self.assertRaisesRegex(PROBE.ProbeError, "PATCH UUIDv7"):
            PROBE.generated_patch_work_item({"Work-Item": "PATCH-001"}, transcript)
        with self.assertRaisesRegex(PROBE.ProbeError, "new-id --class patch"):
            PROBE.generated_patch_work_item(metadata, "")

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
