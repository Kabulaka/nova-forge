#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_architecture.py"
EXAMPLE_NOVA = ROOT / "references/examples/order-platform/.nova"
REVIEW_TOOL = ROOT.parent / "nova-review/scripts/nova_review.py"
REVIEW_SPEC = importlib.util.spec_from_file_location("nova_architecture_review_fixture", REVIEW_TOOL)
assert REVIEW_SPEC is not None and REVIEW_SPEC.loader is not None
NOVA_REVIEW = importlib.util.module_from_spec(REVIEW_SPEC)
sys.modules[REVIEW_SPEC.name] = NOVA_REVIEW
REVIEW_SPEC.loader.exec_module(NOVA_REVIEW)


class ArchitectureValidatorTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["python3", str(VALIDATOR), *args], text=True, capture_output=True, check=False)

    def audited_example(self, temporary: str) -> Path:
        repo = Path(temporary) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Nova Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "nova@example.invalid"], check=True)
        target = repo / ".nova"
        shutil.copytree(EXAMPLE_NOVA, target)
        architecture = target / "architecture/ARCHITECTURE_CONTRACTS.md"
        architecture.write_text(
            architecture.read_text(encoding="utf-8").replace("待Review", "已通过"),
            encoding="utf-8",
        )
        blueprint = (target / "PROJECT_BLUEPRINT.md").read_text(encoding="utf-8")
        blueprint = blueprint.replace(
            "|------|--------|------|------|----------|----------|----------|----------|",
            "|------|--------|------|------|----------|----------|----------|----------|\n"
            "| PEND-100 | P0 | 用户提出 | 架构冻结 | [WP-01](design/2026-08-31_architecture.md#wp-01-architecture) | 无 | 契约通过 Review | 无 |",
        )
        (target / "PROJECT_BLUEPRINT.md").write_text(blueprint, encoding="utf-8")
        design = textwrap.dedent(
            """
            # 架构冻结设计

            > 设计规范版本：3
            > 设计状态：已确认
            > 演进来源：无
            > 工作包：WP-01

            ## 2. 工作包地图

            | 工作包 | 状态 | 交付结果 | 前置依赖 | 设计章节 |
            |--------|------|----------|----------|----------|
            | WP-01 | 待Review | 冻结共享架构契约 | 无 | [架构冻结](#wp-01-architecture) |

            ### 2.1 工作项关闭映射

            | 工作项 | 工作包 |
            |--------|--------|
            | PEND-100 | WP-01 |

            <a id="wp-01-architecture"></a>
            ## WP-01 架构冻结
            """
        ).lstrip()
        design_path = target / "design/2026-08-31_architecture.md"
        design_path.parent.mkdir(parents=True)
        design_path.write_text(design, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", ".nova"], check=True)
        commit_message = textwrap.dedent(
            """
            feat: freeze architecture

            Nova-Schema: 1
            Work-Item: PEND-100
            Change-Class: designed
            Design-Ref: .nova/design/2026-08-31_architecture.md#wp-01-architecture
            Review-Policy: required
            Exemption-Rule: none
            Validation: architecture fixture (pass)
            """
        ).strip() + "\n"
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
            input=commit_message,
            text=True,
            check=True,
        )
        commit_hash = NOVA_REVIEW.run_git(repo, "rev-parse", "HEAD").strip()
        reviewed_diff = NOVA_REVIEW.run_git(
            repo, "show", "--format=", "--binary", "--no-ext-diff", commit_hash
        )
        digest, scope = NOVA_REVIEW.compute_review_evidence({("main", commit_hash): reviewed_diff})
        manifest = {
            "schema": 1,
            "batch_id": "NR-20260831-architecture",
            "reviewed_at": "2026-08-31T12:00:00+08:00",
            "reviewer": "review-agent",
            "conclusion": "PASS",
            "review_round": 1,
            "review_content_sha256": digest,
            "review_scope": scope,
            "items": [{
                "work_item": "PEND-100",
                "change_class": "designed",
                "commits": [commit_hash],
                "validation": "architecture fixture (pass)",
                "design_ref": ".nova/design/2026-08-31_architecture.md#wp-01-architecture",
                "blueprint": ".nova/PROJECT_BLUEPRINT.md",
                "design_file": ".nova/design/2026-08-31_architecture.md",
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
            ["git", "-C", str(repo), "add", ".nova/PROJECT_BLUEPRINT.md", ".nova/design", ".nova/audit"],
            check=True,
        )
        manifest_digest = NOVA_REVIEW.hashlib.sha256(
            NOVA_REVIEW.canonical_manifest(manifest)
        ).hexdigest()
        audit_message = textwrap.dedent(
            f"""
            audit: record architecture Review

            Nova-Audit-Schema: 1
            Review-Batch: NR-20260831-architecture
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
        return architecture

    def test_complete_parallel_example_is_structurally_valid(self) -> None:
        path = EXAMPLE_NOVA / "architecture/ARCHITECTURE_CONTRACTS.md"
        result = self.run_validator(str(path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pending_document_becomes_ready_from_immutable_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.audited_example(temporary)
            result = self.run_validator("--ready", str(path))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_review_evidence_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.audited_example(temporary)
            path.write_text(path.read_text(encoding="utf-8").replace("PEND-100", "无", 1), encoding="utf-8")
            result = self.run_validator("--ready", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Review evidence", result.stdout)

    def test_unindexed_architecture_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            extra = target / "architecture/data/extra.md"
            extra.write_text("extra", encoding="utf-8")
            result = self.run_validator(str(target / "architecture/ARCHITECTURE_CONTRACTS.md"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not indexed", result.stdout)

    def test_needed_gate_requires_matching_indexed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            path = target / "architecture/ARCHITECTURE_CONTRACTS.md"
            text = path.read_text(encoding="utf-8")
            text = "\n".join(line for line in text.splitlines() if "[订单响应夹具]" not in line) + "\n"
            path.write_text(text, encoding="utf-8")
            result = self.run_validator("--ready", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("needed gate has no indexed contract: Mock", result.stdout)

    def test_forged_review_evidence_and_state_conflict_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.audited_example(temporary)
            text = path.read_text(encoding="utf-8").replace("PEND-100", "PEND-999")
            text = text.replace("[OpenAPI](api/openapi.yaml) | 已通过", "[OpenAPI](api/openapi.yaml) | 待Review")
            path.write_text(text, encoding="utf-8")
            result = self.run_validator("--ready", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a trusted PASS", result.stdout)
            self.assertIn("gate state conflicts", result.stdout)

    def test_invalid_openapi_and_mock_contract_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            api = target / "architecture/api/openapi.yaml"
            api.write_text(api.read_text(encoding="utf-8").replace("openapi:", "swagger:"), encoding="utf-8")
            mock = target / "architecture/mocks/order-created.json"
            mock.write_text('{"payload": {}}\n', encoding="utf-8")
            result = self.run_validator(str(target / "architecture/ARCHITECTURE_CONTRACTS.md"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported OpenAPI", result.stdout)
            self.assertIn("_contract and _contractVersion", result.stdout)

    def test_invalid_versions_and_unindexed_foundation_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            api = target / "architecture/api/openapi.yaml"
            api.write_text(
                api.read_text(encoding="utf-8").replace("openapi: 3.1.0", "openapi: garbage"),
                encoding="utf-8",
            )
            mock = target / "architecture/mocks/order-created.json"
            mock.write_text(
                mock.read_text(encoding="utf-8").replace('"_contractVersion": "1.0.0"', '"_contractVersion": "9.9.9"'),
                encoding="utf-8",
            )
            (target / "architecture/foundation/unindexed.md").write_text("extra\n", encoding="utf-8")
            result = self.run_validator(str(target / "architecture/ARCHITECTURE_CONTRACTS.md"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported OpenAPI", result.stdout)
            self.assertIn("Mock contract version mismatch", result.stdout)
            self.assertIn("foundation/unindexed.md", result.stdout)

    def test_contract_change_after_pass_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.audited_example(temporary)
            api = path.parent / "api/openapi.yaml"
            api.write_text(api.read_text(encoding="utf-8") + "\n# changed after PASS\n", encoding="utf-8")
            result = self.run_validator("--ready", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a trusted PASS covering current contracts", result.stdout)

    def test_invalid_asyncapi_and_incomplete_foundation_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            index = target / "architecture/ARCHITECTURE_CONTRACTS.md"
            text = index.read_text(encoding="utf-8").replace(
                "| 事件契约 | 否 | 不适用 | 无 |", "| 事件契约 | 是 | 已通过 | PEND-100 |"
            ).replace(
                "| Mock | 订单 API |",
                "| 事件 | 订单 | [订单事件](events/order.yaml) | 已通过 | 订单模块 |\n| Mock | 订单 API |",
            )
            index.write_text(text, encoding="utf-8")
            event = target / "architecture/events/order.yaml"
            event.parent.mkdir()
            event.write_text("name: not-asyncapi\n", encoding="utf-8")
            foundation = target / "architecture/foundation/project-skeleton.md"
            foundation.write_text(
                foundation.read_text(encoding="utf-8").replace("| Python 3.13 | FastAPI |", "| Python 3.13 |  |"),
                encoding="utf-8",
            )
            result = self.run_validator("--ready", str(index))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported AsyncAPI", result.stdout)
            self.assertIn("empty table cell in 技术与运行", result.stdout)


if __name__ == "__main__":
    unittest.main()
