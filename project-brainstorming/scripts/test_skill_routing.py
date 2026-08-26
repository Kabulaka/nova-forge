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
DESIGN_STANDARD = (SKILL_ROOT / "references" / "design-document-standard.md").read_text(
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
        self.assertIn("访谈 SOP SHA-256", SKILL)
        self.assertIn("同一份稳定快照", SKILL)
        self.assertIn("在读取前后分别计算 SHA-256", SKILL)
        self.assertIn("两次不一致时丢弃正文并重新读取", SKILL)
        self.assertIn("每次继续访谈前", SKILL)
        self.assertIn("项目、路径、蓝图指纹和 SOP 指纹均未变化时", SKILL)
        self.assertIn("不要重读完整蓝图或访谈 SOP", SKILL)
        self.assertIn("SOP 指纹未记录或发生变化时只完整重读访谈 SOP", SKILL)
        self.assertIn("保留已确认的项目理解", SKILL)
        self.assertIn("连续变化则停止并报告", SKILL)
        self.assertIn("不得跨会话或跨项目复用缓存", SKILL)
        self.assertIn("本会话首次提问，或 SOP 指纹未记录/变化", SKILL)
        self.assertIn("会话未记录 SOP SHA-256、当前指纹与记录不同时完整读取", CONVERSATION_SOP)
        self.assertIn("SOP 指纹未变化时才复用", CONVERSATION_SOP)
        self.assertNotIn("蓝图指纹未变化时复用，不重复加载", CONVERSATION_SOP)

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

    def test_v3_legacy_design_name_routes_to_deterministic_path_migration(self) -> None:
        self.assertIn("出现旧式设计文件名时，只读取设计规范", SKILL)
        self.assertIn("不进入七章蓝图迁移决策门", SKILL)
        self.assertIn("当前文件连续版本控制谱系的首次加入日期", DESIGN_STANDARD)
        self.assertIn("无法证明、没有版本历史或不同证据冲突时停止迁移", DESIGN_STANDARD)
        self.assertIn("不得使用迁移当天日期", DESIGN_STANDARD)
        self.assertIn("旧式文件名迁移", MIGRATION_SOP)

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

    def test_terminal_design_requires_new_dated_evolution_document(self) -> None:
        self.assertIn("YYYY-MM-DD_具体名称.md", SKILL)
        self.assertIn("`已实现`、`已废弃`设计是终态历史快照", SKILL)
        self.assertIn("不得向终态文档追加工作包或改回非终态", SKILL)
        self.assertIn("通过“演进来源”链接旧设计", SKILL)

    def test_structured_question_route_is_capability_driven_and_cross_host(self) -> None:
        summary = CONVERSATION_SOP.index("### 阶段总结与交互载体")
        native_tool = CONVERSATION_SOP.index("宿主实际暴露原生结构化提问工具")
        self.assertLess(summary, native_tool)
        self.assertIn("`request_user_input`", CONVERSATION_SOP)
        self.assertIn("`AskUserQuestion`", CONVERSATION_SOP)
        self.assertIn("2–3 个真实、互斥且可解释取舍的方案", CONVERSATION_SOP)
        self.assertIn("推荐项排第一", CONVERSATION_SOP)
        self.assertIn("不根据宿主名称、模式名称或配置文件猜测", CONVERSATION_SOP)
        self.assertIn("不得为了显示选项自行切换 Plan mode", CONVERSATION_SOP)
        self.assertIn("不得修改宿主全局配置", CONVERSATION_SOP)
        self.assertIn("继续使用普通文本提出一个问题", CONVERSATION_SOP)
        self.assertIn("普通回复不得重复同一问题", CONVERSATION_SOP)
        self.assertIn("工具是否已呈现无法确认时停止", CONVERSATION_SOP)

    def test_structured_answer_continues_with_one_next_delta(self) -> None:
        continuation = CONVERSATION_SOP.index("### 结构化答案后的推进")
        self.assertGreater(continuation, CONVERSATION_SOP.index("### 阶段总结与交互载体"))
        self.assertIn("每个交互步", CONVERSATION_SOP)
        self.assertIn("不是整个 AI 执行周期只能调用一次提问工具", CONVERSATION_SOP)
        self.assertIn("立即调用下一次原生工具", CONVERSATION_SOP)
        self.assertIn("每次仍只呈现一个问题", CONVERSATION_SOP)
        self.assertIn("改用一个普通文本问题并等待", CONVERSATION_SOP)
        self.assertIn("选择项及其备注或自由补充作为同一答案", CONVERSATION_SOP)
        self.assertIn("最新明确补充覆盖选项的默认含义", CONVERSATION_SOP)
        self.assertIn("处理补充说明或输出确认都不是暂停或结束信号", CONVERSATION_SOP)

    def test_structured_answer_stops_only_at_explicit_boundaries(self) -> None:
        self.assertIn("话题闭环、用户要求暂停", CONVERSATION_SOP)
        self.assertIn("继续前必须研究或写入", CONVERSATION_SOP)
        self.assertIn("工具失败或呈现状态不明", CONVERSATION_SOP)
        self.assertIn("必须等待本次答案返回后再决定下一问", CONVERSATION_SOP)
        self.assertIn("不得预先提交、并发提问或重复刚回答的问题", CONVERSATION_SOP)

    def test_unanswered_structured_question_is_resumable(self) -> None:
        self.assertIn("工具返回空答案或 `0/1 answered` 时视为未回答", CONVERSATION_SOP)
        self.assertIn("不合并、不推进、不自动重试", CONVERSATION_SOP)
        self.assertIn("原样保留问题原文、选项顺序、标签和说明", CONVERSATION_SOP)
        self.assertIn("用原生工具原样重放该问题", CONVERSATION_SOP)
        self.assertIn("工具不可用时用普通文本完整列出原选项", CONVERSATION_SOP)
        self.assertIn("不得用缺少标签的 A/B/C 代替选项", CONVERSATION_SOP)

    def test_conversation_sop_preserves_frontstage_gates(self) -> None:
        self.assertLessEqual(len(CONVERSATION_SOP.splitlines()), 145)
        self.assertIn("### 单问题闸门", CONVERSATION_SOP)
        self.assertIn("只有一个需要用户回答的句子", CONVERSATION_SOP)
        self.assertIn("用用户可感知结果解释取舍并明确推荐", CONVERSATION_SOP)
        self.assertIn("## 3. 输出净化闸门", CONVERSATION_SOP)
        self.assertIn("删除孤立人名、无上下文英文", CONVERSATION_SOP)
        self.assertIn("架构与开发边界", CONVERSATION_SOP)


if __name__ == "__main__":
    unittest.main()
