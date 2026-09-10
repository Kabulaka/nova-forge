#!/usr/bin/env python3

from __future__ import annotations

import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_requirements.py"
EXAMPLE = ROOT / "references/examples/equipment-rental/.nova"
REVIEW_TOOL = ROOT.parent / "nova-review/scripts/nova_review.py"
REVIEW_SPEC = importlib.util.spec_from_file_location("nova_requirements_review_fixture", REVIEW_TOOL)
assert REVIEW_SPEC is not None and REVIEW_SPEC.loader is not None
NOVA_REVIEW = importlib.util.module_from_spec(REVIEW_SPEC)
sys.modules[REVIEW_SPEC.name] = NOVA_REVIEW
REVIEW_SPEC.loader.exec_module(NOVA_REVIEW)
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "nova_requirements_validator", VALIDATOR
)
assert VALIDATOR_SPEC is not None and VALIDATOR_SPEC.loader is not None
VALIDATOR_MODULE = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(VALIDATOR_MODULE)
REQ = "REQ-019a1234-5678-7abc-8def-0123456789ab"
FEAT = "FEAT-019a1234-5678-7abc-8def-0123456789ac"


class RequirementsValidatorTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def copy_example(self, temporary: str) -> Path:
        target = Path(temporary) / ".nova"
        shutil.copytree(EXAMPLE, target)
        return target

    def audited_requirements(self, temporary: str) -> Path:
        repo = Path(temporary) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Nova Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "nova@example.invalid"], check=True)
        target = repo / ".nova"
        shutil.copytree(EXAMPLE, target)
        blueprint = textwrap.dedent(
            f"""
            # Blueprint

            ## 6. 待开发功能

            | 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 | 需求引用 |
            |------|--------|------|------|----------|----------|----------|----------|
            | PEND-123 | P0 | 用户提出 | 设备借用 | [WP-01](design/2026-08-31_requirement.md#wp-01-requirement) | 无 | 完成 | {REQ}@v1 |
            """
        ).lstrip()
        (target / "PROJECT_BLUEPRINT.md").write_text(blueprint, encoding="utf-8")
        design = textwrap.dedent(
            f"""
            # Requirement implementation

            > 设计规范版本：3
            > 设计状态：已确认
            > 演进来源：无
            > Requirement-Ref：{REQ}@v1
            > 工作包：WP-01

            ## 2. 工作包地图

            | 工作包 | 状态 | 交付结果 | 前置依赖 | 设计章节 |
            |--------|------|----------|----------|----------|
            | WP-01 | 待Review | 实现需求 | 无 | [实现](#wp-01-requirement) |

            ### 2.1 工作项关闭映射

            | 工作项 | 工作包 |
            |--------|--------|
            | PEND-123 | WP-01 |

            <a id="wp-01-requirement"></a>
            ## WP-01 实现
            """
        ).lstrip()
        design_path = target / "design/2026-08-31_requirement.md"
        design_path.parent.mkdir(parents=True)
        design_path.write_text(design, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", ".nova"], check=True)
        message = textwrap.dedent(
            """
            feat: implement requirement

            Nova-Schema: 1
            Work-Item: PEND-123
            Change-Class: designed
            Design-Ref: .nova/design/2026-08-31_requirement.md#wp-01-requirement
            Review-Policy: required
            Exemption-Rule: none
            Validation: requirements fixture (pass)
            """
        ).strip() + "\n"
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
            input=message,
            text=True,
            check=True,
        )
        commit_hash = NOVA_REVIEW.run_git(repo, "rev-parse", "HEAD").strip()
        diff = NOVA_REVIEW.run_git(repo, "show", "--format=", "--binary", "--no-ext-diff", commit_hash)
        digest, scope = NOVA_REVIEW.compute_review_evidence({("main", commit_hash): diff})
        manifest = {
            "schema": 1,
            "batch_id": "NR-20260831-requirement",
            "reviewed_at": "2026-08-31T12:00:00+08:00",
            "reviewer": "review-agent",
            "conclusion": "PASS",
            "review_round": 1,
            "review_content_sha256": digest,
            "review_scope": scope,
            "items": [{
                "work_item": "PEND-123",
                "change_class": "designed",
                "commits": [commit_hash],
                "validation": "requirements fixture (pass)",
                "design_ref": ".nova/design/2026-08-31_requirement.md#wp-01-requirement",
                "blueprint": ".nova/PROJECT_BLUEPRINT.md",
                "design_file": ".nova/design/2026-08-31_requirement.md",
                "package_ids": ["WP-01"],
            }],
        }
        manifest_path = repo / "review.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        recorded = subprocess.run(
            [sys.executable, str(REVIEW_TOOL), "record-pass", "--repo", str(repo), "--manifest", str(manifest_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        subprocess.run(
            ["git", "-C", str(repo), "add", ".nova/PROJECT_BLUEPRINT.md", ".nova/PRODUCT_REQUIREMENTS.md", ".nova/design", ".nova/audit"],
            check=True,
        )
        manifest_digest = NOVA_REVIEW.hashlib.sha256(NOVA_REVIEW.canonical_manifest(manifest)).hexdigest()
        audit_message = textwrap.dedent(
            f"""
            audit: record requirement Review

            Nova-Audit-Schema: 1
            Review-Batch: NR-20260831-requirement
            Manifest-SHA256: {manifest_digest}
            Validation: nova-review audit validation (pass)
            """
        ).strip() + "\n"
        staged = NOVA_REVIEW.run_git(repo, "diff", "--cached", "--binary", "--no-ext-diff")
        _, errors = NOVA_REVIEW.validate_audit_message(repo, audit_message, staged)
        self.assertEqual(errors, [])
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
            input=audit_message,
            text=True,
            check=True,
        )
        return target

    def test_complete_example_passes(self) -> None:
        result = self.run_validator("--index", str(EXAMPLE / "PRODUCT_REQUIREMENTS.md"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_pending_review_transaction_fails_requirement_reads_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            nova_root = self.audited_requirements(temporary)
            NOVA_REVIEW._transaction_state_directory(nova_root.parent).mkdir()
            result = self.run_validator(
                "--index", str(nova_root / "PRODUCT_REQUIREMENTS.md")
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unfinished Nova Review transaction", result.stdout)

    def test_block_passes_independently(self) -> None:
        block = next((EXAMPLE / "requirements").glob("REQ-*.md"))
        result = self.run_validator("--block", str(block))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_inconsistent_implemented_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_example(temporary)
            text = (EXAMPLE / "PRODUCT_REQUIREMENTS.md").read_text(encoding="utf-8")
            text = text.replace("| v1 | 待实现 |", "| v1 | 已实现 |")
            (target / "PRODUCT_REQUIREMENTS.md").write_text(text, encoding="utf-8")
            result = self.run_validator("--index", str(target / "PRODUCT_REQUIREMENTS.md"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("已实现 requires", result.stdout)

    def test_development_state_without_previous_implementation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_example(temporary)
            product = target / "PRODUCT_REQUIREMENTS.md"
            product.write_text(
                product.read_text(encoding="utf-8").replace(
                    "| v1 | 待实现 |", "| v1 | 开发中 |"
                ),
                encoding="utf-8",
            )
            result = self.run_validator("--index", str(product))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_development_state_rejects_unpaired_or_current_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_example(temporary)
            product = target / "PRODUCT_REQUIREMENTS.md"
            text = product.read_text(encoding="utf-8").replace(
                "| v1 | 待实现 |", "| v1 | 开发中 |"
            ).replace("| 无 | 无 |", "| v1 | 无 |")
            product.write_text(text, encoding="utf-8")
            result = self.run_validator("--index", str(product))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("开发中 requires", result.stdout)

    def test_development_state_may_retain_trusted_previous_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.audited_requirements(temporary)
            block = next((target / "requirements").glob("REQ-*.md"))
            block.write_text(
                block.read_text(encoding="utf-8").replace(
                    "> 需求版本：v1", "> 需求版本：v2"
                ),
                encoding="utf-8",
            )
            product = target / "PRODUCT_REQUIREMENTS.md"
            product.write_text(
                product.read_text(encoding="utf-8").replace(
                    f"| {REQ} | v1 | 已实现 |", f"| {REQ} | v2 | 开发中 |"
                ),
                encoding="utf-8",
            )
            result = self.run_validator("--index", str(product))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_implemented_state_requires_trusted_review_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_example(temporary)
            product = target / "PRODUCT_REQUIREMENTS.md"
            text = product.read_text(encoding="utf-8").replace(
                "| v1 | 待实现 | 借用管理 |", "| v1 | 已实现 | 借用管理 |"
            ).replace("| 无 | 无 |", "| v1 | PEND-123 |")
            product.write_text(text, encoding="utf-8")
            failed = self.run_validator("--index", str(product))
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("not a trusted Review PASS", failed.stdout)
        with tempfile.TemporaryDirectory() as temporary:
            target = self.audited_requirements(temporary)
            passed = self.run_validator("--index", str(target / "PRODUCT_REQUIREMENTS.md"))
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

    def test_schema_2_feature_and_historical_pend_are_valid_evidence_identities(self) -> None:
        self.assertEqual(VALIDATOR_MODULE.implementation_evidence(FEAT), [FEAT])
        self.assertEqual(
            VALIDATOR_MODULE.implementation_evidence(f"{FEAT}、PEND-123"),
            [FEAT, "PEND-123"],
        )
        self.assertIsNone(VALIDATOR_MODULE.implementation_evidence("PATCH-123"))

    def test_trusted_review_pass_matches_feature_and_historical_classes(self) -> None:
        design = f"> Requirement-Ref：{REQ}@v1\n".encode()

        def completed(change_class: str) -> tuple[dict[str, object], dict[str, object]]:
            return (
                {
                    "change_class": change_class,
                    "design_ref": ".nova/design/example.md#wp-01-example",
                    "commits": [{"repository": "main", "commit": "a" * 40}],
                },
                {},
            )

        fake_review = SimpleNamespace(
            NovaError=RuntimeError,
            load_completed_item=mock.Mock(return_value=completed("feature")),
            run_git_bytes=mock.Mock(return_value=design),
        )
        with (
            mock.patch.object(
                VALIDATOR_MODULE, "nova_review_module", return_value=fake_review
            ),
            mock.patch.object(
                VALIDATOR_MODULE, "git_repo_for_nova", return_value=Path("/repo")
            ),
        ):
            self.assertTrue(
                VALIDATOR_MODULE.trusted_review_pass(
                    Path("/repo/.nova"), FEAT, REQ, "v1"
                )
            )
            fake_review.load_completed_item.return_value = completed("designed")
            self.assertFalse(
                VALIDATOR_MODULE.trusted_review_pass(
                    Path("/repo/.nova"), FEAT, REQ, "v1"
                )
            )
            self.assertTrue(
                VALIDATOR_MODULE.trusted_review_pass(
                    Path("/repo/.nova"), "PEND-123", REQ, "v1"
                )
            )

    def test_unrelated_or_forged_pass_does_not_implement_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_example(temporary)
            product = target / "PRODUCT_REQUIREMENTS.md"
            text = product.read_text(encoding="utf-8").replace(
                "| v1 | 待实现 | 借用管理 |", "| v1 | 已实现 | 借用管理 |"
            ).replace("| 无 | 无 |", "| v1 | PEND-123 |")
            product.write_text(text, encoding="utf-8")
            fake_index = target / "audit/index/aa/PEND-123.json"
            fake_review = target / "audit/reviews/2026/08/NR-fake.yaml"
            fake_index.parent.mkdir(parents=True)
            fake_review.parent.mkdir(parents=True)
            fake_index.write_text(json.dumps({"schema": 1, "work_item": "PEND-123"}), encoding="utf-8")
            fake_review.write_text(json.dumps({"schema": 1, "conclusion": "PASS"}), encoding="utf-8")
            result = self.run_validator("--index", str(product))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a trusted Review PASS", result.stdout)

    def test_unknown_module_and_empty_cell_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_example(temporary)
            product = target / "PRODUCT_REQUIREMENTS.md"
            text = product.read_text(encoding="utf-8").replace("| 借用管理 | [设备借用闭环]", "| 不存在模块 | [设备借用闭环]")
            text = text.replace("| 设备管理员与借用人 |", "|  |", 1)
            product.write_text(text, encoding="utf-8")
            result = self.run_validator("--index", str(product))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown business module", result.stdout)
            self.assertIn("empty table cell", result.stdout)

    def test_rule_coverage_uses_exact_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_example(temporary)
            block = next((target / "requirements").glob("REQ-*.md"))
            text = block.read_text(encoding="utf-8").replace("R-01、R-02", "R-010、R-02")
            block.write_text(text, encoding="utf-8")
            result = self.run_validator("--block", str(block))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lacks acceptance coverage: R-01", result.stdout)
            self.assertIn("unknown business rule: R-010", result.stdout)


if __name__ == "__main__":
    unittest.main()
