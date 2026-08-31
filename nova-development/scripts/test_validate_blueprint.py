#!/usr/bin/env python3
"""Black-box tests for the versioned blueprint and design validator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT / "scripts" / "validate_blueprint.py"
EXAMPLE_ROOT = SKILL_ROOT / "references" / "examples" / "equipment-borrowing"
VALIDATOR_SPEC = importlib.util.spec_from_file_location("nova_validate_blueprint", VALIDATOR)
assert VALIDATOR_SPEC is not None and VALIDATOR_SPEC.loader is not None
VALIDATOR_MODULE = importlib.util.module_from_spec(VALIDATOR_SPEC)
sys.modules[VALIDATOR_SPEC.name] = VALIDATOR_MODULE
VALIDATOR_SPEC.loader.exec_module(VALIDATOR_MODULE)
DIMENSIONS = (
    "交付边界",
    "参与者与权限",
    "触发与输入",
    "结果、状态与不变量",
    "失败与恢复",
    "AI 决策边界",
)
AUTO_CONFIRMATION = object()


def valid_design(
    *,
    version: str = "5",
    state: str = "已确认",
    package_states: tuple[str, ...] = ("已确认", "已确认"),
    package_ids: tuple[str, ...] = ("WP-01", "WP-02"),
    dependencies: tuple[str, ...] | None = None,
    include_staging: bool = False,
    replacement: bool = False,
    evolution: str = "无",
    confirmation: str | None | object = AUTO_CONFIRMATION,
) -> str:
    if len(package_states) != len(package_ids):
        raise ValueError("package_states must match package_ids")
    if dependencies is None:
        dependencies = tuple(
            "、".join(package_ids[:-1]) if index == len(package_ids) - 1 and index > 0 else "无"
            for index in range(len(package_ids))
        )
    if len(dependencies) != len(package_ids):
        raise ValueError("dependencies must match package_ids")
    package_sections: list[str] = []
    map_rows: list[str] = []
    for index, package_id in enumerate(package_ids, start=1):
        anchor = f"wp-{index:02d}-example"
        role = "收口" if len(package_ids) > 1 and index == len(package_ids) else "能力"
        ordinal = ("一", "二", "三", "四")[index - 1]
        map_rows.append(
            f"| {package_id} | {role} | {package_states[index - 1]} | "
            f"交付第{ordinal}个独立结果 | {dependencies[index - 1]} | [章节](#{anchor}) |"
        )
        contract_rows = "\n".join(
            f"| {package_id}-C{dimension_index:02d} | {dimension} | "
            f"{package_id}/{dimension} | {package_id} 的{dimension}约束 |"
            for dimension_index, dimension in enumerate(DIMENSIONS, start=1)
        )
        own_contracts = "、".join(f"{package_id}-C{i:02d}" for i in range(1, 7))
        if role == "收口":
            related = "、".join(f"{other_id}-C01" for other_id in package_ids[:-1]) + "、"
        else:
            related = "S-01、"
        package_sections.append(
            f"""<a id="{anchor}"></a>
## {package_id} 示例工作包 {index}

### 契约

| 契约 | 维度 | 语义键 | 唯一规则 |
|------|------|--------|----------|
{contract_rows}

### 验收

| 覆盖契约 | 场景 | 预期结果 |
|----------|------|----------|
| {related}{own_contracts} | 执行 {package_id} 正常及失败场景 | 契约全部得到可观察验证 |"""
        )

    map_rows_for_template = "\n        ".join(map_rows)

    replacement_line = "> 替代来源：[新设计](replacement.md)\n" if replacement else ""
    staging = ""
    if include_staging:
        staging = textwrap.dedent(
            """

            ## 3. 澄清暂存

            | 类型 | 内容 | 来源 |
            |------|------|------|
            | 证据推断 | 现有入口可能需要保留 | 代码检索 |
            | 待确认 | 是否保留现有入口 | 用户尚未决定 |
            """
        )

    header = textwrap.dedent(
        f"""
        # 示例史诗设计

        > 设计规范版本：{version}
        > 设计状态：{state}
        > 演进来源：{evolution}
        > 工作包：{"、".join(package_ids)}
        {replacement_line}
        <a id="shared-context"></a>
        ## 1. 共享约束

        ### 1.1 问题与成功结果

        | 问题 | 成功结果 |
        |------|----------|
        | 两个工作包需要共享状态 | 状态和组合结果可验证 |

        ### 1.2 共享契约

        | 契约 | 语义键 | 唯一规则 |
        |------|--------|----------|
        | S-01 | 共享/状态 | 两个工作包共享同一状态定义 |

        <a id="work-package-map"></a>
        ## 2. 工作包地图

        | 工作包 | 角色 | 状态 | 交付结果 | 前置依赖 | 设计章节 |
        |--------|------|------|----------|----------|----------|
        {map_rows_for_template}
        """
    ).strip()
    effective_confirmation = confirmation
    if confirmation is AUTO_CONFIRMATION:
        if version == "5":
            effective_confirmation = "待确认" if state == "澄清中" else "用户明确确认@sha256:" + "0" * 64
        else:
            effective_confirmation = None
    if effective_confirmation is not None:
        header = header.replace(
            f"> 设计状态：{state}\n",
            f"> 设计状态：{state}\n> 收敛确认：{effective_confirmation}\n",
        )
    design = header + "\n\n" + "\n\n".join(package_sections) + staging + "\n"
    if effective_confirmation == "用户明确确认@sha256:" + "0" * 64:
        fingerprint = VALIDATOR_MODULE.design_semantic_fingerprint(
            Path("2026-08-29_显式收敛确认.md"), text_snapshot=design
        )
        design = design.replace("0" * 64, fingerprint, 1)
    return design


def valid_confirmed_current_design(**kwargs: object) -> str:
    return valid_design(version="5", **kwargs)


def refresh_confirmation(design: str) -> str:
    placeholder = "0" * 64
    pending = re.sub(
        r"用户明确确认@sha256:[0-9a-f]{64}",
        f"用户明确确认@sha256:{placeholder}",
        design,
        count=1,
    )
    fingerprint = VALIDATOR_MODULE.design_semantic_fingerprint(
        Path("2026-08-29_显式收敛确认.md"), text_snapshot=pending
    )
    return pending.replace(placeholder, fingerprint, 1)


def legacy_terminal_design() -> str:
    design = valid_design(
        version="4", state="已实现", package_states=("已完成", "已完成")
    )
    design = design.replace("设计规范版本：4", "设计规范版本：3")
    design = design.replace(
        "| 契约 | 语义键 | 唯一规则 |\n|------|--------|----------|",
        "| 契约 | 已确认约束 |\n|------|------------|",
    )
    design = design.replace(
        "| S-01 | 共享/状态 | 两个工作包共享同一状态定义 |",
        "| S-01 | 两个工作包共享同一状态定义 |",
    )
    design = design.replace(
        "| 工作包 | 角色 | 状态 | 交付结果 | 前置依赖 | 设计章节 |\n"
        "|--------|------|------|----------|----------|----------|",
        "| 工作包 | 状态 | 交付结果 | 前置依赖 | 设计章节 |\n"
        "|--------|------|----------|----------|----------|",
    )
    design = re.sub(
        r"^(\| WP-\d+) \| (?:能力|收口) \|",
        r"\1 |",
        design,
        flags=re.MULTILINE,
    )
    design = design.replace(
        "| 契约 | 维度 | 语义键 | 唯一规则 |\n|------|------|--------|----------|",
        "| 契约 | 维度 | 已确认约束 |\n|------|------|------------|",
    )
    design = re.sub(
        r"^(\| WP-\d+-C\d+ \| [^|]+ \|) [^|]+ \| ([^|]+ \|)$",
        r"\1 \2",
        design,
        flags=re.MULTILINE,
    )
    return design


def valid_blueprint(rows: str) -> str:
    rows_for_template = rows.replace("\n", "\n            ")
    return (
        textwrap.dedent(
            f"""
            # 示例项目 — 项目蓝图

            > 蓝图规范版本：3

            ## 1. 项目定位

            | 对象 | 问题 | 成功结果 |
            |------|------|----------|
            | 用户 | 缺少受控流程 | 流程可验证 |

            ## 2. 技术栈

            | 类别 | 当前事实或硬约束 | 事实来源 |
            |------|------------------|----------|
            | 语言 | Python 3 | 运行环境 |

            ## 3. 代码结构

            ### 顶层目录

            ```text
            src/ 业务代码
            tests/ 测试
            ```

            ### 代码落位规则

            | 代码区域 | 职责 | 代码落位规则 |
            |----------|------|--------------|
            | `src/` | 业务实现 | 生产代码只放这里 |

            ## 4. 模块架构

            ### 模块职责

            | 模块 | 职责 | 对外边界 |
            |------|------|----------|
            | 核心 | 执行业务规则 | 用例接口 |

            ## 5. 跨模块契约

            ### 全局契约

            | 契约 | 适用范围 | 验证 |
            |------|----------|------|
            | C-01 | 全部模块 | 契约测试 |

            ### 开发决策边界

            | 边界 | 内容 |
            |------|------|
            | 本期必须实现 | 当前待办 |
            | 明确不做 | 不增加外部服务 |
            | 后续候选 | 表中未完成工作 |
            | AI 可自行决定 | 内部命名 |
            | 必须再次确认 | 改变公开行为 |

            ## 6. 待开发功能

            | 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 |
            |------|--------|------|------|----------|----------|----------|
            {rows_for_template}

            ## 7. 系统架构

            ### 分层与代码映射

            | 层 | 职责 | 对应代码结构 | 允许依赖 |
            |----|------|--------------|----------|
            | 应用层 | 用例编排 | `src/` | 核心模块 |

            ### 数据与资源安全

            | 适用范围 | 不变量 | 验证 |
            |----------|--------|------|
            | 文件写入 | 原子替换 | 故障测试 |

            ### 运行与恢复

            | 资源或失败点 | 所有者 | 恢复与清理 |
            |--------------|--------|------------|
            | 写入失败 | 应用层 | 回滚临时文件 |
            """
        ).strip()
        + "\n"
    )


class ValidatorTests(unittest.TestCase):
    def run_validator(self, path: Path, *, design: bool = False) -> subprocess.CompletedProcess[str]:
        args = [sys.executable, str(VALIDATOR)]
        if design:
            args.append("--design")
        args.append(str(path))
        return subprocess.run(args, check=False, capture_output=True, text=True)

    def write_project(
        self, root: Path, blueprint: str, design: str | None = None
    ) -> tuple[Path, Path | None]:
        blueprint_path = root / ".nova/PROJECT_BLUEPRINT.md"
        blueprint_path.parent.mkdir(parents=True, exist_ok=True)
        blueprint_path.write_text(blueprint, encoding="utf-8")
        design_path = None
        if design is not None:
            design_path = root / ".nova" / "design" / "2026-08-26_epic.md"
            design_path.parent.mkdir(parents=True, exist_ok=True)
            design_path.write_text(design, encoding="utf-8")
        return blueprint_path, design_path

    def write_registered_legacy_design(self, root: Path) -> Path:
        design = legacy_terminal_design()
        design_path = root / ".nova" / "design" / "2026-08-26_design.md"
        design_path.parent.mkdir(parents=True, exist_ok=True)
        design_path.write_text(design, encoding="utf-8")
        digest = hashlib.sha256(design.encode("utf-8")).hexdigest()
        manifest = {"schema": 1, "files": {design_path.name: f"sha256:{digest}"}}
        (design_path.parent / ".v3-legacy-snapshots.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Nova Test"], check=True
        )
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "fixture"], check=True
        )
        return design_path

    def write_registered_compatible_design(self, root: Path, *, register: bool = True) -> Path:
        design = valid_design(version="4")
        design_path = root / ".nova" / "design" / "2026-08-26_design.md"
        design_path.parent.mkdir(parents=True, exist_ok=True)
        design_path.write_text(design, encoding="utf-8")
        fingerprint = VALIDATOR_MODULE.design_semantic_fingerprint(
            design_path, text_snapshot=design
        )
        if register:
            manifest = {
                "schema": 1,
                "files": {design_path.name: f"sha256:{fingerprint}"},
            }
            (design_path.parent / ".v4-compatible-snapshots.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Nova Test"], check=True
        )
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "fixture"], check=True
        )
        return design_path

    def test_two_pending_items_reference_different_work_packages_in_one_design(self) -> None:
        rows = "\n".join(
            (
                "| TASK-01 | P1 | 用户提出 | 第一项 | [WP-01](design/2026-08-26_epic.md#wp-01-example) | 无 | 第一项可验收 |",
                "| TASK-02 | P1 | 问题诊断 | 第二项 | [WP-02](design/2026-08-26_epic.md#wp-02-example) | TASK-01 | 第二项可验收 |",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            blueprint, design = self.write_project(Path(directory), valid_blueprint(rows), valid_design())
            self.assertEqual(self.run_validator(design, design=True).returncode, 0)
            result = self.run_validator(blueprint)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_version_five_confirmed_design_requires_matching_confirmation(self) -> None:
        confirmed = valid_confirmed_current_design()
        invalid = (
            (
                re.sub(r"^> 收敛确认：.*\n", "", confirmed, flags=re.MULTILINE),
                "must contain exactly one convergence confirmation metadata line",
            ),
            (
                re.sub(
                    r"sha256:[0-9a-f]{64}",
                    "sha256:" + "0" * 64,
                    confirmed,
                    count=1,
                ),
                "convergence confirmation fingerprint does not match design semantics",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid_path = root / "2026-08-29_显式收敛确认.md"
            valid_path.write_text(confirmed, encoding="utf-8")
            self.assertEqual(
                self.run_validator(valid_path, design=True).returncode, 0
            )
            for index, (content, expected) in enumerate(invalid, start=1):
                path = root / f"2026-08-29_无效确认{index}.md"
                path.write_text(content, encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout)

    def test_version_five_semantic_change_invalidates_confirmation(self) -> None:
        design = valid_confirmed_current_design().replace(
            "两个工作包共享同一状态定义", "修改后的共享状态定义"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-29_确认后语义变化.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "convergence confirmation fingerprint does not match design semantics",
                result.stdout,
            )

    def test_version_five_clarifying_design_uses_pending_confirmation(self) -> None:
        design = valid_design(
            version="5",
            state="澄清中",
            package_states=("待澄清", "已确认"),
            include_staging=True,
            confirmation="待确认",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-29_澄清草稿.md"
            path.write_text(design, encoding="utf-8")
            self.assertEqual(self.run_validator(path, design=True).returncode, 0)
            path.write_text(
                design.replace("收敛确认：待确认", "收敛确认：用户明确确认"),
                encoding="utf-8",
            )
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "clarifying version 5 design must use convergence confirmation 待确认",
                result.stdout,
            )

    def test_new_version_four_design_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Nova Test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "fixture"],
                check=True,
            )
            path = root / "2026-08-29_新建旧版设计.md"
            path.write_text(valid_design(version="4"), encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "compatible version 4 design is not present in Git HEAD",
                result.stdout,
            )

    def test_version_four_semantic_change_requires_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_registered_compatible_design(Path(directory))
            changed = path.read_text(encoding="utf-8").replace(
                "两个工作包共享同一状态定义", "未经确认的新状态定义"
            )
            path.write_text(changed, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "compatible version 4 design semantics changed; upgrade to version 5",
                result.stdout,
            )

    def test_version_four_lifecycle_only_change_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_registered_compatible_design(Path(directory))
            changed = path.read_text(encoding="utf-8").replace(
                "| WP-01 | 能力 | 已确认 |", "| WP-01 | 能力 | 开发中 |"
            )
            path.write_text(changed, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unregistered_existing_version_four_semantic_change_requires_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_registered_compatible_design(Path(directory), register=False)
            changed = path.read_text(encoding="utf-8").replace(
                "两个工作包共享同一状态定义", "未经确认的新状态定义"
            )
            path.write_text(changed, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "compatible version 4 design semantics changed; upgrade to version 5",
                result.stdout,
            )

    def test_unregistered_existing_version_four_lifecycle_change_is_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_registered_compatible_design(Path(directory), register=False)
            changed = path.read_text(encoding="utf-8").replace(
                "| WP-01 | 能力 | 已确认 |", "| WP-01 | 能力 | 开发中 |"
            )
            path.write_text(changed, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pending_item_rejects_design_document_from_older_format(self) -> None:
        design = valid_design().replace("设计规范版本：5", "设计规范版本：2")
        row = "| TASK-01 | P1 | 用户提出 | 功能 | [WP-01](design/2026-08-26_epic.md#wp-01-example) | 无 | 可执行 |"
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), valid_blueprint(row), design)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid design document design/2026-08-26_epic.md", result.stdout)
            self.assertIn(
                "expected version 5, compatible version 4, or terminal legacy version 3, found 2",
                result.stdout,
            )

    def test_pending_item_rejects_fenced_fake_design_version(self) -> None:
        design = valid_design().replace(
            "> 设计规范版本：5",
            "> 设计规范版本：2\n\n```text\n> 设计规范版本：5\n```",
        )
        row = "| TASK-01 | P1 | 用户提出 | 功能 | [WP-01](design/2026-08-26_epic.md#wp-01-example) | 无 | 可执行 |"
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), valid_blueprint(row), design)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "expected version 5, compatible version 4, or terminal legacy version 3, found 2",
                result.stdout,
            )

    def test_pending_item_requires_fully_valid_design_document(self) -> None:
        invalid_designs = (
            (
                valid_design().replace(
                    '<a id="wp-01-example"></a>',
                    '<a id="wp-01-example"></a>\n<a id="wp-01-example"></a>',
                ),
                "duplicate explicit anchor",
            ),
            (
                valid_design().replace(
                    "| WP-01 | 能力 | 已确认 |", "| WP-01 | 能力 | 未知 |"
                ),
                "invalid work package state",
            ),
        )
        row = "| TASK-01 | P1 | 用户提出 | 功能 | [WP-01](design/2026-08-26_epic.md#wp-01-example) | 无 | 可执行 |"
        for design, expected_error in invalid_designs:
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as directory:
                blueprint, _ = self.write_project(Path(directory), valid_blueprint(row), design)
                result = self.run_validator(blueprint)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid design document design/2026-08-26_epic.md", result.stdout)
                self.assertIn(expected_error, result.stdout)

    def test_direct_migration_accepts_historical_source_and_pending_design(self) -> None:
        row = "| PEND-001 | P2 | 历史迁移 | 未澄清功能 | 待澄清 | 待澄清 | 用户确认后可执行 |"
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), valid_blueprint(row))
            self.assertEqual(self.run_validator(blueprint).returncode, 0)

    def test_pending_source_is_required_and_controlled(self) -> None:
        row = "| TASK-01 | P1 | 技术债务 | 功能 | 待澄清 | 无 | 可执行 |"
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), valid_blueprint(row))
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid pending work source", result.stdout)

    def test_old_six_column_table_and_version_require_upgrade(self) -> None:
        content = valid_blueprint("| TASK-01 | P1 | 用户提出 | 功能 | 待澄清 | 无 | 可执行 |")
        content = content.replace("蓝图规范版本：3", "蓝图规范版本：2")
        content = content.replace("| 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 |", "| 编号 | 优先级 | 功能 | 设计依据 | 前置依赖 | 完成定义 |")
        content = content.replace("|------|--------|------|------|----------|----------|----------|", "|------|--------|------|----------|----------|----------|", 1)
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), content)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("blueprint format upgrade required", result.stdout)
            self.assertIn("pending work table headers must be", result.stdout)

    def test_extra_pending_column_is_rejected(self) -> None:
        content = valid_blueprint("| TASK-01 | P1 | 用户提出 | 功能 | 待澄清 | 无 | 可执行 |")
        content = content.replace("| 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 |", "| 编号 | 优先级 | 来源 | 类别 | 功能 | 设计依据 | 前置依赖 | 完成定义 |")
        content = content.replace("|------|--------|------|------|----------|----------|----------|", "|------|--------|------|------|------|----------|----------|----------|", 1)
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), content)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pending work table headers must be", result.stdout)

    def test_pending_dependency_must_exist_and_not_repeat(self) -> None:
        row = "| TASK-01 | P1 | 用户提出 | 功能 | 待澄清 | TASK-02、TASK-02 | 可执行 |"
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), valid_blueprint(row))
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown pending work dependency", result.stdout)
            self.assertIn("duplicate pending work dependency", result.stdout)

    def test_pending_dependency_rejects_empty_list_items(self) -> None:
        for dependency in ("TASK-02、", "、TASK-02", "TASK-02、、TASK-02"):
            rows = "\n".join(
                (
                    f"| TASK-01 | P1 | 用户提出 | 功能 | 待澄清 | {dependency} | 可执行 |",
                    "| TASK-02 | P1 | 用户提出 | 依赖项 | 待澄清 | 无 | 可执行 |",
                )
            )
            with self.subTest(dependency=dependency), tempfile.TemporaryDirectory() as directory:
                blueprint, _ = self.write_project(Path(directory), valid_blueprint(rows))
                result = self.run_validator(blueprint)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid pending work dependency", result.stdout)

    def test_terminal_design_work_package_cannot_remain_pending(self) -> None:
        design = valid_design(state="已实现", package_states=("已完成", "已完成"))
        row = "| TASK-01 | P1 | 用户提出 | 功能 | [WP-01](design/2026-08-26_epic.md#wp-01-example) | 无 | 可执行 |"
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), valid_blueprint(row), design)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pending work cannot reference terminal", result.stdout)

    def test_unconfirmed_design_work_package_cannot_be_referenced(self) -> None:
        row = "| TASK-01 | P1 | 用户提出 | 功能 | [WP-01](design/2026-08-26_epic.md#wp-01-example) | 无 | 可执行 |"
        for package_state in ("待澄清", "澄清中"):
            design = valid_design(
                state="澄清中",
                package_states=(package_state, "待澄清"),
                include_staging=True,
            )
            with self.subTest(package_state=package_state), tempfile.TemporaryDirectory() as directory:
                blueprint, _ = self.write_project(Path(directory), valid_blueprint(row), design)
                result = self.run_validator(blueprint)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must reference a confirmed, in-development, or pending-review", result.stdout)

    def test_missing_design_anchor_fails(self) -> None:
        row = "| TASK-01 | P1 | 用户提出 | 功能 | [WP](design/2026-08-26_epic.md#wp-99-missing) | 无 | 可执行 |"
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), valid_blueprint(row), valid_design())
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("design anchor not found", result.stdout)

    def test_forbidden_redundant_blueprint_heading_fails(self) -> None:
        content = valid_blueprint("").replace(
            "## 6. 待开发功能", "### 架构红线\n\n- 不重复规则。\n\n## 6. 待开发功能"
        )
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), content)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("redundant blueprint heading", result.stdout)

    def test_closed_hashes_do_not_hide_forbidden_blueprint_heading(self) -> None:
        content = valid_blueprint("").replace(
            "## 6. 待开发功能", "### 非目标 ###\n\n- 重复规则。\n\n## 6. 待开发功能"
        )
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), content)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("redundant blueprint heading", result.stdout)

    def test_fence_with_trailing_text_does_not_close_block(self) -> None:
        content = valid_blueprint("").replace(
            "## 6. 待开发功能",
            "```markdown\n### 非目标\n``` trailing text\n\n## 6. 待开发功能",
        )
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), content)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unclosed fenced code block", result.stdout)

    def test_fenced_fake_blueprint_heading_does_not_satisfy_structure(self) -> None:
        content = valid_blueprint("").replace("## 4. 模块架构", "```markdown\n## 4. 模块架构\n```")
        with tempfile.TemporaryDirectory() as directory:
            blueprint, _ = self.write_project(Path(directory), content)
            result = self.run_validator(blueprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("level-2 sections must be exactly", result.stdout)

    def test_documents_require_one_level_one_title(self) -> None:
        documents = (
            (valid_blueprint("| TASK-01 | P1 | 用户提出 | 功能 | 待澄清 | 无 | 可执行 |").replace("# 示例项目 — 项目蓝图", "示例项目 — 项目蓝图"), False, "blueprint"),
            (valid_design().replace("# 示例史诗设计", "示例史诗设计"), True, "design"),
        )
        for content, is_design, document_type in documents:
            with self.subTest(document_type=document_type), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / f"{document_type}.md"
                path.write_text(content, encoding="utf-8")
                result = self.run_validator(path, design=is_design)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must contain exactly one level-1 title", result.stdout)

    def test_valid_confirmed_design_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(valid_design(), encoding="utf-8")
            self.assertEqual(self.run_validator(path, design=True).returncode, 0)

    def test_pending_review_work_package_remains_blueprint_referenceable(self) -> None:
        design = valid_design(
            state="已确认", package_states=("待Review", "已确认")
        )
        row = "| TASK-01 | P1 | 用户提出 | 功能 | [WP-01](design/2026-08-26_epic.md#wp-01-example) | 无 | 可执行 |"
        with tempfile.TemporaryDirectory() as directory:
            blueprint, design_path = self.write_project(
                Path(directory), valid_blueprint(row), design
            )
            design_result = self.run_validator(design_path, design=True)
            self.assertEqual(
                design_result.returncode,
                0,
                design_result.stdout + design_result.stderr,
            )
            blueprint_result = self.run_validator(blueprint)
            self.assertEqual(
                blueprint_result.returncode,
                0,
                blueprint_result.stdout + blueprint_result.stderr,
            )

    def test_design_filename_requires_valid_creation_date_and_specific_name(self) -> None:
        invalid_names = (
            "design.md",
            "2026-8-26_design.md",
            "2026-02-30_design.md",
            "2026-08-26_.md",
            "2026-08-26_design name.md",
        )
        for name in invalid_names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / name
                path.write_text(valid_design(), encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("design filename", result.stdout)

    def test_design_filename_accepts_chinese_specific_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_设计文档命名.md"
            path.write_text(valid_design(), encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_evolution_source_requires_same_directory_terminal_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_design = root / "2026-08-25_原功能.md"
            old_design.write_text(
                valid_design(state="已实现", package_states=("已完成", "已完成")),
                encoding="utf-8",
            )
            new_design = root / "2026-08-26_功能演进.md"
            new_design.write_text(
                valid_design(evolution="[原功能](./2026-08-25_原功能.md)"), encoding="utf-8"
            )
            result = self.run_validator(new_design, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_evolution_source_rejects_self_missing_and_nonterminal_targets(self) -> None:
        cases = (
            ("[自己](2026-08-26_功能演进.md)", None, "must not reference itself"),
            ("[缺失](2026-08-25_缺失.md)", None, "file not found"),
            (
                "[未完成](2026-08-25_未完成功能.md)",
                valid_design(),
                "must be terminal",
            ),
        )
        for evolution, target_content, expected in cases:
            with self.subTest(evolution=evolution), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if target_content is not None:
                    (root / "2026-08-25_未完成功能.md").write_text(
                        target_content, encoding="utf-8"
                    )
                path = root / "2026-08-26_功能演进.md"
                path.write_text(valid_design(evolution=evolution), encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout)

    def test_evolution_source_rejects_outside_nested_and_legacy_paths(self) -> None:
        cases = (
            ("[上级](../2026-08-25_原功能.md)", "must stay in the same"),
            ("[子目录](nested/2026-08-25_原功能.md)", "must stay in the same"),
            ("[旧式名称](epic.md)", "filename must match"),
        )
        for evolution, expected in cases:
            with self.subTest(evolution=evolution), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "2026-08-26_功能演进.md"
                path.write_text(valid_design(evolution=evolution), encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout)

    def test_evolution_source_rejects_inconsistent_terminal_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_design = root / "2026-08-25_原功能.md"
            old_design.write_text(valid_design(state="已实现"), encoding="utf-8")
            new_design = root / "2026-08-26_功能演进.md"
            new_design.write_text(
                valid_design(evolution="[原功能](2026-08-25_原功能.md)"), encoding="utf-8"
            )
            result = self.run_validator(new_design, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("implemented design contains an unfinished work package", result.stdout)

    def test_design_requires_exactly_one_evolution_source_metadata(self) -> None:
        designs = (
            valid_design().replace("> 演进来源：无\n", ""),
            valid_design().replace("> 演进来源：无", "> 演进来源：无\n> 演进来源：无"),
        )
        for design in designs:
            with self.subTest(), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "2026-08-26_design.md"
                path.write_text(design, encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exactly one evolution source", result.stdout)

    def test_commented_or_inline_anchor_does_not_satisfy_design_contract(self) -> None:
        for replacement in (
            '<!-- <a id="shared-context"></a> -->',
            'prefix <a id="shared-context"></a>',
        ):
            design = valid_design().replace('<a id="shared-context"></a>', replacement)
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "2026-08-26_design.md"
                path.write_text(design, encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("missing explicit shared-context anchor", result.stdout)

    def test_clarifying_design_requires_staging_and_unconfirmed_package(self) -> None:
        design = valid_design(
            state="澄清中", package_states=("澄清中", "待澄清"), include_staging=True
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clarifying_design_without_staging_fails(self) -> None:
        design = valid_design(state="澄清中", package_states=("澄清中", "待澄清"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("clarification staging", result.stdout)

    def test_confirmed_design_must_not_keep_staging(self) -> None:
        design = valid_design(include_staging=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain clarification staging", result.stdout)

    def test_contract_dimensions_must_cover_in_order(self) -> None:
        design = valid_design().replace(
            "| WP-01-C06 | AI 决策边界 | WP-01/AI 决策边界 | WP-01 的AI 决策边界约束 |",
            "| WP-01-C06 | 交付边界 | WP-01/重复范围 | 重复维度 |",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("contract dimensions must cover in first-occurrence order", result.stdout)

    def test_contract_dimension_can_repeat_with_atomic_semantic_key(self) -> None:
        design = valid_design().replace(
            "| WP-01-C02 | 参与者与权限",
            "| WP-01-C07 | 交付边界 | WP-01/额外边界 | 第二条原子边界 |\n"
            "| WP-01-C02 | 参与者与权限",
        ).replace(
            "S-01、WP-01-C01、WP-01-C02",
            "S-01、WP-01-C01、WP-01-C07、WP-01-C02",
        )
        design = refresh_confirmation(design)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_duplicate_semantic_key_fails(self) -> None:
        design = valid_design().replace("WP-02/交付边界", "WP-01/交付边界")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate semantic key across design", result.stdout)

    def test_multi_package_design_requires_one_complete_closure(self) -> None:
        invalid_designs = (
            (
                valid_design().replace("| WP-02 | 收口 |", "| WP-02 | 能力 |"),
                "exactly one 收口 work package",
            ),
            (
                valid_design().replace(
                    "| WP-02 | 收口 | 已确认 | 交付第二个独立结果 | WP-01 |",
                    "| WP-02 | 收口 | 已确认 | 交付第二个独立结果 | 无 |",
                ),
                "must directly depend on every other work package",
            ),
            (
                valid_design().replace("| WP-01-C01、WP-02-C01", "| WP-02-C01"),
                "needs one acceptance scenario covering every other work package",
            ),
        )
        for design, expected in invalid_designs:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "2026-08-26_design.md"
                path.write_text(design, encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout)

    def test_capability_must_not_depend_on_closure_and_two_node_cycle_fails(self) -> None:
        design = valid_design(dependencies=("WP-02", "WP-01"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not depend on closure work package", result.stdout)
            self.assertIn("dependency graph must be acyclic", result.stdout)

    def test_three_node_work_package_dependency_cycle_fails(self) -> None:
        design = valid_design(
            package_ids=("WP-01", "WP-02", "WP-03", "WP-04"),
            package_states=("已确认", "已确认", "已确认", "已确认"),
            dependencies=("WP-02", "WP-03", "WP-01", "WP-01、WP-02、WP-03"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dependency graph must be acyclic", result.stdout)

    def test_clarifying_closure_can_keep_dependency_pending(self) -> None:
        design = valid_design(
            state="澄清中", package_states=("澄清中", "待澄清"), include_staging=True
        ).replace(
            "| WP-02 | 收口 | 待澄清 | 交付第二个独立结果 | WP-01 |",
            "| WP-02 | 收口 | 待澄清 | 交付第二个独立结果 | 待澄清 |",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_terminal_version_three_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(legacy_terminal_design(), encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("registered Git HEAD snapshot", result.stdout)

    def test_registered_terminal_version_three_git_snapshot_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_registered_legacy_design(Path(directory))
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Semantic-Fingerprint", result.stdout)

    def test_modified_terminal_version_three_git_snapshot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_registered_legacy_design(Path(directory))
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "两个工作包需要共享状态", "两个工作包需要共享修改后的状态"
                ),
                encoding="utf-8",
            )
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match manifest", result.stdout)

    def test_active_version_three_is_rejected(self) -> None:
        design = (
            legacy_terminal_design()
            .replace("> 设计状态：已实现", "> 设计状态：已确认")
            .replace("| 已完成 |", "| 已确认 |")
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("active design must use version 5", result.stdout)

    def test_semantic_fingerprint_ignores_status_but_tracks_contract_changes(self) -> None:
        designs = (
            valid_design(),
            valid_design(package_states=("开发中", "已确认")),
            refresh_confirmation(
                valid_design().replace(
                    "WP-01 的交付边界约束", "WP-01 的新交付边界约束"
                )
            ),
        )
        fingerprints: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            for design in designs:
                path.write_text(design, encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                match = re.search(r"Semantic-Fingerprint: sha256:([0-9a-f]{64})", result.stdout)
                self.assertIsNotNone(match, result.stdout)
                fingerprints.append(match.group(1))
        self.assertEqual(fingerprints[0], fingerprints[1])
        self.assertNotEqual(fingerprints[0], fingerprints[2])

    def test_design_validation_and_fingerprint_share_one_read_snapshot(self) -> None:
        first = valid_design()
        changed = first.replace("WP-01 的交付边界约束", "读取后变化的约束")
        reads = 0

        def changing_read(_: Path) -> tuple[str | None, list[str]]:
            nonlocal reads
            reads += 1
            return (first if reads == 1 else changed), []

        path = Path("/tmp/2026-08-26_design.md")
        with mock.patch.object(VALIDATOR_MODULE, "read_document", side_effect=changing_read):
            errors, warnings, fingerprint = VALIDATOR_MODULE.validate_design_snapshot(path)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(reads, 1)
        self.assertEqual(
            fingerprint,
            VALIDATOR_MODULE.design_semantic_fingerprint(path, text_snapshot=first),
        )

    def test_design_snapshot_read_failure_is_fail_closed(self) -> None:
        failure = "cannot read document: simulated failure"
        with mock.patch.object(VALIDATOR_MODULE, "read_document", return_value=(None, [failure])):
            errors, warnings, fingerprint = VALIDATOR_MODULE.validate_design_snapshot(
                Path("/tmp/2026-08-26_design.md")
            )
        self.assertEqual(errors, [failure])
        self.assertEqual(warnings, [])
        self.assertIsNone(fingerprint)

    def test_shared_and_work_package_contracts_require_confirmed_constraints(self) -> None:
        invalid_designs = (
            (
                valid_design().replace(
                    "| S-01 | 共享/状态 | 两个工作包共享同一状态定义 |",
                    "| S-01 | 共享/状态 | |",
                ),
                "empty confirmed constraint for shared contract S-01",
            ),
            (
                valid_design().replace(
                    "| WP-01-C01 | 交付边界 | WP-01/交付边界 | WP-01 的交付边界约束 |",
                    "| WP-01-C01 | 交付边界 | WP-01/交付边界 | |",
                ),
                "empty confirmed constraint for contract WP-01-C01",
            ),
        )
        for design, expected_error in invalid_designs:
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "2026-08-26_design.md"
                path.write_text(design, encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stdout)

    def test_unknown_acceptance_contract_fails(self) -> None:
        design = valid_design().replace(
            "S-01、WP-01-C01", "S-01、UNKNOWN-C01、WP-01-C01", 1
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("acceptance references unknown contract", result.stdout)

    def test_acceptance_coverage_rejects_empty_list_items(self) -> None:
        original = "S-01、WP-01-C01、WP-01-C02、WP-01-C03、WP-01-C04、WP-01-C05、WP-01-C06"
        for coverage in (f"、{original}", f"{original}、", original.replace("、", "、、", 1)):
            design = valid_design().replace(original, coverage, 1)
            with self.subTest(coverage=coverage), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "2026-08-26_design.md"
                path.write_text(design, encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("empty acceptance coverage id", result.stdout)

    def test_uncovered_contract_fails(self) -> None:
        design = valid_design().replace("、WP-02-C06", "", 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("contract lacks acceptance coverage: WP-02-C06", result.stdout)

    def test_design_metadata_must_match_map(self) -> None:
        design = valid_design().replace("> 工作包：WP-01、WP-02", "> 工作包：WP-01")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("metadata work package ids must exactly match", result.stdout)

    def test_design_metadata_rejects_empty_list_items(self) -> None:
        for metadata in ("WP-01、WP-02、", "、WP-01、WP-02", "WP-01、、WP-02"):
            design = valid_design().replace("> 工作包：WP-01、WP-02", f"> 工作包：{metadata}")
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "2026-08-26_design.md"
                path.write_text(design, encoding="utf-8")
                result = self.run_validator(path, design=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid design metadata work package id", result.stdout)

    def test_implemented_design_requires_terminal_packages(self) -> None:
        design = valid_design(state="已实现")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("implemented design contains an unfinished", result.stdout)

    def test_implemented_design_accepts_completed_and_deprecated_packages(self) -> None:
        design = valid_design(state="已实现", package_states=("已完成", "已废弃"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deprecated_design_requires_linked_replacement(self) -> None:
        design = valid_design(state="已废弃", package_states=("已废弃", "已废弃"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("linked replacement", result.stdout)

    def test_deprecated_design_with_replacement_passes(self) -> None:
        design = valid_design(
            state="已废弃", package_states=("已废弃", "已废弃"), replacement=True
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(design, encoding="utf-8")
            result = self.run_validator(path, design=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validator_does_not_modify_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-26_design.md"
            path.write_text(valid_design(), encoding="utf-8")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(self.run_validator(path, design=True).returncode, 0)
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(before, after)

    def test_complete_example_project_passes(self) -> None:
        design = EXAMPLE_ROOT / ".nova" / "design" / "2026-08-25_设备借用闭环.md"
        blueprint = EXAMPLE_ROOT / ".nova/PROJECT_BLUEPRINT.md"
        design_result = self.run_validator(design, design=True)
        blueprint_result = self.run_validator(blueprint)
        self.assertEqual(design_result.returncode, 0, design_result.stdout + design_result.stderr)
        self.assertEqual(blueprint_result.returncode, 0, blueprint_result.stdout + blueprint_result.stderr)

    def test_templates_declare_current_versions_and_required_contract_tables(self) -> None:
        blueprint = (SKILL_ROOT / "assets" / "PROJECT_BLUEPRINT.template.md").read_text(encoding="utf-8")
        design = (SKILL_ROOT / "assets" / "DESIGN.template.md").read_text(encoding="utf-8")
        self.assertIn("> 蓝图规范版本：3", blueprint)
        self.assertIn("| 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 |", blueprint)
        self.assertIn("> 设计规范版本：5", design)
        self.assertIn("> 收敛确认：待确认", design)
        self.assertIn("> 演进来源：", design)
        self.assertIn("| 契约 | 维度 | 语义键 | 唯一规则 |", design)
        self.assertEqual(set(re.findall(r"\| ([^|]+) \| <", design)) & set(DIMENSIONS), set(DIMENSIONS))


if __name__ == "__main__":
    unittest.main()
