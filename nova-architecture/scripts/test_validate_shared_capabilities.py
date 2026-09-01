#!/usr/bin/env python3
"""Tests for validate_shared_capabilities.py."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


VALIDATOR = Path(__file__).with_name("validate_shared_capabilities.py")


class SharedCapabilityValidatorTests(unittest.TestCase):
    def make_repo(self, body: str | None = None) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / ".nova").mkdir()
        (root / "src/shared").mkdir(parents=True)
        (root / "src/shared/database.py").write_text("# shared database\n", encoding="utf-8")
        catalog = root / ".nova/SHARED_CAPABILITIES.md"
        catalog.write_text(body or self.valid_catalog(), encoding="utf-8")
        return temp, catalog

    @staticmethod
    def valid_catalog() -> str:
        return textwrap.dedent(
            """\
            # Example — 共享能力目录

            > 共享能力目录版本：1
            > 目录定位：仅登记已实现且通过最低验收的共享能力。

            ## 1. 已实现能力

            | 类型 | 能力 | 说明 | 代码位置 | 复用边界 |
            |------|------|------|----------|----------|
            | 数据访问 | SQLite 基础设施 | 统一连接和事务 | `src/shared/database.py` | 模块 Repository 复用，不包含业务查询 |
            """
        )

    def run_validator(self, catalog: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(catalog)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_accepts_implemented_capability_with_existing_repo_path(self) -> None:
        temp, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: shared capability catalog is valid", result.stdout)

    def test_rejects_missing_code_location(self) -> None:
        temp, catalog = self.make_repo(
            self.valid_catalog().replace("src/shared/database.py", "src/shared/missing.py")
        )
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("code location does not exist", result.stdout)

    def test_rejects_duplicate_capability_names(self) -> None:
        body = self.valid_catalog() + (
            "| 后端能力 | SQLite 基础设施 | 另一说明 | `src/shared/database.py` | 另一边界 |\n"
        )
        temp, catalog = self.make_repo(body)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate shared capability", result.stdout)

    def test_rejects_escape_and_governance_paths(self) -> None:
        for location in ("../outside.py", ".nova/PROJECT_BLUEPRINT.md", "."):
            with self.subTest(location=location):
                temp, catalog = self.make_repo(
                    self.valid_catalog().replace("src/shared/database.py", location)
                )
                self.addCleanup(temp.cleanup)
                result = self.run_validator(catalog)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid shared capability code location", result.stdout)

    def test_rejects_placeholders_and_empty_catalog(self) -> None:
        placeholder = self.valid_catalog().replace("SQLite 基础设施", "<能力>")
        temp, catalog = self.make_repo(placeholder)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains placeholders", result.stdout)

        empty = self.valid_catalog().split("| 数据访问", 1)[0]
        temp2, catalog2 = self.make_repo(empty)
        self.addCleanup(temp2.cleanup)
        result2 = self.run_validator(catalog2)
        self.assertNotEqual(result2.returncode, 0)
        self.assertIn("at least one implemented capability", result2.stdout)

    def test_rejects_noncanonical_catalog_path(self) -> None:
        temp, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        other = catalog.parent / "CAPABILITIES.md"
        catalog.rename(other)
        result = self.run_validator(other)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path must be .nova/SHARED_CAPABILITIES.md", result.stdout)


if __name__ == "__main__":
    unittest.main()
