#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_requirements.py"
EXAMPLE = ROOT / "references/examples/equipment-rental/.nova"


class RequirementsValidatorTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(VALIDATOR), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def copy_example(self, temporary: str) -> Path:
        target = Path(temporary) / ".nova"
        shutil.copytree(EXAMPLE, target)
        return target

    def write_review_pass(self, target: Path, work_item: str = "PEND-123") -> None:
        index = target / f"audit/index/aa/{work_item}.json"
        review = target / "audit/reviews/2026/08/NR-test.json"
        index.parent.mkdir(parents=True)
        review.parent.mkdir(parents=True)
        index.write_text(json.dumps({
            "schema": 1,
            "work_item": work_item,
            "feature_year": 2026,
            "review_batch": "NR-test",
            "review_path": ".nova/audit/reviews/2026/08/NR-test.json",
        }), encoding="utf-8")
        review.write_text(json.dumps({
            "schema": 1,
            "batch_id": "NR-test",
            "conclusion": "PASS",
            "items": [{"work_item": work_item}],
        }), encoding="utf-8")

    def test_complete_example_passes(self) -> None:
        result = self.run_validator("--index", str(EXAMPLE / "PRODUCT_REQUIREMENTS.md"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

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
            self.write_review_pass(target)
            passed = self.run_validator("--index", str(product))
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

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
