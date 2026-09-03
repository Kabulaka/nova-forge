from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class IntegrationContractTests(unittest.TestCase):
    def test_checkpoint_persists_lossless_stage_projection(self) -> None:
        checkpoint = (
            ROOT / ".nova/architecture/data/session-checkpoint.md"
        ).read_text(encoding="utf-8")
        self.assertIn("不是第二套权威", checkpoint)
        self.assertIn("`stageProjection` 持久化映射", checkpoint)
        for field in (
            "inheritedContracts",
            "stageEvidence",
            "stageDecisions",
            "unresolvedDeltas",
            "resolutionBasis",
        ):
            self.assertIn(f"| {field} |", checkpoint)
        self.assertIn("从同一检查点快照重建完整 `stageProjection`", checkpoint)
        self.assertIn("用户确认和未决差量的类别边界", checkpoint)
        self.assertIn("持久化、备份、迁移和恢复均不得丢失", checkpoint)

    def test_inherited_contract_sources_align_across_stages(self) -> None:
        decision_state = (
            ROOT / ".nova/architecture/data/interview-decision-state.md"
        ).read_text(encoding="utf-8")
        checkpoint = (
            ROOT / ".nova/architecture/data/session-checkpoint.md"
        ).read_text(encoding="utf-8")
        conversation = (
            ROOT / "skills/nova-development/references/conversation-sop.md"
        ).read_text(encoding="utf-8")
        requirements = (ROOT / "skills/nova-requirements/SKILL.md").read_text(
            encoding="utf-8"
        )
        architecture = (ROOT / "skills/nova-architecture/SKILL.md").read_text(
            encoding="utf-8"
        )
        development = (ROOT / "skills/nova-development/SKILL.md").read_text(
            encoding="utf-8"
        )
        for document in (decision_state, checkpoint, conversation):
            self.assertIn("进入当前阶段前", document)
            self.assertIn("需求阶段", document)
            self.assertIn("同一需求权威", document)
            self.assertIn("架构与开发阶段", document)
        self.assertIn("允许其真实来源阶段同为需求", requirements)
        self.assertIn("保留其需求来源阶段", architecture)
        self.assertIn("保留其需求或架构来源阶段", development)
        self.assertIn("不得把同阶段来源伪装为上游阶段", conversation)

    def test_plugin_and_compat_discovery_are_mutually_exclusive(self) -> None:
        foundation = (
            ROOT / ".nova/architecture/foundation/dual-host-plugin.md"
        ).read_text(encoding="utf-8")
        blueprint = (ROOT / ".nova/PROJECT_BLUEPRINT.md").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for document in (foundation, blueprint, readme):
            self.assertIn("版本化插件", document)
            self.assertIn("兼容", document)
        self.assertIn("同一宿主不得同时加载两种入口", foundation)
        self.assertIn("普通文件或真实目录冲突使整次切换零写入失败", foundation)
        self.assertIn("先完成插件禁用或卸载", foundation)
        self.assertIn("插件已启用后的运行故障不得在同一会话自动叠加兼容入口", foundation)
        self.assertIn("不得遗留双入口", blueprint)
        self.assertIn("两种入口即使解析到同一工作区源码也不能在同一宿主并存", readme)


if __name__ == "__main__":
    unittest.main()
