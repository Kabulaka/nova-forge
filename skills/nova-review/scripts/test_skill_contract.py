#!/usr/bin/env python3
"""Contract tests for the concise nova-review entrypoint and routed SOPs."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
COMMIT = (ROOT / "references/commit-contract.md").read_text(encoding="utf-8")
REVIEW = (ROOT / "references/review-sop.md").read_text(encoding="utf-8")
AUDIT = (ROOT / "references/audit-contract.md").read_text(encoding="utf-8")
IMPLEMENTATION = (
    ROOT.parent / "nova-development" / "references" / "implementation-sop.md"
).read_text(encoding="utf-8")


class NovaReviewSkillContractTests(unittest.TestCase):
    def test_entrypoint_is_compact_and_manual_only(self) -> None:
        self.assertLessEqual(len(SKILL.splitlines()), 100)
        self.assertIn("name: nova-review", SKILL)
        self.assertIn("技能被加载不等于用户已授权启动 Review", SKILL)
        self.assertIn("普通实现、测试和本地 commit 不得自动进入本流程", SKILL)
        self.assertIn("用户要求先调试、继续修改、暂停或取消 Review", SKILL)

    def test_selection_has_three_non_overlapping_user_intents(self) -> None:
        self.assertIn("裸“开始 Review”", SKILL)
        self.assertIn("用户列出编号", SKILL)
        self.assertIn("用户明确“全部未审查项”", SKILL)
        self.assertIn("历史中不属于这些编号的旧改动不得纳入", SKILL)

    def test_commit_contract_has_stable_identity_and_fail_closed_exemptions(self) -> None:
        for trailer in (
            "Nova-Schema",
            "Work-Item",
            "Change-Class",
            "Design-Ref",
            "Review-Policy",
            "Exemption-Rule",
            "Validation",
        ):
            self.assertIn(trailer, COMMIT)
        self.assertIn("工作项 ID 是一个独立、内聚、可控交付单元的跨会话稳定身份", COMMIT)
        self.assertIn("流程阶段", COMMIT)
        self.assertIn("内部里程碑", COMMIT)
        self.assertIn("可信审计归档是不可逆终态", COMMIT)
        self.assertIn("Related-Work-Item", COMMIT)
        self.assertIn("蓝图删除活动行不释放编号", AUDIT)
        self.assertIn("无法证明是 `adhoc` 或 `maintenance` 时使用 `designed`", COMMIT)
        self.assertNotIn("EX-REVIEW-RECORD", COMMIT)
        self.assertIn("Nova-Audit-Schema", COMMIT)
        self.assertIn("Git push、远程配置和 SVN commit", COMMIT)

    def test_review_and_audit_rules_are_routed_not_duplicated(self) -> None:
        self.assertIn("显式 `reasoning_effort` 参数", REVIEW)
        self.assertIn("默认与主代理当前思考度一致", REVIEW)
        self.assertIn("才可比主代理调高一档", REVIEW)
        self.assertIn("超过 10 个文件或新增行超过 1000 行", REVIEW)
        self.assertIn("不得依赖截断结果作结论", REVIEW)
        self.assertIn("本轮立即失效且不得输出任何结论", REVIEW)
        self.assertIn("最多三轮", REVIEW)
        self.assertIn("followup_task", REVIEW)
        self.assertIn("禁止主动 `close_agent`", REVIEW)
        self.assertIn("turn_aborted", REVIEW)
        self.assertIn("空响应、中间消息", REVIEW)
        self.assertIn("未 Review", IMPLEMENTATION)
        self.assertIn("### Review 结果", IMPLEMENTATION)
        self.assertIn("未 Review 或 exempt 时写“不适用”", IMPLEMENTATION)
        self.assertIn("完整 diff 命中证据", IMPLEMENTATION)
        self.assertIn("features/", AUDIT)
        self.assertIn("reviews/", AUDIT)
        self.assertIn("index/", AUDIT)
        self.assertIn("package_ids", AUDIT)
        self.assertIn("review_round", AUDIT)
        self.assertIn("review_content_sha256", AUDIT)
        self.assertIn("review_scope", AUDIT)
        self.assertIn("真实 staged diff", AUDIT)
        self.assertIn("Git index", AUDIT)
        self.assertIn("Nova-Audit-Schema", AUDIT)
        self.assertIn("同一 `batch_id` 与完全相同内容可重复调用", AUDIT)
        self.assertEqual(SKILL.count("Observation-Fix"), 1)
        self.assertNotIn("Observation-Defer", SKILL)

    def test_pass_completion_report_routes_to_fixed_implementation_template(self) -> None:
        authority_link = "[实施与交付 SOP](../nova-development/references/implementation-sop.md)"
        self.assertIn(authority_link, SKILL)
        self.assertNotIn("implementation-sop.md#", SKILL)
        self.assertIn("关闭提交完成且 `query` 可信校验通过后", SKILL)
        self.assertIn("完整读取整个", SKILL)
        self.assertIn("严格使用其第 7 节固定结构", SKILL)
        self.assertIn("所有章节不得省略", SKILL)
        self.assertIn("不得用简化的 Review 摘要替代固定完成报告", SKILL)
        self.assertIn(
            "`../nova-development/references/implementation-sop.md` 完整文件；最终报告使用第 7 节",
            SKILL,
        )
        for heading in (
            "概要",
            "变更文件",
            "关键决策",
            "测试结果",
            "提交结果",
            "Review 结果",
            ".nova/PROJECT_BLUEPRINT.md 与设计更新",
            "基线与清理",
            "遗留事项",
        ):
            self.assertIn(f"### {heading}", IMPLEMENTATION)


if __name__ == "__main__":
    unittest.main()
