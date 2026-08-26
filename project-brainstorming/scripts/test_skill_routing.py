#!/usr/bin/env python3
"""Contract tests for project-brainstorming context and resource routing."""

from __future__ import annotations

import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
CONVERSATION_SOP = (SKILL_ROOT / "references" / "conversation-sop.md").read_text(
    encoding="utf-8"
)
MIGRATION_SOP = (SKILL_ROOT / "references" / "blueprint-migration-sop.md").read_text(
    encoding="utf-8"
)


class SkillRoutingContractTests(unittest.TestCase):
    def test_entrypoint_is_compact_and_routes_conditional_detail(self) -> None:
        self.assertLessEqual(len(SKILL.splitlines()), 120)
        self.assertLessEqual(len(SKILL), 8_000)
        self.assertIn("## 资源路由", SKILL)
        self.assertIn("references/conversation-sop.md", SKILL)
        self.assertIn("references/blueprint-migration-sop.md", SKILL)

    def test_target_is_resolved_before_blueprint_loading(self) -> None:
        self.assertIn("先定位项目，再加载上下文", SKILL)
        self.assertIn("只因当前目录存在蓝图，不得把它当成目标项目", SKILL)
        self.assertIn("目标根目录绝对路径", SKILL)

    def test_session_cache_requires_same_project_path_and_fingerprint(self) -> None:
        self.assertIn("蓝图 SHA-256", SKILL)
        self.assertIn("同一份稳定快照", SKILL)
        self.assertIn("在读取前后分别计算 SHA-256", SKILL)
        self.assertIn("两次不一致时丢弃正文并重新读取", SKILL)
        self.assertIn("项目、路径和指纹均未变化时", SKILL)
        self.assertIn("不要重读完整蓝图或访谈 SOP", SKILL)
        self.assertIn("指纹变化时立即废弃旧理解并完整重读", SKILL)
        self.assertIn("不得跨会话或跨项目复用缓存", SKILL)

    def test_v3_skips_migration_but_legacy_and_audit_load_it(self) -> None:
        existence_check = SKILL.index("检查精确蓝图路径是否存在")
        no_blueprint = SKILL.index("蓝图不存在时记录“无蓝图”")
        full_read = SKILL.index("同一份稳定快照取得全文")
        version_route = SKILL.index("## 2. 按蓝图版本路由")
        self.assertLess(existence_check, no_blueprint)
        self.assertLess(no_blueprint, full_read)
        self.assertLess(full_read, version_route)
        self.assertIn("不得对不存在的文件计算 SHA-256 或要求全文", SKILL)
        self.assertIn("蓝图存在时再完成稳定快照全文读取", SKILL)
        self.assertIn("不得用单独读取版本标记替代首次完整读取", SKILL)
        self.assertIn("明确为版本 3：正常澄清和只读分析不加载迁移 SOP", SKILL)
        self.assertIn("用户明确要求迁移审计时例外", SKILL)
        self.assertIn("已存在蓝图但版本标记缺失", SKILL)
        self.assertNotIn("现有蓝图存在时，完整读取", SKILL)
        self.assertIn("不存在蓝图的新项目不属于迁移", MIGRATION_SOP)
        self.assertIn("显式迁移审计是唯一例外", MIGRATION_SOP)

    def test_legacy_migration_choice_blocks_feature_clarification(self) -> None:
        self.assertIn("进入迁移决策门", SKILL)
        self.assertIn("逐项列明新版七章职责", SKILL)
        self.assertIn("原标题或摘要列出每段待归档局部内容", SKILL)
        self.assertIn("先澄清后升级、立即升级、暂不升级", SKILL)
        self.assertIn("禁止追问待办功能、加载蓝图规范、创建或修改文档、运行校验器", SKILL)
        self.assertIn("不得替用户决定", SKILL)
        self.assertIn("不能仅凭章节标题判断", MIGRATION_SOP)
        self.assertIn("七章不得合并成", MIGRATION_SOP)

    def test_validation_runs_only_at_document_write_boundaries(self) -> None:
        self.assertIn("创建、修改或迁移蓝图/设计", SKILL)
        self.assertIn("改变待办引用、工作包状态或文档生命周期", SKILL)
        self.assertIn("纯头脑风暴、继续提问、解释规则、读取项目和只读分析不运行校验器", SKILL)

    def test_conversation_sop_preserves_frontstage_gates(self) -> None:
        self.assertLessEqual(len(CONVERSATION_SOP.splitlines()), 140)
        self.assertIn("### 单问题闸门", CONVERSATION_SOP)
        self.assertIn("只有一个需要用户回答的句子", CONVERSATION_SOP)
        self.assertIn("用用户可感知结果解释取舍并明确推荐", CONVERSATION_SOP)
        self.assertIn("## 3. 输出净化闸门", CONVERSATION_SOP)
        self.assertIn("删除孤立人名、无上下文英文", CONVERSATION_SOP)
        self.assertIn("架构与开发边界", CONVERSATION_SOP)


if __name__ == "__main__":
    unittest.main()
