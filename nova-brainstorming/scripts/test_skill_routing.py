#!/usr/bin/env python3
"""Contract tests for nova-brainstorming context and resource routing."""

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
IMPLEMENTATION_SOP = (SKILL_ROOT / "references" / "implementation-sop.md").read_text(
    encoding="utf-8"
)
DESIGN_STANDARD = (SKILL_ROOT / "references" / "design-document-standard.md").read_text(
    encoding="utf-8"
)
CONVERGENCE_DESIGN = (
    SKILL_ROOT.parent / "docs" / "design" / "2026-08-26_访谈收敛判定与连续推进.md"
).read_text(encoding="utf-8")
BLUEPRINT_EXAMPLE = SKILL_ROOT / "references" / "examples" / "equipment-borrowing" / "PROJECT_BLUEPRINT.md"
DESIGN_EXAMPLE = (
    SKILL_ROOT
    / "references"
    / "examples"
    / "equipment-borrowing"
    / "docs"
    / "design"
    / "2026-08-25_设备借用闭环.md"
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

    def test_confirmed_work_package_uses_minimal_implementation_handoff(self) -> None:
        pre_route = SKILL.index("### 实施请求前置路由")
        first_entry = SKILL.index("### 首次进入或状态失效")
        version_route = SKILL.index("## 2. 按蓝图版本路由")
        self.assertLess(pre_route, first_entry)
        self.assertLess(pre_route, version_route)
        self.assertIn("此路由优先于下述首次进入和蓝图版本路由", SKILL)
        self.assertIn("不得在确认交接资格前把蓝图全文展开到模型上下文", SKILL)
        self.assertIn("只有无法通过定向读取判断阻断原因时", SKILL)
        self.assertIn("未命中实施请求前置路由且发生任一情况时", SKILL)
        self.assertIn("未命中实施请求前置路由时，首次进入或缓存失效", SKILL)
        self.assertIn("### 已确认工作包的实施交接", SKILL)
        self.assertIn("具有已确认设计依据和可执行验收标准", SKILL)
        self.assertIn("不重新运行需求访谈", SKILL)
        self.assertIn("只读取该条目、所引工作包、直接依赖", SKILL)
        self.assertIn("不重读完整蓝图、访谈 SOP 或已闭环关系", SKILL)
        self.assertIn("用户明确启动 Review 时再转交 `nova-review`", SKILL)
        self.assertIn("上下文压缩、自检、显式 Review 或继续修改不使交接失效", SKILL)
        self.assertIn("除已保存实施交接且其列明的失效条件均未发生外", SKILL)
        self.assertIn("条目仍为“待澄清”", SKILL)
        self.assertIn("版本 `5` 收敛确认无效或契约相互冲突时，不得实施", SKILL)
        self.assertIn("版本 `5` 收敛确认缺失或失配", SKILL)
        self.assertIn("既有版本 `4` 设计保持交接兼容", SKILL)
        self.assertIn("默认实施流程是编码、最低验收", SKILL)
        self.assertIn("不得自动启动 Review", SKILL)
        self.assertIn("正式 `PEND-*` 在 Review PASS 前继续保留于蓝图", SKILL)
        self.assertIn("只有修正仍服务于原设计和验收才沿用同一编号", SKILL)
        self.assertIn("可信审计归档后编号永久封存", SKILL)
        self.assertIn("Related-Work-Item", SKILL)
        self.assertIn("push 和 SVN commit 必须另行授权", SKILL)
        self.assertIn("Review 中断则保留 `待Review` 并返回调试", SKILL)
        self.assertIn(
            "Review-Defer、新增待办及无关蓝图变化不自动进入当前范围，也不得复用当前工作项",
            SKILL,
        )
        self.assertIn("当前 Review 的 `Observation-Fix`/Review 修复", IMPLEMENTATION_SOP)
        self.assertIn("合法 `Review-Defer` 必须重新分类建项，不得复用当前编号", IMPLEMENTATION_SOP)

    def test_new_pending_design_auto_enters_implementation_unless_blocked(self) -> None:
        handoff = SKILL.index("### 已确认工作包的实施交接")
        auto_transition = SKILL.index("本轮从需求澄清新建正式 `PEND-*` 时")
        default_flow = SKILL.index("默认实施流程是编码、最低验收")
        self.assertLess(handoff, auto_transition)
        self.assertLess(auto_transition, default_flow)
        self.assertIn("不要求用户在原始请求中再次说“实施”或报出新编号", SKILL)
        self.assertIn("用户已明确确认整份最终摘要", SKILL)
        self.assertIn("版本 `5` 收敛确认有效", SKILL)
        self.assertIn("不得以仅交付文档的回复结束当前执行周期", SKILL)
        self.assertIn("不得再次询问是否开始编码", SKILL)
        self.assertIn("立即完整读取实施 SOP、固定任务差异基线", SKILL)
        self.assertIn("仅头脑风暴、澄清、规划、蓝图、设计或文档", SKILL)
        self.assertIn("用户明确暂停或取消", SKILL)
        self.assertIn("待确认差量、研究证据不足、收敛确认缺失或失配", SKILL)
        self.assertIn("Plan mode 继续服从其方案审批门禁", SKILL)

    def test_skill_name_and_review_boundary_are_explicit(self) -> None:
        self.assertIn("name: nova-brainstorming", SKILL)
        self.assertNotIn("name: project-brainstorming", SKILL)
        self.assertIn("不用于独立代码审查", SKILL)
        self.assertIn("只有 `nova-review` 记录有效 PASS 后", SKILL)

    def test_terminal_design_requires_new_dated_evolution_document(self) -> None:
        self.assertIn("YYYY-MM-DD_具体名称.md", SKILL)
        self.assertIn("`已实现`、`已废弃`设计是终态历史快照", SKILL)
        self.assertIn("不得向终态文档追加工作包或改回非终态", SKILL)
        self.assertIn("通过“演进来源”链接旧设计", SKILL)

    def test_document_examples_are_scoped_to_project_first_creation(self) -> None:
        self.assertIn("目标项目不存在 `PROJECT_BLUEPRINT.md` 且正在首次创建蓝图时", SKILL)
        self.assertIn("`docs/design/` 不存在有效设计且正在首次创建设计时", SKILL)
        self.assertIn(
            "[完整蓝图示例](references/examples/equipment-borrowing/PROJECT_BLUEPRINT.md)",
            SKILL,
        )
        self.assertIn(
            "[关联设计示例](references/examples/equipment-borrowing/docs/design/2026-08-25_设备借用闭环.md)",
            SKILL,
        )
        self.assertTrue(BLUEPRINT_EXAMPLE.is_file())
        self.assertTrue(DESIGN_EXAMPLE.is_file())
        self.assertIn("已有对应文档体系时只读取规范、模板和当前项目相关文档", SKILL)
        self.assertNotIn("首次创建相应文档类型时，再读取 [完整示例]", SKILL)

    def test_resource_reads_reuse_fingerprints_and_resume_only_after_truncation(self) -> None:
        self.assertIn("项目文档和技能文档资源状态", SKILL)
        self.assertIn("目标项目绝对路径、资源绝对路径和 SHA-256", SKILL)
        self.assertIn("只读取尚未加载或指纹变化的", SKILL)
        self.assertIn("路径和 SHA-256 未变化时复用", SKILL)
        self.assertIn("变化时只失效受影响资源", SKILL)
        self.assertIn("不得先 `wc` 再按固定行数串行重读", SKILL)
        self.assertIn("只有工具明确截断时才从未返回位置补读", SKILL)
        self.assertIn("不得读取超过已知文件末尾的空区间", SKILL)
        self.assertIn("不得跨会话或跨项目复用缓存", SKILL)
        self.assertIn("不得为读取资源修改插件、hook 或宿主 UI", SKILL)

    def test_unreliable_resource_probe_stops_without_example_fallback(self) -> None:
        self.assertIn("无法可靠判断目标路径、文档存在性、设计有效性或资源指纹时", SKILL)
        self.assertIn("不得按“不存在”处理、加载示例或写入缓存", SKILL)
        self.assertIn("先用路径、链接和头部元数据缩小候选", SKILL)
        self.assertIn("仍会改变设计语义时停止并只确认一个差量", SKILL)

    def test_evolution_source_uses_metadata_then_targeted_contracts(self) -> None:
        self.assertIn("当前需求、蓝图引用和已确认关系锁定", SKILL)
        self.assertIn("标题、规范版本、状态、演进来源和工作包等头部元数据", SKILL)
        self.assertIn("元数据不足以确认覆盖关系或存在契约冲突时", SKILL)
        self.assertIn("定向读取相关共享契约、工作包和直接依赖", SKILL)
        self.assertIn("不读取仅主题相邻的旁支设计", SKILL)
        self.assertIn("确定设计演进来源", SKILL)

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

    def test_text_and_structured_answers_share_one_progression_contract(self) -> None:
        continuation = CONVERSATION_SOP.index("### 答案后的统一推进")
        self.assertGreater(continuation, CONVERSATION_SOP.index("### 阶段总结与交互载体"))
        self.assertIn("普通文本回复与原生工具返回的有效答案共用以下状态机", CONVERSATION_SOP)
        self.assertIn("载体只决定问题如何呈现，不改变确认、继续或收敛语义", CONVERSATION_SOP)
        self.assertIn("每个交互步", CONVERSATION_SOP)
        self.assertIn("不是整个 AI 执行周期只能提问一次", CONVERSATION_SOP)
        self.assertIn("每次合并后重新计算当前话题的待确认差量和研究任务", CONVERSATION_SOP)
        self.assertIn("按上一节载体规则立即提出一个问题", CONVERSATION_SOP)
        self.assertNotIn("### 结构化答案后的推进", CONVERSATION_SOP)

    def test_progression_blocks_premature_closure_and_idle_next_steps(self) -> None:
        self.assertIn("待确认差量和研究任务均为空", CONVERSATION_SOP)
        self.assertIn(
            "目标、参与者、触发、正常结果、状态变化、权限、关键边界、失败恢复、明确不做与验收证据均已确认",
            CONVERSATION_SOP,
        )
        self.assertIn("局部流程明确但条件未满足时只能称“阶段结论”", CONVERSATION_SOP)
        self.assertIn("不得只列出待办、只说“建议下一步”", CONVERSATION_SOP)
        self.assertIn("不把研究任务改问用户", CONVERSATION_SOP)
        self.assertIn("标记为“证据不足”并说明原因", CONVERSATION_SOP)
        self.assertIn("还有要讨论的吗", CONVERSATION_SOP)
        self.assertIn("当前话题已按第 6 条明确确认", CONVERSATION_SOP)
        self.assertIn("用户要求暂停、继续前必须写入", CONVERSATION_SOP)
        self.assertIn("研究暂时无法完成", CONVERSATION_SOP)
        self.assertIn("工具失败或呈现状态不明", CONVERSATION_SOP)
        self.assertIn("必须等待本次答案返回后再决定下一问", CONVERSATION_SOP)
        self.assertIn("不得预先提交、并发提问或重复刚回答的问题", CONVERSATION_SOP)

    def test_whole_design_confirmation_blocks_model_self_certification(self) -> None:
        self.assertIn("AI 只能形成候选收敛", SKILL)
        self.assertIn("用户明确确认整份最终摘要后才可标记已确认", SKILL)
        self.assertIn("话题闭环使用覆盖整份候选设计的最终摘要", CONVERSATION_SOP)
        self.assertIn("确认整份设计", CONVERSATION_SOP)
        self.assertIn("AI 不得仅凭本项成立自行宣称已收敛", CONVERSATION_SOP)
        self.assertIn("要求开发、沉默、空答案、取消、部分答案", CONVERSATION_SOP)
        self.assertIn("不再询问是否开始编码", CONVERSATION_SOP)
        self.assertIn("该次确认同时授权写入", SKILL)
        self.assertIn("不得再提出写入或开发确认", SKILL)
        self.assertNotIn("取得用户确认后再写", SKILL)
        self.assertIn("正常连续访谈在最终确认前不写设计草稿", CONVERSATION_SOP)
        self.assertIn("只询问一次是否保存", CONVERSATION_SOP)
        self.assertIn("后台同时维护固定收敛矩阵", CONVERSATION_SOP)
        self.assertIn("不得通过省略字段得到空差量", CONVERSATION_SOP)
        self.assertIn("最终只展示由矩阵生成的一份整设计摘要", CONVERSATION_SOP)
        self.assertIn("用户明确确认@sha256:<Semantic-Fingerprint>", DESIGN_STANDARD)
        self.assertIn("任何设计语义变化都必须升级为版本 `5`", DESIGN_STANDARD)
        self.assertIn(
            "版本 `4` 仅限已登记且语义与 Git `HEAD` 权威基线一致的兼容设计",
            DESIGN_STANDARD,
        )
        self.assertNotIn("新建或活动设计规范版本为 `4`", DESIGN_STANDARD)

    def test_unanswered_structured_question_is_resumable(self) -> None:
        self.assertIn("### 结构化问题的中断与恢复", CONVERSATION_SOP)
        self.assertIn("宿主超时、用户取消或其他未提交状态", CONVERSATION_SOP)
        self.assertIn("当前问题未回答的非终态", CONVERSATION_SOP)
        self.assertIn("不合并、不推进、不自动重试", CONVERSATION_SOP)
        self.assertIn("原样保留问题原文、选项顺序、标签和说明", CONVERSATION_SOP)
        self.assertIn("超时长度由宿主决定", CONVERSATION_SOP)
        self.assertIn("不写死、不延长也不轮询工具", CONVERSATION_SOP)
        self.assertNotIn("120 秒", CONVERSATION_SOP)
        self.assertIn("用原生工具原样重放该问题", CONVERSATION_SOP)
        self.assertIn("工具不可用时用普通文本完整列出原选项", CONVERSATION_SOP)
        self.assertIn("不得用缺少标签的 A/B/C 代替选项", CONVERSATION_SOP)

    def test_convergence_design_preserves_tool_timeout_contract(self) -> None:
        self.assertIn("设计状态：已实现", CONVERGENCE_DESIGN)
        self.assertIn("演进来源：[结构化问题取消与恢复]", CONVERGENCE_DESIGN)
        self.assertIn("文本与原生结构化工具共用同一推进状态机", CONVERGENCE_DESIGN)
        self.assertIn("不改变原生工具选择、超时、中断或恢复语义", CONVERGENCE_DESIGN)
        self.assertIn("超时长度由宿主决定", CONVERGENCE_DESIGN)
        self.assertIn("`0/1 answered`", CONVERGENCE_DESIGN)

    def test_conversation_sop_preserves_frontstage_gates(self) -> None:
        self.assertLessEqual(len(CONVERSATION_SOP.splitlines()), 160)
        self.assertIn("### 单问题闸门", CONVERSATION_SOP)
        self.assertIn("只有一个需要用户回答的句子", CONVERSATION_SOP)
        self.assertIn("用用户可感知结果解释取舍并明确推荐", CONVERSATION_SOP)
        self.assertIn("## 3. 输出净化闸门", CONVERSATION_SOP)
        self.assertIn("删除孤立人名、无上下文英文", CONVERSATION_SOP)
        self.assertIn("架构与开发边界", CONVERSATION_SOP)


if __name__ == "__main__":
    unittest.main()
