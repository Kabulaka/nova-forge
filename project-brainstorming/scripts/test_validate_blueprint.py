#!/usr/bin/env python3
"""Black-box tests for the project blueprint and design document validator."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_blueprint.py")
SKILL_ROOT = SCRIPT.parent.parent


def design_document(*, state: str = "已确认", second_anchor: str = "wp-02-review") -> str:
    return textwrap.dedent(
        f"""\
        # 示例史诗设计

        > 设计状态：{state}
        > 关联待办：WP-01、WP-02
        > 必读范围：`PROJECT_BLUEPRINT.md`、本文件“公共上下文”、当前工作包章节及其直接依赖

        <a id="shared-context"></a>
        ## 1. 公共上下文

        ### 问题与目标

        - 形成可验证的共同结果。

        ### 明确非目标

        - 不扩展无关能力。

        ### 共享模型与不变量

        - 两个工作包共享同一状态模型。

        <a id="work-package-map"></a>
        ## 2. 工作包地图

        | 工作包 | 状态 | 前置依赖 | 设计章节 | 组合验收关系 |
        |--------|------|----------|----------|--------------|
        | WP-01 | 已确认 | 无 | [章节](#wp-01-extract) | 与 WP-02 组合验收 |
        | WP-02 | 已确认 | WP-01 | [章节](#{second_anchor}) | 与 WP-01 组合验收 |

        <a id="wp-01-extract"></a>
        ## WP-01 要求提取

        ### 状态、范围与非目标

        - 状态：已确认
        - 范围：提取结构化要求。
        - 非目标：不执行审核。

        ### 前置条件、输入与输出

        - 输入文档，输出结构化要求。

        ### 正常行为、权限与状态

        - 授权用户提交并查看结果。

        ### 边界、失败与恢复

        - 失败必须保留原输入并允许重试。

        ### 依赖与影响范围

        - 无前置工作包。

        ### 验收标准

        - 正常输入生成要求，失败输入返回明确错误。

        <a id="{second_anchor}"></a>
        ## WP-02 审核与版本管理

        ### 状态、范围与非目标

        - 状态：已确认
        - 范围：审核并保存版本。
        - 非目标：不重新执行提取。

        ### 前置条件、输入与输出

        - 输入 WP-01 结果，输出审核版本。

        ### 正常行为、权限与状态

        - 审核人确认后版本生效。

        ### 边界、失败与恢复

        - 保存失败不得改变当前生效版本。

        ### 依赖与影响范围

        - 依赖 WP-01。

        ### 验收标准

        - 覆盖保存成功、失败和组合验收。

        ## 3. 证据推断

        - 无。

        ## 4. 待确认事项

        1. 无。
        """
    )


def blueprint(rows: str, *, include_version: bool = True) -> str:
    version = "> 蓝图规范版本：2\n" if include_version else ""
    template = textwrap.dedent(
        """\
        # 示例项目 — 项目蓝图

        __VERSION__> 文档定位：保存所有模块共同遵守的项目级约束。

        ## 1. 项目定位

        ### 目标

        - 提供可验证能力。

        ### 非目标

        - 不扩展无关范围。

        ## 2. 技术栈

        - Python 3 标准库。

        ## 3. 代码结构

        - 顶层模块保持单一职责。

        ## 4. 模块架构

        - 模块只能按既定方向依赖。

        ## 5. 跨模块契约

        ### 业务规则与核心不变量

        - 所有模块必须保留任务标识。

        ### 外部契约、失败与资源边界

        - 保存失败不得改变已确认状态，并允许恢复。

        ### 安全与非功能要求

        - 未授权数据不得输出。

        ### 开发边界

        #### 本期必须实现

        - 完成待办。

        #### 明确不做

        - 不增加外部服务。

        #### 后续候选

        - 后续再评估扩展。

        #### AI 可自行决定

        - 内部函数命名。

        #### 必须再次确认

        - 公共契约变化。

        ## 6. 待开发功能

        | 编号 | 优先级 | 功能 | 设计依据 | 前置依赖 | 完成定义 |
        |------|--------|------|----------|----------|----------|
        __ROWS__

        ## 7. 系统架构

        ### 架构红线

        - 不得绕过模块边界。
        """
    )
    return template.replace("__VERSION__", version).replace("__ROWS__", rows)


class ValidatorTests(unittest.TestCase):
    def run_validator(self, path: Path, *, design: bool = False) -> subprocess.CompletedProcess[str]:
        args = [sys.executable, str(SCRIPT)]
        if design:
            args.append("--design")
        args.append(str(path))
        return subprocess.run(args, check=False, capture_output=True, text=True)

    def write_project(self, root: Path, blueprint_text: str, design_text: str | None = None) -> Path:
        blueprint_path = root / "PROJECT_BLUEPRINT.md"
        blueprint_path.write_text(blueprint_text, encoding="utf-8")
        if design_text is not None:
            design_path = root / "docs" / "design" / "epic.md"
            design_path.parent.mkdir(parents=True)
            design_path.write_text(design_text, encoding="utf-8")
        return blueprint_path

    def test_two_work_packages_can_reference_different_sections_of_one_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = "\n".join(
                (
                    "| WP-01 | P0 | 要求提取 | [设计 WP-01](docs/design/epic.md#wp-01-extract) | 无 | 正常和失败输入均可验证 |",
                    "| WP-02 | P0 | 审核与版本管理 | [设计 WP-02](docs/design/epic.md#wp-02-review) | WP-01 | 保存成功和失败均可验证 |",
                )
            )
            path = self.write_project(root, blueprint(rows), design_document())
            result = self.run_validator(path)
            design_result = self.run_validator(root / "docs" / "design" / "epic.md", design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(design_result.returncode, 0, design_result.stdout + design_result.stderr)

    def test_direct_migration_allows_unclarified_design_and_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = "| PEND-001 | P2 | 原有待办 | 待澄清 | 待澄清 | 原有完成定义保持不变 |"
            result = self.run_validator(self.write_project(root, blueprint(row)))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_escaped_pipe_in_pending_work_cell_is_not_a_column_separator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = (
                "| PEND-001 | P2 | 对比 A \\| B | 待澄清 | 无 | "
                "原有完成定义保持不变 |"
            )
            result = self.run_validator(self.write_project(root, blueprint(row)))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_blueprint_requires_format_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = "| PEND-001 | P2 | 原有待办 | 待澄清 | 待澄清 | 原有完成定义 |"
            result = self.run_validator(self.write_project(root, blueprint(row, include_version=False)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("blueprint format upgrade required", result.stdout)

    def test_missing_design_document_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = "| WP-01 | P0 | 要求提取 | [设计](docs/design/missing.md#wp-01) | 无 | 完成定义 |"
            result = self.run_validator(self.write_project(root, blueprint(row)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("design document not found", result.stdout)

    def test_missing_design_anchor_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = "| WP-01 | P0 | 要求提取 | [设计](docs/design/epic.md#wp-99-missing) | 无 | 完成定义 |"
            result = self.run_validator(
                self.write_project(root, blueprint(row), design_document())
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("design anchor not found", result.stdout)

    def test_duplicate_pending_work_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = "\n".join(
                (
                    "| WP-01 | P0 | 要求提取 | 待澄清 | 无 | 完成定义一 |",
                    "| WP-01 | P1 | 审核 | 待澄清 | 待澄清 | 完成定义二 |",
                )
            )
            result = self.run_validator(self.write_project(root, blueprint(rows)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate pending work id", result.stdout)

    def test_pending_work_dependency_must_be_known_and_not_self_referential(self) -> None:
        cases = {
            "arbitrary text": "依赖数据库",
            "unknown id": "WP-99",
            "self dependency": "WP-01",
        }
        for label, dependency in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                row = f"| WP-01 | P0 | 要求提取 | 待澄清 | {dependency} | 完成定义 |"
                result = self.run_validator(self.write_project(root, blueprint(row)))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("pending work", result.stdout)

    def test_duplicate_pending_work_dependency_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = "\n".join(
                (
                    "| WP-01 | P0 | 要求提取 | 待澄清 | 无 | 完成定义一 |",
                    "| WP-02 | P0 | 审核 | 待澄清 | WP-01、WP-01 | 完成定义二 |",
                )
            )
            result = self.run_validator(self.write_project(root, blueprint(rows)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate pending work dependency", result.stdout)

    def test_pending_work_dependency_accepts_supported_separators(self) -> None:
        for separator in ("、", ",", "，"):
            with self.subTest(separator=separator), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rows = "\n".join(
                    (
                        "| WP-01 | P0 | 要求提取 | 待澄清 | 无 | 完成定义一 |",
                        "| WP-02 | P0 | 审核 | 待澄清 | 无 | 完成定义二 |",
                        f"| WP-03 | P1 | 发布 | 待澄清 | WP-01{separator}WP-02 | 完成定义三 |",
                    )
                )
                result = self.run_validator(self.write_project(root, blueprint(rows)))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_blueprint_rejects_reference_to_completed_work_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = design_document(state="已实现")
            content = content.replace("| WP-01 | 已确认 |", "| WP-01 | 已完成 |")
            content = content.replace("| WP-02 | 已确认 |", "| WP-02 | 已完成 |")
            content = content.replace("- 状态：已确认", "- 状态：已完成")
            row = (
                "| WP-01 | P0 | 要求提取 | "
                "[设计](docs/design/epic.md#wp-01-extract) | 无 | 完成定义 |"
            )
            result = self.run_validator(
                self.write_project(root, blueprint(row), content)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("terminal work package must be removed", result.stdout)

    def test_fenced_code_cannot_supply_blueprint_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = "| PEND-001 | P2 | 原有待办 | 待澄清 | 无 | 完成定义 |"
            valid = blueprint(row)
            first_line, remainder = valid.split("\n", 1)
            content = f"{first_line}\n\n```markdown\n{remainder}\n```\n"
            result = self.run_validator(self.write_project(root, content))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing level-2 section", result.stdout)

    def test_blueprint_section_titles_must_be_independent_exact_headings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = "| PEND-001 | P2 | 原有待办 | 待澄清 | 无 | 完成定义 |"
            content = blueprint(row).replace(
                "## 1. 项目定位\n", "## 1. 项目定位与技术栈\n"
            ).replace("## 2. 技术栈\n", "")
            result = self.run_validator(self.write_project(root, content))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing level-2 section: 项目定位", result.stdout)
            self.assertIn("missing level-2 section: 技术栈", result.stdout)

    def test_invalid_design_status_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            path.write_text(design_document(state="未知"), encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("design status must be one of", result.stdout)

    def test_work_package_map_status_must_match_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document().replace(
                "| WP-02 | 已确认 | WP-01 |", "| WP-02 | 开发中 | WP-01 |"
            )
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("status mismatch between map and section", result.stdout)

    def test_fenced_anchor_cannot_satisfy_work_package_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document().replace(
                '<a id="wp-01-extract"></a>',
                '```html\n<a id="wp-01-extract"></a>\n```',
            )
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("needs a matching explicit anchor", result.stdout)

    def test_duplicate_work_package_section_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document()
            duplicate = textwrap.dedent(
                """\

                <a id="wp-01-copy"></a>
                ## WP-01 重复章节

                ### 状态、范围与非目标
                - 状态：已确认
                ### 前置条件、输入与输出
                - 输入与输出明确。
                ### 正常行为、权限与状态
                - 权限明确。
                ### 边界、失败与恢复
                - 失败可恢复。
                ### 依赖与影响范围
                - 无。
                ### 验收标准
                - 可执行验证。
                """
            )
            path.write_text(content + duplicate, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate work package section: WP-01", result.stdout)

    def test_work_package_anchor_requires_exact_id_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document().replace("wp-01-extract", "wp-010-extract")
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("needs a matching explicit anchor", result.stdout)

    def test_non_target_heading_does_not_satisfy_positive_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document().replace("### 问题与目标", "### 问题背景")
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing design semantic section: 目标", result.stdout)

    def test_blueprint_template_materializes_to_valid_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = (SKILL_ROOT / "assets" / "PROJECT_BLUEPRINT.template.md").read_text(
                encoding="utf-8"
            )
            replacements = {
                "<项目名称>": "示例项目",
                "<稳定编号>": "WP-01",
                "<设计章节链接或待澄清>": "待澄清",
                "<编号、无或待澄清>": "无",
            }
            for source, target in replacements.items():
                content = content.replace(source, target)
            content = re.sub(r"<(?!/?a\b)[^>\n]+>", "示例", content)
            path = self.write_project(Path(directory), content)
            result = self.run_validator(path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_design_template_materializes_to_valid_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = (SKILL_ROOT / "assets" / "DESIGN.template.md").read_text(
                encoding="utf-8"
            )
            replacements = {
                "<史诗名称>": "示例史诗",
                "<WP-01、WP-02>": "WP-01",
                "<WP-01>": "WP-01",
                "<待澄清>": "澄清中",
                "<无>": "无",
                "<关系>": "独立验收",
                "<工作包名称>": "示例工作包",
                "<待澄清/澄清中/已确认/开发中/已完成/已废弃>": "澄清中",
            }
            for source, target in replacements.items():
                content = content.replace(source, target)
            content = re.sub(r"<(?!/?a\b)[^>\n]+>", "示例", content)
            path = Path(directory) / "design.md"
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clarifying_design_requires_unconfirmed_work_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            path.write_text(design_document(state="澄清中"), encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must contain an unconfirmed work package", result.stdout)

    def test_confirmed_design_with_only_completed_work_packages_requires_implemented(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document(state="已确认")
            content = content.replace("| WP-01 | 已确认 |", "| WP-01 | 已完成 |")
            content = content.replace("| WP-02 | 已确认 |", "| WP-02 | 已完成 |")
            content = content.replace("- 状态：已确认", "- 状态：已完成")
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be implemented", result.stdout)

    def test_deprecated_design_requires_linked_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document(state="已废弃")
            content = content.replace("| WP-01 | 已确认 |", "| WP-01 | 已废弃 |")
            content = content.replace("| WP-02 | 已确认 |", "| WP-02 | 已废弃 |")
            content = content.replace("- 状态：已确认", "- 状态：已废弃")
            content += "\n不提供替代方案。\n"
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("linked replacement source", result.stdout)

    def test_all_deprecated_work_packages_cannot_be_marked_implemented(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document(state="已实现")
            content = content.replace("| WP-01 | 已确认 |", "| WP-01 | 已废弃 |")
            content = content.replace("| WP-02 | 已确认 |", "| WP-02 | 已废弃 |")
            content = content.replace("- 状态：已确认", "- 状态：已废弃")
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be deprecated and provide a replacement", result.stdout)

    def test_required_reading_rejects_whole_epic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.md"
            content = design_document().replace(
                "> 必读范围：`PROJECT_BLUEPRINT.md`、本文件“公共上下文”、当前工作包章节及其直接依赖",
                "> 必读范围：`PROJECT_BLUEPRINT.md` 和整份史诗设计文档",
            )
            path.write_text(content, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not load the whole epic design", result.stdout)


if __name__ == "__main__":
    unittest.main()
